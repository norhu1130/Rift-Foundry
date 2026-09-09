"""Deterministic ordered complete-item candidate generation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from itertools import permutations
from typing import Any

from lol_build.core.expression import EvaluationContext, evaluate


class CandidateGenerationError(ValueError):
    """Raised when candidate-generation policy is invalid."""


class ResourceType(StrEnum):
    """Classify champion resources for item-compatibility filtering."""

    MANA = "MANA"
    ENERGY = "ENERGY"
    NONE = "NONE"


class RejectionReason(StrEnum):
    """Identify each hard rule that can exclude an ordered build path."""

    ITEM_NOT_IN_LOCKED_PATCH = "ITEM_NOT_IN_LOCKED_PATCH"
    PATCH_MISMATCH = "PATCH_MISMATCH"
    PURCHASE_LIMIT_DUPLICATE = "PURCHASE_LIMIT_DUPLICATE"
    MANA_ON_MANALESS_CHAMPION = "MANA_ON_MANALESS_CHAMPION"
    CRITICAL_STRIKE_CAP_EXCEEDED = "CRITICAL_STRIKE_CAP_EXCEEDED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    SLOT_LIMIT_EXCEEDED = "SLOT_LIMIT_EXCEEDED"


@dataclass(frozen=True)
class BuildCandidate:
    """Describe one build candidate considered by the recommendation engine."""

    core_count: int
    item_ids: tuple[int, ...]
    total_gold: int
    occupied_slots: int
    component_paths: tuple[tuple[int, ...], ...]
    nonstacking_passive_groups: tuple[str, ...]
    shared_cooldown_groups: tuple[str, ...]


@dataclass(frozen=True)
class RejectedBuild:
    """Record an excluded item path and every hard-filter reason."""

    item_ids: tuple[int, ...]
    reason: RejectionReason
    detail: str


@dataclass(frozen=True)
class CandidateGenerationResult:
    """Keep accepted builds by core milestone alongside auditable rejections."""

    candidates_by_core: Mapping[int, tuple[BuildCandidate, ...]]
    rejections: tuple[RejectedBuild, ...]


def _duplicate_groups(items: Sequence[Mapping[str, Any]], field: str) -> tuple[str, ...]:
    """Find duplicated group identifiers across a build.

    :param items: Candidate items whose group metadata is inspected.
    :param field: Group key such as ``purchase_limit`` or ``same_passive``.
    :return: Sorted group identifiers shared by multiple items.
    """

    values = [item["groups"][field] for item in items if item["groups"][field] is not None]
    return tuple(sorted(value for value, count in Counter(values).items() if count > 1))


def generate_build_candidates(
    *,
    items: tuple[Mapping[str, Any], ...],
    allowed_item_ids: Set[int],
    expected_patch: str,
    budgets_by_core: Mapping[int, int],
    resource: ResourceType,
    evaluation_context: EvaluationContext,
    range_class: str,
    max_core_count: int = 3,
    max_slots: int = 6,
    critical_strike_cap: Decimal = Decimal(1),
) -> CandidateGenerationResult:
    """Generate legal ordered candidates for complete-item milestones 1–3.

    :param items: Complete-item pool from which ordered paths are generated.
    :param allowed_item_ids: Item IDs present in the verified patch catalog.
    :param expected_patch: Patch version that every candidate item must match.
    :param budgets_by_core: Cumulative gold ceiling for each core milestone.
    :param resource: Champion resource type used to reject incompatible items.
    :param evaluation_context: Levels and stat values used to evaluate numeric expressions.
    :param range_class: Owner attack-range class, either MELEE or RANGED.
    :param max_core_count: Largest complete-item milestone to generate, capped at three.
    :param max_slots: Maximum inventory slots available to the candidate build.
    :param critical_strike_cap: Maximum useful critical-strike fraction before excess is rejected.
    :return: Legal builds grouped by core count and auditable rejected paths.
    """

    if not 1 <= max_core_count <= 3:
        raise CandidateGenerationError("max_core_count must be within [1, 3]")
    if isinstance(max_slots, bool) or not isinstance(max_slots, int) or max_slots < 0:
        raise CandidateGenerationError("max_slots must be a non-negative int")
    if not critical_strike_cap.is_finite() or critical_strike_cap < 0:
        raise CandidateGenerationError("critical_strike_cap must be finite and non-negative")
    for core_count in range(1, max_core_count + 1):
        budget = budgets_by_core.get(core_count)
        if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
            raise CandidateGenerationError(f"missing or invalid budget for core {core_count}")

    item_ids = [item["id"] for item in items]
    if len(set(item_ids)) != len(item_ids):
        raise CandidateGenerationError("item pool contains duplicate IDs")

    ordered_items = tuple(sorted(items, key=lambda item: item["id"]))
    if range_class not in {"MELEE", "RANGED"}:
        raise CandidateGenerationError("range_class must be MELEE or RANGED")
    evaluated_stats = {
        item["id"]: {
            stat: evaluate(expression, evaluation_context)
            for stat, expression in item["stats"].items()
        }
        for item in ordered_items
        if item["id"] in allowed_item_ids
    }
    accepted: dict[int, list[BuildCandidate]] = {
        core_count: [] for core_count in range(1, max_core_count + 1)
    }
    rejected: list[RejectedBuild] = []

    for core_count in range(1, max_core_count + 1):
        for ordered_build in permutations(ordered_items, core_count):
            ids = tuple(item["id"] for item in ordered_build)
            unknown_ids = sorted(set(ids) - set(allowed_item_ids))
            if unknown_ids:
                rejected.append(
                    RejectedBuild(
                        ids,
                        RejectionReason.ITEM_NOT_IN_LOCKED_PATCH,
                        ",".join(map(str, unknown_ids)),
                    )
                )
                continue
            if any(item["patch_version"] != expected_patch for item in ordered_build):
                rejected.append(RejectedBuild(ids, RejectionReason.PATCH_MISMATCH, expected_patch))
                continue

            purchase_duplicates = _duplicate_groups(ordered_build, "purchase_limit")
            if purchase_duplicates:
                rejected.append(
                    RejectedBuild(
                        ids,
                        RejectionReason.PURCHASE_LIMIT_DUPLICATE,
                        ",".join(purchase_duplicates),
                    )
                )
                continue

            total_gold = sum(item["cost"]["total"] for item in ordered_build)
            if total_gold > budgets_by_core[core_count]:
                rejected.append(
                    RejectedBuild(
                        ids,
                        RejectionReason.BUDGET_EXCEEDED,
                        f"{total_gold}>{budgets_by_core[core_count]}",
                    )
                )
                continue

            occupied_slots = sum(item["slot_cost"] for item in ordered_build)
            if occupied_slots > max_slots:
                rejected.append(
                    RejectedBuild(
                        ids,
                        RejectionReason.SLOT_LIMIT_EXCEEDED,
                        f"{occupied_slots}>{max_slots}",
                    )
                )
                continue

            mana = sum(
                (evaluated_stats[item["id"]].get("MANA", Decimal(0)) for item in ordered_build),
                Decimal(0),
            )
            if resource is ResourceType.NONE and mana > 0:
                rejected.append(
                    RejectedBuild(ids, RejectionReason.MANA_ON_MANALESS_CHAMPION, str(mana))
                )
                continue

            critical_strike = sum(
                (
                    evaluated_stats[item["id"]].get("CRITICAL_STRIKE_CHANCE", Decimal(0))
                    for item in ordered_build
                ),
                Decimal(0),
            )
            if critical_strike > critical_strike_cap:
                rejected.append(
                    RejectedBuild(
                        ids,
                        RejectionReason.CRITICAL_STRIKE_CAP_EXCEEDED,
                        f"{critical_strike}>{critical_strike_cap}",
                    )
                )
                continue

            accepted[core_count].append(
                BuildCandidate(
                    core_count,
                    ids,
                    total_gold,
                    occupied_slots,
                    tuple(tuple(item["build_path"]) for item in ordered_build),
                    _duplicate_groups(ordered_build, "same_passive"),
                    _duplicate_groups(ordered_build, "shared_cooldown"),
                )
            )

    return CandidateGenerationResult(
        {core: tuple(values) for core, values in accepted.items()}, tuple(rejected)
    )
