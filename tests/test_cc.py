import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from lol_build.core.cc import (
    CcAdjustmentError,
    CcAdjustmentStatus,
    CrowdControlApplication,
    DurationMultiplierWindow,
    ImmunityWindow,
    ResponseActivation,
    ResponseKind,
    adjust_for_crowd_control,
)
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, DamageOutput, EntityId


def _fact() -> dict:
    return {
        "id": "cc_blind_test_v1",
        "blocked_channels": ["BASIC_ATTACK"],
        "interactions": {
            "tenacity_reducible": {"status": "VERIFIED", "value": True},
            "cleanse_removable": {"status": "VERIFIED", "value": True},
            "qss_removable": {"status": "VERIFIED", "value": True},
            "immunity_resistible": {"status": "VERIFIED", "value": True},
            "slow_resistance_applies": {"status": "VERIFIED", "value": False},
        },
        "verification": {"status": "VERIFIED"},
    }


def _events() -> tuple[ActionEvent, ...]:
    output = (DamageOutput(EntityId.TARGET, Decimal(10), DamageType.PHYSICAL),)
    return (
        ActionEvent("attack_during", 2000, 2, EntityId.ACTOR, ActionChannel.BASIC_ATTACK, output),
        ActionEvent("ability_during", 2000, 3, EntityId.ACTOR, ActionChannel.ABILITY, output),
        ActionEvent("attack_after", 4500, 4, EntityId.ACTOR, ActionChannel.BASIC_ATTACK, output),
    )


def _application(at_ms: int = 1000) -> CrowdControlApplication:
    return CrowdControlApplication("blind_1", "cc_blind_test_v1", at_ms, 1, 3000, EntityId.ACTOR)


def test_only_the_blocked_action_channel_is_cancelled() -> None:
    result = adjust_for_crowd_control(
        duration_ms=8000,
        events=_events(),
        applications=(_application(),),
        mechanic_facts={"cc_blind_test_v1": _fact()},
    )

    assert result.status is CcAdjustmentStatus.KNOWN
    assert [event.cancelled for event in result.adjusted_events or ()] == [True, False, False]
    assert result.channel_uptime[ActionChannel.BASIC_ATTACK] == Decimal("0.625")
    assert result.channel_uptime[ActionChannel.ABILITY] == 1


def test_cleanse_removes_active_cc_and_later_duration_window_affects_future_cc() -> None:
    output = (DamageOutput(EntityId.TARGET, Decimal(10), DamageType.PHYSICAL),)
    events = (
        ActionEvent("before_cleanse", 1400, 5, EntityId.ACTOR, ActionChannel.BASIC_ATTACK, output),
        ActionEvent("after_cleanse", 1600, 7, EntityId.ACTOR, ActionChannel.BASIC_ATTACK, output),
        ActionEvent("future_during", 5200, 9, EntityId.ACTOR, ActionChannel.BASIC_ATTACK, output),
        ActionEvent("future_after", 6100, 10, EntityId.ACTOR, ActionChannel.BASIC_ATTACK, output),
    )
    result = adjust_for_crowd_control(
        duration_ms=8000,
        events=events,
        applications=(_application(), _application(at_ms=5000)),
        mechanic_facts={"cc_blind_test_v1": _fact()},
        responses=(ResponseActivation("cleanse_1", ResponseKind.CLEANSE, 1500, 6, EntityId.ACTOR),),
        duration_windows=(
            DurationMultiplierWindow(
                "cleanse_tenacity", 1500, 6500, EntityId.ACTOR, Decimal("0.25")
            ),
        ),
    )

    assert result.status is CcAdjustmentStatus.KNOWN
    assert [event.cancelled for event in result.adjusted_events or ()] == [True, False, True, False]
    observed_intervals = [
        (interval.start_ms, interval.end_ms, interval.ended_by)
        for interval in result.intervals or ()
    ]
    assert observed_intervals == [
        (1000, 1500, "cleanse_1"),
        (5000, 5750, None),
    ]


def test_immunity_prevents_verified_resistible_cc_application() -> None:
    result = adjust_for_crowd_control(
        duration_ms=8000,
        events=_events(),
        applications=(_application(),),
        mechanic_facts={"cc_blind_test_v1": _fact()},
        immunity_windows=(ImmunityWindow("immune", 500, 1500, EntityId.ACTOR),),
    )

    assert result.status is CcAdjustmentStatus.KNOWN
    assert result.intervals == ()
    assert all(not event.cancelled for event in result.adjusted_events or ())


def test_unverified_fact_returns_unknown_without_events_or_score() -> None:
    fact = deepcopy(_fact())
    fact["verification"] = {"status": "UNVERIFIED"}
    fact["interactions"]["tenacity_reducible"] = {"status": "UNVERIFIED", "value": None}

    result = adjust_for_crowd_control(
        duration_ms=8000,
        events=_events(),
        applications=(_application(),),
        mechanic_facts={"cc_blind_test_v1": fact},
    )

    assert result.status is CcAdjustmentStatus.UNKNOWN
    assert result.adjusted_events is None
    assert result.channel_uptime is None
    assert "not VERIFIED" in result.reason


def test_locked_blind_record_cannot_generate_uptime() -> None:
    repository = Path(__file__).resolve().parents[1]
    fact = json.loads((repository / "data/curated/mechanics/blind.json").read_text())

    result = adjust_for_crowd_control(
        duration_ms=8000,
        events=_events(),
        applications=(
            CrowdControlApplication("blind_1", "cc_blind_v1", 1000, 1, 3000, EntityId.ACTOR),
        ),
        mechanic_facts={"cc_blind_v1": fact},
    )

    assert result.status is CcAdjustmentStatus.UNKNOWN
    assert result.adjusted_events is None
    assert result.channel_uptime is None


def test_overlapping_duration_multipliers_are_not_silently_stacked() -> None:
    windows = (
        DurationMultiplierWindow("one", 0, 3000, EntityId.ACTOR, Decimal("0.7")),
        DurationMultiplierWindow("two", 0, 3000, EntityId.ACTOR, Decimal("0.8")),
    )
    with pytest.raises(CcAdjustmentError, match="verified stacking rule"):
        adjust_for_crowd_control(
            duration_ms=8000,
            events=_events(),
            applications=(_application(),),
            mechanic_facts={"cc_blind_test_v1": _fact()},
            duration_windows=windows,
        )
