"""Dedicated scaffold module for Senna."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class SennaCog(ChampionCog):
    """Reserve Senna-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Senna"
