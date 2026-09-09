"""Tests for timeline death-prevention windows and Tryndamere's ultimate."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    Combatant,
    DamageOutput,
    DeathPreventionOutput,
    EntityId,
    ExecuteOutput,
    simulate_timeline,
)

ROOT = Path(__file__).resolve().parents[1]


def _combatant(entity: EntityId) -> Combatant:
    """Create a resistance-free combatant for death-floor tests.

    :param entity: Timeline role assigned to the combatant.
    :return: Combatant with one hundred health and no mitigation.
    """
    return Combatant(entity, Decimal(100), Decimal(100), Decimal(0), Decimal(0))


def test_death_prevention_clamps_all_damage_types_until_exact_expiry() -> None:
    """Apply the floor to physical, magic, and true damage, then allow death."""
    events = (
        ActionEvent(
            "undying",
            0,
            0,
            EntityId.TARGET,
            ActionChannel.ABILITY,
            (DeathPreventionOutput(EntityId.TARGET, Decimal(10), 5000, "undying"),),
            requires_living_opponent=False,
        ),
        ActionEvent(
            "physical",
            1000,
            1,
            EntityId.ACTOR,
            ActionChannel.ABILITY,
            (DamageOutput(EntityId.TARGET, Decimal(50), DamageType.PHYSICAL),),
        ),
        ActionEvent(
            "magic",
            2000,
            2,
            EntityId.ACTOR,
            ActionChannel.ABILITY,
            (DamageOutput(EntityId.TARGET, Decimal(50), DamageType.MAGIC),),
        ),
        ActionEvent(
            "true",
            3000,
            3,
            EntityId.ACTOR,
            ActionChannel.ABILITY,
            (DamageOutput(EntityId.TARGET, Decimal(50), DamageType.TRUE),),
        ),
        ActionEvent(
            "at-expiry",
            5000,
            4,
            EntityId.ACTOR,
            ActionChannel.ABILITY,
            (DamageOutput(EntityId.TARGET, Decimal(10), DamageType.TRUE),),
        ),
    )

    result = simulate_timeline(
        duration_ms=5000,
        horizon_ms=3000,
        actor=_combatant(EntityId.ACTOR),
        target=_combatant(EntityId.TARGET),
        events=events,
    )

    assert result.target_at_horizon.current_hp == Decimal(10)
    assert result.target_at_horizon.shield == Decimal(0)
    assert result.target_at_horizon.dead is False
    assert result.target_at_end.current_hp == Decimal(0)
    assert result.target_at_end.dead is True
    assert result.damage_to_target_first_horizon == Decimal(150)
    assert result.damage_to_target_total == Decimal(160)
    true_hit = next(entry for entry in result.log if entry.event_id == "true")
    assert true_hit.hp_delta == Decimal(0)
    assert true_hit.detail == "death_prevention_absorbed:50"
    prevention = next(entry for entry in result.log if entry.event_id == "undying")
    assert prevention.operation == "DEATH_PREVENTION"
    assert prevention.hp_delta == Decimal(0)


def test_death_prevention_stops_execute_without_healing_to_the_floor() -> None:
    """Clamp an execute at current low health without treating the floor as healing."""
    target = Combatant(
        EntityId.TARGET,
        Decimal(100),
        Decimal(20),
        Decimal(0),
        Decimal(0),
    )
    events = (
        ActionEvent(
            "undying",
            0,
            0,
            EntityId.TARGET,
            ActionChannel.ABILITY,
            (DeathPreventionOutput(EntityId.TARGET, Decimal(50), 1000, "undying"),),
            requires_living_opponent=False,
        ),
        ActionEvent(
            "execute",
            100,
            1,
            EntityId.ACTOR,
            ActionChannel.PASSIVE,
            (ExecuteOutput(EntityId.TARGET, Decimal("0.25")),),
        ),
    )

    result = simulate_timeline(
        duration_ms=1000,
        horizon_ms=100,
        actor=_combatant(EntityId.ACTOR),
        target=target,
        events=events,
    )

    assert result.target_at_horizon.current_hp == Decimal(20)
    assert result.target_at_horizon.dead is False
    execute = next(entry for entry in result.log if entry.event_id == "execute")
    assert execute.hp_delta == Decimal(0)
    assert execute.detail == "death_prevention_absorbed:20"


def test_tryndamere_floor_is_deterministic_across_role_reversal() -> None:
    """Keep Tryndamere's R behavior attached to him in either participant role."""
    engine = MatchupEngine(ROOT)

    actor_first = engine.evaluate(MatchupRequest("Tryndamere", "Garen"))
    actor_second = engine.evaluate(MatchupRequest("Tryndamere", "Garen"))
    opponent = engine.evaluate(MatchupRequest("Garen", "Tryndamere"))

    assert actor_first.timeline == actor_second.timeline
    assert (
        actor_first.timeline.actor_at_end.current_hp
        == opponent.timeline.target_at_end.current_hp
    )
    assert actor_first.actor_hp_lost == opponent.opponent_hp_lost
    assert actor_first.actor_action_model == opponent.opponent_action_model
    assert "TRYNDAMERE_R_DEATH_FLOOR_NOT_ENFORCED_BY_TIMELINE" not in actor_first.blockers
    assert "TRYNDAMERE_R_DEATH_FLOOR_NOT_ENFORCED_BY_TIMELINE" not in opponent.blockers
