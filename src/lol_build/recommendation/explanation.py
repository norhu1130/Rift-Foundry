"""Deterministic, structured explanations for selected build branches."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal


@dataclass(frozen=True)
class MetricComparison:
    """Compare one selected metric with a named reference candidate."""

    metric_id: str
    objective: str
    selected_value: Decimal
    reference_value: Decimal
    delta: Decimal


@dataclass(frozen=True)
class SlotRunnerUp:
    """Best legal alternative item for one build slot, the rest of the path held fixed.

    Search engines compute this by re-evaluating every other pool item in the
    same slot under the same legality rules that produced the winning path,
    then keeping the best one that also passes the branch's own gate (kill
    threshold, chassis readiness, defense feasibility, and so on). ``item_id``
    is ``None`` when no legal alternative passes that gate. That still splits
    into two distinct situations, which ``legal_alternative_count`` tells
    apart from ``alternative_count``:

    - ``legal_alternative_count == 0``: no other item could legally occupy
      this slot at all (budget, group, or effect-implementation rules
      exhausted it) — the selected item was not narrowly better, it was the
      only option.
    - ``legal_alternative_count > 0`` but ``alternative_count == 0``: other
      items could legally occupy the slot, but none of them kept the build
      inside the branch's own gate — the selected item is not swappable
      without leaving the branch's admissible set entirely.

    In that second situation, ``excluded_item_id`` names the single best such
    gate-failing item (ranked by the same priority metrics as the branch,
    gate ignored) so a UI can show what was actually closest instead of just
    "no alternative" — ``excluded_reason_codes`` names exactly which gate
    condition it failed, and ``excluded_metric_comparisons`` compares it to
    the selected build the same way ``metric_comparisons`` does. All three
    stay empty/``None`` when ``legal_alternative_count == 0`` (nothing to
    compare) or when ``item_id`` is already set (no exclusion happened).
    """

    item_id: int | None
    alternative_count: int
    legal_alternative_count: int
    metric_comparisons: tuple[MetricComparison, ...]
    excluded_item_id: int | None = None
    excluded_reason_codes: tuple[str, ...] = ()
    excluded_metric_comparisons: tuple[MetricComparison, ...] = ()


@dataclass(frozen=True)
class ItemContribution:
    """Expose the item inputs that support its displayed recommendation roles."""

    item_id: int
    stat_ids: tuple[str, ...]
    effect_labels: tuple[str, ...]
    role_codes: tuple[str, ...]
    slot_runner_up: SlotRunnerUp | None = None


@dataclass(frozen=True)
class BuildExplanation:
    """Describe why one branch survived gates and outranked its comparison build."""

    policy_id: str
    reason_codes: tuple[str, ...]
    satisfied_constraints: tuple[str, ...]
    priority_metrics: tuple[str, ...]
    comparison_kind: str | None
    comparison_item_ids: tuple[int, ...]
    metric_comparisons: tuple[MetricComparison, ...]
    item_contributions: tuple[ItemContribution, ...]


_STAT_ROLES: Mapping[str, tuple[str, ...]] = {
    "AD": ("DAMAGE_OUTPUT",),
    "AP": ("DAMAGE_OUTPUT",),
    "ATTACK_SPEED": ("ATTACK_CADENCE",),
    "ABILITY_HASTE": ("ABILITY_CADENCE",),
    "HP": ("HEALTH_CHASSIS",),
    "ARMOR": ("PHYSICAL_DURABILITY",),
    "MAGIC_RESISTANCE": ("MAGICAL_DURABILITY",),
    "MOVE_SPEED_FLAT": ("ENGAGE_MOBILITY",),
    "MOVE_SPEED_PERCENT": ("ENGAGE_MOBILITY",),
    "TENACITY": ("CC_DURATION_REDUCTION",),
    "LIFESTEAL": ("COMBAT_SUSTAIN",),
    "OMNIVAMP": ("COMBAT_SUSTAIN",),
    "PERCENT_ARMOR_PENETRATION": ("PHYSICAL_PENETRATION",),
    "LETHALITY": ("PHYSICAL_PENETRATION",),
    "MAGIC_PENETRATION_FLAT": ("MAGICAL_PENETRATION",),
    "MAGIC_PENETRATION_PERCENT": ("MAGICAL_PENETRATION",),
}


def _effect_roles(label: str) -> tuple[str, ...]:
    """Map a curated effect label to conservative mechanic roles.

    :param label: Curated passive or active source label.
    :return: Role codes directly supported by the label.
    """

    normalized = label.casefold()
    roles: set[str] = set()
    if label.startswith("ACTIVE:"):
        roles.add("ITEM_ACTIVE")
    if any(token in normalized for token in ("spellblade", "cleave", "mist's edge", "fray")):
        roles.add("DAMAGE_EFFECT")
    if any(token in normalized for token in ("lifeline", "shield")):
        roles.add("LOW_HEALTH_SURVIVAL")
    if any(token in normalized for token in ("shipwrecker", "quicken", "shockwave")):
        roles.add("ENGAGE_MOBILITY")
    if "colossal consumption" in normalized or "goliath" in normalized:
        roles.add("STACKING_HEALTH_SCALING")
    if "warmog's heart" in normalized:
        roles.add("OUT_OF_COMBAT_RECOVERY")
        roles.add("BONUS_HEALTH_REQUIREMENT")
    return tuple(sorted(roles))


def item_contribution(item: Mapping[str, object]) -> ItemContribution:
    """Derive one item's roles from locked stats and curated effect labels.

    :param item: Loaded item document used by the calculation engine.
    :return: Auditable input fields and conservative role codes.
    """

    stats = item["stats"]
    assert isinstance(stats, Mapping)
    programs = item.get("__effect_programs", ())
    assert isinstance(programs, (list, tuple))
    labels = tuple(
        sorted(
            {
                str(program["source_label"])
                for program in programs
                if isinstance(program, Mapping) and program.get("source_label")
            }
        )
    )
    roles = {role for stat_id in stats for role in _STAT_ROLES.get(str(stat_id), ())}
    roles.update(role for label in labels for role in _effect_roles(label))
    return ItemContribution(
        int(item["id"]),
        tuple(sorted(str(stat_id) for stat_id in stats)),
        labels,
        tuple(sorted(roles)),
    )


def _metric_comparisons(
    priority_metrics: tuple[str, ...],
    minimize_metrics: tuple[str, ...],
    selected_metrics: Mapping[str, Decimal],
    reference_metrics: Mapping[str, Decimal],
) -> tuple[MetricComparison, ...]:
    """Compare a reference candidate's metrics against the selected build's.

    :param priority_metrics: Metrics the branch's own selection rule ranks by.
    :param minimize_metrics: Priority metrics for which a lower value is preferred.
    :param selected_metrics: Engine metric vector for the winning full build.
    :param reference_metrics: Engine metric vector for the candidate being compared.
    :return: One comparison per shared priority metric.
    """

    return tuple(
        MetricComparison(
            metric_id,
            "MINIMIZE" if metric_id in minimize_metrics else "MAXIMIZE",
            selected_metrics[metric_id],
            reference_metrics[metric_id],
            selected_metrics[metric_id] - reference_metrics[metric_id],
        )
        for metric_id in priority_metrics
        if metric_id in selected_metrics and metric_id in reference_metrics
    )


def build_slot_runner_up(
    *,
    priority_metrics: tuple[str, ...],
    minimize_metrics: tuple[str, ...] = (),
    selected_metrics: Mapping[str, Decimal],
    runner_up_item_id: int | None,
    runner_up_metrics: Mapping[str, Decimal] | None,
    alternative_count: int,
    legal_alternative_count: int,
    excluded_item_id: int | None = None,
    excluded_reason_codes: tuple[str, ...] = (),
    excluded_metrics: Mapping[str, Decimal] | None = None,
) -> SlotRunnerUp:
    """Build one item slot's runner-up record from its already-evaluated candidates.

    :param priority_metrics: Metrics the branch's own selection rule ranks by.
    :param minimize_metrics: Priority metrics for which a lower value is preferred.
    :param selected_metrics: Engine metric vector for the winning full build.
    :param runner_up_item_id: Best legal, gate-passing alternative for this slot,
        or ``None`` when no such alternative exists.
    :param runner_up_metrics: Engine metric vector for the runner-up full build.
    :param alternative_count: Legal, gate-passing alternatives considered for this slot.
    :param legal_alternative_count: Legal alternatives considered before the branch's
        own gate, so a UI can distinguish "no other item could go here" from
        "other items existed but none passed this branch's own admissibility gate".
    :param excluded_item_id: Best legal item that failed the branch's own gate,
        when ``runner_up_item_id`` is ``None`` because of that gate rather than
        because no legal alternative exists at all.
    :param excluded_reason_codes: Which specific gate condition ``excluded_item_id``
        failed.
    :param excluded_metrics: Engine metric vector for ``excluded_item_id``'s build.
    :return: Structured per-slot comparison suitable for deterministic UI rendering.
    """

    if runner_up_item_id is not None and runner_up_metrics is not None:
        comparisons = _metric_comparisons(
            priority_metrics, minimize_metrics, selected_metrics, runner_up_metrics
        )
        return SlotRunnerUp(
            runner_up_item_id, alternative_count, legal_alternative_count, comparisons
        )
    excluded_comparisons = (
        _metric_comparisons(priority_metrics, minimize_metrics, selected_metrics, excluded_metrics)
        if excluded_item_id is not None and excluded_metrics is not None
        else ()
    )
    return SlotRunnerUp(
        None,
        alternative_count,
        legal_alternative_count,
        (),
        excluded_item_id,
        excluded_reason_codes,
        excluded_comparisons,
    )


def build_explanation(
    *,
    policy_id: str,
    reason_codes: tuple[str, ...],
    satisfied_constraints: tuple[str, ...],
    priority_metrics: tuple[str, ...],
    minimize_metrics: tuple[str, ...] = (),
    selected_item_ids: tuple[int, ...],
    selected_metrics: Mapping[str, Decimal],
    items_by_id: Mapping[int, Mapping[str, object]],
    comparison_kind: str | None = None,
    comparison_item_ids: tuple[int, ...] = (),
    comparison_metrics: Mapping[str, Decimal] | None = None,
    slot_runner_ups: tuple[SlotRunnerUp | None, ...] = (),
) -> BuildExplanation:
    """Build an explanation exclusively from selection and item-engine inputs.

    :param policy_id: Branch selection policy key recorded in the audit output.
    :param reason_codes: Ordered conclusions supported by the selection trace.
    :param satisfied_constraints: Hard gates that the selected candidate passed.
    :param priority_metrics: Metrics used to rank the branch in descending priority.
    :param minimize_metrics: Priority metrics for which a lower value is preferred.
    :param selected_item_ids: Ordered items owned by the selected candidate.
    :param selected_metrics: Engine metric vector belonging to the selected candidate.
    :param items_by_id: Loaded item documents keyed by Riot identifier.
    :param comparison_kind: Meaning of the optional reference candidate.
    :param comparison_item_ids: Ordered item path of the reference candidate.
    :param comparison_metrics: Engine metric vector belonging to the reference candidate.
    :param slot_runner_ups: Optional per-item runner-up, parallel to ``selected_item_ids``.
    :return: Structured explanation suitable for deterministic UI rendering.
    """

    comparisons = ()
    if comparison_metrics is not None:
        comparisons = tuple(
            MetricComparison(
                metric_id,
                "MINIMIZE" if metric_id in minimize_metrics else "MAXIMIZE",
                selected_metrics[metric_id],
                comparison_metrics[metric_id],
                selected_metrics[metric_id] - comparison_metrics[metric_id],
            )
            for metric_id in priority_metrics
            if metric_id in selected_metrics and metric_id in comparison_metrics
        )
    contributions = tuple(
        item_contribution(items_by_id[item_id]) for item_id in selected_item_ids
    )
    if slot_runner_ups:
        contributions = tuple(
            replace(contribution, slot_runner_up=slot_runner_ups[index])
            if index < len(slot_runner_ups)
            else contribution
            for index, contribution in enumerate(contributions)
        )
    return BuildExplanation(
        policy_id,
        tuple(reason_codes),
        tuple(satisfied_constraints),
        tuple(priority_metrics),
        comparison_kind,
        tuple(comparison_item_ids),
        comparisons,
        contributions,
    )
