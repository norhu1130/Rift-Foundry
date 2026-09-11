"""Kindred combat Cog backed by locked 16.17.1 source documents."""

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


class KindredCog(ChampionCog):
    """Model Kindred's level-13 Q5/W5/E1 marks-independent rotation."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Kindred.json",
        "data/raw/16.17.1/communitydragon/champions/203.json",
        "data/raw/16.17.1/communitydragon/champions/kindred.bin.json",
    )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Return neutral speed without an earned Hunt mark.

        :param context: Role-bound Kindred encounter context.
        :return: Neutral movement multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return Dance of Arrows' displayed displacement.

        :param context: Role-bound Kindred encounter context.
        :return: Dash reach in game units.
        """
        return Decimal(340)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item effects beyond the deterministic marks-free rotation.

        :param item: Normalized locked item candidate.
        :return: Kindred-specific blocker or ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        return (
            f"KINDRED_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
            if unsupported
            else None
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Q, W and basic attacks without fabricating mark stacks.

        :param context: Role-bound snapshots and duration.
        :return: Deterministic events and mark/respite blockers.
        """
        base = self._sequence_base(context)
        ad = context.snapshot.attack_damage
        events = [
            action(
                "KINDRED_Q_DANCE_OF_ARROWS",
                at_ms=100,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(140) + Decimal("0.75") * ad,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
            action(
                "KINDRED_W_WOLFS_FRENZY",
                at_ms=500,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(60) + Decimal("0.20") * ad,
                        DamageType.MAGIC,
                    ),
                ),
            ),
        ]
        for i, t in enumerate(
            range(
                350,
                context.duration_ms + 1,
                self._attack_interval_ms(context.snapshot.attack_speed),
            ),
            1,
        ):
            events.append(
                action(
                    f"KINDRED_BASIC_ATTACK_{i}",
                    at_ms=t,
                    sequence=base + 100 + i,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(damage(context.opponent_entity, ad, DamageType.PHYSICAL),),
                )
            )
        return ActionPlan(
            "kindred_q5_w5_e1_level13_rotation_v1",
            tuple(sorted(events, key=lambda e: (e.at_ms, e.sequence))),
            (
                "KINDRED_LEVEL13_RANK_POLICY_UNVERIFIED",
                "KINDRED_MARKS_NOT_MODELED",
                "KINDRED_E_THIRD_HIT_NOT_MODELED",
                "KINDRED_R_REPRIEVE_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Keep Lamb's Respite absent until spatial eligibility is modeled.

        :param context: Role-bound Kindred encounter context.
        :return: Reaction blockers for the omitted death-prevention state.
        """
        return ReactionPlan(
            "kindred_respite_reaction_v1",
            blockers=("KINDRED_R_ZONE_AND_DEATH_PREVENTION_NOT_MODELED",),
        )
