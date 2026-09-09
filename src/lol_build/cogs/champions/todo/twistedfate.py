"""Dedicated scaffold module for TwistedFate."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class TwistedFateCog(ChampionCog):
    """Reserve TwistedFate-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:TwistedFate"
