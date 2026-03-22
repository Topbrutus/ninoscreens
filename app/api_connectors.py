from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ApiServiceDefinition:
    service_id: str
    label: str
    default_base_url: str
    default_test_path: str
    description: str


@dataclass(frozen=True)
class ApiConnectionSettings:
    service_id: str
    base_url: str
    api_key: str
    test_path: str
    timeout_seconds: float = 8.0


@dataclass(frozen=True)
class ApiConnectionResult:
    ok: bool
    message: str
    service_id: str
    base_url: str
    http_status: int | None = None
    masked_key_hint: str = ""
    requires_human_validation: bool = False


SERVICES: Final[dict[str, ApiServiceDefinition]] = {
    "openai-compatible": ApiServiceDefinition(
        service_id="openai-compatible",
        label="OpenAI compatible",
        default_base_url="https://api.openai.com",
        default_test_path="/v1/models",
        description="Connexion Bearer classique vers une API compatible OpenAI.",
    ),
    "custom-bearer": ApiServiceDefinition(
        service_id="custom-bearer",
        label="Custom Bearer",
        default_base_url="https://api.exemple.com",
        default_test_path="/",
        description="Connexion Bearer générique avec chemin de test personnalisable.",
    ),
}


def get_service_definition(service_id: str) -> ApiServiceDefinition:
    return SERVICES.get(service_id, SERVICES["openai-compatible"])


def list_service_definitions() -> list[ApiServiceDefinition]:
    return list(SERVICES.values())


def mask_api_key(api_key: str) -> str:
    clean = api_key.strip()
    if not clean:
        return ""
    if len(clean) <= 6:
        return "•" * len(clean)
    return f"{clean[:3]}{'• * max(4, len(clean) - 6)}{clean[-3:]}"


def build_test_url(base_url: str, test_path: str) -> str:
    normalized_base = base_url.strip().rstrip("/") + "/"
    normalized_path = test_path.strip() or "/"
    if not normalized_path.startswith("/"):
        normalized_path = "/" + normalized_path
    return urljoin(normalized_base, normalized_path[1:])


def test_api_connection(settings: ApiConnectionSettings) -> ApiConnectionResult:
    base_url = settings.base_url.strip()
    api_key = settings.api_key.strip()
    test_path = settings.test_path.strip()

    if not base_url:
        return ApiConnectionResult(
            ok=False,
            message="Base URL requise.",
            service_id=settings.service_id,
            base_url=base_url,
        )
    if not api_key:
        return ApiConnectionResult(
            ok=False,
            message="Clé API requise.",
            service_id=settings.service_id,
            base_url=base_url,
        )

    target_url = build_test_url(base_url, test_path)
    request = Request(
        target_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "ninoscreens/agent-cockpit",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=settings.timeout_seconds) as response:
            status = getattr(response, "status", None) or response.getcode()
            body = response.read(2048)
    except HTTPError as exc:
        status = exc.code
        if status in {401, 403}:
            return ApiConnectionResult(
                ok=False,
                message="Clé API refusée par le service.",
                service_id=settings.service_id,
                base_url=base_url,
                http_status=status,
            )
        if status == 404:
            return ApiConnectionResult(
                ok=False,
                message="Point de test introuvable. Vérifier le service ou le chemin.",
                service_id=settings.service_id,
                base_url=base_url,
                http_status=status,
                requires_human_validation=True,
            )
        return ApiConnectionResult(
            ok=False,
            message=f"Le service a répondu avec le code {status}.",
            service_id=settings.service_id,
            base_url=base_url,
            http_status=status,
            requires_human_validation=status >= 500,
        )
    except URLError as exc:
        return ApiConnectionResult(
            ok=False,
            message=f"Connexion impossible : {exc.reason}",
            service_id=settings.service_id,
            base_url=base_url,
            requires_human_validation=True,
        )
    except Exception as exc:  # pragma: no cover - runtime safety
        return ApiConnectionResult(
            ok=False,
            message=f"Erreur réseau interne : {exc}",
            service_id=settings.service_id,
            base_url=base_url,
            requires_human_validation=True,
        )

    if status and 200 <= status < 300:
        parsed_hint = ""
        try:
            parsed = json.loads(body.decode("utf-8") or "{}")
            if isinstance(parsed, dict):
                parsed_hint = str(parsed.get("object", "")).strip()
        except Exception:
            parsed_hint = ""

        message = "Connexion API validée."
        if parsed_hint:
            message = f"Connexion API validée ({parsed_hint})."

        return ApiConnectionResult(
            ok=True,
            message=message,
            service_id=settings.service_id,
            base_url=base_url,
            http_status=status,
            masked_key_hint=mask_api_key(api_key),
        )

    return ApiConnectionResult(
        ok=False,
        message="Réponse inattendue du service.",
        service_id=settings.service_id,
        base_url=base_url,
        http_status=status,
        requires_human_validation=True,
    )
