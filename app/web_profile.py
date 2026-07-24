from __future__ import annotations

import logging
import os
import urllib.parse
from pathlib import Path

from PySide6.QtWebEngineCore import (
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)

from app.config import APP_NAME, web_profile_root


def _configure_profile_paths(profile: QWebEngineProfile, storage_root) -> None:
    profile.setPersistentStoragePath(str(storage_root / "storage"))
    profile.setCachePath(str(storage_root / "cache"))


def _install_clipboard_write_patch(profile: QWebEngineProfile) -> None:
    """
    Patch navigator.clipboard.writeText in web tiles so user-initiated copy
    actions keep working even when Chromium rejects the native async clipboard
    path. The fallback only writes text, does not expose read access, and does
    not grant a global clipboard permission.
    """
    script = QWebEngineScript()
    script.setName("nino-clipboard-write-fallback")
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setRunsOnSubFrames(True)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setSourceCode(
        """
        (() => {
          const clipboard = navigator.clipboard;
          if (!clipboard || clipboard.__ninoWriteTextPatched) {
            return;
          }

          const makeNotAllowedError = (message) => {
            try {
              return new DOMException(message, "NotAllowedError");
            } catch (_error) {
              const error = new Error(message);
              error.name = "NotAllowedError";
              return error;
            }
          };

          const fallbackWriteText = async (text) => {
            const value = String(text ?? "");
            const host = document.body || document.documentElement;
            if (!host) {
              throw makeNotAllowedError("Clipboard copy unavailable.");
            }

            const textarea = document.createElement("textarea");
            textarea.value = value;
            textarea.setAttribute("readonly", "");
            textarea.style.position = "fixed";
            textarea.style.left = "-9999px";
            textarea.style.top = "-9999px";
            textarea.style.opacity = "0";
            host.appendChild(textarea);
            textarea.focus();
            textarea.select();

            let copied = false;
            try {
              copied = document.execCommand("copy");
            } catch (_error) {
              copied = false;
            } finally {
              textarea.remove();
            }

            if (!copied) {
              throw makeNotAllowedError("Clipboard copy unavailable.");
            }
          };

          const extractPlainTextFromItems = async (items) => {
            const itemList = Array.from(items || []);
            for (const item of itemList) {
              if (!item || !Array.isArray(item.types) || typeof item.getType !== "function") {
                continue;
              }
              if (!item.types.includes("text/plain")) {
                continue;
              }
              try {
                const blob = await item.getType("text/plain");
                if (blob && typeof blob.text === "function") {
                  return await blob.text();
                }
              } catch (_error) {
                continue;
              }
            }
            return "";
          };

          const originalWriteText = typeof clipboard.writeText === "function"
            ? clipboard.writeText.bind(clipboard)
            : null;
          const originalWrite = typeof clipboard.write === "function"
            ? clipboard.write.bind(clipboard)
            : null;
          const patchedWriteText = async (text) => {
            if (originalWriteText) {
              try {
                return await originalWriteText(text);
              } catch (error) {
                const name = error && error.name ? String(error.name) : "";
                if (name !== "NotAllowedError" && name !== "SecurityError") {
                  throw error;
                }
              }
            }

            return fallbackWriteText(text);
          };

          const patchedWrite = async (items) => {
            if (originalWrite) {
              try {
                return await originalWrite(items);
              } catch (error) {
                const name = error && error.name ? String(error.name) : "";
                if (name !== "NotAllowedError" && name !== "SecurityError") {
                  throw error;
                }
              }
            }

            const text = await extractPlainTextFromItems(items);
            if (!text) {
              throw makeNotAllowedError("Clipboard copy unavailable.");
            }
            return fallbackWriteText(text);
          };

          try {
            Object.defineProperty(clipboard, "writeText", {
              configurable: true,
              enumerable: true,
              writable: true,
              value: patchedWriteText,
            });
          } catch (_error) {
            clipboard.writeText = patchedWriteText;
          }

          if (originalWrite) {
            try {
              Object.defineProperty(clipboard, "write", {
                configurable: true,
                enumerable: true,
                writable: true,
                value: patchedWrite,
              });
            } catch (_error) {
              clipboard.write = patchedWrite;
            }
          }

          clipboard.__ninoWriteTextPatched = true;
        })();
        """
    )
    profile.scripts().insert(script)


class SecurityPolicy:
    def __init__(self, allowed_roots: list[Path]):
        self.allowed_roots = allowed_roots

    def _is_in_allowed_roots(self, target_path_str: str) -> bool:
        try:
            target_path_str = urllib.parse.unquote(target_path_str)
            if os.name == 'nt' and target_path_str.startswith('/'):
                target_path_str = target_path_str[1:]

            abs_target = os.path.normcase(os.path.abspath(os.path.normpath(target_path_str)))
            for root in self.allowed_roots:
                abs_root = os.path.normcase(os.path.abspath(str(root)))
                if abs_target == abs_root or abs_target.startswith(abs_root + os.sep):
                    return True
            return False
        except Exception:
            return False

    def should_block(self, request_url: str, first_party_url: str) -> bool:
        try:
            req_parsed = urllib.parse.urlparse(request_url)
            first_parsed = urllib.parse.urlparse(first_party_url)
        except Exception:
            return True

        req_scheme = req_parsed.scheme.lower()
        first_scheme = first_parsed.scheme.lower()

        if req_scheme != "file":
            return False

        if first_scheme in ("http", "https", "ws", "wss"):
            return True

        if not self._is_in_allowed_roots(req_parsed.path):
            return True

        return False

class SecurityInterceptor(QWebEngineUrlRequestInterceptor):
    def __init__(self, policy: SecurityPolicy, parent=None):
        super().__init__(parent)
        self.policy = policy
        self.logger = logging.getLogger(__name__)

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        try:
            req_url = info.requestUrl().toString()
            first_url = info.firstPartyUrl().toString()

            if self.policy.should_block(req_url, first_url):
                req_scheme = info.requestUrl().scheme()
                first_scheme = info.firstPartyUrl().scheme()
                self.logger.warning("BLOCK request: source_scheme=%s target_scheme=%s", first_scheme, req_scheme)
                info.block(True)
        except RuntimeError:
            pass

_SHARED_INTERCEPTOR: SecurityInterceptor | None = None

def apply_security_configuration(profile: QWebEngineProfile) -> None:
    global _SHARED_INTERCEPTOR

    settings = profile.settings()

    if hasattr(QWebEngineSettings.WebAttribute, 'WebSecurityEnabled'):
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebSecurityEnabled, True)
    if hasattr(QWebEngineSettings.WebAttribute, 'LocalContentCanAccessFileUrls'):
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
    if hasattr(QWebEngineSettings.WebAttribute, 'LocalContentCanAccessRemoteUrls'):
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)

    if _SHARED_INTERCEPTOR is None:
        assets_root = Path(__file__).resolve().parent / "assets"
        policy = SecurityPolicy([assets_root])
        _SHARED_INTERCEPTOR = SecurityInterceptor(policy)

    profile.setUrlRequestInterceptor(_SHARED_INTERCEPTOR)
    profile._nino_security_interceptor = _SHARED_INTERCEPTOR

def build_shared_profile(parent) -> QWebEngineProfile:
    """
    Build a single shared profile for the nine tiles.

    V1 choice:
    - one shared persistent profile
    - consistent cookies/cache/session behavior
    - simpler and lighter than 9 isolated profiles

    The application structure keeps the door open for per-tile profiles later.
    """
    root = web_profile_root()
    default_profile = QWebEngineProfile.defaultProfile()
    _configure_profile_paths(default_profile, root / "default_profile")

    profile = QWebEngineProfile(APP_NAME, parent)
    _configure_profile_paths(profile, root)
    _install_clipboard_write_patch(profile)

    settings = profile.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadIconsForPage, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
    settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)

    apply_security_configuration(profile)

    return profile
