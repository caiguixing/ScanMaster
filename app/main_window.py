"""ScanMaster 主界面。

支持拖拽/粘贴/选择图片和 PDF，一键执行文档扫描、OCR 文字提取、
图片转 Word、PDF 转 Word、表格转 Excel。
"""
import os

from PySide6.QtCore import Qt, QFileInfo, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices, QFont, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QTextEdit, QProgressBar, QFileDialog,
    QMessageBox, QSplitter, QGroupBox, QAbstractItemView, QStatusBar,
)

from .worker import Worker, IMAGE_EXTS

APP_TITLE = "ScanMaster 智能文档扫描"

SUPPORTED_EXTS = IMAGE_EXTS | {".pdf"}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.files: list[str] = []
        self.worker: Worker | None = None
        self.out_dir = os.path.join(os.path.expanduser("~"), "Desktop", "ScanMaster_Output")
        self._build_ui()
        self.setWindowTitle(APP_TITLE)
        self.resize(1180, 760)
        self.setAcceptDrops(True)
        self.statusBar().showMessage("就绪：拖入图片/PDF，或点击「导入文件」")

    # ---------- UI 构建 ----------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # 顶部功能栏
        toolbar = QHBoxLayout()
        self.btn_import = QPushButton("导入文件")
        self.btn_import.clicked.connect(self.import_files)
        toolbar.addWidget(self.btn_import)

        self.btn_paste = QPushButton("粘贴剪贴板")
        self.btn_paste.clicked.connect(self.paste_from_clipboard)
        toolbar.addWidget(self.btn_paste)

        toolbar.addStretch(1)
        self.btn_outdir = QPushButton("输出目录")
        self.btn_outdir.clicked.connect(self.choose_out_dir)
        toolbar.addWidget(self.btn_outdir)
        self.lbl_outdir = QLabel(self._short_path(self.out_dir))
        self.lbl_outdir.setStyleSheet("color:#666;")
        toolbar.addWidget(self.lbl_outdir)
        root.addLayout(toolbar)

        # 主区域：左侧文件列表 + 预览 | 右侧结果
        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)

        left_layout.addWidget(QLabel("文件列表（可拖拽 / 粘贴导入）："))
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.currentRowChanged.connect(self.on_select_file)
        left_layout.addWidget(self.file_list, 2)

        self.preview = QLabel("预览区")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(240)
        self.preview.setStyleSheet(
            "border:1px dashed #bbb; background:#fafafa; color:#999;"
        )
        left_layout.addWidget(self.preview, 3)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("识别结果 / 处理日志："))
        self.result = QTextEdit()
        self.result.setReadOnly(True)
        self.result.setFont(QFont("Microsoft YaHei", 10))
        right_layout.addWidget(self.result)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        # 功能按钮区
        actions = QGroupBox("功能")
        act_layout = QHBoxLayout(actions)
        buttons = [
            ("文档扫描矫正", "scan", "#2d7ff9"),
            ("提取文字", "ocr", "#17a673"),
            ("图片转 Word", "image_to_word", "#7b5cff"),
            ("PDF 转 Word", "pdf_to_word", "#e8821a"),
            ("表格转 Excel", "to_excel", "#d64a6c"),
        ]
        for text, task, color in buttons:
            btn = QPushButton(text)
            btn.setStyleSheet(
                f"QPushButton{{background:{color};color:white;padding:9px;"
                f"border-radius:5px;font-weight:bold;}}"
                f"QPushButton:disabled{{background:#ccc;}}"
            )
            btn.clicked.connect(lambda checked=False, t=task: self.start_task(t))
            act_layout.addWidget(btn)
        root.addWidget(actions)

        # 进度条
        self.progress = QProgressBar()
        self.progress.setValue(0)
        root.addWidget(self.progress)

    # ---------- 文件导入 ----------
    def import_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片或 PDF", "",
            "文档与图片 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp *.pdf)",
        )
        self.add_files(paths)

    def paste_from_clipboard(self):
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        image = clipboard.image()
        if not image.isNull():
            path = os.path.join(
                self.out_dir,
                f"粘贴图片_{len(self.files) + 1}.png",
            )
            os.makedirs(self.out_dir, exist_ok=True)
            image.save(path)
            self.add_files([path])
            self.log("已从剪贴板导入图片")
            return
        self.log("剪贴板中没有图片")

    def add_files(self, paths: list[str]):
        added = 0
        for path in paths:
            if not os.path.isfile(path):
                continue
            if os.path.splitext(path)[1].lower() not in SUPPORTED_EXTS:
                continue
            if path not in self.files:
                self.files.append(path)
                self.file_list.addItem(QListWidgetItem(os.path.basename(path)))
                added += 1
        if self.files and self.file_list.currentRow() < 0:
            self.file_list.setCurrentRow(0)
        if added:
            self.log(f"已导入 {added} 个文件，共 {len(self.files)} 个")

    def on_select_file(self, row: int):
        if row < 0 or row >= len(self.files):
            return
        path = self.files[row]
        if os.path.splitext(path)[1].lower() == ".pdf":
            self.preview.setText("PDF 文件\n（转换后查看 Word 结果）")
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.preview.setText("无法预览")
            return
        scaled = pixmap.scaled(
            self.preview.width() - 20, self.preview.height() - 20,
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self.preview.setPixmap(scaled)

    # ---------- 拖拽支持 ----------
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        self.add_files(paths)
        event.acceptProposedAction()

    # ---------- 任务执行 ----------
    def start_task(self, task: str):
        if not self.files:
            QMessageBox.information(self, APP_TITLE, "请先导入图片或 PDF 文件")
            return
        if task == "pdf_to_word":
            files = [f for f in self.files if f.lower().endswith(".pdf")]
            if not files:
                QMessageBox.information(self, APP_TITLE, "未检测到 PDF 文件")
                return
        else:
            files = [f for f in self.files
                     if os.path.splitext(f)[1].lower() in IMAGE_EXTS]
            if not files:
                QMessageBox.information(self, APP_TITLE, "未检测到图片文件")
                return

        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, APP_TITLE, "有任务正在执行，请稍候")
            return

        self.result.clear()
        self.progress.setValue(0)
        self.log(f"开始任务：{task}（{len(files)} 个文件）")
        self.worker = Worker(task, files, self.out_dir)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()

    def on_progress(self, pct: int, msg: str):
        self.progress.setValue(pct)
        self.statusBar().showMessage(msg)

    def on_finished(self, task: str, data):
        self.progress.setValue(100)
        self.statusBar().showMessage("处理完成")
        if task == "ocr":
            for name, lines in data:
                self.log(f"\n===== {name}（{len(lines)} 行）=====")
                for line in lines:
                    self.log(f"[{line['score']:.2f}] {line['text']}")
            self.log(f"\n结果文本已保存至: {self.out_dir}")
            txt_path = os.path.join(self.out_dir, "识别文字.txt")
            all_text = "\n".join(
                f"===== {name} =====\n" + "\n".join(l["text"] for l in lines)
                for name, lines in data
            )
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(all_text)
        else:
            self.log("已生成文件：")
            for path in data:
                self.log(f"  • {path}")
            try:
                QDesktopServices.openUrl(QUrl.fromLocalFile(self.out_dir))
            except Exception:
                pass
        QMessageBox.information(self, APP_TITLE, "处理完成！")

    def on_failed(self, error: str):
        self.statusBar().showMessage("处理失败")
        self.log(f"\n[错误] {error}")
        QMessageBox.critical(self, APP_TITLE, f"处理失败：\n{error[:500]}")

    # ---------- 工具方法 ----------
    def choose_out_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", self.out_dir)
        if path:
            self.out_dir = path
            self.lbl_outdir.setText(self._short_path(path))

    def log(self, msg: str):
        self.result.append(msg)

    @staticmethod
    def _short_path(path: str, max_len: int = 32) -> str:
        return path if len(path) <= max_len else "..." + path[-max_len:]
