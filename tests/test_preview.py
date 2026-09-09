from dataclasses import asdict
from pathlib import Path

from lol_build.application.on_hit_preview import synthetic_preview_document
from lol_build.core.canonical import dumps
from lol_build.recommendation.readiness import RecommendationStatus
from lol_build.recommendation.selection import BranchId
from lol_build.simulation.on_hit import MissStackPolicy

ROOT = Path(__file__).resolve().parents[1]


def test_synthetic_preview_connects_three_branches_without_release_eligibility() -> None:
    result = synthetic_preview_document(ROOT)

    assert result.recommendation_status is RecommendationStatus.INSUFFICIENT_EVIDENCE
    assert result.preview_kind == "SYNTHETIC_NON_RELEASE"
    assert result.release_eligible is False
    assert set(result.branches) == {BranchId.DEFAULT, BranchId.OFFENSE, BranchId.DEFENSE}
    assert all(len(branch.item_ids) == 3 for branch in result.branches.values())
    assert all(not branch.provenance.release_eligible for branch in result.branches.values())
    assert result.branches[BranchId.OFFENSE].item_ids[0] == 3115
    assert result.branches[BranchId.DEFENSE].item_ids[0] == 6665
    assert result.stable_across_miss_stack_policies is True
    assert (
        result.variant_branch_item_ids[MissStackPolicy.GRANTS_STACK]
        == result.variant_branch_item_ids[MissStackPolicy.DOES_NOT_GRANT_STACK]
    )


def test_synthetic_preview_is_byte_identical() -> None:
    first = synthetic_preview_document(ROOT)
    second = synthetic_preview_document(ROOT)

    assert dumps(asdict(first)) == dumps(asdict(second))
