"""基于表格线的结构化表格识别。

针对手写表格的常见难点：
- 姓名等列是跨行合并单元格（一个姓名对应多个产品行）
- 手写中文识别率低，整行检测会把相邻列的字粘连

策略：
1. 形态学检测表格横线/竖线，确定网格
2. 按列分别 OCR（避免相邻列文字粘连），多种预处理融合去重提升召回
3. 每个文本框按 y 中心归入对应行
4. 首列（姓名列）向下填充，还原跨行合并单元格
"""
from typing import List, Dict, Tuple

import cv2
import numpy as np


def detect_table_lines(gray: np.ndarray):
    """检测表格横线和竖线位置，返回 (h_lines, v_lines)。"""
    h, w = gray.shape[:2]
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 20, 15), 1))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)

    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h // 30, 15)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)

    h_proj = horizontal.sum(axis=1) / 255.0
    v_proj = vertical.sum(axis=0) / 255.0
    # 阈值自适应：取投影峰值的一定比例，兼容「整张纸」和「裁切表格」两种图
    # （整张纸里表格线占比小，固定阈值会漏检）
    h_thresh = max(h_proj.max() * 0.45, w * 0.10)
    v_thresh = max(v_proj.max() * 0.45, h * 0.10)
    h_lines = _cluster_positions(np.where(h_proj > h_thresh)[0], min_gap=4)
    v_lines = _cluster_positions(np.where(v_proj > v_thresh)[0], min_gap=4)

    if len(h_lines) < 2 or len(v_lines) < 2:
        return [], []
    return h_lines, v_lines


def _cluster_positions(pos: np.ndarray, min_gap: int = 4) -> List[int]:
    if len(pos) == 0:
        return []
    groups = []
    current = [int(pos[0])]
    for p in pos[1:]:
        p = int(p)
        if p - current[-1] <= min_gap:
            current.append(p)
        else:
            groups.append(current)
            current = [p]
    groups.append(current)
    return [int(round(sum(g) / len(g))) for g in groups]


def _preprocess_variants(col: np.ndarray) -> List[np.ndarray]:
    """对单列图像生成 2 种预处理版本（平衡召回与速度）。"""
    variants = [col]
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    variants.append(clahe.apply(col))
    return variants


def _ocr_column(ocr_engine, col: np.ndarray) -> List[Tuple[float, str, float]]:
    """对单列做多预处理 OCR，返回去重后的 (y中心, 文本, 置信度) 列表。"""
    collected: List[Tuple[float, str, float]] = []
    padded = 8
    for variant in _preprocess_variants(col):
        # 放大 2x 提升小字/手写体识别率，坐标换算时除以缩放比
        scaled = cv2.resize(variant, None, fx=2, fy=2,
                            interpolation=cv2.INTER_CUBIC)
        padded_img = cv2.copyMakeBorder(scaled, padded, padded, padded, padded,
                                        cv2.BORDER_CONSTANT, value=255)
        result, _ = ocr_engine(padded_img, box_thresh=0.3, text_score=0.3)
        if not result:
            continue
        for box, text, score in result:
            ys = [(float(p[1]) - padded) / 2 for p in box]  # 还原到原坐标
            cy = (min(ys) + max(ys)) / 2
            text = str(text).strip()
            if text:
                collected.append((cy, text, float(score)))

    # 多预处理会产生同一文字的多个变体，需聚合成一个。
    # 规则：y 接近（±20px）的候视为同一处文字，选置信度×长度最优的单个结果，
    # 不再拼接（拼接会把"150"和"i5o"叠成"150 i5o"）。
    collected.sort(key=lambda t: -t[2])  # 先按置信度降序，优先保留好的
    merged: List[Tuple[float, str, float]] = []
    for cy, text, score in collected:
        duplicate = False
        for ecy, etext, escore in merged:
            if abs(cy - ecy) < 20:
                duplicate = True
                break
        if not duplicate:
            merged.append((cy, text, score))
    merged.sort(key=lambda t: t[0])
    return merged


def build_table(gray: np.ndarray, lines: List[Dict],
                ocr_engine=None, fill_merged: bool = True) -> Tuple[List[List[str]], bool]:
    """构建二维表格。

    Args:
        gray: 矫正后灰度图
        lines: 整图 OCR 结果（无表格线时的退化方案用）
        ocr_engine: RapidOCR 引擎实例；提供时按列重新识别（效果更好）
        fill_merged: 是否对首列向下填充（还原跨行合并单元格）

    Returns:
        (table, detected)
    """
    h_lines, v_lines = detect_table_lines(gray)
    if not h_lines or not v_lines:
        return _fallback_table(lines), False

    n_rows = len(h_lines) - 1
    n_cols = len(v_lines) - 1
    table = [["" for _ in range(n_cols)] for _ in range(n_rows)]

    if ocr_engine is not None:
        # 按列 OCR（避免相邻列粘连）
        for c in range(n_cols):
            col_img = gray[:, v_lines[c]:v_lines[c + 1]]
            items = _ocr_column(ocr_engine, col_img)
            for cy, text, score in items:
                r = _y_to_row(cy, h_lines)
                if table[r][c]:
                    table[r][c] += " " + text
                else:
                    table[r][c] = text
    else:
        # 退化：用传入的整图 lines 按中心点归属
        for line in lines:
            cx, cy = _box_center(line)
            r = _y_to_row(cy, h_lines)
            c = _x_to_col(cx, v_lines)
            text = line["text"].strip()
            if text:
                table[r][c] = (table[r][c] + " " + text).strip()

    # 首列向下填充：还原跨行合并单元格（如姓名跨多行）
    # 仅当首列大部分为空（<50% 有值）时才判定为合并单元格，避免误伤普通表格
    if fill_merged and n_rows > 2:
        header0 = table[0][0].strip() if table else ""
        data_filled = sum(1 for r in range(1, n_rows) if table[r][0].strip()
                          and table[r][0].strip() != header0)
        if 0 < data_filled < (n_rows - 1) * 0.5:
            last_value = ""
            for r in range(1, n_rows):  # 从数据行开始，跳过表头
                value = table[r][0].strip()
                if value and value != header0:
                    last_value = value
                elif last_value and any(table[r][c].strip() for c in range(1, n_cols)):
                    # 仅在该行有其他列数据（真实数据行）时才填充姓名
                    table[r][0] = last_value

    # 去掉完全空白行
    table = [row for row in table if any(cell.strip() for cell in row)]
    return table, True


def _y_to_row(cy: float, h_lines: List[int]) -> int:
    for i in range(len(h_lines) - 1):
        if h_lines[i] <= cy < h_lines[i + 1]:
            return i
    return max(0, len(h_lines) - 2)


def _x_to_col(cx: float, v_lines: List[int]) -> int:
    for j in range(len(v_lines) - 1):
        if v_lines[j] <= cx < v_lines[j + 1]:
            return j
    return max(0, len(v_lines) - 2)


def _box_center(line: Dict) -> Tuple[float, float]:
    box = line["box"]
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _fallback_table(lines: List[Dict]) -> List[List[str]]:
    from .exporters import _cluster_rows
    rows = _cluster_rows(lines)
    return [[line["text"] for line in sorted(row, key=lambda l: min(p[0] for p in l["box"]))]
            for row in rows]


def table_to_lines(table: List[List[str]]) -> List[Dict]:
    lines = []
    for row in table:
        for text in row:
            if text.strip():
                lines.append({"text": text, "score": 1.0,
                              "box": [[0, 0], [0, 0], [0, 0], [0, 0]]})
    return lines
