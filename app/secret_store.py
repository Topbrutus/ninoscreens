from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from app.config import APP_NAME


class _KeyringBackend(Protocol):
    def set_password(self, service_name: str, username: str, password: str) -> None:
        ...

    def get_password(self, service_name: str, username: str) -> str | None:
        ...

    def delete_password(self, service_name: str, username: str) -> None:
        ...


try:
    import keyring as _imported_keyring
    from keyring.errors import KeyringError as _ImportedKeyringError
except Exception:  # pragma: no cover - optional dependency
    keyring_backend: _KeyringBackend | None = None
    keyring_error_type: type[Exception] = Exception
else:
    keyring_backend = _imported_keyring
    keyring_error_type = _ImportedKeyringError


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SecretStoreResult:
    ok: bool
    message: str


class _DefaultBackend:
    pass


_DEFAULT_BACKEND = _DefaultBackend()


class SecretStore:
    def __init__(
        self,
        namespace: str = APP_NAME,
        *,
        backend: _KeyringBackend | None | _DefaultBackend = _DEFAULT_BACKEND,
        keyring_errors: type[Exception] | tuple[type[Exception], ...] | None = None,
    ) -> None:
        self.namespace = namespace
        if isinstance(backend, _DefaultBackend):
            self._backend = keyring_backend
        else:
            self._backend = backend
        self._keyring_errors = keyring_error_type if keyring_errors is None else keyring_errors

    @property
    def is_available(self) -> bool:
        return self._backend is not None

    def save_api_key(self, account: str, api_key: str) -> SecretStoreResult:
        if not account or not isinstance(account, str) or not account.strip():
            return SecretStoreResult(False, "Compte invalide.")
        if not api_key or not isinstance(api_key, str):
            return SecretStoreResult(False, "Clé invalide.")

        account = account.strip()
        backend = self._backend
        if backend is None:
            return SecretStoreResult(False, "Stockage sécurisé indisponible.")
        try:
            backend.set_password(self.namespace, account, api_key)
        except self._keyring_errors as exc:
            logger.error("Erreur Keyring (save_api_key) : %s", type(exc).__name__)
            return SecretStoreResult(False, "Échec interne du stockage sécurisé.")
        except Exception as exc:
            logger.error("Erreur inattendue (save_api_key) : %s", type(exc).__name__)
            return SecretStoreResult(False, "Échec interne inattendu.")
        return SecretStoreResult(True, "Clé enregistrée avec succès.")

    def load_api_key(self, account: str) -> str:
        if not account or not isinstance(account, str) or not account.strip():
            return ""

        account = account.strip()
        backend = self._backend
        if backend is None:
            return ""
        try:
            result = backend.get_password(self.namespace, account)
            return result if result is not None else ""
        except self._keyring_errors as exc:
            logger.error("Erreur Keyring (load_api_key) : %s", type(exc).__name__)
            return ""
        except Exception as exc:
            logger.error("Erreur inattendue (load_api_key) : %s", type(exc).__name__)
            return ""

    def delete_api_key(self, account: str) -> SecretStoreResult:
        if not account or not isinstance(account, str) or not account.strip():
            return SecretStoreResult(False, "Compte invalide.")

        account = account.strip()
        backend = self._backend
        if backend is None:
            return SecretStoreResult(False, "Stockage sécurisé indisponible.")
        try:
            backend.delete_password(self.namespace, account)
        except self._keyring_errors as exc:
            logger.error("Erreur Keyring (delete_api_key) : %s", type(exc).__name__)
            return SecretStoreResult(False, "Échec interne lors de la suppression.")
        except Exception as exc:
            logger.error("Erreur inattendue (delete_api_key) : %s", type(exc).__name__)
            return SecretStoreResult(False, "Échec interne inattendu.")
        return SecretStoreResult(True, "Clé supprimée avec succès.")
