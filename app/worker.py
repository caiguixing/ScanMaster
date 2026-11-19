"""后台工作线程：识别任务放到 QThread 避免卡死 UI。

重要：Worker 只做「识别」产出 ScanResult，不写文件。
主线程弹出预览对话框，用户确认后才调用 export_result 写文件。
"""
import os
import traceback
from typing import List

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

from .scanner import DocumentScanner, to_pil
from .ocr_engine import OcrEngine
from .table_ocr import build_table, table_to_lines
from .result import ScanResult, ScanItem
from . import exporters

# 支持的图片后缀
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


class Worker(QThread):
    """识别线程：task 支持 scan / ocr / image_to_word / pdf_to_word / to_excel。"""

    progress = Signal(int, str)          # 百分比, 描述
    finished_ok = Signal(str, object)    # 任务名, ScanResult
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
            handler = getattr(self, f"_task_{self.task}", None)
            if handler is None:
                raise ValueError(f"未知任务类型: {self.task}")
            result = handler()
            self.finished_ok.emit(self.task, result)
        except Exception as exc:
            self.failed.emit(f"{exc}\n{traceback.format_exc()}")

    # ---------- 识别任务（只识别，不导出） ----------
    def _recognize_image(self, path: str, need_table: bool = True) -> ScanItem:
        """识别单张图片：扫描矫正 + OCR（+ 表格结构）。"""
        item = ScanItem(os.path.basename(path), path)
        img = self._read(path)
        # OCR 用紧凑表格区域（full_page=False），表格线清晰、行数准确
        gray_scanned = self.scanner.scan(img, enhance=False, full_page=False)
        # 扫描预览/导出用整张纸 A4（full_page=True），保留页眉页脚
        item.scanned = self.scanner.scan(img, enhance=True, full_page=True)
        lines = self.ocr.recognize(gray_scanned)
        if need_table:
            gray = cv2.cvtColor(gray_scanned, cv2.COLOR_BGR2GRAY)
            # 传 OcrEngine 实例（含 recognize_cell 多 preprocessing 融合）
            table, detected = build_table(gray, lines, ocr_engine=self.ocr)
            item.table = table
            item.table_detected = detected
            item.lines = table_to_lines(table) if detected else lines
        else:
            item.lines = lines
        return item

    def _task_scan(self):
        result = ScanResult("scan")
        total = len(self.files)
        for i, path in enumerate(self.files):
            self._emit(int(i / total * 100), f"扫描矫正: {os.path.basename(path)}")
            item = ScanItem(os.path.basename(path), path)
            img = self._read(path)
            item.scanned = self.scanner.scan(img, enhance=True)
            result.items.append(item)
        self._emit(100, f"扫描完成，共 {len(result.items)} 张")
        return result

    def _task_ocr(self):
        result = ScanResult("ocr")
        total = len(self.files)
        for i, path in enumerate(self.files):
            self._emit(int(i / total * 100), f"识别文字: {os.path.basename(path)}")
            result.items.append(self._recognize_image(path, need_table=True))
        self._emit(100, "文字识别完成")
        return result

    def _task_image_to_word(self):
        result = ScanResult("image_to_word")
        total = len(self.files)
        for i, path in enumerate(self.files):
            self._emit(int(i / total * 100), f"图片转 Word: {os.path.basename(path)}")
            result.items.append(self._recognize_image(path, need_table=True))
        self._emit(100, "识别完成，请预览确认")
        return result

    def _task_to_excel(self):
        result = ScanResult("to_excel")
        total = len(self.files)
        for i, path in enumerate(self.files):
            self._emit(int(i / total * 100), f"表格识别: {os.path.basename(path)}")
            result.items.append(self._recognize_image(path, need_table=True))
        self._emit(100, "表格识别完成，请预览确认")
        return result

    def _task_pdf_to_word(self):
        import fitz
        result = ScanResult("pdf_to_word")
        total = len(self.files)
        for i, path in enumerate(self.files):
            self._emit(5, f"打开 PDF: {os.path.basename(path)}")
            doc = fitz.open(path)
            item = ScanItem(os.path.basename(path), path)
            page_total = len(doc)
            for pno in range(page_total):
                self._emit(
                    5 + int((i + pno / max(page_total, 1)) / total * 90),
                    f"识别第 {pno + 1}/{page_total} 页",
                )
                page = doc.load_page(pno)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                img = cv2.imdecode(np.frombuffer(pix.tobytes("png"), np.uint8),
                                   cv2.IMREAD_COLOR)
                item.pdf_pages.append(self.ocr.recognize(img))
            doc.close()
            result.items.append(item)
        self._emit(100, "PDF 识别完成，请预览确认")
        return result

    @staticmethod
    def _read(path: str):
        data = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"无法读取图片: {path}")
        return img


def export_result(result: ScanResult, out_dir: str) -> List[str]:
    """把识别结果导出为文件（用户确认预览后调用）。返回输出文件路径列表。"""
    os.makedirs(out_dir, exist_ok=True)
    task = result.task
    saved = []

    if task == "scan":
        for item in result.items:
            out = os.path.join(out_dir,
                               os.path.splitext(item.name)[0] + "_扫描.png")
            to_pil(item.scanned).save(out)
            saved.append(out)

    elif task == "ocr":
        all_text = "\n\n".join(
            f"===== {item.name} =====\n" +
            "\n".join(l["text"] for l in item.lines)
            for item in result.items
        )
        out = os.path.join(out_dir, "识别文字.txt")
        with open(out, "w", encoding="utf-8") as f:
            f.write(all_text)
        saved.append(out)

    elif task == "image_to_word":
        for item in result.items:
            scan_path = os.path.join(out_dir,
                                     os.path.splitext(item.name)[0] + "_扫描.png")
            if item.scanned is not None:
                to_pil(item.scanned).save(scan_path)
            else:
                scan_path = None
            out = os.path.join(out_dir,
                               os.path.splitext(item.name)[0] + ".docx")
            exporters.export_docx(item.lines, out, image_path=scan_path)
            saved.append(out)

    elif task == "to_excel":
        for item in result.items:
            out = os.path.join(out_dir,
                               os.path.splitext(item.name)[0] + ".xlsx")
            if item.table:
                exporters.export_table_xlsx(
                    item.table, out,
                    f"{'表格' if item.table_detected else '文字'}_识别结果",
                )
            else:
                exporters.export_xlsx(item.lines, out)
            saved.append(out)

    elif task == "pdf_to_word":
        for item in result.items:
            out = os.path.join(out_dir,
                               os.path.splitext(item.name)[0] + ".docx")
            exporters.export_docx_pages(item.pdf_pages, out)
            saved.append(out)

    return saved
