"""Dedicated scaffold module for Quinn."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class QuinnCog(ChampionCog):
    """Reserve Quinn-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Quinn"
