"""Dedicated scaffold module for Rell."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class RellCog(ChampionCog):
    """Reserve Rell-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Rell"
