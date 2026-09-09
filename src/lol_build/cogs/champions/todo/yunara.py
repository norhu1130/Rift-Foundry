"""Dedicated scaffold module for Yunara."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class YunaraCog(ChampionCog):
    """Reserve Yunara-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Yunara"
