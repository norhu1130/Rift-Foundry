"""Dedicated scaffold module for Viego."""

from lol_build.cogs.base import ChampionCog, CogCapability, CogMaturity


class ViegoCog(ChampionCog):
    """Reserve Viego-specific behavior without claiming unmodeled abilities."""

    maturity = CogMaturity.SCAFFOLDED
    capabilities = frozenset({CogCapability.BASIC_ATTACK})
    curation_blocker = "COG_SCAFFOLDED:Viego"
