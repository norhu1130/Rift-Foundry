"""Dedicated scaffold module for Sylas."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class SylasCog(ChampionCog):
    """Reserve Sylas-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Sylas"
