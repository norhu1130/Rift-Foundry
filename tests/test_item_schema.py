import json
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from lol_build.core.canonical import dumps
from lol_build.core.expression import EvaluationContext, evaluate
from lol_build.items.evaluation import (
    BuildNumericStatus,
    evaluate_build_numeric,
    evaluate_item_numeric,
)

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


EXPRESSION_SCHEMA = _load(ROOT / "schemas/numeric-expression.schema.json")
ITEM_SCHEMA = _load(ROOT / "schemas/item.schema.json")
REGISTRY = Registry().with_resource(
    "https://local.lol-build.example/schemas/numeric-expression.schema.json",
    Resource.from_contents(EXPRESSION_SCHEMA),
)
VALIDATOR = Draft202012Validator(
    ITEM_SCHEMA,
    registry=REGISTRY,
    format_checker=FormatChecker(),
)


def _item(item_id: int) -> dict:
    return _load(ROOT / f"data/curated/items/{item_id}.json")


CURATED_ITEM_IDS = (3053, 3071, 3111, 3115, 3153, 4633, 6665)


def test_all_curated_items_are_structurally_valid() -> None:
    for item_id in CURATED_ITEM_IDS:
        assert list(VALIDATOR.iter_errors(_item(item_id))) == []


def test_sterak_numeric_effects_evaluate_without_approximation() -> None:
    item = _item(3053)
    context = EvaluationContext(
        self_level=13,
        target_level=13,
        stats={
            ("SELF", "BASE", "AD"): Decimal("100"),
            ("SELF", "BONUS", "HP"): Decimal("1000"),
        },
    )

    assert evaluate(item["effects"][0]["value_expression"], context) == Decimal("50.00")
    assert evaluate(item["effects"][1]["value_expression"], context) == Decimal("600.00")


def test_item_modes_do_not_accidentally_share_ids() -> None:
    raw_items = _load(ROOT / "data/raw/16.17.1/en_US/item.json")["data"]

    assert raw_items["3111"]["maps"]["11"] is True
    assert raw_items["223111"]["maps"]["11"] is False


def test_two_item_evaluation_is_byte_identical() -> None:
    context = EvaluationContext(
        self_level=13,
        target_level=13,
        stats={
            ("SELF", "BASE", "AD"): Decimal("100"),
            ("SELF", "BONUS", "HP"): Decimal("1000"),
        },
    )
    first = [
        evaluate_item_numeric(_item(item_id), context, range_class="MELEE")
        for item_id in (3111, 3053)
    ]
    second = [
        evaluate_item_numeric(_item(item_id), context, range_class="MELEE")
        for item_id in (3111, 3053)
    ]

    assert dumps(first).encode() == dumps(second).encode()
    assert all(result["release_eligible"] is False for result in first)


def test_sterak_ranged_modifier_is_applied() -> None:
    context = EvaluationContext(
        self_level=13,
        target_level=13,
        stats={
            ("SELF", "BASE", "AD"): Decimal("100"),
            ("SELF", "BONUS", "HP"): Decimal("1000"),
        },
    )

    result = evaluate_item_numeric(_item(3053), context, range_class="RANGED")

    assert result["effects"][1]["base_value"] == Decimal("600.00")
    assert result["effects"][1]["effective_value"] == Decimal("360.0000")
    assert result["effects"][1]["applied_modifiers"] == ["SELF_IS_RANGED"]


def test_nashors_add_and_multiply_expression() -> None:
    context = EvaluationContext(
        self_level=13,
        target_level=13,
        stats={("SELF", "TOTAL", "AP"): Decimal("200")},
    )

    result = evaluate_item_numeric(_item(3115), context, range_class="MELEE")

    assert result["effects"][0]["effective_value"] == Decimal("45.00")


def test_bork_current_health_damage_has_exact_range_split() -> None:
    context = EvaluationContext(
        self_level=13,
        target_level=13,
        stats={("TARGET", "CURRENT", "HP"): Decimal("2000")},
    )

    melee = evaluate_item_numeric(_item(3153), context, range_class="MELEE")
    ranged = evaluate_item_numeric(_item(3153), context, range_class="RANGED")

    assert melee["effects"][0]["effective_value"] == Decimal("180.000")
    assert ranged["effects"][0]["effective_value"] == Decimal("120.00")


def test_riftmaker_bonus_health_conversion() -> None:
    context = EvaluationContext(
        self_level=13,
        target_level=13,
        stats={("SELF", "BONUS", "HP"): Decimal("1000")},
    )

    result = evaluate_item_numeric(_item(4633), context, range_class="MELEE")

    assert result["effects"][0]["effective_value"] == Decimal("20.00")


def test_stateful_effects_are_named_but_not_silently_evaluated() -> None:
    context = EvaluationContext(
        self_level=13,
        target_level=13,
        stats={
            ("TARGET", "CURRENT", "HP"): Decimal("2000"),
            ("SELF", "BONUS", "HP"): Decimal("1000"),
        },
    )

    expected = {
        3071: ["black_cleaver_carve_v1", "black_cleaver_fervor_v1"],
        3153: ["blade_ruined_king_clawing_shadows_v1"],
        4633: ["riftmaker_void_corruption_v1"],
        6665: ["jaksho_voidborn_resilience_v1"],
    }
    for item_id, handlers in expected.items():
        result = evaluate_item_numeric(_item(item_id), context, range_class="MELEE")
        assert result["named_exceptions"] == handlers
        assert result["release_eligible"] is False


def test_supported_build_uses_post_item_stats_for_cross_item_effects() -> None:
    context = EvaluationContext(
        self_level=13,
        target_level=13,
        stats={
            ("SELF", "BASE", "AD"): Decimal("100"),
            ("SELF", "BONUS", "HP"): Decimal(0),
            ("SELF", "TOTAL", "AP"): Decimal(0),
        },
    )

    result = evaluate_build_numeric((_item(3053), _item(3115)), context, range_class="MELEE")

    assert result.status is BuildNumericStatus.CALCULATED
    assert result.stats["HP"] == Decimal(400)
    assert result.stats["AP"] == Decimal(80)
    sterak, nashors = result.item_results
    assert sterak["effects"][1]["effective_value"] == Decimal("240.00")
    assert nashors["effects"][0]["effective_value"] == Decimal("27.00")
    assert result.release_eligible is False


def test_duplicate_passive_and_shared_cooldown_never_generate_numeric_result() -> None:
    first = _item(3053)
    second = _item(3053)
    second["id"] = 999001
    context = EvaluationContext(
        self_level=13,
        target_level=13,
        stats={
            ("SELF", "BASE", "AD"): Decimal("100"),
            ("SELF", "BONUS", "HP"): Decimal(0),
        },
    )

    result = evaluate_build_numeric((first, second), context, range_class="MELEE")

    assert result.status is BuildNumericStatus.UNKNOWN
    assert result.stats is None
    assert result.item_results is None
    assert result.blockers == (
        "UNRESOLVED_SAME_PASSIVE:lifeline",
        "UNRESOLVED_SHARED_COOLDOWN:lifeline",
    )


def test_named_temporal_handler_blocks_portfolio_score() -> None:
    result = evaluate_build_numeric(
        (_item(6665),),
        EvaluationContext(self_level=13, target_level=13, stats={}),
        range_class="MELEE",
    )

    assert result.status is BuildNumericStatus.UNKNOWN
    assert result.blockers == ("UNIMPLEMENTED_HANDLER:6665:jaksho_voidborn_resilience_v1",)
