"""Office 导出模块：TXT / Word / Excel。

- 导出 TXT：纯文字行
- 导出 Word：原图 + 识别文字段（图片转 Word）；PDF 每页渲染后 OCR 汇总
- 导出 Excel：根据 OCR 文本框坐标聚类重建表格
"""
import os
from typing import List, Dict

from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment


def _lines_to_text(lines: List[Dict]) -> str:
    return "\n".join(line["text"] for line in lines)


def export_txt(lines: List[Dict], out_path: str) -> str:
    """导出纯文字 TXT。"""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(_lines_to_text(lines))
    return out_path


def export_docx(lines: List[Dict], out_path: str,
                image_path: str = None, title: str = "文档识别结果") -> str:
    """导出 Word：可选插入原扫描图 + 识别文字段落。"""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    doc = Document()

    heading = doc.add_heading(title, level=0)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER

    if image_path and os.path.exists(image_path):
        try:
            doc.add_picture(image_path, width=Inches(6.0))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        except Exception:
            pass  # 图片插入失败不影响文字导出

    doc.add_heading("识别文字", level=1)
    for line in lines:
        para = doc.add_paragraph(line["text"])
        para.paragraph_format.space_after = Pt(4)

    doc.save(out_path)
    return out_path


def export_docx_pages(pages: List[List[Dict]], out_path: str,
                      title: str = "PDF 识别结果") -> str:
    """把 PDF 多页 OCR 结果汇总为一个 Word 文档。"""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    doc = Document()
    heading = doc.add_heading(title, level=0)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for page_no, lines in enumerate(pages, start=1):
        doc.add_heading(f"第 {page_no} 页", level=1)
        for line in lines:
            para = doc.add_paragraph(line["text"])
            para.paragraph_format.space_after = Pt(4)
        if page_no != len(pages):
            doc.add_page_break()

    doc.save(out_path)
    return out_path


def _cluster_rows(lines: List[Dict], tolerance: float = 12.0) -> List[List[Dict]]:
    """根据文本框 y 坐标把文字行聚类成表格行。"""
    if not lines:
        return []
    items = []
    for line in lines:
        ys = [p[1] for p in line["box"]]
        xs = [p[0] for p in line["box"]]
        items.append((min(ys), min(xs), line))
    items.sort(key=lambda t: (t[0], t[1]))

    heights = sorted(max(p[1] for p in l["box"]) - min(p[1] for p in l["box"])
                     for l in lines)
    tol = max(tolerance, heights[len(heights) // 2] * 0.6)

    rows: List[List[Dict]] = []
    current: List[Dict] = []
    current_y = None
    for y, _x, line in items:
        if current_y is None or abs(y - current_y) <= tol:
            current.append(line)
            current_y = y if current_y is None else current_y
        else:
            rows.append(current)
            current = [line]
            current_y = y
    if current:
        rows.append(current)
    return rows


def export_xlsx(lines: List[Dict], out_path: str,
                sheet_title: str = "识别表格") -> str:
    """把 OCR 文本框按坐标重建为表格并导出 Excel（退化方案，无表格线时用）。"""
    return export_table_xlsx(_cluster_rows_to_table(lines), out_path, sheet_title)


def _cluster_rows_to_table(lines: List[Dict]) -> List[List[str]]:
    rows = _cluster_rows(lines)
    table = []
    for row in rows:
        row.sort(key=lambda l: min(p[0] for p in l["box"]))
        table.append([line["text"] for line in row])
    return table


def export_table_xlsx(table: List[List[str]], out_path: str,
                      sheet_title: str = "识别表格") -> str:
    """把二维数组表格导出为 Excel（保留单元格结构）。

    Args:
        table: 二维数组，每个元素是一个单元格文本
        out_path: 输出路径
    """
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title[:31]

    for row in table:
        ws.append(list(row))

    # 首行加粗，全表垂直居中 + 自动换行
    if ws.max_row >= 1:
        for cell in ws[1]:
            cell.font = Font(bold=True)
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="center", wrap_text=True)

    # 设置合理列宽
    for col_idx in range(1, ws.max_column + 1):
        max_len = 0
        for row_idx in range(1, ws.max_row + 1):
            val = ws.cell(row=row_idx, column=col_idx).value
            if val:
                max_len = max(max_len, min(len(str(val)), 40))
        ws.column_dimensions[
            ws.cell(row=1, column=col_idx).column_letter
        ].width = max(10, max_len + 2)

    wb.save(out_path)
    return out_path
