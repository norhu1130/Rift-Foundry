"""Dedicated scaffold module for Seraphine."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class SeraphineCog(ChampionCog):
    """Reserve Seraphine-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Seraphine"
