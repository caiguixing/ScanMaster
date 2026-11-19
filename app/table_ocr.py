"""基于表格线的结构化表格识别（手写表格加强版）。

针对手写表格的常见难点：
- 姓名等列是跨行合并单元格（一个姓名对应多个产品行）
- 手写中文识别率低，整行检测会把相邻列的字粘连、漏格
- 竖线检测常漏掉最左边框，导致列整体错位

策略：
1. 形态学检测表格横线/竖线，确定网格；自动补齐左右边框，防列错位
2. 逐单元格裁剪，多预处理 × 多尺度 OCR + 置信度投票（见 OcrEngine.recognize_cell）
3. 每个单元格只取最优候选，避免多预处理结果拼接成乱码
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
    h_thresh = max(h_proj.max() * 0.45, w * 0.10)
    v_thresh = max(v_proj.max() * 0.45, h * 0.10)
    h_lines = _cluster_positions(np.where(h_proj > h_thresh)[0], min_gap=4)
    v_lines = _cluster_positions(np.where(v_proj > v_thresh)[0], min_gap=4)

    if len(h_lines) < 2 or len(v_lines) < 2:
        return [], []

    # 补边框：竖线若离左右边界较远，说明漏检了边框，补上（防止列整体错位）
    edge_tol = max(8, w // 40)
    if v_lines[0] > edge_tol:
        v_lines = [0] + v_lines
    if v_lines[-1] < w - edge_tol:
        v_lines = v_lines + [w - 1]
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


def _is_blank(gray: np.ndarray) -> bool:
    """判断单元格图像是否基本空白（只有表格线/噪点，无书写内容）。"""
    if gray.size == 0:
        return True
    # 去掉边缘几个像素（表格线）
    core = gray[3:-3, 3:-3] if gray.shape[0] > 8 and gray.shape[1] > 8 else gray
    if core.size == 0:
        return True
    # 深色像素占比极低 -> 空白
    dark = (core < 150).sum()
    return dark < max(4, core.size * 0.005)


def build_table(gray: np.ndarray, lines: List[Dict],
                ocr_engine=None, fill_merged: bool = True) -> Tuple[List[List[str]], bool]:
    """构建二维表格。

    Args:
        gray: 矫正后灰度图
        lines: 整图 OCR 结果（无表格线时的退化方案用）
        ocr_engine: OcrEngine 实例；提供时逐单元格重新识别（效果更好）
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

    if ocr_engine is not None and hasattr(ocr_engine, "recognize_cell"):
        # 逐单元格 OCR：每个格子独立识别，取最优候选（避免相邻列粘连）
        for r in range(n_rows):
            for c in range(n_cols):
                x0, x1 = v_lines[c] + 3, v_lines[c + 1] - 3
                y0, y1 = h_lines[r] + 3, h_lines[r + 1] - 3
                if x1 <= x0 or y1 <= y0:
                    continue
                cell = gray[y0:y1, x0:x1]
                if _is_blank(cell):
                    continue
                cands = ocr_engine.recognize_cell(cell)
                if cands:
                    table[r][c] = cands[0]["text"]
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
    if fill_merged and n_rows > 2 and n_cols > 1:
        header0 = table[0][0].strip() if table else ""
        data_filled = sum(1 for r in range(1, n_rows)
                          if table[r][0].strip() and table[r][0].strip() != header0)
        if 0 < data_filled < (n_rows - 1) * 0.6:
            last_value = ""
            for r in range(1, n_rows):
                value = table[r][0].strip()
                if value and value != header0:
                    last_value = value
                elif last_value and any(table[r][c].strip() for c in range(1, n_cols)):
                    table[r][0] = last_value

    # 去掉完全空白行（保留有数据的行，含表头）
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
