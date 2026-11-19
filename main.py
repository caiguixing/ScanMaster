"""ScanMaster 智能文档扫描工具 - 程序入口。

运行: python main.py
"""
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from app.main_window import MainWindow

STYLE = """
QMainWindow, QWidget { font-family: 'Microsoft YaHei'; }
QGroupBox { font-weight: bold; font-size: 13px; }
QListWidget::item { padding: 4px; }
QPushButton { font-size: 12px; }
"""


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
