"""Dedicated scaffold module for Taliyah."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class TaliyahCog(ChampionCog):
    """Reserve Taliyah-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Taliyah"
