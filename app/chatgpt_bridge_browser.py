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

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView


PROFILE_ROOT = Path(r"D:\runtime\profiles\chatgpt-bridge")
CACHE_ROOT = Path(r"D:\runtime\cache\chatgpt-bridge")
STATE_ROOT = Path(r"D:\communication\chatgpt-bridge")
LOG_ROOT = Path(r"D:\logs\chatgpt-bridge")
TEMP_ROOT = Path(r"D:\temp\chatgpt-bridge")
TARGET_CONFIG_PATH = Path(r"D:\config\chatgpt-bridge\target.json")
TARGET_HISTORY_PATH = STATE_ROOT / "target-history.jsonl"
LIVE_DIAGNOSTIC_LOG_PATH = STATE_ROOT / "live-diagnostic.jsonl"
BROWSER_STATE_PATH = STATE_ROOT / "browser-state.json"
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
  try {
    const now = new Date().toISOString();
    const safeUrl = () => `${location.origin}${location.pathname}`;
    const visible = (el) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity || 1) <= 0) return false;
    if (rect.width <= 0 || rect.height <= 0) return false;
    if (el.closest("[hidden], [aria-hidden='true']")) return false;
    return true;
    };
    const disabled = (el) => {
    if (!el) return true;
    if (el.disabled) return true;
    if (el.getAttribute("aria-disabled") === "true") return true;
    if (el.closest("[aria-disabled='true'], fieldset[disabled]")) return true;
    return false;
    };
    const evidence = [];
    const addEvidence = (kind, selector, el) => {
    if (el) evidence.push({kind, selector, visible: visible(el)});
    };

    const path = location.pathname || "/";
    const readyState = document.readyState || "unknown";
    const loginForm = document.querySelector("form[action*='auth'], input[type='password'], a[href*='/auth/login'], button[data-testid*='login']");
    const loginAction = Array.from(document.querySelectorAll("a, button")).find((el) => {
    const label = `${el.getAttribute("aria-label") || ""} ${el.getAttribute("data-testid") || ""}`.toLowerCase();
    return /\b(log-?in|sign-?up)\b/.test(label);
    });
    const newChat = document.querySelector("a[href='/'], a[href='/new'], [data-testid='create-new-chat-button'], [aria-label*='New chat'], [aria-label*='Nouveau']");
    const sidebar = document.querySelector("nav, aside, [data-testid='history'], [data-testid='sidebar']");
    const main = document.querySelector("main");
    addEvidence("new_chat", "[data-testid='create-new-chat-button']|[aria-label*='New chat']", newChat);
    addEvidence("sidebar", "nav|aside|[data-testid='sidebar']", sidebar);
    addEvidence("main", "main", main);
    addEvidence("login_form", "form[action*='auth']|input[type='password']", loginForm);
    addEvidence("login_action", "a|button login/signup", loginAction);

    let sessionState = "SESSION_UNKNOWN";
    if (readyState !== "complete" && readyState !== "interactive") {
    sessionState = "SESSION_LOADING";
    } else if (path.startsWith("/auth") || path.startsWith("/login") || visible(loginForm) || visible(loginAction)) {
    sessionState = "LOGIN_REQUIRED";
    } else if (visible(newChat) || visible(sidebar) || visible(main) || path.startsWith("/c/")) {
    sessionState = "AUTHENTICATED";
    }

    const composerSelectors = [
    "#prompt-textarea",
    "[data-testid='prompt-textarea']",
    "textarea[data-testid='prompt-textarea']",
    "textarea[placeholder]",
    "div[contenteditable='true'][data-lexical-editor='true']",
    "[contenteditable='true'][role='textbox']",
    "form [contenteditable='true']",
    "main [contenteditable='true']"
    ];
    const candidates = [];
    for (const selector of composerSelectors) {
    for (const el of Array.from(document.querySelectorAll(selector))) {
      const rect = el.getBoundingClientRect();
      const inMain = Boolean(el.closest("main"));
      const inForm = Boolean(el.closest("form"));
      const inSidebar = Boolean(el.closest("nav, aside, [data-testid='sidebar'], [data-testid='history']"));
      const editable = el.tagName.toLowerCase() === "textarea" || el.isContentEditable || el.getAttribute("contenteditable") === "true";
      candidates.push({
        el, selector, inMain, inForm, inSidebar, editable,
        visible: visible(el), enabled: !disabled(el),
        area: rect.width * rect.height
      });
    }
    }
    const winner = candidates.find((c) => c.visible && c.enabled && c.editable && !c.inSidebar && (c.inMain || c.inForm));
    const stopButton = Array.from(document.querySelectorAll("button")).find((button) => {
    const label = `${button.getAttribute("aria-label") || ""} ${button.getAttribute("data-testid") || ""}`.toLowerCase();
    return label.includes("stop") || label.includes("arrêter");
    });
    const generation = visible(stopButton) ? "STREAMING" : "IDLE";
    let composerState = "NOT_DETECTED";
    if (readyState !== "complete" && candidates.length === 0) {
    composerState = "LOADING";
    } else if (generation === "STREAMING") {
    composerState = "GENERATION_ACTIVE";
    } else if (winner) {
    composerState = "DETECTED";
    } else if (candidates.some((c) => c.visible && !c.enabled)) {
    composerState = "DISABLED";
    }
    return {
    ok: true,
    url: safeUrl(),
    ready_state: readyState,
    timestamp: now,
    session: { state: sessionState, evidence, url: safeUrl(), ready_state: readyState, timestamp: now },
    composer: {
      state: composerState,
      selector: winner ? winner.selector : null,
      element_kind: winner ? winner.el.tagName.toLowerCase() : "unknown",
      visible: Boolean(winner && winner.visible),
      enabled: Boolean(winner && winner.enabled),
      editable: Boolean(winner && winner.editable),
      ready_state: readyState,
      candidate_count: candidates.length,
      timestamp: now
    },
    generation
    };
  } catch (error) {
    return {
      ok: false,
      url: `${location.origin}${location.pathname}`,
      ready_state: (document && document.readyState) || "unknown",
      timestamp: new Date().toISOString(),
      session: {state: "SESSION_UNKNOWN", evidence: [], url: `${location.origin}${location.pathname}`, ready_state: (document && document.readyState) || "unknown", timestamp: new Date().toISOString()},
      composer: {state: "UNKNOWN", selector: null, element_kind: "unknown", visible: false, enabled: false, editable: false, ready_state: (document && document.readyState) || "unknown", candidate_count: 0, timestamp: new Date().toISOString()},
      generation: "UNKNOWN",
      error: "JAVASCRIPT_EVALUATION_FAILED"
    };
  }
})()
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


def _route_kind(url: str) -> str:
    try:
        path = urlsplit(url).path or "/"
    except ValueError:
        return "INVALID"
    if path.startswith("/c/"):
        return "CONVERSATION"
    if path in {"/", ""}:
        return "HOME"
    if path.startswith("/library"):
        return "LIBRARY"
    if path.startswith("/login") or path.startswith("/auth"):
        return "LOGIN"
    return "OTHER"


def _sanitize_chatgpt_url(url: str) -> str:
    parts = urlsplit(str(url or "").strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, host, path, "", ""))


def _is_allowed_chatgpt_url(url: str) -> bool:
    try:
        parts = urlsplit(str(url or "").strip())
    except ValueError:
        return False
    return parts.scheme.lower() == "https" and (parts.hostname or "").lower() == "chatgpt.com"


def _is_useful_browser_state_url(url: str) -> bool:
    if not _is_allowed_chatgpt_url(url):
        return False
    route = _route_kind(url)
    return route not in {"LOGIN", "INVALID"}


def _browser_state_payload(url: str, *, now: str, browser_host_id: str = BROWSER_HOST_ID) -> dict[str, Any]:
    sanitized = _sanitize_chatgpt_url(url)
    return {
        "schema_version": 1,
        "last_url": sanitized,
        "last_route_kind": _route_kind(sanitized),
        "updated_at": now,
        "browser_host_id": browser_host_id,
    }


def _choose_start_url(target_url: str, browser_state_url: str) -> str:
    if _is_useful_browser_state_url(target_url):
        return _sanitize_chatgpt_url(target_url)
    if _is_useful_browser_state_url(browser_state_url):
        return _sanitize_chatgpt_url(browser_state_url)
    return ALLOWED_CHATGPT_PREFIX


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
        self._navigation_epoch = 0
        self._diagnostic_generation = 0
        self._validation_in_progress = False
        self._live_diagnostic_in_progress = False
        self.page.loadStarted.connect(self._mark_navigation_started)
        self.page.urlChanged.connect(self._on_url_changed)
        self.page.loadFinished.connect(lambda _ok: self.refresh_status())
        QTimer.singleShot(0, self.restore_or_start)

    @property
    def host_id(self) -> str:
        return BROWSER_HOST_ID

    def widget(self) -> QWebEngineView:
        self.ensure_view_bound()
        return self.view

    def _mark_navigation_started(self) -> None:
        self._navigation_epoch += 1
        self._last_status.session = "SESSION_LOADING"
        self._last_status.composer = "LOADING"
        self.status_changed.emit(self.status_snapshot())

    def _on_url_changed(self, url: QUrl) -> None:
        self._mark_navigation_started()
        self._remember_browser_url(url.toString())

    def ensure_view_bound(self) -> dict[str, Any]:
        if self.view.page() is not self.page:
            self.view.setPage(self.page)
        return self.technical_identity()

    def technical_identity(self) -> dict[str, Any]:
        visible_page = self.view.page()
        return {
            "browser_host_id": self.host_id,
            "browser_host_object_id": id(self),
            "profile_object_id": id(self.profile),
            "host_page_object_id": id(self.page),
            "visible_view_object_id": id(self.view),
            "visible_view_page_object_id": id(visible_page),
            "same_page_object": visible_page is self.page,
            "profile_path": str(PROFILE_ROOT),
            "current_url": self.current_url(),
            "navigation_epoch": self._navigation_epoch,
        }

    def _read_browser_state_url(self) -> str:
        if not BROWSER_STATE_PATH.exists():
            return ""
        try:
            data = json.loads(BROWSER_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        if not isinstance(data, dict) or data.get("browser_host_id") != self.host_id:
            return ""
        return str(data.get("last_url") or "")

    def _remember_browser_url(self, url: str) -> None:
        if not _is_useful_browser_state_url(url):
            return
        payload = _browser_state_payload(url, now=self._now(), browser_host_id=self.host_id)
        try:
            _write_json_atomic(BROWSER_STATE_PATH, payload)
        except OSError:
            self._last_error = "BROWSER_STATE_WRITE_FAILED"

    def _startup_url(self) -> str:
        return _choose_start_url(self.target_url(), self._read_browser_state_url())

    def restore_or_start(self) -> dict[str, Any]:
        identity = self.ensure_view_bound()
        current = self.current_url()
        if current and current != "about:blank":
            self._remember_browser_url(current)
            return {**identity, "restored": False, "url": current}
        url = self._startup_url()
        self._last_error = "BROWSER_RESTORING"
        self._mark_navigation_started()
        self.page.setUrl(QUrl(url))
        return {**self.technical_identity(), "restored": True, "url": url}

    def _write_live_diagnostic_event(self, event: str, *, info: dict[str, Any] | None = None, error_code: str | None = None) -> None:
        info = info if isinstance(info, dict) else {}
        session = info.get("session") if isinstance(info.get("session"), dict) else {}
        composer = info.get("composer") if isinstance(info.get("composer"), dict) else {}
        _append_jsonl(LIVE_DIAGNOSTIC_LOG_PATH, {
            "timestamp": self._now(),
            "event": event,
            "browser_host_id": self.host_id,
            "current_route_kind": _route_kind(str(info.get("url") or self.current_url())),
            "ready_state": str(info.get("ready_state") or ""),
            "session_state": str(session.get("state") or ""),
            "composer_state": str(composer.get("state") or ""),
            "generation_state": str(info.get("generation") or ""),
            "navigation_epoch": self._navigation_epoch,
            "diagnostic_generation": self._diagnostic_generation,
            "error_code": error_code,
        })

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
        self.ensure_view_bound()
        url = self.target_url() or self._startup_url()
        self._mark_navigation_started()
        self.page.setUrl(QUrl(url))

    def current_url(self) -> str:
        return self.page.url().toString()

    def _diagnostic_payload_to_status(self, info: dict[str, Any]) -> BridgeBrowserStatus:
        current_url = str(info.get("url") or self.page.url().toString())
        valid, reason = self.validate_target_url(self.target_url())
        session_info = info.get("session") if isinstance(info.get("session"), dict) else {}
        composer_info = info.get("composer") if isinstance(info.get("composer"), dict) else {}
        session = str(session_info.get("state") or "SESSION_UNKNOWN")
        composer = str(composer_info.get("state") or "UNKNOWN")
        if not self.target_url():
            target = "NOT_CONFIGURED"
            reason = "BRIDGE_TARGET_NOT_CONFIGURED"
        elif not valid:
            target = "INVALID"
        else:
            target = "CONFIGURED"
        last_error = self._last_error or ("" if reason == "VALID" else reason)
        return BridgeBrowserStatus(
            browser="ONLINE",
            session=session,
            target=target,
            current_url=current_url,
            composer=composer,
            generation=str(info.get("generation") or "UNKNOWN"),
            cycle=self._current_cycle,
            last_error=last_error,
            configured_at=str(self._target.get("configured_at") or ""),
            last_validated_at=str(self._target.get("last_validated_at") or ""),
            target_conversation_id=str(self._target.get("target_conversation_id") or ""),
            validation_status=str(self._target.get("validation_status") or "NOT_TESTED"),
        )

    def _run_dom_diagnostic(self, generation: int, callback: Callable[[dict[str, Any]], None]) -> None:
        epoch = self._navigation_epoch
        self._write_live_diagnostic_event("LIVE_DIAGNOSTIC_STARTED")

        def _complete(result: Any) -> None:
            if generation != self._diagnostic_generation or epoch != self._navigation_epoch:
                self._write_live_diagnostic_event("STALE_DIAGNOSTIC_IGNORED", error_code="STALE_DIAGNOSTIC_IGNORED")
                callback({"ok": False, "stale": True, "error": "STALE_DIAGNOSTIC_IGNORED"})
                return
            info = result if isinstance(result, dict) else {"ok": False, "error": "JAVASCRIPT_RESULT_INVALID"}
            self._write_live_diagnostic_event("SESSION_DIAGNOSTIC_COMPLETED", info=info, error_code=info.get("error"))
            self._write_live_diagnostic_event("COMPOSER_DIAGNOSTIC_COMPLETED", info=info, error_code=info.get("error"))
            callback(info)

        self.page.runJavaScript(CHATGPT_DOM_PROBE_JS, _complete)

    def diagnose_until_stable(
        self,
        callback: Callable[[dict[str, Any]], None],
        *,
        require_composer: bool = False,
        attempt: int = 0,
        generation: int | None = None,
    ) -> None:
        delays = [0, 250, 500, 1000, 2000, 3000, 4000]
        if generation is None:
            self._diagnostic_generation += 1
            generation = self._diagnostic_generation

        def _evaluate(info: dict[str, Any]) -> None:
            if info.get("stale"):
                if attempt >= len(delays) - 1:
                    callback({"ok": False, "reason": "STALE_DIAGNOSTIC_IGNORED", "status": self.status_snapshot(), "diagnostic": info})
                    return
                QTimer.singleShot(delays[attempt + 1], lambda: self.diagnose_until_stable(callback, require_composer=require_composer, attempt=attempt + 1, generation=generation))
                return
            status = self._diagnostic_payload_to_status(info)
            session_state = status.session
            composer_state = status.composer
            ready = info.get("ready_state") in {"complete", "interactive"}
            if info.get("error"):
                reason = str(info.get("error") or "JAVASCRIPT_EVALUATION_FAILED")
                self._last_error = reason
                status.last_error = reason
                self._last_status = status
                self.status_changed.emit(status.__dict__.copy())
                self._write_live_diagnostic_event("LIVE_DIAGNOSTIC_FAILED", info=info, error_code=reason)
                callback({"ok": False, "reason": reason, "status": status.__dict__.copy(), "diagnostic": info})
                return
            if session_state == "AUTHENTICATED" and (not require_composer or composer_state == "DETECTED"):
                self._last_error = ""
                status.last_error = ""
                self._last_status = status
                self.status_changed.emit(status.__dict__.copy())
                self._write_live_diagnostic_event("LIVE_DIAGNOSTIC_APPLIED", info=info)
                callback({"ok": True, "status": status.__dict__.copy(), "diagnostic": info})
                return
            self._last_status = status
            self.status_changed.emit(status.__dict__.copy())
            if composer_state == "GENERATION_ACTIVE":
                self._last_error = "GENERATION_ACTIVE"
                self._write_live_diagnostic_event("LIVE_DIAGNOSTIC_FAILED", info=info, error_code="GENERATION_ACTIVE")
                callback({"ok": False, "reason": "GENERATION_ACTIVE", "status": status.__dict__.copy(), "diagnostic": info})
                return
            if attempt >= len(delays) - 1:
                reason = "COMPOSER_LOADING_TIMEOUT" if require_composer and session_state == "AUTHENTICATED" else "TARGET_PAGE_LOADING_TIMEOUT"
                if session_state == "LOGIN_REQUIRED":
                    reason = "LOGIN_REQUIRED"
                elif require_composer and composer_state in {"NOT_DETECTED", "DISABLED"}:
                    reason = "COMPOSER_NOT_DETECTED" if composer_state == "NOT_DETECTED" else "COMPOSER_DISABLED"
                self._last_error = reason
                status.last_error = reason
                self._last_status = status
                self.status_changed.emit(status.__dict__.copy())
                self._write_live_diagnostic_event("LIVE_DIAGNOSTIC_FAILED", info=info, error_code=reason)
                callback({"ok": False, "reason": reason, "status": status.__dict__.copy(), "diagnostic": info})
                return
            if not ready or session_state in {"SESSION_LOADING", "SESSION_UNKNOWN"} or (require_composer and composer_state == "LOADING"):
                QTimer.singleShot(delays[attempt + 1], lambda: self.diagnose_until_stable(callback, require_composer=require_composer, attempt=attempt + 1, generation=generation))
                return
            if require_composer and session_state == "AUTHENTICATED" and composer_state != "DETECTED":
                QTimer.singleShot(delays[attempt + 1], lambda: self.diagnose_until_stable(callback, require_composer=require_composer, attempt=attempt + 1, generation=generation))
                return
            reason = "LOGIN_REQUIRED" if session_state == "LOGIN_REQUIRED" else "SESSION_UNKNOWN"
            self._last_error = reason
            status.last_error = reason
            self._last_status = status
            self.status_changed.emit(status.__dict__.copy())
            self._write_live_diagnostic_event("LIVE_DIAGNOSTIC_FAILED", info=info, error_code=reason)
            callback({"ok": False, "reason": reason, "status": status.__dict__.copy(), "diagnostic": info})

        self._run_dom_diagnostic(generation, _evaluate)

    def apply_target_url(self, url: str, callback: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        if self._validation_in_progress:
            result = {"ok": False, "status": "VALIDATION_IN_PROGRESS", "reason": "VALIDATION_IN_PROGRESS"}
            if callback:
                callback(result)
            return result
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

        self._validation_in_progress = True
        self._last_status.session = "SESSION_LOADING"
        self._last_status.composer = "LOADING"
        self.status_changed.emit(self.status_snapshot())

        def _finish(result: dict[str, Any]) -> None:
            self._validation_in_progress = False
            status = result.get("status") if isinstance(result.get("status"), dict) else {}
            session_state = str(status.get("session") or "SESSION_UNKNOWN")
            composer_state = str(status.get("composer") or "UNKNOWN")
            if not result.get("ok"):
                reason = str(result.get("reason") or "TARGET_VALIDATION_FAILED")
                self._last_error = reason
                if callback:
                    callback({"ok": False, "status": reason, "reason": reason, "session": session_state, "composer": composer_state})
                return
            payload = self._save_target(normalized)
            self._last_error = ""
            self.refresh_status()
            if callback:
                callback({"ok": True, "status": "VALID", "target": payload})

        if self.current_url() != normalized:
            self._mark_navigation_started()
            self.page.setUrl(QUrl(normalized))
        QTimer.singleShot(250, lambda: self.diagnose_until_stable(_finish, require_composer=True))
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
        if self.host_id != BROWSER_HOST_ID:
            self._last_error = "WRONG_BROWSER_HOST"
            if callback:
                callback(self.status_snapshot())
            return
        self.ensure_view_bound()
        if not self.current_url() or self.current_url() == "about:blank":
            self.restore_or_start()
        if self._live_diagnostic_in_progress:
            if callback:
                callback(self.status_snapshot())
            return
        self._live_diagnostic_in_progress = True
        self._write_live_diagnostic_event("LIVE_DIAGNOSTIC_REQUESTED")
        self._last_status.session = "SESSION_LOADING"
        self._last_status.composer = "LOADING"
        self._last_status.last_error = "VALIDATION_IN_PROGRESS"
        self.status_changed.emit(self.status_snapshot())

        def _done(result: dict[str, Any]) -> None:
            self._live_diagnostic_in_progress = False
            status = result.get("status") if isinstance(result.get("status"), dict) else self.status_snapshot()
            if callback:
                callback(status)

        self.diagnose_until_stable(_done, require_composer=True)

    def status_snapshot(self) -> dict[str, Any]:
        return self._last_status.__dict__.copy()

    def _target_test_status(self, info: dict[str, Any], *, validation_status: str, last_error: str = "") -> dict[str, Any]:
        status = self._diagnostic_payload_to_status(info)
        snapshot = status.__dict__.copy()
        snapshot["target"] = "CONFIGURED" if self.target_url() else "NOT_CONFIGURED"
        snapshot["validation_status"] = validation_status
        snapshot["last_error"] = last_error
        return snapshot

    def diagnostic_without_send(self, callback: Callable[[dict[str, Any]], None], url: str | None = None) -> None:
        field_url = str(url if url is not None else self.current_url()).strip()
        self.ensure_view_bound()
        identity = self.technical_identity()
        if not identity.get("same_page_object"):
            self._last_error = "WRONG_BROWSER_HOST"
            callback({**self.status_snapshot(), "last_error": "WRONG_BROWSER_HOST"})
            return
        active = self._active_cycle()
        if active is not None:
            self._last_error = "TARGET_CHANGE_BLOCKED"
            callback({**self.status_snapshot(), "last_error": "ACTIVE_BRIDGE_CYCLE", "cycle": active.get("cycle_id", "")})
            return
        try:
            normalized = self.normalize_target_url(field_url)
        except ValueError:
            normalized = field_url
        valid, reason = self.validate_target_url(normalized)
        if not valid:
            self._last_error = reason
            callback({**self.status_snapshot(), "validation_status": reason, "last_error": reason})
            return
        if self._validation_in_progress or self._live_diagnostic_in_progress:
            callback({**self.status_snapshot(), "validation_status": "VALIDATION_IN_PROGRESS", "last_error": "VALIDATION_IN_PROGRESS"})
            return
        self._live_diagnostic_in_progress = True
        self._diagnostic_generation += 1
        generation = self._diagnostic_generation
        self._last_status.session = "SESSION_LOADING"
        self._last_status.composer = "LOADING"
        self._last_status.generation = "UNKNOWN"
        self._last_status.validation_status = "TESTING"
        self._last_status.last_error = ""
        self.status_changed.emit(self.status_snapshot())

        def _finish(result: dict[str, Any]) -> None:
            self._live_diagnostic_in_progress = False
            if result.get("stale"):
                return
            if not result.get("ok"):
                reason_text = str(result.get("reason") or "TARGET_VALIDATION_FAILED")
                status_dict = result.get("status") if isinstance(result.get("status"), dict) else self.status_snapshot()
                status_dict = {**status_dict, "validation_status": reason_text, "last_error": reason_text}
                self._last_error = reason_text
                self._last_status = BridgeBrowserStatus(**{k: status_dict.get(k, getattr(BridgeBrowserStatus(), k)) for k in BridgeBrowserStatus().__dict__})
                self.status_changed.emit(status_dict)
                callback(status_dict)
                return
            diagnostic = result.get("diagnostic") if isinstance(result.get("diagnostic"), dict) else {}
            status_dict = self._target_test_status(diagnostic, validation_status="VALID", last_error="")
            status_dict["target"] = "NOT_CONFIGURED" if not self.target_url() else "CONFIGURED"
            self._last_error = ""
            self._last_status = BridgeBrowserStatus(**{k: status_dict.get(k, getattr(BridgeBrowserStatus(), k)) for k in BridgeBrowserStatus().__dict__})
            self.status_changed.emit(status_dict)
            callback(status_dict)

        if _sanitize_chatgpt_url(self.current_url()) != _sanitize_chatgpt_url(normalized):
            self._mark_navigation_started()
            self.page.setUrl(QUrl(normalized))
            QTimer.singleShot(250, lambda: self.diagnose_until_stable(_finish, require_composer=True, generation=generation))
            return
        self.diagnose_until_stable(_finish, require_composer=True, generation=generation)

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
        self.view_identity = "fake-view"
        self.view_page_identity = self.page_identity
        self._target_url = "https://chatgpt.com/c/fake-conversation" if target_configured else ""
        self._current_url = self._target_url or "https://chatgpt.com/"
        self.browser_state_url = ""
        self.applied_urls: list[str] = []
        self.navigations: list[str] = []
        self.cleared = False
        self.validation_in_progress = False
        self.refresh_calls = 0
        self.diagnostic_in_progress = False
        self.target_json_writes = 0
        self.history_writes = 0
        self.cycles_created = 0
        self.text_read = 0
        self.text_entered = 0

    def target_url(self) -> str:
        return self._target_url

    def current_url(self) -> str:
        return self._current_url

    def set_current_url(self, url: str) -> None:
        self._current_url = url

    def navigate_to_target(self) -> None:
        url = self._target_url or _choose_start_url("", self.browser_state_url)
        self.navigations.append(url)
        self._current_url = url

    def ensure_view_bound(self) -> dict[str, Any]:
        self.view_page_identity = self.page_identity
        return self.technical_identity()

    def technical_identity(self) -> dict[str, Any]:
        return {
            "browser_host_id": BROWSER_HOST_ID,
            "browser_host_object_id": id(self),
            "profile_object_id": "fake-profile",
            "host_page_object_id": self.page_identity,
            "visible_view_object_id": self.view_identity,
            "visible_view_page_object_id": self.view_page_identity,
            "same_page_object": self.view_page_identity == self.page_identity,
            "profile_path": str(PROFILE_ROOT),
            "current_url": self._current_url,
            "navigation_epoch": 0,
        }

    def restore_or_start(self) -> dict[str, Any]:
        identity = self.ensure_view_bound()
        if self._current_url and self._current_url != "about:blank":
            return {**identity, "restored": False, "url": self._current_url}
        url = _choose_start_url(self._target_url, self.browser_state_url)
        self.navigations.append(url)
        self._current_url = url
        return {**self.technical_identity(), "restored": True, "url": url}

    def widget(self) -> QWidget:
        from PySide6.QtWidgets import QWidget

        return QWidget()

    def refresh_status(self, callback: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.refresh_calls += 1
        status = self.status_snapshot()
        if callback:
            callback(status)

    def diagnostic_without_send(self, callback: Callable[[dict[str, Any]], None], url: str | None = None) -> None:
        if self.diagnostic_in_progress:
            callback({**self.status_snapshot(), "validation_status": "VALIDATION_IN_PROGRESS", "last_error": "VALIDATION_IN_PROGRESS"})
            return
        self.diagnostic_in_progress = True
        requested_url = str(url or self._current_url)
        try:
            normalized = ChatGPTBridgeBrowserHost.normalize_target_url(requested_url)
        except ValueError:
            normalized = requested_url
        if not normalized.startswith("https://chatgpt.com/c/"):
            reason = "INVALID_URL" if not normalized.startswith("https://chatgpt.com/") else "UNSUPPORTED_ROUTE"
            self.diagnostic_in_progress = False
            callback({**self.status_snapshot(), "validation_status": reason, "last_error": reason})
            return
        if _sanitize_chatgpt_url(self._current_url) != _sanitize_chatgpt_url(normalized):
            self.navigations.append(normalized)
            self._current_url = normalized
        status = {
            **self.status_snapshot(),
            "target": "NOT_CONFIGURED" if not self.target_configured else "CONFIGURED",
            "validation_status": "VALID",
            "last_error": "",
            "generation": "IDLE",
        }
        self.diagnostic_in_progress = False
        callback(status)

    def apply_target_url(self, url: str, callback: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        if self.validation_in_progress:
            result = {"ok": False, "status": "VALIDATION_IN_PROGRESS", "reason": "VALIDATION_IN_PROGRESS"}
            if callback:
                callback(result)
            return result
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
