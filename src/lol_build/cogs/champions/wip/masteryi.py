"""Master Yi combat Cog backed by locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    ChampionCog,
    CogMaturity,
    ControlImmunityWindow,
    ControlType,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, damage, missing_health_healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, DamageModifierWindow, StatusOutput


class MasterYiCog(ChampionCog):
    """Model Q5/E5/W1/R2 with attack-driven Q cooldown reduction.

    Highlander and Wuju Style begin together. Alpha Strike hits one champion
    through all four bounces, then attacks proceed around a one-second Meditate
    channel. Every fourth attack adds Double Strike. Attack timestamps determine
    whether enough one-second refunds exist for a second Alpha Strike.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/MasterYi.json",
        "data/raw/16.17.1/communitydragon/champions/11.json",
        "data/raw/16.17.1/communitydragon/champions/masteryi.bin.json",
    )

    _Q_AT_MS = 200
    _W_START_MS = 5000
    _W_END_MS = 6000
    _ATTACK_SPEED_RATIO = Decimal("0.679")

    @staticmethod
    def _haste_adjusted_ms(base_ms: int, haste: Decimal) -> int:
        """Apply ability haste to one cooldown.

        :param base_ms: Locked cooldown in milliseconds.
        :param haste: Non-negative ability haste from the snapshot.
        :return: Positive adjusted cooldown in milliseconds.
        """
        return max(1, int(Decimal(base_ms) * Decimal(100) / (Decimal(100) + haste)))

    def _attack_times(self, context: ParticipantContext) -> tuple[int, ...]:
        """Build Highlander attack timestamps around Meditate.

        :param context: Snapshot supplying attack speed and encounter duration.
        :return: Ordered attack timestamps excluding the W channel.
        """
        speed = context.snapshot.attack_speed + self._ATTACK_SPEED_RATIO * Decimal("0.45")
        interval = self._attack_interval_ms(speed)
        times: list[int] = []
        at_ms = 900
        while at_ms <= context.duration_ms:
            if self._W_START_MS <= at_ms < self._W_END_MS:
                at_ms = self._W_END_MS
            times.append(at_ms)
            at_ms += interval
        return tuple(times)

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Wuju attacks and each fourth-hit Double Strike.

        :param context: Snapshot supplying AD, bonus AD, speed, and duration.
        :return: Chronological attack events with true-damage on-hit outputs.
        """
        true_on_hit = Decimal(40) + Decimal("0.35") * context.snapshot.bonus_attack_damage
        base = self._sequence_base(context) + 200
        events: list[ActionEvent] = []
        for index, at_ms in enumerate(self._attack_times(context), start=1):
            outputs = [
                damage(
                    context.opponent_entity,
                    context.snapshot.attack_damage,
                    DamageType.PHYSICAL,
                ),
                damage(context.opponent_entity, true_on_hit, DamageType.TRUE),
            ]
            if index % 4 == 0:
                outputs.extend(
                    (
                        damage(
                            context.opponent_entity,
                            Decimal("0.50") * context.snapshot.attack_damage,
                            DamageType.PHYSICAL,
                        ),
                        damage(
                            context.opponent_entity,
                            Decimal("0.50") * true_on_hit,
                            DamageType.TRUE,
                        ),
                    )
                )
            events.append(
                action(
                    f"MASTER_YI_ATTACK_{index}{'_DOUBLE_STRIKE' if index % 4 == 0 else ''}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
        return tuple(events)

    def _alpha_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule first Q and a refund-enabled second Q when reachable.

        :param context: Snapshot supplying AD, crit, haste, and attack timestamps.
        :return: One or two single-target Alpha Strike events.
        """
        base_damage = Decimal(100) + Decimal("0.70") * context.snapshot.attack_damage
        expected_crit = Decimal(1) + Decimal("0.75") * context.snapshot.critical_strike_chance
        amount = base_damage * Decimal("1.75") * expected_crit
        cooldown = self._haste_adjusted_ms(18000, context.snapshot.ability_haste)
        cast_times = [self._Q_AT_MS]
        for refund_count, attack_at in enumerate(self._attack_times(context), start=1):
            if attack_at - self._Q_AT_MS + refund_count * 1000 >= cooldown:
                cast_times.append(attack_at + 1)
                break
        base = self._sequence_base(context) + 100
        return tuple(
            action(
                f"MASTER_YI_Q_ALPHA_STRIKE_{index}",
                at_ms=at_ms,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, amount, DamageType.PHYSICAL),),
            )
            for index, at_ms in enumerate(cast_times, start=1)
            if at_ms <= context.duration_ms
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Highlander's rank-two movement-speed multiplier.

        :param context: Role-bound Master Yi encounter context.
        :return: Movement multiplier during Highlander.
        """
        return Decimal("1.45")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Alpha Strike's locked target acquisition range.

        :param context: Role-bound Master Yi encounter context.
        :return: Targeted displacement range in game units.
        """
        return Decimal(600)

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Avoid treating a mana channel as unconditional lane sustain.

        :param context: Role-bound Master Yi encounter context.
        :param duration_ms: Requested lane observation duration.
        :param no_damage_delay_ms: Time since the last incoming damage event.
        :return: Zero healing and resource/missing-health blockers.
        """
        return Decimal(0), ("MASTER_YI_W_REQUIRES_MANA_AND_MISSING_HEALTH_STATE",)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats absent from Master Yi's fixed fixture.

        :param item: Normalized candidate from the locked catalog.
        :return: Master-Yi-scoped blocker, or ``None`` for represented stats.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            return f"MASTER_YI_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build R/E activation, Alpha Strikes, attacks, and partial Meditate.

        :param context: Role-bound Master Yi and opponent snapshots.
        :return: Deterministic level-13 action schedule.
        """
        base = self._sequence_base(context)
        meditate_tick = (Decimal(120) + context.snapshot.ability_power) / Decimal(8)
        # MaxMissingHealthPercent = 1: each tick grows by up to 100% with missing
        # health. tick * (1 + missing / max) is tick plus (tick / max) of missing.
        meditate = missing_health_healing(
            context.self_entity,
            meditate_tick / context.snapshot.max_hp,
            base_amount=meditate_tick,
        )
        fixed = (
            action(
                "MASTER_YI_R_HIGHLANDER",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "MASTER_YI_HIGHLANDER", 8000),),
                requires_living_opponent=False,
            ),
            action(
                "MASTER_YI_E_WUJU_STYLE",
                at_ms=0,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "MASTER_YI_WUJU_STYLE", 6000),),
                requires_living_opponent=False,
            ),
            action(
                "MASTER_YI_W_MEDITATE_TICK_1",
                at_ms=5500,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(meditate,),
                requires_living_opponent=False,
            ),
            action(
                "MASTER_YI_W_MEDITATE_TICK_2",
                at_ms=6000,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(meditate,),
                requires_living_opponent=False,
            ),
        )
        events = (*fixed, *self._alpha_events(context), *self._attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"MASTER_YI_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "master_yi_q5_e5_w1_r2_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "MASTER_YI_LEVEL13_Q5_E5_W1_R2_ORDER_LOCKED_UNVERIFIED",
                "MASTER_YI_Q_ALL_FOUR_BOUNCES_HIT_ONE_CHAMPION_ASSUMED",
                "MASTER_YI_Q_CRITICAL_STRIKE_MODELED_AS_EXPECTED_DAMAGE",
                "MASTER_YI_Q_ON_HIT_EFFECTIVENESS_NOT_MODELED",
                "MASTER_YI_W_ONE_SECOND_CHANNEL_SELECTED",
                "MASTER_YI_W_MISSING_HEALTH_AMPLIFICATION_READ_AS_LINEAR",
                "MASTER_YI_W_PAUSES_E_AND_R_FOR_ONE_SECOND_ASSUMED",
                "MASTER_YI_TAKEDOWN_EXTENSIONS_AND_COOLDOWN_REFUNDS_OUTSIDE_DUEL",
                "MASTER_YI_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Meditate damage reduction and Highlander slow immunity.

        :param context: Role-bound Master Yi and opponent snapshots.
        :return: Timed defensive and control-immunity windows.
        """
        return ReactionPlan(
            "master_yi_w1_r2_reaction_v1",
            damage_windows=(
                DamageModifierWindow(
                    "master_yi_w_initial_damage_reduction",
                    5000,
                    min(5500, context.duration_ms),
                    context.self_entity,
                    (DamageType.PHYSICAL, DamageType.MAGIC),
                    Decimal("0.30"),
                ),
                DamageModifierWindow(
                    "master_yi_w_damage_reduction",
                    5500,
                    min(6500, context.duration_ms),
                    context.self_entity,
                    (DamageType.PHYSICAL, DamageType.MAGIC),
                    Decimal("0.575"),
                ),
            ),
            control_immunity_windows=(
                ControlImmunityWindow(
                    "master_yi_r_slow_immunity",
                    0,
                    context.duration_ms,
                    context.self_entity,
                    (ControlType.SLOW,),
                    "MASTER_YI_R_HIGHLANDER",
                ),
            ),
            blockers=(
                "MASTER_YI_Q_UNTARGETABILITY_TARGET_SELECTION_NOT_MODELED",
                "MASTER_YI_W_CHANNEL_INTERRUPTION_USES_SHARED_CAST_BLOCKING",
            ),
        )
