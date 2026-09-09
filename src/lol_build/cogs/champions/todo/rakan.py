"""Dedicated scaffold module for Rakan."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class RakanCog(ChampionCog):
    """Reserve Rakan-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Rakan"
