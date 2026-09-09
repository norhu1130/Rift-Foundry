from decimal import Decimal

from lol_build.recommendation.feasibility import defense_candidate_is_feasible
from lol_build.recommendation.selection import (
    BranchId,
    EvaluatedCandidate,
    SelectionPolicy,
    epsilon_pareto_frontier,
    select_three_branches,
)


def _candidate(
    id: str,
    *,
    primary: str,
    offense: str,
    defense: str,
    horizon: str,
    cost: str = "3000",
    kill: bool = False,
    item_id: int = 1,
) -> EvaluatedCandidate:
    return EvaluatedCandidate(
        id,
        (item_id,),
        {
            "PRIMARY": Decimal(primary),
            "OFFENSE": Decimal(offense),
            "DEFENSE": Decimal(defense),
            "HORIZON_DAMAGE": Decimal(horizon),
            "COST": Decimal(cost),
        },
        kill,
        int(cost),
        1,
    )


def _policy(epsilon: str = "0") -> SelectionPolicy:
    return SelectionPolicy(
        maximize=("PRIMARY", "OFFENSE", "DEFENSE", "HORIZON_DAMAGE"),
        minimize=("COST",),
        epsilons={
            "PRIMARY": Decimal(epsilon),
            "OFFENSE": Decimal(epsilon),
            "DEFENSE": Decimal(epsilon),
            "HORIZON_DAMAGE": Decimal(epsilon),
            "COST": Decimal(0),
        },
        primary_metric="PRIMARY",
        offense_metric="OFFENSE",
        defense_metric="DEFENSE",
        kill_fallback_metric="HORIZON_DAMAGE",
        defense_max_primary_loss_fraction=Decimal("0.10"),
    )


def test_kill_gate_applies_only_to_default_and_offense() -> None:
    killer = _candidate(
        "killer", primary="100", offense="120", defense="80", horizon="110", kill=True
    )
    tank = _candidate("tank", primary="95", offense="90", defense="200", horizon="80", item_id=2)

    result = select_three_branches((killer, tank), _policy())

    assert result.branches[BranchId.DEFAULT].selected.id == "killer"
    assert result.branches[BranchId.OFFENSE].selected.id == "killer"
    assert result.branches[BranchId.DEFAULT].kill_gate_applied is True
    assert result.branches[BranchId.DEFENSE].selected.id == "tank"
    assert result.branches[BranchId.DEFENSE].kill_gate_applied is False


def test_no_kill_keeps_all_and_uses_horizon_damage_fallback() -> None:
    primary = _candidate("primary", primary="120", offense="100", defense="100", horizon="80")
    horizon = _candidate(
        "horizon", primary="110", offense="90", defense="110", horizon="150", item_id=2
    )

    result = select_three_branches((primary, horizon), _policy())

    assert result.branches[BranchId.DEFAULT].selected.id == "horizon"
    assert result.branches[BranchId.OFFENSE].selected.id == "horizon"
    assert result.branches[BranchId.DEFAULT].kill_gate_fallback is True
    assert set(result.branches[BranchId.DEFAULT].pareto_frontier_ids) == {
        "primary",
        "horizon",
    }


def test_defense_branch_enforces_relative_primary_loss_limit() -> None:
    baseline = _candidate("baseline", primary="100", offense="100", defense="100", horizon="100")
    legal_defense = _candidate(
        "legal", primary="90", offense="90", defense="140", horizon="90", item_id=2
    )
    excessive_loss = _candidate(
        "too_slow", primary="89", offense="80", defense="300", horizon="80", item_id=3
    )

    result = select_three_branches((baseline, legal_defense, excessive_loss), _policy())

    defense = result.branches[BranchId.DEFENSE]
    assert defense.selected.id == "legal"
    assert "too_slow" not in defense.pareto_frontier_ids


def test_epsilon_pareto_and_tie_breaking_are_deterministic() -> None:
    cheaper = _candidate(
        "z_cheaper",
        primary="100",
        offense="100",
        defense="100",
        horizon="100",
        cost="3000",
        item_id=9,
    )
    near = _candidate(
        "a_near",
        primary="100.5",
        offense="100",
        defense="100",
        horizon="100",
        cost="3000",
        item_id=1,
    )
    dominated = _candidate(
        "dominated",
        primary="90",
        offense="90",
        defense="90",
        horizon="90",
        cost="3100",
        item_id=2,
    )

    frontier = epsilon_pareto_frontier((cheaper, dominated, near), _policy("1"))
    assert [candidate.id for candidate in frontier] == ["a_near", "z_cheaper"]

    tie_left = _candidate(
        "z_tie", primary="100", offense="100", defense="100", horizon="100", item_id=9
    )
    tie_right = _candidate(
        "a_tie", primary="100", offense="100", defense="100", horizon="100", item_id=1
    )
    result = select_three_branches((tie_left, tie_right), _policy())
    assert result.branches[BranchId.DEFAULT].selected.id == "a_tie"

    reversed_result = select_three_branches((tie_right, tie_left), _policy())
    assert reversed_result.branches[BranchId.DEFAULT] == result.branches[BranchId.DEFAULT]


def test_defense_label_requires_every_semantic_gate() -> None:
    metrics = {"DAMAGE_TOTAL_8S": Decimal(80)}
    inputs = {
        "primary_metric": "DAMAGE_TOTAL_8S",
        "best_primary": Decimal(100),
        "maximum_primary_loss_fraction": Decimal("0.20"),
        "all_core_engage_ready": True,
        "all_core_chassis_ready": True,
        "all_core_item_passives_ready": True,
    }

    assert defense_candidate_is_feasible(metrics, **inputs)
    assert not defense_candidate_is_feasible(
        metrics,
        **{**inputs, "all_core_engage_ready": False},
    )
    assert not defense_candidate_is_feasible(
        {"DAMAGE_TOTAL_8S": Decimal("79.99")},
        **inputs,
    )
