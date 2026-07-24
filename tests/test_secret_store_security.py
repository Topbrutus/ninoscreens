from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.secret_store import SecretStore

TEST_SECRET_SENTINEL = "NINO_TEST_SECRET_DO_NOT_PERSIST_7C91A2"
BACKEND_EXCEPTION_SENTINEL = "NINO_BACKEND_EXCEPTION_SECRET_91D4"


class DummyKeyringError(Exception):
    pass


class DummyNoKeyringError(DummyKeyringError):
    pass


class DummyLockedKeyringError(DummyKeyringError):
    pass


class DummyKeyringBackend:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}
        self.raise_on_set: type[Exception] | None = None
        self.raise_on_get: type[Exception] | None = None
        self.raise_on_delete: type[Exception] | None = None
        self.raise_message = ""

    def _raise_if_configured(self, error_type: type[Exception] | None) -> None:
        if error_type is not None:
            raise error_type(self.raise_message)

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self._raise_if_configured(self.raise_on_set)
        self.store[(service_name, username)] = password

    def get_password(self, service_name: str, username: str) -> str | None:
        self._raise_if_configured(self.raise_on_get)
        return self.store.get((service_name, username))

    def delete_password(self, service_name: str, username: str) -> None:
        self._raise_if_configured(self.raise_on_delete)
        if (service_name, username) not in self.store:
            raise DummyKeyringError("Not found")
        del self.store[(service_name, username)]


class TestSecretStoreSecurity(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = DummyKeyringBackend()
        self.store = SecretStore(
            "test_namespace",
            backend=self.backend,
            keyring_errors=(DummyKeyringError, DummyNoKeyringError, DummyLockedKeyringError),
        )

    def test_save_success_with_injected_backend(self) -> None:
        res = self.store.save_api_key("user1", TEST_SECRET_SENTINEL)

        self.assertTrue(res.ok)
        self.assertNotIn(TEST_SECRET_SENTINEL, res.message)
        self.assertEqual(self.backend.store[("test_namespace", "user1")], TEST_SECRET_SENTINEL)

    def test_load_success_with_injected_backend(self) -> None:
        self.backend.store[("test_namespace", "user1")] = TEST_SECRET_SENTINEL

        val = self.store.load_api_key("user1")

        self.assertEqual(val, TEST_SECRET_SENTINEL)

    def test_delete_success_with_injected_backend(self) -> None:
        self.backend.store[("test_namespace", "user1")] = TEST_SECRET_SENTINEL

        res = self.store.delete_api_key("user1")

        self.assertTrue(res.ok)
        self.assertNotIn(TEST_SECRET_SENTINEL, res.message)
        self.assertNotIn(("test_namespace", "user1"), self.backend.store)

    def test_backend_absent_fails_closed(self) -> None:
        store = SecretStore("test_namespace", backend=None, keyring_errors=DummyKeyringError)

        self.assertFalse(store.is_available)
        res = store.save_api_key("user1", TEST_SECRET_SENTINEL)
        res_del = store.delete_api_key("user1")

        self.assertFalse(res.ok)
        self.assertFalse(res_del.ok)
        self.assertEqual(store.load_api_key("user1"), "")
        self.assertNotIn(TEST_SECRET_SENTINEL, res.message)
        self.assertNotIn(TEST_SECRET_SENTINEL, res_del.message)

    def test_no_keyring_error_is_generic(self) -> None:
        self.backend.raise_on_set = DummyNoKeyringError
        self.backend.raise_message = f"No backend: {BACKEND_EXCEPTION_SENTINEL}"

        with self.assertLogs("app.secret_store", level="ERROR") as log_mock:
            res = self.store.save_api_key("user1", TEST_SECRET_SENTINEL)

        self.assertFalse(res.ok)
        self.assertNotIn(BACKEND_EXCEPTION_SENTINEL, res.message)
        self.assertNotIn(TEST_SECRET_SENTINEL, res.message)
        self._assert_logs_do_not_contain_sentinels(log_mock.output)

    def test_locked_keyring_error_is_generic(self) -> None:
        self.backend.raise_on_get = DummyLockedKeyringError
        self.backend.raise_message = f"Locked: {BACKEND_EXCEPTION_SENTINEL}"

        with self.assertLogs("app.secret_store", level="ERROR") as log_mock:
            val = self.store.load_api_key("user1")

        self.assertEqual(val, "")
        self._assert_logs_do_not_contain_sentinels(log_mock.output)

    def test_sensitive_backend_exception_message_not_public_or_logged(self) -> None:
        self.backend.raise_on_set = DummyKeyringError
        self.backend.raise_message = f"Error with {BACKEND_EXCEPTION_SENTINEL}"

        with self.assertLogs("app.secret_store", level="ERROR") as log_mock:
            res = self.store.save_api_key("user1", TEST_SECRET_SENTINEL)

        self.assertFalse(res.ok)
        self.assertNotIn(BACKEND_EXCEPTION_SENTINEL, res.message)
        self.assertNotIn(TEST_SECRET_SENTINEL, res.message)
        self._assert_logs_do_not_contain_sentinels(log_mock.output)

    def test_unexpected_exception_message_not_public_or_logged(self) -> None:
        with patch.object(
            self.backend,
            "set_password",
            side_effect=ValueError(f"Generic {BACKEND_EXCEPTION_SENTINEL}"),
        ):
            with self.assertLogs("app.secret_store", level="ERROR") as log_mock:
                res = self.store.save_api_key("user1", TEST_SECRET_SENTINEL)

        self.assertFalse(res.ok)
        self.assertNotIn(BACKEND_EXCEPTION_SENTINEL, res.message)
        self.assertNotIn(TEST_SECRET_SENTINEL, res.message)
        self._assert_logs_do_not_contain_sentinels(log_mock.output)

    def test_system_backend_not_called_when_fake_backend_is_injected(self) -> None:
        system_backend = Mock()
        system_backend.set_password.side_effect = AssertionError("system set_password called")
        system_backend.get_password.side_effect = AssertionError("system get_password called")
        system_backend.delete_password.side_effect = AssertionError("system delete_password called")

        with patch("app.secret_store.keyring_backend", system_backend):
            store = SecretStore(
                "test_namespace",
                backend=self.backend,
                keyring_errors=DummyKeyringError,
            )
            self.assertTrue(store.save_api_key("user1", TEST_SECRET_SENTINEL).ok)
            self.assertEqual(store.load_api_key("user1"), TEST_SECRET_SENTINEL)
            self.assertTrue(store.delete_api_key("user1").ok)

        system_backend.set_password.assert_not_called()
        system_backend.get_password.assert_not_called()
        system_backend.delete_password.assert_not_called()

    def test_ci_environment_does_not_auto_enable_fake_backend(self) -> None:
        with patch.dict(os.environ, {"CI": "true"}, clear=False):
            with patch("app.secret_store.keyring_backend", None):
                store = SecretStore("test_namespace")

        self.assertFalse(store.is_available)
        self.assertFalse(store.save_api_key("user1", TEST_SECRET_SENTINEL).ok)
        self.assertEqual(store.load_api_key("user1"), "")

    def test_dbus_environment_is_not_required_for_injected_backend(self) -> None:
        with patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": ""}, clear=False):
            res = self.store.save_api_key("user1", TEST_SECRET_SENTINEL)

        self.assertTrue(res.ok)
        self.assertEqual(self.store.load_api_key("user1"), TEST_SECRET_SENTINEL)

    def test_sentinels_are_not_written_to_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            res = self.store.save_api_key("user1", TEST_SECRET_SENTINEL)
            self.backend.raise_on_get = DummyKeyringError
            self.backend.raise_message = f"Backend detail {BACKEND_EXCEPTION_SENTINEL}"
            self.assertEqual(self.store.load_api_key("user1"), "")

            self.assertTrue(res.ok)
            self._assert_tree_has_no_sentinels(temp_path)

    def test_delete_error_is_generic(self) -> None:
        self.backend.store[("test_namespace", "user1")] = TEST_SECRET_SENTINEL
        self.backend.raise_on_delete = DummyLockedKeyringError
        self.backend.raise_message = f"Delete failed {BACKEND_EXCEPTION_SENTINEL}"

        with self.assertLogs("app.secret_store", level="ERROR") as log_mock:
            res = self.store.delete_api_key("user1")

        self.assertFalse(res.ok)
        self.assertNotIn(BACKEND_EXCEPTION_SENTINEL, res.message)
        self.assertNotIn(TEST_SECRET_SENTINEL, res.message)
        self._assert_logs_do_not_contain_sentinels(log_mock.output)

    def test_missing_entry_contract(self) -> None:
        self.assertEqual(self.store.load_api_key("unknown"), "")

        res = self.store.delete_api_key("unknown")

        self.assertFalse(res.ok)
        self.assertNotIn(TEST_SECRET_SENTINEL, res.message)

    def test_empty_account_rejected(self) -> None:
        res = self.store.save_api_key("", TEST_SECRET_SENTINEL)
        res_del = self.store.delete_api_key(" ")

        self.assertFalse(res.ok)
        self.assertEqual(self.store.load_api_key(""), "")
        self.assertFalse(res_del.ok)

    def test_empty_key_rejected(self) -> None:
        res = self.store.save_api_key("user1", "")

        self.assertFalse(res.ok)

    def _assert_logs_do_not_contain_sentinels(self, log_lines: list[str]) -> None:
        for record in log_lines:
            self.assertNotIn(TEST_SECRET_SENTINEL, record)
            self.assertNotIn(BACKEND_EXCEPTION_SENTINEL, record)

    def _assert_tree_has_no_sentinels(self, root: Path) -> None:
        for path in root.rglob("*"):
            if path.is_file():
                content = path.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn(TEST_SECRET_SENTINEL, content)
                self.assertNotIn(BACKEND_EXCEPTION_SENTINEL, content)


if __name__ == "__main__":
    unittest.main()
