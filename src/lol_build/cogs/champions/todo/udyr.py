"""Dedicated scaffold module for Udyr."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class UdyrCog(ChampionCog):
    """Reserve Udyr-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Udyr"
