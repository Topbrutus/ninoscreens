from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

ENV_RUN_PROJECT_ROOT = "NINOSCREEN_RUN_PROJECT_ROOT"
DEFAULT_RUN_PROJECT_ROOT = Path("/home/gaby/MonDeuxiemeProjet")


def run_project_root(env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    raw_value = str(source.get(ENV_RUN_PROJECT_ROOT, "") or "").strip()
    if not raw_value:
        return DEFAULT_RUN_PROJECT_ROOT
    return Path(raw_value).expanduser()
