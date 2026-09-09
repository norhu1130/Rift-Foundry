"""Dedicated scaffold module for Ryze."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class RyzeCog(ChampionCog):
    """Reserve Ryze-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Ryze"
