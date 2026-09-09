"""Dedicated module for the modeled Garen Cog."""

from lol_build.cogs.base import CogCapability, CogMaturity
from lol_build.cogs.garen import GarenCog as _ModeledGarenCog


class GarenCog(_ModeledGarenCog):
    """Expose the modeled Garen behavior through its roster-owned module."""

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
        "data/raw/16.17.1/en_US/champion/Garen.json",
        "data/raw/16.17.1/communitydragon/champions/86.json",
        "data/raw/16.17.1/communitydragon/champions/garen.bin.json",
    )
