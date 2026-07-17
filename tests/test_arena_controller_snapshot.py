from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.arena_controller import ArenaController  # noqa: E402


class ArenaControllerSnapshotTests(unittest.TestCase):
    def test_request_snapshot_refresh_coalesces_inflight_worker(self) -> None:
        controller = ArenaController()

        with patch.object(controller._snapshot_thread_pool, "start") as start_mock:
            self.assertTrue(controller.request_snapshot_refresh(force=True))
            self.assertFalse(controller.request_snapshot_refresh())

        start_mock.assert_called_once()
        self.assertTrue(controller.snapshot_refresh_in_progress())
        controller._finish_snapshot_refresh(snapshot={"arena_state": "ARENA_READY"})
        self.assertFalse(controller.snapshot_refresh_in_progress())

    def test_finish_snapshot_refresh_keeps_last_valid_snapshot_on_error(self) -> None:
        controller = ArenaController()
        controller._snapshot_cache = {"arena_state": "ARENA_READY"}
        controller._snapshot_cache_timestamp = 1.0

        controller._finish_snapshot_refresh(error="boom")

        self.assertEqual(controller.cached_snapshot(), {"arena_state": "ARENA_READY"})
        self.assertEqual(controller.snapshot_last_error(), "boom")


if __name__ == "__main__":
    unittest.main()
