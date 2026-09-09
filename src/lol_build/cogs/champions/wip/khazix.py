"""Kha'Zix combat Cog backed by locked 16.17.1 source documents."""

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


class KhazixCog(ChampionCog):
    """Model Kha'Zix's non-evolved level-13 Q5/W5/R2 burst."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Khazix.json",
        "data/raw/16.17.1/communitydragon/champions/121.json",
        "data/raw/16.17.1/communitydragon/champions/khazix.bin.json",
    )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Return neutral speed because stealth activation is conditional.

        :param context: Role-bound Kha'Zix encounter context.
        :return: Neutral movement multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return Leap's locked base range.

        :param context: Role-bound Kha'Zix encounter context.
        :return: Base Leap distance in game units.
        """
        return Decimal(700)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject unsupported resource, sustain, and critical channels.

        :param item: Normalized locked item candidate.
        :return: Kha'Zix-specific blocker or ``None``.
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
            f"KHAZIX_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
            if unsupported
            else None
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build non-evolved Q, W, E and attack events.

        :param context: Role-bound snapshots and encounter duration.
        :return: Deterministic burst plan with evolution-state blockers.
        """
        base, bonus = self._sequence_base(context), context.snapshot.bonus_attack_damage
        events = [
            action(
                "KHAZIX_E_LEAP",
                at_ms=100,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(205) + Decimal("0.20") * bonus,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
            action(
                "KHAZIX_W_VOID_SPIKE",
                at_ms=400,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(195) + Decimal("1.00") * bonus,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
            action(
                "KHAZIX_Q_TASTE_THEIR_FEAR",
                at_ms=700,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(180) + Decimal("1.15") * bonus,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
        ]
        for index, at_ms in enumerate(
            range(
                900,
                context.duration_ms + 1,
                self._attack_interval_ms(context.snapshot.attack_speed),
            ),
            1,
        ):
            events.append(
                action(
                    f"KHAZIX_BASIC_ATTACK_{index}",
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
            "khazix_q5_w5_e5_level13_rotation_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            (
                "KHAZIX_LEVEL13_RANK_AND_EVOLUTION_POLICY_UNVERIFIED",
                "KHAZIX_ISOLATION_NOT_MODELED",
                "KHAZIX_R_STEALTH_AND_PASSIVE_STATE_NOT_MODELED",
                "KHAZIX_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Return the explicit absence of fabricated stealth defenses.

        :param context: Role-bound Kha'Zix encounter context.
        :return: Reaction plan carrying stealth-state blockers.
        """
        return ReactionPlan(
            "khazix_stateful_reaction_v1",
            blockers=(
                "KHAZIX_R_STEALTH_TARGETABILITY_NOT_MODELED",
                "KHAZIX_PASSIVE_SLOW_NOT_MODELED",
            ),
        )
