from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView


PROFILE_ROOT = Path(r"D:\runtime\profiles\chatgpt-bridge")
CACHE_ROOT = Path(r"D:\runtime\cache\chatgpt-bridge")
STATE_ROOT = Path(r"D:\communication\chatgpt-bridge")
LOG_ROOT = Path(r"D:\logs\chatgpt-bridge")
TEMP_ROOT = Path(r"D:\temp\chatgpt-bridge")
TARGET_CONFIG_PATH = Path(r"D:\config\chatgpt-bridge\target.json")
TARGET_HISTORY_PATH = STATE_ROOT / "target-history.jsonl"
CYCLES_ROOT = STATE_ROOT / "cycles"
RESPONSES_ROOT = Path(r"D:\communication\responses")
ALLOWED_CHATGPT_PREFIX = "https://chatgpt.com/"
TRANSPORT_KIND = "DEDICATED_BACKGROUND_WEBVIEW"
BROWSER_HOST_ID = "chatgpt-bridge-primary"
ACTIVE_CYCLE_STATES = {
    "SEND_ATTEMPTED",
    "SENT_CONFIRMED",
    "WAITING_FOR_RESPONSE",
    "RESPONSE_STREAMING",
    "RESPONSE_STABLE",
}
BLOCKED_ROUTES = ("/library", "/gpts", "/images", "/settings", "/login")


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
    for path in (PROFILE_ROOT, CACHE_ROOT, STATE_ROOT, LOG_ROOT, TEMP_ROOT, RESPONSES_ROOT, TARGET_CONFIG_PATH.parent, CYCLES_ROOT):
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
    final = json.loads(path.read_text(encoding="utf-8"))
    if final != payload:
        raise OSError(f"Atomic write verification failed for {path}")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


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
    configured_at: str = ""
    last_validated_at: str = ""
    target_conversation_id: str = ""
    validation_status: str = "NOT_TESTED"
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
        return BROWSER_HOST_ID

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

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _conversation_id(url: str) -> str | None:
        try:
            parts = urlsplit(url)
        except ValueError:
            return None
        segments = [segment for segment in parts.path.split("/") if segment]
        if len(segments) >= 2 and segments[0] == "c":
            return segments[1] or None
        return None

    @staticmethod
    def normalize_target_url(url: str) -> str:
        raw = url.strip()
        parts = urlsplit(raw)
        scheme = parts.scheme.lower()
        host = parts.netloc.lower()
        path = parts.path or "/"
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        return urlunsplit((scheme, host, path, parts.query, ""))

    def validate_target_url(self, url: str) -> tuple[bool, str]:
        if not url or not url.strip():
            return False, "INVALID_URL"
        try:
            parts = urlsplit(url.strip())
        except ValueError:
            return False, "INVALID_URL"
        if parts.scheme.lower() != "https":
            return False, "INVALID_URL"
        if parts.hostname != "chatgpt.com":
            return False, "INVALID_URL"
        path = parts.path or "/"
        if any(path == route or path.startswith(f"{route}/") for route in BLOCKED_ROUTES):
            if path.startswith("/login"):
                return False, "LOGIN_REQUIRED"
            return False, "UNSUPPORTED_ROUTE"
        if not self._conversation_id(url):
            return False, "UNSUPPORTED_ROUTE"
        return True, "VALID"

    def _active_cycle(self) -> dict[str, str] | None:
        if not CYCLES_ROOT.exists():
            return None
        for path in CYCLES_ROOT.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            state = str(data.get("state") or "")
            if state in ACTIVE_CYCLE_STATES:
                return {"cycle_id": str(data.get("cycle_id") or path.stem), "state": state}
        return None

    def _save_target(self, target_url: str, *, validation_status: str = "VALID", last_error: str | None = None) -> dict[str, Any]:
        now = self._now()
        payload = {
            "schema_version": 2,
            "enabled": True,
            "transport_kind": TRANSPORT_KIND,
            "target_url": target_url,
            "target_conversation_id": self._conversation_id(target_url),
            "browser_host_id": BROWSER_HOST_ID,
            "profile_root": str(PROFILE_ROOT),
            "configured_at": now,
            "configured_by": "manual_nino_ui",
            "last_validated_at": now if validation_status == "VALID" else None,
            "validation_status": validation_status,
            "last_error": last_error,
        }
        old = self._target
        _write_json_atomic(TARGET_CONFIG_PATH, payload)
        self._target = payload
        _append_jsonl(TARGET_HISTORY_PATH, {
            "timestamp": now,
            "old_target_url": old.get("target_url") if isinstance(old, dict) else None,
            "new_target_url": payload["target_url"],
            "old_conversation_id": old.get("target_conversation_id") if isinstance(old, dict) else None,
            "new_conversation_id": payload["target_conversation_id"],
            "change_source": "manual_nino_ui",
            "validation_status": validation_status,
            "active_cycle_at_change": None,
            "result": "APPLIED",
        })
        return payload

    def target_url(self) -> str:
        return str(self._target.get("target_url", "") or "")

    def navigate_to_target(self) -> None:
        url = self.target_url() or ALLOWED_CHATGPT_PREFIX
        self.page.setUrl(QUrl(url))

    def current_url(self) -> str:
        return self.page.url().toString()

    def apply_target_url(self, url: str, callback: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        active = self._active_cycle()
        if active is not None:
            result = {"ok": False, "status": "TARGET_CHANGE_BLOCKED", "reason": "ACTIVE_BRIDGE_CYCLE", **active}
            if callback:
                callback(result)
            return result
        try:
            normalized = self.normalize_target_url(url)
        except ValueError:
            result = {"ok": False, "status": "INVALID_URL", "reason": "INVALID_URL"}
            if callback:
                callback(result)
            return result
        valid, reason = self.validate_target_url(normalized)
        if not valid:
            self._last_error = reason
            self.refresh_status()
            result = {"ok": False, "status": reason, "reason": reason}
            if callback:
                callback(result)
            return result

        def _finish(status: dict[str, Any]) -> None:
            composer_ok = status.get("composer") == "DETECTED"
            if not composer_ok:
                self._last_error = "COMPOSER_NOT_DETECTED"
                if callback:
                    callback({"ok": False, "status": "COMPOSER_NOT_DETECTED", "reason": "COMPOSER_NOT_DETECTED"})
                return
            payload = self._save_target(normalized)
            self._last_error = ""
            self.refresh_status()
            if callback:
                callback({"ok": True, "status": "VALID", "target": payload})

        if self.current_url() != normalized:
            self.page.setUrl(QUrl(normalized))
        self.refresh_status(_finish)
        return {"ok": True, "status": "VALIDATING", "target_url": normalized}

    def set_current_conversation_as_target(self) -> tuple[bool, str]:
        result = self.apply_target_url(self.current_url())
        return bool(result.get("ok")), str(result.get("status") or result.get("reason") or "")

    def clear_target(self) -> None:
        active = self._active_cycle()
        if active is not None:
            self._last_error = "TARGET_CHANGE_BLOCKED"
            self.refresh_status()
            return
        old = self._target
        now = self._now()
        payload = {
            "schema_version": 2,
            "enabled": False,
            "transport_kind": TRANSPORT_KIND,
            "target_url": "",
            "target_conversation_id": None,
            "browser_host_id": BROWSER_HOST_ID,
            "profile_root": str(PROFILE_ROOT),
            "configured_at": now,
            "configured_by": "manual_nino_ui",
            "last_validated_at": None,
            "validation_status": "NOT_TESTED",
            "last_error": None,
        }
        _write_json_atomic(TARGET_CONFIG_PATH, payload)
        self._target = payload
        _append_jsonl(TARGET_HISTORY_PATH, {
            "timestamp": now,
            "old_target_url": old.get("target_url") if isinstance(old, dict) else None,
            "new_target_url": "",
            "old_conversation_id": old.get("target_conversation_id") if isinstance(old, dict) else None,
            "new_conversation_id": None,
            "change_source": "manual_nino_ui",
            "validation_status": "NOT_TESTED",
            "active_cycle_at_change": None,
            "result": "CLEARED",
        })
        self.refresh_status()

    def refresh_status(self, callback: Callable[[dict[str, Any]], None] | None = None) -> None:
        def _complete(result: Any) -> None:
            info = result if isinstance(result, dict) else {}
            current_url = str(info.get("url") or self.page.url().toString())
            valid, reason = self.validate_target_url(self.target_url())
            session = "AUTHENTICATED" if bool(info.get("composer_detected")) else "LOGIN_REQUIRED"
            if not self.target_url():
                target = "NOT_CONFIGURED"
                reason = "BRIDGE_TARGET_NOT_CONFIGURED"
            elif not valid:
                target = "INVALID"
            else:
                target = "CONFIGURED"
            last_error = self._last_error or ("" if reason == "VALID" else reason)
            status = BridgeBrowserStatus(
                browser="ONLINE",
                session=session,
                target=target,
                current_url=current_url,
                composer="DETECTED" if info.get("composer_detected") else "NOT_DETECTED",
                generation=str(info.get("generation") or "UNKNOWN"),
                cycle=self._current_cycle,
                last_error=last_error,
                configured_at=str(self._target.get("configured_at") or ""),
                last_validated_at=str(self._target.get("last_validated_at") or ""),
                target_conversation_id=str(self._target.get("target_conversation_id") or ""),
                validation_status=str(self._target.get("validation_status") or "NOT_TESTED"),
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
    status_changed = Signal(dict)

    def __init__(self, target_configured: bool = True, session_authenticated: bool = True, composer_detected: bool = True) -> None:
        super().__init__()
        self.target_configured = target_configured
        self.session_authenticated = session_authenticated
        self.composer_detected = composer_detected
        self.transport = TRANSPORT_KIND
        self.visible_page_dependency = "NONE"
        self.sends = 0
        self.page_identity = "fake-page"
        self._target_url = "https://chatgpt.com/c/fake-conversation" if target_configured else ""
        self._current_url = self._target_url or "https://chatgpt.com/"
        self.applied_urls: list[str] = []
        self.navigations: list[str] = []
        self.cleared = False

    def target_url(self) -> str:
        return self._target_url

    def current_url(self) -> str:
        return self._current_url

    def set_current_url(self, url: str) -> None:
        self._current_url = url

    def navigate_to_target(self) -> None:
        self.navigations.append(self._target_url)
        self._current_url = self._target_url

    def widget(self) -> QWidget:
        from PySide6.QtWidgets import QWidget

        return QWidget()

    def refresh_status(self, callback: Callable[[dict[str, Any]], None] | None = None) -> None:
        status = self.status_snapshot()
        if callback:
            callback(status)

    def diagnostic_without_send(self, callback: Callable[[dict[str, Any]], None]) -> None:
        callback(self.status_snapshot())

    def apply_target_url(self, url: str, callback: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        try:
            normalized = ChatGPTBridgeBrowserHost.normalize_target_url(url)
        except ValueError:
            normalized = url
        if not normalized.startswith("https://chatgpt.com/c/"):
            valid, reason = False, "INVALID_URL" if not normalized.startswith("https://chatgpt.com/") else "UNSUPPORTED_ROUTE"
        else:
            valid, reason = True, "VALID"
        if not valid:
            result = {"ok": False, "status": reason, "reason": reason}
        elif not self.session_authenticated:
            result = {"ok": False, "status": "LOGIN_REQUIRED", "reason": "LOGIN_REQUIRED"}
        elif not self.composer_detected:
            result = {"ok": False, "status": "COMPOSER_NOT_DETECTED", "reason": "COMPOSER_NOT_DETECTED"}
        else:
            self._target_url = normalized
            self._current_url = normalized
            self.target_configured = True
            self.applied_urls.append(normalized)
            result = {"ok": True, "status": "VALID", "target": {"target_url": normalized}}
        if callback:
            callback(result)
        return result

    def clear_target(self) -> None:
        self._target_url = ""
        self.target_configured = False
        self.cleared = True

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
            "current_url": self._current_url,
            "configured_at": "2026-01-01T00:00:00+00:00" if self.target_configured else "",
            "last_validated_at": "2026-01-01T00:00:00+00:00" if self.target_configured else "",
            "target_conversation_id": "fake-conversation" if self.target_configured else "",
            "validation_status": "VALID" if self.target_configured else "NOT_TESTED",
            "composer": "DETECTED" if self.composer_detected else "NOT_DETECTED",
            "generation": "IDLE",
            "cycle": "NONE",
            "last_error": "" if reason == "READY" else reason,
            "transport": TRANSPORT_KIND,
            "visible_page_dependency": "NONE",
            "arena_status": "ARENA_ONLINE" if reason == "READY" else "ARENA_DEGRADED",
            "arena_reason": reason,
        }
