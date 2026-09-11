"""Regression tests for healing, vamp, regeneration, and healing reduction."""

from decimal import Decimal

from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    Combatant,
    DamageOutput,
    EntityId,
    HealOutput,
    MissingHealthHealOutput,
    StatusOutput,
    simulate_timeline,
)


def _combatant(
    entity: EntityId,
    *,
    current_hp: str = "1000",
    life_steal: str = "0",
    omnivamp: str = "0",
    regen: str = "0",
) -> Combatant:
    return Combatant(
        entity,
        max_hp=Decimal(1000),
        current_hp=Decimal(current_hp),
        armor=Decimal(0),
        magic_resistance=Decimal(0),
        life_steal=Decimal(life_steal),
        omnivamp=Decimal(omnivamp),
        health_regen_per_second=Decimal(regen),
    )


def _hit(event_id: str, at_ms: int, sequence: int, channel: ActionChannel) -> ActionEvent:
    return ActionEvent(
        event_id,
        at_ms,
        sequence,
        EntityId.ACTOR,
        channel,
        (DamageOutput(EntityId.TARGET, Decimal(100), DamageType.PHYSICAL),),
    )


def _grievous(at_ms: int, sequence: int, magnitude: str, source: EntityId) -> ActionEvent:
    recipient = EntityId.ACTOR if source is EntityId.TARGET else EntityId.TARGET
    return ActionEvent(
        f"grievous_{sequence}",
        at_ms,
        sequence,
        source,
        ActionChannel.ABILITY,
        (StatusOutput(recipient, "HEALING_REDUCTION", 3000, Decimal(magnitude)),),
    )


def test_life_steal_heals_from_basic_attacks_but_not_abilities() -> None:
    result = simulate_timeline(
        duration_ms=1000,
        horizon_ms=1000,
        actor=_combatant(EntityId.ACTOR, current_hp="500", life_steal="0.10"),
        target=_combatant(EntityId.TARGET),
        events=(
            _hit("attack", 100, 1, ActionChannel.BASIC_ATTACK),
            _hit("spell", 200, 2, ActionChannel.ABILITY),
        ),
    )

    assert result.actor_at_end.current_hp == Decimal(510)
    assert result.healing_by_entity[EntityId.ACTOR] == Decimal(10)


def test_omnivamp_heals_from_every_damage_channel() -> None:
    result = simulate_timeline(
        duration_ms=1000,
        horizon_ms=1000,
        actor=_combatant(EntityId.ACTOR, current_hp="500", omnivamp="0.10"),
        target=_combatant(EntityId.TARGET),
        events=(
            _hit("attack", 100, 1, ActionChannel.BASIC_ATTACK),
            _hit("spell", 200, 2, ActionChannel.ABILITY),
        ),
    )

    assert result.actor_at_end.current_hp == Decimal(520)


def test_healing_reduction_cuts_vamp_and_is_attributed_to_its_source() -> None:
    result = simulate_timeline(
        duration_ms=1000,
        horizon_ms=1000,
        actor=_combatant(EntityId.ACTOR, current_hp="500", life_steal="0.10"),
        target=_combatant(EntityId.TARGET),
        events=(
            _grievous(50, 1, "0.40", EntityId.TARGET),
            _hit("attack", 100, 2, ActionChannel.BASIC_ATTACK),
        ),
    )

    assert result.actor_at_end.current_hp == Decimal(506)
    assert result.healing_prevented_by_entity[EntityId.ACTOR] == Decimal(4)
    assert result.healing_prevented_by_source[EntityId.TARGET] == Decimal(4)
    assert result.actor_healing_prevented == Decimal(0)


def test_grievous_wounds_does_not_stack_and_keeps_the_stronger_source() -> None:
    result = simulate_timeline(
        duration_ms=2000,
        horizon_ms=2000,
        actor=_combatant(EntityId.ACTOR),
        target=_combatant(EntityId.TARGET, current_hp="500"),
        events=(
            _grievous(100, 1, "0.40", EntityId.ACTOR),
            _grievous(200, 2, "0.25", EntityId.ACTOR),
            ActionEvent(
                "heal",
                300,
                3,
                EntityId.TARGET,
                ActionChannel.ABILITY,
                (HealOutput(EntityId.TARGET, Decimal(100)),),
            ),
        ),
    )

    assert result.target_at_end.current_hp == Decimal(560)
    assert result.actor_healing_prevented == Decimal(40)
    assert result.opposing_side_healing == Decimal(60)


def test_regeneration_accrues_continuously_and_respects_reduction_and_death() -> None:
    result = simulate_timeline(
        duration_ms=4000,
        horizon_ms=4000,
        actor=_combatant(EntityId.ACTOR, current_hp="500", regen="10"),
        target=_combatant(EntityId.TARGET, current_hp="500", regen="10"),
        events=(
            _grievous(1000, 1, "0.50", EntityId.TARGET),
            ActionEvent(
                "kill_target",
                2000,
                2,
                EntityId.ACTOR,
                ActionChannel.ABILITY,
                (DamageOutput(EntityId.TARGET, Decimal(10_000), DamageType.TRUE),),
                requires_living_opponent=False,
            ),
        ),
    )

    # Actor: 1s at full rate, then 3s reduced by 50% while the status lasts.
    assert result.actor_at_end.current_hp == Decimal(525)
    assert result.target_at_end.dead
    assert result.healing_by_entity[EntityId.TARGET] == Decimal(20)


def test_regeneration_is_capped_at_maximum_health() -> None:
    result = simulate_timeline(
        duration_ms=10_000,
        horizon_ms=10_000,
        actor=_combatant(EntityId.ACTOR, current_hp="995", regen="10"),
        target=_combatant(EntityId.TARGET),
        events=(
            ActionEvent(
                "noop",
                100,
                1,
                EntityId.TARGET,
                ActionChannel.ABILITY,
                (HealOutput(EntityId.TARGET, Decimal(0)),),
            ),
        ),
    )

    assert result.actor_at_end.current_hp == Decimal(1000)
    assert result.healing_prevented_by_entity[EntityId.ACTOR] == Decimal(0)


def test_missing_health_heal_reads_missing_health_when_it_resolves() -> None:
    result = simulate_timeline(
        duration_ms=1000,
        horizon_ms=1000,
        actor=_combatant(EntityId.ACTOR),
        target=_combatant(EntityId.TARGET),
        events=(
            ActionEvent(
                "wound",
                100,
                1,
                EntityId.TARGET,
                ActionChannel.ABILITY,
                (DamageOutput(EntityId.ACTOR, Decimal(600), DamageType.TRUE),),
            ),
            ActionEvent(
                "decimate",
                200,
                2,
                EntityId.ACTOR,
                ActionChannel.ABILITY,
                (MissingHealthHealOutput(EntityId.ACTOR, Decimal("0.17")),),
            ),
        ),
    )

    assert result.actor_at_end.current_hp == Decimal(400) + Decimal(600) * Decimal("0.17")


def test_darius_q_heal_scales_with_missing_health() -> None:
    from pathlib import Path

    from lol_build.application.matchup import MatchupEngine, MatchupRequest

    root = Path(__file__).resolve().parents[1]
    evaluation = MatchupEngine(root).evaluate(MatchupRequest("Darius", "Garen"))
    decimate_heals = [
        entry
        for entry in evaluation.timeline.log
        if entry.event_id.startswith("DARIUS_Q") and entry.operation == "HEAL"
    ]

    assert len(decimate_heals) == 1
    assert decimate_heals[0].hp_delta is not None and decimate_heals[0].hp_delta >= 0


def test_triggered_death_prevention_revives_after_stasis_once() -> None:
    from lol_build.core.timeline import DeathPreventionOutput

    result = simulate_timeline(
        duration_ms=6000,
        horizon_ms=6000,
        actor=_combatant(EntityId.ACTOR, current_hp="100"),
        target=_combatant(EntityId.TARGET),
        events=(
            ActionEvent(
                "chronoshift",
                0,
                1,
                EntityId.ACTOR,
                ActionChannel.ABILITY,
                (
                    DeathPreventionOutput(
                        EntityId.ACTOR,
                        health_floor=Decimal(1),
                        duration_ms=5000,
                        state_key="REVIVE",
                        trigger_stasis_ms=3000,
                        trigger_heal=Decimal(500),
                    ),
                ),
            ),
            ActionEvent(
                "lethal",
                1000,
                2,
                EntityId.TARGET,
                ActionChannel.ABILITY,
                (DamageOutput(EntityId.ACTOR, Decimal(400), DamageType.TRUE),),
            ),
            ActionEvent(
                "during_stasis",
                2000,
                3,
                EntityId.TARGET,
                ActionChannel.ABILITY,
                (DamageOutput(EntityId.ACTOR, Decimal(400), DamageType.TRUE),),
            ),
            ActionEvent(
                "after_revive",
                4500,
                4,
                EntityId.TARGET,
                ActionChannel.ABILITY,
                (DamageOutput(EntityId.ACTOR, Decimal(100), DamageType.TRUE),),
            ),
        ),
    )

    stasis_hit = next(entry for entry in result.log if entry.event_id == "during_stasis")
    assert stasis_hit.status == "IMMUNE_STASIS"
    # Floor 1, revive heal 500 at 4000 ms, then 100 damage; the window is spent.
    assert result.actor_at_end.current_hp == Decimal(401)
    assert not result.actor_at_end.dead


def test_spell_shield_heal_applies_only_when_an_ability_is_blocked() -> None:
    shield = ActionEvent(
        "spell_shield",
        0,
        1,
        EntityId.ACTOR,
        ActionChannel.ABILITY,
        (
            StatusOutput(EntityId.ACTOR, "SPELL_SHIELD", 1500),
            StatusOutput(EntityId.ACTOR, "SPELL_SHIELD_HEAL", 1500, Decimal(80)),
        ),
    )
    blocked = simulate_timeline(
        duration_ms=2000,
        horizon_ms=2000,
        actor=_combatant(EntityId.ACTOR, current_hp="500"),
        target=_combatant(EntityId.TARGET),
        events=(
            shield,
            ActionEvent(
                "enemy_spell",
                500,
                2,
                EntityId.TARGET,
                ActionChannel.ABILITY,
                (DamageOutput(EntityId.ACTOR, Decimal(300), DamageType.TRUE),),
            ),
        ),
    )
    unblocked = simulate_timeline(
        duration_ms=2000,
        horizon_ms=2000,
        actor=_combatant(EntityId.ACTOR, current_hp="500"),
        target=_combatant(EntityId.TARGET),
        events=(
            shield,
            ActionEvent(
                "enemy_attack",
                500,
                2,
                EntityId.TARGET,
                ActionChannel.BASIC_ATTACK,
                (DamageOutput(EntityId.ACTOR, Decimal(100), DamageType.TRUE),),
            ),
        ),
    )

    assert blocked.actor_at_end.current_hp == Decimal(580)
    assert unblocked.actor_at_end.current_hp == Decimal(400)
