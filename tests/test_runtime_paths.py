from __future__ import annotations

from pathlib import Path
import unittest

from app.runtime_paths import DEFAULT_RUN_PROJECT_ROOT, run_project_root


class RunProjectRootTest(unittest.TestCase):
    def test_uses_legacy_path_when_override_is_missing(self) -> None:
        self.assertEqual(run_project_root({}), DEFAULT_RUN_PROJECT_ROOT)

    def test_uses_legacy_path_when_override_is_blank(self) -> None:
        self.assertEqual(run_project_root({"NINOSCREEN_RUN_PROJECT_ROOT": "   "}), DEFAULT_RUN_PROJECT_ROOT)

    def test_uses_environment_override_for_vps_runtime(self) -> None:
        self.assertEqual(
            run_project_root({"NINOSCREEN_RUN_PROJECT_ROOT": "/home/rob/chateau-astra/run-backend"}),
            Path("/home/rob/chateau-astra/run-backend"),
        )


if __name__ == "__main__":
    unittest.main()
