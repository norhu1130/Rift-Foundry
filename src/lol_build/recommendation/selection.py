"""Epsilon-Pareto filtering and deterministic three-branch selection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class SelectionError(ValueError):
    """Raised when selection inputs do not define a comparable candidate set."""


class BranchId(StrEnum):
    """Name the default, offense-biased, and defense-biased recommendation branches."""

    DEFAULT = "DEFAULT"
    OFFENSE = "OFFENSE"
    DEFENSE = "DEFENSE"


@dataclass(frozen=True)
class EvaluatedCandidate:
    """Describe one evaluated candidate considered by the recommendation engine."""

    id: str
    item_ids: tuple[int, ...]
    metrics: Mapping[str, Decimal]
    kill_threshold_met: bool
    total_gold: int
    occupied_slots: int


@dataclass(frozen=True)
class SelectionPolicy:
    """Configure vector objectives, tolerances, kill gating, and branch rank axes."""

    maximize: tuple[str, ...]
    minimize: tuple[str, ...]
    epsilons: Mapping[str, Decimal]
    primary_metric: str
    offense_metric: str
    defense_metric: str
    kill_fallback_metric: str
    defense_max_primary_loss_fraction: Decimal
    kill_gate_enabled: bool = True


@dataclass(frozen=True)
class BranchSelection:
    """Record the selected candidate and its Pareto/kill-gate context."""

    branch: BranchId
    selected: EvaluatedCandidate
    pareto_frontier_ids: tuple[str, ...]
    kill_gate_applied: bool
    kill_gate_fallback: bool
    rank_metric: str


@dataclass(frozen=True)
class SelectionResult:
    """Map every required branch to its chosen candidate and audit metadata."""

    branches: Mapping[BranchId, BranchSelection]


def _validate(candidates: tuple[EvaluatedCandidate, ...], policy: SelectionPolicy) -> None:
    """Reject candidate sets that cannot be compared under the selection policy.

    :param candidates: Evaluated build candidates eligible for selection.
    :param policy: Selection policy defining maximized metrics and epsilon tolerances.
    :return: None.
    """

    if not candidates:
        raise SelectionError("at least one candidate is required")
    if len({candidate.id for candidate in candidates}) != len(candidates):
        raise SelectionError("candidate IDs must be unique")
    objective_metrics = set(policy.maximize) | set(policy.minimize)
    if not policy.maximize:
        raise SelectionError("at least one maximize metric is required")
    if set(policy.maximize) & set(policy.minimize):
        raise SelectionError("a metric cannot be both maximized and minimized")
    rank_metrics = {
        policy.primary_metric,
        policy.offense_metric,
        policy.defense_metric,
        policy.kill_fallback_metric,
    }
    if not rank_metrics <= set(policy.maximize):
        raise SelectionError("branch rank metrics must be maximize objectives")
    if set(policy.epsilons) != objective_metrics:
        raise SelectionError("epsilons must exactly cover objective metrics")
    if any(not value.is_finite() or value < 0 for value in policy.epsilons.values()):
        raise SelectionError("epsilons must be finite and non-negative")
    loss = policy.defense_max_primary_loss_fraction
    if not loss.is_finite() or not Decimal(0) <= loss <= Decimal(1):
        raise SelectionError("defense primary loss fraction must be within [0, 1]")
    for candidate in candidates:
        if set(candidate.metrics) != objective_metrics:
            raise SelectionError(f"candidate {candidate.id!r} has an incompatible metric vector")
        if any(not value.is_finite() for value in candidate.metrics.values()):
            raise SelectionError(f"candidate {candidate.id!r} has a non-finite metric")


def _epsilon_dominates(
    left: EvaluatedCandidate,
    right: EvaluatedCandidate,
    policy: SelectionPolicy,
) -> bool:
    """Test epsilon-aware Pareto dominance between candidates.

    :param left: Candidate tested as the possible Pareto dominator.
    :param right: Candidate tested for domination by ``left``.
    :param policy: Selection policy defining maximized metrics and epsilon tolerances.
    :return: Whether ``left`` is no worse within epsilon and strictly better on one axis.
    """

    no_worse = True
    strictly_better = False
    for metric in policy.maximize:
        epsilon = policy.epsilons[metric]
        no_worse &= left.metrics[metric] >= right.metrics[metric] - epsilon
        strictly_better |= left.metrics[metric] > right.metrics[metric] + epsilon
    for metric in policy.minimize:
        epsilon = policy.epsilons[metric]
        no_worse &= left.metrics[metric] <= right.metrics[metric] + epsilon
        strictly_better |= left.metrics[metric] < right.metrics[metric] - epsilon
    return no_worse and strictly_better


def epsilon_pareto_frontier(
    candidates: tuple[EvaluatedCandidate, ...], policy: SelectionPolicy
) -> tuple[EvaluatedCandidate, ...]:
    """Return candidates not epsilon-dominated by another candidate.

    :param candidates: Evaluated build candidates eligible for selection.
    :param policy: Selection policy defining maximized metrics and epsilon tolerances.
    :return: Candidates not epsilon-dominated on every configured metric.
    """

    _validate(candidates, policy)
    frontier = (
        candidate
        for candidate in candidates
        if not any(
            other.id != candidate.id and _epsilon_dominates(other, candidate, policy)
            for other in candidates
        )
    )
    return tuple(sorted(frontier, key=lambda candidate: candidate.id))


def _rank(candidates: tuple[EvaluatedCandidate, ...], metric: str) -> EvaluatedCandidate:
    """Choose the metric leader with deterministic cost and identity tie-breakers.

    :param candidates: Evaluated build candidates eligible for selection.
    :param metric: Metric name used for deterministic candidate ordering.
    :return: Highest-ranked candidate with deterministic ID tie-breaking.
    """

    return min(
        candidates,
        key=lambda candidate: (
            -candidate.metrics[metric],
            candidate.total_gold,
            candidate.occupied_slots,
            candidate.item_ids,
            candidate.id,
        ),
    )


def _offensive_branch(
    branch: BranchId,
    candidates: tuple[EvaluatedCandidate, ...],
    policy: SelectionPolicy,
    normal_rank_metric: str,
) -> BranchSelection:
    """Select the offensive branch from a Pareto frontier.

    :param branch: Recommendation branch being constructed or labeled.
    :param candidates: Evaluated build candidates eligible for selection.
    :param policy: Selection policy defining maximized metrics and epsilon tolerances.
    :param normal_rank_metric: Fallback metric used when the kill threshold is not met.
    :return: Offensive selection with kill-gate and frontier audit metadata.
    """

    gated = candidates
    gate_applied = False
    gate_fallback = False
    rank_metric = normal_rank_metric
    if policy.kill_gate_enabled:
        killers = tuple(candidate for candidate in candidates if candidate.kill_threshold_met)
        if killers:
            gated = killers
            gate_applied = True
        else:
            gate_fallback = True
            rank_metric = policy.kill_fallback_metric
    frontier = epsilon_pareto_frontier(gated, policy)
    return BranchSelection(
        branch,
        _rank(frontier, rank_metric),
        tuple(candidate.id for candidate in frontier),
        gate_applied,
        gate_fallback,
        rank_metric,
    )


def select_three_branches(
    candidates: tuple[EvaluatedCandidate, ...], policy: SelectionPolicy
) -> SelectionResult:
    """Select default, offense, and defense branches without scalarizing vectors.

    :param candidates: Evaluated build candidates eligible for selection.
    :param policy: Selection policy defining maximized metrics and epsilon tolerances.
    :return: Default, offense, and defense selections with their audit context.
    """

    _validate(candidates, policy)
    default = _offensive_branch(BranchId.DEFAULT, candidates, policy, policy.primary_metric)
    offense = _offensive_branch(BranchId.OFFENSE, candidates, policy, policy.offense_metric)

    best_primary = max(candidate.metrics[policy.primary_metric] for candidate in candidates)
    if best_primary <= 0:
        raise SelectionError("relative defense loss requires a positive best primary metric")
    minimum_primary = best_primary * (Decimal(1) - policy.defense_max_primary_loss_fraction)
    defense_eligible = tuple(
        candidate
        for candidate in candidates
        if candidate.metrics[policy.primary_metric] >= minimum_primary
    )
    defense_frontier = epsilon_pareto_frontier(defense_eligible, policy)
    defense = BranchSelection(
        BranchId.DEFENSE,
        _rank(defense_frontier, policy.defense_metric),
        tuple(candidate.id for candidate in defense_frontier),
        False,
        False,
        policy.defense_metric,
    )
    return SelectionResult(
        {
            BranchId.DEFAULT: default,
            BranchId.OFFENSE: offense,
            BranchId.DEFENSE: defense,
        }
    )
