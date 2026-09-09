"""Dedicated module for the modeled Ahri Cog."""

from lol_build.cogs.ahri import AhriCog as _ModeledAhriCog
from lol_build.cogs.base import CogCapability, CogMaturity


class AhriCog(_ModeledAhriCog):
    """Expose the modeled Ahri behavior through its roster-owned module."""

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
        "data/raw/16.17.1/en_US/champion/Ahri.json",
        "data/raw/16.17.1/communitydragon/champions/103.json",
        "data/raw/16.17.1/communitydragon/champions/ahri.bin.json",
    )
