"""Briar combat Cog backed by the locked 16.17.1 champion sources."""

from __future__ import annotations

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    DamageModifierWindow,
    MissingHealthDamageOutput,
    ResistanceReductionOutput,
    StatModifierOutput,
    StatusOutput,
)


class BriarCog(ChampionCog):
    """Model Briar's W5/Q5/E1/R2 level-13 single-target duel fixture.

    The fixture lands Certain Death, uses Head Rush, enters Blood Frenzy,
    recasts Snack Attack, and ends with a fully charged Chilling Scream. The
    passive bleed uses a deterministic five-stack refresh schedule; dynamic
    missing-health amplification and geometry-dependent outcomes remain
    explicit verification blockers.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Briar.json",
        "data/raw/16.17.1/communitydragon/champions/233.json",
        "data/raw/16.17.1/communitydragon/champions/briar.bin.json",
    )

    _ATTACK_SPEED_RATIO = Decimal("0.669")
    _W5_ATTACK_SPEED_BONUS = Decimal("0.95")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose the fixed W and Q displacement available after contact.

        Certain Death's global missile and arrival path are deliberately not
        folded into this value because target distance and collision are absent.

        :param context: Role-bound snapshots for the current encounter.
        :return: Combined W maximum dash and Q cast range in game units.
        """
        return Decimal(775)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Blood Frenzy's rank-five pursuit speed multiplier.

        :param context: Role-bound snapshots for the fixed frenzy fixture.
        :return: Movement-speed multiplier while pursuing the selected target.
        """
        return Decimal("1.60")

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats that the fixed Briar model cannot consume.

        :param item: Normalized candidate from the locked item catalog.
        :return: Briar-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"BRIAR_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    @staticmethod
    def _q_cooldown_ms(context: ParticipantContext) -> int:
        """Calculate Q5's eight-second cooldown after ability haste.

        :param context: Briar snapshot supplying non-negative ability haste.
        :return: Rounded cooldown in milliseconds with a one-ms floor.
        """
        cooldown = Decimal(8000) * Decimal(100) / (Decimal(100) + context.snapshot.ability_haste)
        return max(1, int(cooldown.to_integral_value()))

    def _head_rush_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Q5 hits with their causally ordered armor reduction.

        :param context: Role-bound snapshots supplying AP, bonus AD, and haste.
        :return: In-horizon Head Rush events and stun outputs.
        """
        raw_damage = (
            Decimal(160)
            + Decimal("0.60") * context.snapshot.ability_power
            + Decimal("0.80") * context.snapshot.bonus_attack_damage
        )
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 500
        cooldown_ms = self._q_cooldown_ms(context)
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"BRIAR_Q_HEAD_RUSH_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        ResistanceReductionOutput(
                            context.opponent_entity,
                            "ARMOR",
                            Decimal("0.20"),
                            1,
                            5000,
                            f"BRIAR_Q_ARMOR_SHRED_{context.self_entity.value}",
                        ),
                        damage(context.opponent_entity, raw_damage, DamageType.PHYSICAL),
                        crowd_control(context.opponent_entity, "STUN", duration_ms=850),
                    ),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def _frenzy_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build W5-accelerated attacks and one Snack Attack reset.

        :param context: Role-bound snapshots supplying attack and health stats.
        :return: Blind-susceptible frenzy attacks through the E channel start.
        """
        frenzy_speed = (
            context.snapshot.attack_speed + self._ATTACK_SPEED_RATIO * self._W5_ATTACK_SPEED_BONUS
        )
        interval_ms = self._attack_interval_ms(frenzy_speed)
        base = self._sequence_base(context) + 200
        bite_base = Decimal(65) + Decimal("1.05") * context.snapshot.attack_damage
        bite_missing_ratio = (
            Decimal("0.09") + Decimal("0.00025") * context.snapshot.bonus_attack_damage
        )
        bite_heal = Decimal("0.40") * bite_base + Decimal("0.05") * context.snapshot.max_hp
        events: list[ActionEvent] = []
        at_ms = 900
        attack_number = 1
        while at_ms < 6000 and at_ms <= context.duration_ms:
            events.append(
                action(
                    f"BRIAR_W_FRENZY_ATTACK_{attack_number}",
                    at_ms=at_ms,
                    sequence=base + attack_number,
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
            attack_number += 1
            at_ms += interval_ms

        events.append(
            action(
                "BRIAR_W_SNACK_ATTACK",
                at_ms=min(2800, context.duration_ms),
                sequence=base + 90,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    MissingHealthDamageOutput(
                        context.opponent_entity,
                        bite_base,
                        bite_missing_ratio,
                        DamageType.PHYSICAL,
                    ),
                    healing(context.self_entity, bite_heal),
                ),
            )
        )
        return tuple(events)

    def _passive_events(
        self,
        context: ParticipantContext,
        applications: tuple[int, ...],
    ) -> tuple[ActionEvent, ...]:
        """Resolve passive bleed ticks from the fixed application schedule.

        :param context: Briar snapshot supplying level and bonus attack damage.
        :param applications: Sorted timestamps that apply or refresh the bleed.
        :return: Half-second physical bleed ticks with base passive healing.
        """
        if not applications:
            return ()
        damage_per_second = (
            Decimal(2)
            + Decimal(8) * Decimal(context.snapshot.level - 1) / Decimal(17)
            + Decimal("0.10") * context.snapshot.bonus_attack_damage
        )
        base = self._sequence_base(context) + 500
        events: list[ActionEvent] = []
        tick_ms = applications[0] + 500
        last_application = applications[-1]
        while tick_ms <= min(context.duration_ms, last_application + 5000):
            active = tuple(
                timestamp
                for timestamp in applications
                if timestamp <= tick_ms and timestamp + 5000 >= tick_ms
            )
            if active:
                stacks = min(5, len(active))
                multiplier = Decimal(1) + Decimal("0.25") * Decimal(stacks - 1)
                tick_damage = damage_per_second * multiplier / Decimal(2)
                events.append(
                    action(
                        f"BRIAR_PASSIVE_BLEED_TICK_{len(events) + 1}",
                        at_ms=tick_ms,
                        sequence=base + len(events),
                        source=context.self_entity,
                        channel=ActionChannel.PASSIVE,
                        outputs=(
                            damage(
                                context.opponent_entity,
                                tick_damage,
                                DamageType.PHYSICAL,
                            ),
                            healing(context.self_entity, tick_damage * Decimal("0.25")),
                        ),
                    )
                )
            tick_ms += 500
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Briar's locked R-Q-W-attacks-bite-E duel sequence.

        :param context: Role-bound Briar and opponent snapshots.
        :return: Deterministic damage, sustain, control, and stat events.
        """
        base = self._sequence_base(context)
        q_events = self._head_rush_events(context)
        attacks = self._frenzy_attack_events(context)
        r_damage = Decimal(250) + Decimal("1.30") * context.snapshot.ability_power
        e_damage = (
            Decimal(80) + context.snapshot.bonus_attack_damage + context.snapshot.ability_power
        )
        fixed_events = (
            action(
                "BRIAR_R_CERTAIN_DEATH_IMPACT",
                at_ms=200,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.MAGIC),
                    StatModifierOutput(
                        context.self_entity,
                        "ARMOR",
                        Decimal("0.20") * context.snapshot.bonus_attack_damage,
                        7800,
                    ),
                    StatModifierOutput(
                        context.self_entity,
                        "MAGIC_RESISTANCE",
                        Decimal("0.20") * context.snapshot.bonus_attack_damage,
                        7800,
                    ),
                    StatusOutput(context.self_entity, "BRIAR_R_HEMOMANIA", 7800),
                    # Rank-two LifestealPercent while Hemomania lasts.
                    StatModifierOutput(context.self_entity, "LIFESTEAL", Decimal("0.15"), 7800),
                ),
            ),
            action(
                "BRIAR_W_BLOOD_FRENZY",
                at_ms=800,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "BRIAR_W_FRENZY", 5000),),
                requires_living_opponent=False,
            ),
            action(
                "BRIAR_E_CHILLING_SCREAM_START",
                at_ms=6000,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "BRIAR_E_CHARGING", 1000),),
                requires_living_opponent=False,
            ),
            action(
                "BRIAR_E_CHILLING_SCREAM_RELEASE",
                at_ms=7000,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    healing(
                        context.self_entity,
                        Decimal("0.10") * context.snapshot.max_hp,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=500,
                        magnitude=Decimal("0.80"),
                    ),
                    crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=500),
                ),
            ),
        )
        direct_events = (*fixed_events, *q_events, *attacks)
        application_times = tuple(
            sorted(
                event.at_ms
                for event in direct_events
                if event.id
                not in {
                    "BRIAR_W_BLOOD_FRENZY",
                    "BRIAR_E_CHILLING_SCREAM_START",
                }
            )
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"BRIAR_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "briar_w5_q5_e1_r2_level13_locked_v1",
            tuple(
                sorted(
                    (*direct_events, *self._passive_events(context, application_times)),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "BRIAR_LEVEL13_W5_Q5_E1_R2_POLICY_UNVERIFIED",
                "BRIAR_ROTATION_TIMING_UNVERIFIED",
                "BRIAR_PASSIVE_STACK_REFRESH_TIMING_UNVERIFIED",
                "BRIAR_PASSIVE_HEAL_POST_MITIGATION_ATTRIBUTION_UNVERIFIED",
                "BRIAR_PASSIVE_MISSING_HEALTH_HEAL_AMPLIFICATION_NOT_MODELED",
                "BRIAR_W_UNCONTROLLABLE_TARGET_SELECTION_NOT_MODELED",
                "BRIAR_W_BITE_DYNAMIC_DAMAGE_HEAL_ATTRIBUTION_PARTIAL",
                "BRIAR_W_ATTACK_RESET_TIMING_UNVERIFIED",
                "BRIAR_E_CHANNEL_INTERRUPTION_NOT_MODELED",
                "BRIAR_E_WALL_COLLISION_DAMAGE_AND_STUN_NOT_MODELED",
                "BRIAR_E_KNOCKBACK_DURATION_ASSUMED",
                "BRIAR_R_MISSILE_COLLISION_GLOBAL_PATH_NOT_MODELED",
                "BRIAR_R_AUTOMATIC_PURSUIT_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose E damage reduction and Briar's fixed control windows.

        :param context: Role-bound snapshots for the Briar participant.
        :return: E mitigation plus Q stun and E displacement intervals.
        """
        return ReactionPlan(
            "briar_q5_e1_reaction_v1",
            damage_windows=(
                DamageModifierWindow(
                    "briar_e_damage_reduction",
                    6000,
                    min(7000, context.duration_ms),
                    context.self_entity,
                    (DamageType.PHYSICAL, DamageType.MAGIC),
                    Decimal("0.65"),
                ),
            ),
            cast_block_windows=(
                CastBlockWindow(
                    "briar_q_stun",
                    500,
                    min(1350, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                        ActionChannel.ITEM_ACTIVE,
                    ),
                    "BRIAR_Q_HEAD_RUSH_1",
                    True,
                    ControlType.STUN,
                ),
                CastBlockWindow(
                    "briar_e_knockback",
                    7000,
                    min(7500, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                        ActionChannel.ITEM_ACTIVE,
                    ),
                    "BRIAR_E_CHILLING_SCREAM_RELEASE",
                    False,
                    ControlType.AIRBORNE,
                ),
            ),
            blockers=(
                "BRIAR_E_CHANNEL_INTERRUPTION_NOT_MODELED",
                "BRIAR_E_WALL_COLLISION_STUN_NOT_MODELED",
                "BRIAR_R_SECONDARY_TARGET_FEAR_OUTSIDE_SINGLE_TARGET_FIXTURE",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Decline to invent Briar lane sustain without a health trace.

        :param context: Role-bound Briar lane snapshot.
        :param duration_ms: Lane observation duration in milliseconds.
        :param no_damage_delay_ms: Required out-of-combat recovery delay.
        :return: Zero recovery and precise dynamic-state blockers.
        """
        return Decimal(0), (
            "BRIAR_LANE_TARGET_AND_ATTACK_SCHEDULE_NOT_MODELED",
            "BRIAR_LANE_MISSING_HEALTH_HEAL_SCALING_NOT_MODELED",
            "BRIAR_HAS_NO_INNATE_HEALTH_REGEN",
        )
