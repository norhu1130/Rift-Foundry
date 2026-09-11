"""Janna combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class JannaCog(ChampionCog):
    """Model Janna's Q1/W5/E5/R2 level-13 single-target fixture.

    Howling Gale is fully charged and hits the opponent, Eye of the Storm is
    cast on Janna, and Monsoon completes its three-second channel. Ally-only
    and additional-area recipients remain explicit blockers.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Janna.json",
        "data/raw/16.17.1/communitydragon/champions/40.json",
        "data/raw/16.17.1/communitydragon/champions/janna.bin.json",
    )

    _W_AT_MS = 100
    _E_AT_MS = 550
    _Q_IMPACT_AT_MS = 3300
    _R_AT_MS = 4300
    _R_HEAL_AT_MS = 7300

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose rank-five Zephyr's passive movement-speed multiplier.

        :param context: Role-bound Janna encounter context supplying AP.
        :return: Rank-five passive multiplier before soft movement-speed caps.
        """
        return Decimal("1.10") + Decimal("0.0002") * context.snapshot.ability_power

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Report that Janna has no displacement-based gap closer.

        :param context: Role-bound Janna encounter context.
        :return: Zero game units.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Janna's fixed duel policy.

        AP affects represented spells, shielding, healing, and engagement;
        attack damage and attack speed affect ordinary attacks. Heal/shield
        power is unavailable on champion snapshots and therefore stays blocked.

        :param item: Normalized candidate from the locked item catalog.
        :return: Janna-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"JANNA_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule deterministic attacks around the fixed spell fixture.

        :param context: Role-bound snapshots supplying attack damage and cadence.
        :return: Chronological physical basic-attack events.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        sequence = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 900
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"JANNA_BASIC_ATTACK_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=sequence + len(events),
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

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Janna's fixed damage, control, and attack sequence.

        Q uses its locked maximum three-second charge. R records only the one
        represented opponent's initial displacement; its self heal is supplied
        by the reaction plan so defensive effects remain grouped together.

        :param context: Role-bound Janna and opponent combat snapshots.
        :return: Deterministic Q/W/R and ordinary-attack events.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        fixed_events = (
            action(
                "JANNA_W_ZEPHYR",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(175) + Decimal("0.50") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=2000,
                        magnitude=Decimal("0.36") + Decimal("0.0006") * ap,
                    ),
                ),
            ),
            action(
                "JANNA_Q_HOWLING_GALE_MAX_CHARGE",
                at_ms=self._Q_IMPACT_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(85) + Decimal("0.80") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "AIRBORNE",
                        duration_ms=1250,
                    ),
                ),
            ),
            action(
                "JANNA_R_MONSOON_KNOCKBACK",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    crowd_control(
                        context.opponent_entity,
                        "AIRBORNE",
                        duration_ms=500,
                    ),
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"JANNA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "janna_q1_w5_e5_r2_level13_locked_v1",
            tuple(
                sorted(
                    (*fixed_events, *self._basic_attacks(context)),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "JANNA_LEVEL13_Q1_W5_E5_R2_POLICY_UNVERIFIED",
                "JANNA_Q_MAX_CHARGE_AND_SINGLE_TARGET_HIT_FIXTURE",
                "JANNA_Q_CHARGE_AND_MISSILE_TRAVEL_TIMING_UNVERIFIED",
                "JANNA_W_PASSIVE_DISABLED_AFTER_CAST_NOT_MODELED",
                "JANNA_E_ALLY_AND_TURRET_TARGETS_NOT_REPRESENTED",
                "JANNA_E_BONUS_ATTACK_DAMAGE_NOT_MODELED",
                "JANNA_E_CC_COOLDOWN_REFUND_NOT_MODELED",
                "JANNA_R_ADDITIONAL_ENEMIES_NOT_REPRESENTABLE_IN_TWO_COMBATANT_DUEL",
                "JANNA_R_ALLY_HEALING_NOT_REPRESENTABLE_IN_TWO_COMBATANT_DUEL",
                "JANNA_R_CHANNEL_INTERRUPTION_AND_EARLY_END_NOT_MODELED",
                "JANNA_PASSIVE_ALLY_MOVEMENT_SPEED_NOT_REPRESENTABLE",
                "JANNA_PASSIVE_BONUS_MOVE_SPEED_ON_HIT_NOT_MODELED",
                "JANNA_CAST_AND_ATTACK_TIMING_UNVERIFIED",
                "JANNA_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Q/W/R control, self shielding, and self healing.

        E is deliberately self-cast. Monsoon healing is aggregated when the
        fixed uninterrupted channel completes because the locked source does
        not expose a reliable timeline tick phase.

        :param context: Role-bound Janna and opponent combat snapshots.
        :return: Defensive events and causally linked control windows.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        return ReactionPlan(
            "janna_q1_w5_e5_r2_reaction_locked_v1",
            events=(
                action(
                    "JANNA_E_EYE_OF_THE_STORM_SELF",
                    at_ms=self._E_AT_MS,
                    sequence=base + 500,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        shielding(
                            context.self_entity,
                            Decimal(240) + Decimal("0.55") * ap,
                            duration_ms=4000,
                        ),
                    ),
                    requires_living_opponent=False,
                ),
                action(
                    "JANNA_R_MONSOON_SELF_HEAL_COMPLETE",
                    at_ms=self._R_HEAL_AT_MS,
                    sequence=base + 501,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(
                        healing(
                            context.self_entity,
                            Decimal(450) + Decimal("1.50") * ap,
                        ),
                    ),
                    requires_living_opponent=False,
                ),
            ),
            cast_block_windows=(
                CastBlockWindow(
                    "janna_w_zephyr_slow",
                    self._W_AT_MS,
                    min(self._W_AT_MS + 2000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "JANNA_W_ZEPHYR",
                    True,
                    ControlType.SLOW,
                ),
                CastBlockWindow(
                    "janna_q_howling_gale_airborne",
                    self._Q_IMPACT_AT_MS,
                    min(self._Q_IMPACT_AT_MS + 1250, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "JANNA_Q_HOWLING_GALE_MAX_CHARGE",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "janna_r_monsoon_knockback",
                    self._R_AT_MS,
                    min(self._R_AT_MS + 500, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "JANNA_R_MONSOON_KNOCKBACK",
                    False,
                    ControlType.AIRBORNE,
                ),
            ),
            blockers=(
                "JANNA_E_SELF_CAST_FIXTURE_UNVERIFIED",
                "JANNA_E_SHIELD_DECAY_AFTER_FOUR_SECONDS_HAS_NO_ACTIVE_INTERVAL",
                "JANNA_R_HEAL_AGGREGATED_AFTER_FULL_CHANNEL",
                "JANNA_R_HEAL_TICK_PHASE_NOT_IN_LOCKED_SOURCE",
                "JANNA_R_HEAL_CANCEL_CAUSALITY_NOT_MODELED",
                "JANNA_R_KNOCKBACK_DISTANCE_AND_DIRECTION_NOT_MODELED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Decline to invent repeated shield, channel, or mana schedules.

        :param context: Role-bound Janna lane snapshot.
        :param duration_ms: Lane observation window in milliseconds.
        :param no_damage_delay_ms: Delay before out-of-combat recovery begins.
        :return: Zero extra health and explicit missing-schedule blockers.
        """
        return Decimal(0), (
            "JANNA_LANE_E_DAMAGE_TIMING_AND_TARGET_SCHEDULE_NOT_MODELED",
            "JANNA_LANE_R_CHANNEL_SCHEDULE_NOT_MODELED",
            "JANNA_LANE_MANA_BUDGET_NOT_MODELED",
        )
