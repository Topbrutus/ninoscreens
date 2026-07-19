from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView


PROFILE_ROOT = Path(r"D:\runtime\profiles\chatgpt-bridge")
CACHE_ROOT = Path(r"D:\runtime\cache\chatgpt-bridge")
STATE_ROOT = Path(r"D:\communication\chatgpt-bridge")
LOG_ROOT = Path(r"D:\logs\chatgpt-bridge")
TEMP_ROOT = Path(r"D:\temp\chatgpt-bridge")
TARGET_CONFIG_PATH = Path(r"D:\config\chatgpt-bridge\target.json")
RESPONSES_ROOT = Path(r"D:\communication\responses")
ALLOWED_CHATGPT_PREFIX = "https://chatgpt.com/"
TRANSPORT_KIND = "DEDICATED_BACKGROUND_WEBVIEW"


CHATGPT_DOM_PROBE_JS = r"""
(() => {
  const selectors = [
    "textarea",
    "div[contenteditable='true']",
    "[data-testid='composer'] textarea",
    "[data-testid='composer'] div[contenteditable='true']",
    "#prompt-textarea"
  ];
  const composer = selectors.map((selector) => document.querySelector(selector)).find(Boolean);
  const buttons = Array.from(document.querySelectorAll("button"));
  const sendButton = buttons.find((button) => {
    const label = `${button.getAttribute("aria-label") || ""} ${button.textContent || ""}`.toLowerCase();
    return label.includes("send") || label.includes("envoyer");
  });
  const stopButton = buttons.find((button) => {
    const label = `${button.getAttribute("aria-label") || ""} ${button.textContent || ""}`.toLowerCase();
    return label.includes("stop") || label.includes("arrêter");
  });
  const text = document.body ? document.body.innerText || "" : "";
  return {
    url: location.href,
    title: document.title,
    composer_detected: Boolean(composer),
    send_button_detected: Boolean(sendButton),
    generation: stopButton ? "STREAMING" : "IDLE",
    body_length: text.length
  };
})();
"""


CHATGPT_INSERT_JS = r"""
((message) => {
  const selectors = [
    "textarea",
    "div[contenteditable='true']",
    "[data-testid='composer'] textarea",
    "[data-testid='composer'] div[contenteditable='true']",
    "#prompt-textarea"
  ];
  const composer = selectors.map((selector) => document.querySelector(selector)).find(Boolean);
  if (!composer) {
    return { ok: false, error: "COMPOSER_NOT_DETECTED" };
  }
  composer.focus();
  if ("value" in composer) {
    composer.value = message;
    composer.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: message }));
  } else {
    composer.textContent = message;
    composer.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: message }));
  }
  const inserted = "value" in composer ? composer.value : composer.textContent;
  return { ok: inserted === message, inserted_length: inserted.length };
})
"""


CHATGPT_SEND_JS = r"""
(() => {
  const buttons = Array.from(document.querySelectorAll("button"));
  const sendButton = buttons.find((button) => {
    const label = `${button.getAttribute("aria-label") || ""} ${button.textContent || ""}`.toLowerCase();
    return (label.includes("send") || label.includes("envoyer")) && !button.disabled;
  });
  if (!sendButton) {
    return { ok: false, error: "SEND_BUTTON_NOT_DETECTED" };
  }
  sendButton.click();
  return { ok: true, clicked: true };
})();
"""


CHATGPT_READ_RESPONSE_JS = r"""
(() => {
  const candidates = Array.from(document.querySelectorAll("[data-message-author-role='assistant'], .assistant, main article"));
  const last = candidates.length ? candidates[candidates.length - 1] : null;
  return last ? (last.innerText || last.textContent || "") : "";
})();
"""


def _ensure_roots() -> None:
    for path in (PROFILE_ROOT, CACHE_ROOT, STATE_ROOT, LOG_ROOT, TEMP_ROOT, RESPONSES_ROOT, TARGET_CONFIG_PATH.parent):
        path.mkdir(parents=True, exist_ok=True)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp") as handle:
        handle.write(serialized)
        handle.flush()
        os.fsync(handle.fileno())
        temp_name = handle.name
    os.replace(temp_name, path)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


@dataclass
class BridgeBrowserStatus:
    browser: str = "OFFLINE"
    session: str = "UNKNOWN"
    target: str = "NOT_CONFIGURED"
    current_url: str = ""
    composer: str = "UNKNOWN"
    generation: str = "UNKNOWN"
    cycle: str = "NONE"
    last_error: str = ""
    transport: str = TRANSPORT_KIND
    visible_page_dependency: str = "NONE"


class ChatGPTBridgeBrowserHost(QObject):
    status_changed = Signal(dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        _ensure_roots()
        self.profile = QWebEngineProfile("ChatGPTBridge", self)
        self.profile.setPersistentStoragePath(str(PROFILE_ROOT / "storage"))
        self.profile.setCachePath(str(CACHE_ROOT))
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        settings = self.profile.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, True)
        self.page = QWebEnginePage(self.profile, self)
        self.view = QWebEngineView()
        self.view.setPage(self.page)
        self._target: dict[str, Any] = self._load_target()
        self._last_status = BridgeBrowserStatus(browser="ONLINE")
        self._current_cycle = "NONE"
        self._last_error = ""
        self.page.loadFinished.connect(lambda _ok: self.refresh_status())

    @property
    def host_id(self) -> str:
        return "chatgpt-bridge-browser"

    def widget(self) -> QWebEngineView:
        return self.view

    def _load_target(self) -> dict[str, Any]:
        if not TARGET_CONFIG_PATH.exists():
            return {}
        try:
            data = json.loads(TARGET_CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_target(self, target_url: str) -> None:
        payload = {
            "schema_version": 1,
            "target_url": target_url,
            "target_conversation_id": self._conversation_id(target_url),
            "profile_root": str(PROFILE_ROOT),
            "enabled": True,
            "configured_at": self._now(),
            "last_validated_at": None,
            "last_error": None,
            "transport_kind": TRANSPORT_KIND,
            "deprecated_bridge_target_tile_id": None,
        }
        _write_json_atomic(TARGET_CONFIG_PATH, payload)
        self._target = payload

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _conversation_id(url: str) -> str | None:
        marker = "https://chatgpt.com/c/"
        if url.startswith(marker):
            tail = url[len(marker) :].split("?", 1)[0].split("#", 1)[0].strip("/")
            return tail or None
        return None

    def target_url(self) -> str:
        return str(self._target.get("target_url", "") or "")

    def validate_target_url(self, url: str) -> tuple[bool, str]:
        if not url.startswith(ALLOWED_CHATGPT_PREFIX):
            return False, "BRIDGE_TARGET_INVALID_DOMAIN"
        if url.rstrip("/") in {"https://chatgpt.com", "https://chatgpt.com/library"} or "/library" in url:
            return False, "BRIDGE_TARGET_NOT_CONFIGURED"
        if not self._conversation_id(url):
            return False, "BRIDGE_TARGET_NOT_CONFIGURED"
        return True, "READY"

    def navigate_to_target(self) -> None:
        url = self.target_url() or ALLOWED_CHATGPT_PREFIX
        self.page.setUrl(QUrl(url))

    def set_current_conversation_as_target(self) -> tuple[bool, str]:
        url = self.page.url().toString()
        valid, reason = self.validate_target_url(url)
        if not valid:
            self._last_error = reason
            self.refresh_status()
            return False, reason
        self._save_target(url)
        self.refresh_status()
        return True, "READY"

    def clear_target(self) -> None:
        payload = {
            "schema_version": 1,
            "target_url": "",
            "target_conversation_id": None,
            "profile_root": str(PROFILE_ROOT),
            "enabled": False,
            "configured_at": None,
            "last_validated_at": None,
            "last_error": None,
            "transport_kind": TRANSPORT_KIND,
        }
        _write_json_atomic(TARGET_CONFIG_PATH, payload)
        self._target = payload
        self.refresh_status()

    def refresh_status(self, callback: Callable[[dict[str, Any]], None] | None = None) -> None:
        def _complete(result: Any) -> None:
            info = result if isinstance(result, dict) else {}
            current_url = str(info.get("url") or self.page.url().toString())
            valid, reason = self.validate_target_url(self.target_url())
            session = "AUTHENTICATED" if valid and bool(info.get("composer_detected")) else "LOGIN_REQUIRED"
            if not self.target_url():
                target = "NOT_CONFIGURED"
                reason = "BRIDGE_TARGET_NOT_CONFIGURED"
            elif not valid:
                target = "INVALID"
            else:
                target = "CONFIGURED"
            status = BridgeBrowserStatus(
                browser="ONLINE",
                session=session,
                target=target,
                current_url=current_url,
                composer="DETECTED" if info.get("composer_detected") else "NOT_DETECTED",
                generation=str(info.get("generation") or "UNKNOWN"),
                cycle=self._current_cycle,
                last_error=self._last_error or ("" if reason == "READY" else reason),
            )
            self._last_status = status
            payload = status.__dict__.copy()
            self.status_changed.emit(payload)
            if callback:
                callback(payload)

        self.page.runJavaScript(CHATGPT_DOM_PROBE_JS, _complete)

    def status_snapshot(self) -> dict[str, Any]:
        return self._last_status.__dict__.copy()

    def diagnostic_without_send(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self.refresh_status(callback)

    def insert_bridge_message(self, cycle_id: str, transmission_key: str, expected_state: str, message: str, callback: Callable[[dict[str, Any]], None]) -> None:
        if expected_state != "SEND_ATTEMPTED":
            callback({"ok": False, "error": "INVALID_EXPECTED_STATE"})
            return
        script = f"{CHATGPT_INSERT_JS}({json.dumps(message)});"
        self.page.runJavaScript(script, callback)

    def send_bridge_message_once(self, cycle_id: str, transmission_key: str, callback: Callable[[dict[str, Any]], None]) -> None:
        self.page.runJavaScript(CHATGPT_SEND_JS, callback)

    def read_stable_assistant_response(self, callback: Callable[[dict[str, Any]], None]) -> None:
        def _complete(text: Any) -> None:
            value = str(text or "")
            callback({"ok": bool(value), "response_text": value, "response_hash": _sha256_text(value)})

        self.page.runJavaScript(CHATGPT_READ_RESPONSE_JS, _complete)


class FakeBridgeBrowserHost(QObject):
    """Deterministic test double with the same public status semantics."""

    def __init__(self, target_configured: bool = True, session_authenticated: bool = True, composer_detected: bool = True) -> None:
        super().__init__()
        self.target_configured = target_configured
        self.session_authenticated = session_authenticated
        self.composer_detected = composer_detected
        self.transport = TRANSPORT_KIND
        self.visible_page_dependency = "NONE"
        self.sends = 0
        self.page_identity = "fake-page"

    def status_snapshot(self) -> dict[str, Any]:
        if not self.target_configured:
            reason = "BRIDGE_TARGET_NOT_CONFIGURED"
            target = "NOT_CONFIGURED"
        elif not self.session_authenticated:
            reason = "BRIDGE_LOGIN_REQUIRED"
            target = "CONFIGURED"
        elif not self.composer_detected:
            reason = "BRIDGE_COMPOSER_NOT_DETECTED"
            target = "CONFIGURED"
        else:
            reason = "READY"
            target = "CONFIGURED"
        return {
            "browser": "ONLINE",
            "session": "AUTHENTICATED" if self.session_authenticated else "LOGIN_REQUIRED",
            "target": target,
            "composer": "DETECTED" if self.composer_detected else "NOT_DETECTED",
            "generation": "IDLE",
            "cycle": "NONE",
            "last_error": "" if reason == "READY" else reason,
            "transport": TRANSPORT_KIND,
            "visible_page_dependency": "NONE",
            "arena_status": "ARENA_ONLINE" if reason == "READY" else "ARENA_DEGRADED",
            "arena_reason": reason,
        }
