from __future__ import annotations

import unittest

from app.config import TILE_COUNT
from app.session_store import serialize_app_state
from app.state import (
    AppState,
    derive_slot_to_tile_id,
    derive_slot_to_tile_id_from_tile_positions,
    derive_tile_id_to_slot,
    normalize_slot_to_tile_id,
    swap_slot_order,
)


class StateLayoutTests(unittest.TestCase):
    def test_swap_slot_order_swaps_tile_positions(self) -> None:
        order = list(range(TILE_COUNT))

        swapped = swap_slot_order(order, 2, 5)

        self.assertEqual(swapped[2], 5)
        self.assertEqual(swapped[5], 2)
        self.assertEqual(swapped[0], 0)

    def test_slot_and_tile_mappings_round_trip(self) -> None:
        order = list(range(TILE_COUNT))
        for first, second in ((1, 4), (8, 9), (0, 7), (3, 5)):
            order = swap_slot_order(order, first, second)

        tile_to_slot = derive_tile_id_to_slot(order)
        self.assertEqual(derive_slot_to_tile_id(tile_to_slot), order)

    def test_legacy_tile_positions_migrates_with_partial_invalid_entries(self) -> None:
        legacy_positions = [0, 2, 2, 99, 4, "oops", 1] + list(range(7, TILE_COUNT))
        migrated = derive_slot_to_tile_id_from_tile_positions(legacy_positions)

        self.assertEqual(len(migrated), TILE_COUNT)
        self.assertEqual(sorted(migrated), list(range(TILE_COUNT)))
        self.assertEqual(migrated[0], 0)
        self.assertEqual(migrated[2], 1)
        self.assertEqual(migrated[4], 4)
        self.assertEqual(migrated[1], 6)

    def test_normalize_invalid_order_falls_back_to_identity(self) -> None:
        self.assertEqual(
            normalize_slot_to_tile_id([0, 0] + list(range(2, TILE_COUNT))),
            list(range(TILE_COUNT)),
        )

    def test_session_payload_persists_layout_mappings(self) -> None:
        app_state = AppState()
        app_state.slot_to_tile_id[0], app_state.slot_to_tile_id[3] = app_state.slot_to_tile_id[3], app_state.slot_to_tile_id[0]
        app_state.slot_to_tile_id[10], app_state.slot_to_tile_id[11] = app_state.slot_to_tile_id[11], app_state.slot_to_tile_id[10]

        payload = serialize_app_state(app_state)

        self.assertEqual(payload["schema_version"], 5)
        self.assertEqual(payload["slot_to_tile_id"], app_state.slot_to_tile_id)
        self.assertEqual(payload["tile_id_to_slot"], derive_tile_id_to_slot(app_state.slot_to_tile_id))

    def test_legacy_tile_positions_round_trip_through_inverse(self) -> None:
        legacy_positions = [0, 3, 6, 9, 12, 15] + list(range(6, TILE_COUNT))
        migrated = derive_slot_to_tile_id_from_tile_positions(legacy_positions)

        self.assertEqual(derive_slot_to_tile_id(derive_tile_id_to_slot(migrated)), migrated)


if __name__ == "__main__":
    unittest.main()
