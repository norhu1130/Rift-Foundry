import copy
import json
from pathlib import Path
from typing import Any

import pytest

from lol_build.scenarios.validation import (
    ScenarioValidationError,
    validate_scenario,
    validate_scenario_document,
)

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_PATH = ROOT / "fixtures/scenarios/duel_jax_l13_8s_vs_teemo_blind_v1.json"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _set_path(document: Any, path: list[str | int], value: Any) -> None:
    cursor = document
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = value


def test_first_scenario_is_structurally_and_semantically_valid() -> None:
    scenario = validate_scenario(SCENARIO_PATH, root=ROOT)

    assert scenario["id"] == "duel_jax_l13_8s_vs_teemo_blind_v1"
    assert scenario["verification"]["status"] == "UNVERIFIED"


@pytest.mark.parametrize("failure", _load(ROOT / "tests/fixtures/scenario_failures.json"))
def test_semantic_failure_fixtures_report_json_path(failure: dict[str, Any]) -> None:
    scenario = copy.deepcopy(_load(SCENARIO_PATH))
    _set_path(scenario, failure["path"], failure["value"])

    with pytest.raises(ScenarioValidationError, match=failure["error"]):
        validate_scenario_document(scenario, root=ROOT)


def test_verified_scenario_rejects_unverified_blind_mechanic() -> None:
    scenario = _load(SCENARIO_PATH)
    scenario["verification"]["status"] = "VERIFIED"
    scenario["verification"]["verified_patch"] = "16.17.1"

    with pytest.raises(ScenarioValidationError, match="unverified mechanic"):
        validate_scenario_document(scenario, root=ROOT)
