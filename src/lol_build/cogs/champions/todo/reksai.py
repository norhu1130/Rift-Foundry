"""Dedicated scaffold module for RekSai."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class RekSaiCog(ChampionCog):
    """Reserve RekSai-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:RekSai"
