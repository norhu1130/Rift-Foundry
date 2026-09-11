"""Coverage tests for the one-module-per-champion Cog architecture."""

from __future__ import annotations

import json
import re
from pathlib import Path

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity
from lol_build.cogs.manifest import (
    CHAMPION_COG_MANIFEST,
    CURATED_CHAMPION_KEYS,
    require_champion_cog_spec,
)

ROOT = Path(__file__).resolve().parents[1]
CHAMPION_MODULE_ROOT = ROOT / "src/lol_build/cogs/champions"


def _locked_catalog() -> dict[str, dict[str, object]]:
    """Read the version-locked Data Dragon champion catalog.

    :return: Champion summaries indexed by case-sensitive Data Dragon ID.
    """
    document = json.loads(
        (ROOT / "data/raw/16.17.1/en_US/champion.json").read_text(encoding="utf-8")
    )
    return document["data"]


def test_manifest_and_physical_modules_exactly_match_locked_roster() -> None:
    """Prevent missing, duplicate, and stale champion extension modules.

    :return: None.
    """
    locked_keys = set(_locked_catalog())
    specs = {spec.champion_key: spec for spec in CHAMPION_COG_MANIFEST}
    module_stems = {
        path.stem for path in CHAMPION_MODULE_ROOT.rglob("*.py") if path.name != "__init__.py"
    }

    assert len(CHAMPION_COG_MANIFEST) == len(locked_keys) == 173
    assert set(specs) == locked_keys
    assert len(specs) == len(CHAMPION_COG_MANIFEST)
    assert module_stems == {key.casefold() for key in locked_keys}


_MATURITY_FOLDER = {
    CogMaturity.SCAFFOLDED: "todo",
    CogMaturity.VERIFIED: "curated",
}
_BLOCKER_TUPLE_RE = re.compile(r"blockers=\((.*?)\),?\n", re.S)


def _has_champion_scoped_mechanism_gap(module_path: Path) -> bool:
    """Detect a champion Cog that documents an excluded or assumed mechanism.

    :param module_path: Physical path of the champion's Cog module.
    :return: True if any ``blockers=(...)`` block carries a literal string
        beyond the standard ``*self.verification_blockers()`` unpacking.
    """
    text = module_path.read_text(encoding="utf-8")
    return any(re.search(r'["\']', block) for block in _BLOCKER_TUPLE_RE.findall(text))


def test_champion_module_folder_matches_manifest_maturity() -> None:
    """Keep the todo/modeled_unverified/wip/curated folder layout in lockstep
    with manifest maturity and, within ``MODELED_UNVERIFIED``, with whether the
    Cog documents a champion-scoped mechanism gap.

    :return: None.
    """
    for spec in CHAMPION_COG_MANIFEST:
        module_relpath = Path(*spec.module_name.split(".")[3:]).with_suffix(".py")
        module_path = CHAMPION_MODULE_ROOT / module_relpath
        assert module_path.is_file(), (spec.champion_key, module_path)

        folder = spec.module_name.split(".")[3]
        assert spec.module_name == (
            f"lol_build.cogs.champions.{folder}.{spec.champion_key.casefold()}"
        ), spec.champion_key

        if spec.maturity is CogMaturity.MODELED_UNVERIFIED:
            expected_folder = (
                "wip" if _has_champion_scoped_mechanism_gap(module_path) else "modeled_unverified"
            )
        else:
            expected_folder = _MATURITY_FOLDER[spec.maturity]
        assert folder == expected_folder, spec.champion_key


def test_every_manifest_target_is_a_dedicated_champion_class() -> None:
    """Require every roster entry to resolve to its own physical module and class.

    :return: None.
    """
    catalog = _locked_catalog()
    loaded_classes: set[type[ChampionCog]] = set()
    for champion_key, document in catalog.items():
        spec = require_champion_cog_spec(champion_key)
        cog_class = spec.load_class()
        cog = cog_class(document)

        assert cog_class.__module__ == spec.module_name
        assert cog_class.__name__ == spec.class_name
        assert cog_class not in loaded_classes
        assert cog.champion_key == champion_key
        assert cog.qualified_name == f"champion:{champion_key}"
        assert cog.maturity is spec.maturity
        assert cog.verification_blockers() == (spec.blocker,)
        loaded_classes.add(cog_class)


def test_uncurated_champions_are_explicit_scaffolds_with_unique_blockers() -> None:
    """Keep structural coverage distinct from modeled champion behavior.

    :return: None.
    """
    for spec in CHAMPION_COG_MANIFEST:
        if spec.champion_key in CURATED_CHAMPION_KEYS:
            assert spec.maturity is CogMaturity.MODELED_UNVERIFIED
            assert spec.blocker == f"COG_MODEL_UNVERIFIED:{spec.champion_key}"
            continue

        cog_class = spec.load_class()
        assert cog_class.__bases__ == (ChampionCog,)
        assert spec.maturity is CogMaturity.SCAFFOLDED
        assert spec.blocker == f"COG_SCAFFOLDED:{spec.champion_key}"
        assert cog_class.maturity is CogMaturity.SCAFFOLDED


def test_modeled_champions_reference_three_locked_evidence_documents() -> None:
    """Require every modeled Cog to cite the locked detail, profile, and BIN inputs.

    :return: None.
    """
    catalog = _locked_catalog()
    patch_lock = json.loads((ROOT / "patch.lock.json").read_text(encoding="utf-8"))
    locked_paths = {entry["path"] for entry in patch_lock["files"]}
    for spec in CHAMPION_COG_MANIFEST:
        if spec.maturity is not CogMaturity.MODELED_UNVERIFIED:
            continue

        cog = spec.load_class()(catalog[spec.champion_key])
        raw_evidence_refs = tuple(ref for ref in cog.evidence_refs if ref.startswith("data/raw/"))
        assert len(raw_evidence_refs) >= 3, spec.champion_key
        assert any("/en_US/champion/" in ref for ref in raw_evidence_refs)
        assert any(ref.endswith(".bin.json") for ref in raw_evidence_refs)
        assert any(
            Path(ref).stem.isdigit()
            for ref in raw_evidence_refs
            if "/communitydragon/champions/" in ref
        )
        for evidence_ref in cog.evidence_refs:
            assert (ROOT / evidence_ref).is_file(), (spec.champion_key, evidence_ref)
        for evidence_ref in raw_evidence_refs:
            assert evidence_ref in locked_paths, (spec.champion_key, evidence_ref)


def test_modeled_champions_declare_the_routable_recommendation_contract() -> None:
    """Prevent maturity promotion without the behaviors used by recommendation.

    :return: None.
    """
    catalog = _locked_catalog()
    required = frozenset(
        {
            CogCapability.BASIC_ATTACK,
            CogCapability.ABILITY_ROTATION,
            CogCapability.REACTION_MODEL,
            CogCapability.ITEM_POLICY,
            CogCapability.RECOMMENDATION,
        }
    )
    for spec in CHAMPION_COG_MANIFEST:
        if spec.maturity is not CogMaturity.MODELED_UNVERIFIED:
            continue

        cog = spec.load_class()(catalog[spec.champion_key])
        assert required <= cog.capabilities, spec.champion_key


def test_champion_modules_inherit_the_shared_sequence_policy() -> None:
    """Keep participant ordering infrastructure out of champion-owned rules.

    :return: None.
    """
    for spec in CHAMPION_COG_MANIFEST:
        cog_class = spec.load_class()
        assert "_sequence_base" not in cog_class.__dict__, spec.champion_key
