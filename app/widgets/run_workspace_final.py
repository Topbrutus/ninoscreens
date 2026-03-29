from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from datetime import datetime

from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

PIPEWIRE_MIC = "alsa_input.usb-Sony_CEVCECM-03.iec958-stereo"


class _VoiceWorker(QObject):
    recognized = Signal(str)
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._running = False
        self._device = PIPEWIRE_MIC

    def listen_once(self) -> None:
        self._running = True

        def _run() -> None:
            tmp = tempfile.mktemp(suffix=".wav")
            try:
                rec = subprocess.Popen(
                    ["parecord", f"--device={self._device}",
                     "--file-format=wav", tmp],
                    stderr=subprocess.DEVNULL
                )
                import time
                time.sleep(5)
                rec.terminate()
                rec.wait()

                import speech_recognition as sr
                recognizer = sr.Recognizer()
                with sr.AudioFile(tmp) as source:
                    audio = recognizer.record(source)
                text = recognizer.recognize_google(audio, language="fr-FR")
                self.recognized.emit(text)
            except Exception as exc:
                self.error.emit(f"Erreur micro: {exc}")
            finally:
                self._running = False
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()


class MicButton(QPushButton):
    mic_activated = Signal()
    mic_deactivated = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("MIC", parent)
        self.setProperty("compact", True)
        self.setToolTip("Micro global — cliquer pour parler")
        self.setCheckable(True)
        self.setFixedWidth(48)
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, active: bool) -> None:
        self.setText("REC" if active else "MIC")
        if active:
            self.mic_activated.emit()
        else:
            self.mic_deactivated.emit()

    def set_listening(self, listening: bool) -> None:
        self.setChecked(listening)


class RunWorkspace(QFrame):
    prompt_submitted = Signal(str)
    window_command = Signal(str)
    mic_state_changed = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ControlPanel")

        self._mode = "text"
        self._mic_active = False
        self._mic_device = PIPEWIRE_MIC
        self._voice_worker = _VoiceWorker()
        self._voice_worker.recognized.connect(self._on_voice_recognized)
        self._voice_worker.error.connect(self._on_voice_error)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("RUN / Corvo")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")

        subtitle = QLabel("Espace dedie a Run : journal, terminal, voix et controle des fenetres.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("MutedText")

        # --- Boutons outils ---
        tools_frame = QFrame()
        tools_layout = QGridLayout(tools_frame)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setHorizontalSpacing(8)
        tools_layout.setVerticalSpacing(8)

        self.tool_buttons: dict[str, QPushButton] = {}

        btn_monitor = QPushButton("Monitor")
        btn_monitor.setProperty("compact", True)
        btn_monitor.setEnabled(True)
        tools_layout.addWidget(btn_monitor, 0, 0)
        self.tool_buttons["monitor"] = btn_monitor

        self.btn_voice = QPushButton("Voix")
        self.btn_voice.setProperty("compact", True)
        self.btn_voice.setCheckable(True)
        self.btn_voice.clicked.connect(self._toggle_voice_mode)
        tools_layout.addWidget(self.btn_voice, 0, 1)
        self.tool_buttons["voice"] = self.btn_voice

        btn_audio = QPushButton("Audio")
        btn_audio.setProperty("compact", True)
        btn_audio.setEnabled(False)
        tools_layout.addWidget(btn_audio, 0, 2)

        btn_api = QPushButton("API")
        btn_api.setProperty("compact", True)
        btn_api.setEnabled(False)
        tools_layout.addWidget(btn_api, 1, 0)

        self.btn_micro = MicButton()
        self.btn_micro.setToolTip("Micro — cliquer pour choisir et activer")
        self.btn_micro.mic_activated.connect(self._toggle_mic_drawer)
        self.btn_micro.mic_deactivated.connect(self._toggle_mic_drawer)
        tools_layout.addWidget(self.btn_micro, 1, 1)
        self.tool_buttons["micro"] = self.btn_micro

        btn_tools = QPushButton("Outils+")
        btn_tools.setProperty("compact", True)
        btn_tools.setEnabled(False)
        tools_layout.addWidget(btn_tools, 1, 2)

        # --- Drawer micro ---
        self.mic_drawer = QFrame()
        self.mic_drawer.setObjectName("TopBar")
        self.mic_drawer.hide()
        drawer_layout = QVBoxLayout(self.mic_drawer)
        drawer_layout.setContentsMargins(8, 8, 8, 8)
        drawer_layout.setSpacing(6)
        drawer_title = QLabel("Choisir le micro :")
        drawer_title.setObjectName("MutedText")
        drawer_layout.addWidget(drawer_title)

        self.mic_list = QListWidget()
        self.mic_list.setMaximumHeight(100)

        try:
            result = subprocess.run(
                ["pactl", "list", "sources", "short"],
                capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    name = parts[1]
                    item = QListWidgetItem(name)
                    self.mic_list.addItem(item)
                    if "input" in name or "CEVCECM" in name:
                        self.mic_list.setCurrentItem(item)
        except Exception:
            self.mic_list.addItem(QListWidgetItem(PIPEWIRE_MIC))
            self.mic_list.setCurrentRow(0)

        drawer_layout.addWidget(self.mic_list)

        btn_activate = QPushButton("Activer ce micro")
        btn_activate.setProperty("role", "accent")
        btn_activate.clicked.connect(self._activate_selected_mic)
        drawer_layout.addWidget(btn_activate)

        # --- Mode toggle ---
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(8)
        mode_label = QLabel("Mode :")
        mode_label.setObjectName("MutedText")

        self.btn_mode_text = QPushButton("Ecriture")
        self.btn_mode_text.setProperty("compact", True)
        self.btn_mode_text.setCheckable(True)
        self.btn_mode_text.setChecked(True)
        self.btn_mode_text.clicked.connect(lambda: self._set_mode("text"))

        self.btn_mode_voice = QPushButton("Controle vocal")
        self.btn_mode_voice.setProperty("compact", True)
        self.btn_mode_voice.setCheckable(True)
        self.btn_mode_voice.clicked.connect(lambda: self._set_mode("voice"))

        mode_row.addWidget(mode_label)
        mode_row.addWidget(self.btn_mode_text)
        mode_row.addWidget(self.btn_mode_voice)
        mode_row.addStretch()

        # --- Controle fenetres ---
        win_frame = QFrame()
        win_frame.setObjectName("TopBar")
        win_layout = QHBoxLayout(win_frame)
        win_layout.setContentsMargins(8, 6, 8, 6)
        win_layout.setSpacing(6)

        win_label = QLabel("Fenetres :")
        win_label.setObjectName("MutedText")
        win_layout.addWidget(win_label)

        for cmd, tip in [
            ("focus", "Focus carreau N"),
            ("split", "Split carreaux"),
            ("page", "Changer page"),
            ("grille", "Retour grille"),
        ]:
            b = QPushButton(cmd.capitalize())
            b.setProperty("compact", True)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, c=cmd: self._send_window_command(c))
            win_layout.addWidget(b)

        self.win_input = QLineEdit()
        self.win_input.setPlaceholderText("focus 3 / split 1+2 / page 2")
        self.win_input.setFixedWidth(200)
        self.win_input.returnPressed.connect(self._submit_window_command)
        win_layout.addWidget(self.win_input)
        win_layout.addStretch()

        # --- Monitor ---
        self.monitor = QTextEdit()
        self.monitor.setReadOnly(True)
        self.monitor.setMinimumHeight(200)

        # --- Input texte ---
        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(8)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Ecrire a Run ici puis appuyer Entree...")
        self.input_edit.returnPressed.connect(self._submit_prompt)

        self.send_button = QPushButton("Envoyer")
        self.send_button.setProperty("role", "accent")
        self.send_button.clicked.connect(self._submit_prompt)

        input_row.addWidget(self.input_edit, 1)
        input_row.addWidget(self.send_button)

        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(tools_frame)
        root.addWidget(self.mic_drawer)
        root.addLayout(mode_row)
        root.addWidget(win_frame)
        root.addWidget(self.monitor, 1)
        root.addLayout(input_row)

        self.append_system_message("Workspace RUN initialise. Voix, fenetres et modes actifs.")

    def _toggle_mic_drawer(self) -> None:
        if self.mic_drawer.isVisible():
            self.mic_drawer.hide()
            self.btn_micro.set_listening(False)
        else:
            self.mic_drawer.show()

    def _activate_selected_mic(self) -> None:
        item = self.mic_list.currentItem()
        if item is None:
            return
        name = item.text()
        self._mic_device = name
        self._voice_worker._device = name
        self.mic_drawer.hide()
        self.btn_micro.set_listening(False)
        self.append_system_message(f"Micro actif : {name}", tone="success")
        self._start_listening()

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        self.btn_mode_text.setChecked(mode == "text")
        self.btn_mode_voice.setChecked(mode == "voice")
        self.input_edit.setEnabled(mode == "text")
        self.send_button.setEnabled(mode == "text")
        if mode == "voice":
            self.append_system_message("Mode vocal active.", tone="info")
            self._start_listening()
        else:
            self.append_system_message("Mode ecriture active.", tone="info")
            self._stop_listening()

    def _toggle_voice_mode(self) -> None:
        if self.btn_voice.isChecked():
            self._start_listening()
        else:
            self._stop_listening()

    def _start_listening(self) -> None:
        self._mic_active = True
        self.btn_micro.set_listening(True)
        self.mic_state_changed.emit(True)
        self.append_system_message("Micro actif — parlez maintenant (5 sec)...", tone="info")
        self._voice_worker.listen_once()

    def _stop_listening(self) -> None:
        self._mic_active = False
        self.btn_micro.set_listening(False)
        self.mic_state_changed.emit(False)

    def _on_voice_recognized(self, text: str) -> None:
        self.append_system_message(f"Reconnu : {text}", tone="success")
        if self._mode == "voice":
            self._dispatch_voice_command(text)
        else:
            self.input_edit.setText(text)
        if self._mic_active:
            QTimer.singleShot(300, self._voice_worker.listen_once)

    def _on_voice_error(self, msg: str) -> None:
        self.append_system_message(msg, tone="error")
        self.btn_micro.set_listening(False)
        self.btn_voice.setChecked(False)
        self._mic_active = False

    def _dispatch_voice_command(self, text: str) -> None:
        low = text.lower().strip()
        if any(low.startswith(k) for k in ("focus", "split", "page", "grille", "retour")):
            self.window_command.emit(text)
        else:
            self.append_user_message(text)
            self.prompt_submitted.emit(text)

    def _send_window_command(self, cmd: str) -> None:
        arg = self.win_input.text().strip()
        full = f"{cmd} {arg}".strip() if arg else cmd
        self.append_system_message(f"Commande fenetre : {full}", tone="info")
        self.window_command.emit(full)
        self.win_input.clear()

    def _submit_window_command(self) -> None:
        cmd = self.win_input.text().strip()
        if cmd:
            self.append_system_message(f"Commande fenetre : {cmd}", tone="info")
            self.window_command.emit(cmd)
            self.win_input.clear()

    def append_system_message(self, text: str, *, tone: str = "info") -> None:
        clean = text.strip()
        if not clean:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        prefix = {"info": "RUN", "success": "OK", "blocked": "BLOCK", "error": "ERR"}.get(tone, "RUN")
        self.monitor.append(f"[{stamp}] {prefix} > {clean}")

    def append_user_message(self, text: str) -> None:
        clean = text.strip()
        if not clean:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        self.monitor.append(f"[{stamp}] YOU > {clean}")

    def _submit_prompt(self) -> None:
        text = self.input_edit.text().strip()
        if not text:
            return
        self.append_user_message(text)
        self.prompt_submitted.emit(text)
        self.input_edit.clear()
