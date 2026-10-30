from app.brutus_rarity_watch import EXPECTED_TIERS, analyze_brutus_status


def good_payload():
    return {
        "state": "PAUSED",
        "hierarchical_rarity": {
            "mode": "PAPILLON_FROZEN_RARITY_POWER10_V1",
            "selection_order": "COMMON_TO_RARE",
            "execution_order": "RARE_TO_COMMON",
            "no_mid_cycle_movement": True,
            "snapshot_generation": 7,
            "selection_count": 42,
            "rarity_suppressed": 0,
            "tiers": [
                {"class": "COMMON" if p == 0 else f"R{p}", "power": p, "multiplier": m}
                for p, m in EXPECTED_TIERS.items()
            ],
        },
        "brutomagique": {"pi_reader": {"snapshot_pending_refresh": False}},
    }


def test_valid_frozen_power10_policy_is_green():
    health = analyze_brutus_status(good_payload())
    assert health.online is True
    assert health.ok is True
    assert health.runtime_state == "PAUSED"
    assert health.snapshot_generation == 7
    assert health.selection_count == 42
    assert health.violations == ()


def test_mid_cycle_movement_guard_failure_is_alert():
    payload = good_payload()
    payload["hierarchical_rarity"]["no_mid_cycle_movement"] = False
    health = analyze_brutus_status(payload)
    assert health.ok is False
    assert "no_mid_cycle_movement" in health.message


def test_equal_policy_but_pending_refresh_stays_locked():
    payload = good_payload()
    payload["brutomagique"]["pi_reader"]["snapshot_pending_refresh"] = True
    health = analyze_brutus_status(payload)
    assert health.ok is True
    assert health.pending_refresh is True
    assert "refresh pending" in health.message


def test_wrong_power_tier_is_alert():
    payload = good_payload()
    payload["hierarchical_rarity"]["tiers"][10]["multiplier"] = 999
    health = analyze_brutus_status(payload)
    assert health.ok is False
    assert "tiers_power10_invalid" in health.violations
