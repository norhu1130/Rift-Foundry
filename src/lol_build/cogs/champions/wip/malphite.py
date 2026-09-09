"""Malphite combat Cog for the locked level-13 duel benchmark."""

from __future__ import annotations

from decimal import Decimal

from lol_build.cogs.base import (
    ActionPlan,
    AttackCadenceModifierWindow,
    CastBlockWindow,
    ChampionCog,
    CogCapability,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, StatModifierOutput, StatusOutput


class MalphiteCog(ChampionCog):
    """Model Malphite's Q5/W1/E5/R2 spell-led benchmark rotation."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = frozenset(
        {
            CogCapability.BASIC_ATTACK,
            CogCapability.ABILITY_ROTATION,
            CogCapability.REACTION_MODEL,
            CogCapability.ENGAGEMENT,
            CogCapability.ITEM_POLICY,
            CogCapability.RECOMMENDATION,
        }
    )
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Malphite.json",
        "data/raw/16.17.1/communitydragon/champions/54.json",
        "data/raw/16.17.1/communitydragon/champions/malphite.bin.json",
    )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Unstoppable Force's locked cast range.

        :param context: Role-bound Malphite combat context.
        :return: Maximum R displacement in game units.
        """
        return Decimal(1000)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item values absent from the fixed spell schedule.

        :param item: Normalized candidate item from the locked catalog.
        :return: Champion-scoped blocker, or ``None`` when represented.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "OMNIVAMP",
        } & stats.keys()
        if unsupported:
            return f"MALPHITE_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build R2, Q5, E5, W1 empowerment, and regular attacks.

        E emits observable runtime state while the reaction plan supplies the
        causally linked cadence window used to reschedule opposing attacks.

        :param context: Role-bound snapshots for Malphite and his opponent.
        :return: Deterministic spell-led schedule with evidence blockers.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        armor = context.snapshot.armor
        events = [
            action(
                "MALPHITE_R_UNSTOPPABLE_FORCE",
                at_ms=400,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(300) + Decimal("0.90") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "KNOCKUP", duration_ms=1500),
                ),
            ),
            action(
                "MALPHITE_Q_SEISMIC_SHARD",
                at_ms=2000,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(270) + Decimal("0.60") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity, "SLOW", duration_ms=3000, magnitude=Decimal("0.40")
                    ),
                ),
            ),
            action(
                "MALPHITE_E_GROUND_SLAM",
                at_ms=2200,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(200) + Decimal("0.40") * ap + Decimal("0.60") * armor,
                        DamageType.MAGIC,
                    ),
                    StatusOutput(
                        context.opponent_entity,
                        "MALPHITE_ATTACK_SPEED_REDUCTION",
                        3000,
                        Decimal("0.50"),
                    ),
                    StatModifierOutput(
                        context.opponent_entity, "ATTACK_SPEED_MULTIPLIER", Decimal("0.50"), 3000
                    ),
                ),
            ),
            action(
                "MALPHITE_W_THUNDERCLAP_ATTACK",
                at_ms=2400,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity, context.snapshot.attack_damage, DamageType.PHYSICAL
                    ),
                    damage(
                        context.opponent_entity,
                        Decimal(30) + Decimal("0.20") * ap + Decimal("0.15") * armor,
                        DamageType.MAGIC,
                    ),
                ),
            ),
        ]
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        for index, at_ms in enumerate(range(3200, context.duration_ms + 1, interval_ms), start=1):
            events.append(
                action(
                    f"MALPHITE_BASIC_ATTACK_{index}",
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
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"MALPHITE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "malphite_q5_w1_e5_r2_level13_locked_v1",
            tuple(events),
            (
                *level_blockers,
                "MALPHITE_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "MALPHITE_ROTATION_TIMING_UNVERIFIED",
                "MALPHITE_Q_MOVEMENT_STEAL_NOT_EVALUATED",
                "MALPHITE_W_SPLASH_EXCLUDED_SINGLE_TARGET_BENCHMARK",
                "MALPHITE_W_BONUS_ARMOR_PASSIVE_NOT_APPLIED_TO_SNAPSHOT",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Apply R knockup and benchmark-start Granite Shield.

        :param context: Role-bound snapshots for Malphite and his opponent.
        :return: Non-tenacity-reducible knockup and passive shield reaction.
        """
        base = self._sequence_base(context)
        return ReactionPlan(
            "malphite_r_knockup_and_granite_shield_v1",
            events=(
                action(
                    "MALPHITE_PASSIVE_GRANITE_SHIELD",
                    at_ms=0,
                    sequence=base + 900,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(
                        shielding(context.self_entity, Decimal("0.10") * context.snapshot.max_hp),
                    ),
                    requires_living_opponent=False,
                ),
            ),
            cast_block_windows=(
                CastBlockWindow(
                    "malphite_r_knockup",
                    400,
                    min(1900, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY),
                    "MALPHITE_R_UNSTOPPABLE_FORCE",
                    False,
                ),
            ),
            attack_cadence_windows=(
                AttackCadenceModifierWindow(
                    "malphite_e_ground_slam_attack_speed_reduction",
                    2200,
                    min(5200, context.duration_ms),
                    Decimal("0.50"),
                    "MALPHITE_E_GROUND_SLAM",
                ),
            )
            if context.duration_ms > 2200
            else (),
            blockers=(
                "MALPHITE_R_CAST_AND_HIT_TIMING_UNVERIFIED",
                "MALPHITE_PASSIVE_ASSUMES_READY_AT_BENCHMARK_START",
                "MALPHITE_PASSIVE_RECHARGE_NOT_MODELED",
            ),
        )
