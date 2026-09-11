"""Mechanic-driven sustained on-hit rotation event scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from lol_build.core.combat import ATTACK_SPEED_CAP, DamageType, apply_ability_haste
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    Combatant,
    DamageOutput,
    EntityId,
    TimelineResult,
    simulate_timeline,
)


class RotationError(ValueError):
    """Raised when a rotation specification is not executable."""


class MissStackPolicy(StrEnum):
    """Control whether a blinded basic attack advances on-hit stacks."""

    GRANTS_STACK = "GRANTS_STACK"
    DOES_NOT_GRANT_STACK = "DOES_NOT_GRANT_STACK"


@dataclass(frozen=True)
class SustainedOnHitSpec:
    """Fix all timing, scaling, and stacking inputs for a sustained on-hit rotation."""

    duration_ms: int
    horizon_ms: int
    base_attack_speed: Decimal
    attack_speed_ratio: Decimal
    bonus_attack_speed: Decimal
    passive_attack_speed_per_stack: Decimal
    passive_max_stacks: int
    total_attack_damage: Decimal
    total_ability_power: Decimal
    ability_haste: Decimal
    reset_first_at_ms: int
    reset_base_cooldown_seconds: Decimal
    reset_magic_base_damage: Decimal
    reset_ap_ratio: Decimal
    once_at_ms: int
    once_magic_base_damage: Decimal
    once_ap_ratio: Decimal
    once_target_max_hp_ratio: Decimal
    nth_hit: int
    nth_magic_base_damage: Decimal
    nth_ap_ratio: Decimal
    on_hit_magic_base_damage: Decimal = Decimal(0)
    on_hit_ap_ratio: Decimal = Decimal(0)
    attack_speed_cap: Decimal = ATTACK_SPEED_CAP


@dataclass(frozen=True)
class BlindWindow:
    """Describe the timing and effect of one blind window."""

    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class RotationResult:
    """Report scheduled events, resolved damage, attacks, stacks, and blockers."""

    miss_stack_policy: MissStackPolicy
    attacks_attempted: int
    attacks_hit: int
    passive_stacks_at_end: int
    events: tuple[ActionEvent, ...]
    timeline: TimelineResult
    blockers: tuple[str, ...]


def _validate(spec: SustainedOnHitSpec, blind: BlindWindow) -> None:
    """Validate timing, stack, and finite numeric constraints for the rotation.

    :param spec: Validated rotation specification defining timings and coefficients.
    :param blind: Optional blind interval applied to scheduled basic attacks.
    :return: None.
    """

    if spec.duration_ms <= 0 or not 0 <= spec.horizon_ms <= spec.duration_ms:
        raise RotationError("invalid duration or horizon")
    if not 0 <= blind.start_ms <= blind.end_ms <= spec.duration_ms:
        raise RotationError("blind window must be within the rotation")
    positive_decimals = (
        spec.base_attack_speed,
        spec.attack_speed_ratio,
        spec.attack_speed_cap,
    )
    if any(not value.is_finite() or value <= 0 for value in positive_decimals):
        raise RotationError("attack-speed base, ratio, and cap must be positive")
    nonnegative_decimals = (
        spec.bonus_attack_speed,
        spec.passive_attack_speed_per_stack,
        spec.total_attack_damage,
        spec.total_ability_power,
        spec.ability_haste,
        spec.reset_base_cooldown_seconds,
        spec.reset_magic_base_damage,
        spec.reset_ap_ratio,
        spec.once_magic_base_damage,
        spec.once_ap_ratio,
        spec.once_target_max_hp_ratio,
        spec.nth_magic_base_damage,
        spec.nth_ap_ratio,
        spec.on_hit_magic_base_damage,
        spec.on_hit_ap_ratio,
    )
    if any(not value.is_finite() or value < 0 for value in nonnegative_decimals):
        raise RotationError("rotation numeric inputs must be finite and non-negative")
    if spec.passive_max_stacks < 0 or spec.nth_hit <= 0:
        raise RotationError("stack cap and nth-hit interval are invalid")


def _attack_interval_ms(spec: SustainedOnHitSpec, stacks: int) -> int:
    """Convert attacks per second into an attack interval.

    :param spec: Validated rotation specification defining timings and coefficients.
    :param stacks: Program IDs mapped to their current stack count.
    :return: Rounded interval in milliseconds for the current stack count.
    """

    bonus = spec.bonus_attack_speed + spec.passive_attack_speed_per_stack * stacks
    attacks_per_second = min(
        spec.attack_speed_cap,
        spec.base_attack_speed + spec.attack_speed_ratio * bonus,
    )
    return max(
        1,
        int((Decimal(1000) / attacks_per_second).to_integral_value(ROUND_HALF_EVEN)),
    )


def _damage_outputs(
    spec: SustainedOnHitSpec,
    *,
    reset_attack: bool,
    successful_hit_number: int,
) -> tuple[DamageOutput, ...]:
    """Build the damage outputs for one on-hit attack.

    :param spec: Validated rotation specification defining timings and coefficients.
    :param reset_attack: Whether the attack was produced by an attack-reset ability.
    :param successful_hit_number: One-based count of attacks that actually hit the target.
    :return: Physical attack and optional on-hit damage outputs for the event.
    """

    outputs = [DamageOutput(EntityId.TARGET, spec.total_attack_damage, DamageType.PHYSICAL)]
    on_hit = spec.on_hit_magic_base_damage + spec.on_hit_ap_ratio * spec.total_ability_power
    if on_hit > 0:
        outputs.append(DamageOutput(EntityId.TARGET, on_hit, DamageType.MAGIC))
    if reset_attack:
        reset_damage = spec.reset_magic_base_damage + spec.reset_ap_ratio * spec.total_ability_power
        outputs.append(DamageOutput(EntityId.TARGET, reset_damage, DamageType.MAGIC))
    if successful_hit_number % spec.nth_hit == 0:
        nth_damage = spec.nth_magic_base_damage + spec.nth_ap_ratio * spec.total_ability_power
        outputs.append(DamageOutput(EntityId.TARGET, nth_damage, DamageType.MAGIC))
    return tuple(outputs)


def simulate_sustained_on_hit_rotation(
    *,
    spec: SustainedOnHitSpec,
    blind: BlindWindow,
    miss_stack_policy: MissStackPolicy,
    actor: Combatant,
    target: Combatant,
) -> RotationResult:
    """Schedule attacks, a reset, a one-shot ability, and every-nth-hit damage.

    :param spec: Validated rotation specification defining timings and coefficients.
    :param blind: Optional blind interval applied to scheduled basic attacks.
    :param miss_stack_policy: Rule deciding whether a blinded attack advances on-hit stacks.
    :param actor: Mutable combat snapshot that owns the scheduled attacks.
    :param target: Mutable combat snapshot that receives the rotation's damage.
    :return: Simulated timeline plus attempted/hit attack and final-stack counts.
    """

    _validate(spec, blind)
    reset_cooldown_ms = int(
        (
            apply_ability_haste(
                spec.reset_base_cooldown_seconds, spec.ability_haste
            ).effective_cooldown_seconds
            * 1000
        ).to_integral_value(ROUND_HALF_EVEN)
    )
    if reset_cooldown_ms <= 0:
        raise RotationError("reset cooldown must remain positive")

    events: list[ActionEvent] = []
    sequence = 0
    passive_stacks = 0
    attacks_attempted = 0
    attacks_hit = 0
    next_attack_ms = 0
    next_reset_ms = spec.reset_first_at_ms
    while min(next_attack_ms, next_reset_ms) <= spec.duration_ms:
        reset_attack = next_reset_ms <= next_attack_ms
        at_ms = next_reset_ms if reset_attack else next_attack_ms
        if at_ms > spec.duration_ms:
            break
        attacks_attempted += 1
        blinded = blind.start_ms <= at_ms < blind.end_ms
        hit = not blinded
        if hit:
            attacks_hit += 1
        if hit or miss_stack_policy is MissStackPolicy.GRANTS_STACK:
            passive_stacks = min(spec.passive_max_stacks, passive_stacks + 1)
        sequence += 1
        successful_hit_number = attacks_hit if hit else 1
        event = ActionEvent(
            id=f"{'RESET' if reset_attack else 'ATTACK'}_{attacks_attempted}",
            at_ms=at_ms,
            sequence=sequence,
            source=EntityId.ACTOR,
            channel=ActionChannel.BASIC_ATTACK,
            outputs=_damage_outputs(
                spec,
                reset_attack=reset_attack,
                successful_hit_number=successful_hit_number,
            ),
            cancelled=blinded,
            cancellation_reason="BLIND_MISS" if blinded else None,
        )
        events.append(event)
        interval = _attack_interval_ms(spec, passive_stacks)
        if reset_attack:
            next_reset_ms += reset_cooldown_ms
            next_attack_ms = at_ms + interval
        else:
            next_attack_ms = at_ms + interval

    once_damage = (
        spec.once_magic_base_damage
        + spec.once_ap_ratio * spec.total_ability_power
        + spec.once_target_max_hp_ratio * target.max_hp
    )
    events.append(
        ActionEvent(
            id="ABILITY_ONCE",
            at_ms=spec.once_at_ms,
            sequence=sequence + 1,
            source=EntityId.ACTOR,
            channel=ActionChannel.ABILITY,
            outputs=(DamageOutput(EntityId.TARGET, once_damage, DamageType.MAGIC),),
        )
    )
    ordered_events = tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence)))
    timeline = simulate_timeline(
        duration_ms=spec.duration_ms,
        horizon_ms=spec.horizon_ms,
        actor=actor,
        target=target,
        events=ordered_events,
    )
    return RotationResult(
        miss_stack_policy,
        attacks_attempted,
        attacks_hit,
        passive_stacks,
        ordered_events,
        timeline,
        (
            "BLIND_MISS_PASSIVE_STACK_UNVERIFIED",
            "BLIND_MISS_EMPOWERED_AND_NTH_HIT_CONSUMPTION_UNVERIFIED",
            "ATTACK_RESET_TIMING_UNVERIFIED",
        ),
    )
