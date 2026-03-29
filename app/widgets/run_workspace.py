from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from datetime import datetime

from PySide6.QtCore import QObject, Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QSlider,
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

PIPEWIRE_MIC = "alsa_input.usb-Sony_CEVCECM-03.analog-stereo"


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
                import time
                time.sleep(1.0)
                rec = subprocess.Popen(
                    ["parecord", f"--device={self._device}",
                     "--file-format=wav", tmp],
                    stderr=subprocess.DEVNULL
                )
                time.sleep(7)
                rec.terminate()
                rec.wait()

                # Convertir en 16000Hz mono pour Google Speech
                tmp16 = tmp.replace(".wav", "_16k.wav")
                subprocess.run(
                    ["sox", tmp, "-r", "16000", "-c", "1", tmp16, "vol", "5"],
                    stderr=subprocess.DEVNULL
                )
                import os as _os
                if _os.path.exists(tmp16):
                    _os.unlink(tmp)
                    tmp = tmp16

                import requests as _requests, base64 as _b64, os as _os
                api_key = _os.environ.get("GOOGLE_API_KEY", "")
                if not api_key:
                    self.error.emit("GOOGLE_API_KEY manquant")
                    return
                with open(tmp, "rb") as f:
                    audio_b64 = _b64.b64encode(f.read()).decode()
                resp = _requests.post(
                    f"https://speech.googleapis.com/v1/speech:recognize?key={api_key}",
                    json={"config": {"encoding": "LINEAR16", "sampleRateHertz": 16000, "languageCode": "fr-FR"},
                          "audio": {"content": audio_b64}}
                )
                data = resp.json()
                results = data.get("results", [])
                if not results:
                    self.error.emit("Parole non reconnue.")
                    return
                text = results[0]["alternatives"][0]["transcript"]
                self.recognized.emit(text)
            except Exception as exc:
                import traceback
                self.error.emit(f"Erreur micro: {exc} | {traceback.format_exc()[-200:]}")
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
        self.btn_voice.clicked.connect(self._toggle_voice_drawer)
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
            found = False
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    name = parts[1]
                    if "monitor" in name:
                        continue
                    item = QListWidgetItem(name)
                    self.mic_list.addItem(item)
                    if "analog-stereo" in name or ("input" in name and "CEVCECM" in name):
                        self.mic_list.setCurrentItem(item)
                        found = True
            if not found:
                item = QListWidgetItem(PIPEWIRE_MIC)
                self.mic_list.addItem(item)
                self.mic_list.setCurrentRow(0)
        except Exception:
            item = QListWidgetItem(PIPEWIRE_MIC)
            self.mic_list.addItem(item)
            self.mic_list.setCurrentRow(0)

        drawer_layout.addWidget(self.mic_list)

        btn_activate = QPushButton("Activer ce micro")
        btn_activate.setProperty("role", "accent")
        btn_activate.clicked.connect(self._activate_selected_mic)
        drawer_layout.addWidget(btn_activate)

        # --- Drawer voix ---
        self.voice_drawer = QFrame()
        self.voice_drawer.setObjectName("TopBar")
        self.voice_drawer.hide()
        vd_layout = QVBoxLayout(self.voice_drawer)
        vd_layout.setContentsMargins(8, 8, 8, 8)
        vd_layout.setSpacing(6)

        vd_title = QLabel("Config voix :")
        vd_title.setObjectName("MutedText")
        vd_layout.addWidget(vd_title)

        voice_row = QHBoxLayout()
        voice_label = QLabel("Voix :")
        voice_label.setObjectName("MutedText")
        self.voice_combo = QComboBox()
        for name, code in [
            ("Femme FR-CA (Neural)", "fr-CA-Neural2-A"),
            ("Homme FR-CA (Neural)", "fr-CA-Neural2-B"),
            ("Femme FR-FR (Neural)", "fr-FR-Neural2-A"),
            ("Homme FR-FR (Neural)", "fr-FR-Neural2-B"),
        ]:
            self.voice_combo.addItem(name, code)
        self.voice_combo.setCurrentIndex(1)
        voice_row.addWidget(voice_label)
        voice_row.addWidget(self.voice_combo, 1)
        vd_layout.addLayout(voice_row)

        vol_row = QHBoxLayout()
        vol_label = QLabel("Volume :")
        vol_label.setObjectName("MutedText")
        self.vol_slider = QSlider()
        self.vol_slider.setOrientation(Qt.Orientation.Horizontal)
        self.vol_slider.setMinimum(1)
        self.vol_slider.setMaximum(10)
        self.vol_slider.setValue(7)
        self.vol_slider.setFixedWidth(150)
        vol_row.addWidget(vol_label)
        vol_row.addWidget(self.vol_slider)
        vol_row.addStretch()
        vd_layout.addLayout(vol_row)

        btn_test_voice = QPushButton("Tester la voix")
        btn_test_voice.setProperty("compact", True)
        btn_test_voice.clicked.connect(self._test_voice)
        vd_layout.addWidget(btn_test_voice)

        btn_close_vd = QPushButton("Fermer")
        btn_close_vd.setProperty("compact", True)
        btn_close_vd.clicked.connect(lambda: self.voice_drawer.hide())
        vd_layout.addWidget(btn_close_vd)

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
        root.addWidget(self.voice_drawer)
        root.addLayout(mode_row)
        root.addWidget(win_frame)
        root.addWidget(self.monitor, 1)
        root.addLayout(input_row)

        self.append_system_message("Workspace RUN initialise. Voix, fenetres et modes actifs.")

    def _toggle_voice_drawer(self) -> None:
        if self.voice_drawer.isVisible():
            self.voice_drawer.hide()
            self.btn_voice.setChecked(False)
        else:
            self.voice_drawer.show()
            self.btn_voice.setChecked(True)

    def speak(self, text: str) -> None:
        import threading, requests as _req, base64 as _b64, os as _os, subprocess as _sp, tempfile as _tmp, re as _re
        def _run():
            try:
                key = _os.environ.get("GOOGLE_API_KEY", "")
                if not key:
                    try:
                        sh = open("/home/gaby/Ninoscreens/start.sh").read()
                        m = _re.search(r'GOOGLE_API_KEY="([^"]+)"', sh)
                        if m: key = m.group(1)
                    except Exception:
                        pass
                if not key:
                    print("TTS: clé manquante")
                    return
                voice = "fr-CA-Neural2-B"
                if hasattr(self, "voice_combo"):
                    voice = self.voice_combo.currentData() or voice
                r = _req.post(
                    f"https://texttospeech.googleapis.com/v1/text:synthesize?key={key}",
                    json={"input": {"text": text}, "voice": {"languageCode": voice[:5], "name": voice}, "audioConfig": {"audioEncoding": "MP3"}}
                )
                data = r.json()
                if "audioContent" not in data:
                    print(f"TTS erreur: {data}")
                    return
                audio = _b64.b64decode(data["audioContent"])
                tmp = _tmp.mktemp(suffix=".mp3")
                with open(tmp, "wb") as f:
                    f.write(audio)
                _sp.run(["mpg123", "-q", tmp])
                _os.unlink(tmp)
            except Exception as exc:
                print(f"TTS exception: {exc}")
        threading.Thread(target=_run, daemon=True).start()

    def _test_voice(self) -> None:
        self.speak("Bonjour, je suis Nino, votre assistant vocal.")

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
