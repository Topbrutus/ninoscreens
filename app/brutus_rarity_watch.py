from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

EXPECTED_POLICY_MODE = "PAPILLON_FROZEN_RARITY_POWER10_V1"
EXPECTED_SELECTION_ORDER = "COMMON_TO_RARE"
EXPECTED_EXECUTION_ORDER = "RARE_TO_COMMON"
EXPECTED_TIERS = {power: 10**power for power in range(0, 11)}


@dataclass(frozen=True, slots=True)
class BrutusRarityHealth:
    online: bool
    ok: bool
    severity: str
    message: str
    runtime_state: str = "UNKNOWN"
    snapshot_generation: int = 0
    selection_count: int = 0
    pending_refresh: bool = False
    violations: tuple[str, ...] = ()
    status_url: str = ""


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def analyze_brutus_status(payload: Mapping[str, Any], *, status_url: str = "") -> BrutusRarityHealth:
    rarity = _mapping(payload.get("hierarchical_rarity"))
    reader = _mapping(_mapping(payload.get("brutomagique")).get("pi_reader"))
    violations: list[str] = []

    if not rarity:
        violations.append("hierarchical_rarity absent")
    else:
        if rarity.get("mode") != EXPECTED_POLICY_MODE:
            violations.append(f"mode={rarity.get('mode')!r}")
        if rarity.get("selection_order") != EXPECTED_SELECTION_ORDER:
            violations.append(f"selection_order={rarity.get('selection_order')!r}")
        if rarity.get("execution_order") != EXPECTED_EXECUTION_ORDER:
            violations.append(f"execution_order={rarity.get('execution_order')!r}")
        if rarity.get("no_mid_cycle_movement") is not True:
            violations.append("no_mid_cycle_movement!=true")

        tiers = rarity.get("tiers")
        observed: dict[int, int] = {}
        if isinstance(tiers, list):
            for item in tiers:
                if not isinstance(item, Mapping):
                    continue
                power = _as_int(item.get("power"), -1)
                multiplier = _as_int(item.get("multiplier"), -1)
                if power >= 0:
                    observed[power] = multiplier
        if observed != EXPECTED_TIERS:
            violations.append("tiers_power10_invalid")

        if _as_int(rarity.get("rarity_suppressed"), 0) != 0:
            violations.append("rarity_suppressed_nonzero")

    pending_refresh = bool(
        rarity.get("snapshot_pending_refresh", reader.get("snapshot_pending_refresh", False))
    )
    runtime_state = str(payload.get("state", "UNKNOWN") or "UNKNOWN")
    generation = _as_int(rarity.get("snapshot_generation"), _as_int(reader.get("snapshot_generation"), 0))
    selection_count = _as_int(rarity.get("selection_count"), 0)

    if violations:
        return BrutusRarityHealth(
            online=True,
            ok=False,
            severity="alert",
            message="RARITY LOCK ALERT: " + "; ".join(violations),
            runtime_state=runtime_state,
            snapshot_generation=generation,
            selection_count=selection_count,
            pending_refresh=pending_refresh,
            violations=tuple(violations),
            status_url=status_url,
        )

    suffix = " / refresh pending" if pending_refresh else ""
    return BrutusRarityHealth(
        online=True,
        ok=True,
        severity="ok",
        message=f"RARITY LOCK OK{suffix}",
        runtime_state=runtime_state,
        snapshot_generation=generation,
        selection_count=selection_count,
        pending_refresh=pending_refresh,
        status_url=status_url,
    )


def fetch_brutus_status(status_url: str, *, timeout_seconds: float = 1.0) -> BrutusRarityHealth:
    request = Request(
        status_url,
        headers={"Accept": "application/json", "User-Agent": "ninoscreens/brutus-rarity-watch"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=max(0.1, float(timeout_seconds))) as response:
            body = response.read(2_000_000)
            status = getattr(response, "status", None) or response.getcode()
        if not (200 <= int(status) < 300):
            raise RuntimeError(f"HTTP {status}")
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("JSON root is not an object")
        return analyze_brutus_status(payload, status_url=status_url)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        return BrutusRarityHealth(
            online=False,
            ok=False,
            severity="offline",
            message=f"BRUTUS OFFLINE: {type(exc).__name__}: {exc}",
            status_url=status_url,
        )
