"""Semantic checks and derivation for client CC measurements."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from statistics import median
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from lol_build.buildtime.paths import repository_root
from lol_build.core.canonical import dumps


class MeasurementError(ValueError):
    """Raised when a completed measurement cannot support a fact."""


class MeasurementStatus(StrEnum):
    """Track whether client observations are absent or ready for evidence review."""

    PENDING = "PENDING"
    READY_FOR_EVIDENCE_CHAIN = "READY_FOR_EVIDENCE_CHAIN"


@dataclass(frozen=True)
class MeasurementAssessment:
    """Carry derived mechanic facts and blockers from one controlled client run."""

    status: MeasurementStatus
    interaction_values: Mapping[str, bool] | None
    auxiliary_values: Mapping[str, bool] | None
    blockers: tuple[str, ...]


_EXPECTED_CASES = {
    "B0": "baseline_duration",
    "B1": "tenacity_reducible",
    "B2": "cleanse_removable",
    "B3": "qss_removable",
    "B4": "immunity_resistible",
    "B5": "slow_resistance_applies",
    "B6": "blinded_attack_grants_jax_passive_stack",
}


def _duration_frames(case: Mapping[str, Any]) -> tuple[list[int], int]:
    """Convert measured CC duration into frame counts.

    :param case: Measurement fixture containing repeated client observations.
    :return: Individual duration-frame counts and their median.
    """

    observations = case["observations"]
    if len(observations) != 5:
        raise MeasurementError(f"{case['id']} requires exactly five observations")
    if any(set(observation) != {"start_frame", "end_frame", "fps"} for observation in observations):
        raise MeasurementError(f"{case['id']} requires frame observations")
    fps_values = {observation["fps"] for observation in observations}
    if len(fps_values) != 1:
        raise MeasurementError(f"{case['id']} observations must use one FPS")
    durations = []
    for observation in observations:
        duration = observation["end_frame"] - observation["start_frame"]
        if duration <= 0:
            raise MeasurementError(f"{case['id']} end frame must follow start frame")
        durations.append(duration)
    return durations, fps_values.pop()


def _consistent_boolean(case: Mapping[str, Any]) -> bool:
    """Return a boolean only when every observation agrees.

    :param case: Measurement fixture containing repeated client observations.
    :return: The unanimous observed outcome.
    """

    observations = case["observations"]
    if len(observations) != 5:
        raise MeasurementError(f"{case['id']} requires exactly five observations")
    if any(set(observation) != {"outcome"} for observation in observations):
        raise MeasurementError(f"{case['id']} requires boolean observations")
    values = {observation["outcome"] for observation in observations}
    if len(values) != 1:
        raise MeasurementError(f"{case['id']} outcomes disagree")
    return values.pop()


def assess_blind_measurement(document: Mapping[str, Any]) -> MeasurementAssessment:
    """Derive interaction booleans only from a complete, reviewed seven-case run.

    :param document: Parsed JSON document to validate or transform.
    :return: Derived mechanic facts, or a pending assessment when captures are absent.
    """

    if document["status"] == "PENDING_CLIENT_MEASUREMENT":
        return MeasurementAssessment(
            MeasurementStatus.PENDING,
            None,
            None,
            ("CLIENT_MEASUREMENT_MISSING",),
        )
    if document["status"] != "COMPLETED":
        raise MeasurementError("unknown measurement status")
    review = document.get("review")
    if not isinstance(review, Mapping) or review.get("approved") is not True:
        raise MeasurementError("completed measurement requires approved human review")
    if not document.get("capture_refs"):
        raise MeasurementError("completed measurement requires capture references")

    cases = {case["id"]: case for case in document["cases"]}
    if set(cases) != set(_EXPECTED_CASES) or any(
        cases[id]["interaction"] != interaction for id, interaction in _EXPECTED_CASES.items()
    ):
        raise MeasurementError("cases must exactly match the frozen B0-B6 mapping")

    baseline, baseline_fps = _duration_frames(cases["B0"])
    tenacity, tenacity_fps = _duration_frames(cases["B1"])
    slow_resistance, slow_fps = _duration_frames(cases["B5"])
    if {baseline_fps, tenacity_fps, slow_fps} != {baseline_fps}:
        raise MeasurementError("B0, B1, and B5 must use the same FPS")
    baseline_median = Decimal(median(baseline))
    tenacity_delta = baseline_median - Decimal(median(tenacity))
    slow_delta = abs(baseline_median - Decimal(median(slow_resistance)))
    if tenacity_delta < 0:
        raise MeasurementError("B1 is longer than baseline and cannot support a boolean fact")
    if Decimal(0) < tenacity_delta <= Decimal(1):
        raise MeasurementError("B1 duration difference is within one-frame ambiguity")
    if Decimal(0) < slow_delta <= Decimal(1):
        raise MeasurementError("B5 duration difference is within one-frame ambiguity")

    values = {
        "tenacity_reducible": tenacity_delta > 1,
        "cleanse_removable": _consistent_boolean(cases["B2"]),
        "qss_removable": _consistent_boolean(cases["B3"]),
        "immunity_resistible": _consistent_boolean(cases["B4"]),
        "slow_resistance_applies": slow_delta > 1,
    }
    return MeasurementAssessment(
        MeasurementStatus.READY_FOR_EVIDENCE_CHAIN,
        values,
        {"blinded_attack_grants_jax_passive_stack": _consistent_boolean(cases["B6"])},
        ("SUBSEQUENT_CHANGE_SCAN_REQUIRED",),
    )


def validate_measurement(path: Path, *, root: Path | None = None) -> MeasurementAssessment:
    """Validate a measurement document structurally and semantically.

    :param path: Measurement fixture to validate and assess.
    :param root: Project root containing locked data and curated records.
    :return: Semantic assessment of the schema-valid measurement document.
    """

    if root is None:
        root = repository_root()
    document = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads((root / "schemas/cc-measurement.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]
        pointer = "/" + "/".join(map(str, error.absolute_path))
        raise MeasurementError(f"{pointer}: {error.message}")
    return assess_blind_measurement(document)


def main() -> None:
    """Run the module command-line interface.

    :return: None.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("measurement", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    assessment = validate_measurement(args.measurement, root=args.root.resolve())
    print(dumps(asdict(assessment)))


if __name__ == "__main__":
    main()
