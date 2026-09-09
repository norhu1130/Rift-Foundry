"""Dedicated scaffold module for Shyvana."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class ShyvanaCog(ChampionCog):
    """Reserve Shyvana-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Shyvana"
