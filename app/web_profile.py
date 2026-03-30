from __future__ import annotations

from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings

from app.config import APP_NAME, web_profile_root


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
    profile = QWebEngineProfile(APP_NAME, parent)
    profile.setPersistentStoragePath(str(root / "storage"))
    profile.setCachePath(str(root / "cache"))

    settings = profile.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadIconsForPage, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
    settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.AllowWindowActivationFromJavaScript, True)

    profile.downloadRequested.connect(_handle_download)

    return profile


def _handle_download(download) -> None:
    import os
    from PySide6.QtWebEngineCore import QWebEngineDownloadRequest
    download_dir = os.path.expanduser("~/Téléchargements")
    os.makedirs(download_dir, exist_ok=True)
    download.setDownloadDirectory(download_dir)
    download.accept()
