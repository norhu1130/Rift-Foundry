"""Kog'Maw combat Cog backed by locked 16.17.1 source documents."""

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
from lol_build.core.timeline import ActionChannel, StatusOutput


class KogMawCog(ChampionCog):
    """Model Kog'Maw's level-13 W5 artillery and attack rotation."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/KogMaw.json",
        "data/raw/16.17.1/communitydragon/champions/96.json",
        "data/raw/16.17.1/communitydragon/champions/kogmaw.bin.json",
    )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Return neutral movement speed for the immobile artillery baseline.

        :param context: Role-bound Kog'Maw encounter context.
        :return: Neutral multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return zero because Kog'Maw has no dash.

        :param context: Role-bound Kog'Maw encounter context.
        :return: Zero dash distance.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject unmodeled resource, sustain, and critical item channels.

        :param item: Normalized locked item candidate.
        :return: Kog'Maw-specific blocker or ``None``.
        """
        s = item["stats"]
        assert isinstance(s, dict)
        u = {
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "MANA_REGEN",
            "OMNIVAMP",
        } & s.keys()
        return f"KOGMAW_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(u))}" if u else None

    def build_action_plan(self, c: ParticipantContext) -> ActionPlan:
        """Build W-active percentage-health attacks and one artillery hit.

        :param c: Role-bound snapshots and duration.
        :return: Deterministic attack plan with missing-health blockers.
        """
        b = self._sequence_base(c)
        ev = [
            action(
                "KOGMAW_W_BIO_ARCANE_BARRAGE",
                at_ms=100,
                sequence=b,
                source=c.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(c.self_entity, "KOGMAW_W_BIO_ARCANE", 8000),),
            ),
            action(
                "KOGMAW_R_LIVING_ARTILLERY",
                at_ms=700,
                sequence=b + 1,
                source=c.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        c.opponent_entity,
                        Decimal(300) + Decimal("0.35") * c.snapshot.ability_power,
                        DamageType.MAGIC,
                    ),
                ),
            ),
        ]
        for i, t in enumerate(
            range(250, c.duration_ms + 1, self._attack_interval_ms(c.snapshot.attack_speed)), 1
        ):
            ev.append(
                action(
                    f"KOGMAW_W_ATTACK_{i}",
                    at_ms=t,
                    sequence=b + 100 + i,
                    source=c.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(c.opponent_entity, c.snapshot.attack_damage, DamageType.PHYSICAL),
                        damage(
                            c.opponent_entity,
                            c.opponent_snapshot.max_hp * Decimal("0.07"),
                            DamageType.MAGIC,
                        ),
                    ),
                )
            )
        return ActionPlan(
            "kogmaw_w5_r2_level13_rotation_v1",
            tuple(sorted(ev, key=lambda e: (e.at_ms, e.sequence))),
            (
                "KOGMAW_LEVEL13_RANK_POLICY_UNVERIFIED",
                "KOGMAW_W_DURATION_AND_ON_HIT_ORDER_UNVERIFIED",
                "KOGMAW_R_MISSING_HEALTH_SCALING_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, c: ParticipantContext) -> ReactionPlan:
        """Return no fabricated defensive reaction for Kog'Maw.

        :param c: Role-bound Kog'Maw encounter context.
        :return: Explicitly blocked reaction plan.
        """
        return ReactionPlan(
            "kogmaw_reaction_v1", blockers=("KOGMAW_PASSIVE_DEATH_STATE_NOT_MODELED",)
        )
