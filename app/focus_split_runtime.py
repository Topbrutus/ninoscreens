
from __future__ import annotations
from typing import Any
from PySide6.QtCore import QSize, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame,QGridLayout,QHBoxLayout,QLabel,QPushButton,QStackedWidget,QVBoxLayout,QWidget
from app.config import PAGE_COUNT,TILES_PER_PAGE,TOOLBAR_BUTTON_SIZE

def _alive(w: Any) -> bool:
    if w is None: return False
    try: w.objectName()
    except RuntimeError: return False
    return True

def _polish(w: QWidget | None) -> None:
    if not w: return
    s = w.style()
    if not s: return
    s.unpolish(w); s.polish(w); w.update()

def _icon_for(tile: Any) -> QIcon | None:
    if not tile or not getattr(tile, "state", None) or not tile.state.has_content: return None
    page = getattr(tile, "_page", None)
    fn = getattr(page, "icon", None)
    if not callable(fn): return None
    try: icon = fn()
    except TypeError: return None
    return None if icon is None or icon.isNull() else icon

class SplitSelector(QFrame):
    picked = Signal(int)
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(8)
        tip = QLabel("Choisissez la page à ouvrir à droite."); tip.setObjectName("MutedText")
        root.addWidget(tip)
        host = QWidget(); grid = QGridLayout(host)
        grid.setContentsMargins(0,0,0,0); grid.setHorizontalSpacing(4); grid.setVerticalSpacing(4)
        root.addWidget(host, 1)
        self.buttons: dict[int, QPushButton] = {}
        for i in range(PAGE_COUNT * TILES_PER_PAGE):
            b = QPushButton(str(i + 1)); b.setProperty("compact", True); b.setProperty("role", "memory-slot")
            b.setProperty("fillState", "empty"); b.setProperty("borderState", "idle"); b.setProperty("active", False)
            b.setMinimumSize(42, 34)
            b.clicked.connect(lambda _=False, idx=i: self.picked.emit(idx))
            r, c = divmod(i, TILES_PER_PAGE); grid.addWidget(b, r, c); self.buttons[i] = b

    def refresh(self, tiles: dict[int, Any], primary: int) -> None:
        for i, b in self.buttons.items():
            t = tiles.get(i); loaded = bool(t and getattr(t, "state", None) and t.state.has_content)
            b.setEnabled(loaded and i != primary)
            b.setProperty("fillState", "cool" if loaded else "empty")
            b.setProperty("borderState", "ready" if loaded else "idle")
            b.setText(str(i + 1))
            icon = _icon_for(t)
            b.setIcon(icon if icon else QIcon())
            if icon: b.setIconSize(QSize(16, 16))
            b.setToolTip("Page principale actuelle" if i == primary else (t.state.display_title if loaded else f"Carreau {i+1} vide"))
            _polish(b)

class FocusSplit:
    def __init__(self, window: Any) -> None:
        self.w = window; self.fv = window.focus_view
        self.states: dict[int, int | None] = {}
        self.primary: int | None = None; self.secondary: int | None = None
        self.panel = self.title = self.close = self.stack = self.selector = self.host = self.host_layout = None

    def install(self) -> None:
        self._install_panel()
        self.timer = QTimer(self.w); self.timer.setInterval(300); self.timer.timeout.connect(self.tick); self.timer.start()
        for t in self.w.tiles.values():
            t.focus_requested.connect(lambda _id: self.sync())
            t.grid_requested.connect(lambda _id: self.sync())
            t.state_changed.connect(lambda _s: self.sync())
        self.fv.tile_switch_requested.connect(lambda _id: self.sync())
        self.w.main_stack.currentChanged.connect(lambda _i: self.sync())
        self.w.page_stack.currentChanged.connect(lambda _i: self.sync())
        self.w.focus_exit_button.clicked.connect(self.sync)
        self.sync()

    def _install_panel(self) -> None:
        root = self.fv.layout(); body = root.itemAt(0).layout() if root and root.count() else None
        if body is None: return
        self.panel = QFrame(); self.panel.setObjectName("SplitRightPanel")
        lay = QVBoxLayout(self.panel); lay.setContentsMargins(0,0,0,0); lay.setSpacing(8)
        head = QWidget(); h = QHBoxLayout(head); h.setContentsMargins(0,0,0,0); h.setSpacing(8)
        self.title = QLabel("Split"); self.title.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.close = QPushButton("X"); self.close.setProperty("compact", True); self.close.setProperty("role", "danger")
        self.close.setFixedSize(TOOLBAR_BUTTON_SIZE); self.close.clicked.connect(self.to_selector)
        h.addWidget(self.title, 1); h.addWidget(self.close, 0)
        self.stack = QStackedWidget()
        self.selector = SplitSelector(); self.selector.picked.connect(self.pick)
        self.host = QWidget(); self.host_layout = QVBoxLayout(self.host); self.host_layout.setContentsMargins(0,0,0,0); self.host_layout.setSpacing(0)
        self.stack.addWidget(self.selector); self.stack.addWidget(self.host)
        lay.addWidget(head); lay.addWidget(self.stack, 1)
        body.insertWidget(1, self.panel, 1); self.panel.hide()

    def tick(self) -> None:
        self.ensure_buttons(); self.sync(); self.refresh_buttons()

    def ensure_buttons(self) -> None:
        for t in self.w.tiles.values():
            if getattr(t, "_browser_container", None) is None: continue
            b = getattr(t, "_split_btn", None)
            if _alive(b): continue
            cont = t._browser_container; l = cont.layout() if cont else None
            if l is None or l.count() == 0: continue
            head = l.itemAt(0).widget(); hl = head.layout() if head else None
            if hl is None: continue
            b = QPushButton("Split"); b.setProperty("compact", True); b.setProperty("role", "accent")
            b.setFixedHeight(TOOLBAR_BUTTON_SIZE.height()); b.setMinimumWidth(58)
            b.clicked.connect(lambda _=False, tid=t.tile_id: self.toggle(tid))
            idx = hl.indexOf(getattr(t, "close_button", None))
            hl.insertWidget(idx if idx >= 0 else hl.count(), b); t._split_btn = b

    def refresh_buttons(self) -> None:
        for t in self.w.tiles.values():
            b = getattr(t, "_split_btn", None)
            if not _alive(b): continue
            vis = bool(t.state.has_content) and bool(getattr(t, "_toolbar_focus_mode", False)) and not bool(getattr(t, "_in_secondary_split", False)) and self.w.main_stack.currentWidget() is self.fv and self.w._focused_tile_id == t.tile_id
            b.setVisible(vis)
            active = self.primary == t.tile_id and t.tile_id in self.states
            b.setProperty("role", "nav" if active else "accent")
            b.setToolTip("Fermer complètement le split" if active else "Ouvrir un split")
            _polish(b)

    def sync(self) -> None:
        cur = self.w._focused_tile_id if self.w.main_stack.currentWidget() is self.fv else None
        if cur != self.primary:
            self.detach_secondary(); self.primary = cur
        if cur is None: self.hide_panel(); return
        st = self.states.get(cur, "__off__")
        if st == "__off__": self.hide_panel(); return
        if st is None: self.show_selector(cur); return
        self.show_secondary(cur, st)

    def toggle(self, tid: int) -> None:
        if tid != self.primary: return
        if tid in self.states:
            self.detach_secondary(); self.states.pop(tid, None); self.hide_panel()
        else:
            self.states[tid] = None; self.show_selector(tid)
        self.refresh_buttons()

    def pick(self, sid: int) -> None:
        if self.primary is None: return
        self.states[self.primary] = sid; self.show_secondary(self.primary, sid); self.refresh_buttons()

    def to_selector(self) -> None:
        if self.primary is None: return
        self.states[self.primary] = None; self.show_selector(self.primary); self.refresh_buttons()

    def show_selector(self, primary: int) -> None:
        if not self.panel or not self.stack or not self.selector: return
        self.detach_secondary(); self.selector.refresh(self.w.tiles, primary)
        if self.title: self.title.setText("Choisir une page")
        if self.close: self.close.setVisible(False)
        self.stack.setCurrentWidget(self.selector); self.panel.show()

    def show_secondary(self, primary: int, sid: int) -> None:
        if not self.panel or not self.stack or not self.host or not self.host_layout: return
        if sid == primary:
            self.states[primary] = None; self.show_selector(primary); return
        t = self.w.tiles.get(sid)
        if t is None or not t.state.has_content:
            self.states[primary] = None; self.show_selector(primary); return
        if self.secondary != sid:
            self.detach_secondary()
            self.w._detach_tile_from_grid(sid)
            self.set_secondary_mode(t, True)
            self.clear_host(); self.host_layout.addWidget(t, 1); self.secondary = sid
        if self.title: self.title.setText(t.state.display_title)
        if self.close: self.close.setVisible(True)
        self.stack.setCurrentWidget(self.host); self.panel.show()

    def clear_host(self) -> None:
        if self.host_layout is None: return
        while self.host_layout.count():
            it = self.host_layout.takeAt(0); w = it.widget()
            if w is not None: w.setParent(None)

    def detach_secondary(self) -> None:
        if self.secondary is None:
            self.clear_host(); return
        sid = self.secondary; t = self.w.tiles.get(sid); self.clear_host()
        if t is not None:
            self.set_secondary_mode(t, False)
            self.w.page_grids[self.w._tile_page_index(sid)].place_tile(t, sid % TILES_PER_PAGE)
        self.secondary = None

    def set_secondary_mode(self, tile: Any, on: bool) -> None:
        tile._in_secondary_split = on
        for name in ("memory_button", "focus_button", "close_button"):
            w = getattr(tile, name, None)
            if _alive(w): w.setVisible(not on)
        b = getattr(tile, "_split_btn", None)
        if _alive(b): b.setVisible(False)

    def hide_panel(self) -> None:
        self.detach_secondary()
        if self.panel: self.panel.hide()
        if self.close: self.close.setVisible(False)
        if self.title: self.title.setText("Split")

def apply_runtime_focus_split(window: Any) -> None:
    window._focus_split = FocusSplit(window)
    window._focus_split.install()
