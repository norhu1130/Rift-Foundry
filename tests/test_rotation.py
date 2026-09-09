from decimal import Decimal

from lol_build.core.timeline import Combatant, EntityId
from lol_build.simulation.on_hit import (
    BlindWindow,
    MissStackPolicy,
    SustainedOnHitSpec,
    simulate_sustained_on_hit_rotation,
)


def _spec() -> SustainedOnHitSpec:
    return SustainedOnHitSpec(
        duration_ms=8000,
        horizon_ms=3000,
        base_attack_speed=Decimal("0.638"),
        attack_speed_ratio=Decimal("0.638"),
        bonus_attack_speed=Decimal("0.8723"),
        passive_attack_speed_per_stack=Decimal("0.11"),
        passive_max_stacks=8,
        total_attack_damage=Decimal("114.5375"),
        total_ability_power=Decimal(80),
        ability_haste=Decimal(15),
        reset_first_at_ms=500,
        reset_base_cooldown_seconds=Decimal(3),
        reset_magic_base_damage=Decimal(190),
        reset_ap_ratio=Decimal("0.6"),
        once_at_ms=2000,
        once_magic_base_damage=Decimal(160),
        once_ap_ratio=Decimal("0.7"),
        once_target_max_hp_ratio=Decimal("0.04"),
        nth_hit=3,
        nth_magic_base_damage=Decimal(130),
        nth_ap_ratio=Decimal("0.6"),
        on_hit_magic_base_damage=Decimal(15),
        on_hit_ap_ratio=Decimal("0.15"),
    )


def _actor() -> Combatant:
    return Combatant(EntityId.ACTOR, Decimal(2200), Decimal(2200), Decimal(75), Decimal(50))


def _target() -> Combatant:
    return Combatant(
        EntityId.TARGET,
        Decimal("100000"),
        Decimal("100000"),
        Decimal("73.275"),
        Decimal("89.235"),
    )


def test_blind_miss_stack_uncertainty_changes_future_attack_schedule() -> None:
    no_stack = simulate_sustained_on_hit_rotation(
        spec=_spec(),
        blind=BlindWindow(1000, 4000),
        miss_stack_policy=MissStackPolicy.DOES_NOT_GRANT_STACK,
        actor=_actor(),
        target=_target(),
    )
    grants = simulate_sustained_on_hit_rotation(
        spec=_spec(),
        blind=BlindWindow(1000, 4000),
        miss_stack_policy=MissStackPolicy.GRANTS_STACK,
        actor=_actor(),
        target=_target(),
    )

    assert grants.attacks_attempted > no_stack.attacks_attempted
    assert grants.passive_stacks_at_end == 8
    assert grants.timeline.damage_to_target_total != no_stack.timeline.damage_to_target_total
    assert all(not event.cancelled for event in grants.events if event.at_ms >= 4000)


def test_without_blind_both_miss_policies_are_identical() -> None:
    no_stack = simulate_sustained_on_hit_rotation(
        spec=_spec(),
        blind=BlindWindow(0, 0),
        miss_stack_policy=MissStackPolicy.DOES_NOT_GRANT_STACK,
        actor=_actor(),
        target=_target(),
    )
    grants = simulate_sustained_on_hit_rotation(
        spec=_spec(),
        blind=BlindWindow(0, 0),
        miss_stack_policy=MissStackPolicy.GRANTS_STACK,
        actor=_actor(),
        target=_target(),
    )

    assert grants.events == no_stack.events
    assert grants.timeline == no_stack.timeline


def test_blind_cancels_only_attacks_and_not_the_once_ability() -> None:
    result = simulate_sustained_on_hit_rotation(
        spec=_spec(),
        blind=BlindWindow(1000, 4000),
        miss_stack_policy=MissStackPolicy.DOES_NOT_GRANT_STACK,
        actor=_actor(),
        target=_target(),
    )

    ability = next(event for event in result.events if event.id == "ABILITY_ONCE")
    assert ability.cancelled is False
    assert any(event.cancelled for event in result.events if event.channel == "BASIC_ATTACK")
