"""Hwei combat Cog backed by the locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

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
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class HweiCog(ChampionCog):
    """Model Hwei's Q5/E5/W1/R2 WE-EQ-R-QQ-QE fixture.

    Stirring Lights empowers EQ, R attachment, and QQ in that order. EQ and R
    provide the two distinct damaging signatures required for one passive
    explosion. Spiraling Despair is split into twelve quarter-second damage
    ticks and its final detonation. The second Disaster cast selects QE once
    the shared Q cooldown expires.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Hwei.json",
        "data/raw/16.17.1/communitydragon/champions/910.json",
        "data/raw/16.17.1/communitydragon/champions/hwei.bin.json",
    )

    _WE_AT_MS = 0
    _EQ_AT_MS = 100
    _R_AT_MS = 500
    _QQ_AT_MS = 800
    _R_DURATION_MS = 3000

    @staticmethod
    def _cooldown_ms(seconds: Decimal, ability_haste: Decimal) -> int:
        """Convert a subject-wide cooldown through ability haste.

        :param seconds: Locked base cooldown in seconds.
        :param ability_haste: Non-negative haste supplied by the snapshot.
        :return: Deterministically rounded cooldown in milliseconds.
        :raises ValueError: If ability haste is negative.
        """
        if ability_haste < 0:
            raise ValueError("ability_haste must be non-negative")
        value = seconds * Decimal(100_000) / (Decimal(100) + ability_haste)
        return max(1, int(value.to_integral_value(ROUND_HALF_EVEN)))

    @staticmethod
    def _we_damage(context: ParticipantContext) -> Decimal:
        """Calculate one rank-one Stirring Lights damage proc.

        :param context: Snapshot supplying Hwei's ability power.
        :return: Raw magic damage for one of the three lights.
        """
        return Decimal(20) + Decimal("0.15") * context.snapshot.ability_power

    @staticmethod
    def _passive_damage(context: ParticipantContext) -> Decimal:
        """Calculate Signature of the Visionary damage at level 13.

        :param context: Snapshot supplying level and ability power.
        :return: Raw magic damage for one two-signature detonation.
        """
        level_fraction = Decimal(context.snapshot.level - 1) / Decimal(17)
        return (
            Decimal(40)
            + Decimal(245) * level_fraction
            + Decimal("0.35") * context.snapshot.ability_power
        )

    @staticmethod
    def _qq_damage(context: ParticipantContext) -> Decimal:
        """Calculate rank-five QQ including capped maximum-health damage.

        :param context: Hwei and opponent snapshots.
        :return: Raw single-target Devastating Fire damage.
        """
        health_bonus = min(
            Decimal(250),
            Decimal("0.07") * context.opponent_snapshot.max_hp,
        )
        return Decimal(170) + Decimal("0.80") * context.snapshot.ability_power + health_bonus

    def _r_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule R attachment, DOT quarters, and final explosion.

        :param context: Snapshot supplying AP, duration, and role bindings.
        :return: Chronological Spiraling Despair events.
        """
        base = self._sequence_base(context) + 200
        ap = context.snapshot.ability_power
        dot_per_second = Decimal(20) + Decimal("0.05") * ap
        events: list[ActionEvent] = [
            action(
                "HWEI_R_SPIRALING_DESPAIR_ATTACH",
                at_ms=self._R_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self._we_damage(context),
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=self._R_DURATION_MS,
                        magnitude=Decimal("0.10"),
                    ),
                    StatusOutput(
                        context.opponent_entity,
                        "HWEI_R_DESPAIR_STACKING",
                        self._R_DURATION_MS,
                    ),
                ),
            ),
            action(
                "HWEI_PASSIVE_SIGNATURE_EQ_R",
                at_ms=self._R_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self._passive_damage(context),
                        DamageType.MAGIC,
                    ),
                ),
            ),
        ]
        quarter_damage = dot_per_second / Decimal(4)
        for index in range(1, 13):
            at_ms = self._R_AT_MS + index * 250
            if at_ms > context.duration_ms:
                break
            events.append(
                action(
                    f"HWEI_R_SPIRALING_DESPAIR_DOT_{index}",
                    at_ms=at_ms,
                    sequence=base + 10 + index,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            quarter_damage,
                            DamageType.MAGIC,
                        ),
                    ),
                )
            )
        explosion_ms = self._R_AT_MS + self._R_DURATION_MS
        if explosion_ms <= context.duration_ms:
            events.append(
                action(
                    "HWEI_R_SPIRALING_DESPAIR_EXPLOSION",
                    at_ms=explosion_ms,
                    sequence=base + 30,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal(325) + Decimal("0.80") * ap,
                            DamageType.MAGIC,
                        ),
                    ),
                )
            )
        return tuple(events)

    def _qe_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule the haste-dependent second Q subject cast as QE.

        :param context: Snapshot supplying AP, haste, duration, and roles.
        :return: QE impact and half-second lava ticks when available.
        """
        at_ms = self._QQ_AT_MS + self._cooldown_ms(Decimal(6), context.snapshot.ability_haste)
        if at_ms > context.duration_ms:
            return ()
        base = self._sequence_base(context) + 400
        ap = context.snapshot.ability_power
        impact = Decimal(80) + Decimal("0.30") * ap
        damage_per_second = Decimal(80) + Decimal("0.24") * ap
        events: list[ActionEvent] = [
            action(
                "HWEI_QE_MOLTEN_FISSURE_IMPACT",
                at_ms=at_ms,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, impact, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=2500,
                        magnitude=Decimal("0.35"),
                    ),
                ),
            )
        ]
        for index in range(1, 6):
            tick_ms = at_ms + index * 500
            if tick_ms > context.duration_ms:
                break
            events.append(
                action(
                    f"HWEI_QE_MOLTEN_FISSURE_LAVA_{index}",
                    at_ms=tick_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            damage_per_second / Decimal(2),
                            DamageType.MAGIC,
                        ),
                    ),
                )
            )
        return tuple(events)

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks after the three Stirring Lights procs.

        :param context: Snapshot supplying attack damage, speed, and duration.
        :return: Chronological non-empowered basic attacks.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 600
        return tuple(
            action(
                f"HWEI_BASIC_ATTACK_{index}",
                at_ms=at_ms,
                sequence=base + index,
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
            for index, at_ms in enumerate(
                range(1800, context.duration_ms + 1, interval_ms),
                start=1,
            )
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Return neutral speed because this fixture selects WE instead of WQ.

        :param context: Role-bound Hwei encounter context.
        :return: Neutral movement multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return zero because Hwei has no displacement ability.

        :param context: Role-bound Hwei encounter context.
        :return: Zero dash distance.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the selected spellbook fixture.

        :param item: Normalized candidate from the locked catalog.
        :return: Hwei-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"HWEI_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build WE, EQ, R, QQ, QE, passive, and follow-up attacks.

        :param context: Role-bound Hwei and opponent snapshots.
        :return: Deterministic selected-variant action schedule.
        """
        base = self._sequence_base(context)
        we_damage = self._we_damage(context)
        fixed = (
            action(
                "HWEI_WE_STIRRING_LIGHTS",
                at_ms=self._WE_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "HWEI_WE_THREE_LIGHTS", 9000),),
                requires_living_opponent=False,
            ),
            action(
                "HWEI_EQ_GRIM_VISAGE",
                at_ms=self._EQ_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(230) + Decimal("0.65") * context.snapshot.ability_power,
                        DamageType.MAGIC,
                    ),
                    damage(context.opponent_entity, we_damage, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "FEAR", duration_ms=1500),
                ),
            ),
            action(
                "HWEI_QQ_DEVASTATING_FIRE",
                at_ms=self._QQ_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, self._qq_damage(context), DamageType.MAGIC),
                    damage(context.opponent_entity, we_damage, DamageType.MAGIC),
                ),
            ),
        )
        events = (
            *fixed,
            *self._r_events(context),
            *self._qe_events(context),
            *self._attack_events(context),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"HWEI_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "hwei_q5_e5_w1_r2_we_eq_r_qq_qe_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "HWEI_LEVEL13_Q5_E5_W1_R2_LOCKED_RECOMMENDATION_UNVERIFIED",
                "HWEI_SELECTED_VARIANT_CAST_AND_PROJECTILE_TIMING_UNVERIFIED",
                "HWEI_EQ_R_FIRST_PASSIVE_PROC_ASSUMED",
                "HWEI_ADDITIONAL_PASSIVE_SIGNATURE_PROCS_NOT_MODELED",
                "HWEI_WE_MANA_RESTORE_NOT_MODELED",
                "HWEI_R_TARGET_REMAINS_ATTACHED_FOR_FULL_DURATION_ASSUMED",
                "HWEI_QE_TARGET_REMAINS_IN_LAVA_FOR_FULL_DURATION_ASSUMED",
                "HWEI_QW_WQ_WW_EW_EE_VARIANTS_OUTSIDE_SELECTED_ROTATION",
                "HWEI_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose selected EQ, R, and QE movement-control windows.

        :param context: Role-bound Hwei and opponent snapshots.
        :return: Fear and slow windows linked to their source events.
        """
        qe_events = self._qe_events(context)
        qe_windows = (
            (
                CastBlockWindow(
                    "hwei_qe_lava_slow",
                    qe_events[0].at_ms,
                    min(qe_events[0].at_ms + 2500, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "HWEI_QE_MOLTEN_FISSURE_IMPACT",
                    True,
                    ControlType.SLOW,
                ),
            )
            if qe_events
            else ()
        )
        return ReactionPlan(
            "hwei_eq5_r2_qe5_control_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "hwei_eq_grim_visage_fear",
                    self._EQ_AT_MS,
                    min(self._EQ_AT_MS + 1500, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "HWEI_EQ_GRIM_VISAGE",
                    True,
                    ControlType.FEAR,
                ),
                CastBlockWindow(
                    "hwei_r_spiraling_despair_slow",
                    self._R_AT_MS,
                    min(self._R_AT_MS + self._R_DURATION_MS, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "HWEI_R_SPIRALING_DESPAIR_ATTACH",
                    True,
                    ControlType.SLOW,
                ),
                *qe_windows,
            ),
            blockers=(
                "HWEI_R_QUARTER_SECOND_SLOW_STACK_MAGNITUDES_NOT_MODELED",
                "HWEI_UNSELECTED_CONTROL_VARIANTS_NOT_IN_REACTION_PLAN",
            ),
        )
