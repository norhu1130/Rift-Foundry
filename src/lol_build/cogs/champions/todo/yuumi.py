"""Dedicated scaffold module for Yuumi."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class YuumiCog(ChampionCog):
    """Reserve Yuumi-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Yuumi"
