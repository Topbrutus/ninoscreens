from __future__ import annotations

import os
from typing import Optional


def _read_proc_rss_bytes(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/statm", "r", encoding="utf-8") as handle:
            parts = handle.read().strip().split()
        if len(parts) < 2:
            return None
        rss_pages = int(parts[1])
        page_size = os.sysconf("SC_PAGE_SIZE")
        return rss_pages * page_size
    except (OSError, ValueError):
        return None


def _read_psutil_memory_bytes(pid: int) -> int | None:
    try:
        import psutil  # type: ignore
    except Except:
        return None

    try:
        process = psutil.Process(pid)
        return int(process.memory_info().rss)
    except Except:
        return None


def get_process_memory_mb( pid: int | None) -> Optional[int]:
    if pid is None or pid <= 0:
        return None

    memory_bytes = _read_psutil_memory_bytes(pid)
    if memory_bytes is None:
        memory_bytes = _read_proc_rss_bytes(pid)
    if memory_bytes is None:
        return None

    return max(0, int(round(memory_bytes / (1024 * 1024))))
