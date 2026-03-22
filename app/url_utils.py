from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QUrl


@dataclass(frozen=True)
class UrlParseResult:
    ok: bool
    url: QUrl
    normalized_text: str
    error: str = ""


def normalize_user_url(raw_text: str) -> UrlParseResult:
    """
    Normalize a user-entered URL with conservative heuristics.

    Strategy:
    - trim spaces
    - use QUrl.fromUserInput for common inputs such as google.com
    - accept only http/https in V1 to keep expectations clear
    """
    candidate = raw_text.strip()
    if not candidate:
        return UrlParseResult(False, QUrl(), "", "Veuillez saisir une adresse internet.")

    normalized = QUrl.fromUserInput(candidate)
    if not normalized.isValid():
        return UrlParseResult(False, QUrl(), "", "Adresse invalide.")

    if normalized.scheme().lower() not in {"http", "https"}:
        return UrlParseResult(
            False,
            QUrl(),
            "",
            "Seules les adresses http et https sont prises en charge dans cette version.",
        )

    if not normalized.host() and not normalized.path():
        return UrlParseResult(False, QUrl(), "", "Adresse incomplète.")

    return UrlParseResult(True, normalized, normalized.toString(), "")
