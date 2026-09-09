import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/mechanic-fact.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def _record(name: str) -> dict:
    path = ROOT / f"data/curated/mechanics/{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_initial_mechanic_records_are_structurally_valid() -> None:
    for name in ("blind", "stun", "slow"):
        assert list(VALIDATOR.iter_errors(_record(name))) == []


def test_every_initial_interaction_is_explicitly_unverified() -> None:
    for name in ("blind", "stun", "slow"):
        for interaction in _record(name)["interactions"].values():
            assert interaction == {"status": "UNVERIFIED", "value": None}


def test_verified_record_cannot_contain_unknown_interaction() -> None:
    record = copy.deepcopy(_record("blind"))
    record["verification"] = {
        "status": "VERIFIED",
        "verified_patch": "16.17.1",
        "last_change_evidence": {
            "title": "Example",
            "url": "https://example.invalid/change",
            "published_at": "2026-01-01",
            "supports": "Example evidence for structural testing only.",
        },
        "subsequent_change_scan": {
            "from_patch_exclusive": "16.1",
            "through_patch": "16.17.1",
            "completed_at": "2026-09-06T20:42:51Z",
            "queries": ["example"],
            "result": "NO_RELEVANT_CHANGE_FOUND",
        },
        "measurements": [
            {
                "game_patch": "16.17.1",
                "environment": "CUSTOM_GAME",
                "procedure_ref": "tests/manual/example.md",
                "observed_at": "2026-09-06T20:42:51Z",
                "result_ref": "results/example.json",
            }
        ],
        "notes": "Structural test record.",
    }

    errors = list(VALIDATOR.iter_errors(record))
    assert errors
    assert any("tenacity_reducible" in error.absolute_path for error in errors)


def test_unverified_interaction_cannot_smuggle_a_false_value() -> None:
    record = copy.deepcopy(_record("blind"))
    record["interactions"]["tenacity_reducible"]["value"] = False

    errors = list(VALIDATOR.iter_errors(record))
    assert errors
    assert any("tenacity_reducible" in error.absolute_path for error in errors)
