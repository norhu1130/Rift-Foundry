"""Trundle combat Cog backed by the locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    ChampionCog,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage, healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    ResistanceReductionOutput,
    StatModifierOutput,
    StatusOutput,
)


class TrundleCog(ChampionCog):
    """Model Trundle's Q5/W5/E1/R2 level-13 single-target duel.

    Frozen Domain remains active for the full benchmark and accelerates only
    the ordinary attack clock. Chomp is emitted as an additional attack event
    at each fixed cooldown to represent its reset. Subjugate applies its locked
    half-upfront drain and resistance steal followed by four equal ticks.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Trundle.json",
        "data/raw/16.17.1/communitydragon/champions/48.json",
        "data/raw/16.17.1/communitydragon/champions/trundle.bin.json",
    )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose rank-five Frozen Domain movement speed for pursuit.

        :param context: Role-bound snapshots for the current encounter.
        :return: Movement-speed multiplier while Trundle remains on the domain.
        """
        return Decimal("1.52")

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the fixed Trundle schedule.

        Attack damage, ability power, attack speed, health, resistances,
        penetration, movement speed, and tenacity reach a modeled channel.
        Haste cannot reschedule casts, and critical or attributed item sustain
        cannot be evaluated by this action policy.

        :param item: Normalized candidate from the locked item catalog.
        :return: Trundle-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "MANA_REGEN",
            "OMNIVAMP",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"TRUNDLE_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _ordinary_attack_events(
        self,
        context: ParticipantContext,
    ) -> tuple[ActionEvent, ...]:
        """Schedule attacks on the rank-five Frozen Domain cadence.

        The opening attack occurs before Chomp. Later attacks use the same
        immutable attack damage because the shared scheduler cannot make Q's
        stolen attack damage conditional on whether the empowered hit landed.

        :param context: Role-bound snapshots supplying attack stats and duration.
        :return: Deterministic ordinary basic attacks through the benchmark.
        """
        attack_speed_ratio = Decimal("0.67")
        domain_attack_speed = context.snapshot.attack_speed + attack_speed_ratio * Decimal("1.10")
        interval_ms = self._attack_interval_ms(domain_attack_speed)
        base = self._sequence_base(context) + 100
        events = [
            action(
                "TRUNDLE_BASIC_ATTACK_1",
                at_ms=500,
                sequence=base,
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
        ]
        at_ms = 501 + interval_ms
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"TRUNDLE_BASIC_ATTACK_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=base + len(events),
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
            at_ms += interval_ms
        return tuple(events)

    def _chomp_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Create rank-five Q reset attacks on the locked 3.5-second cooldown.

        :param context: Role-bound snapshots supplying total attack damage.
        :return: Empowered attacks carrying physical damage and the brief slow.
        """
        base = self._sequence_base(context) + 200
        raw_damage = Decimal(90) + Decimal("1.55") * context.snapshot.attack_damage
        events: list[ActionEvent] = []
        at_ms = 501
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"TRUNDLE_Q_CHOMP_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            raw_damage,
                            DamageType.PHYSICAL,
                        ),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=100,
                            magnitude=Decimal("0.75"),
                        ),
                    ),
                )
            )
            at_ms += 3500
        return tuple(events)

    @staticmethod
    def _reduction_outputs(
        context: ParticipantContext,
        *,
        stacks: int,
    ) -> tuple[ResistanceReductionOutput, ...]:
        """Create one Subjugate resistance-reduction increment set.

        :param context: Role-bound context identifying the drained opponent.
        :param stacks: Five-percent increments applied at this drain timestamp.
        :return: Paired armor and magic-resistance reduction outputs.
        """
        outputs: list[ResistanceReductionOutput] = []
        for _ in range(stacks):
            outputs.extend(
                (
                    ResistanceReductionOutput(
                        context.opponent_entity,
                        "ARMOR",
                        Decimal("0.05"),
                        8,
                        8000,
                        f"TRUNDLE_R_ARMOR_SHRED_{context.self_entity.value}",
                    ),
                    ResistanceReductionOutput(
                        context.opponent_entity,
                        "MAGIC_RESISTANCE",
                        Decimal("0.05"),
                        8,
                        8000,
                        f"TRUNDLE_R_MR_SHRED_{context.self_entity.value}",
                    ),
                )
            )
        return tuple(outputs)

    def _subjugate_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build R2's maximum-health drain and progressive resistance steal.

        Half the total effect resolves upfront. Four later ticks each resolve
        one eighth of the total drain and another five percentage points of the
        target's original armor and magic resistance. Frozen Domain's locked
        healing amplification is applied to the modeled raw drain heal.

        :param context: Role-bound snapshots supplying AP, target HP, and resists.
        :return: Five causal ultimate events with damage, healing, and stat changes.
        """
        base = self._sequence_base(context) + 400
        total_ratio = Decimal("0.25") + Decimal("0.0002") * (context.snapshot.ability_power)
        events: list[ActionEvent] = []
        for index, at_ms in enumerate((200, 1200, 2200, 3200, 4200)):
            upfront = index == 0
            ratio = total_ratio / (Decimal(2) if upfront else Decimal(8))
            resistance_fraction = Decimal("0.20") if upfront else Decimal("0.05")
            raw_drain = context.opponent_snapshot.max_hp * ratio
            events.append(
                action(
                    "TRUNDLE_R_SUBJUGATE_INITIAL"
                    if upfront
                    else f"TRUNDLE_R_SUBJUGATE_TICK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY if upfront else ActionChannel.PASSIVE,
                    outputs=(
                        *self._reduction_outputs(
                            context,
                            stacks=4 if upfront else 1,
                        ),
                        StatModifierOutput(
                            context.self_entity,
                            "ARMOR",
                            context.opponent_snapshot.armor * resistance_fraction,
                            8000,
                        ),
                        StatModifierOutput(
                            context.self_entity,
                            "MAGIC_RESISTANCE",
                            context.opponent_snapshot.magic_resistance * resistance_fraction,
                            8000,
                        ),
                        damage(
                            context.opponent_entity,
                            raw_drain,
                            DamageType.MAGIC,
                        ),
                        healing(
                            context.self_entity,
                            raw_drain * Decimal("1.25"),
                        ),
                    ),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked level-13 duel rotation for either participant role.

        :param context: Role-bound snapshots for Trundle and the opponent.
        :return: Q resets, W-accelerated attacks, E slow, and R drain events.
        """
        base = self._sequence_base(context)
        fixed_events = (
            action(
                "TRUNDLE_W_FROZEN_DOMAIN",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "TRUNDLE_W_ACTIVE", 8000),),
                requires_living_opponent=False,
            ),
            action(
                "TRUNDLE_E_PILLAR_SLOW",
                at_ms=100,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=6000,
                        magnitude=Decimal("0.34"),
                    ),
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"TRUNDLE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "trundle_q5_w5_e1_r2_level13_synthetic_v1",
            tuple(
                sorted(
                    (
                        *fixed_events,
                        *self._subjugate_events(context),
                        *self._ordinary_attack_events(context),
                        *self._chomp_events(context),
                    ),
                    key=lambda event: (event.at_ms, event.sequence),
                )
            ),
            (
                *level_blockers,
                "TRUNDLE_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "TRUNDLE_ROTATION_TIMING_UNVERIFIED",
                "TRUNDLE_W_DOMAIN_UPTIME_ASSUMED",
                "TRUNDLE_Q_ATTACK_RESET_TIMING_UNVERIFIED",
                "TRUNDLE_Q_SELF_AND_ENEMY_AD_TRANSFER_NOT_EVALUATED",
                "TRUNDLE_E_TARGET_REMAINS_IN_SLOW_ZONE_ASSUMED",
                "TRUNDLE_E_TERRAIN_AND_DISPLACEMENT_NOT_EVALUATED",
                "TRUNDLE_R_RAW_DRAIN_HEAL_ATTRIBUTION_UNVERIFIED",
                "TRUNDLE_PASSIVE_NEARBY_UNIT_DEATHS_OUTSIDE_SCENARIO",
                "TRUNDLE_RESOURCE_COSTS_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Describe reaction assumptions not encoded by Trundle's action events.

        R's self resistance gain is emitted causally with each drain event, so
        no unconditional defensive window is needed. E slow is represented as
        a timeline status, while its terrain collision remains explicitly out.

        :param context: Role-bound snapshots for the current encounter.
        :return: Neutral reaction plan with unresolved terrain semantics.
        """
        return ReactionPlan(
            "trundle_r_resistance_steal_reaction_v1",
            blockers=(
                "TRUNDLE_E_TERRAIN_PATHING_NOT_EVALUATED",
                "TRUNDLE_E_KNOCKBACK_NOT_EVALUATED",
            ),
        )
