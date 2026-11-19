"""预览确认对话框：导出前展示扫描图与识别结果，用户确认后才写文件。"""
from typing import List

import cv2

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage, QFont
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QScrollArea,
    QSplitter, QMessageBox,
)

from .result import ScanResult, ScanItem
from .scanner import to_pil

TASK_TITLES = {
    "scan": "文档扫描矫正 — 预览确认",
    "ocr": "提取文字 — 预览确认",
    "image_to_word": "图片转 Word — 预览确认",
    "pdf_to_word": "PDF 转 Word — 预览确认",
    "to_excel": "表格转 Excel — 预览确认",
}


def _np_to_pixmap(bgr) -> QPixmap:
    """OpenCV BGR 数组 -> QPixmap。

    关键：QImage 的 (data, w, h) 构造不会拷贝外部缓冲。若直接传
    bytes/numpy.data，缓冲被回收后会产生悬空指针，导致大图预览时
    access violation 崩溃（小图因内存未覆写而侥幸不崩）。
    因此这里用 qimg.copy() 做深拷贝，让 QImage 拥有独立像素数据。
    """
    import numpy as np
    if bgr is None:
        return QPixmap()
    # 统一转成连续 BGR numpy 数组
    arr = bgr
    if not isinstance(arr, np.ndarray):
        arr = np.array(to_pil(arr).convert("RGB"))[:, :, ::-1].copy()
    if arr.ndim == 2:  # 灰度
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    # BGR -> RGB，copy() 深拷贝保证 QImage 独立持有像素数据
    rgb = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
    qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


class PreviewDialog(QDialog):
    """识别结果预览。confirm() 返回 True 表示用户确认导出。"""

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        self.tip = QLabel("请预览结果；截取不完整可点每个文件左侧的"
                          "「手工调整裁剪」拖动四角重新框选，确认无误再导出。")
        self.tip.setStyleSheet("color:#c2410c; font-weight:bold; padding:4px;")
        self.tip.setWordWrap(True)
        root.addWidget(self.tip)

        tabs = QTabWidget()
        for item in self.result.items:
            tabs.addTab(self._make_item_widget(item), item.name)
        root.addWidget(tabs, 1)

        # 底部按钮
        btn_box = QHBoxLayout()
        btn_box.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)
        btn_ok = QPushButton("确认导出")
        btn_ok.setStyleSheet(
            "QPushButton{background:#17a673;color:white;padding:9px 20px;"
            "border-radius:5px;font-weight:bold;font-size:13px;}"
        )
        btn_ok.clicked.connect(self._on_confirm)
        btn_box.addWidget(btn_ok)
        root.addLayout(btn_box)

    def __init__(self, result: ScanResult, parent=None):
        super().__init__(parent)
        self.result = result
        self.confirmed = False
        self._image_labels = {}   # item -> (label, size_label) 供刷新
        self._table_widgets = {}  # id(item) -> QTableWidget，供确认时读回编辑
        self._text_widgets = {}   # id(item) -> QTextEdit，供确认时读回编辑
        self.setWindowTitle(TASK_TITLES.get(result.task, "预览确认"))
        self.resize(1100, 780)
        self._build_ui()

    def _make_item_widget(self, item: ScanItem) -> QWidget:
        """单个文件的预览页：左侧扫描图 + 右侧识别内容。"""
        widget = QWidget()
        layout = QHBoxLayout(widget)

        splitter = QSplitter(Qt.Horizontal)
        # 左侧：扫描图（可滚动缩放）
        image_pane = self._make_image_pane(item)
        splitter.addWidget(image_pane)
        # 右侧：识别内容（表格或文字）
        content_pane = self._make_content_pane(item)
        splitter.addWidget(content_pane)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)
        return widget

    def _make_image_pane(self, item: ScanItem) -> QWidget:
        pane = QWidget()
        vbox = QVBoxLayout(pane)
        header = QHBoxLayout()
        header.addWidget(QLabel("扫描图预览："))
        header.addStretch(1)
        btn_adjust = QPushButton("✂ 手工调整裁剪")
        btn_adjust.setToolTip("截取不完整时，在原图上手动拖动四角重新框选")
        btn_adjust.clicked.connect(lambda: self._on_adjust(item))
        # PDF 没有单张原图可调整，禁用
        btn_adjust.setEnabled(bool(item.source_path) and
                               not item.source_path.lower().endswith(".pdf"))
        header.addWidget(btn_adjust)
        vbox.addLayout(header)

        label = QLabel("无图像")
        label.setAlignment(Qt.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(label)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:#f0f0f0;")
        vbox.addWidget(scroll, 1)
        size_label = QLabel("")
        size_label.setStyleSheet("color:#666;")
        vbox.addWidget(size_label)

        self._image_labels[id(item)] = (label, size_label)
        self._refresh_image(item)
        return pane

    def _refresh_image(self, item: ScanItem):
        """根据 item.scanned 刷新预览标签。"""
        label, size_label = self._image_labels.get(id(item), (None, None))
        if label is None:
            return
        pixmap = _np_to_pixmap(item.scanned)
        if pixmap.isNull():
            label.setText("无图像")
            size_label.setText("")
            return
        scaled = pixmap.scaled(
            520, 700, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        label.setPixmap(scaled)
        label.setToolTip(f"原始尺寸: {pixmap.width()} x {pixmap.height()}")
        size_label.setText(
            f"尺寸: {pixmap.width()} × {pixmap.height()} px（保留整张纸）")

    def _on_adjust(self, item: ScanItem):
        """弹出手动裁剪编辑器，用新四角重新矫正并刷新预览。"""
        import os
        from PySide6.QtWidgets import QMessageBox
        from .scanner import DocumentScanner
        from .crop_dialog import CropDialog

        if not item.source_path or not os.path.isfile(item.source_path):
            QMessageBox.information(self, "手工调整", "找不到原始图片，无法调整。")
            return
        # 读取原图（中文路径用 fromfile）
        import numpy as np
        import cv2
        data = np.fromfile(item.source_path, dtype=np.uint8)
        original = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if original is None:
            QMessageBox.information(self, "手工调整", "原图读取失败。")
            return

        scanner = DocumentScanner()
        # 初始四角：优先用上次调整结果，否则自动检测
        initial = item.manual_quad
        if initial is None:
            initial = scanner.detect_quad(original, full_page=True)
        dlg = CropDialog(original, initial, self)
        if dlg.exec() != QDialog.Accepted:
            return
        quad = dlg.get_quad()
        try:
            warped = scanner.warp_by_quad(original, quad)
            scanned = scanner.enhance_scan(warped)
        except Exception as exc:
            QMessageBox.critical(self, "手工调整", f"重新矫正失败：{exc}")
            return
        item.scanned = scanned
        item.manual_quad = quad
        self._refresh_image(item)
        self.tip.setText("✓ 已应用手工裁剪，确认无误后点「确认导出」；"
                         "仍可再次点「手工调整裁剪」微调。")

    def _make_content_pane(self, item: ScanItem) -> QWidget:
        pane = QWidget()
        vbox = QVBoxLayout(pane)
        task = self.result.task

        if task == "to_excel" and item.table:
            vbox.addWidget(QLabel("表格识别结果（可直接双击单元格修改，改后导出生效）："))
            rows = len(item.table)
            cols = max((len(r) for r in item.table), default=0)
            table_widget = QTableWidget(rows, cols)
            table_widget.setHorizontalHeaderLabels(
                [f"列{i+1}" for i in range(cols)])
            for r, row in enumerate(item.table):
                for c in range(cols):
                    text = row[c] if c < len(row) else ""
                    cell = QTableWidgetItem(text)
                    cell.setFont(QFont("Microsoft YaHei", 9))
                    # 手写体识别可能有误差，空单元格用浅黄底提示需人工补录
                    if not text.strip():
                        from PySide6.QtGui import QColor
                        cell.setBackground(QColor("#fff6d6"))
                    table_widget.setItem(r, c, cell)
            table_widget.resizeColumnsToContents()
            # 增加行/列按钮，应对漏格、漏行
            row_col_bar = QHBoxLayout()
            btn_add_row = QPushButton("＋ 增加一行")
            btn_add_row.clicked.connect(lambda: self._add_table_row(table_widget))
            btn_add_col = QPushButton("＋ 增加一列")
            btn_add_col.clicked.connect(lambda: self._add_table_col(table_widget))
            row_col_bar.addWidget(btn_add_row)
            row_col_bar.addWidget(btn_add_col)
            row_col_bar.addStretch(1)
            vbox.addLayout(row_col_bar)
            vbox.addWidget(table_widget, 1)
            note = QLabel(
                "提示：手写体识别准确率有限。双击任意单元格可直接修改；"
                "黄色空格为未识别内容，请对照左侧扫描图补录后再导出。"
            )
            note.setStyleSheet("color:#c2410c; font-weight:bold;")
            note.setWordWrap(True)
            vbox.addWidget(note)
            self._table_widgets[id(item)] = table_widget

        elif task == "scan":
            vbox.addWidget(QLabel("文档已矫正为整张纸扫描件（白底、去阴影、去黑点）。"))
            placeholder = QLabel("扫描结果见左侧预览。\n确认后将保存为 PNG 图片。")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("color:#666; font-size:13px;")
            vbox.addWidget(placeholder, 1)

        elif task == "pdf_to_word":
            vbox.addWidget(QLabel("PDF 文字识别结果（可直接编辑，改后导出生效）："))
            text_edit = QTextEdit()
            text_edit.setFont(QFont("Microsoft YaHei", 10))
            for pno, lines in enumerate(item.pdf_pages, 1):
                text_edit.append(f"===== 第 {pno} 页（{len(lines)} 行）=====")
                for line in lines:
                    text_edit.append(line["text"])
            vbox.addWidget(text_edit, 1)
            self._text_widgets[id(item)] = ("pdf", text_edit)

        else:
            # OCR / image_to_word：显示识别文字（可编辑补正）
            vbox.addWidget(QLabel(
                f"识别文字（{len(item.lines)} 行，可直接编辑修改）："))
            text_edit = QTextEdit()
            text_edit.setFont(QFont("Microsoft YaHei", 10))
            for line in item.lines:
                text_edit.append(line["text"])
            vbox.addWidget(text_edit, 1)
            note = QLabel("提示：手写体识别可能有误，可直接在此修改文字，确认后按修改后的内容导出。")
            note.setStyleSheet("color:#c2410c;")
            note.setWordWrap(True)
            vbox.addWidget(note)
            self._text_widgets[id(item)] = ("lines", text_edit)

        return pane

    @staticmethod
    def _add_table_row(table_widget: QTableWidget):
        r = table_widget.rowCount()
        table_widget.insertRow(r)
        for c in range(table_widget.columnCount()):
            cell = QTableWidgetItem("")
            cell.setFont(QFont("Microsoft YaHei", 9))
            table_widget.setItem(r, c, cell)

    @staticmethod
    def _add_table_col(table_widget: QTableWidget):
        c = table_widget.columnCount()
        table_widget.insertColumn(c)
        table_widget.setHorizontalHeaderItem(c, QTableWidgetItem(f"列{c+1}"))
        for r in range(table_widget.rowCount()):
            cell = QTableWidgetItem("")
            cell.setFont(QFont("Microsoft YaHei", 9))
            table_widget.setItem(r, c, cell)

    def _sync_edits(self):
        """把用户在预览里的编辑写回 ScanItem，供导出使用。"""
        for item in self.result.items:
            tw = self._table_widgets.get(id(item))
            if tw is not None:
                table = []
                for r in range(tw.rowCount()):
                    row = []
                    for c in range(tw.columnCount()):
                        cell = tw.item(r, c)
                        row.append(cell.text() if cell else "")
                    table.append(row)
                item.table = table
                item.lines = []
                for row in table:
                    for text in row:
                        if text.strip():
                            item.lines.append({"text": text, "score": 1.0,
                                               "box": [[0, 0], [0, 0], [0, 0], [0, 0]]})
                continue
            entry = self._text_widgets.get(id(item))
            if entry is not None:
                kind, text_edit = entry
                raw = text_edit.toPlainText().splitlines()
                texts = [t.rstrip() for t in raw if t.strip()]
                if kind == "pdf":
                    pages = []
                    current = None
                    for t in raw:
                        if t.startswith("=====") and "页" in t:
                            if current is not None:
                                pages.append(current)
                            current = []
                        elif current is not None and t.strip():
                            current.append({"text": t, "score": 1.0,
                                            "box": [[0, 0], [0, 0], [0, 0], [0, 0]]})
                    if current is not None:
                        pages.append(current)
                    item.pdf_pages = pages
                else:
                    item.lines = [
                        {"text": t, "score": 1.0,
                         "box": [[0, 0], [0, 0], [0, 0], [0, 0]]}
                        for t in texts
                    ]

    def _on_confirm(self):
        # 关键：先把用户在预览中的编辑写回结果，再确认导出
        self._sync_edits()
        self.confirmed = True
        self.accept()

    def confirm(self) -> bool:
        """exec() 后调用，返回用户是否确认。"""
        return self.confirmed and self.result() == QDialog.Accepted
