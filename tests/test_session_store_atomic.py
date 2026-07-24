import hashlib
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.session_store import (
    load_session_payload,
    save_session_payload,
)

LOG_SENTINELS = (
    "NINO_SESSION_PRIMARY_SECRET_54A1",
    "NINO_SESSION_BACKUP_SECRET_72C9",
    "NINO_TEST_SECRET_DO_NOT_PERSIST_7C91A2",
)


def _snapshot_files(directory: Path) -> dict[str, dict[str, object]]:
    snapshot: dict[str, dict[str, object]] = {}
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        stat = path.stat()
        snapshot[path.name] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        }
    return snapshot


class TestSessionStoreAtomic(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp_dir.name)
        self.appdata_dir = self.data_root / "appdata"
        self.appdata_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.appdata_dir / "dashboard_session.json"
        self.bak_file = self.session_file.with_name(self.session_file.name + ".bak")
        
        self.env_patcher = patch.dict(os.environ, {"NINO_DATA_ROOT": str(self.data_root)})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.temp_dir.cleanup()

    def test_normal_save_and_load(self):
        payload = {"schema_version": 5, "test": "valeur"}
        save_session_payload(payload)
        
        loaded = load_session_payload()
        self.assertEqual(loaded, payload)

    def test_utf8_french_characters(self):
        payload = {"schema_version": 5, "message": "éàçù€îï"}
        save_session_payload(payload)
        
        loaded = load_session_payload()
        self.assertEqual(loaded, payload)
        
        raw_bytes = self.session_file.read_bytes()
        self.assertIn("éàçù€îï".encode("utf-8"), raw_bytes)

    def test_temp_file_in_same_dir(self):
        with patch("app.session_store.os.replace") as mock_replace:
            payload = {"schema_version": 5}
            save_session_payload(payload)
            
            self.assertTrue(mock_replace.called)
            temp_path = mock_replace.call_args[0][0]
            self.assertTrue(str(temp_path).startswith(str(self.appdata_dir)))

    def test_flush_and_fsync_called(self):
        with patch("app.session_store.os.fsync") as mock_fsync:
            with patch("app.session_store._sync_dir"):
                payload = {"schema_version": 5}
                save_session_payload(payload)
                self.assertTrue(mock_fsync.called)

    def test_os_replace_after_validation(self):
        with patch("app.session_store.json.loads") as mock_loads:
            # json.loads fails when parsing the temporary file
            mock_loads.side_effect = [None, json.JSONDecodeError("msg", "doc", 0)]
            
            payload = {"schema_version": 5}
            with self.assertRaises(json.JSONDecodeError):
                save_session_payload(payload)
            
            self.assertFalse(self.session_file.exists())

    def test_interrupt_during_write_preserves_previous(self):
        payload1 = {"schema_version": 5, "version": 1}
        save_session_payload(payload1)
        
        with patch("app.session_store.tempfile.NamedTemporaryFile") as mock_temp:
            mock_temp.side_effect = KeyboardInterrupt()
            
            with self.assertRaises(KeyboardInterrupt):
                save_session_payload({"schema_version": 5, "version": 2})
                
        self.assertEqual(load_session_payload(), payload1)

    def test_failure_on_replace_preserves_previous_and_removes_temp(self):
        payload1 = {"schema_version": 5, "version": 1}
        save_session_payload(payload1)
        
        with patch("app.session_store.os.replace") as mock_replace:
            def side_effect(src, dst):
                if dst == self.session_file:
                    raise OSError("Permission denied")
                else:
                    os.rename(src, dst)
            mock_replace.side_effect = side_effect
            
            with self.assertRaises(OSError):
                save_session_payload({"schema_version": 5, "version": 2})
                
        self.assertEqual(load_session_payload(), payload1)
        temp_files_after = set(self.appdata_dir.iterdir())
        self.assertEqual(len(temp_files_after), 2)
        self.assertTrue(self.bak_file.exists())

    def test_new_session_invalid_no_replacement(self):
        payload1 = {"schema_version": 5, "version": 1}
        save_session_payload(payload1)
        
        payload2 = {"schema_version": 5, "version": object()}
        with self.assertRaises(TypeError):
            save_session_payload(payload2)
            
        self.assertEqual(load_session_payload(), payload1)

    def test_restore_from_bak_when_session_corrupt(self):
        payload = {"schema_version": 5, "version": 1}
        save_session_payload(payload)
        save_session_payload({"schema_version": 5, "version": 2})
        
        self.session_file.write_text("invalid json")
        
        loaded = load_session_payload()
        self.assertEqual(loaded, {"schema_version": 5, "version": 1})

    def test_bak_invalid_fails_cleanly(self):
        save_session_payload({"schema_version": 5, "version": 1})
        save_session_payload({"schema_version": 5, "version": 2})
        
        self.session_file.write_text("invalid")
        self.bak_file.write_text("invalid also")
        
        loaded = load_session_payload()
        self.assertIsNone(loaded)

    def test_two_successive_saves(self):
        save_session_payload({"schema_version": 5, "version": 1})
        self.assertTrue(self.session_file.exists())
        self.assertFalse(self.bak_file.exists())
        
        save_session_payload({"schema_version": 5, "version": 2})
        self.assertTrue(self.session_file.exists())
        self.assertTrue(self.bak_file.exists())
        
        self.assertEqual(load_session_payload(), {"schema_version": 5, "version": 2})

    def test_no_fake_api_key_when_secret_reference_present(self):
        payload = {"schema_version": 5, "account": "user", "secret_reference": "keyring:api_key"}
        save_session_payload(payload)
        loaded = load_session_payload()
        self.assertEqual(loaded, payload)

    def test_windows_compatible_no_fsync_dir(self):
        from app.session_store import _sync_dir
        with patch("app.session_store.os.name", "posix"):
            with patch("app.session_store.os.open") as mock_open:
                mock_open.side_effect = OSError("Not a directory")
                
                class DummyPath:
                    def __str__(self): return "dummy"
                _sync_dir(DummyPath())
                self.assertTrue(mock_open.called)

    def test_no_residual_temp_file_on_success(self):
        save_session_payload({"schema_version": 5})
        files = list(self.appdata_dir.iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0], self.session_file)

    def test_reject_api_key_root(self):
        with self.assertRaises(ValueError):
            save_session_payload({"api_key": "NINO_TEST_SECRET_DO_NOT_PERSIST_7C91A2"})

    def test_reject_access_token_nested(self):
        with self.assertRaises(ValueError):
            save_session_payload({"nested": {"access_token": "NINO_TEST_SECRET_DO_NOT_PERSIST_7C91A2"}})

    def test_reject_password_in_list(self):
        with self.assertRaises(ValueError):
            save_session_payload({"items": [{"password": "NINO_TEST_SECRET_DO_NOT_PERSIST_7C91A2"}]})

    def test_case_insensitive_rejection(self):
        with self.assertRaises(ValueError):
            save_session_payload({"API_KEY": "NINO_TEST_SECRET_DO_NOT_PERSIST_7C91A2"})

    def test_original_payload_not_modified(self):
        payload = {"valid": "yes", "nested": {"valid": "yes"}}
        import copy
        payload_copy = copy.deepcopy(payload)
        save_session_payload(payload)
        self.assertEqual(payload, payload_copy)

    def test_existing_session_preserved_after_rejection(self):
        save_session_payload({"valid": "yes"})
        with self.assertRaises(ValueError):
            save_session_payload({"password": "NINO_TEST_SECRET_DO_NOT_PERSIST_7C91A2"})
        self.assertEqual(load_session_payload(), {"valid": "yes"})

    def test_bak_preserved_after_rejection(self):
        save_session_payload({"valid": "v1"})
        save_session_payload({"valid": "v2"})
        self.assertTrue(self.bak_file.exists())
        bak_content = self.bak_file.read_text()
        
        with self.assertRaises(ValueError):
            save_session_payload({"password": "NINO_TEST_SECRET_DO_NOT_PERSIST_7C91A2"})
            
        self.assertEqual(self.bak_file.read_text(), bak_content)

    def test_no_tmp_created_after_rejection(self):
        save_session_payload({"valid": "yes"})
        files_before = set(self.appdata_dir.iterdir())
        
        with self.assertRaises(ValueError):
            save_session_payload({"api_key": "NINO_TEST_SECRET_DO_NOT_PERSIST_7C91A2"})
            
        files_after = set(self.appdata_dir.iterdir())
        self.assertEqual(files_before, files_after)

    def test_allowed_references(self):
        payload = {
            "secret_reference": "not_a_secret_reference_id",
            "secret_account": "user",
            "has_secret": True,
            "token_count": 5
        }
        save_session_payload(payload)
        self.assertEqual(load_session_payload(), payload)


class TestSessionStoreLoadHardening(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp_dir.name)
        self.appdata_dir = self.data_root / "appdata"
        self.appdata_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.appdata_dir / "dashboard_session.json"
        self.bak_file = self.session_file.with_name(self.session_file.name + ".bak")

        self.env_patcher = patch.dict(os.environ, {"NINO_DATA_ROOT": str(self.data_root)})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.temp_dir.cleanup()

    def _write_primary(self, content: str | bytes) -> None:
        if isinstance(content, bytes):
            self.session_file.write_bytes(content)
        else:
            self.session_file.write_text(content, encoding="utf-8")

    def _write_backup(self, payload: dict[str, object]) -> None:
        self.bak_file.write_text(json.dumps(payload), encoding="utf-8")

    def _assert_no_log_sentinels(self, records: list[logging.LogRecord]) -> None:
        combined = " ".join(record.getMessage() for record in records)
        for sentinel in LOG_SENTINELS:
            self.assertNotIn(sentinel, combined)

    def _assert_no_exception_text_in_logs(self, records: list[logging.LogRecord]) -> None:
        combined = " ".join(record.getMessage() for record in records).lower()
        for token in ("traceback", "jsondecodeerror", "unicodeerror", "permission denied"):
            self.assertNotIn(token, combined)

    def _assert_files_unchanged(
        self,
        before: dict[str, dict[str, object]],
        after: dict[str, dict[str, object]],
    ) -> None:
        self.assertEqual(set(before.keys()), set(after.keys()))
        for name, before_meta in before.items():
            after_meta = after[name]
            self.assertEqual(before_meta["sha256"], after_meta["sha256"])
            self.assertEqual(before_meta["size"], after_meta["size"])
            self.assertEqual(before_meta["mtime"], after_meta["mtime"])

    def test_primary_valid_backup_present_uses_primary_only(self) -> None:
        primary = {"schema_version": 5, "version": "primary"}
        backup = {"schema_version": 5, "version": "backup"}
        self._write_primary(json.dumps(primary))
        self._write_backup(backup)

        loaded = load_session_payload()
        self.assertEqual(loaded, primary)

    def test_primary_missing_backup_valid(self) -> None:
        backup = {"schema_version": 5, "version": "backup"}
        self._write_backup(backup)

        with self.assertLogs("app.session_store", level="WARNING") as captured:
            loaded = load_session_payload()

        self.assertEqual(loaded, backup)
        self._assert_no_log_sentinels(captured.records)
        self._assert_no_exception_text_in_logs(captured.records)

    def test_primary_empty_backup_valid(self) -> None:
        self._write_primary("")
        backup = {"schema_version": 5, "version": "backup"}
        self._write_backup(backup)

        with self.assertLogs("app.session_store", level="WARNING") as captured:
            loaded = load_session_payload()

        self.assertEqual(loaded, backup)
        self.assertTrue(any("using backup store" in record.getMessage() for record in captured.records))

    def test_primary_corrupt_json_backup_valid(self) -> None:
        self._write_primary("{not json")
        backup = {"schema_version": 5, "version": "backup"}
        self._write_backup(backup)

        with self.assertLogs("app.session_store", level="WARNING"):
            loaded = load_session_payload()

        self.assertEqual(loaded, backup)

    def test_primary_truncated_backup_valid(self) -> None:
        self._write_primary('{"schema_version": 5, "version":')
        backup = {"schema_version": 5, "version": "backup"}
        self._write_backup(backup)

        with self.assertLogs("app.session_store", level="WARNING"):
            loaded = load_session_payload()

        self.assertEqual(loaded, backup)

    def test_primary_non_utf8_backup_valid(self) -> None:
        self._write_primary(b"\xff\xfe\x00\x7b")
        backup = {"schema_version": 5, "version": "backup"}
        self._write_backup(backup)

        with self.assertLogs("app.session_store", level="WARNING"):
            loaded = load_session_payload()

        self.assertEqual(loaded, backup)

    def test_primary_inaccessible_backup_valid(self) -> None:
        backup = {"schema_version": 5, "version": "backup"}
        self._write_primary(json.dumps({"schema_version": 5, "version": "primary"}))
        self._write_backup(backup)
        session_file = self.session_file
        original_read_text = Path.read_text

        def read_text_side_effect(path_self, *args, **kwargs):
            if path_self == session_file:
                raise OSError("access denied")
            return original_read_text(path_self, *args, **kwargs)

        with patch.object(Path, "read_text", read_text_side_effect):
            with self.assertLogs("app.session_store", level="WARNING") as captured:
                loaded = load_session_payload()

        self.assertEqual(loaded, backup)
        self._assert_no_exception_text_in_logs(captured.records)

    def test_primary_invalid_structure_backup_valid(self) -> None:
        self._write_primary(json.dumps([1, 2, 3]))
        backup = {"schema_version": 5, "version": "backup"}
        self._write_backup(backup)

        with self.assertLogs("app.session_store", level="WARNING"):
            loaded = load_session_payload()

        self.assertEqual(loaded, backup)

    def test_primary_and_backup_invalid_return_none(self) -> None:
        self._write_primary("{bad")
        self.bak_file.write_text("{also bad", encoding="utf-8")

        with self.assertLogs("app.session_store", level="WARNING") as captured:
            loaded = load_session_payload()

        self.assertIsNone(loaded)
        self.assertTrue(
            any(
                "primary and backup stores unavailable or invalid" in record.getMessage()
                for record in captured.records
            )
        )

    def test_primary_sensitive_key_rejected_uses_backup(self) -> None:
        self._write_primary(
            json.dumps({"schema_version": 5, "api_key": "NINO_SESSION_PRIMARY_SECRET_54A1"})
        )
        backup = {"schema_version": 5, "version": "backup"}
        self._write_backup(backup)

        with self.assertLogs("app.session_store", level="WARNING") as captured:
            loaded = load_session_payload()

        self.assertEqual(loaded, backup)
        self._assert_no_log_sentinels(captured.records)

    def test_backup_sensitive_key_rejected(self) -> None:
        self._write_primary("{bad")
        self.bak_file.write_text(
            json.dumps({"schema_version": 5, "token": "NINO_SESSION_BACKUP_SECRET_72C9"}),
            encoding="utf-8",
        )

        with self.assertLogs("app.session_store", level="WARNING") as captured:
            loaded = load_session_payload()

        self.assertIsNone(loaded)
        self._assert_no_log_sentinels(captured.records)

    def test_sensitive_key_nested_dict(self) -> None:
        self._write_primary(json.dumps({"nested": {"client_secret": "x"}}))
        backup = {"schema_version": 5, "version": "backup"}
        self._write_backup(backup)

        with self.assertLogs("app.session_store", level="WARNING"):
            loaded = load_session_payload()

        self.assertEqual(loaded, backup)

    def test_sensitive_key_nested_list(self) -> None:
        self._write_primary(json.dumps({"items": [{"password": "x"}]}))
        backup = {"schema_version": 5, "version": "backup"}
        self._write_backup(backup)

        with self.assertLogs("app.session_store", level="WARNING"):
            loaded = load_session_payload()

        self.assertEqual(loaded, backup)

    def test_sensitive_key_nested_list_and_dict(self) -> None:
        self._write_primary(json.dumps({"groups": [{"entries": [{"authorization": "x"}]}]}))
        backup = {"schema_version": 5, "version": "backup"}
        self._write_backup(backup)

        with self.assertLogs("app.session_store", level="WARNING"):
            loaded = load_session_payload()

        self.assertEqual(loaded, backup)

    def test_allowed_reference_keys_on_load(self) -> None:
        payload = {
            "schema_version": 5,
            "secret_reference": "ref",
            "secret_account": "user",
            "has_secret": True,
            "token_count": 3,
        }
        self._write_primary(json.dumps(payload))

        loaded = load_session_payload()
        self.assertEqual(loaded, payload)

    def test_fallback_emits_generic_warning(self) -> None:
        backup = {"schema_version": 5, "version": "backup"}
        self._write_backup(backup)

        with self.assertLogs("app.session_store", level="WARNING") as captured:
            load_session_payload()

        messages = [record.getMessage() for record in captured.records]
        self.assertTrue(any("primary store unavailable or invalid" in message for message in messages))
        self.assertTrue(any("using backup store" in message for message in messages))

    def test_both_fail_emits_generic_warning(self) -> None:
        self._write_primary("{bad")

        with self.assertLogs("app.session_store", level="WARNING") as captured:
            loaded = load_session_payload()

        self.assertIsNone(loaded)
        self.assertTrue(
            any(
                "primary and backup stores unavailable or invalid" in record.getMessage()
                for record in captured.records
            )
        )

    def test_logs_exclude_sentinels_and_exception_text(self) -> None:
        self._write_primary(json.dumps({"api_key": "NINO_SESSION_PRIMARY_SECRET_54A1"}))
        self._write_backup({"schema_version": 5, "version": "backup"})

        with self.assertLogs("app.session_store", level="WARNING") as captured:
            load_session_payload()

        self._assert_no_log_sentinels(captured.records)
        self._assert_no_exception_text_in_logs(captured.records)

    def test_read_does_not_modify_files_on_backup_fallback(self) -> None:
        self._write_primary("{bad")
        self._write_backup({"schema_version": 5, "version": "backup"})
        before = _snapshot_files(self.appdata_dir)

        with self.assertLogs("app.session_store", level="WARNING"):
            loaded = load_session_payload()

        after = _snapshot_files(self.appdata_dir)
        self.assertEqual(loaded, {"schema_version": 5, "version": "backup"})
        self._assert_files_unchanged(before, after)
        self.assertFalse(any(name.endswith(".tmp") for name in before.keys()))

    def test_read_does_not_modify_files_on_valid_primary(self) -> None:
        payload = {"schema_version": 5, "version": "primary"}
        self._write_primary(json.dumps(payload))
        self._write_backup({"schema_version": 5, "version": "backup"})
        before = _snapshot_files(self.appdata_dir)

        loaded = load_session_payload()

        after = _snapshot_files(self.appdata_dir)
        self.assertEqual(loaded, payload)
        self._assert_files_unchanged(before, after)

    def test_read_does_not_modify_files_when_both_invalid(self) -> None:
        self._write_primary("{bad")
        self.bak_file.write_text("{also bad", encoding="utf-8")
        before = _snapshot_files(self.appdata_dir)

        with self.assertLogs("app.session_store", level="WARNING"):
            loaded = load_session_payload()

        after = _snapshot_files(self.appdata_dir)
        self.assertIsNone(loaded)
        self._assert_files_unchanged(before, after)

    def test_backup_not_copied_to_primary(self) -> None:
        self._write_primary("{bad")
        backup = {"schema_version": 5, "version": "backup"}
        self._write_backup(backup)

        with self.assertLogs("app.session_store", level="WARNING"):
            load_session_payload()

        self.assertEqual(self.session_file.read_text(encoding="utf-8"), "{bad")

    def test_load_none_accepted_by_callers(self) -> None:
        self._write_primary("{bad")

        try:
            loaded = load_session_payload()
        except Exception as exc:  # pragma: no cover - explicit guard
            self.fail(f"load_session_payload raised unexpectedly: {exc!r}")

        self.assertIsNone(loaded)


if __name__ == '__main__':
    unittest.main()
