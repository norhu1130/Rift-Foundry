"""Miss Fortune combat Cog backed by locked 16.17.1 sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class MissFortuneCog(ChampionCog):
    """Model a Q5/W5/E1/R2 level-13 single-target rotation.

    Make It Rain ticks eight times, Double Up hits its primary target, Strut
    accelerates attacks before Bullet Time, and the ultimate emits sixteen
    independently cancellable waves. Bounce geometry and target alternation
    are deliberately excluded from this one-opponent fixture.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/MissFortune.json",
        "data/raw/16.17.1/communitydragon/champions/21.json",
        "data/raw/16.17.1/communitydragon/champions/missfortune.bin.json",
    )

    _E_AT_MS = 0
    _Q_AT_MS = 250
    _W_AT_MS = 400
    _R_AT_MS = 2500
    _R_END_MS = 5500

    def _rain_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Split E1's two-second damage into eight locked ticks.

        :param context: Snapshot supplying AP, roles, and duration.
        :return: Quarter-second Make It Rain events.
        """
        tick = (Decimal(35) + Decimal("0.60") * context.snapshot.ability_power) / Decimal(4)
        base = self._sequence_base(context) + 100
        return tuple(
            action(
                f"MISS_FORTUNE_E_MAKE_IT_RAIN_{index}",
                at_ms=at_ms,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(damage(context.opponent_entity, tick, DamageType.MAGIC),),
            )
            for index, at_ms in enumerate(range(250, 2250, 250), start=1)
            if at_ms <= context.duration_ms
        )

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule W-accelerated attacks around the ultimate channel.

        :param context: Snapshot supplying attack damage, speed, and duration.
        :return: Synthetic attack clock with a four-second W steroid.
        """
        normal = self._attack_interval_ms(context.snapshot.attack_speed)
        accelerated = self._attack_interval_ms(context.snapshot.attack_speed * Decimal(2))
        base = self._sequence_base(context) + 300
        times = list(range(500, self._R_AT_MS, accelerated))
        times.extend(range(self._R_END_MS, context.duration_ms + 1, normal))
        return tuple(
            action(
                f"MISS_FORTUNE_BASIC_ATTACK_{index}",
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
            for index, at_ms in enumerate(times, start=1)
            if at_ms <= context.duration_ms
        )

    def _ultimate_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule sixteen R2 waves with expected critical damage.

        :param context: Snapshot supplying AD, AP, crit chance, and roles.
        :return: Individually cancellable Bullet Time wave events.
        """
        raw = (
            Decimal(30)
            + Decimal("0.60") * context.snapshot.attack_damage
            + Decimal("0.25") * context.snapshot.ability_power
        )
        expected_crit = Decimal(1) + context.snapshot.critical_strike_chance * Decimal("0.225")
        amount = raw * expected_crit
        base = self._sequence_base(context) + 600
        return tuple(
            action(
                f"MISS_FORTUNE_R_BULLET_TIME_WAVE_{index}",
                at_ms=self._R_AT_MS + (index - 1) * 187,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, amount, DamageType.PHYSICAL),),
            )
            for index in range(1, 17)
            if self._R_AT_MS + (index - 1) * 187 <= context.duration_ms
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Convert W5's out-of-combat flat speed into a snapshot multiplier.

        :param context: Role-bound Miss Fortune encounter context.
        :return: Ratio after adding the locked one-hundred movement speed.
        """
        return (context.snapshot.move_speed + Decimal(100)) / context.snapshot.move_speed

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return zero because Miss Fortune has no displacement ability.

        :param context: Role-bound Miss Fortune encounter context.
        :return: Zero dash distance.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the selected fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Champion-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "MANA_REGEN",
            "OMNIVAMP",
        } & stats.keys()
        if unsupported:
            return (
                f"MISS_FORTUNE_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
            )
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build E, primary Q, W attacks, and the R channel.

        :param context: Role-bound Miss Fortune and opponent snapshots.
        :return: Deterministic level-13 action schedule.
        """
        ap = context.snapshot.ability_power
        base = self._sequence_base(context)
        q = Decimal(120) + context.snapshot.attack_damage + Decimal("0.35") * ap
        love_tap = context.snapshot.attack_damage
        fixed = (
            action(
                "MISS_FORTUNE_E_MAKE_IT_RAIN_CAST",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=2000,
                        magnitude=Decimal("0.40") + Decimal("0.0006") * ap,
                    ),
                ),
            ),
            action(
                "MISS_FORTUNE_Q_DOUBLE_UP_PRIMARY",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q, DamageType.PHYSICAL),
                    damage(context.opponent_entity, love_tap, DamageType.PHYSICAL),
                ),
            ),
        )
        events = (
            *fixed,
            *self._rain_events(context),
            *self._attack_events(context),
            *self._ultimate_events(context),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"MISS_FORTUNE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "miss_fortune_q5_w5_e1_r2_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "MISS_FORTUNE_LEVEL13_Q5_W5_E1_R2_ORDER_UNVERIFIED",
                "MISS_FORTUNE_Q_SECOND_TARGET_BOUNCE_NOT_MODELED",
                "MISS_FORTUNE_Q_PRIMARY_LOVE_TAP_AVAILABLE_ASSUMED",
                "MISS_FORTUNE_LOVE_TAP_TARGET_ALTERNATION_NOT_MODELED",
                "MISS_FORTUNE_W_ATTACK_CLOCK_RESET_AND_REFUND_APPROXIMATED",
                "MISS_FORTUNE_E_TARGET_REMAINS_FOR_ALL_EIGHT_TICKS_ASSUMED",
                "MISS_FORTUNE_R_ALL_SIXTEEN_WAVES_HIT_ASSUMED",
                "MISS_FORTUNE_R_CRIT_EXPECTATION_USES_LOCKED_175_PERCENT_BASE_CRIT",
                "MISS_FORTUNE_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose E's movement slow and the interruptible R channel.

        :param context: Role-bound Miss Fortune and opponent snapshots.
        :return: Hostile slow window plus explicit channel blocker evidence.
        """
        return ReactionPlan(
            "miss_fortune_e_slow_r_channel_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "miss_fortune_e_make_it_rain_slow",
                    self._E_AT_MS,
                    min(2000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "MISS_FORTUNE_E_MAKE_IT_RAIN_CAST",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=(
                "MISS_FORTUNE_R_CHANNEL_EVENTS_CANCEL_WHEN_HOSTILE_CAST_BLOCK_OVERLAPS",
                "MISS_FORTUNE_E_MOVEMENT_MAGNITUDE_NOT_INTEGRATED_IN_TIMELINE",
            ),
        )
