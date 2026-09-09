from decimal import Decimal

import pytest

from lol_build.core.combat import (
    AbilityHasteResult,
    CombatMathError,
    DamageMix,
    DamageType,
    ResistanceModifiers,
    apply_ability_haste,
    apply_resistance,
    apply_resistance_pipeline,
    calculate_effective_health,
    resistance_multiplier,
)


def test_effective_health_keeps_damage_channels_separate() -> None:
    result = calculate_effective_health(
        Decimal(1000),
        armor=Decimal(100),
        magic_resistance=Decimal(0),
        damage_mix=DamageMix(
            physical=Decimal("0.5"),
            magical=Decimal("0.5"),
            true=Decimal(0),
        ),
    )

    assert result.physical_ehp == Decimal(2000)
    assert result.magical_ehp == Decimal(1000)
    assert result.true_ehp == Decimal(1000)
    assert result.mixed_damage_multiplier == Decimal("0.75")
    assert result.mixed_ehp == Decimal(1000) / Decimal("0.75")


def test_mixed_ehp_is_not_weighted_average_of_channel_ehp() -> None:
    result = calculate_effective_health(
        Decimal(1000),
        armor=Decimal(100),
        magic_resistance=Decimal(0),
        damage_mix=DamageMix(
            physical=Decimal("0.5"),
            magical=Decimal("0.5"),
            true=Decimal(0),
        ),
    )
    incorrect_weighted_average = (
        Decimal("0.5") * result.physical_ehp + Decimal("0.5") * result.magical_ehp
    )

    assert incorrect_weighted_average == Decimal(1500)
    assert result.mixed_ehp != incorrect_weighted_average


@pytest.mark.parametrize(
    ("damage_mix", "selected_field"),
    [
        (DamageMix(Decimal(1), Decimal(0), Decimal(0)), "physical_ehp"),
        (DamageMix(Decimal(0), Decimal(1), Decimal(0)), "magical_ehp"),
        (DamageMix(Decimal(0), Decimal(0), Decimal(1)), "true_ehp"),
    ],
)
def test_pure_damage_mix_equals_its_channel_ehp(
    damage_mix: DamageMix,
    selected_field: str,
) -> None:
    result = calculate_effective_health(
        Decimal(1000),
        armor=Decimal(50),
        magic_resistance=Decimal(-50),
        damage_mix=damage_mix,
    )

    assert result.mixed_ehp == getattr(result, selected_field)


def test_negative_resistance_reduces_channel_ehp_below_health() -> None:
    result = calculate_effective_health(
        Decimal(1000),
        armor=Decimal(-100),
        magic_resistance=Decimal(0),
        damage_mix=DamageMix(Decimal(1), Decimal(0), Decimal(0)),
    )

    assert result.physical_ehp == Decimal(1000) / Decimal("1.5")
    assert result.physical_ehp < result.health


@pytest.mark.parametrize(
    "damage_mix",
    [
        DamageMix(Decimal("0.7"), Decimal("0.2"), Decimal(0)),
        DamageMix(Decimal("1.1"), Decimal("-0.1"), Decimal(0)),
        DamageMix(Decimal("NaN"), Decimal(0), Decimal(1)),
    ],
)
def test_invalid_damage_mix_is_rejected(damage_mix: DamageMix) -> None:
    with pytest.raises(CombatMathError):
        calculate_effective_health(
            Decimal(1000),
            armor=Decimal(0),
            magic_resistance=Decimal(0),
            damage_mix=damage_mix,
        )


def test_negative_health_is_rejected() -> None:
    with pytest.raises(CombatMathError, match="health must be non-negative"):
        calculate_effective_health(
            Decimal(-1),
            armor=Decimal(0),
            magic_resistance=Decimal(0),
            damage_mix=DamageMix(Decimal(1), Decimal(0), Decimal(0)),
        )


@pytest.mark.parametrize(
    ("ability_haste", "expected_cooldown", "expected_reduction"),
    [
        ("0", "5", "0"),
        ("100", "2.5", "0.5"),
        ("900", "0.5", "0.9"),
    ],
)
def test_ability_haste_returns_cooldown_and_equivalent_reduction(
    ability_haste: str,
    expected_cooldown: str,
    expected_reduction: str,
) -> None:
    result = apply_ability_haste(Decimal(5), Decimal(ability_haste))

    assert isinstance(result, AbilityHasteResult)
    assert result.effective_cooldown_seconds == Decimal(expected_cooldown)
    assert result.equivalent_cooldown_reduction == Decimal(expected_reduction)
    assert result.cooldown_multiplier + result.equivalent_cooldown_reduction == 1


def test_very_large_ability_haste_approaches_but_does_not_reach_full_reduction() -> None:
    result = apply_ability_haste(Decimal(5), Decimal("1000000000"))

    assert Decimal(0) < result.effective_cooldown_seconds < Decimal("0.000001")
    assert Decimal("0.999999") < result.equivalent_cooldown_reduction < Decimal(1)


def test_zero_base_cooldown_remains_zero() -> None:
    result = apply_ability_haste(Decimal(0), Decimal(100))

    assert result.effective_cooldown_seconds == 0
    assert result.equivalent_cooldown_reduction == Decimal("0.5")


@pytest.mark.parametrize(
    ("base_cooldown", "ability_haste", "message"),
    [
        (Decimal(-1), Decimal(0), "base_cooldown_seconds"),
        (Decimal(5), Decimal(-1), "ability_haste"),
        (Decimal("NaN"), Decimal(0), "finite"),
        (Decimal(5), Decimal("Infinity"), "finite"),
    ],
)
def test_invalid_ability_haste_inputs_are_rejected(
    base_cooldown: Decimal,
    ability_haste: Decimal,
    message: str,
) -> None:
    with pytest.raises(CombatMathError, match=message):
        apply_ability_haste(base_cooldown, ability_haste)


def test_ability_haste_rejects_float_input() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        apply_ability_haste(5.0, Decimal(0))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("resistance", "expected"),
    [
        ("100", "0.5"),
        ("0", "1"),
        ("-100", "1.5"),
    ],
)
def test_resistance_multiplier_covers_all_sign_regions(resistance: str, expected: str) -> None:
    assert resistance_multiplier(Decimal(resistance)) == Decimal(expected)


def test_negative_resistance_is_monotonic_and_bounded_below_two() -> None:
    at_minus_50 = resistance_multiplier(Decimal("-50"))
    at_minus_500 = resistance_multiplier(Decimal("-500"))

    assert Decimal(1) < at_minus_50 < at_minus_500 < Decimal(2)


def test_damage_types_use_only_their_matching_resistance() -> None:
    physical = apply_resistance(
        Decimal(100),
        DamageType.PHYSICAL,
        armor=Decimal(100),
        magic_resistance=Decimal("-100"),
    )
    magic = apply_resistance(
        Decimal(100),
        DamageType.MAGIC,
        armor=Decimal(100),
        magic_resistance=Decimal("-100"),
    )
    true = apply_resistance(
        Decimal(100),
        DamageType.TRUE,
        armor=Decimal(100),
        magic_resistance=Decimal("-100"),
    )

    assert physical.post_mitigation_damage == Decimal(50)
    assert magic.post_mitigation_damage == Decimal(150)
    assert true.post_mitigation_damage == Decimal(100)
    assert true.resistance is None


def test_zero_damage_remains_zero_in_every_channel() -> None:
    for damage_type in DamageType:
        result = apply_resistance(
            Decimal(0),
            damage_type,
            armor=Decimal("-100"),
            magic_resistance=Decimal("-100"),
        )
        assert result.post_mitigation_damage == 0


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_non_finite_values_are_rejected(value: Decimal) -> None:
    with pytest.raises(CombatMathError, match="finite"):
        resistance_multiplier(value)


def test_negative_raw_damage_is_rejected() -> None:
    with pytest.raises(CombatMathError, match="non-negative"):
        apply_resistance(
            Decimal(-1),
            DamageType.PHYSICAL,
            armor=Decimal(0),
            magic_resistance=Decimal(0),
        )


def test_float_input_is_rejected() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        resistance_multiplier(100.0)  # type: ignore[arg-type]


def test_resistance_pipeline_has_auditable_order_and_penetration_floor() -> None:
    result = apply_resistance_pipeline(
        Decimal(100),
        ResistanceModifiers(
            flat_reduction=Decimal(20),
            percent_reduction=Decimal("0.25"),
            percent_penetration=Decimal("0.50"),
            flat_penetration=Decimal(35),
        ),
    )

    assert [stage.name for stage in result.stages] == [
        "FLAT_REDUCTION",
        "PERCENT_REDUCTION",
        "PERCENT_PENETRATION",
        "FLAT_PENETRATION",
    ]
    assert [(stage.before, stage.after) for stage in result.stages] == [
        (Decimal(100), Decimal(80)),
        (Decimal(80), Decimal(60)),
        (Decimal(60), Decimal(30)),
        (Decimal(30), Decimal(0)),
    ]
    assert result.effective_resistance == 0


def test_reduction_can_cross_zero_but_penetration_cannot_continue_below_it() -> None:
    result = apply_resistance_pipeline(
        Decimal(10),
        ResistanceModifiers(
            flat_reduction=Decimal(20),
            percent_reduction=Decimal("0.5"),
            percent_penetration=Decimal("0.5"),
            flat_penetration=Decimal(20),
        ),
    )

    assert result.effective_resistance == Decimal(-10)
    assert [stage.applied for stage in result.stages] == [True, False, False, False]


def test_pipeline_preserves_existing_negative_resistance_except_flat_reduction() -> None:
    result = apply_resistance_pipeline(
        Decimal(-20),
        ResistanceModifiers(
            flat_reduction=Decimal(10),
            percent_reduction=Decimal("0.5"),
            percent_penetration=Decimal("0.5"),
            flat_penetration=Decimal(10),
        ),
    )

    assert result.effective_resistance == Decimal(-30)
    assert [stage.applied for stage in result.stages] == [True, False, False, False]


def test_pipeline_without_modifiers_is_identity_with_complete_trace() -> None:
    result = apply_resistance_pipeline(Decimal(75), ResistanceModifiers())

    assert result.effective_resistance == Decimal(75)
    assert len(result.stages) == 4
    assert all(stage.applied is False for stage in result.stages)


@pytest.mark.parametrize(
    "modifiers",
    [
        ResistanceModifiers(flat_reduction=Decimal(-1)),
        ResistanceModifiers(flat_penetration=Decimal(-1)),
        ResistanceModifiers(percent_reduction=Decimal("1.01")),
        ResistanceModifiers(percent_penetration=Decimal("-0.01")),
    ],
)
def test_invalid_resistance_modifiers_are_rejected(
    modifiers: ResistanceModifiers,
) -> None:
    with pytest.raises(CombatMathError):
        apply_resistance_pipeline(Decimal(100), modifiers)
