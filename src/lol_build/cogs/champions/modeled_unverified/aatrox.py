"""Dedicated module for the modeled Aatrox Cog."""

from lol_build.cogs.aatrox import AatroxCog as _ModeledAatroxCog
from lol_build.cogs.base import CogCapability, CogMaturity


class AatroxCog(_ModeledAatroxCog):
    """Expose the modeled Aatrox behavior through its roster-owned module."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = frozenset(
        {
            CogCapability.BASIC_ATTACK,
            CogCapability.ABILITY_ROTATION,
            CogCapability.REACTION_MODEL,
            CogCapability.ITEM_POLICY,
            CogCapability.ENGAGEMENT,
            CogCapability.RECOMMENDATION,
        }
    )
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Aatrox.json",
        "data/raw/16.17.1/communitydragon/champions/266.json",
        "data/raw/16.17.1/communitydragon/champions/aatrox.bin.json",
    )
