from decimal import Decimal

import pytest

from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    Combatant,
    DamageModifierWindow,
    DamageOutput,
    EntityId,
    HealOutput,
    HealthCostOutput,
    MaxHealthModifierOutput,
    MissingHealthDamageOutput,
    ShieldOutput,
    StatusOutput,
    TimelineError,
    simulate_timeline,
)


def test_tenacity_reduces_reducible_cc_but_not_airborne() -> None:
    result = simulate_timeline(
        duration_ms=2000,
        horizon_ms=1000,
        actor=_actor(),
        target=Combatant(
            EntityId.TARGET,
            Decimal(100),
            Decimal(100),
            Decimal(0),
            Decimal(0),
            tenacity=Decimal("0.30"),
        ),
        events=(
            ActionEvent(
                "charm",
                100,
                1,
                EntityId.ACTOR,
                ActionChannel.ABILITY,
                (StatusOutput(EntityId.TARGET, "CC_CHARM", 1000),),
            ),
            ActionEvent(
                "airborne",
                100,
                2,
                EntityId.ACTOR,
                ActionChannel.ABILITY,
                (StatusOutput(EntityId.TARGET, "CC_AIRBORNE", 1000),),
            ),
        ),
    )

    charm = next(entry for entry in result.log if entry.event_id == "charm")
    airborne = next(entry for entry in result.log if entry.event_id == "airborne")
    assert charm.detail == "CC_CHARM:800:magnitude=1"
    assert airborne.detail == "CC_AIRBORNE:1100:magnitude=1"


def _actor(*, current_hp: str = "100") -> Combatant:
    return Combatant(
        EntityId.ACTOR,
        max_hp=Decimal(100),
        current_hp=Decimal(current_hp),
        armor=Decimal(0),
        magic_resistance=Decimal(0),
    )


def _target() -> Combatant:
    return Combatant(
        EntityId.TARGET,
        max_hp=Decimal(100),
        current_hp=Decimal(100),
        armor=Decimal(0),
        magic_resistance=Decimal(0),
    )


def test_health_cost_bypasses_shields_and_damage_aggregation() -> None:
    """Spend caster health without consuming shields or scoring damage."""
    actor = Combatant(
        EntityId.ACTOR,
        max_hp=Decimal(100),
        current_hp=Decimal(100),
        armor=Decimal(999),
        magic_resistance=Decimal(999),
        shield=Decimal(50),
    )
    result = simulate_timeline(
        duration_ms=1000,
        horizon_ms=500,
        actor=actor,
        target=_target(),
        events=(
            ActionEvent(
                "health_cost",
                100,
                1,
                EntityId.ACTOR,
                ActionChannel.ABILITY,
                (
                    HealthCostOutput(
                        EntityId.ACTOR,
                        flat_amount=Decimal(10),
                        current_health_ratio=Decimal("0.20"),
                    ),
                ),
                requires_living_opponent=False,
            ),
        ),
    )

    assert result.actor_at_end.current_hp == 70
    assert result.actor_at_end.shield == 50
    assert result.damage_to_target_total == 0
    assert result.log[-1].operation == "HEALTH_COST"


def test_health_cost_respects_floor_and_rejects_empty_contract() -> None:
    """Clamp payments to their floor and reject a zero-valued cost."""
    result = simulate_timeline(
        duration_ms=1000,
        horizon_ms=500,
        actor=_actor(current_hp="10"),
        target=_target(),
        events=(
            ActionEvent(
                "floor_cost",
                100,
                1,
                EntityId.ACTOR,
                ActionChannel.ABILITY,
                (HealthCostOutput(EntityId.ACTOR, flat_amount=Decimal(50)),),
                requires_living_opponent=False,
            ),
        ),
    )
    assert result.actor_at_end.current_hp == 1

    with pytest.raises(TimelineError, match="requires a positive"):
        simulate_timeline(
            duration_ms=1000,
            horizon_ms=500,
            actor=_actor(),
            target=_target(),
            events=(
                ActionEvent(
                    "empty_cost",
                    100,
                    1,
                    EntityId.ACTOR,
                    ActionChannel.ABILITY,
                    (HealthCostOutput(EntityId.ACTOR),),
                ),
            ),
        )


def test_temporary_maximum_health_grants_current_health_then_expires() -> None:
    """Grant current health immediately and clamp it when the bonus expires."""
    result = simulate_timeline(
        duration_ms=2000,
        horizon_ms=500,
        actor=_actor(current_hp="50"),
        target=_target(),
        events=(
            ActionEvent(
                "wild_growth",
                100,
                1,
                EntityId.ACTOR,
                ActionChannel.ABILITY,
                (MaxHealthModifierOutput(EntityId.ACTOR, Decimal(75), 1000),),
                requires_living_opponent=False,
            ),
        ),
    )

    assert result.actor_at_horizon.current_hp == 125
    assert result.actor_at_end.current_hp == 100
    assert result.log[-1].operation == "MAX_HEALTH_MODIFIER"


def test_damage_output_penetration_is_local_and_combines_with_source_penetration() -> None:
    """Apply spell-specific penetration without leaking it to later damage."""
    actor = Combatant(
        EntityId.ACTOR,
        max_hp=Decimal(1000),
        current_hp=Decimal(1000),
        armor=Decimal(0),
        magic_resistance=Decimal(0),
        percent_armor_penetration=Decimal("0.25"),
        flat_armor_penetration=Decimal(10),
    )
    target = Combatant(
        EntityId.TARGET,
        max_hp=Decimal(1000),
        current_hp=Decimal(1000),
        armor=Decimal(100),
        magic_resistance=Decimal(0),
    )
    events = (
        ActionEvent(
            "local_penetration",
            0,
            0,
            EntityId.ACTOR,
            ActionChannel.ABILITY,
            (
                DamageOutput(
                    EntityId.TARGET,
                    Decimal(100),
                    DamageType.PHYSICAL,
                    percent_resistance_penetration=Decimal("0.40"),
                ),
            ),
        ),
        ActionEvent(
            "ordinary_damage",
            1,
            1,
            EntityId.ACTOR,
            ActionChannel.ABILITY,
            (DamageOutput(EntityId.TARGET, Decimal(100), DamageType.PHYSICAL),),
        ),
    )

    result = simulate_timeline(
        duration_ms=1,
        horizon_ms=1,
        actor=actor,
        target=target,
        events=events,
    )
    damages = [entry for entry in result.log if entry.operation == "DAMAGE"]

    assert damages[0].post_mitigation_amount == Decimal(100) * Decimal(100) / Decimal(135)
    assert damages[1].post_mitigation_amount == Decimal(100) * Decimal(100) / Decimal(165)


def test_damage_output_penetration_validation_rejects_invalid_contracts() -> None:
    """Reject out-of-range penetration and meaningless true-damage penetration."""
    invalid_outputs = (
        DamageOutput(
            EntityId.TARGET,
            Decimal(10),
            DamageType.PHYSICAL,
            percent_resistance_penetration=Decimal("1.01"),
        ),
        DamageOutput(
            EntityId.TARGET,
            Decimal(10),
            DamageType.PHYSICAL,
            flat_resistance_penetration=Decimal(-1),
        ),
        DamageOutput(
            EntityId.TARGET,
            Decimal(10),
            DamageType.TRUE,
            percent_resistance_penetration=Decimal("0.40"),
        ),
    )

    for index, output in enumerate(invalid_outputs):
        with pytest.raises(TimelineError):
            simulate_timeline(
                duration_ms=0,
                horizon_ms=0,
                actor=_actor(),
                target=_target(),
                events=(
                    ActionEvent(
                        f"invalid_penetration_{index}",
                        0,
                        0,
                        EntityId.ACTOR,
                        ActionChannel.ABILITY,
                        (output,),
                    ),
                ),
            )


def test_rotation_is_chronological_and_derives_death_from_state() -> None:
    events = (
        ActionEvent(
            "late_lethal_ability",
            3000,
            4,
            EntityId.ACTOR,
            ActionChannel.ABILITY,
            (DamageOutput(EntityId.TARGET, Decimal(80), DamageType.MAGIC),),
        ),
        ActionEvent(
            "opening_attack",
            0,
            1,
            EntityId.ACTOR,
            ActionChannel.BASIC_ATTACK,
            (DamageOutput(EntityId.TARGET, Decimal(30), DamageType.PHYSICAL),),
        ),
        ActionEvent(
            "target_attack",
            1000,
            2,
            EntityId.TARGET,
            ActionChannel.BASIC_ATTACK,
            (DamageOutput(EntityId.ACTOR, Decimal(20), DamageType.PHYSICAL),),
        ),
        ActionEvent(
            "post_death_attack",
            4000,
            5,
            EntityId.ACTOR,
            ActionChannel.BASIC_ATTACK,
            (DamageOutput(EntityId.TARGET, Decimal(50), DamageType.PHYSICAL),),
        ),
    )

    result = simulate_timeline(
        duration_ms=8000,
        horizon_ms=3000,
        actor=_actor(),
        target=_target(),
        events=events,
    )

    assert result.damage_to_target_first_horizon == Decimal(110)
    assert result.damage_to_target_total == Decimal(110)
    assert result.target_at_horizon.dead is True
    assert result.target_at_horizon.current_hp == 0
    assert result.target_dead_at_horizon is True
    assert [entry.event_id for entry in result.log] == [
        "opening_attack",
        "target_attack",
        "late_lethal_ability",
        "post_death_attack",
    ]
    assert result.log[-1].status == "SKIPPED_OPPONENT_DEAD"


def test_output_order_logs_heal_shield_and_damage_application() -> None:
    events = (
        ActionEvent(
            "damage_and_heal",
            0,
            1,
            EntityId.ACTOR,
            ActionChannel.ABILITY,
            (
                DamageOutput(EntityId.TARGET, Decimal(10), DamageType.MAGIC),
                HealOutput(EntityId.ACTOR, Decimal(30)),
            ),
        ),
        ActionEvent(
            "shield_then_damage",
            1000,
            2,
            EntityId.TARGET,
            ActionChannel.ABILITY,
            (
                ShieldOutput(EntityId.ACTOR, Decimal(25)),
                DamageOutput(EntityId.ACTOR, Decimal(40), DamageType.MAGIC),
            ),
            requires_living_opponent=False,
        ),
    )

    result = simulate_timeline(
        duration_ms=8000,
        horizon_ms=3000,
        actor=_actor(current_hp="50"),
        target=_target(),
        events=events,
    )

    assert [entry.operation for entry in result.log] == [
        "DAMAGE",
        "HEAL",
        "SHIELD",
        "DAMAGE",
    ]
    assert result.actor_at_horizon.current_hp == Decimal(65)
    assert result.actor_at_horizon.shield == 0
    final_damage = result.log[-1]
    assert final_damage.shield_absorbed == Decimal(25)
    assert final_damage.hp_delta == Decimal(-15)


def test_cancelled_multi_output_event_removes_damage_and_healing_together() -> None:
    event = ActionEvent(
        "volibear_w_like_event",
        1000,
        1,
        EntityId.ACTOR,
        ActionChannel.ABILITY,
        (
            DamageOutput(EntityId.TARGET, Decimal(40), DamageType.PHYSICAL),
            HealOutput(EntityId.ACTOR, Decimal(30)),
        ),
        cancelled=True,
        cancellation_reason="CAST_PREVENTED",
    )

    result = simulate_timeline(
        duration_ms=8000,
        horizon_ms=3000,
        actor=_actor(current_hp="50"),
        target=_target(),
        events=(event,),
    )

    assert result.damage_to_target_total == 0
    assert result.actor_at_end.current_hp == Decimal(50)
    assert result.target_at_end.current_hp == Decimal(100)
    assert len(result.log) == 1
    assert result.log[0].status == "CANCELLED"
    assert result.log[0].detail == "CAST_PREVENTED"


def test_same_timestamp_sequence_is_explicit_and_unique() -> None:
    duplicate_order = (
        ActionEvent(
            "one",
            0,
            1,
            EntityId.ACTOR,
            ActionChannel.ABILITY,
            (HealOutput(EntityId.ACTOR, Decimal(1)),),
        ),
        ActionEvent(
            "two",
            0,
            1,
            EntityId.ACTOR,
            ActionChannel.ABILITY,
            (HealOutput(EntityId.ACTOR, Decimal(1)),),
        ),
    )

    with pytest.raises(TimelineError, match="duplicate event order key"):
        simulate_timeline(
            duration_ms=8000,
            horizon_ms=3000,
            actor=_actor(),
            target=_target(),
            events=duplicate_order,
        )


def test_event_at_horizon_is_included() -> None:
    event = ActionEvent(
        "at_horizon",
        3000,
        1,
        EntityId.ACTOR,
        ActionChannel.ABILITY,
        (DamageOutput(EntityId.TARGET, Decimal(10), DamageType.TRUE),),
    )

    result = simulate_timeline(
        duration_ms=8000,
        horizon_ms=3000,
        actor=_actor(),
        target=_target(),
        events=(event,),
    )

    assert result.damage_to_target_first_horizon == Decimal(10)
    assert result.target_at_horizon.current_hp == Decimal(90)


def test_invalid_event_and_combatant_inputs_are_rejected() -> None:
    with pytest.raises(TimelineError, match="outside"):
        simulate_timeline(
            duration_ms=8000,
            horizon_ms=3000,
            actor=_actor(),
            target=_target(),
            events=(
                ActionEvent(
                    "too_late",
                    8001,
                    1,
                    EntityId.ACTOR,
                    ActionChannel.ABILITY,
                    (DamageOutput(EntityId.TARGET, Decimal(1), DamageType.TRUE),),
                ),
            ),
        )

    with pytest.raises(TimelineError, match="requires a reason"):
        simulate_timeline(
            duration_ms=8000,
            horizon_ms=3000,
            actor=_actor(),
            target=_target(),
            events=(
                ActionEvent(
                    "bad_cancel",
                    0,
                    1,
                    EntityId.ACTOR,
                    ActionChannel.ABILITY,
                    (HealOutput(EntityId.ACTOR, Decimal(1)),),
                    cancelled=True,
                ),
            ),
        )


def test_damage_modifier_window_affects_only_declared_damage_types() -> None:
    events = (
        ActionEvent(
            "physical",
            1000,
            1,
            EntityId.ACTOR,
            ActionChannel.ABILITY,
            (DamageOutput(EntityId.TARGET, Decimal(100), DamageType.PHYSICAL),),
        ),
        ActionEvent(
            "true",
            1000,
            2,
            EntityId.ACTOR,
            ActionChannel.ABILITY,
            (DamageOutput(EntityId.TARGET, Decimal(100), DamageType.TRUE),),
        ),
    )
    result = simulate_timeline(
        duration_ms=8000,
        horizon_ms=3000,
        actor=_actor(),
        target=Combatant(
            EntityId.TARGET,
            max_hp=Decimal(1000),
            current_hp=Decimal(1000),
            armor=Decimal(0),
            magic_resistance=Decimal(0),
        ),
        events=events,
        damage_modifier_windows=(
            DamageModifierWindow(
                "physical_reduction",
                500,
                2000,
                EntityId.TARGET,
                (DamageType.PHYSICAL,),
                Decimal("0.75"),
            ),
        ),
    )

    assert result.damage_to_target_total == Decimal(175)
    assert [entry.raw_amount for entry in result.log] == [Decimal(75), Decimal(100)]


def test_missing_health_damage_uses_state_at_event_time() -> None:
    result = simulate_timeline(
        duration_ms=3000,
        horizon_ms=3000,
        actor=_actor(),
        target=Combatant(
            EntityId.TARGET,
            max_hp=Decimal(1000),
            current_hp=Decimal(1000),
            armor=Decimal(0),
            magic_resistance=Decimal(0),
        ),
        events=(
            ActionEvent(
                "opener",
                100,
                1,
                EntityId.ACTOR,
                ActionChannel.ABILITY,
                (DamageOutput(EntityId.TARGET, Decimal(400), DamageType.TRUE),),
            ),
            ActionEvent(
                "missing_health_execute",
                200,
                2,
                EntityId.ACTOR,
                ActionChannel.ABILITY,
                (
                    MissingHealthDamageOutput(
                        EntityId.TARGET,
                        Decimal(200),
                        Decimal("0.30"),
                        DamageType.TRUE,
                    ),
                ),
            ),
        ),
    )

    execute = next(entry for entry in result.log if entry.event_id == "missing_health_execute")
    assert execute.raw_amount == Decimal(320)
    assert result.target_at_end.current_hp == Decimal(280)


def test_source_penetration_increases_damage_against_positive_resistance() -> None:
    event = ActionEvent(
        "physical_hit",
        0,
        0,
        EntityId.ACTOR,
        ActionChannel.ABILITY,
        (DamageOutput(EntityId.TARGET, Decimal(100), DamageType.PHYSICAL),),
    )
    target = Combatant(
        EntityId.TARGET,
        Decimal(1000),
        Decimal(1000),
        Decimal(100),
        Decimal(0),
    )
    baseline = simulate_timeline(
        duration_ms=1000,
        horizon_ms=1000,
        actor=_actor(),
        target=target,
        events=(event,),
    )
    penetrated = simulate_timeline(
        duration_ms=1000,
        horizon_ms=1000,
        actor=Combatant(
            EntityId.ACTOR,
            Decimal(100),
            Decimal(100),
            Decimal(0),
            Decimal(0),
            percent_armor_penetration=Decimal("0.40"),
            flat_armor_penetration=Decimal(10),
        ),
        target=target,
        events=(event,),
    )

    assert baseline.damage_to_target_total == Decimal(50)
    assert penetrated.damage_to_target_total > baseline.damage_to_target_total
