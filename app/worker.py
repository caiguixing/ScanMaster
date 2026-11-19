"""后台工作线程：把耗时任务（扫描/OCR/导出）放到 QThread，避免卡死 UI。"""
import os
import traceback
from typing import List

import cv2
from PySide6.QtCore import QThread, Signal

from .scanner import DocumentScanner, to_pil
from .ocr_engine import OcrEngine
from .table_ocr import build_table, table_to_lines
from . import exporters

# 支持的图片后缀
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


class Worker(QThread):
    """通用任务线程。task 支持:
    scan / ocr / image_to_word / pdf_to_word / to_excel
    """

    progress = Signal(int, str)          # 百分比, 描述
    finished_ok = Signal(str, object)    # 任务名, 结果数据
    failed = Signal(str)                 # 错误信息

    def __init__(self, task: str, files: List[str], out_dir: str, parent=None):
        super().__init__(parent)
        self.task = task
        self.files = files
        self.out_dir = out_dir
        self.scanner = DocumentScanner()
        self.ocr = OcrEngine()

    def _emit(self, pct: int, msg: str):
        self.progress.emit(pct, msg)

    def run(self):
        try:
            os.makedirs(self.out_dir, exist_ok=True)
            handler = getattr(self, f"_task_{self.task}", None)
            if handler is None:
                raise ValueError(f"未知任务类型: {self.task}")
            result = handler()
            self.finished_ok.emit(self.task, result)
        except Exception as exc:
            self.failed.emit(f"{exc}\n{traceback.format_exc()}")

    # ---------- 各任务实现 ----------
    def _task_scan(self):
        """仅扫描矫正，保存矫正后的图片，返回输出路径列表。"""
        saved = []
        total = len(self.files)
        for i, path in enumerate(self.files):
            self._emit(int(i / total * 100), f"扫描矫正: {os.path.basename(path)}")
            img = self._read(path)
            scanned = self.scanner.scan(img)
            name = os.path.splitext(os.path.basename(path))[0] + "_扫描.png"
            out = os.path.join(self.out_dir, name)
            to_pil(scanned).save(out)
            saved.append(out)
        self._emit(100, f"完成，共矫正 {len(saved)} 张")
        return saved

    def _recognize_structured(self, img):
        """矫正 + OCR + 表格结构识别。返回 (scanned, table, detected, lines)。

        lines 用表格行优先顺序重排，保证 TXT/Word 中文字按表格阅读顺序排列。
        """
        import cv2
        scanned = self.scanner.scan(img, enhance=False)
        lines = self.ocr.recognize(scanned)
        gray = cv2.cvtColor(scanned, cv2.COLOR_BGR2GRAY)
        # 传入 OCR 引擎启用按列识别（避免相邻列文字粘连）
        table, detected = build_table(gray, lines,
                                      ocr_engine=self.ocr._get_engine())
        ordered_lines = table_to_lines(table) if detected else lines
        return scanned, table, detected, ordered_lines

    def _task_ocr(self):
        """OCR 识别，返回 [(文件名, lines), ...]（表格按行优先顺序）。"""
        results = []
        total = len(self.files)
        for i, path in enumerate(self.files):
            self._emit(int(i / total * 100), f"识别文字: {os.path.basename(path)}")
            img = self._read(path)
            _scanned, _table, _detected, lines = self._recognize_structured(img)
            results.append((os.path.basename(path), lines))
        self._emit(100, "文字识别完成")
        return results

    def _task_image_to_word(self):
        """图片 -> Word（原图 + 识别文字），返回输出路径列表。"""
        saved = []
        total = len(self.files)
        for i, path in enumerate(self.files):
            self._emit(int(i / total * 100), f"图片转 Word: {os.path.basename(path)}")
            img = self._read(path)
            scanned, _table, _detected, lines = self._recognize_structured(img)
            scan_path = os.path.join(
                self.out_dir,
                os.path.splitext(os.path.basename(path))[0] + "_扫描.png",
            )
            to_pil(scanned).save(scan_path)
            out = os.path.join(
                self.out_dir,
                os.path.splitext(os.path.basename(path))[0] + ".docx",
            )
            exporters.export_docx(lines, out, image_path=scan_path)
            saved.append(out)
        self._emit(100, f"Word 导出完成，共 {len(saved)} 个文件")
        return saved

    def _task_pdf_to_word(self):
        """PDF 逐页渲染 -> OCR -> 汇总 Word，返回输出路径列表。"""
        import fitz  # PyMuPDF
        saved = []
        total = len(self.files)
        for i, path in enumerate(self.files):
            self._emit(5, f"打开 PDF: {os.path.basename(path)}")
            doc = fitz.open(path)
            pages = []
            page_total = len(doc)
            for pno in range(page_total):
                self._emit(
                    5 + int((i + pno / max(page_total, 1)) / total * 90),
                    f"识别第 {pno + 1}/{page_total} 页",
                )
                page = doc.load_page(pno)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                img_bytes = pix.tobytes("png")
                import numpy as np
                img = cv2.imdecode(np.frombuffer(img_bytes, dtype=np.uint8),
                                   cv2.IMREAD_COLOR)
                lines = self.ocr.recognize(img)
                pages.append(lines)
            doc.close()
            out = os.path.join(
                self.out_dir,
                os.path.splitext(os.path.basename(path))[0] + ".docx",
            )
            exporters.export_docx_pages(pages, out)
            saved.append(out)
        self._emit(100, f"PDF 转 Word 完成，共 {len(saved)} 个文件")
        return saved

    def _task_to_excel(self):
        """OCR -> 结构化表格 Excel，返回输出路径列表。"""
        import cv2
        saved = []
        total = len(self.files)
        for i, path in enumerate(self.files):
            self._emit(int(i / total * 100), f"表格识别: {os.path.basename(path)}")
            img = self._read(path)
            scanned = self.scanner.scan(img, enhance=False)
            lines = self.ocr.recognize(scanned)
            gray = cv2.cvtColor(scanned, cv2.COLOR_BGR2GRAY)
            table, detected = build_table(gray, lines,
                                          ocr_engine=self.ocr._get_engine())
            out = os.path.join(
                self.out_dir,
                os.path.splitext(os.path.basename(path))[0] + ".xlsx",
            )
            exporters.export_table_xlsx(table, out)
            self._emit(100, f"已导出 {os.path.basename(out)}"
                       f"（{'检测到表格线' if detected else '退化模式'}）")
            saved.append(out)
        self._emit(100, f"Excel 导出完成，共 {len(saved)} 个文件")
        return saved

    @staticmethod
    def _read(path: str):
        """读取图片（兼容中文路径）。"""
        import numpy as np
        data = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"无法读取图片: {path}")
        return img
