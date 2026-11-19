"""冒烟测试：不依赖 GUI，验证核心模块可正常运行。

运行: python tests/smoke_test.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np

from app.scanner import DocumentScanner, to_pil
from app.ocr_engine import OcrEngine
from app import exporters

FONT = "C:/Windows/Fonts/simhei.ttf"


def make_test_image(path: str):
    """生成一张带中文文字的测试图片。"""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (900, 500), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 40) if os.path.exists(FONT) else ImageFont.load_default()
    draw.text((60, 80), "ScanMaster 智能文档扫描", fill="black", font=font)
    draw.text((60, 180), "提取文字测试 1234567890", fill="black", font=font)
    draw.text((60, 280), "图片转Word / PDF转Office", fill="black", font=font)
    img.save(path)
    return path


def main():
    tmp = tempfile.mkdtemp(prefix="scanmaster_test_")
    print(f"[1] 临时目录: {tmp}")

    img_path = make_test_image(os.path.join(tmp, "test.png"))
    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None, "测试图片生成失败"

    print("[2] 测试文档扫描矫正 ...")
    scanner = DocumentScanner()
    scanned = scanner.scan(img, enhance=False)
    scan_path = os.path.join(tmp, "test_扫描.png")
    to_pil(scanned).save(scan_path)
    print(f"    矫正输出: {scan_path} ({scanned.shape})")

    print("[3] 测试 OCR 文字识别（首次加载模型稍慢）...")
    ocr = OcrEngine()
    lines = ocr.recognize(scanned)
    print(f"    识别到 {len(lines)} 行:")
    for line in lines:
        print(f"    [{line['score']:.2f}] {line['text']}")
    assert lines, "未识别到任何文字"

    print("[4] 测试导出模块 ...")
    txt = exporters.export_txt(lines, os.path.join(tmp, "out.txt"))
    docx = exporters.export_docx(lines, os.path.join(tmp, "out.docx"),
                                 image_path=scan_path)
    xlsx = exporters.export_xlsx(lines, os.path.join(tmp, "out.xlsx"))
    for f in (txt, docx, xlsx):
        assert os.path.exists(f) and os.path.getsize(f) > 0, f"导出失败: {f}"
        print(f"    OK: {f}")

    print("\n[PASS] 所有核心模块冒烟测试通过")
    print(f"输出文件位于: {tmp}")


if __name__ == "__main__":
    main()
