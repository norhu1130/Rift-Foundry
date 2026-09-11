"""Kled combat Cog backed by locked 16.17.1 source documents."""

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


class KledCog(ChampionCog):
    """Model mounted Kled's level-13 Q5/W5/E1 engage baseline."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Kled.json",
        "data/raw/16.17.1/communitydragon/champions/240.json",
        "data/raw/16.17.1/communitydragon/champions/kled.bin.json",
    )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Return neutral speed because Chaaaaaaaarge target routing is unknown.

        :param context: Role-bound Kled encounter context.
        :return: Neutral movement multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return Jousting's base dash distance.

        :param context: Role-bound Kled encounter context.
        :return: Dash reach in game units.
        """
        return Decimal(550)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject unsupported sustain, critical, and mana channels.

        :param item: Normalized locked item candidate.
        :return: Kled-specific blocker or ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        return (
            f"KLED_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
            if unsupported
            else None
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build mounted Q, E and basic attacks.

        :param context: Role-bound snapshots and duration.
        :return: Deterministic mounted rotation with dismount blockers.
        """
        b = self._sequence_base(context)
        ad = context.snapshot.attack_damage
        ev = [
            action(
                "KLED_E_JOUSTING",
                at_ms=100,
                sequence=b,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(160) + Decimal("0.60") * ad,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
            action(
                "KLED_Q_BEAR_TRAP",
                at_ms=450,
                sequence=b + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(140) + Decimal("0.65") * ad,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
        ]
        for i, t in enumerate(
            range(
                700,
                context.duration_ms + 1,
                self._attack_interval_ms(context.snapshot.attack_speed),
            ),
            1,
        ):
            ev.append(
                action(
                    f"KLED_BASIC_ATTACK_{i}",
                    at_ms=t,
                    sequence=b + 100 + i,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(damage(context.opponent_entity, ad, DamageType.PHYSICAL),),
                )
            )
        return ActionPlan(
            "kled_q5_w5_e1_level13_mounted_rotation_v1",
            tuple(sorted(ev, key=lambda e: (e.at_ms, e.sequence))),
            (
                "KLED_LEVEL13_RANK_POLICY_UNVERIFIED",
                "KLED_DISMOUNT_AND_COURAGE_NOT_MODELED",
                "KLED_W_FOURTH_HIT_NOT_MODELED",
                "KLED_R_TARGETING_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Avoid inventing Skaarl health and remount defensive behavior.

        :param context: Role-bound Kled encounter context.
        :return: Reaction plan with mounted-state blockers.
        """
        return ReactionPlan(
            "kled_mounted_reaction_v1", blockers=("KLED_SKAARL_HEALTH_AND_REMOUNT_NOT_MODELED",)
        )
