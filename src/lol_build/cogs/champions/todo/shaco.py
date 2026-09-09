"""Dedicated scaffold module for Shaco."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class ShacoCog(ChampionCog):
    """Reserve Shaco-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Shaco"
