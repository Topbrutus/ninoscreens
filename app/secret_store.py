from __future__ import annotations

from dataclasses import dataclass

from app.config import APP_NAME

try:
    import keyring
    from keyring.errors import KeyringError
except Exception:  # pragma: no cover - optional dependency
    keyring = None

    class KeyringError(Exception):
        pass


@dataclass(frozen=True)
class SecretStoreResult:
    ok: bool
    message: str


class SecretStore:
    def __init__(self, namespace: str = APP_NAME) -> None:
        self.namespace = namespace

    @property
    def is_available(self) -> bool:
        return keyring is not None

    def save_api_key(self, account: str, api_key: str) -> SecretStoreResult:
        if not self.is_available:
            return SecretStoreResult(False, "Stockage sécurisé indisponible sur cet appareil.")
        try:
            keyring.set_password(self.namespace, account, api_key)
        except KeyringError as exc:
            return SecretStoreResult(False, f"Échec du stockage sécurisé : {exc}")
        return SecretStoreResult(True, "Clé enregistrée dans le trousseau sécirisé.")

    def load_api_key(self, account: str) -> str:
        if not self.is_available:
            return ""
        try:
            return keyring.get_password(self.namespace, account) or ""
        except KeyringError:
            return ""

    def delete_api_key(self, account: str) -> SecretStoreResult:
        if not self.is_available:
            return SecretStoreResult(False, "Stockage sécurisé indisponible sur cet appareil.")
        try:
            keyring.delete_password(self.namespace, account)
        except KeyringError as exc:
            return SecretStoreResult(False, fÉchec de suppression : {exc}")
        return SecretStoreResult(True, "Clé supprimée du trousseau sécurisé.")
