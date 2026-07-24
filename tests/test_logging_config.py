from __future__ import annotations

import logging
import sys
import tempfile
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch

from app.config import (
    LOG_BACKUP_COUNT,
    LOG_FILENAME,
    LOG_MAX_BYTES,
    configure_logging,
)


def _managed_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [
        handler
        for handler in logger.handlers
        if getattr(handler, "_ninoscreens_managed_handler", False)
    ]


class LoggingConfigTests(unittest.TestCase):
    def _reset_logger(self, logger: logging.Logger) -> None:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        logger.setLevel(logging.NOTSET)

    def tearDown(self) -> None:
        for logger_name in (
            "tests.logging.create",
            "tests.logging.idempotent",
            "tests.logging.fallback",
            "tests.logging.external",
        ):
            self._reset_logger(logging.getLogger(logger_name))

    def test_creates_rotating_log_file_with_expected_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = logging.getLogger("tests.logging.create")
            try:
                log_path = configure_logging(Path(tmpdir), logger_name=logger.name)

                self.assertEqual(log_path, Path(tmpdir) / LOG_FILENAME)
                self.assertTrue(log_path.exists())

                handlers = _managed_handlers(logger)
                self.assertEqual(len(handlers), 1)
                handler = handlers[0]
                self.assertIsInstance(handler, RotatingFileHandler)
                self.assertEqual(handler.maxBytes, LOG_MAX_BYTES)
                self.assertEqual(handler.backupCount, LOG_BACKUP_COUNT)

                raw_secret = "RAW_SECRET_VALUE_FOR_TEST"
                logger.info("Credential check uses %s", "<redacted>")
                for active_handler in handlers:
                    active_handler.flush()

                log_text = log_path.read_text(encoding="utf-8")
                self.assertIn("<redacted>", log_text)
                self.assertNotIn(raw_secret, log_text)
            finally:
                self._reset_logger(logger)

    def test_repeated_initialization_does_not_duplicate_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = logging.getLogger("tests.logging.idempotent")
            try:
                first_path = configure_logging(Path(tmpdir), logger_name=logger.name)
                second_path = configure_logging(Path(tmpdir), logger_name=logger.name)

                self.assertEqual(first_path, second_path)
                self.assertEqual(len(_managed_handlers(logger)), 1)
            finally:
                self._reset_logger(logger)

    def test_falls_back_to_stderr_when_file_handler_creation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = logging.getLogger("tests.logging.fallback")
            try:
                with patch("app.config.RotatingFileHandler", side_effect=OSError("denied")):
                    log_path = configure_logging(Path(tmpdir), logger_name=logger.name)

                self.assertIsNone(log_path)
                handlers = _managed_handlers(logger)
                self.assertEqual(len(handlers), 1)
                self.assertIsInstance(handlers[0], logging.StreamHandler)
                self.assertIs(handlers[0].stream, sys.stderr)
            finally:
                self._reset_logger(logger)

    def test_external_handlers_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = logging.getLogger("tests.logging.external")
            external_handler = logging.StreamHandler()
            logger.addHandler(external_handler)
            try:
                configure_logging(Path(tmpdir), logger_name=logger.name)

                self.assertIn(external_handler, logger.handlers)
                self.assertEqual(len(_managed_handlers(logger)), 1)
            finally:
                self._reset_logger(logger)


if __name__ == "__main__":
    unittest.main()
