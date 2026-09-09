"""Shared hard gates for semantically valid recommendation branches."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal


def defense_candidate_is_feasible(
    metrics: Mapping[str, Decimal],
    *,
    primary_metric: str,
    best_primary: Decimal,
    maximum_primary_loss_fraction: Decimal,
    all_core_engage_ready: bool,
    all_core_chassis_ready: bool,
    all_core_item_passives_ready: bool,
) -> bool:
    """Require readiness and a bounded primary-metric loss for a defense label.

    :param metrics: Candidate metric vector containing the branch primary metric.
    :param primary_metric: Damage or utility metric protected by the loss limit.
    :param best_primary: Highest primary value observed across legal candidates.
    :param maximum_primary_loss_fraction: Largest accepted relative loss from the best value.
    :param all_core_engage_ready: Whether every build prefix reaches combat.
    :param all_core_chassis_ready: Whether every build prefix passes its durability floor.
    :param all_core_item_passives_ready: Whether conditional core passives are active.
    :return: Whether the candidate may truthfully carry the defense branch label.
    """

    if not Decimal(0) <= maximum_primary_loss_fraction <= Decimal(1):
        raise ValueError("maximum_primary_loss_fraction must be within [0, 1]")
    minimum_primary = best_primary * (Decimal(1) - maximum_primary_loss_fraction)
    return (
        all_core_engage_ready
        and all_core_chassis_ready
        and all_core_item_passives_ready
        and metrics[primary_metric] >= minimum_primary
    )
