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
    import os
    chrome_default = os.path.expanduser("~/.config/google-chrome/Default")
    if os.path.exists(chrome_default):
        profile.setPersistentStoragePath(chrome_default)
        profile.setCachePath(os.path.expanduser("~/.config/google-chrome/Default/Cache"))
    else:
        profile.setPersistentStoragePath(str(root / "storage"))
        profile.setCachePath(str(root / "cache"))

    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
    )

    settings = profile.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadIconsForPage, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)

    profile.setHttpUserAgent(
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
    )

    return profile
