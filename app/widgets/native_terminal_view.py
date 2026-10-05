from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QPlainTextEdit


_OSC_RE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\\\)", re.DOTALL)
_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SINGLE_ESC_RE = re.compile(r"\x1b[@-_]")


def terminal_plain_text(raw: str) -> str:
    text = _OSC_RE.sub("", raw)
    text = _CSI_RE.sub("", text)
    text = _SINGLE_ESC_RE.sub("", text)

    lines: list[list[str]] = [[]]
    column = 0
    for char in text:
        if char == "\n":
            lines.append([])
            column = 0
            continue
        if char == "\r":
            column = 0
            continue
        if char == "\b":
            column = max(0, column - 1)
            continue
        if char == "\t":
            target = ((column // 8) + 1) * 8
            line = lines[-1]
            while len(line) < target:
                line.append(" ")
            column = target
            continue
        if ord(char) < 32 and char not in {"\u00a0"}:
            continue

        line = lines[-1]
        while len(line) < column:
            line.append(" ")
        if column < len(line):
            line[column] = char
        else:
            line.append(char)
        column += 1

    return "\n".join("".join(line) for line in lines)


class NativeTerminalView(QPlainTextEdit):
    input_requested = Signal(str)
    interrupt_requested = Signal()
    paste_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._last_text = ""
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.setStyleSheet(
            "QPlainTextEdit { background: #14171c; color: #edf2f7; "
            "border: 1px solid #313a46; padding: 8px; selection-background-color: #315f87; }"
        )

    def update_from_raw(self, raw: str) -> None:
        text = terminal_plain_text(raw)
        if text == self._last_text:
            return
        if self.textCursor().hasSelection():
            return

        scroll = self.verticalScrollBar()
        old_value = scroll.value()
        was_at_bottom = old_value >= max(0, scroll.maximum() - 2)
        self.setPlainText(text)
        self._last_text = text
        if was_at_bottom:
            scroll.setValue(scroll.maximum())
        else:
            scroll.setValue(min(old_value, scroll.maximum()))

    def dump_text(self) -> str:
        return self.toPlainText()

    def keyPressEvent(self, event) -> None:
        modifiers = event.modifiers()
        key = event.key()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)

        if ctrl and shift and key == Qt.Key.Key_C:
            self.copy()
            return
        if ctrl and shift and key == Qt.Key.Key_V:
            self.paste_requested.emit()
            return
        if ctrl and key == Qt.Key.Key_C:
            if self.textCursor().hasSelection():
                self.copy()
            else:
                self.interrupt_requested.emit()
            return
        if ctrl and key == Qt.Key.Key_V:
            self.paste_requested.emit()
            return

        special = {
            Qt.Key.Key_Return: "\r",
            Qt.Key.Key_Enter: "\r",
            Qt.Key.Key_Backspace: "\x7f",
            Qt.Key.Key_Tab: "\t",
            Qt.Key.Key_Escape: "\x1b",
            Qt.Key.Key_Up: "\x1b[A",
            Qt.Key.Key_Down: "\x1b[B",
            Qt.Key.Key_Right: "\x1b[C",
            Qt.Key.Key_Left: "\x1b[D",
            Qt.Key.Key_Home: "\x1b[H",
            Qt.Key.Key_End: "\x1b[F",
            Qt.Key.Key_Insert: "\x1b[2~",
            Qt.Key.Key_Delete: "\x1b[3~",
            Qt.Key.Key_PageUp: "\x1b[5~",
            Qt.Key.Key_PageDown: "\x1b[6~",
        }
        if key in special:
            self.input_requested.emit(special[key])
            return

        if ctrl:
            key_value = int(key)
            first = int(Qt.Key.Key_A)
            last = int(Qt.Key.Key_Z)
            if first <= key_value <= last:
                self.input_requested.emit(chr(key_value - first + 1))
                return

        text = event.text()
        if text and not (modifiers & Qt.KeyboardModifier.MetaModifier):
            self.input_requested.emit(("\x1b" if alt else "") + text)
            return

        super().keyPressEvent(event)
