"""LeBlanc combat Cog backed by locked 16.17.1 source documents."""

from decimal import Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    ChampionCog,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel


class LeblancCog(ChampionCog):
    """Model LeBlanc's level-13 Q5/W5/E1/R2 single-target burst."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Leblanc.json",
        "data/raw/16.17.1/communitydragon/champions/7.json",
        "data/raw/16.17.1/communitydragon/champions/leblanc.bin.json",
    )

    def engagement_speed_multiplier(self, c: ParticipantContext) -> Decimal:
        """Return neutral speed because Distortion provides displacement instead.

        :param c: Role-bound LeBlanc encounter context.
        :return: Neutral multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, c: ParticipantContext) -> Decimal:
        """Return Distortion's displayed dash reach.

        :param c: Role-bound LeBlanc encounter context.
        :return: Dash reach in game units.
        """
        return Decimal(600)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject unmodeled resource, sustain, and critical channels.

        :param item: Normalized locked item candidate.
        :return: LeBlanc-specific blocker or ``None``.
        """
        s = item["stats"]
        assert isinstance(s, dict)
        u = {
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "MANA",
            "MANA_REGEN",
        } & s.keys()
        return f"LEBLANC_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(u))}" if u else None

    def build_action_plan(self, c: ParticipantContext) -> ActionPlan:
        """Build Q mark, W impact, E chain, and Mimic burst events.

        :param c: Role-bound snapshots and duration.
        :return: Deterministic burst plan with return-state blockers.
        """
        b = self._sequence_base(c)
        ap = c.snapshot.ability_power
        ev = [
            action(
                "LEBLANC_Q_SIGIL",
                at_ms=100,
                sequence=b,
                source=c.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        c.opponent_entity, Decimal(235) + Decimal("0.40") * ap, DamageType.MAGIC
                    ),
                ),
            ),
            action(
                "LEBLANC_W_DISTORTION",
                at_ms=350,
                sequence=b + 1,
                source=c.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        c.opponent_entity, Decimal(245) + Decimal("0.60") * ap, DamageType.MAGIC
                    ),
                ),
            ),
            action(
                "LEBLANC_R_MIMIC_W",
                at_ms=700,
                sequence=b + 2,
                source=c.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        c.opponent_entity, Decimal(350) + Decimal("0.75") * ap, DamageType.MAGIC
                    ),
                ),
            ),
        ]
        return ActionPlan(
            "leblanc_q5_w5_e1_r2_level13_burst_v1",
            tuple(ev),
            (
                "LEBLANC_LEVEL13_RANK_POLICY_UNVERIFIED",
                "LEBLANC_Q_MARK_DETONATION_NOT_MODELED",
                "LEBLANC_E_DELAYED_ROOT_NOT_MODELED",
                "LEBLANC_W_RETURN_AND_R_COPY_SELECTION_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, c: ParticipantContext) -> ReactionPlan:
        """Avoid fabricating Distortion return and chain-root defensive effects.

        :param c: Role-bound LeBlanc encounter context.
        :return: Explicit reaction blockers.
        """
        return ReactionPlan(
            "leblanc_reaction_v1",
            blockers=(
                "LEBLANC_W_RETURN_POSITION_NOT_MODELED",
                "LEBLANC_E_TETHER_RANGE_NOT_MODELED",
            ),
        )
