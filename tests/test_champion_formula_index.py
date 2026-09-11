"""Verify lossless, source-linked indexing of champion formula evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lol_build.buildtime.champion_formula_index import (
    DetectionStatus,
    FormulaCandidateKind,
    FormulaIndexError,
    index_champion_formula_documents,
)
from lol_build.buildtime.champion_snapshots import ChampionIdentity


def _write_json(path: Path, value: object) -> Path:
    """Write one compact source fixture used by the isolated index tests.

    :param path: Destination beneath the temporary test directory.
    :param value: JSON-compatible fixture value to encode.
    :return: ``path`` after its parent and contents have been created.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _fixture_paths(root: Path) -> tuple[Path, Path, Path]:
    """Create mutually corroborating Data Dragon and Community Dragon fixtures.

    :param root: Temporary directory that owns the three source files.
    :return: Data Dragon detail, Community profile, and BIN paths.
    """

    dd_spells = [
        {
            "id": f"Alpha{slot}",
            "name": f"Alpha {slot}",
            "cooldown": ["10.25", 9],
            "effectBurn": [None, "20/40", "0.75"],
        }
        for slot in "QWER"
    ]
    dd = _write_json(
        root / "Alpha.json",
        {
            "data": {
                "Alpha": {
                    "id": "Alpha",
                    "key": "1",
                    "passive": {"name": "Alpha Force"},
                    "spells": dd_spells,
                }
            }
        },
    )
    profile = _write_json(
        root / "1.json",
        {
            "id": 1,
            "passive": {"name": "Alpha Force"},
            "spells": [
                {
                    "spellKey": slot.lower(),
                    "name": f"Alpha {slot}",
                    "cooldownCoefficients": [10.25, 9.0],
                    "coefficients": {"coefficient1": 0.75},
                    "effectAmounts": {"Effect1Amount": [0.0, 20.0, 40.0]},
                }
                for slot in "QWER"
            ],
        },
    )
    champion_root = "Characters/Alpha/CharacterRecords/Root"
    spell_paths = [f"Characters/Alpha/Spells/Alpha{slot}Ability/Alpha{slot}" for slot in "QWER"]
    bin_document: dict[str, object] = {
        champion_root: {"spellNames": spell_paths, "spells": spell_paths},
        "Characters/Alpha/Spells/AlphaForcePassive": {"mSpell": {"mCoefficient": 0.125}},
    }
    for path in spell_paths:
        bin_document[path] = {
            "mSpell": {
                "cooldownTime": [0.0, 10.25, 9.0],
                "mEffectAmount": [{"value": [0.0, 20.0, 40.0]}],
                "mCoefficient": 0.75,
                "mSpellCalculations": {
                    "Damage": {
                        "calculationParts": [
                            {"mCoefficient": 1.25, "mStat": 2, "__type": "StatByCoefficientPart"}
                        ],
                        "__type": "GameCalculation",
                    }
                },
            }
        }
    bin_path = _write_json(root / "alpha.bin.json", bin_document)
    return dd, profile, bin_path


def test_indexes_slots_and_preserves_raw_candidates_with_source_refs(tmp_path: Path) -> None:
    """Keep exact values and JSON pointers while assigning structured spell roots.

    :param tmp_path: Isolated filesystem supplied by pytest.
    :return: None.
    """

    paths = _fixture_paths(tmp_path)

    index = index_champion_formula_documents(ChampionIdentity("Alpha", 1), *paths)

    assert [spell.slot for spell in index.spells] == ["P", "Q", "W", "E", "R"]
    q_spell = index.spells[1]
    assert "AlphaQ" in q_spell.names
    assert any(
        ref.source == "COMMUNITY_BIN"
        and ref.json_pointer == "/Characters~1Alpha~1Spells~1AlphaQAbility~1AlphaQ"
        for ref in q_spell.source_refs
    )
    dd_cooldown = next(
        candidate
        for candidate in q_spell.candidates
        if candidate.kind is FormulaCandidateKind.COOLDOWN
        and candidate.source_ref.source == "DATA_DRAGON"
    )
    assert dd_cooldown.value == ["10.25", 9]
    assert dd_cooldown.source_ref.json_pointer.endswith("/spells/0/cooldown")
    calculation = next(candidate for candidate in q_spell.candidates if candidate.label == "Damage")
    assert calculation.status is DetectionStatus.AUTO_DETECTED
    assert calculation.value["calculationParts"][0]["mCoefficient"] == pytest.approx(1.25)
    assert calculation.source_ref.json_pointer.endswith("/mSpell/mSpellCalculations/Damage")


def test_passive_name_correlation_is_explicitly_ambiguous(tmp_path: Path) -> None:
    """Prevent a name-matched passive BIN record from becoming approved evidence.

    :param tmp_path: Isolated filesystem supplied by pytest.
    :return: None.
    """

    index = index_champion_formula_documents(
        ChampionIdentity("Alpha", 1), *_fixture_paths(tmp_path)
    )

    passive = index.spells[0]
    candidate = next(
        item for item in passive.candidates if item.source_ref.source == "COMMUNITY_BIN"
    )
    assert candidate.status is DetectionStatus.AMBIGUOUS


def test_structured_passive_root_is_auto_detected(tmp_path: Path) -> None:
    """Prefer the character root's explicit passive path over name correlation.

    :param tmp_path: Isolated filesystem supplied by pytest.
    :return: None.
    """

    dd, profile, bin_path = _fixture_paths(tmp_path)
    document = json.loads(bin_path.read_text(encoding="utf-8"))
    document["Characters/Alpha/CharacterRecords/Root"]["mCharacterPassiveSpell"] = (
        "Characters/Alpha/Spells/AlphaForcePassive"
    )
    bin_path.write_text(json.dumps(document), encoding="utf-8")

    index = index_champion_formula_documents(ChampionIdentity("Alpha", 1), dd, profile, bin_path)

    passive = index.spells[0]
    candidate = next(
        item for item in passive.candidates if item.source_ref.source == "COMMUNITY_BIN"
    )
    assert candidate.status is DetectionStatus.AUTO_DETECTED


def test_document_output_is_deterministic_and_preserves_decimal_text(tmp_path: Path) -> None:
    """Render repeated indexing identically without binary-float precision loss.

    :param tmp_path: Isolated filesystem supplied by pytest.
    :return: None.
    """

    paths = _fixture_paths(tmp_path)
    first = index_champion_formula_documents(ChampionIdentity("Alpha", 1), *paths)
    second = index_champion_formula_documents(ChampionIdentity("Alpha", 1), *paths)

    assert first.to_document() == second.to_document()
    profile_coefficient = next(
        item
        for item in first.to_document()["spells"][1]["candidates"]
        if item["source_ref"]["source"] == "COMMUNITY_PROFILE" and item["label"] == "coefficients"
    )
    assert profile_coefficient["value"]["coefficient1"] == "0.75"


def test_rejects_a_mismatched_community_profile_identity(tmp_path: Path) -> None:
    """Stop cross-champion evidence from entering an otherwise valid index.

    :param tmp_path: Isolated filesystem supplied by pytest.
    :return: None.
    """

    dd, profile, bin_path = _fixture_paths(tmp_path)
    profile_document = json.loads(profile.read_text(encoding="utf-8"))
    profile_document["id"] = 2
    profile.write_text(json.dumps(profile_document), encoding="utf-8")

    with pytest.raises(FormulaIndexError, match="does not match"):
        index_champion_formula_documents(ChampionIdentity("Alpha", 1), dd, profile, bin_path)
