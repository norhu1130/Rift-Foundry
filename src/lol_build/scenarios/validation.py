"""Structural and semantic validation for scenario profiles."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, NoReturn

from jsonschema import Draft202012Validator, FormatChecker

from lol_build.buildtime.patch_lock import PatchLockError, verify_patch_lock
from lol_build.buildtime.paths import repository_root


class ScenarioValidationError(RuntimeError):
    """A scenario violation with a JSON-pointer-like path."""


def _fail(path: str, message: str) -> NoReturn:
    """Raise a scenario validation error at a JSON path.

    :param path: JSON pointer identifying the invalid scenario field.
    :param message: Human-readable validation failure appended to the JSON path.
    :return: This function never returns.
    """

    raise ScenarioValidationError(f"{path}: {message}")


def _load_json(path: Path) -> Any:
    """Read scenario JSON and report decoding failures as validation errors.

    :param path: Scenario or schema JSON file to read.
    :return: Parsed JSON value from ``path``.
    """

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScenarioValidationError(f"/: cannot load JSON {path}: {error}") from error


def _decimal(path: str, value: str) -> Decimal:
    """Parse a finite Decimal from scenario data.

    :param path: JSON pointer used when reporting an invalid scalar.
    :param value: Raw JSON scalar expected to encode a finite decimal.
    :return: Finite decimal represented by ``value``.
    """

    try:
        result = Decimal(value)
    except InvalidOperation:
        _fail(path, f"invalid decimal string {value!r}")
    if not result.is_finite():
        _fail(path, "decimal must be finite")
    return result


def validate_scenario_document(document: dict[str, Any], *, root: Path) -> None:
    """Validate semantic invariants that JSON Schema cannot express.

    :param document: Parsed JSON document to validate or transform.
    :param root: Project root containing locked data and curated records.
    :return: None.
    """

    mix = document["target"]["incoming_damage_mix"]
    mix_total = sum(
        (
            _decimal(f"/target/incoming_damage_mix/{name}", mix[name])
            for name in ("physical", "magical", "true")
        ),
        start=Decimal(0),
    )
    if mix_total != Decimal(1):
        _fail("/target/incoming_damage_mix", f"damage shares must sum to 1, got {mix_total}")

    snapshot = document["target"]["stat_snapshot"]
    if _decimal("/target/stat_snapshot/max_hp", snapshot["max_hp"]) <= 0:
        _fail("/target/stat_snapshot/max_hp", "max_hp must be greater than zero")
    if snapshot["status"] == "VERIFIED" and not snapshot.get("measurement_ref"):
        _fail("/target/stat_snapshot/measurement_ref", "verified snapshot requires a measurement")

    duration_ms = document["encounter"]["duration_ms"]
    for index, event in enumerate(document["encounter"]["cc_profile"]["events"]):
        if event["at_ms"] >= duration_ms:
            _fail(
                f"/encounter/cc_profile/events/{index}/at_ms",
                f"event must start before encounter ends at {duration_ms} ms",
            )

    for index, window in enumerate(document["encounter"].get("target_defensive_windows", [])):
        if window["start_ms"] >= window["end_ms"]:
            _fail(
                f"/encounter/target_defensive_windows/{index}",
                "start_ms must be before end_ms",
            )
        if window["end_ms"] > duration_ms:
            _fail(
                f"/encounter/target_defensive_windows/{index}/end_ms",
                f"window must end within encounter at {duration_ms} ms",
            )
    for index, event in enumerate(document["encounter"].get("target_shield_events", [])):
        if event["at_ms"] >= duration_ms:
            _fail(
                f"/encounter/target_shield_events/{index}/at_ms",
                f"event must occur before encounter ends at {duration_ms} ms",
            )
        if _decimal(f"/encounter/target_shield_events/{index}/amount", event["amount"]) < 0:
            _fail(
                f"/encounter/target_shield_events/{index}/amount",
                "shield amount must be non-negative",
            )

    horizon_ms = document["selection_policy"]["kill_gate"]["horizon_ms"]
    if horizon_ms > duration_ms:
        _fail(
            "/selection_policy/kill_gate/horizon_ms",
            f"kill horizon must not exceed encounter duration {duration_ms} ms",
        )

    branch_ids = [branch["id"] for branch in document["selection_policy"]["branches"]]
    expected_branches = {"DEFAULT", "OFFENSE", "DEFENSE"}
    if len(branch_ids) != len(set(branch_ids)) or set(branch_ids) != expected_branches:
        _fail(
            "/selection_policy/branches",
            f"branch IDs must be exactly {sorted(expected_branches)}, got {branch_ids}",
        )

    lock_ref = document["patch"]["data_lock_ref"]
    lock_path = (root / lock_ref).resolve()
    try:
        lock = verify_patch_lock(lock_path)
    except PatchLockError as error:
        _fail("/patch/data_lock_ref", str(error))
    if lock["region"] != document["patch"]["region"]:
        _fail("/patch/region", f"does not match patch lock region {lock['region']}")
    if lock["game_patch"] != document["patch"]["game_patch"]:
        _fail("/patch/game_patch", f"does not match patch lock {lock['game_patch']}")

    mechanic_records = {
        record["id"]: record
        for path in (root / "data/curated/mechanics").glob("*.json")
        if isinstance((record := _load_json(path)), dict) and "id" in record
    }
    for index, event in enumerate(document["encounter"]["cc_profile"]["events"]):
        mechanic_ref = event["mechanic_ref"]
        if mechanic_ref not in mechanic_records:
            _fail(
                f"/encounter/cc_profile/events/{index}/mechanic_ref",
                f"unknown mechanic record {mechanic_ref!r}",
            )
        mechanic = mechanic_records[mechanic_ref]
        if mechanic["game_patch"] != document["patch"]["game_patch"]:
            _fail(
                f"/encounter/cc_profile/events/{index}/mechanic_ref",
                f"mechanic patch {mechanic['game_patch']} does not match scenario patch",
            )
        if (
            document["verification"]["status"] == "VERIFIED"
            and mechanic["verification"]["status"] != "VERIFIED"
        ):
            _fail(
                f"/encounter/cc_profile/events/{index}/mechanic_ref",
                "verified scenario cannot reference an unverified mechanic",
            )


def validate_scenario(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    """Load a scenario, validate its schema, then validate semantic invariants.

    :param path: Scenario JSON file to load and validate.
    :param root: Project root containing locked data and curated records.
    :return: Validated scenario document ready for deterministic evaluation.
    """

    path = path.resolve()
    if root is None:
        root = repository_root()
    schema_path = root / "schemas/scenario-profile.schema.json"
    document = _load_json(path)
    schema = _load_json(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]
        pointer = "/" + "/".join(map(str, error.absolute_path))
        _fail(pointer, error.message)
    validate_scenario_document(document, root=root)
    return document


def main() -> None:
    """Run the module command-line interface.

    :return: None.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    args = parser.parse_args()
    scenario = validate_scenario(args.scenario)
    print(f"validated scenario {scenario['id']} for patch {scenario['patch']['game_patch']}")


if __name__ == "__main__":
    main()
