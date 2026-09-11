"""Nunu & Willump combat Cog backed by locked 16.17.1 sources."""

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
from lol_build.cogs.mechanics import action, damage, healing, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class NunuCog(ChampionCog):
    """Model Nunu's Q5/W1/E5/R2 level-13 maximum-channel fixture."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Nunu.json",
        "data/raw/16.17.1/communitydragon/champions/20.json",
        "data/raw/16.17.1/communitydragon/champions/nunu.bin.json",
    )

    _W_AT_MS = 0
    _Q_AT_MS = 200
    _E_AT_MS = 400
    _E_ROOT_AT_MS = 3400
    _R_START_MS = 3500
    _R_END_MS = 6500

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Call of the Freljord's triggered movement bonus.

        :param context: Role-bound Nunu encounter context.
        :return: Ten-percent movement-speed multiplier after champion damage.
        """
        return Decimal("1.10")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose the locked maximum Biggest Snowball roll distance.

        :param context: Role-bound Nunu encounter context.
        :return: Maximum snowball travel in game units.
        """
        return Decimal(1750)

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Avoid inventing Consume targets, cooldowns, and health thresholds.

        :param context: Role-bound Nunu lane context.
        :param duration_ms: Requested lane observation duration.
        :param no_damage_delay_ms: Time since the last incoming damage event.
        :return: Zero recovery and the missing lane-state requirements.
        """
        return Decimal(0), ("NUNU_Q_LANE_HEAL_REQUIRES_TARGET_AND_CURRENT_HEALTH_TIMELINE",)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the selected Nunu fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Nunu-scoped blocker, or ``None`` for represented stats.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        return (
            f"NUNU_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
            if unsupported
            else None
        )

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks during the four-second passive attack-speed buff.

        :param context: Snapshot supplying AD, attack speed, crit, and duration.
        :return: Chronological expected-damage basic attacks before R begins.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed * Decimal("1.20"))
        amount = context.snapshot.attack_damage * (
            Decimal(1) + context.snapshot.critical_strike_chance
        )
        base = self._sequence_base(context) + 200
        return tuple(
            action(
                f"NUNU_PASSIVE_BUFFED_BASIC_ATTACK_{index}",
                at_ms=at_ms,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(damage(context.opponent_entity, amount, DamageType.PHYSICAL),),
            )
            for index, at_ms in enumerate(range(700, self._R_START_MS, interval), start=1)
            if at_ms <= context.duration_ms
        )

    def _snowball_barrage_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule all three rank-five E volleys as nine individual snowballs.

        :param context: Snapshot supplying AP, roles, and duration.
        :return: Nine evenly spaced magic-damage projectiles.
        """
        amount = Decimal(45) + Decimal("0.12") * context.snapshot.ability_power
        base = self._sequence_base(context) + 50
        timestamps = (400, 550, 700, 1300, 1450, 1600, 2200, 2350, 2500)
        return tuple(
            action(
                f"NUNU_E_SNOWBALL_BARRAGE_{index}",
                at_ms=at_ms,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, amount, DamageType.MAGIC),),
            )
            for index, at_ms in enumerate(timestamps, start=1)
            if at_ms <= context.duration_ms
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build maximum W, champion Q, three E volleys, and maximum R.

        :param context: Role-bound level-13 Nunu encounter context.
        :return: Deterministic eight-second spell and attack schedule.
        """
        ap = context.snapshot.ability_power
        bonus_hp = context.snapshot.bonus_health
        base = self._sequence_base(context)
        q_heal = Decimal("0.60") * (
            Decimal(185) + Decimal("0.10") * bonus_hp + Decimal("0.90") * ap
        )
        fixed = (
            action(
                "NUNU_W_BIGGEST_SNOWBALL_MAXIMUM",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.MOVEMENT,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(180) + Decimal("1.50") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "NUNU_Q_CONSUME_CHAMPION",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(220) + Decimal("0.05") * bonus_hp + Decimal("0.65") * ap,
                        DamageType.MAGIC,
                    ),
                    healing(context.self_entity, q_heal),
                ),
            ),
            action(
                "NUNU_E_SNOWBOUND_ROOT_DAMAGE",
                at_ms=self._E_ROOT_AT_MS,
                sequence=base + 100,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(60) + Decimal("0.80") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "NUNU_R_ABSOLUTE_ZERO_SHIELD",
                at_ms=self._R_START_MS,
                sequence=base + 101,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(
                        context.self_entity,
                        Decimal(75) + Decimal("0.40") * bonus_hp + Decimal("1.50") * ap,
                        duration_ms=6000,
                        decay_delay_ms=3000,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "NUNU_R_ABSOLUTE_ZERO_MAXIMUM_DETONATION",
                at_ms=self._R_END_MS,
                sequence=base + 102,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(925) + Decimal(3) * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
        )
        events = (*fixed, *self._snowball_barrage_events(context), *self._attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"NUNU_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "nunu_q5_w1_e5_r2_maximum_channel_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "NUNU_LEVEL13_Q5_E5_W1_R2_ORDER_LOCKED_UNVERIFIED",
                "NUNU_W_ASSUMED_MAXIMUM_FIVE_SECOND_GROWTH_BEFORE_TIMELINE",
                "NUNU_Q_ABOVE_HALF_HEALTH_HEAL_USED",
                "NUNU_E_ALL_NINE_SNOWBALLS_AND_ROOT_ASSUMED_TO_HIT",
                "NUNU_R_FULL_CHANNEL_ASSUMED_NOT_INTERRUPTED",
                "NUNU_PASSIVE_CLEAVE_HAS_NO_SECONDARY_TARGET",
                "NUNU_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose W knockup/stun, E slows/root, and R movement slow.

        :param context: Role-bound Nunu and opponent snapshots.
        :return: Hostile movement and action-control windows.
        """
        root_duration = int(
            (Decimal("0.5") + Decimal(context.snapshot.level - 1) / Decimal(17)) * Decimal(1000)
        )
        return ReactionPlan(
            "nunu_w1_e5_r2_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "nunu_w_maximum_knockup",
                    0,
                    500,
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT),
                    "NUNU_W_BIGGEST_SNOWBALL_MAXIMUM",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "nunu_w_maximum_stun",
                    500,
                    1250,
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT),
                    "NUNU_W_BIGGEST_SNOWBALL_MAXIMUM",
                    True,
                    ControlType.STUN,
                ),
                *tuple(
                    CastBlockWindow(
                        f"nunu_e_volley_{index}_slow",
                        at_ms,
                        min(at_ms + 1000, context.duration_ms),
                        (ActionChannel.MOVEMENT,),
                        f"NUNU_E_SNOWBALL_BARRAGE_{index * 3}",
                        True,
                        ControlType.SLOW,
                    )
                    for index, at_ms in enumerate((700, 1600, 2500), start=1)
                ),
                CastBlockWindow(
                    "nunu_e_snowbound_root",
                    self._E_ROOT_AT_MS,
                    min(self._E_ROOT_AT_MS + root_duration, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "NUNU_E_SNOWBOUND_ROOT_DAMAGE",
                    True,
                    ControlType.ROOT,
                ),
                CastBlockWindow(
                    "nunu_r_absolute_zero_slow",
                    self._R_START_MS,
                    self._R_END_MS,
                    (ActionChannel.MOVEMENT,),
                    "NUNU_R_ABSOLUTE_ZERO_SHIELD",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=(
                "NUNU_R_PROGRESSIVE_SLOW_MAGNITUDE_NOT_MODELED",
                "NUNU_R_CHANNEL_CANCELLATION_REQUIRES_PERSISTENT_CAST_CAUSALITY",
            ),
        )
