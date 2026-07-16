from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

from app.config import app_data_root


DEFAULT_SUMMARY_DIR = Path("D:/communication/resumes")
TRANSMISSION_STORE_FILENAME = "jules_summary_transmissions.json"


class JulesSummaryError(ValueError):
    def __init__(self, status: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True)
class JulesSummary:
    body: str
    source: str
    source_id: str
    source_path: str
    created_at: str
    sha256: str
    external_sha: str = ""

    @property
    def formatted_message(self) -> str:
        return (
            "RÉSUMÉ TRANSMIS PAR JULES\n\n"
            "Source :\n"
            f"{self.source}\n\n"
            "Date :\n"
            f"{self.created_at}\n\n"
            f"{self.body.strip()}\n\n"
            "FIN DU RÉSUMÉ JULES"
        )


def transmission_store_path() -> Path:
    return app_data_root() / TRANSMISSION_STORE_FILENAME


def load_transmission_store(path: Path | None = None) -> dict[str, Any]:
    store_path = path or transmission_store_path()
    if not store_path.exists():
        return {"schema_version": 1, "transmissions": []}
    try:
        payload = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "transmissions": []}
    if not isinstance(payload, dict):
        return {"schema_version": 1, "transmissions": []}
    transmissions = payload.get("transmissions")
    if not isinstance(transmissions, list):
        payload["transmissions"] = []
    payload.setdefault("schema_version", 1)
    return payload


def save_transmission_store(payload: Mapping[str, Any], path: Path | None = None) -> None:
    store_path = path or transmission_store_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(dict(payload), ensure_ascii=False, indent=2)
    json.loads(serialized)

    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(store_path.parent),
            prefix=f".{store_path.name}.",
            suffix=".tmp",
        ) as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = handle.name

        if temp_path is None:
            raise RuntimeError("Unable to create Jules transmission temp file")

        with open(temp_path, "r", encoding="utf-8") as handle:
            json.loads(handle.read())

        os.replace(temp_path, store_path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def has_successful_transmission(summary: JulesSummary, store: Mapping[str, Any]) -> bool:
    transmissions = store.get("transmissions", [])
    if not isinstance(transmissions, list):
        return False
    for record in transmissions:
        if not isinstance(record, dict):
            continue
        if record.get("status") != "transmis":
            continue
        if record.get("source_id") == summary.source_id or record.get("sha256") == summary.sha256:
            return True
        if summary.external_sha and record.get("external_sha") == summary.external_sha:
            return True
    return False


def has_transmission_attempt(summary: JulesSummary, store: Mapping[str, Any]) -> bool:
    transmissions = store.get("transmissions", [])
    if not isinstance(transmissions, list):
        return False
    for record in transmissions:
        if not isinstance(record, dict):
            continue
        if record.get("source_id") == summary.source_id or record.get("sha256") == summary.sha256:
            return True
        if summary.external_sha and record.get("external_sha") == summary.external_sha:
            return True
    return False


def append_transmission_record(record: Mapping[str, Any], path: Path | None = None) -> None:
    store = load_transmission_store(path)
    transmissions = store.setdefault("transmissions", [])
    if not isinstance(transmissions, list):
        transmissions = []
        store["transmissions"] = transmissions
    transmissions.append(dict(record))
    save_transmission_store(store, path)


def build_success_record(
    summary: JulesSummary,
    *,
    conversation_url: str,
    tile_number: int,
) -> dict[str, Any]:
    return {
        "summary_id": summary.source_id,
        "source_id": summary.source_id,
        "source": summary.source,
        "source_path": summary.source_path,
        "sha256": summary.sha256,
        "external_sha": summary.external_sha,
        "summary_created_at": summary.created_at,
        "conversation": {
            "tile_number": tile_number,
            "url": conversation_url,
        },
        "transmitted_at": datetime.now().isoformat(timespec="seconds"),
        "status": "transmis",
    }


def build_failure_record(
    summary: JulesSummary | None,
    *,
    status: str,
    error: str,
    conversation_url: str = "",
    tile_number: int | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "summary_id": summary.source_id if summary is not None else "",
        "source_id": summary.source_id if summary is not None else "",
        "source": summary.source if summary is not None else "",
        "source_path": summary.source_path if summary is not None else "",
        "sha256": summary.sha256 if summary is not None else "",
        "external_sha": summary.external_sha if summary is not None else "",
        "summary_created_at": summary.created_at if summary is not None else "",
        "conversation": {
            "tile_number": tile_number,
            "url": conversation_url,
        },
        "attempted_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "error": error,
    }
    return record


def summary_from_payload(payload: Mapping[str, Any]) -> JulesSummary:
    source_path = str(payload.get("source_path", "") or "").strip()
    body = str(payload.get("summary", "") or payload.get("body", "") or "").strip()
    if source_path and not body:
        try:
            body = Path(source_path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise JulesSummaryError(
                "RESUME_SOURCE_ILLISIBLE",
                f"Résumé source illisible : {exc}",
                details={"source_path": source_path},
            ) from exc

    if not body:
        raise JulesSummaryError("RESUME_INVALIDE", "Résumé vide.")

    sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
    external_sha = str(payload.get("sha", "") or payload.get("commit_sha", "") or "").strip()
    source = str(payload.get("source", "") or "").strip()
    if not source:
        source = f"fichier:{source_path}" if source_path else "résumé explicite"
    source_id = str(payload.get("source_id", "") or payload.get("github_id", "") or "").strip()
    if not source_id:
        source_id = f"sha:{external_sha}" if external_sha else f"sha256:{sha256}"
    created_at = str(payload.get("created_at", "") or payload.get("timestamp", "") or "").strip()
    if not created_at and source_path:
        try:
            created_at = datetime.fromtimestamp(Path(source_path).stat().st_mtime).isoformat(timespec="seconds")
        except OSError:
            created_at = datetime.now().isoformat(timespec="seconds")
    if not created_at:
        created_at = datetime.now().isoformat(timespec="seconds")

    summary = JulesSummary(
        body=body,
        source=source,
        source_id=source_id,
        source_path=source_path,
        created_at=created_at,
        sha256=sha256,
        external_sha=external_sha,
    )
    validate_summary(summary)
    return summary


def latest_untransmitted_summary(
    *,
    summary_dir: Path = DEFAULT_SUMMARY_DIR,
    store: Mapping[str, Any] | None = None,
    skip_attempted: bool = False,
) -> JulesSummary:
    if not summary_dir.exists():
        raise JulesSummaryError(
            "RESUME_SOURCE_ILLISIBLE",
            f"Dossier de résumés absent : {summary_dir}",
        )

    current_store = store or load_transmission_store()
    candidates = sorted(
        (path for path in summary_dir.iterdir() if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    invalid_reasons: list[str] = []
    for path in candidates:
        try:
            summary = summary_from_payload(
                {
                    "source_path": str(path),
                    "source": f"fichier:{path}",
                    "created_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
                }
            )
        except JulesSummaryError as exc:
            invalid_reasons.append(f"{path.name}: {exc.message}")
            continue
        if skip_attempted and has_transmission_attempt(summary, current_store):
            continue
        if has_successful_transmission(summary, current_store):
            continue
        return summary

    detail = "; ".join(invalid_reasons[:5])
    message = "Aucun résumé valide non transmis trouvé."
    if detail:
        message = f"{message} Résumés rejetés : {detail}"
    raise JulesSummaryError("RESUME_INVALIDE", message)


def validate_summary(summary: JulesSummary) -> None:
    text = _normalize(summary.body)
    missing = [
        label
        for label, patterns in _REQUIRED_SECTIONS.items()
        if not any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)
    ]
    if missing:
        raise JulesSummaryError(
            "RESUME_INVALIDE",
            "Résumé incomplet : sections manquantes " + ", ".join(missing) + ".",
            details={"missing_sections": missing},
        )

    secret_patterns = {
        "api_key": r"\b(?:api[_-]?key|secret[_-]?key|token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}",
        "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        "password": r"\b(?:password|mot de passe)\s*[:=]\s*\S+",
    }
    for label, pattern in secret_patterns.items():
        if re.search(pattern, summary.body, flags=re.IGNORECASE):
            raise JulesSummaryError(
                "RESUME_CONTIENT_SECRET",
                f"Résumé bloqué : secret potentiel détecté ({label}).",
                details={"secret_kind": label},
            )


def _normalize(value: str) -> str:
    return (
        value.lower()
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("à", "a")
        .replace("ù", "u")
        .replace("ç", "c")
    )


_REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "objectif": (r"\bobjectif\s*:",),
    "travail effectué": (r"\btravail effectue\s*:", r"\btravail realise\s*:"),
    "fichiers modifiés": (r"\bfichiers? (?:crees? ou )?modifies?\s*:", r"\bfichiers?\s*:"),
    "tests réalisés": (r"\btests? (?:realises?|effectues?)\s*:", r"\bverifications?\s*:"),
    "blocages ou risques": (r"\bblocages? ou risques?\s*:", r"\brisques?\s*:"),
    "commits créés": (r"\bcommits? (?:crees?|locaux?)\s*:", r"\bsha des commits?\s*:"),
    "état du push": (r"\betat du push\s*:", r"\bpush\s*:"),
    "prochaine action proposée": (r"\bprochaine action (?:proposee|unique)\s*:",),
}
