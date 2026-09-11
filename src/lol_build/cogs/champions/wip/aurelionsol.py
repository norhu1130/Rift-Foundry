"""Aurelion Sol combat Cog backed by the locked 16.17.1 sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, movement_speed
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class AurelionSolCog(ChampionCog):
    """Model a level-13 Q5/E5/W1/R2 single-target Aurelion Sol fixture.

    The fixture begins with fifty Stardust, below the seventy-five-stack
    empowered-ultimate threshold in the locked bin. Singularity and Falling
    Star establish control, Astral Flight closes distance, and Breath of Light
    is held for three complete one-second burst periods while flight supplies
    rank-one's eight-percent Q amplification.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/AurelionSol.json",
        "data/raw/16.17.1/communitydragon/champions/136.json",
        "data/raw/16.17.1/communitydragon/champions/aurelionsol.bin.json",
    )
    _STARDUST = Decimal(50)
    _E_AT_MS = 100
    _R_AT_MS = 400
    _W_AT_MS = 1200
    _Q_START_MS = 1600
    _Q_PERIODS = 3

    @staticmethod
    def _cooldown_ms(seconds: Decimal, ability_haste: Decimal) -> int:
        """Convert a locked base cooldown into deterministic milliseconds.

        :param seconds: Base cooldown in seconds from the locked spell bin.
        :param ability_haste: Non-negative ability haste on the snapshot.
        :return: Effective cooldown rounded to nearest-even milliseconds.
        """
        effective = seconds * Decimal(100) / (Decimal(100) + ability_haste)
        return max(
            1,
            int((effective * Decimal(1000)).to_integral_value(ROUND_HALF_EVEN)),
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Astral Flight's locked speed formula for approach scoring.

        :param context: Role-bound Aurelion Sol combat context.
        :return: Flight speed divided by ordinary movement speed.
        """
        return (Decimal(340) + context.snapshot.move_speed) / context.snapshot.move_speed

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return rank-one Astral Flight range at the fixed Stardust count.

        :param context: Role-bound context retained for the common hook contract.
        :return: Locked 1500 base range plus 7.5 units per fixture Stardust.
        """
        return Decimal(1500) + Decimal("7.5") * self._STARDUST

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the deterministic fixture.

        :param item: Normalized item candidate from the locked catalog.
        :return: Aurelion-Sol-scoped blocker, or ``None`` when representable.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "CRITICAL_STRIKE_CHANCE",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"AURELIONSOL_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule pre-channel attacks with the shared cadence conversion.

        :param context: Role-bound snapshot supplying attack damage and speed.
        :return: Physical attacks occurring before Breath of Light begins.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        sequence = self._sequence_base(context) + 500
        events: list[ActionEvent] = []
        at_ms = 650
        while at_ms < self._Q_START_MS and at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"AURELIONSOL_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=sequence + index,
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

    def _e_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Singularity damage fields when haste permits a recast.

        :param context: Role-bound snapshots supplying AP and combat horizon.
        :return: Deterministic Singularity tick events.
        """
        ap = context.snapshot.ability_power
        amount = Decimal(30) + Decimal("0.12") * ap
        cooldown_ms = self._cooldown_ms(Decimal(12), context.snapshot.ability_haste)
        sequence = self._sequence_base(context) + 20
        events: list[ActionEvent] = []
        cast_at_ms = self._E_AT_MS
        cast_index = 1
        while cast_at_ms <= context.duration_ms:
            for tick_index in range(1, 6):
                at_ms = cast_at_ms + (tick_index - 1) * 1000
                if at_ms > context.duration_ms:
                    break
                outputs = [damage(context.opponent_entity, amount, DamageType.MAGIC)]
                if tick_index == 1:
                    outputs.append(
                        crowd_control(
                            context.opponent_entity,
                            "PULL",
                            duration_ms=max(1, min(5000, context.duration_ms - at_ms)),
                        )
                    )
                events.append(
                    action(
                        f"AURELIONSOL_E_SINGULARITY_{cast_index}_TICK_{tick_index}",
                        at_ms=at_ms,
                        sequence=sequence + len(events),
                        source=context.self_entity,
                        channel=ActionChannel.ABILITY,
                        outputs=tuple(outputs),
                    )
                )
            cast_at_ms += cooldown_ms
            cast_index += 1
        return tuple(events)

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule three complete flight-amplified Q periods and bursts.

        :param context: Role-bound snapshots supplying AP and target maximum HP.
        :return: Three deterministic Q period events within the horizon.
        """
        ap = context.snapshot.ability_power
        amplification = Decimal("1.08")
        continuous = (Decimal(105) + Decimal("0.55") * ap) * amplification
        burst = (Decimal(100) + Decimal("0.30") * ap) * amplification
        stack_burst = (
            context.opponent_snapshot.max_hp * Decimal("0.00031") * self._STARDUST * amplification
        )
        sequence = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        for period in range(1, self._Q_PERIODS + 1):
            at_ms = self._Q_START_MS + period * 1000
            if at_ms > context.duration_ms:
                break
            events.append(
                action(
                    f"AURELIONSOL_Q_BREATH_PERIOD_{period}_FLIGHT",
                    at_ms=at_ms,
                    sequence=sequence + period,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, continuous, DamageType.MAGIC),
                        damage(context.opponent_entity, burst, DamageType.MAGIC),
                        damage(context.opponent_entity, stack_burst, DamageType.TRUE),
                    ),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the fixed E-R-W-Q control and flight-damage sequence.

        :param context: Role-bound Aurelion Sol and opponent snapshots.
        :return: Deterministic combat events with state-honest blockers.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        flight_speed = Decimal(340) + context.snapshot.move_speed
        fixed_events = (
            action(
                "AURELIONSOL_R_FALLING_STAR",
                at_ms=self._R_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(250) + Decimal("0.75") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=1000),
                ),
            ),
            action(
                "AURELIONSOL_W_ASTRAL_FLIGHT",
                at_ms=self._W_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.MOVEMENT,
                outputs=(
                    movement_speed(
                        context.self_entity,
                        flight_speed - context.snapshot.move_speed,
                        duration_ms=3500,
                    ),
                ),
                requires_living_opponent=False,
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"AURELIONSOL_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "aurelionsol_q5_e5_w1_r2_level13_stardust50_v1",
            tuple(
                sorted(
                    (
                        *self._e_events(context),
                        *fixed_events,
                        *self._basic_attacks(context),
                        *self._q_events(context),
                    ),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "AURELIONSOL_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "AURELIONSOL_STARDUST_FIXED_50_FIXTURE",
                "AURELIONSOL_DYNAMIC_STARDUST_GAIN_NOT_MODELED",
                "AURELIONSOL_Q_TARGET_TRACKING_AND_SIX_SEGMENT_TICKS_NOT_MODELED",
                "AURELIONSOL_Q_THREE_SECOND_CHANNEL_POLICY_UNVERIFIED",
                "AURELIONSOL_Q_MANA_DRAIN_NOT_MODELED",
                "AURELIONSOL_W_FLIGHT_POSITION_AND_TERRAIN_NOT_MODELED",
                "AURELIONSOL_W_Q_AMPLIFICATION_SCOPE_UNVERIFIED",
                "AURELIONSOL_E_CURRENT_HP_EXECUTE_NOT_MODELED",
                "AURELIONSOL_E_PULL_POSITION_NOT_MODELED",
                "AURELIONSOL_E_CAST_DURING_Q_CHANNEL_POLICY_UNVERIFIED",
                "AURELIONSOL_R_IMPACT_POSITION_NOT_MODELED",
                "AURELIONSOL_MULTI_TARGET_EFFECTS_NOT_MODELED",
                "AURELIONSOL_CAST_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Singularity pull and Falling Star stun windows.

        :param context: Role-bound snapshots identifying the controlled opponent.
        :return: Movement pull and tenacity-reducible stun intervals.
        """
        return ReactionPlan(
            "aurelionsol_e_pull_r_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "aurelionsol_e_singularity_pull",
                    self._E_AT_MS,
                    min(self._E_AT_MS + 5000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "AURELIONSOL_E_SINGULARITY_1_TICK_1",
                    False,
                    ControlType.UNSPECIFIED,
                ),
                CastBlockWindow(
                    "aurelionsol_r_falling_star_stun",
                    self._R_AT_MS,
                    min(self._R_AT_MS + 1000, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "AURELIONSOL_R_FALLING_STAR",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(
                "AURELIONSOL_E_PULL_CONTROL_TYPE_UNREPRESENTED",
                "AURELIONSOL_E_PULL_POSITION_NOT_MODELED",
                "AURELIONSOL_R_HIT_TIMING_UNVERIFIED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Keep Aurelion Sol lane sustain at zero without inventing recovery.

        :param context: Role-bound combat context retained by the shared API.
        :param duration_ms: Lane observation window in milliseconds.
        :param no_damage_delay_ms: Recovery delay supplied by the caller.
        :return: Zero native recovery and explicit resource-model blocker.
        """
        return Decimal(0), ("AURELIONSOL_MANA_GATED_LANE_SUSTAIN_NOT_MODELED",)
