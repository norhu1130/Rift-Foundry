"""Dedicated scaffold module for Renata."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class RenataCog(ChampionCog):
    """Reserve Renata-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Renata"
