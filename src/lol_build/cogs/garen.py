"""Garen reaction Cog usable from either participant position."""

from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_FLOOR, Decimal

from lol_build.cogs.base import (
    ActionPlan,
    CastBlockWindow,
    ChampionCog,
    CogCapability,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    DamageModifierWindow,
    DamageOutput,
    EntityId,
    MissingHealthDamageOutput,
    ResistanceReductionOutput,
    ShieldOutput,
    StatModifierOutput,
    StatusOutput,
    opponent_sequence_offset,
)


class GarenCog(ChampionCog):
    """Provide the current synthetic rank-one W reaction.

    The action plan currently covers Q and E; R remains blocked until missing-HP
    damage is represented. The reaction uses context entities, so it protects
    Garen regardless of which request side he occupies.
    """

    recommendation_model_id = "generic_cog_build_preview_v1"
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

    def snapshot(self, *, level: int, item_stats=None):
        """Add the benchmark's assumed capped W passive resistances.

        :param level: Champion level.
        :param item_stats: Normalized aggregate item modifiers.
        :return: Garen snapshot with permanent W armor and magic resistance.
        """
        snapshot = super().snapshot(level=level, item_stats=item_stats)
        # The level-13 benchmark assumes W's 150-minion permanent-resist cap.
        return replace(
            snapshot,
            armor=snapshot.armor + Decimal(30),
            magic_resistance=snapshot.magic_resistance + Decimal(30),
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Return the assumed rank-five Q movement-speed multiplier.

        :param context: Concrete participant context.
        :return: Pursuit movement multiplier.
        """
        return Decimal("1.35")

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Estimate Garen passive regeneration after its no-damage delay.

        :param context: Concrete participant context.
        :param duration_ms: Lane observation duration.
        :param no_damage_delay_ms: Delay before regeneration begins.
        :return: Recovered health and verification blockers.
        """
        active_seconds = max(Decimal(0), Decimal(duration_ms - no_damage_delay_ms) / Decimal(1000))
        # Level 13: 8.1% maximum health per five seconds from the locked curve.
        amount = context.snapshot.max_hp * Decimal("0.081") / Decimal(5) * active_seconds
        return amount, ("GAREN_PASSIVE_REGEN_CURATED_UNVERIFIED",)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats absent from the synthetic Garen model.

        :param item: Normalized item candidate.
        :return: Blocker code or ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {"AP", "MANA", "HEAL_SHIELD_POWER"} & stats.keys()
        if unsupported:
            return f"GAREN_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked level-13 Q5/E5/R2 synthetic action sequence.

        :param context: Role-bound combat snapshots.
        :return: Garen action plan with explicit timing blockers.
        """
        sequence = self._sequence_base(context)
        q_damage = Decimal(150) + Decimal("1.5") * context.snapshot.attack_damage
        events: list[ActionEvent] = [
            ActionEvent(
                "GAREN_Q_STRIKE",
                200,
                sequence,
                context.self_entity,
                ActionChannel.BASIC_ATTACK,
                (
                    DamageOutput(context.opponent_entity, q_damage, DamageType.PHYSICAL),
                    StatusOutput(context.opponent_entity, "SILENCE", 1500),
                ),
            )
        ]
        sequence += 1
        base_attack_speed = Decimal(str(self.document["stats"]["attackspeed"]))
        bonus_attack_speed = max(
            Decimal(0), context.snapshot.attack_speed / base_attack_speed - Decimal(1)
        )
        strike_count = 7 + int(
            (bonus_attack_speed / Decimal("0.25")).to_integral_value(ROUND_FLOOR)
        )
        tick_interval = 3000 // strike_count
        expected_critical_multiplier = Decimal(1) + (
            Decimal("0.30") * context.snapshot.critical_strike_chance
        )
        per_tick = (
            (Decimal(16) + Decimal("0.52") * context.snapshot.attack_damage)
            * Decimal("1.25")
            * expected_critical_multiplier
        )
        for index in range(strike_count):
            outputs = [DamageOutput(context.opponent_entity, per_tick, DamageType.PHYSICAL)]
            if index == 5:
                outputs.append(
                    ResistanceReductionOutput(
                        context.opponent_entity,
                        "ARMOR",
                        Decimal("0.25"),
                        1,
                        6000,
                        "garen_e_armor_shred",
                    )
                )
            events.append(
                ActionEvent(
                    f"GAREN_E_TICK_{index + 1}",
                    800 + index * tick_interval,
                    sequence,
                    context.self_entity,
                    ActionChannel.ABILITY,
                    tuple(outputs),
                )
            )
            sequence += 1
        events.append(
            ActionEvent(
                "GAREN_R_DEMACIAN_JUSTICE",
                4000,
                sequence,
                context.self_entity,
                ActionChannel.ABILITY,
                (
                    MissingHealthDamageOutput(
                        context.opponent_entity,
                        Decimal(200),
                        Decimal("0.30"),
                        DamageType.TRUE,
                    ),
                ),
            )
        )
        return ActionPlan(
            "garen_q5_e5_r2_level13_synthetic_v1",
            tuple(events),
            (
                "GAREN_E_TICK_PHASE_UNVERIFIED",
                "GAREN_E_NEAREST_TARGET_BONUS_UNVERIFIED",
                "GAREN_E_EXPECTED_CRITICAL_DAMAGE_UNVERIFIED",
                "GAREN_Q_CRITICAL_STRIKE_NOT_EVALUATED",
                "GAREN_R_CAST_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Build Garen W defense and Q silence reactions.

        :param context: Role-bound combat snapshots.
        :return: Shield, damage-reduction, tenacity, and silence plan.
        """
        shield = Decimal(65) + Decimal("0.18") * context.snapshot.bonus_health
        return ReactionPlan(
            "garen_w_rank1_synthetic_v1",
            events=(
                ActionEvent(
                    "GAREN_W_SHIELD",
                    1000,
                    (20_000 if context.self_entity is EntityId.ACTOR else 30_000)
                    + opponent_sequence_offset(context.self_entity),
                    context.self_entity,
                    ActionChannel.ABILITY,
                    (
                        ShieldOutput(context.self_entity, shield),
                        StatModifierOutput(
                            context.self_entity,
                            "TENACITY_PERCENT",
                            Decimal("0.60"),
                            750,
                        ),
                    ),
                    requires_living_opponent=False,
                ),
            ),
            damage_windows=(
                DamageModifierWindow(
                    "garen_w_rank1_damage_reduction",
                    1000,
                    min(5000, context.duration_ms),
                    context.self_entity,
                    (DamageType.PHYSICAL, DamageType.MAGIC),
                    Decimal("0.75"),
                ),
            ),
            cast_block_windows=(
                CastBlockWindow(
                    "garen_q_silence",
                    500,
                    min(2000, context.duration_ms),
                    (ActionChannel.ABILITY,),
                    "GAREN_Q_STRIKE",
                    True,
                ),
            ),
            blockers=(
                "GAREN_Q_SILENCE_INTERACTION_UNVERIFIED",
                "GAREN_W_RANK1_TIMING_UNVERIFIED",
                "GAREN_W_TRUE_DAMAGE_TREATMENT_UNVERIFIED",
                "GAREN_W_TEMPORARY_TENACITY_CAST_WINDOW_NOT_EVALUATED",
            ),
        )
