import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from lol_build.scenarios.measurement import (
    MeasurementError,
    MeasurementStatus,
    assess_blind_measurement,
)

ROOT = Path(__file__).resolve().parents[1]
PENDING = json.loads((ROOT / "fixtures/measurements/cc_blind_16.17.1.pending.json").read_text())
SCHEMA = json.loads((ROOT / "schemas/cc-measurement.schema.json").read_text())


def _completed() -> dict:
    document = deepcopy(PENDING)
    document["status"] = "COMPLETED"
    document["capture_refs"] = ["captures/blind-test.mp4"]
    document["observed_at"] = "2026-09-07T11:30:00+09:00"
    document["review"] = {
        "reviewer": "human-reviewer",
        "reviewed_at": "2026-09-07T12:00:00+09:00",
        "approved": True,
        "notes": "Synthetic structural test only.",
    }
    for case in document["cases"]:
        if case["id"] in {"B0", "B1", "B5"}:
            frames = {"B0": 180, "B1": 126, "B5": 180}[case["id"]]
            case["observations"] = [
                {"start_frame": index * 300, "end_frame": index * 300 + frames, "fps": 60}
                for index in range(5)
            ]
        else:
            case["observations"] = [{"outcome": True} for _ in range(5)]
    return document


def test_pending_fixture_is_valid_and_cannot_generate_values() -> None:
    validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    assert list(validator.iter_errors(PENDING)) == []
    result = assess_blind_measurement(PENDING)
    assert result.status is MeasurementStatus.PENDING
    assert result.interaction_values is None
    assert result.auxiliary_values is None


def test_completed_measurement_derives_all_five_interactions() -> None:
    document = _completed()
    validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    assert list(validator.iter_errors(document)) == []

    result = assess_blind_measurement(document)

    assert result.status is MeasurementStatus.READY_FOR_EVIDENCE_CHAIN
    assert result.interaction_values == {
        "tenacity_reducible": True,
        "cleanse_removable": True,
        "qss_removable": True,
        "immunity_resistible": True,
        "slow_resistance_applies": False,
    }
    assert result.auxiliary_values == {"blinded_attack_grants_jax_passive_stack": True}
    assert result.blockers == ("SUBSEQUENT_CHANGE_SCAN_REQUIRED",)


def test_disagreement_and_one_frame_ambiguity_block_derivation() -> None:
    disagreement = _completed()
    disagreement["cases"][2]["observations"][0]["outcome"] = False
    with pytest.raises(MeasurementError, match="outcomes disagree"):
        assess_blind_measurement(disagreement)

    ambiguous = _completed()
    for observation in ambiguous["cases"][1]["observations"]:
        observation["end_frame"] = observation["start_frame"] + 179
    with pytest.raises(MeasurementError, match="one-frame ambiguity"):
        assess_blind_measurement(ambiguous)
