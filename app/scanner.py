"""文档扫描矫正引擎（夸克扫描王式）。

流程：
1. 缩放加速
2. Canny 边缘 + 大核闭运算 -> 检测整张纸的四角（而非内部表格）
3. 透视变换拉正，保留整张纸（含页眉页脚）
4. 去阴影 + 形态学去噪 + 二值化，输出干净白底黑字

输入 BGR numpy 数组，输出矫正后的 BGR 数组。
"""
import cv2
import numpy as np


class DocumentScanner:
    """把拍摄的纸质文档照片矫正成整张纸的干净扫描件。"""

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
    def _order_points(pts: np.ndarray) -> np.ndarray:
        """四点统一为 [左上, 右上, 右下, 左下]。"""
        rect = np.zeros((4, 2), dtype="float32")
        sums = pts.sum(axis=1)
        rect[0] = pts[np.argmin(sums)]
        rect[2] = pts[np.argmax(sums)]
        diffs = np.diff(pts, axis=1).ravel()
        rect[1] = pts[np.argmin(diffs)]
        rect[3] = pts[np.argmax(diffs)]
        return rect

    def _find_paper_quad(self, gray: np.ndarray, content_only: bool = False):
        """检测四边形。

        content_only=False：阶段A 大核闭运算找整张纸（含页眉页脚）
        content_only=True ：直接阶段B 找内容/表格区域的紧凑四边形（利于 OCR）
        """
        h, w = gray.shape
        blur = cv2.GaussianBlur(gray, (7, 7), 0)
        edges = cv2.Canny(blur, 40, 120)

        if content_only:
            edges = cv2.morphologyEx(
                edges, cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
            contours, _ = cv2.findContours(
                edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
                if cv2.contourArea(contour) < 1000:
                    continue
                peri = cv2.arcLength(contour, True)
                approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
                if len(approx) == 4:
                    return approx.reshape(4, 2).astype("float32")
            return None

        # 阶段 A：大核闭运算，把纸张四周的断续边缘连成闭合轮廓
        for ksize in (35, 25, 15):
            kernel = cv2.getStructuringElement(
                cv2.MORPH_RECT, (ksize, ksize))
            closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
            contours, _ = cv2.findContours(
                closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                continue
            candidates = sorted(contours, key=cv2.contourArea, reverse=True)[:5]
            for contour in candidates:
                area = cv2.contourArea(contour)
                if area < w * h * 0.25:
                    continue
                peri = cv2.arcLength(contour, True)
                approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
                if len(approx) != 4:
                    continue
                x, y, bw, bh = cv2.boundingRect(contour)
                ratio = bw / max(bh, 1)
                # 纸张宽高比通常在 0.55~1.5（竖版 A4≈0.71，横版≈1.41）
                if 0.5 <= ratio <= 1.6 and area > w * h * 0.35:
                    return approx.reshape(4, 2).astype("float32")

        # 阶段 B：退化方案——普通 Canny 找最大四边形
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        edges2 = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(
            edges2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
            if cv2.contourArea(contour) < 1000:
                continue
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
            if len(approx) == 4:
                return approx.reshape(4, 2).astype("float32")
        return None

    @staticmethod
    def _expand_to_paper(rect: np.ndarray, img_shape, margin: float = 0.035) -> np.ndarray:
        """把检测到的四边形向外扩展并对齐 A4 比例，找回页眉/页脚。

        纸张顶边常因浅色背景检测偏内（把公司名标题裁掉）。策略：
        1) 先按 margin 均匀外扩，找回左右下边界
        2) 用检测到的纸张宽度按 A4 比例(高/宽=1.414)反推顶边 y，
           让纸张高度符合真实 A4，从而包含页眉
        3) 钳制在图像范围内
        """
        h, w = img_shape
        center = rect.mean(axis=0)
        expanded = center + (rect - center) * (1 + margin)

        tl, tr, br, bl = expanded
        # 纸张宽度（取上下两边均值）
        paper_w = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
        # A4 竖版：高 ≈ 宽 × 1.414
        a4_h = paper_w * 1.414
        bottom_y = (br[1] + bl[1]) / 2
        inferred_top_y = bottom_y - a4_h

        # 仅当推断的顶边在图像内且高于当前顶边时，才用它（找回页眉）
        current_top_y = (tl[1] + tr[1]) / 2
        if 0 <= inferred_top_y < current_top_y - 30:
            shift = inferred_top_y - current_top_y
            expanded[0][1] += shift  # 左上
            expanded[1][1] += shift  # 右上

        expanded[:, 0] = np.clip(expanded[:, 0], 0, w - 1)
        expanded[:, 1] = np.clip(expanded[:, 1], 0, h - 1)
        return expanded.astype("float32")

    @staticmethod
    def _denoise_binarize(gray: np.ndarray) -> np.ndarray:
        """去阴影 + 去黑点 + 二值化，得到夸克式干净白底黑字。

        关键：先用形态学开运算去除孤立噪点，再做自适应阈值，
        避免 CLAHE 放大噪点造成的黑点。
        """
        # 1) 高斯降噪，压掉椒盐噪点
        denoised = cv2.GaussianBlur(gray, (3, 3), 0)

        # 2) 光照归一化去阴影（大核背景估计）
        background = cv2.GaussianBlur(denoised, (0, 0), sigmaX=25)
        normalized = cv2.divide(denoised, background, scale=255)

        # 3) Otsu 全局二值化（整张纸光照已均匀，全局阈值比自适应更干净、无噪点）
        _, binary = cv2.threshold(normalized, 0, 255,
                                  cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # 4) 形态学开运算去除孤立黑点（小核，保留笔画）
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

        # 5) 膨胀一点点，让变细的笔画恢复连贯
        kernel2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
        cleaned = cv2.dilate(cleaned, kernel2, iterations=1)
        return cleaned

    def detect_quad(self, image: np.ndarray, full_page: bool = True):
        """检测纸张四角，返回原图坐标系下的 [左上,右上,右下,左下]。

        供手动裁剪编辑器获取初始四角；返回 None 表示检测失败。
        """
        if image is None or image.size == 0:
            return None
        small, scale = self._resize(image)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        quad = self._find_paper_quad(gray, content_only=not full_page)
        if quad is None:
            return None
        rect = self._order_points(quad / scale)
        if full_page:
            rect = self._expand_to_paper(rect, image.shape[:2])
        return rect.astype("float32")

    @staticmethod
    def warp_by_quad(image: np.ndarray, rect: np.ndarray) -> np.ndarray:
        """按指定四角（原图坐标）做透视变换拉正，不做增强。"""
        rect = np.asarray(rect, dtype="float32")
        tl, tr, br, bl = rect
        width_a = np.linalg.norm(br - bl)
        width_b = np.linalg.norm(tr - tl)
        height_a = np.linalg.norm(tr - br)
        height_b = np.linalg.norm(tl - bl)
        max_w = int(max(width_a, width_b))
        max_h = int(max(height_a, height_b))
        if not (100 <= max_w <= 20000 and 100 <= max_h <= 20000):
            return image.copy()
        dst = np.array([[0, 0], [max_w - 1, 0],
                        [max_w - 1, max_h - 1], [0, max_h - 1]],
                       dtype="float32")
        matrix = cv2.getPerspectiveTransform(rect, dst)
        return cv2.warpPerspective(image, matrix, (max_w, max_h))

    @staticmethod
    def enhance_scan(work: np.ndarray) -> np.ndarray:
        """把已拉正的图去阴影/去黑点/二值化，得到干净扫描件。"""
        if work.ndim == 3:
            work_gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
        else:
            work_gray = work
        binary = DocumentScanner._denoise_binarize(work_gray)
        return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)

    def scan(self, image: np.ndarray, enhance: bool = True,
             full_page: bool = True,
             manual_quad: np.ndarray | None = None) -> np.ndarray:
        """矫正单张图片。

        Args:
            enhance: True 输出去阴影二值化的干净扫描件；False 保留灰度供 OCR
            full_page: True 检测整张纸（含页眉页脚，A4 比例）；
                       False 检测内容/表格区域（紧凑，利于表格线检测与 OCR）
            manual_quad: 手动指定的四角（原图坐标），提供时跳过自动检测
        """
        if image is None or image.size == 0:
            raise ValueError("图片为空，无法扫描")

        original = image.copy()
        if manual_quad is not None:
            rect = np.asarray(manual_quad, dtype="float32")
            work = self.warp_by_quad(original, rect)
        else:
            small, scale = self._resize(original)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            quad = self._find_paper_quad(gray, content_only=not full_page)
            if quad is None:
                work = original
            else:
                rect = self._order_points(quad / scale)
                # 仅整张纸扫描件外扩 + A4 校正；OCR 用紧凑内容区避免表格线模糊
                if full_page:
                    rect = self._expand_to_paper(rect, original.shape[:2])
                work = self.warp_by_quad(original, rect)

        if not enhance:
            return work
        return self.enhance_scan(work)


def to_bgr(pil_image) -> np.ndarray:
    """Pillow 图像 -> OpenCV BGR 数组。"""
    arr = np.array(pil_image.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def to_pil(bgr: np.ndarray):
    """OpenCV BGR 数组 -> Pillow 图像。"""
    from PIL import Image
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)
