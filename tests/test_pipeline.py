import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from lol_build.core.canonical import dumps
from lol_build.recommendation.readiness import (
    RecommendationStatus,
    assess_release_readiness,
    readiness_document,
)

ROOT = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text())


def _documents() -> tuple[dict, dict, dict[str, dict], list[dict]]:
    scenario = _load("fixtures/scenarios/duel_jax_l13_8s_vs_teemo_blind_v1.json")
    champion = _load("data/curated/champions/24.json")
    mechanics = {
        fact["id"]: fact
        for path in sorted((ROOT / "data/curated/mechanics").glob("*.json"))
        for fact in [json.loads(path.read_text())]
    }
    items = [
        json.loads(path.read_text())
        for path in sorted((ROOT / "data/curated/items").glob("*.json"))
    ]
    return scenario, champion, mechanics, items


def test_locked_workspace_reports_evidence_blockers_in_stable_order() -> None:
    result = readiness_document(ROOT)

    assert result.recommendation_status is RecommendationStatus.INSUFFICIENT_EVIDENCE
    assert [blocker.code for blocker in result.blockers[:3]] == [
        "SCENARIO_UNVERIFIED",
        "CHAMPION_PROFILE_UNVERIFIED",
        "MECHANIC_UNVERIFIED",
    ]
    assert [blocker.ref for blocker in result.blockers if blocker.code == "ITEM_UNVERIFIED"] == [
        "3053",
        "3071",
        "3111",
        "3115",
        "3153",
        "4633",
        "6665",
    ]
    assert dumps(asdict(result)) == dumps(asdict(readiness_document(ROOT)))


def test_all_verified_dependencies_make_pipeline_ready() -> None:
    scenario, champion, mechanics, items = _documents()
    scenario["verification"] = {
        "status": "VERIFIED",
        "verified_patch": "16.17.1",
        "evidence_refs": ["synthetic-test"],
    }
    champion["verification"]["status"] = "VERIFIED"
    for fact in mechanics.values():
        fact["verification"]["status"] = "VERIFIED"
    for item in items:
        item["verification"]["status"] = "VERIFIED"

    result = assess_release_readiness(
        scenario=scenario,
        champion_profile=champion,
        mechanic_facts=mechanics,
        items=items,
    )

    assert result.recommendation_status is RecommendationStatus.READY
    assert result.blockers == ()


def test_unsupported_scenario_is_not_mislabeled_as_no_item_solution() -> None:
    scenario, champion, mechanics, items = _documents()
    outside = deepcopy(scenario)
    outside["encounter"]["target_count"] = 2

    result = assess_release_readiness(
        scenario=outside,
        champion_profile=champion,
        mechanic_facts=mechanics,
        items=items,
    )

    assert result.recommendation_status is RecommendationStatus.OUT_OF_SCOPE
    assert result.recommendation_status is not RecommendationStatus.NO_FEASIBLE_ITEM_RESPONSE


def test_readiness_checks_only_the_requested_item_pool() -> None:
    result = readiness_document(ROOT, item_ids={3115})

    item_blockers = [
        blocker.ref for blocker in result.blockers if blocker.code == "ITEM_UNVERIFIED"
    ]
    assert item_blockers == ["3115"]


def test_readiness_can_select_darius_garen_slice() -> None:
    result = readiness_document(
        ROOT,
        item_ids={3053, 3071},
        scenario_path=Path("fixtures/scenarios/duel_darius_l13_8s_vs_garen_v1.json"),
        champion_path=Path("data/curated/champions/122.json"),
    )

    assert result.scope.actor_champion_id == 122
    assert result.recommendation_status is RecommendationStatus.INSUFFICIENT_EVIDENCE
    assert any(blocker.ref == "cc_silence_v1" for blocker in result.blockers)
