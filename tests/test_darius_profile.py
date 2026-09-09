import json
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "data/curated/champions/122.json"


def test_darius_profile_matches_shared_champion_schema() -> None:
    schema = json.loads((ROOT / "schemas/champion-profile.schema.json").read_text())
    profile = json.loads(PROFILE_PATH.read_text())

    assert list(Draft202012Validator(schema).iter_errors(profile)) == []
    assert profile["rotation"]["id"] == "rotation_darius_five_stack_execute_8s_v1"
    assert profile["mechanic_parameters"]["execute_stack_multiplier"] == {
        "damage_increase_per_stack": "0.2",
        "max_stacks": 5,
        "source_ref": "data/raw/16.17.1/communitydragon/champions/darius.bin.json",
    }


def test_darius_ranked_damage_values_match_locked_records() -> None:
    profile = json.loads(PROFILE_PATH.read_text())
    abilities = {ability["id"]: ability for ability in profile["abilities"]}

    assert abilities["Q_OUTER_DAMAGE"]["base_damage_by_rank"] == ["50", "80", "110", "140", "170"]
    assert Decimal(abilities["R_EXECUTE_DAMAGE"]["scalings"][0]["coefficient"]) == Decimal("0.75")
    assert profile["verification"]["status"] == "CURATED_UNVERIFIED"
