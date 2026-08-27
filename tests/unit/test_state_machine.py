from __future__ import annotations

from itertools import pairwise

import pytest
from most_sprite.control.state_machine import ALLOWED_TRANSITIONS, assert_transition
from most_sprite.domain.enums import InstrumentState
from most_sprite.errors import SpriteError


def test_documented_happy_path_is_accepted() -> None:
    path = [
        InstrumentState.OFFLINE,
        InstrumentState.INITIALIZING,
        InstrumentState.STANDBY,
        InstrumentState.PREPARING,
        InstrumentState.READY,
        InstrumentState.EXPOSING,
        InstrumentState.READING,
        InstrumentState.STANDBY,
    ]
    for current, target in pairwise(path):
        assert_transition(current, target)


def test_exposing_cannot_jump_to_offline() -> None:
    with pytest.raises(SpriteError, match="cannot transition"):
        assert_transition(InstrumentState.EXPOSING, InstrumentState.OFFLINE)


def test_every_non_fault_state_has_a_safe_route() -> None:
    for state, targets in ALLOWED_TRANSITIONS.items():
        if state not in {InstrumentState.OFFLINE, InstrumentState.STANDBY}:
            assert targets or state == InstrumentState.SAFE_FAULT
