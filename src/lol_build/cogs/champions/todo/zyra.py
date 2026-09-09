"""Dedicated scaffold module for Zyra."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class ZyraCog(ChampionCog):
    """Reserve Zyra-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Zyra"
