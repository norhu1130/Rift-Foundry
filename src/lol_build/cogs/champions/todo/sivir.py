"""Dedicated scaffold module for Sivir."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class SivirCog(ChampionCog):
    """Reserve Sivir-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Sivir"
