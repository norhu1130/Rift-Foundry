"""Deterministic base damage and resistance calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

HUNDRED = Decimal(100)
ONE = Decimal(1)
TWO = Decimal(2)


class CombatMathError(ValueError):
    """Raised when a combat calculation receives an invalid numeric input."""


class DamageType(StrEnum):
    """Select physical, magical, or true-damage mitigation rules."""

    PHYSICAL = "PHYSICAL"
    MAGIC = "MAGIC"
    TRUE = "TRUE"


@dataclass(frozen=True)
class DamageResult:
    """Record raw damage, mitigation inputs, and final post-resistance damage."""

    damage_type: DamageType
    raw_damage: Decimal
    resistance: Decimal | None
    multiplier: Decimal
    post_mitigation_damage: Decimal


@dataclass(frozen=True)
class ResistanceModifiers:
    """Define the ordered numeric changes in resistance modifiers."""

    flat_reduction: Decimal = Decimal(0)
    percent_reduction: Decimal = Decimal(0)
    percent_penetration: Decimal = Decimal(0)
    flat_penetration: Decimal = Decimal(0)


@dataclass(frozen=True)
class ResistanceStage:
    """Record resistance before and after one ordered pipeline operation."""

    name: str
    before: Decimal
    after: Decimal
    applied: bool


@dataclass(frozen=True)
class ResistancePipelineResult:
    """Expose effective resistance and every ordered reduction/penetration stage."""

    initial_resistance: Decimal
    effective_resistance: Decimal
    stages: tuple[ResistanceStage, ...]


@dataclass(frozen=True)
class AbilityHasteResult:
    """Expose cooldown multiplier, equivalent reduction, and final cooldown."""

    base_cooldown_seconds: Decimal
    ability_haste: Decimal
    cooldown_multiplier: Decimal
    equivalent_cooldown_reduction: Decimal
    effective_cooldown_seconds: Decimal


@dataclass(frozen=True)
class DamageMix:
    """Define physical, magical, and true-damage fractions for EHP."""

    physical: Decimal
    magical: Decimal
    true: Decimal


@dataclass(frozen=True)
class EffectiveHealthResult:
    """Expose physical, magical, true, and damage-mix-weighted durability."""

    health: Decimal
    armor: Decimal
    magic_resistance: Decimal
    damage_mix: DamageMix
    physical_ehp: Decimal
    magical_ehp: Decimal
    true_ehp: Decimal
    mixed_damage_multiplier: Decimal
    mixed_ehp: Decimal


def _require_finite_decimal(value: Decimal, *, name: str) -> None:
    """Reject non-Decimal and non-finite numeric inputs.

    :param value: Decimal operand required by a combat calculation.
    :param name: Diagnostic field name included in validation errors.
    :return: None.
    """

    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise CombatMathError(f"{name} must be finite")


def resistance_multiplier(resistance: Decimal) -> Decimal:
    """Return the damage multiplier for positive, zero, or negative resistance.

    Positive resistance uses ``100 / (100 + resistance)``. Negative resistance
    uses ``2 - 100 / (100 - resistance)`` and approaches, but never reaches, 2.

    :param resistance: Target armor or magic resistance before damage multiplication.
    :return: Fraction of raw damage remaining after the supplied resistance.
    """

    _require_finite_decimal(resistance, name="resistance")
    if resistance >= 0:
        return HUNDRED / (HUNDRED + resistance)
    return TWO - (HUNDRED / (HUNDRED - resistance))


def apply_ability_haste(
    base_cooldown_seconds: Decimal,
    ability_haste: Decimal,
) -> AbilityHasteResult:
    """Convert ability haste into cooldown and equivalent reduction values.

    :param base_cooldown_seconds: Unmodified spell cooldown in seconds.
    :param ability_haste: Non-negative ability haste applied to the base cooldown.
    :return: Cooldown multiplier, equivalent reduction, and effective cooldown.
    """

    _require_finite_decimal(base_cooldown_seconds, name="base_cooldown_seconds")
    _require_finite_decimal(ability_haste, name="ability_haste")
    if base_cooldown_seconds < 0:
        raise CombatMathError("base_cooldown_seconds must be non-negative")
    if ability_haste < 0:
        raise CombatMathError("ability_haste must be non-negative")

    denominator = HUNDRED + ability_haste
    cooldown_multiplier = HUNDRED / denominator
    equivalent_cooldown_reduction = ability_haste / denominator
    return AbilityHasteResult(
        base_cooldown_seconds=base_cooldown_seconds,
        ability_haste=ability_haste,
        cooldown_multiplier=cooldown_multiplier,
        equivalent_cooldown_reduction=equivalent_cooldown_reduction,
        effective_cooldown_seconds=base_cooldown_seconds * cooldown_multiplier,
    )


def _validate_damage_mix(damage_mix: DamageMix) -> None:
    """Validate damage mix.

    :param damage_mix: Physical, magical, and true-damage fractions that sum to one.
    :return: None.
    """

    if not isinstance(damage_mix, DamageMix):
        raise TypeError("damage_mix must be DamageMix")
    for name in ("physical", "magical", "true"):
        value = getattr(damage_mix, name)
        _require_finite_decimal(value, name=f"damage_mix.{name}")
        if not Decimal(0) <= value <= Decimal(1):
            raise CombatMathError(f"damage_mix.{name} must be between 0 and 1")
    if damage_mix.physical + damage_mix.magical + damage_mix.true != ONE:
        raise CombatMathError("damage mix must sum exactly to 1")


def calculate_effective_health(
    health: Decimal,
    *,
    armor: Decimal,
    magic_resistance: Decimal,
    damage_mix: DamageMix,
) -> EffectiveHealthResult:
    """Calculate per-channel and mixed effective health without averaging EHP.

    :param health: Maximum health used by the effective-health calculation.
    :param armor: Armor protecting against the physical portion of the damage mix.
    :param magic_resistance: Magic resistance protecting against magical damage.
    :param damage_mix: Physical, magical, and true-damage fractions that sum to one.
    :return: Per-channel EHP and damage-mix-weighted EHP without scalar averaging.
    """

    _require_finite_decimal(health, name="health")
    _require_finite_decimal(armor, name="armor")
    _require_finite_decimal(magic_resistance, name="magic_resistance")
    if health < 0:
        raise CombatMathError("health must be non-negative")
    _validate_damage_mix(damage_mix)

    physical_multiplier = resistance_multiplier(armor)
    magical_multiplier = resistance_multiplier(magic_resistance)
    mixed_damage_multiplier = (
        damage_mix.physical * physical_multiplier
        + damage_mix.magical * magical_multiplier
        + damage_mix.true
    )
    return EffectiveHealthResult(
        health=health,
        armor=armor,
        magic_resistance=magic_resistance,
        damage_mix=damage_mix,
        physical_ehp=health / physical_multiplier,
        magical_ehp=health / magical_multiplier,
        true_ehp=health,
        mixed_damage_multiplier=mixed_damage_multiplier,
        mixed_ehp=health / mixed_damage_multiplier,
    )


def _validate_modifiers(modifiers: ResistanceModifiers) -> None:
    """Validate modifiers.

    :param modifiers: Ordered resistance reductions and penetration values.
    :return: None.
    """

    for name in ("flat_reduction", "flat_penetration"):
        value = getattr(modifiers, name)
        _require_finite_decimal(value, name=name)
        if value < 0:
            raise CombatMathError(f"{name} must be non-negative")
    for name in ("percent_reduction", "percent_penetration"):
        value = getattr(modifiers, name)
        _require_finite_decimal(value, name=name)
        if not Decimal(0) <= value <= Decimal(1):
            raise CombatMathError(f"{name} must be between 0 and 1")


def apply_resistance_pipeline(
    resistance: Decimal,
    modifiers: ResistanceModifiers,
) -> ResistancePipelineResult:
    """Apply flat reduction, percent reduction, percent pen, then flat pen.

    Reduction may make resistance negative. Percentage operations are skipped
    once resistance is non-positive, and penetration is clamped at zero.

    :param resistance: Target armor or magic resistance before damage multiplication.
    :param modifiers: Ordered resistance reductions and penetration values.
    :return: Effective resistance and an auditable record of every transformation stage.
    """

    _require_finite_decimal(resistance, name="resistance")
    if not isinstance(modifiers, ResistanceModifiers):
        raise TypeError("modifiers must be ResistanceModifiers")
    _validate_modifiers(modifiers)

    current = resistance
    stages: list[ResistanceStage] = []

    before = current
    current -= modifiers.flat_reduction
    stages.append(ResistanceStage("FLAT_REDUCTION", before, current, modifiers.flat_reduction != 0))

    before = current
    percent_reduction_applies = current > 0 and modifiers.percent_reduction != 0
    if percent_reduction_applies:
        current *= ONE - modifiers.percent_reduction
    stages.append(ResistanceStage("PERCENT_REDUCTION", before, current, percent_reduction_applies))

    before = current
    percent_penetration_applies = current > 0 and modifiers.percent_penetration != 0
    if percent_penetration_applies:
        current *= ONE - modifiers.percent_penetration
    stages.append(
        ResistanceStage("PERCENT_PENETRATION", before, current, percent_penetration_applies)
    )

    before = current
    flat_penetration_applies = current > 0 and modifiers.flat_penetration != 0
    if flat_penetration_applies:
        current = max(Decimal(0), current - modifiers.flat_penetration)
    stages.append(ResistanceStage("FLAT_PENETRATION", before, current, flat_penetration_applies))

    return ResistancePipelineResult(
        initial_resistance=resistance,
        effective_resistance=current,
        stages=tuple(stages),
    )


def apply_resistance(
    raw_damage: Decimal,
    damage_type: DamageType,
    *,
    armor: Decimal,
    magic_resistance: Decimal,
) -> DamageResult:
    """Apply the matching resistance while keeping true damage separate.

    :param raw_damage: Damage amount before resistance and mitigation.
    :param damage_type: Physical, magical, or true damage classification.
    :param armor: Armor protecting against the physical portion of the damage mix.
    :param magic_resistance: Magic resistance protecting against magical damage.
    :return: Raw and post-mitigation damage with the resistance used, if applicable.
    """

    _require_finite_decimal(raw_damage, name="raw_damage")
    _require_finite_decimal(armor, name="armor")
    _require_finite_decimal(magic_resistance, name="magic_resistance")
    if raw_damage < 0:
        raise CombatMathError("raw_damage must be non-negative")
    if not isinstance(damage_type, DamageType):
        raise TypeError("damage_type must be DamageType")

    if damage_type is DamageType.TRUE:
        resistance = None
        multiplier = ONE
    elif damage_type is DamageType.PHYSICAL:
        resistance = armor
        multiplier = resistance_multiplier(armor)
    else:
        resistance = magic_resistance
        multiplier = resistance_multiplier(magic_resistance)

    return DamageResult(
        damage_type=damage_type,
        raw_damage=raw_damage,
        resistance=resistance,
        multiplier=multiplier,
        post_mitigation_damage=raw_damage * multiplier,
    )
