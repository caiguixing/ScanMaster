"""识别结果容器：Worker 识别后返回给主线程预览，确认后才导出文件。"""
from typing import List, Dict, Optional

import numpy as np


class ScanItem:
    """单个文件的识别结果。"""

    def __init__(self, name: str, source_path: str = ""):
        self.name = name
        self.source_path = source_path
        self.scanned: Optional[np.ndarray] = None   # 矫正后 BGR 图
        self.table: Optional[List[List[str]]] = None  # 二维表格
        self.table_detected: bool = False
        self.lines: List[Dict] = []                  # OCR 文字行
        self.pdf_pages: List[List[Dict]] = []        # PDF 每页文字


class ScanResult:
    """一次任务的全部识别结果。"""

    def __init__(self, task: str):
        self.task = task
        self.items: List[ScanItem] = []
