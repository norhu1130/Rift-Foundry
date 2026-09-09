"""Dedicated module for the modeled Darius Cog."""

from lol_build.cogs.base import CogCapability, CogMaturity
from lol_build.cogs.darius import DariusCog as _ModeledDariusCog


class DariusCog(_ModeledDariusCog):
    """Expose the modeled Darius behavior through its roster-owned module."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = frozenset(
        {
            CogCapability.BASIC_ATTACK,
            CogCapability.ABILITY_ROTATION,
            CogCapability.REACTION_MODEL,
            CogCapability.ITEM_POLICY,
            CogCapability.RECOMMENDATION,
        }
    )
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Darius.json",
        "data/raw/16.17.1/communitydragon/champions/122.json",
        "data/raw/16.17.1/communitydragon/champions/darius.bin.json",
    )
