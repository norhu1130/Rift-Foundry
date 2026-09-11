"""Malzahar combat Cog backed by locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    CastBlockWindow,
    ChampionCog,
    CogMaturity,
    ControlImmunityWindow,
    ControlType,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, DamageModifierWindow, StatusOutput


class MalzaharCog(ChampionCog):
    """Model Malzahar's E5/Q5/W1/R2 refresh-and-suppress fixture.

    Malefic Visions ticks are segmented at Q and R refresh boundaries. Nether
    Grasp's beam and maximum-health pool use independent quarter-second events,
    allowing hostile control to cancel remaining channel outputs. Two stored W
    stacks summon three voidlings in the selected setup.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Malzahar.json",
        "data/raw/16.17.1/communitydragon/champions/90.json",
        "data/raw/16.17.1/communitydragon/champions/malzahar.bin.json",
    )

    _E_AT_MS = 0
    _Q_AT_MS = 1500
    _W_AT_MS = 1700
    _R_AT_MS = 2500
    _R_END_MS = 5000

    def _vision_segment(
        self,
        context: ParticipantContext,
        *,
        start_ms: int,
        stop_ms: int,
        label: str,
        sequence_offset: int,
    ) -> tuple[ActionEvent, ...]:
        """Schedule E ticks until the next refresh or natural expiration.

        :param context: Snapshot supplying AP, roles, and duration.
        :param start_ms: Timestamp at which this E duration begins.
        :param stop_ms: Exclusive refresh or expiry boundary.
        :param label: Stable segment identifier.
        :param sequence_offset: Disjoint sequence allocation.
        :return: Quarter-second Malefic Visions events.
        """
        tick = (Decimal(220) + Decimal("0.80") * context.snapshot.ability_power) / Decimal(16)
        base = self._sequence_base(context) + sequence_offset
        events: list[ActionEvent] = []
        for index in range(1, 17):
            at_ms = start_ms + index * 250
            if at_ms >= stop_ms or at_ms > context.duration_ms:
                break
            events.append(
                action(
                    f"MALZAHAR_E_MALEFIC_VISIONS_{label}_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(damage(context.opponent_entity, tick, DamageType.MAGIC),),
                )
            )
        return tuple(events)

    def _ultimate_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ten beam ticks and twenty pool ticks for Nether Grasp.

        :param context: Snapshot supplying AP, target health, and duration.
        :return: Individually cancellable beam and persistent pool events.
        """
        ap = context.snapshot.ability_power
        beam_tick = (Decimal(200) + Decimal("0.80") * ap) / Decimal(10)
        pool_total = context.opponent_snapshot.max_hp * (Decimal("0.15") + Decimal("0.00025") * ap)
        pool_tick = pool_total / Decimal(20)
        base = self._sequence_base(context) + 300
        events: list[ActionEvent] = []
        for index in range(1, 21):
            at_ms = self._R_AT_MS + index * 250
            if at_ms > context.duration_ms:
                break
            outputs = [damage(context.opponent_entity, pool_tick, DamageType.MAGIC)]
            if index <= 10:
                outputs.append(damage(context.opponent_entity, beam_tick, DamageType.MAGIC))
            events.append(
                action(
                    f"MALZAHAR_R_NETHER_GRASP_TICK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=(ActionChannel.ABILITY if index <= 10 else ActionChannel.PASSIVE),
                    outputs=tuple(outputs),
                )
            )
        return tuple(events)

    def _voidling_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule three voidlings at an explicit synthetic one-second cadence.

        :param context: Snapshot supplying damage stats and duration.
        :return: Aggregated three-voidling attack events.
        """
        level_base = Decimal(5) + (Decimal("64.5") - Decimal(5)) * (
            self.growth_multiplier(context.snapshot.level) / Decimal(17)
        )
        one = (
            Decimal(12)
            + level_base
            + Decimal("0.40") * context.snapshot.bonus_attack_damage
            + Decimal("0.20") * context.snapshot.ability_power
        )
        base = self._sequence_base(context) + 500
        return tuple(
            action(
                f"MALZAHAR_W_THREE_VOIDLINGS_ATTACK_{index}",
                at_ms=at_ms,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(damage(context.opponent_entity, Decimal(3) * one, DamageType.MAGIC),),
            )
            for index, at_ms in enumerate(
                range(self._W_AT_MS + 500, context.duration_ms + 1, 1000), start=1
            )
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Return neutral speed because Malzahar has no movement steroid.

        :param context: Role-bound Malzahar encounter context.
        :return: Neutral movement multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return zero because Malzahar has no displacement ability.

        :param context: Role-bound Malzahar encounter context.
        :return: Zero dash distance.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the selected spell fixture.

        :param item: Normalized candidate from the locked catalog.
        :return: Malzahar-scoped blocker, or ``None`` for represented stats.
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
            return f"MALZAHAR_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build E refreshes, Q silence, W summons, and R channel ticks.

        :param context: Role-bound Malzahar and opponent snapshots.
        :return: Deterministic level-13 action schedule.
        """
        ap = context.snapshot.ability_power
        base = self._sequence_base(context)
        fixed = (
            action(
                "MALZAHAR_E_MALEFIC_VISIONS_CAST",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.opponent_entity, "MALZAHAR_E", 4000),),
            ),
            action(
                "MALZAHAR_Q_CALL_OF_THE_VOID",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(210) + Decimal("0.55") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "SILENCE", duration_ms=2000),
                ),
            ),
            action(
                "MALZAHAR_W_VOID_SWARM_THREE",
                at_ms=self._W_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "MALZAHAR_THREE_VOIDLINGS", 8000),),
                requires_living_opponent=False,
            ),
            action(
                "MALZAHAR_R_NETHER_GRASP_START",
                at_ms=self._R_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(crowd_control(context.opponent_entity, "SUPPRESSION", duration_ms=2500),),
            ),
        )
        events = [*fixed]
        events.extend(
            self._vision_segment(
                context, start_ms=0, stop_ms=self._Q_AT_MS, label="INITIAL", sequence_offset=100
            )
        )
        events.extend(
            self._vision_segment(
                context,
                start_ms=self._Q_AT_MS,
                stop_ms=self._R_AT_MS,
                label="Q_REFRESH",
                sequence_offset=150,
            )
        )
        events.extend(
            self._vision_segment(
                context,
                start_ms=self._R_AT_MS,
                stop_ms=self._R_AT_MS + 4001,
                label="R_REFRESH",
                sequence_offset=200,
            )
        )
        events.extend(self._ultimate_events(context))
        events.extend(self._voidling_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"MALZAHAR_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "malzahar_e5_q5_w1_r2_refresh_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "MALZAHAR_LEVEL13_E5_Q5_W1_R2_ORDER_LOCKED_UNVERIFIED",
                "MALZAHAR_W_THREE_VOIDLINGS_FROM_TWO_STORED_STACKS_ASSUMED",
                "MALZAHAR_VOIDLING_ONE_SECOND_ATTACK_CADENCE_SYNTHETIC",
                "MALZAHAR_E_Q_AND_R_REFRESH_BOUNDARIES_SYNTHETIC",
                "MALZAHAR_R_TARGET_REMAINS_IN_POOL_FOR_FIVE_SECONDS_ASSUMED",
                "MALZAHAR_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose passive protection, Q silence, and R suppression.

        :param context: Role-bound Malzahar and opponent snapshots.
        :return: Defensive and hostile-control windows.
        """
        return ReactionPlan(
            "malzahar_passive_q5_r2_reaction_v1",
            damage_windows=(
                DamageModifierWindow(
                    "malzahar_void_shift_damage_reduction",
                    0,
                    250,
                    context.self_entity,
                    (DamageType.PHYSICAL, DamageType.MAGIC, DamageType.TRUE),
                    Decimal("0.10"),
                ),
            ),
            cast_block_windows=(
                CastBlockWindow(
                    "malzahar_q_silence",
                    self._Q_AT_MS,
                    min(self._Q_AT_MS + 2000, context.duration_ms),
                    (ActionChannel.ABILITY,),
                    "MALZAHAR_Q_CALL_OF_THE_VOID",
                    True,
                    ControlType.SILENCE,
                ),
                CastBlockWindow(
                    "malzahar_r_suppression",
                    self._R_AT_MS,
                    min(self._R_END_MS, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT),
                    "MALZAHAR_R_NETHER_GRASP_START",
                    False,
                    ControlType.SUPPRESSION,
                ),
            ),
            control_immunity_windows=(
                ControlImmunityWindow(
                    "malzahar_void_shift_control_immunity",
                    0,
                    250,
                    context.self_entity,
                    (ControlType.ALL,),
                    None,
                ),
            ),
            blockers=("MALZAHAR_VOID_SHIFT_TRIGGER_AND_LINGER_TIMING_SYNTHETIC",),
        )
