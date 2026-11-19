"""本地离线 OCR 文字识别封装。

底层使用 RapidOCR（PaddleOCR 模型的 ONNX 移植版），完全离线运行，
兼容 Python 3.13，无需安装 paddlepaddle。首次调用会加载内置模型。
"""
from typing import List, Dict

from rapidocr_onnxruntime import RapidOCR


class OcrEngine:
    """线程安全的按需加载 OCR 引擎。识别结果为按阅读顺序排列的文字行。"""

    def __init__(self):
        self._engine = None

    def _get_engine(self) -> RapidOCR:
        if self._engine is None:
            self._engine = RapidOCR()
        return self._engine

    def recognize(self, image) -> List[Dict]:
        """识别图片中的文字。

        Args:
            image: BGR numpy 数组或图片文件路径。

        Returns:
            [{"text": str, "score": float, "box": [[x,y], ...]}, ...]
        """
        result, _ = self._get_engine()(image)
        lines: List[Dict] = []
        if not result:
            return lines
        for box, text, score in result:
            if not text or not str(text).strip():
                continue
            lines.append({
                "text": str(text),
                "score": float(score),
                "box": [[float(p[0]), float(p[1])] for p in box],
            })
        return self._sort_lines(lines)

    @staticmethod
    def _sort_lines(lines: List[Dict]) -> List[Dict]:
        """按阅读顺序排序：先按行聚类（y），行内按 x 从左到右。"""
        if not lines:
            return []
        indexed = []
        for idx, line in enumerate(lines):
            ys = [p[1] for p in line["box"]]
            xs = [p[0] for p in line["box"]]
            indexed.append((min(ys), min(xs), idx, line))

        # 估算行高作为聚类容差
        heights = sorted(max(p[1] for p in l["box"]) - min(p[1] for p in l["box"])
                         for l in lines)
        tolerance = max(10.0, heights[len(heights) // 2] * 0.6)

        indexed.sort(key=lambda t: (t[0], t[1]))
        rows = []
        current = []
        current_y = None
        for item in indexed:
            if current_y is None or abs(item[0] - current_y) <= tolerance:
                current.append(item)
                current_y = item[0] if current_y is None else current_y
            else:
                rows.append(current)
                current = [item]
                current_y = item[0]
        if current:
            rows.append(current)

        ordered = []
        for row in rows:
            row.sort(key=lambda t: t[1])
            ordered.extend(t[3] for t in row)
        return ordered
