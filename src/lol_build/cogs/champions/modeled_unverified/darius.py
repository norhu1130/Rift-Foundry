"""Dedicated module for the modeled Darius Cog."""

from decimal import Decimal

from lol_build.cogs.base import CogCapability, CogMaturity, ParticipantContext
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

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Represent a landed Apprehend as removable approach distance.

        Apprehend pulls the opponent rather than moving Darius; like Rocket Grab,
        the shared engagement interface counts the displacement as closed
        distance. Hitting the pull at maximum range remains an assumption.

        :param context: Role-bound snapshots for the hook fixture.
        :return: Apprehend's locked 550-unit cast range.
        """
        return Decimal(550)
