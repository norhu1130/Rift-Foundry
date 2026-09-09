from copy import deepcopy
from pathlib import Path

import pytest

from lol_build.scenarios.validation import (
    ScenarioValidationError,
    validate_scenario,
    validate_scenario_document,
)

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "fixtures/scenarios/duel_darius_l13_8s_vs_garen_v1.json"


def test_darius_garen_scenario_is_locked_and_structurally_valid() -> None:
    scenario = validate_scenario(SCENARIO, root=ROOT)

    assert scenario["actor"]["champion_id"] == 122
    assert scenario["target"]["reproduction_recipe"]["champion_id"] == 86
    assert scenario["encounter"]["cc_profile"]["events"][0]["cc_type"] == "SILENCE"
    assert (
        scenario["encounter"]["target_defensive_windows"][0]["incoming_damage_multiplier"] == "0.75"
    )
    assert scenario["verification"]["status"] == "UNVERIFIED"


def test_darius_garen_defensive_window_must_fit_encounter() -> None:
    scenario = validate_scenario(SCENARIO, root=ROOT)
    invalid = deepcopy(scenario)
    invalid["encounter"]["target_defensive_windows"][0]["end_ms"] = 9000

    with pytest.raises(ScenarioValidationError, match="window must end within"):
        validate_scenario_document(invalid, root=ROOT)
