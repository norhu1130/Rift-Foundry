"""Dedicated scaffold module for Xayah."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class XayahCog(ChampionCog):
    """Reserve Xayah-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Xayah"
