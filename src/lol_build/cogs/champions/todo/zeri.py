"""Dedicated scaffold module for Zeri."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class ZeriCog(ChampionCog):
    """Reserve Zeri-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Zeri"
