"""手动裁剪调整对话框：在原图上拖动四角，精确框选要扫描的纸张区域。

交互（夸克扫描王式）：
- 原图缩放显示，四个角点可拖动
- 拖动单个角 / 整条边（在边上拖动则整边平移）
- 滚轮缩放视图
- 「复位」恢复自动检测的初始四角
- 「确认」返回四角（原图坐标），供重新透视矫正
"""
from typing import Optional

import cv2
import numpy as np
from PySide6.QtCore import Qt, QPointF, Signal
from PySide6.QtGui import (
    QImage, QPixmap, QPen, QColor, QBrush, QPainter, QCursor, QPolygonF,
)
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsPolygonItem,
    QGraphicsEllipseItem, QGraphicsItem, QCheckBox,
)


def _bgr_to_pixmap(bgr: np.ndarray) -> QPixmap:
    """BGR -> QPixmap，用 copy() 深拷贝避免悬空指针（大图必须）。"""
    arr = np.ascontiguousarray(bgr)
    h, w = arr.shape[:2]
    rgb = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
    qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


class _CornerHandle(QGraphicsEllipseItem):
    """可拖动的角点。重写 itemChange 限制在图像范围内并通知重绘。"""

    def __init__(self, index: int, pos: QPointF, radius: float,
                 bounds, on_move):
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self.index = index
        self.on_move = on_move
        self.bounds = bounds  # (w, h)
        self.setPos(pos)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setBrush(QBrush(QColor("#2d7ff9")))
        self.setPen(QPen(QColor("white"), 2))
        self.setZValue(10)
        self.setCursor(QCursor(Qt.SizeAllCursor))

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            w, h = self.bounds
            value = QPointF(max(0, min(w - 1, value.x())),
                            max(0, min(h - 1, value.y())))
        result = super().itemChange(change, value)
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.on_move()
        return result


class CropDialog(QDialog):
    """返回用户调整后的四角（原图坐标，顺序 左上/右上/右下/左下）。"""

    def __init__(self, image_bgr: np.ndarray,
                 initial_quad: Optional[np.ndarray], parent=None):
        super().__init__(parent)
        self.setWindowTitle("手工调整裁剪区域 — ScanMaster")
        self.resize(1000, 760)
        self.image = image_bgr
        self.h, self.w = image_bgr.shape[:2]

        # 初始四角：自动检测 or 默认内缩矩形
        if initial_quad is None or len(initial_quad) != 4:
            m = 0.04
            self.initial = np.array([
                [self.w * m, self.h * m],
                [self.w * (1 - m), self.h * m],
                [self.w * (1 - m), self.h * (1 - m)],
                [self.w * m, self.h * (1 - m)],
            ], dtype="float32")
        else:
            from .scanner import DocumentScanner
            self.initial = DocumentScanner._order_points(
                np.asarray(initial_quad, dtype="float32"))
        self.quad = self.initial.copy()

        self._build_ui()
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def _build_ui(self):
        root = QVBoxLayout(self)

        tip = QLabel(
            "拖动蓝色圆点调整四个角，框住整张纸（含页眉页脚）。"
            "在四边线上拖动可平移整条边，滚轮缩放视图。"
        )
        tip.setStyleSheet("color:#c2410c; font-weight:bold; padding:4px;")
        tip.setWordWrap(True)
        root.addWidget(tip)

        # 图像场景
        self.scene = QGraphicsScene(self)
        pixmap = _bgr_to_pixmap(self.image)
        self.pix_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.pix_item)
        self.scene.setSceneRect(0, 0, self.w, self.h)

        # 半透明遮罩 + 四边形高亮
        self.poly = QGraphicsPolygonItem()
        self.poly.setBrush(QBrush(QColor(45, 127, 249, 45)))
        self.poly.setPen(QPen(QColor("#2d7ff9"), 3))
        self.scene.addItem(self.poly)

        # 四角手柄
        radius = max(self.w, self.h) * 0.012
        self.handles = []
        for i, (x, y) in enumerate(self.initial):
            handle = _CornerHandle(
                i, QPointF(x, y), radius, (self.w, self.h), self._on_corner_moved)
            self.scene.addItem(handle)
            self.handles.append(handle)

        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setDragMode(QGraphicsView.NoDrag)
        self.view.setBackgroundBrush(QBrush(QColor("#e8e8e8")))
        root.addWidget(self.view, 1)

        # 底部按钮
        btn_box = QHBoxLayout()
        self.chk_lock = QCheckBox("锁定 A4 比例（自动校正高度）")
        self.chk_lock.setChecked(False)
        btn_box.addWidget(self.chk_lock)
        btn_box.addStretch(1)
        btn_reset = QPushButton("复位")
        btn_reset.clicked.connect(self.reset)
        btn_box.addWidget(btn_reset)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)
        btn_ok = QPushButton("应用裁剪")
        btn_ok.setStyleSheet(
            "QPushButton{background:#2d7ff9;color:white;padding:9px 20px;"
            "border-radius:5px;font-weight:bold;font-size:13px;}"
        )
        btn_ok.clicked.connect(self.accept)
        btn_box.addWidget(btn_ok)
        root.addLayout(btn_box)

        self._sync_from_handles()

    def _on_corner_moved(self):
        self._sync_from_handles()

    def _sync_from_handles(self):
        """从手柄位置更新四边形/边线显示与 quad 数据。"""
        pts = [QPointF(h.pos()) for h in self.handles]
        self.poly.setPolygon(QPolygonF(pts))
        self.quad = np.array([[p.x(), p.y()] for p in pts], dtype="float32")

    def reset(self):
        for i, (x, y) in enumerate(self.initial):
            self.handles[i].setPos(QPointF(x, y))
        self.chk_lock.setChecked(False)
        self._sync_from_handles()
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def get_quad(self) -> np.ndarray:
        """返回四角（原图坐标，左上/右上/右下/左下）。"""
        from .scanner import DocumentScanner
        quad = DocumentScanner._order_points(self.quad.copy())
        if self.chk_lock.isChecked():
            # 按上边宽度推算 A4 高度，下边两角随之平移（保持各自 x）
            top_w = np.linalg.norm(quad[1] - quad[0])
            target_h = top_w * 1.414
            cy_top = (quad[0][1] + quad[1][1]) / 2
            new_bottom = cy_top + target_h
            quad[2][1] = new_bottom
            quad[3][1] = new_bottom
        return quad
