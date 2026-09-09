"""Index patch-locked champion spell formula evidence without approving formulas."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from lol_build.buildtime.champion_snapshots import ChampionIdentity, load_champion_roster
from lol_build.buildtime.patch_lock import verify_patch_lock
from lol_build.core.canonical import dumps, normalize


class FormulaIndexError(RuntimeError):
    """Report missing, malformed, or contradictory champion formula evidence."""


class DetectionStatus(StrEnum):
    """Describe whether a source structure or a heuristic connected the evidence."""

    AUTO_DETECTED = "AUTO_DETECTED"
    AMBIGUOUS = "AMBIGUOUS"


class FormulaCandidateKind(StrEnum):
    """Classify raw values by their possible role in a future curated formula."""

    COOLDOWN = "COOLDOWN"
    BASE_VALUE = "BASE_VALUE"
    COEFFICIENT = "COEFFICIENT"


@dataclass(frozen=True)
class SourceRef:
    """Locate evidence exactly within one immutable source document.

    :param source: Dataset that supplied the referenced JSON value.
    :param path: Repository-relative or caller-supplied source file path.
    :param json_pointer: RFC 6901 pointer to the referenced value.
    """

    source: str
    path: str
    json_pointer: str


@dataclass(frozen=True)
class FormulaCandidate:
    """Retain an uninterpreted source value that may participate in a formula.

    A candidate is evidence, not an approved gameplay formula. In particular,
    effect-array positions and BIN calculations still require human confirmation.

    :param kind: Possible semantic role detected from the source field name.
    :param label: Original source field or calculation name.
    :param value: Complete JSON subtree, parsed with decimal precision preserved.
    :param status: Strength of the structural connection to the spell slot.
    :param source_ref: Exact file and JSON pointer from which ``value`` came.
    """

    kind: FormulaCandidateKind
    label: str
    value: Any
    status: DetectionStatus
    source_ref: SourceRef


@dataclass(frozen=True)
class SpellFormulaIndex:
    """Collect raw formula evidence associated with one champion spell slot.

    :param slot: Champion ability slot, including ``P`` for passive evidence.
    :param names: Distinct source names and identifiers associated with the slot.
    :param source_refs: Source objects and BIN records inspected for the slot.
    :param candidates: Cooldown, base-value, and coefficient evidence in source order.
    """

    slot: str
    names: tuple[str, ...]
    source_refs: tuple[SourceRef, ...]
    candidates: tuple[FormulaCandidate, ...]


@dataclass(frozen=True)
class ChampionFormulaIndex:
    """Expose all source-linked spell evidence for one champion.

    :param champion: Data Dragon champion identifier.
    :param numeric_id: Numeric identifier shared with Community Dragon.
    :param spells: Passive and Q/W/E/R evidence in deterministic slot order.
    """

    champion: str
    numeric_id: int
    spells: tuple[SpellFormulaIndex, ...]

    def to_document(self) -> dict[str, Any]:
        """Convert the immutable index into a canonical JSON-compatible mapping.

        :return: Mapping suitable for deterministic reports and fixture assertions.
        """

        return normalize(asdict(self))


_SLOTS = ("P", "Q", "W", "E", "R")
_ACTIVE_SLOTS = _SLOTS[1:]
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _load_json(path: Path) -> Any:
    """Decode source JSON while preserving the decimal spelling of numeric values.

    :param path: Immutable champion snapshot to read.
    :return: Parsed JSON tree whose non-integral numbers are ``Decimal`` objects.
    """

    try:
        return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    except (OSError, json.JSONDecodeError) as error:
        raise FormulaIndexError(f"cannot load champion formula source {path}: {error}") from error


def _pointer_segment(value: str) -> str:
    """Escape one object key for use in an RFC 6901 JSON Pointer.

    :param value: Unescaped JSON object key.
    :return: Pointer-safe segment retaining the complete original key.
    """

    return value.replace("~", "~0").replace("/", "~1")


def _pointer(*segments: str | int) -> str:
    """Join source path segments into an RFC 6901 JSON Pointer.

    :param segments: Object keys and array indices leading to a JSON value.
    :return: Absolute JSON Pointer, or the empty pointer for the document root.
    """

    return "" if not segments else "/" + "/".join(_pointer_segment(str(item)) for item in segments)


def _normalized_name(value: str) -> str:
    """Normalize a source label solely for conservative record correlation.

    :param value: Spell name, spell ID, or BIN record path.
    :return: Lowercase alphanumeric comparison token.
    """

    return _NON_ALNUM.sub("", value.lower())


def _source_ref(source: str, path: Path, pointer: str) -> SourceRef:
    """Create a source reference using stable caller-visible path text.

    :param source: Dataset name attached to the source file.
    :param path: Source snapshot path supplied to the indexing API.
    :param pointer: JSON Pointer within the source snapshot.
    :return: Immutable reference for a spell record or formula candidate.
    """

    return SourceRef(source=source, path=path.as_posix(), json_pointer=pointer)


def _candidate(
    kind: FormulaCandidateKind,
    label: str,
    value: Any,
    status: DetectionStatus,
    source: str,
    path: Path,
    pointer: str,
) -> FormulaCandidate:
    """Package one unmodified JSON subtree with its detection provenance.

    :param kind: Possible formula role assigned by the field-name scanner.
    :param label: Original field or named calculation label.
    :param value: Complete parsed JSON subtree at ``pointer``.
    :param status: Confidence in the evidence-to-slot association.
    :param source: Dataset containing the candidate.
    :param path: Snapshot file containing the candidate.
    :param pointer: Exact JSON Pointer to ``value``.
    :return: Candidate that deliberately makes no gameplay correctness claim.
    """

    return FormulaCandidate(kind, label, value, status, _source_ref(source, path, pointer))


def _scan_tree(
    value: Any,
    *,
    source: str,
    path: Path,
    pointer_parts: tuple[str | int, ...],
    status: DetectionStatus,
) -> list[FormulaCandidate]:
    """Find recognized raw numeric fields without evaluating their semantics.

    Named calculation objects are retained whole so calculation parts, stat keys,
    and nested coefficients are not destroyed by premature interpretation.

    :param value: Spell source subtree to traverse.
    :param source: Dataset containing the subtree.
    :param path: Snapshot file containing the subtree.
    :param pointer_parts: Path segments locating ``value`` in the source document.
    :param status: Strength of the subtree's association with a spell slot.
    :return: Candidates ordered by their appearance in the source document.
    """

    results: list[FormulaCandidate] = []
    if not isinstance(value, dict):
        return results
    for key, child in value.items():
        child_parts = (*pointer_parts, key)
        lowered = key.lower()
        if lowered == "mspellcalculations" and isinstance(child, dict):
            for calculation_name, calculation in child.items():
                results.append(
                    _candidate(
                        FormulaCandidateKind.COEFFICIENT,
                        calculation_name,
                        calculation,
                        status,
                        source,
                        path,
                        _pointer(*child_parts, calculation_name),
                    )
                )
            continue
        kind: FormulaCandidateKind | None = None
        if "cooldown" in lowered:
            kind = FormulaCandidateKind.COOLDOWN
        elif lowered in {"effectburn", "effectamounts", "meffectamount", "datavalues"}:
            kind = FormulaCandidateKind.BASE_VALUE
        elif any(token in lowered for token in ("coefficient", "ratio", "scaling")):
            kind = FormulaCandidateKind.COEFFICIENT
        if kind is not None:
            results.append(
                _candidate(
                    kind,
                    key,
                    child,
                    status,
                    source,
                    path,
                    _pointer(*child_parts),
                )
            )
            continue
        if isinstance(child, dict):
            results.extend(
                _scan_tree(
                    child,
                    source=source,
                    path=path,
                    pointer_parts=child_parts,
                    status=status,
                )
            )
    return results


def _require_object(value: Any, description: str) -> dict[str, Any]:
    """Reject a source node whose object structure is required for indexing.

    :param value: Parsed JSON node to validate.
    :param description: Human-readable source location used in failure messages.
    :return: ``value`` narrowed to an object mapping.
    """

    if not isinstance(value, dict):
        raise FormulaIndexError(f"expected object at {description}")
    return value


def _data_dragon_champion(document: Any, champion: str) -> dict[str, Any]:
    """Select the requested champion from a Data Dragon detail document.

    :param document: Parsed Data Dragon champion detail JSON.
    :param champion: Expected champion identifier.
    :return: Champion detail object containing passive and active spells.
    """

    root = _require_object(document, "Data Dragon document")
    data = _require_object(root.get("data"), "Data Dragon /data")
    return _require_object(data.get(champion), f"Data Dragon /data/{champion}")


def _bin_slot_records(
    document: dict[str, Any], champion: str
) -> dict[str, tuple[tuple[str, DetectionStatus], ...]]:
    """Associate BIN spell records with slots using roots before name heuristics.

    The ordered ``CharacterRecords/Root.spells`` list is authoritative structural
    evidence for Q/W/E/R. Passive names lack an equivalent slot list and therefore
    remain ambiguous when found by correlation.

    :param document: Parsed Community Dragon BIN object.
    :param champion: Champion identifier used to find the character root.
    :return: Slot-to-record mappings with an explicit association status.
    """

    root_key = next(
        (
            key
            for key in document
            if key.lower() == f"characters/{champion.lower()}/characterrecords/root"
        ),
        None,
    )
    assigned: dict[str, list[tuple[str, DetectionStatus]]] = {slot: [] for slot in _SLOTS}
    if root_key is not None:
        root = document[root_key]
        spells = root.get("spells", []) if isinstance(root, dict) else []
        if isinstance(spells, list):
            for slot, spell_path in zip(_ACTIVE_SLOTS, spells, strict=False):
                if not isinstance(spell_path, str):
                    continue
                prefix = spell_path.rsplit("/", 1)[0] + "/"
                matching = [
                    key for key in document if key == spell_path or key.startswith(prefix)
                ]
                assigned[slot].extend((key, DetectionStatus.AUTO_DETECTED) for key in matching)
        passive_path = root.get("mCharacterPassiveSpell") if isinstance(root, dict) else None
        if isinstance(passive_path, str) and passive_path:
            passive_prefix = passive_path.rsplit("/", 1)[0] + "/"
            matching = [
                key for key in document if key == passive_path or key.startswith(passive_prefix)
            ]
            assigned["P"].extend(
                (key, DetectionStatus.AUTO_DETECTED) for key in matching
            )
    return {slot: tuple(records) for slot, records in assigned.items()}


def index_champion_formula_documents(
    champion: ChampionIdentity,
    data_dragon_path: Path,
    community_profile_path: Path,
    community_bin_path: Path,
    *,
    source_labels: tuple[str, str, str] | None = None,
) -> ChampionFormulaIndex:
    """Index one champion's three detailed snapshots without approving formulas.

    :param champion: Cross-source champion identity expected in all three snapshots.
    :param data_dragon_path: Data Dragon detail document with ordered Q/W/E/R spells.
    :param community_profile_path: Community Dragon client-facing champion profile.
    :param community_bin_path: Community Dragon calculation-grade BIN JSON dump.
    :param source_labels: Stable report paths when read paths are absolute or temporary.
    :return: Slot-indexed raw evidence with exact paths and detection statuses.
    """

    dd_document = _load_json(data_dragon_path)
    profile = _require_object(_load_json(community_profile_path), "Community profile")
    bin_document = _require_object(_load_json(community_bin_path), "Community BIN")
    dd_champion = _data_dragon_champion(dd_document, champion.key)
    if str(profile.get("id")) != str(champion.numeric_id):
        raise FormulaIndexError(
            f"Community profile ID {profile.get('id')!r} does not match {champion.numeric_id}"
        )

    if source_labels is None:
        report_paths = data_dragon_path, community_profile_path, community_bin_path
    else:
        report_paths = tuple(Path(label) for label in source_labels)
    dd_report_path, profile_report_path, bin_report_path = report_paths

    dd_spells = dd_champion.get("spells", [])
    profile_spells = profile.get("spells", [])
    if not isinstance(dd_spells, list) or not isinstance(profile_spells, list):
        raise FormulaIndexError("champion active spells must be arrays")
    bin_records = _bin_slot_records(bin_document, champion.key)
    indexes: list[SpellFormulaIndex] = []

    for slot in _SLOTS:
        names: list[str] = []
        refs: list[SourceRef] = []
        candidates: list[FormulaCandidate] = []
        if slot == "P":
            dd_value = dd_champion.get("passive")
            profile_value = profile.get("passive")
            dd_parts: tuple[str | int, ...] = ("data", champion.key, "passive")
            profile_parts: tuple[str | int, ...] = ("passive",)
        else:
            position = _ACTIVE_SLOTS.index(slot)
            dd_value = dd_spells[position] if position < len(dd_spells) else None
            profile_value = next(
                (
                    spell
                    for spell in profile_spells
                    if isinstance(spell, dict) and str(spell.get("spellKey", "")).upper() == slot
                ),
                profile_spells[position] if position < len(profile_spells) else None,
            )
            dd_parts = ("data", champion.key, "spells", position)
            profile_position = (
                profile_spells.index(profile_value) if profile_value in profile_spells else position
            )
            profile_parts = ("spells", profile_position)

        for source, path, source_value, parts in (
            ("DATA_DRAGON", dd_report_path, dd_value, dd_parts),
            ("COMMUNITY_PROFILE", profile_report_path, profile_value, profile_parts),
        ):
            if not isinstance(source_value, dict):
                continue
            refs.append(_source_ref(source, path, _pointer(*parts)))
            for field in ("id", "spellKey", "name"):
                name = source_value.get(field)
                if isinstance(name, str) and name and name not in names:
                    names.append(name)
            candidates.extend(
                _scan_tree(
                    source_value,
                    source=source,
                    path=path,
                    pointer_parts=parts,
                    status=DetectionStatus.AUTO_DETECTED,
                )
            )

        selected_bin_records = list(bin_records[slot])
        if slot == "P" and names and not selected_bin_records:
            tokens = tuple(token for token in map(_normalized_name, names) if len(token) >= 4)
            selected_bin_records.extend(
                (key, DetectionStatus.AMBIGUOUS)
                for key in bin_document
                if "/spells/" in key.lower()
                and any(token in _normalized_name(key) for token in tokens)
            )
        seen_records: set[str] = set()
        for record_key, status in selected_bin_records:
            if record_key in seen_records:
                continue
            seen_records.add(record_key)
            record = bin_document[record_key]
            record_parts = (record_key,)
            refs.append(_source_ref("COMMUNITY_BIN", bin_report_path, _pointer(*record_parts)))
            candidates.extend(
                _scan_tree(
                    record,
                    source="COMMUNITY_BIN",
                    path=bin_report_path,
                    pointer_parts=record_parts,
                    status=status,
                )
            )
        indexes.append(SpellFormulaIndex(slot, tuple(names), tuple(refs), tuple(candidates)))
    return ChampionFormulaIndex(champion.key, champion.numeric_id, tuple(indexes))


def _locked_source_paths(
    lock: dict[str, Any], champion: ChampionIdentity
) -> tuple[str, str, str]:
    """Resolve the three required snapshot paths from verified lock entries.

    :param lock: Verified patch-lock document.
    :param champion: Champion whose source paths must be unique in the lock.
    :return: Data Dragon detail, Community profile, and Community BIN paths.
    """

    expected_suffixes = (
        f"/champion/{champion.key}.json",
        f"/champions/{champion.numeric_id}.json",
        f"/champions/{champion.key.lower()}.bin.json",
    )
    results: list[str] = []
    for suffix in expected_suffixes:
        matches = [entry["path"] for entry in lock["files"] if entry["path"].endswith(suffix)]
        if len(matches) != 1:
            raise FormulaIndexError(
                f"expected one locked source ending in {suffix}, found {len(matches)}"
            )
        results.append(matches[0])
    return results[0], results[1], results[2]


def build_champion_formula_index(
    lock_path: Path,
    *,
    champion_key: str | None = None,
    schema_path: Path | None = None,
) -> tuple[ChampionFormulaIndex, ...]:
    """Authenticate locked snapshots and build deterministic champion indexes.

    :param lock_path: Patch lock covering every indexed source document.
    :param champion_key: Optional case-insensitive champion filter.
    :param schema_path: Optional patch-lock schema override for isolated fixtures.
    :return: Champion indexes sorted by the numeric roster identifier.
    """

    lock_path = lock_path.resolve()
    lock = verify_patch_lock(lock_path, schema_path=schema_path)
    roster = load_champion_roster(lock_path)
    if champion_key is not None:
        roster = tuple(item for item in roster if item.key.casefold() == champion_key.casefold())
        if not roster:
            raise FormulaIndexError(f"champion is not present in locked roster: {champion_key}")
    results: list[ChampionFormulaIndex] = []
    for champion in roster:
        paths = _locked_source_paths(lock, champion)
        results.append(
            index_champion_formula_documents(
                champion,
                *(lock_path.parent / relative for relative in paths),
                source_labels=paths,
            )
        )
    return tuple(results)


def main() -> None:
    """Print a deterministic JSON formula-evidence report for locked champions.

    :return: None.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", nargs="?", type=Path, default=Path("patch.lock.json"))
    parser.add_argument("--champion", help="limit the report to one Data Dragon champion key")
    parser.add_argument("--pretty", action="store_true", help="indent JSON for manual inspection")
    args = parser.parse_args()
    indexes = build_champion_formula_index(args.lock, champion_key=args.champion)
    document = {
        "schema_version": 1,
        "champion_count": len(indexes),
        "champions": [index.to_document() for index in indexes],
    }
    if args.pretty:
        print(json.dumps(normalize(document), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(dumps(document))


if __name__ == "__main__":
    main()
