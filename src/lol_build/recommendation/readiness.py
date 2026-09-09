"""Release-readiness gate for the offline recommendation pipeline."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence, Set
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from lol_build.core.canonical import dumps
from lol_build.scenarios.validation import validate_scenario


class RecommendationStatus(StrEnum):
    """State whether a recommendation is usable, unsupported, or evidence-blocked."""

    READY = "READY"
    NO_FEASIBLE_ITEM_RESPONSE = "NO_FEASIBLE_ITEM_RESPONSE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


@dataclass(frozen=True)
class RecommendationScope:
    """Identify the exact patch, actor, encounter, and build horizon being judged."""

    scenario_id: str
    game_patch: str
    actor_champion_id: int
    encounter_duration_ms: int
    target_count: int
    max_core_count: int


@dataclass(frozen=True)
class ReadinessBlocker:
    """Identify one evidence or schema condition preventing release."""

    code: str
    ref: str
    observed_status: str


@dataclass(frozen=True)
class PipelineReadiness:
    """Summarize recommendation status, scope, and release blockers."""

    recommendation_status: RecommendationStatus
    scope: RecommendationScope
    blockers: tuple[ReadinessBlocker, ...]


def assess_release_readiness(
    *,
    scenario: Mapping[str, Any],
    champion_profile: Mapping[str, Any],
    mechanic_facts: Mapping[str, Mapping[str, Any]],
    items: Sequence[Mapping[str, Any]],
) -> PipelineReadiness:
    """Refuse recommendation scoring until every numeric dependency is verified.

    :param scenario: Validated encounter assumptions governing the calculation.
    :param champion_profile: Mechanic-keyed champion profile checked for release readiness.
    :param mechanic_facts: Verified and unverified mechanic records required by the scenario.
    :param items: Curated item records whose verification state affects release eligibility.
    :return: Readiness status and blockers for the requested recommendation scope.
    """

    scope = RecommendationScope(
        scenario["id"],
        scenario["patch"]["game_patch"],
        scenario["actor"]["champion_id"],
        scenario["encounter"]["duration_ms"],
        scenario["encounter"]["target_count"],
        3,
    )
    unsupported = (
        scope.target_count != 1
        or scenario["encounter"]["execution_model"] != "DETERMINISTIC_ROTATION"
        or scope.encounter_duration_ms != champion_profile["rotation"]["duration_ms"]
    )
    if unsupported:
        return PipelineReadiness(
            RecommendationStatus.OUT_OF_SCOPE,
            scope,
            (ReadinessBlocker("UNSUPPORTED_SCENARIO", scenario["id"], "OUT_OF_SCOPE"),),
        )

    blockers: list[ReadinessBlocker] = []
    scenario_status = scenario["verification"]["status"]
    if scenario_status != "VERIFIED":
        blockers.append(ReadinessBlocker("SCENARIO_UNVERIFIED", scenario["id"], scenario_status))
    champion_status = champion_profile["verification"]["status"]
    if champion_status != "VERIFIED":
        blockers.append(
            ReadinessBlocker("CHAMPION_PROFILE_UNVERIFIED", champion_profile["id"], champion_status)
        )

    mechanic_refs = sorted(
        {event["mechanic_ref"] for event in scenario["encounter"]["cc_profile"]["events"]}
    )
    for mechanic_ref in mechanic_refs:
        fact = mechanic_facts.get(mechanic_ref)
        status = "MISSING" if fact is None else fact["verification"]["status"]
        if status != "VERIFIED":
            blockers.append(ReadinessBlocker("MECHANIC_UNVERIFIED", mechanic_ref, status))
    for item in sorted(items, key=lambda value: value["id"]):
        status = item["verification"]["status"]
        if status != "VERIFIED":
            blockers.append(ReadinessBlocker("ITEM_UNVERIFIED", str(item["id"]), status))

    status = RecommendationStatus.INSUFFICIENT_EVIDENCE if blockers else RecommendationStatus.READY
    return PipelineReadiness(status, scope, tuple(blockers))


def _load(path: Path) -> dict[str, Any]:
    """Read one local JSON object used by the readiness gate.

    :param path: JSON file to read.
    :return: Parsed JSON object from ``path``.
    """

    return json.loads(path.read_text(encoding="utf-8"))


def readiness_document(
    root: Path,
    *,
    item_ids: Set[int] | None = None,
    scenario_path: Path | None = None,
    champion_path: Path | None = None,
) -> PipelineReadiness:
    """Build the canonical release-readiness document.

    :param root: Project root containing locked data and curated records.
    :param item_ids: Ordered Riot item identifiers in the build.
    :param scenario_path: Path to the validated encounter scenario JSON.
    :param champion_path: Path to the mechanic-keyed champion profile JSON.
    :return: Readiness assessment built from the referenced scenario and champion.
    """

    if scenario_path is None:
        scenario_path = root / "fixtures/scenarios/duel_jax_l13_8s_vs_teemo_blind_v1.json"
    elif not scenario_path.is_absolute():
        scenario_path = root / scenario_path
    if champion_path is None:
        champion_path = root / "data/curated/champions/24.json"
    elif not champion_path.is_absolute():
        champion_path = root / champion_path
    scenario = validate_scenario(scenario_path, root=root)
    champion = _load(champion_path)
    if champion["champion_id"] != scenario["actor"]["champion_id"]:
        raise ValueError("champion profile does not match scenario actor")
    mechanics = {
        fact["id"]: fact
        for path in sorted((root / "data/curated/mechanics").glob("*.json"))
        for fact in [_load(path)]
    }
    items = [
        item
        for path in sorted((root / "data/curated/items").glob("*.json"))
        for item in [_load(path)]
        if item_ids is None or item["id"] in item_ids
    ]
    return assess_release_readiness(
        scenario=scenario,
        champion_profile=champion,
        mechanic_facts=mechanics,
        items=items,
    )


def main() -> None:
    """Run the module command-line interface.

    :return: None.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--scenario", type=Path)
    parser.add_argument("--champion", type=Path)
    args = parser.parse_args()
    print(
        dumps(
            asdict(
                readiness_document(
                    args.root.resolve(),
                    scenario_path=args.scenario,
                    champion_path=args.champion,
                )
            )
        )
    )


if __name__ == "__main__":
    main()
