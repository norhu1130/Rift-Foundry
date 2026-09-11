"""Lillia combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class LilliaCog(ChampionCog):
    """Model Lillia's Q5/W1/E5/R2 sleep-and-wake duel fixture.

    Swirlseed applies Dream Dust before Lilting Lullaby. The target reaches
    sleep, then a center Watch Out! Eep! hit wakes it and triggers R damage.
    Outer-edge Q casts provide both magic and true damage. Each passive DOT is
    truncated when a later spell refreshes it instead of overlapping copies.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Lillia.json",
        "data/raw/16.17.1/communitydragon/champions/876.json",
        "data/raw/16.17.1/communitydragon/champions/lillia.bin.json",
    )

    _E_AT_MS = 0
    _R_AT_MS = 400
    _SLEEP_AT_MS = 1900
    _W_AT_MS = 2100
    _FIRST_Q_AT_MS = 2600

    @staticmethod
    def _haste_adjusted_ms(base_ms: int, haste: Decimal) -> int:
        """Apply ability haste to one cooldown.

        :param base_ms: Locked base cooldown in milliseconds.
        :param haste: Non-negative ability haste from the snapshot.
        :return: Rounded cooldown with a one-millisecond floor.
        :raises ValueError: If haste is negative.
        """
        if haste < 0:
            raise ValueError("haste must be non-negative")
        return max(1, int(Decimal(base_ms) * Decimal(100) / (Decimal(100) + haste)))

    @staticmethod
    def _dust_total_damage(context: ParticipantContext) -> Decimal:
        """Calculate one full Dream Dust application against a champion.

        :param context: Snapshot supplying AP and opponent maximum health.
        :return: Raw magic damage over all six passive ticks.
        """
        ratio = Decimal("0.05") + Decimal("0.000125") * context.snapshot.ability_power
        return ratio * context.opponent_snapshot.max_hp

    @staticmethod
    def _dust_heal_per_tick(context: ParticipantContext) -> Decimal:
        """Approximate one champion-target passive heal tick at level 13.

        :param context: Snapshot supplying level and ability power.
        :return: Raw self-healing paired with one passive tick.
        """
        level_heal = Decimal(1) + Decimal(14) * Decimal(context.snapshot.level - 1) / Decimal(17)
        return level_heal + Decimal("0.05") * context.snapshot.ability_power

    def _dust_events(
        self,
        context: ParticipantContext,
        *,
        start_ms: int,
        stop_ms: int,
        label: str,
        sequence_offset: int,
    ) -> tuple[ActionEvent, ...]:
        """Schedule passive ticks until expiry or the next spell refresh.

        :param context: Role-bound snapshots and encounter duration.
        :param start_ms: Timestamp of the spell that applies Dream Dust.
        :param stop_ms: Exclusive timestamp of the next passive refresh.
        :param label: Stable identifier segment for this application.
        :param sequence_offset: Disjoint sequence allocation for the application.
        :return: Chronological damage-and-heal passive ticks.
        """
        damage_per_tick = self._dust_total_damage(context) / Decimal(6)
        heal_per_tick = self._dust_heal_per_tick(context)
        base = self._sequence_base(context) + sequence_offset
        events: list[ActionEvent] = []
        for index in range(1, 7):
            at_ms = start_ms + index * 500
            if at_ms >= stop_ms or at_ms > context.duration_ms:
                break
            events.append(
                action(
                    f"LILLIA_PASSIVE_DREAM_DUST_{label}_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(
                        damage(context.opponent_entity, damage_per_tick, DamageType.MAGIC),
                        healing(context.self_entity, heal_per_tick),
                    ),
                )
            )
        return tuple(events)

    def _q_cast_times(self, context: ParticipantContext) -> tuple[int, ...]:
        """Return haste-sensitive rank-five Q timestamps.

        :param context: Snapshot supplying haste and encounter duration.
        :return: Ordered Q cast timestamps within the benchmark.
        """
        interval = self._haste_adjusted_ms(4000, context.snapshot.ability_haste)
        return tuple(range(self._FIRST_Q_AT_MS, context.duration_ms + 1, interval))

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build outer-edge Q damage and refreshed passive applications.

        :param context: Role-bound snapshots and encounter duration.
        :return: Q casts followed by their non-overlapping passive ticks.
        """
        casts = self._q_cast_times(context)
        magic = Decimal(75) + Decimal("0.35") * context.snapshot.ability_power
        events: list[ActionEvent] = []
        base = self._sequence_base(context) + 300
        for index, at_ms in enumerate(casts, start=1):
            events.append(
                action(
                    f"LILLIA_Q_BLOOMING_BLOWS_OUTER_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, magic, DamageType.MAGIC),
                        damage(context.opponent_entity, magic, DamageType.TRUE),
                    ),
                )
            )
            next_cast = casts[index] if index < len(casts) else context.duration_ms + 1
            events.extend(
                self._dust_events(
                    context,
                    start_ms=at_ms,
                    stop_ms=next_cast,
                    label=f"Q{index}",
                    sequence_offset=400 + index * 10,
                )
            )
        return tuple(events)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose four Q5 Prance stacks including their AP scaling.

        :param context: Snapshot supplying Lillia's ability power.
        :return: Maximum selected-fixture movement-speed multiplier.
        """
        per_stack = Decimal("0.07") + Decimal("0.0003") * context.snapshot.ability_power
        return Decimal(1) + Decimal(4) * per_stack

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose W's maximum locked directional dash distance.

        :param context: Role-bound Lillia encounter context.
        :return: Dash distance in game units.
        """
        return Decimal(700)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the selected fixture.

        :param item: Normalized candidate from the locked catalog.
        :return: Lillia-scoped blocker, or ``None`` for represented stats.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"LILLIA_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the E-R-sleep-W-Q sequence and passive refreshes.

        :param context: Role-bound Lillia and opponent snapshots.
        :return: Deterministic level-13 action schedule.
        """
        ap = context.snapshot.ability_power
        base = self._sequence_base(context)
        fixed = (
            action(
                "LILLIA_E_SWIRLSEED",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(160) + Decimal("0.50") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=3000,
                        magnitude=Decimal("0.40"),
                    ),
                ),
            ),
            action(
                "LILLIA_R_LILTING_LULLABY_DROWSY",
                at_ms=self._R_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.opponent_entity, "LILLIA_DROWSY", 1500),),
            ),
            action(
                "LILLIA_R_LILTING_LULLABY_SLEEP",
                origin_event_id="LILLIA_R_LILTING_LULLABY_DROWSY",
                at_ms=self._SLEEP_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(crowd_control(context.opponent_entity, "SLEEP", duration_ms=2000),),
            ),
            action(
                "LILLIA_W_WATCH_OUT_EEP_CENTER_WAKE",
                at_ms=self._W_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(240) + Decimal("1.05") * ap,
                        DamageType.MAGIC,
                    ),
                    damage(
                        context.opponent_entity,
                        Decimal(150) + Decimal("0.40") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
        )
        events = [*fixed]
        events.extend(
            self._dust_events(
                context,
                start_ms=self._E_AT_MS,
                stop_ms=self._W_AT_MS,
                label="E",
                sequence_offset=100,
            )
        )
        events.extend(
            self._dust_events(
                context,
                start_ms=self._W_AT_MS,
                stop_ms=self._FIRST_Q_AT_MS,
                label="W",
                sequence_offset=200,
            )
        )
        events.extend(self._q_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"LILLIA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "lillia_q5_w1_e5_r2_sleep_wake_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "LILLIA_LEVEL13_Q5_E5_W1_R2_ORDER_UNVERIFIED",
                "LILLIA_E_AND_W_CENTER_HIT_ASSUMED",
                "LILLIA_R_WAKE_AT_FIRST_W_DAMAGE_ASSUMED",
                "LILLIA_PASSIVE_LEVEL_HEAL_INTERPOLATION_UNVERIFIED",
                "LILLIA_PASSIVE_REFRESH_BOUNDARY_SYNTHETIC",
                "LILLIA_PRANCE_STACK_UP_AND_FALLOFF_TIMELINE_NOT_MODELED",
                "LILLIA_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose E slow, R drowsy, and wake-truncated sleep windows.

        :param context: Role-bound Lillia and opponent snapshots.
        :return: Movement and all-action control windows.
        """
        return ReactionPlan(
            "lillia_e5_r2_control_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "lillia_e_swirlseed_slow",
                    self._E_AT_MS,
                    min(3000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "LILLIA_E_SWIRLSEED",
                    True,
                    ControlType.SLOW,
                ),
                CastBlockWindow(
                    "lillia_r_drowsy_slow",
                    self._R_AT_MS,
                    min(self._SLEEP_AT_MS, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "LILLIA_R_LILTING_LULLABY_DROWSY",
                    True,
                    ControlType.SLOW,
                ),
                CastBlockWindow(
                    "lillia_r_sleep_until_wake",
                    self._SLEEP_AT_MS,
                    min(self._W_AT_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "LILLIA_R_LILTING_LULLABY_SLEEP",
                    True,
                    ControlType.SLEEP,
                ),
            ),
            blockers=("LILLIA_DROWSY_PROGRESSIVE_SLOW_MAGNITUDE_NOT_MODELED",),
        )
