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

    def __init__(self, result: ScanResult, parent=None):
        super().__init__(parent)
        self.result = result
        self.confirmed = False
        self.setWindowTitle(TASK_TITLES.get(result.task, "预览确认"))
        self.resize(1100, 780)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        tip = QLabel("请预览识别结果，确认无误后点击「确认导出」；"
                     "如需重新识别请点击「取消」。")
        tip.setStyleSheet("color:#c2410c; font-weight:bold; padding:4px;")
        root.addWidget(tip)

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
        vbox.addWidget(QLabel("扫描图预览："))
        label = QLabel("无图像")
        label.setAlignment(Qt.AlignCenter)
        pixmap = _np_to_pixmap(item.scanned)
        if not pixmap.isNull():
            # 缩放到面板大小，保持比例
            scaled = pixmap.scaled(
                520, 700, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(scaled)
            label.setToolTip(f"原始尺寸: {pixmap.width()} x {pixmap.height()}")
        scroll = QScrollArea()
        scroll.setWidget(label)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background:#f0f0f0;")
        vbox.addWidget(scroll, 1)
        if not pixmap.isNull():
            size_label = QLabel(
                f"尺寸: {pixmap.width()} × {pixmap.height()} px（保留整张纸）")
            size_label.setStyleSheet("color:#666;")
            vbox.addWidget(size_label)
        return pane

    def _make_content_pane(self, item: ScanItem) -> QWidget:
        pane = QWidget()
        vbox = QVBoxLayout(pane)
        task = self.result.task

        if task == "to_excel" and item.table:
            vbox.addWidget(QLabel("表格识别结果（将导出到 Excel）："))
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
                    table_widget.setItem(r, c, cell)
            table_widget.resizeColumnsToContents()
            vbox.addWidget(table_widget, 1)
            note = QLabel("提示：手写体字形识别可能有误差，请核对关键数据。")
            note.setStyleSheet("color:#c2410c;")
            vbox.addWidget(note)

        elif task == "scan":
            vbox.addWidget(QLabel("文档已矫正为整张纸扫描件（白底、去阴影、去黑点）。"))
            placeholder = QLabel("扫描结果见左侧预览。\n确认后将保存为 PNG 图片。")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("color:#666; font-size:13px;")
            vbox.addWidget(placeholder, 1)

        elif task == "pdf_to_word":
            vbox.addWidget(QLabel("PDF 文字识别结果："))
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            for pno, lines in enumerate(item.pdf_pages, 1):
                text_edit.append(f"===== 第 {pno} 页（{len(lines)} 行）=====")
                for line in lines:
                    text_edit.append(line["text"])
            vbox.addWidget(text_edit, 1)

        else:
            # OCR / image_to_word：显示识别文字
            vbox.addWidget(QLabel(f"识别文字（{len(item.lines)} 行）："))
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setFont(QFont("Microsoft YaHei", 10))
            for line in item.lines:
                text_edit.append(line["text"])
            vbox.addWidget(text_edit, 1)

        return pane

    def _on_confirm(self):
        self.confirmed = True
        self.accept()

    def confirm(self) -> bool:
        """exec() 后调用，返回用户是否确认。"""
        return self.confirmed and self.result() == QDialog.Accepted
