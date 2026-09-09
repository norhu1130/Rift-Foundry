import json
from decimal import Decimal
from pathlib import Path

from lol_build.core.combat import (
    DamageMix,
    apply_ability_haste,
    calculate_effective_health,
    resistance_multiplier,
)
from lol_build.core.validation import (
    compare_accumulated_damage,
    compare_integer_damage,
)

ROOT = Path(__file__).resolve().parents[1]


def test_calculated_golden_fixture() -> None:
    fixture = json.loads((ROOT / "fixtures/golden/combat_math_v1.json").read_text(encoding="utf-8"))

    for case in fixture["resistance_multiplier"]:
        assert resistance_multiplier(Decimal(case["resistance"])) == Decimal(case["expected"])

    for case in fixture["ability_haste"]:
        result = apply_ability_haste(
            Decimal(case["base_cooldown_seconds"]), Decimal(case["ability_haste"])
        )
        assert result.effective_cooldown_seconds == Decimal(case["expected_cooldown_seconds"])
        assert result.equivalent_cooldown_reduction == Decimal(
            case["expected_equivalent_reduction"]
        )

    case = fixture["mixed_ehp"]
    result = calculate_effective_health(
        Decimal(case["health"]),
        armor=Decimal(case["armor"]),
        magic_resistance=Decimal(case["magic_resistance"]),
        damage_mix=DamageMix(
            Decimal(case["damage_mix"]["physical"]),
            Decimal(case["damage_mix"]["magical"]),
            Decimal(case["damage_mix"]["true"]),
        ),
    )
    assert result.physical_ehp == Decimal(case["expected_physical_ehp"])
    assert result.magical_ehp == Decimal(case["expected_magical_ehp"])
    assert result.mixed_ehp == Decimal(case["expected_mixed_ehp"])
    assert fixture["client_measurement"]["status"] == "PENDING"


def test_resistance_and_haste_monotonicity() -> None:
    assert resistance_multiplier(Decimal(200)) < resistance_multiplier(Decimal(100))
    assert (
        apply_ability_haste(Decimal(5), Decimal(200)).effective_cooldown_seconds
        < apply_ability_haste(Decimal(5), Decimal(100)).effective_cooldown_seconds
    )


def test_integer_damage_absolute_tolerance() -> None:
    assert compare_integer_damage(Decimal("100.9"), Decimal(100)).passed is True
    assert compare_integer_damage(Decimal("101.1"), Decimal(100)).passed is False


def test_accumulated_damage_relative_tolerance() -> None:
    assert compare_accumulated_damage(Decimal(1009), Decimal(1000)).passed is True
    assert compare_accumulated_damage(Decimal(1011), Decimal(1000)).passed is False
    assert compare_accumulated_damage(Decimal(0), Decimal(0)).passed is True
    assert compare_accumulated_damage(Decimal(1), Decimal(0)).passed is False
