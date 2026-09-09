"""Regression tests for temporary, event-sourced attack-cadence modifiers."""

from pathlib import Path

from lol_build.application.matchup import (
    MatchupEngine,
    MatchupEvaluation,
    MatchupRequest,
)
from lol_build.core.timeline import ActionChannel

ROOT = Path(__file__).resolve().parents[1]


def _event_times(result: MatchupEvaluation, prefix: str) -> tuple[int, ...]:
    """Extract applied or cancelled basic-attack timestamps by stable ID prefix.

    :param result: Matchup evaluation exposing a timeline log.
    :param prefix: Event identifier prefix owned by the champion under test.
    :return: Chronological timestamps of matching basic-attack actions.
    """
    return tuple(
        entry.at_ms
        for entry in result.timeline.log
        if entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.event_id.startswith(prefix)
    )


def test_malphite_e_slows_attack_clock_then_restores_original_cadence() -> None:
    """Delay Darius attacks during E and restore his original interval afterward."""
    engine = MatchupEngine(ROOT)
    result = engine.evaluate(MatchupRequest("Darius", "Malphite"))

    attacks = _event_times(result, "DARIUS_ATTACK_")

    assert attacks == (200, 1642, 3968, 6026, 7468)
    assert attacks[-1] - attacks[-2] == 1442
    assert "MALPHITE_E_ATTACK_SPEED_REDUCTION_SCHEDULE_NOT_REBUILT" not in result.blockers


def test_malphite_e_does_not_reschedule_ability_channel() -> None:
    """Keep Darius spell timestamps fixed while his basic-attack clock is slowed."""
    engine = MatchupEngine(ROOT)
    result = engine.evaluate(MatchupRequest("Darius", "Malphite"))

    ability_times = {
        entry.event_id: entry.at_ms
        for entry in result.timeline.log
        if entry.action_channel is ActionChannel.ABILITY
        and entry.event_id.startswith("DARIUS_")
    }

    assert ability_times["DARIUS_Q_3"] == 1700
    assert ability_times["DARIUS_R_4"] == 3000


def test_cancelled_malphite_e_does_not_slow_attacks() -> None:
    """Remove the cadence window when an opposing control effect cancels E."""
    engine = MatchupEngine(ROOT)
    result = engine.evaluate(MatchupRequest("Jax", "Malphite"))

    attacks = _event_times(result, "JAX_GENERIC_ATTACK_")

    assert 2484 in attacks
    assert 2768 not in attacks
    assert any(
        entry.event_id == "MALPHITE_E_GROUND_SLAM" and entry.status == "CANCELLED"
        for entry in result.timeline.log
    )


def test_attack_speed_reduction_is_role_symmetric_and_deterministic() -> None:
    """Attach Malphite's cadence effect to him across role reversal and reruns."""
    engine = MatchupEngine(ROOT)
    actor_first = engine.evaluate(MatchupRequest("Malphite", "Darius"))
    actor_second = engine.evaluate(MatchupRequest("Malphite", "Darius"))
    opponent = engine.evaluate(MatchupRequest("Darius", "Malphite"))

    assert actor_first == actor_second
    assert _event_times(actor_first, "DARIUS_ATTACK_") == _event_times(
        opponent, "DARIUS_ATTACK_"
    )
