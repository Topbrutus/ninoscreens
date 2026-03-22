from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QWidget

try:  # pragma: no cover
    from PySide6.QtTextToSpeech import QTextToSpeech
except Exception:  # pragma: no cover
    QTextToSpeech = None


class AudioEvent(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    BLOCKED = "blocked"
    TASK_COMPLETE = "task_complete"
    API_CONNECTED = "api_connected"


@dataclass
class AudioFeedbackState:
    sound_enabled: bool = True
    voice_enabled: bool = False
    speak_blocked: bool = True
    speak_task_complete: bool = True
    speak_api_connected: bool = False


class AudioFeedbackManager(QObject):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = AudioFeedbackState()
        self._last_sound_at = 0.0
        self._last_voice_at = 0.0
        self._min_sound_gap_seconds = 0.65
        self._min_voice_gap_seconds = 1.8
        self._messages: deque[str] = deque(maxlen=30)
        self._tts = QTextToSpeech(self) if QTextToSpeech is not None else None

    @property
    def voice_available(self) -> bool:
        return self._tts is not None

    def set_sound_enabled(self, enabled: bool) -> None:
        self.state.sound_enabled = enabled

    def set_voice_enabled(self, enabled: bool) -> None:
        self.state.voice_enabled = enabled and self.voice_available

    def set_speak_blocked(self, enabled: bool) -> None:
        self.state.speak_blocked = enabled

    def set_speak_task_complete(self, enabled: bool) -> None:
        self.state.speak_task_complete = enabled

    def set_speak_api_connected(self, enabled: bool) -> None:
        self.state.speak_api_connected = enabled

    def notify(self, event: AudioEvent, message: str = "") -> None:
        clean = message.strip()
        if clean:
            self._messages.appendleft(clean)
        self._play_pattern(event)
        self._speak_if_needed(event, clean)

    def latest_messages(self, limit: int = 10) -> list[str]:
        return list(self._messages)[: max(1, limit)]

    def _play_pattern(self, event: AudioEvent) -> None:
        if not self.state.sound_enabled:
            return
        now = time.monotonic()
        if now - self._last_sound_at < self._min_sound_gap_seconds:
            return
        self._last_sound_at = now
        pattern = {
            AudioEvent.SUCCESS: [0],
            AudioEvent.ERROR: [0, 180],
            AudioEvent.BLOCKED: [0, 180, 360],
            AudioEvent.TASK_COMPLETE: [0, 220],
            AudioEvent.API_CONNECTED: [0],
        }.get(event, [0])
        for delay in pattern:
            QTimer.singleShot(delay, QApplication.beep)

    def _speak_if_needed(self, event: AudioEvent, message: str) -> None:
        if not self.state.voice_enabled or not self.voice_available or not message:
            return
        should_speak = (
            (event is AudioEvent.BLOCKED and self.state.speak_blocked)
            or (event is AudioEvent.TASK_COMPLETE and self.state.speak_task_complete)
            or (event is AudioEvent.API_CONNECTED and self.state.speak_api_connected)
        )
        if not should_speak:
            return
        now = time.monotonic()
        if now - self._last_voice_at < self._min_voice_gap_seconds:
            return
        self._last_voice_at = now
        self._tts.say(message[:180])
