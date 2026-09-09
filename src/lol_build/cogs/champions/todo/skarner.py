"""Dedicated scaffold module for Skarner."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class SkarnerCog(ChampionCog):
    """Reserve Skarner-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Skarner"
