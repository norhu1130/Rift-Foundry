"""Focused metadata regressions for Gwen's Cog."""

from pathlib import Path

from lol_build.cogs import CogMaturity
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.registry import create_default_registry

ROOT = Path(__file__).resolve().parents[1]


def test_gwen_locked_model_metadata() -> None:
    """Require complete capability declaration and three local sources."""
    cog = create_default_registry(ROOT).require_cog("Gwen")
    assert cog.maturity is CogMaturity.MODELED_UNVERIFIED
    assert cog.capabilities == DUEL_CAPABILITIES
    assert len(cog.evidence_refs) == 3 and all((ROOT / ref).is_file() for ref in cog.evidence_refs)
