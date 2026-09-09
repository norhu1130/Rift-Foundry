"""Numeric evaluation of curated item records."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from lol_build.core.expression import EvaluationContext, evaluate


class BuildNumericStatus(StrEnum):
    """Distinguish complete numeric evaluation from explicitly unknown output."""

    CALCULATED = "CALCULATED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class BuildNumericResult:
    """Expose build totals, item-level evidence, and reasons calculation was withheld."""

    status: BuildNumericStatus
    stats: Mapping[str, Decimal] | None
    item_results: tuple[Mapping[str, Any], ...] | None
    release_eligible: bool
    blockers: tuple[str, ...]


def evaluate_item_numeric(
    item: Mapping[str, Any],
    context: EvaluationContext,
    *,
    range_class: str,
) -> dict[str, Any]:
    """Evaluate all numeric item expressions into an auditable result tree.

    :param item: Normalized item document being evaluated.
    :param context: Exact levels and stats referenced by item expression trees.
    :param range_class: Owner attack-range class, either MELEE or RANGED.
    :return: Auditable item tree containing evaluated stats, effects, and evidence status.
    """

    if range_class not in {"MELEE", "RANGED"}:
        raise ValueError(f"unsupported range class: {range_class!r}")

    stats = {name: evaluate(expression, context) for name, expression in item["stats"].items()}
    effects = []
    for effect in item["effects"]:
        base_value = evaluate(effect["value_expression"], context)
        multiplier = Decimal(1)
        applied_modifiers: list[str] = []
        expected_when = f"SELF_IS_{range_class}"
        for modifier in effect["modifiers"]:
            if modifier["when"] == expected_when:
                multiplier *= evaluate(modifier["multiplier"], context)
                applied_modifiers.append(modifier["when"])
        effects.append(
            {
                "id": effect["id"],
                "base_value": base_value,
                "effective_value": base_value * multiplier,
                "applied_modifiers": applied_modifiers,
            }
        )

    return {
        "item_id": item["id"],
        "patch_version": item["patch_version"],
        "stats": stats,
        "effects": effects,
        "named_exceptions": [exception["handler"] for exception in item["unsupported_effects"]],
        "source_status": item["verification"]["status"],
        "release_eligible": item["verification"]["status"] == "VERIFIED",
    }


def _duplicate_group(items: tuple[Mapping[str, Any], ...], key: str) -> tuple[str, ...]:
    """Find duplicated item-group identifiers.

    :param items: Candidate items whose group field is checked for duplicates.
    :param key: Group field to inspect, such as ``same_passive`` or ``shared_cooldown``.
    :return: Sorted group identifiers that occur more than once.
    """

    groups = [item["groups"][key] for item in items if item["groups"][key] is not None]
    return tuple(sorted(group for group, count in Counter(groups).items() if count > 1))


def evaluate_build_numeric(
    items: tuple[Mapping[str, Any], ...],
    context: EvaluationContext,
    *,
    range_class: str,
) -> BuildNumericResult:
    """Evaluate a supported item portfolio without inventing group semantics.

    :param items: Candidate items to aggregate and evaluate in purchase order.
    :param context: Base levels and stats before item bonuses are applied.
    :param range_class: Owner attack-range class, either MELEE or RANGED.
    :return: Aggregated stats and per-item calculations, or explicit blockers when unsafe.
    """

    blockers: list[str] = []
    for group in _duplicate_group(items, "same_passive"):
        blockers.append(f"UNRESOLVED_SAME_PASSIVE:{group}")
    for group in _duplicate_group(items, "shared_cooldown"):
        blockers.append(f"UNRESOLVED_SHARED_COOLDOWN:{group}")
    for item in items:
        for exception in item["unsupported_effects"]:
            blockers.append(f"UNIMPLEMENTED_HANDLER:{item['id']}:{exception['handler']}")
    if blockers:
        return BuildNumericResult(
            BuildNumericStatus.UNKNOWN,
            None,
            None,
            False,
            tuple(blockers),
        )

    stats: dict[str, Decimal] = {}
    for item in items:
        for stat, expression in item["stats"].items():
            stats[stat] = stats.get(stat, Decimal(0)) + evaluate(expression, context)

    augmented_stats = dict(context.stats)
    for stat, value in stats.items():
        for basis in ("BONUS", "TOTAL"):
            key = ("SELF", basis, stat)
            if key in augmented_stats:
                augmented_stats[key] += value
    augmented_context = EvaluationContext(
        self_level=context.self_level,
        target_level=context.target_level,
        stats=augmented_stats,
    )
    item_results = tuple(
        evaluate_item_numeric(item, augmented_context, range_class=range_class) for item in items
    )
    return BuildNumericResult(
        BuildNumericStatus.CALCULATED,
        stats,
        item_results,
        all(item["verification"]["status"] == "VERIFIED" for item in items),
        (),
    )
