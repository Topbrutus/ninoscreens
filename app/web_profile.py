from __future__ import annotations

from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineScript, QWebEngineSettings

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

    return profile
