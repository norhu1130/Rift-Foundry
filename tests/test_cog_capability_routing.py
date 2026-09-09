"""Regression tests for explicit champion-Cog capability routing."""

from pathlib import Path

import pytest

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs.base import ChampionCog
from lol_build.cogs.manifest import CHAMPION_COG_MANIFEST
from lol_build.cogs.registry import ChampionCogRegistry

ROOT = Path(__file__).resolve().parents[1]


class LegacyMarkerOnlyCog(ChampionCog):
    """Expose the removed legacy marker without declaring a capability."""

    recommendation_model_id = "legacy_marker_must_not_enable_routing"


def _remaining_scaffold() -> str:
    """Return one manifest-backed scaffold during staged Cog promotion.

    :return: Champion key for an unmodeled Cog.
    """
    scaffold = next(
        (
            spec.champion_key
            for spec in CHAMPION_COG_MANIFEST
            if spec.maturity.value == "SCAFFOLDED"
        ),
        None,
    )
    if scaffold is None:
        pytest.skip("all locked champion Cogs have been promoted")
    return scaffold


def test_modeled_cogs_and_scaffolds_have_distinct_recommendation_routing() -> None:
    """Only explicitly capable modeled Cogs should expose recommendations."""
    engine = MatchupEngine(ROOT)
    scaffold = _remaining_scaffold()

    for champion in ("Aatrox", "Ahri", "Darius", "Garen"):
        assert engine.resolve(
            MatchupRequest(champion, scaffold)
        ).specialized_recommendation_available

    assert not engine.resolve(
        MatchupRequest(scaffold, "Darius")
    ).specialized_recommendation_available


def test_recommendation_capability_follows_actor_during_role_reversal() -> None:
    """Swapping matchup roles should also swap recommendation ownership."""
    engine = MatchupEngine(ROOT)
    scaffold = _remaining_scaffold()

    modeled_actor = engine.resolve(MatchupRequest("Darius", scaffold))
    scaffold_actor = engine.resolve(MatchupRequest(scaffold, "Darius"))

    assert modeled_actor.specialized_recommendation_available is True
    assert scaffold_actor.specialized_recommendation_available is False


def test_scaffold_recommendation_returns_an_explicit_blocker() -> None:
    """A scaffold actor should stop before candidate generation."""
    engine = MatchupEngine(ROOT)
    scaffold = _remaining_scaffold()

    result = engine.recommend(MatchupRequest(scaffold, "Darius"))

    assert result.recommendation is None
    assert result.blockers == (f"RECOMMENDATION_MODEL_UNCURATED:{scaffold}",)


def test_legacy_model_identifier_does_not_grant_recommendation_capability() -> None:
    """A historical class attribute must not bypass the capability contract."""
    default_engine = MatchupEngine(ROOT)
    akali = default_engine.registry.require_cog("Akali")
    registry = ChampionCogRegistry()
    registry.add_cog(LegacyMarkerOnlyCog(akali.document, akali.detail_root))
    engine = MatchupEngine(ROOT, registry=registry)

    resolved = engine.resolve(MatchupRequest("Akali", "Akali"))
    result = engine.recommend(MatchupRequest("Akali", "Akali"))

    assert resolved.specialized_recommendation_available is False
    assert result.recommendation is None
    assert result.blockers == ("RECOMMENDATION_MODEL_UNCURATED:Akali",)
