"""Dedicated scaffold module for Yorick."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class YorickCog(ChampionCog):
    """Reserve Yorick-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Yorick"
