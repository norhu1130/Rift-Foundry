"""Kennen combat Cog backed by locked 16.17.1 source documents."""

from decimal import Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    CastBlockWindow,
    ChampionCog,
    CogMaturity,
    ControlType,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel


class KennenCog(ChampionCog):
    """Model Kennen's level-13 Q5/W5/R2 lightning rotation."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Kennen.json",
        "data/raw/16.17.1/communitydragon/champions/85.json",
        "data/raw/16.17.1/communitydragon/champions/kennen.bin.json",
    )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Return Lightning Rush's rank-one pursuit multiplier.

        :param context: Role-bound Kennen encounter context.
        :return: Movement multiplier for the modeled approach.
        """
        return Decimal("1.10")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return zero because Lightning Rush is not a dash.

        :param context: Role-bound Kennen encounter context.
        :return: Zero dash distance.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject unsupported probabilistic and resource item channels.

        :param item: Normalized locked item candidate.
        :return: Kennen-specific blocker or ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "MANA_REGEN",
            "OMNIVAMP",
        } & stats.keys()
        return (
            f"KENNEN_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
            if unsupported
            else None
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Q, W, R and attack events under the locked rank policy.

        :param context: Role-bound snapshots and encounter duration.
        :return: Deterministic lightning rotation with stack-state blockers.
        """
        base, ap = self._sequence_base(context), context.snapshot.ability_power
        events = [
            action(
                "KENNEN_Q_THUNDERING_SHURIKEN",
                at_ms=100,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(260) + Decimal("0.85") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "KENNEN_W_ELECTRICAL_SURGE",
                at_ms=500,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(170) + Decimal("0.80") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "KENNEN_R_SLICING_MAELSTROM",
                at_ms=900,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(300) + Decimal("0.40") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=1250),
                ),
            ),
        ]
        for index, at_ms in enumerate(
            range(
                700,
                context.duration_ms + 1,
                self._attack_interval_ms(context.snapshot.attack_speed),
            ),
            1,
        ):
            events.append(
                action(
                    f"KENNEN_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 100 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            context.snapshot.attack_damage,
                            DamageType.PHYSICAL,
                        ),
                    ),
                )
            )
        return ActionPlan(
            "kennen_q5_w5_r2_level13_rotation_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            (
                "KENNEN_LEVEL13_RANK_POLICY_UNVERIFIED",
                "KENNEN_MARK_STACKS_AND_R_TICK_COUNT_NOT_MODELED",
                "KENNEN_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the modeled Maelstrom stun as a causal control window.

        :param context: Role-bound Kennen encounter context.
        :return: Stun window and mark-stack verification blocker.
        """
        return ReactionPlan(
            "kennen_r_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "kennen_r_stun",
                    900,
                    min(2150, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT),
                    "KENNEN_R_SLICING_MAELSTROM",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=("KENNEN_MARK_STUN_TRIGGER_UNVERIFIED",),
        )
