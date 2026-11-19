"""本地离线 OCR 文字识别封装。

底层使用 RapidOCR（PaddleOCR 模型的 ONNX 移植版），完全离线运行，
兼容 Python 3.13，无需安装 paddlepaddle。首次调用会加载内置模型。

针对手写体/浅色字的识别加强：
1. 检测阈值降低，提升小字、浅字召回
2. recognize_enhanced()：多预处理 × 多尺度融合 + 置信度投票，
   专供表格单元格使用（单元格小、无上下文，单预处理漏检严重）
"""
from collections import Counter
from typing import List, Dict, Tuple

import cv2
import numpy as np

from rapidocr_onnxruntime import RapidOCR


class OcrEngine:
    """线程安全的按需加载 OCR 引擎。识别结果为按阅读顺序排列的文字行。"""

    def __init__(self):
        self._engine = None
        self._rec_engine = None   # 识别模式引擎（use_text_det=False），单元格专用

    def _get_engine(self) -> RapidOCR:
        if self._engine is None:
            self._engine = RapidOCR()
        return self._engine

    def _get_rec_engine(self) -> RapidOCR:
        """单元格识别模式引擎：整块当单行文本，比检测模式快 10x+、数字更准。

        注意 RapidOCR 的 bug：use_text_det=False 时调用若传 kwargs 会引用
        不存在的 text_detector 而崩溃，故阈值在构造时传入，调用时不传参。
        """
        if self._rec_engine is None:
            self._rec_engine = RapidOCR(use_text_det=False, text_score=0.1)
        return self._rec_engine

    def recognize(self, image, full_page: bool = True) -> List[Dict]:
        """识别整图文字。

        Args:
            image: BGR numpy 数组或图片文件路径。
            full_page: 整图/大图用 True（尺寸大、自动检测）；
                       已是紧凑裁剪小图时也保持 True（RapidOCR 内部会判断）。

        Returns:
            [{"text": str, "score": float, "box": [[x,y], ...]}, ...]
        """
        arr = self._ensure_array(image)
        if arr is None:
            return []
        # 降低检测阈值，捕捉手写体和浅色文字（默认 0.5 偏高会漏检）
        result, _ = self._get_engine()(
            arr, box_thresh=0.35, unclip_ratio=1.8, text_score=0.3
        )
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
    def _ensure_array(image):
        if image is None:
            return None
        if isinstance(image, np.ndarray):
            return image
        img = cv2.imdecode(np.fromfile(str(image), dtype=np.uint8), cv2.IMREAD_COLOR)
        return img

    # ---------- 单元格识别加强 ----------
    @staticmethod
    def cell_variants(cell: np.ndarray) -> List[Tuple[str, np.ndarray]]:
        """为单元格生成多种预处理版本，弥补手写体漏检。

        保留原灰度、CLAHE 对比度增强、Otsu 二值化三种。
        注意：手写浅字经 Otsu 可能丢笔画，故三种都试，投票取共识。
        """
        gray = cell if cell.ndim == 2 else cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
        variants = [("raw", gray)]
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        variants.append(("clahe", clahe.apply(gray)))
        # 轻度高斯后再 Otsu，减少噪点干扰
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(("otsu", otsu))
        return variants

    def recognize_cell(self, cell: np.ndarray,
                       scales=(2,)) -> List[Dict]:
        """识别单个单元格：识别模式（快且数字准）+ 多预处理投票。

        单元格本质是单行文本，用 use_text_det=False 识别模式：
        - 比检测模式快 10 倍以上
        - 数字、代码识别明显更准（不会被检测框截断）
        对同一格子的多种预处理结果投票，取得票最高者。

        返回:
            [{"text": str, "score": float, "votes": int}, ...]
        """
        if cell is None or cell.size == 0:
            return []
        votes: Counter = Counter()
        best_score: Dict[str, float] = {}
        rec_engine = self._get_rec_engine()
        for _name, variant in self.cell_variants(cell):
            for scale in scales:
                up = cv2.resize(variant, None, fx=scale, fy=scale,
                                interpolation=cv2.INTER_CUBIC)
                try:
                    result, _ = rec_engine(up)  # 不传 kwargs（见 _get_rec_engine 注释）
                except Exception:
                    continue
                if not result:
                    continue
                for _box, text, score in result:
                    text = "".join(str(text).split())  # 去空格统一
                    if not text:
                        continue
                    votes[text] += 1
                    s = float(score)
                    if text not in best_score or s > best_score[text]:
                        best_score[text] = s
        ranked = sorted(
            votes.items(),
            key=lambda kv: (kv[1], best_score.get(kv[0], 0.0)),
            reverse=True,
        )
        return [{"text": t, "score": best_score.get(t, 0.0), "votes": n}
                for t, n in ranked]

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
