"""Nautilus combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class NautilusCog(ChampionCog):
    """Model Nautilus's Q5/W5/E1/R2 lock-down fixture.

    Q closes distance, W shields, the first attack applies Staggering Blow and
    one W damage-over-time instance, E emits three waves with repeat-hit
    penalties, and R resolves against its primary target. Per-target passive
    cooldown prevents a second root inside the eight-second encounter.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Nautilus.json",
        "data/raw/16.17.1/communitydragon/champions/111.json",
        "data/raw/16.17.1/communitydragon/champions/nautilus.bin.json",
    )

    _Q_AT_MS = 0
    _W_AT_MS = 100
    _PASSIVE_ATTACK_AT_MS = 300
    _E_AT_MS = 500
    _R_AT_MS = 2000

    def _w_dot_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Split one empowered attack's W5 damage over two seconds.

        :param context: Snapshot supplying AP, roles, and duration.
        :return: Four half-second Titan's Wrath damage ticks.
        """
        tick = (Decimal(70) + Decimal("0.40") * context.snapshot.ability_power) / Decimal(4)
        base = self._sequence_base(context) + 100
        return tuple(
            action(
                f"NAUTILUS_W_TITANS_WRATH_DOT_{index}",
                at_ms=self._PASSIVE_ATTACK_AT_MS + index * 500,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(damage(context.opponent_entity, tick, DamageType.MAGIC),),
            )
            for index in range(1, 5)
            if self._PASSIVE_ATTACK_AT_MS + index * 500 <= context.duration_ms
        )

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks after the passive-empowered opener.

        :param context: Snapshot supplying AD, attack speed, and duration.
        :return: First rooted attack and ordinary follow-up attacks.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 300
        times = range(self._PASSIVE_ATTACK_AT_MS, context.duration_ms + 1, interval)
        return tuple(
            action(
                "NAUTILUS_PASSIVE_STAGGERING_BLOW"
                if index == 1
                else f"NAUTILUS_BASIC_ATTACK_{index}",
                at_ms=at_ms,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity,
                        context.snapshot.attack_damage
                        + (Decimal(80) if index == 1 else Decimal(0)),
                        DamageType.PHYSICAL,
                    ),
                    *(
                        (crowd_control(context.opponent_entity, "ROOT", duration_ms=1250),)
                        if index == 1
                        else ()
                    ),
                ),
            )
            for index, at_ms in enumerate(times, start=1)
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Return neutral speed because Q supplies displacement.

        :param context: Role-bound Nautilus encounter context.
        :return: Neutral movement multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Q's locked cast range as maximum mutual closing reach.

        :param context: Role-bound Nautilus encounter context.
        :return: Dredge Line range in game units.
        """
        return Decimal(1150)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the selected fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Nautilus-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            return f"NAUTILUS_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Q, W, attacks, three E waves, R, and W damage ticks.

        :param context: Role-bound Nautilus and opponent snapshots.
        :return: Deterministic level-13 action schedule.
        """
        ap = context.snapshot.ability_power
        base = self._sequence_base(context)
        e_wave = Decimal(55) + Decimal("0.50") * ap
        fixed = [
            action(
                "NAUTILUS_Q_DREDGE_LINE",
                at_ms=self._Q_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(265) + Decimal("0.90") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "NAUTILUS_W_TITANS_WRATH_SHIELD",
                at_ms=self._W_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(
                        context.self_entity,
                        Decimal(90) + Decimal("0.12") * context.snapshot.max_hp,
                        duration_ms=6000,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "NAUTILUS_R_DEPTH_CHARGE_PRIMARY",
                at_ms=self._R_AT_MS,
                sequence=base + 20,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(275) + Decimal("0.80") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=500),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=1000),
                ),
            ),
        ]
        for index, multiplier in enumerate((Decimal(1), Decimal("0.50"), Decimal("0.50")), start=1):
            fixed.append(
                action(
                    f"NAUTILUS_E_RIPTIDE_WAVE_{index}",
                    at_ms=self._E_AT_MS + (index - 1) * 500,
                    sequence=base + 2 + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, e_wave * multiplier, DamageType.MAGIC),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=1250,
                            magnitude=Decimal("0.30"),
                        ),
                    ),
                )
            )
        events = (*fixed, *self._attack_events(context), *self._w_dot_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"NAUTILUS_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "nautilus_q5_w5_e1_r2_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "NAUTILUS_LEVEL13_Q5_W5_E1_R2_SUPPORT_ORDER_UNVERIFIED",
                "NAUTILUS_Q_MUTUAL_PULL_DURATION_AND_DISTANCE_SYNTHETIC",
                "NAUTILUS_W_REQUIRES_SHIELD_TO_PERSIST_FOR_ATTACK_DOT",
                "NAUTILUS_W_ONLY_FIRST_ATTACK_DOT_INSTANCE_MODELED",
                "NAUTILUS_E_ALL_THREE_WAVES_HIT_WITH_REPEAT_PENALTY_ASSUMED",
                "NAUTILUS_R_PRIMARY_CC_SPLIT_INTO_500MS_AIRBORNE_AND_1000MS_STUN",
                "NAUTILUS_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Q displacement, passive root, E slow, and R primary control.

        :param context: Role-bound Nautilus and opponent snapshots.
        :return: Deterministic hostile control windows.
        """
        all_active = (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT)
        return ReactionPlan(
            "nautilus_full_control_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "nautilus_q_dredge_line_displacement",
                    self._Q_AT_MS,
                    min(500, context.duration_ms),
                    all_active,
                    "NAUTILUS_Q_DREDGE_LINE",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "nautilus_passive_staggering_blow_root",
                    self._PASSIVE_ATTACK_AT_MS,
                    min(self._PASSIVE_ATTACK_AT_MS + 1250, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "NAUTILUS_PASSIVE_STAGGERING_BLOW",
                    True,
                    ControlType.ROOT,
                ),
                CastBlockWindow(
                    "nautilus_e_riptide_slow",
                    self._E_AT_MS,
                    min(self._E_AT_MS + 2250, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "NAUTILUS_E_RIPTIDE_WAVE_1",
                    True,
                    ControlType.SLOW,
                ),
                CastBlockWindow(
                    "nautilus_r_depth_charge_airborne",
                    self._R_AT_MS,
                    min(self._R_AT_MS + 500, context.duration_ms),
                    all_active,
                    "NAUTILUS_R_DEPTH_CHARGE_PRIMARY",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "nautilus_r_depth_charge_stun",
                    self._R_AT_MS + 500,
                    min(self._R_AT_MS + 1500, context.duration_ms),
                    all_active,
                    "NAUTILUS_R_DEPTH_CHARGE_PRIMARY",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(
                "NAUTILUS_Q_PULL_DURATION_UNVERIFIED",
                "NAUTILUS_R_PRIMARY_CC_PHASE_SPLIT_UNVERIFIED",
            ),
        )
