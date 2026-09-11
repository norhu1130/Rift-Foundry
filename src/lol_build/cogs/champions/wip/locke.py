"""Locke combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing, health_cost
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    ExecuteOutput,
    StatusOutput,
)


class LockeCog(ChampionCog):
    """Model Locke's Q5/E5/W1/R2 three-nail duel fixture.

    The fixture fires all three Ritual Nails, consumes their marks with one
    attack, uses Ashen Pursuit for entry and its empowered follow-up, then casts
    Purgatory. Soul Ignition contributes its level-scaled attack and movement
    speed, six current-health costs, and only the deterministic recovery known
    without observing incoming damage.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Locke.json",
        "data/raw/16.17.1/communitydragon/champions/805.json",
        "data/raw/16.17.1/communitydragon/champions/locke.bin.json",
    )

    _W_AT_MS = 0
    _Q_TIMES = (100, 200, 300)
    _Q_CONSUME_AT_MS = 500
    _E_AT_MS = 900
    _E_ATTACK_AT_MS = 1100
    _R_AT_MS = 6500
    _W_END_MS = 6000
    _ATTACK_SPEED_RATIO = Decimal("0.625")

    @staticmethod
    def _level_interpolation(level: int, start: Decimal, end: Decimal) -> Decimal:
        """Linearly interpolate a locked level-one-to-eighteen value.

        :param level: Champion level in the supported game range.
        :param start: Value at level one.
        :param end: Value at level eighteen.
        :return: Interpolated value at ``level``.
        """
        return start + (end - start) * Decimal(level - 1) / Decimal(17)

    def _w_attack_speed_bonus(self, context: ParticipantContext) -> Decimal:
        """Calculate Soul Ignition's level-scaled attack-speed bonus.

        :param context: Snapshot supplying Locke's level.
        :return: Fractional attack-speed bonus during the six-second effect.
        """
        return self._level_interpolation(context.snapshot.level, Decimal("0.40"), Decimal("0.70"))

    @staticmethod
    def _passive_minimum_on_hit(context: ParticipantContext) -> Decimal:
        """Calculate the conservative passive on-hit endpoint.

        :param context: Snapshot supplying Locke's level and ability power.
        :return: Raw magic damage at the lower passive endpoint.
        """
        level_base = LockeCog._level_interpolation(context.snapshot.level, Decimal(5), Decimal(40))
        return level_base + Decimal("0.10") * context.snapshot.ability_power

    @staticmethod
    def _q_mark_damage(context: ParticipantContext) -> Decimal:
        """Calculate three rank-five marks with their locked 40% bonus.

        :param context: Snapshot supplying Locke's ability power.
        :return: Raw magic damage when one attack consumes all three marks.
        """
        one_mark = Decimal(50) + Decimal("0.35") * context.snapshot.ability_power
        return Decimal(3) * one_mark * Decimal("1.40")

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Soul Ignition attacks before and after its expiry.

        :param context: Snapshot supplying attack speed, AD, AP, and duration.
        :return: Chronological ordinary attacks with passive magic damage.
        """
        empowered_speed = (
            context.snapshot.attack_speed
            + self._ATTACK_SPEED_RATIO * self._w_attack_speed_bonus(context)
        )
        empowered_interval = self._attack_interval_ms(empowered_speed)
        normal_interval = self._attack_interval_ms(context.snapshot.attack_speed)
        times: list[int] = []
        at_ms = 1700
        while at_ms < min(self._W_END_MS, context.duration_ms + 1):
            times.append(at_ms)
            at_ms += empowered_interval
        at_ms = max(self._W_END_MS, at_ms)
        while at_ms <= context.duration_ms:
            times.append(at_ms)
            at_ms += normal_interval
        passive = self._passive_minimum_on_hit(context)
        base = self._sequence_base(context) + 300
        return tuple(
            action(
                f"LOCKE_BASIC_ATTACK_{index}",
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
                    damage(context.opponent_entity, passive, DamageType.MAGIC),
                ),
            )
            for index, at_ms in enumerate(times, start=1)
        )

    def _w_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Soul Ignition status, health costs, and known recovery.

        :param context: Snapshot supplying AP, level, and role binding.
        :return: Persistent W events independent of opponent survival.
        """
        base = self._sequence_base(context) + 500
        events: list[ActionEvent] = [
            action(
                "LOCKE_W_SOUL_IGNITION_START",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "LOCKE_SOUL_IGNITION", 6000),),
                requires_living_opponent=False,
            )
        ]
        for index in range(1, 7):
            events.append(
                action(
                    f"LOCKE_W_CURRENT_HEALTH_COST_{index}",
                    at_ms=index * 1000,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(
                        health_cost(
                            context.self_entity,
                            current_health_ratio=Decimal("0.02"),
                        ),
                    ),
                    requires_living_opponent=False,
                )
            )
        deterministic_recovery = Decimal(40) + context.snapshot.ability_power
        events.append(
            action(
                "LOCKE_W_SOUL_IGNITION_END_RECOVERY",
                at_ms=self._W_END_MS,
                sequence=base + 20,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(healing(context.self_entity, deterministic_recovery),),
                requires_living_opponent=False,
            )
        )
        return tuple(events)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Soul Ignition's rank-one movement-speed multiplier.

        :param context: Snapshot supplying Locke's ability power.
        :return: Maximum movement multiplier before the one-second decay.
        """
        bonus = Decimal("0.40") + Decimal("0.0002") * context.snapshot.ability_power
        return Decimal(1) + bonus

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Combine Ashen Pursuit's cast range and locked bonus dash range.

        :param context: Role-bound Locke encounter context.
        :return: Maximum selected-fixture displacement in game units.
        """
        return Decimal(700)

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Avoid claiming W is positive sustain without damage history.

        :param context: Role-bound Locke encounter context.
        :param duration_ms: Requested lane observation duration.
        :param no_damage_delay_ms: Time since the last incoming damage event.
        :return: Zero health and an incoming-damage dependency blocker.
        """
        return Decimal(0), ("LOCKE_W_RECOVERY_REQUIRES_DAMAGE_HISTORY",)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Locke's fixed fixture.

        :param item: Normalized candidate from the locked catalog.
        :return: Locke-scoped blocker, or ``None`` for represented stats.
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
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"LOCKE_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build three Q missiles, marked attacks, E, W, and R execute.

        :param context: Role-bound Locke and opponent snapshots.
        :return: Deterministic level-13 action schedule.
        """
        ap = context.snapshot.ability_power
        base = self._sequence_base(context)
        q_events = tuple(
            action(
                f"LOCKE_Q_RITUAL_NAIL_{index}",
                at_ms=at_ms,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(72) + Decimal("0.20") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=2000 if index == 3 else 1000,
                        magnitude=Decimal("0.60") if index == 3 else Decimal("0.25"),
                    ),
                ),
            )
            for index, at_ms in enumerate(self._Q_TIMES, start=1)
        )
        fixed = (
            action(
                "LOCKE_Q_THREE_MARK_CONSUME_ATTACK",
                at_ms=self._Q_CONSUME_AT_MS,
                sequence=base + 10,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity,
                        context.snapshot.attack_damage,
                        DamageType.PHYSICAL,
                    ),
                    damage(context.opponent_entity, self._q_mark_damage(context), DamageType.MAGIC),
                    damage(
                        context.opponent_entity,
                        self._passive_minimum_on_hit(context),
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "LOCKE_E_ASHEN_PURSUIT_DASH",
                at_ms=self._E_AT_MS,
                sequence=base + 11,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(120) + Decimal("0.40") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "LOCKE_E_ASHEN_PURSUIT_ATTACK",
                at_ms=self._E_ATTACK_AT_MS,
                sequence=base + 12,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity,
                        context.snapshot.attack_damage,
                        DamageType.PHYSICAL,
                    ),
                    damage(
                        context.opponent_entity,
                        Decimal(80) + Decimal("0.40") * ap,
                        DamageType.MAGIC,
                    ),
                    damage(
                        context.opponent_entity,
                        self._passive_minimum_on_hit(context),
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "LOCKE_R_PURGATORY",
                at_ms=self._R_AT_MS,
                sequence=base + 13,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(225) + Decimal("0.60") * ap,
                        DamageType.MAGIC,
                    ),
                    ExecuteOutput(context.opponent_entity, Decimal("0.11")),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=2000,
                        magnitude=Decimal("0.99"),
                    ),
                ),
            ),
        )
        events = (*q_events, *fixed, *self._attack_events(context), *self._w_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"LOCKE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "locke_q5_e5_w1_r2_three_nail_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "LOCKE_LEVEL13_Q5_E5_W1_R2_ORDER_LOCKED_UNVERIFIED",
                "LOCKE_Q_ALL_THREE_NAILS_HIT_AND_CONSUME_TOGETHER_ASSUMED",
                "LOCKE_PASSIVE_MINIMUM_ON_HIT_ENDPOINT_SELECTED",
                "LOCKE_PASSIVE_HEALTH_DEPENDENT_INTERPOLATION_NOT_MODELED",
                "LOCKE_W_TWO_PERCENT_CURRENT_HEALTH_TICK_CADENCE_UNVERIFIED",
                "LOCKE_W_INCOMING_DAMAGE_RESTORATION_NOT_MODELED",
                "LOCKE_W_HEAL_CAP_NOT_MODELED",
                "LOCKE_R_PERMANENT_EXECUTE_STACKS_NOT_MODELED",
                "LOCKE_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Q and R slows while preserving their distinct durations.

        :param context: Role-bound Locke and opponent snapshots.
        :return: Movement-control reaction windows linked to source events.
        """
        windows = [
            CastBlockWindow(
                f"locke_q_nail_slow_{index}",
                at_ms,
                min(at_ms + (2000 if index == 3 else 1000), context.duration_ms),
                (ActionChannel.MOVEMENT,),
                f"LOCKE_Q_RITUAL_NAIL_{index}",
                True,
                ControlType.SLOW,
            )
            for index, at_ms in enumerate(self._Q_TIMES, start=1)
        ]
        windows.append(
            CastBlockWindow(
                "locke_r_purgatory_slow",
                self._R_AT_MS,
                min(self._R_AT_MS + 2000, context.duration_ms),
                (ActionChannel.MOVEMENT,),
                "LOCKE_R_PURGATORY",
                True,
                ControlType.SLOW,
            )
        )
        return ReactionPlan(
            "locke_q5_r2_slow_reaction_v1",
            cast_block_windows=tuple(windows),
            blockers=("LOCKE_Q_SLOW_REFRESH_AND_STACK_ORDER_UNVERIFIED",),
        )
