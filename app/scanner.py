"""文档扫描矫正引擎。

流程：缩放 -> 高斯模糊 -> Canny 边缘 -> 轮廓筛选四边形 -> 透视变换 -> 图像增强。
输入为 BGR 的 numpy 数组，输出为矫正后的 BGR 数组。无法识别边界时回退到增强原图。
"""
import cv2
import numpy as np


class DocumentScanner:
    """把拍摄的纸质文档照片矫正成正面扫描件。"""

    def __init__(self, max_side: int = 1200):
        self.max_side = max_side

    def _resize(self, img: np.ndarray):
        h, w = img.shape[:2]
        scale = self.max_side / max(h, w)
        if scale < 1.0:
            small = cv2.resize(img, None, fx=scale, fy=scale,
                               interpolation=cv2.INTER_AREA)
            return small, scale
        return img.copy(), 1.0

    @staticmethod
    def _find_quad(contours):
        """在轮廓中找一个面积最大的近似四边形，返回 4 个顶点。"""
        candidates = sorted(contours, key=cv2.contourArea, reverse=True)[:12]
        for contour in candidates:
            if cv2.contourArea(contour) < 1000:
                continue
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
            if len(approx) == 4:
                return approx.reshape(4, 2).astype("float32")
        return None

    @staticmethod
    def _order_points(pts: np.ndarray) -> np.ndarray:
        """把四点统一为 [左上, 右上, 右下, 左下] 顺序。"""
        rect = np.zeros((4, 2), dtype="float32")
        sums = pts.sum(axis=1)
        rect[0] = pts[np.argmin(sums)]
        rect[2] = pts[np.argmax(sums)]
        diffs = np.diff(pts, axis=1).ravel()
        rect[1] = pts[np.argmin(diffs)]
        rect[3] = pts[np.argmax(diffs)]
        return rect

    def _enhance(self, img: np.ndarray) -> np.ndarray:
        """去阴影 + 对比度增强，保留完整笔画（不做激进二值化）。

        用大核高斯估计光照背景并归一化，消除阴影；再做轻度 CLAHE 提升对比度。
        相比自适应阈值，这种方式不会造成手写笔画断裂和噪点。
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img.copy()
        # 估计光照背景（大核模糊），除法归一化去阴影
        background = cv2.GaussianBlur(gray, (0, 0), sigmaX=25)
        normalized = cv2.divide(gray, background, scale=255)
        # 轻度 CLAHE 提升局部对比度
        clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(normalized)
        return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)

    def scan(self, image: np.ndarray, enhance: bool = True) -> np.ndarray:
        """矫正单张图片。enhance=False 时只做透视矫正不做二值化（利于彩色 OCR）。"""
        if image is None or image.size == 0:
            raise ValueError("图片为空，无法扫描")

        original = image.copy()
        small, scale = self._resize(original)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 30, 120)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        quad = self._find_quad(contours)
        if quad is None:
            return self._enhance(original) if enhance else original

        pts = quad / scale
        rect = self._order_points(pts)
        tl, tr, br, bl = rect
        width_a = np.linalg.norm(br - bl)
        width_b = np.linalg.norm(tr - tl)
        height_a = np.linalg.norm(tr - br)
        height_b = np.linalg.norm(tl - bl)
        max_w = int(max(width_a, width_b))
        max_h = int(max(height_a, height_b))

        # 过滤误检：尺寸异常时回退原图
        if not (100 <= max_w <= 20000 and 100 <= max_h <= 20000):
            return self._enhance(original) if enhance else original

        dst = np.array([[0, 0], [max_w - 1, 0],
                        [max_w - 1, max_h - 1], [0, max_h - 1]],
                       dtype="float32")
        matrix = cv2.getPerspectiveTransform(rect, dst)
        warped = cv2.warpPerspective(original, matrix, (max_w, max_h))
        return self._enhance(warped) if enhance else warped


def to_bgr(pil_image) -> np.ndarray:
    """Pillow 图像 -> OpenCV BGR 数组。"""
    arr = np.array(pil_image.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def to_pil(bgr: np.ndarray):
    """OpenCV BGR 数组 -> Pillow 图像。"""
    from PIL import Image
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)
