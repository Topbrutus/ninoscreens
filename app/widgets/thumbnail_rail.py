from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.config import APP_MARGIN, PALETTE, THUMBNAIL_IMAGE_SIZE
from app.state import TileState, TileVisualStatus


class ThumbnailCard(QFrame):
    clicked = Signal(int)

    def __init__(self, tile_id: int, parent=None) -> None:
        super().__init__(parent)
        self.tile_id = tile_id
        self.setObjectName("ThumbnailCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("active", False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self.status_dot = QLabel()
        self.status_dot.setFixedSize(12, 12)

        self.index_label = QLabel(f"#{tile_id + 1}")
        self.index_label.setObjectName("SecondaryText")

        self.site_icon_label = QLabel()
        self.site_icon_label.setFixedSize(16, 16)
        self.site_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_label = QLabel(f"Carreau {tile_id + 1}")
        self.title_label.setWordWrap(True)

        header.addWidget(self.status_dot, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(self.index_label, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(self.site_icon_label, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(self.title_label, 1)

        self.preview_label = QLabel()
        self.preview_label.setFixedSize(THUMBNAIL_IMAGE_SIZE)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setScaledContents(False)

        root.addLayout(header)
        root.addWidget(self.preview_label, 0, Qt.AlignmentFlag.AlignCenter)

        self._update_status_dot(PALETTE.empty)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self.tile_id)
        super().mousePressEvent(event)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def update_from_state(self, state: TileState, active: bool) -> None:
        self.set_active(active)
        self.title_label.setText(state.display_title)

        if state.status == TileVisualStatus.LOADING:
            color = PALETTE.warning
        elif state.status == TileVisualStatus.READY:
            color = PALETTE.success
        elif state.status == TileVisualStatus.ERROR:
            color = PALETTE.error
        else:
            color = PALETTE.empty
        self._update_status_dot(color)

        icon_pixmap = state.site_icon or self._placeholder_icon(state)
        self.site_icon_label.setPixmap(
            icon_pixmap.scaled(
                QSize(16, 16),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

        pixmap = state.thumbnail or self._placeholder_preview(state)
        scaled = pixmap.scaled(
            THUMBNAIL_IMAGE_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)

    def _update_status_dot(self, color: str) -> None:
        pixmap = QPixmap(QSize(12, 12))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, 11, 11)
        painter.end()
        self.status_dot.setPixmap(pixmap)

    def _placeholder_preview(self, state: TileState) -> QPixmap:
        pixmap = QPixmap(THUMBNAIL_IMAGE_SIZE)
        pixmap.fill(QColor(PALETTE.panel_bg))
        painter = QPainter(pixmap)
        painter.setPen(QColor(PALETTE.text_secondary))
        painter.drawText(
            pixmap.rect(),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            state.display_title,
        )
        painter.end()
        return pixmap

    def _placeholder_icon(self, state: TileState) -> QPixmap:
        pixmap = QPixmap(QSize(16, 16))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(PALETTE.panel_bg))
        painter.setPen(QColor(PALETTE.border))
        painter.drawRoundedRect(0, 0, 15, 15, 4, 4)
        painter.setPen(QColor(PALETTE.text_secondary))
        fallback = (state.domain[:1] or state.display_title[:1] or str(state.tile_id + 1)).upper()
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, fallback)
        painter.end()
        return pixmap


class ThumbnailRail(QFrame):
    tile_selected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ThumbnailRail")
        self.setFixedWidth(240)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(APP_MARGIN, APP_MARGIN, APP_MARGIN, APP_MARGIN)
        outer.setSpacing(10)

        title = QLabel("Carreaux")
        title.setObjectName("SecondaryText")
        outer.addWidget(title)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.container = QWidget()
        self.cards_layout = QVBoxLayout(self.container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(10)

        self.cards: dict[int, ThumbnailCard] = {}
        for tile_id in range(9):
            card = ThumbnailCard(tile_id)
            card.clicked.connect(self.tile_selected.emit)
            self.cards[tile_id] = card
            self.cards_layout.addWidget(card)

        self.cards_layout.addStretch(1)
        self.scroll.setWidget(self.container)
        outer.addWidget(self.scroll, 1)

    def refresh(self, states: Iterable[TileState], active_tile_id: int | None) -> None:
        for state in states:
            card = self.cards[state.tile_id
            card.update_from_state(state, active_tile_id == state.tile_id)
