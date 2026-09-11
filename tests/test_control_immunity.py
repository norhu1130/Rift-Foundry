"""Regression tests for discrete, role-symmetric control immunity."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import (
    MatchupEngine,
    MatchupRequest,
    _active_cast_windows,
    _active_control_immunities,
    _strip_immune_control_outputs,
)
from lol_build.cogs.base import CastBlockWindow, ControlImmunityWindow, ControlType
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    DamageOutput,
    EntityId,
    StatusOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def _event(
    event_id: str,
    *,
    at_ms: int = 0,
    cancelled: bool = False,
) -> ActionEvent:
    """Build one minimal source event for causal-window tests.

    :param event_id: Stable event identifier referenced by a reaction window.
    :param at_ms: Event timestamp in milliseconds.
    :param cancelled: Whether an opponent control already prevented the event.
    :return: Valid action event containing a harmless damage output.
    """
    return ActionEvent(
        event_id,
        at_ms,
        0,
        EntityId.ACTOR,
        ActionChannel.ABILITY,
        (DamageOutput(EntityId.TARGET, Decimal(0), DamageType.TRUE),),
        cancelled=cancelled,
        cancellation_reason="TEST_CANCELLED" if cancelled else None,
    )


def test_selective_immunity_distinguishes_blind_stun_and_slow() -> None:
    """Filter only named controls while leaving unrelated control windows active."""
    source_events = (_event("blind"), _event("stun"), _event("slow"))
    windows = (
        CastBlockWindow(
            "blind_window",
            100,
            1100,
            (ActionChannel.BASIC_ATTACK,),
            "blind",
            True,
            ControlType.BLIND,
        ),
        CastBlockWindow(
            "stun_window",
            100,
            1100,
            (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY),
            "stun",
            True,
            ControlType.STUN,
        ),
        CastBlockWindow(
            "slow_window",
            100,
            1100,
            (ActionChannel.MOVEMENT,),
            "slow",
            True,
            ControlType.SLOW,
        ),
    )
    immunity = ControlImmunityWindow(
        "blind_only",
        0,
        1000,
        EntityId.TARGET,
        (ControlType.BLIND,),
    )

    active = _active_cast_windows(windows, source_events, Decimal(0), (immunity,))

    assert [window.control_type for window in active] == [ControlType.STUN, ControlType.SLOW]


def test_immunity_is_discrete_while_tenacity_only_shortens_duration() -> None:
    """Keep immunity removal categorically separate from tenacity duration scaling."""
    source = (_event("stun"),)
    stun = CastBlockWindow(
        "stun_window",
        100,
        1100,
        (ActionChannel.ABILITY,),
        "stun",
        True,
        ControlType.STUN,
    )
    immunity = ControlImmunityWindow(
        "all_control",
        0,
        1000,
        EntityId.TARGET,
        (ControlType.ALL,),
    )

    tenacious = _active_cast_windows((stun,), source, Decimal("0.30"))
    immune = _active_cast_windows((stun,), source, Decimal("0.30"), (immunity,))

    assert tenacious[0].end_ms - tenacious[0].start_ms == 700
    assert immune == ()


def test_cancelled_enabling_cast_removes_immunity_window() -> None:
    """Preserve fixed-point causality when the immunity-enabling action is absent."""
    immunity = ControlImmunityWindow(
        "r_immunity",
        0,
        8000,
        EntityId.ACTOR,
        (ControlType.ALL,),
        "R_CAST",
    )

    assert _active_control_immunities((immunity,), (_event("R_CAST"),)) == (immunity,)
    assert (
        _active_control_immunities(
            (immunity,),
            (_event("R_CAST", cancelled=True),),
        )
        == ()
    )


def test_control_output_is_removed_without_removing_sibling_damage() -> None:
    """Keep mixed spell damage when its attached control cannot affect the recipient."""
    spell = ActionEvent(
        "MIXED_DAMAGE_AND_BLIND",
        500,
        1,
        EntityId.TARGET,
        ActionChannel.ABILITY,
        (
            DamageOutput(EntityId.ACTOR, Decimal(100), DamageType.MAGIC),
            StatusOutput(EntityId.ACTOR, "CC_BLIND", 1000),
        ),
    )
    immunity = ControlImmunityWindow(
        "all_control",
        0,
        1000,
        EntityId.ACTOR,
        (ControlType.ALL,),
    )

    adjusted = _strip_immune_control_outputs((spell,), (immunity,))

    assert len(adjusted) == 1
    assert adjusted[0].outputs == (spell.outputs[0],)


def test_olaf_r_prevents_teemo_blind_in_both_matchup_roles() -> None:
    """Apply Ragnarok immunity to Olaf without changing Teemo Q damage ownership."""
    engine = MatchupEngine(ROOT)
    olaf_actor = engine.evaluate(MatchupRequest("Olaf", "Teemo"))
    olaf_target = engine.evaluate(MatchupRequest("Teemo", "Olaf"))

    for result in (olaf_actor, olaf_target):
        assert not any(
            entry.event_id.startswith("OLAF_BASIC_ATTACK_") and entry.status == "CANCELLED"
            for entry in result.timeline.log
        )
        assert any(
            entry.event_id == "TEEMO_Q_BLINDING_DART"
            and entry.operation == "DAMAGE"
            and entry.status == "APPLIED"
            for entry in result.timeline.log
        )
        assert "OLAF_R_CC_IMMUNITY_NOT_ENFORCED_BY_CAST_BLOCK_MODEL" not in result.blockers

    assert olaf_actor.actor_hp_lost == olaf_target.opponent_hp_lost
    assert olaf_actor.opponent_hp_lost == olaf_target.actor_hp_lost
