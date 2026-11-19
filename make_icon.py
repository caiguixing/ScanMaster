# -*- coding: utf-8 -*-
"""生成 ScanMaster 应用图标 app_icon.ico（多尺寸）。"""
import os
from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_icon.ico")
S = 1024


def lerp(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


# 1) 蓝色渐变背景
canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(canvas)
top, bottom = (30, 90, 220), (16, 165, 235)
for y in range(S):
    d.line([(0, y), (S, y)], fill=lerp(top, bottom, y / S) + (255,))

mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=225, fill=255)
canvas.putalpha(mask)

# 2) 纸张阴影
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle(
    [300, 235, 775, 835], radius=28, fill=(0, 0, 0, 80)
)
shadow = shadow.filter(ImageFilter.GaussianBlur(20))
canvas = Image.alpha_composite(canvas, shadow)

d = ImageDraw.Draw(canvas)
L, T, R, B, fold = 270, 200, 745, 800, 115
paper = [
    (L, T + 30), (L + 30, T), (R - fold, T), (R, T + fold),
    (R, B - 30), (R - 30, B), (L, B),
]
d.polygon(paper, fill=(255, 255, 255, 255))
d.polygon(
    [(R - fold, T), (R, T + fold), (R - fold, T + fold)],
    fill=(226, 232, 240, 255),
)
d.line(
    [(R - fold, T), (R - fold, T + fold), (R, T + fold)],
    fill=(148, 163, 184, 255), width=6,
)

# 3) 文字线
for yy, ww in [(360, 330), (440, 370), (520, 300), (600, 350)]:
    d.rounded_rectangle(
        [L + 72, yy, L + 72 + ww, yy + 28], radius=14, fill=(203, 213, 225, 255)
    )

# 4) 扫描线发光
glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(glow).rectangle(
    [L + 45, 472, R - 25, 488], fill=(16, 185, 129, 235)
)
glow = glow.filter(ImageFilter.GaussianBlur(16))
canvas = Image.alpha_composite(canvas, glow)
d = ImageDraw.Draw(canvas)
d.rounded_rectangle([L + 45, 476, R - 25, 484], radius=4, fill=(4, 150, 105, 255))

# 5) 缩小并保存多尺寸 ICO
base = canvas.resize((256, 256), Image.LANCZOS)
base.save(OUT, format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
print("图标已生成:", OUT, os.path.getsize(OUT), "bytes")
