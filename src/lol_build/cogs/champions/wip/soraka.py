"""Soraka combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing, movement_speed
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class SorakaCog(ChampionCog):
    """Model Soraka's Q5/W5/E1/R2 level-13 duel fixture.

    Starcall, Equinox, Wish, and ordinary attacks are represented against one
    enemy. Astral Infusion deliberately emits no event: its required allied
    target does not exist in the engine's two-opponent encounter contract, so
    neither its healing nor Soraka's health cost may be applied honestly.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Soraka.json",
        "data/raw/16.17.1/communitydragon/champions/16.json",
        "data/raw/16.17.1/communitydragon/champions/soraka.bin.json",
    )

    _Q_FIRST_AT_MS = 100
    _E_CAST_AT_MS = 500
    _E_EXPIRE_AT_MS = 2000
    _R_AT_MS = 2300
    _Q_SECOND_AT_MS = 4100
    _Q_HOT_DURATION_MS = 2500

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Avoid claiming ally-dependent Salvation as duel engagement power.

        :param context: Role-bound Soraka encounter context.
        :return: Neutral multiplier because no low-health ally is represented.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Report Soraka's absence of a displacement-based gap closer.

        :param context: Role-bound Soraka encounter context.
        :return: Zero game units.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Soraka's fixed duel policy.

        AP changes represented damage and self-healing, while attack speed and
        attack damage reach ordinary attacks. Healing amplification is blocked
        because champion snapshots do not yet carry that stat and W cannot be
        cast without an allied participant.

        :param item: Normalized candidate from the locked item catalog.
        :return: Soraka-scoped blocker, or ``None`` for represented channels.
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
            return f"SORAKA_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule deterministic attacks around Soraka's fixed spell casts.

        :param context: Role-bound snapshots supplying attack damage and cadence.
        :return: Chronological basic attacks susceptible to attack-channel control.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 900
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"SORAKA_BASIC_ATTACK_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=base + len(events),
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

    def _starcall_events(
        self,
        context: ParticipantContext,
        *,
        at_ms: int,
        cast_index: int,
    ) -> tuple[ActionEvent, ActionEvent]:
        """Create one Starcall hit and its delayed aggregate Rejuvenation heal.

        CommunityDragon records 225 plus 35 percent AP damage, 120 plus 30
        percent AP healing over 2.5 seconds, a 30 percent slow, and a 30 percent
        decaying self haste at rank five. The heal is aggregated at the end of
        the locked duration because the source does not expose tick cadence.

        :param context: Role-bound snapshots supplying Soraka's AP and movement.
        :param at_ms: Deterministic Starcall impact time.
        :param cast_index: One-based cast number used in stable event identifiers.
        :return: Hit event followed by the causally linked aggregate heal event.
        """
        base = self._sequence_base(context) + 10 * cast_index
        ap = context.snapshot.ability_power
        return (
            action(
                f"SORAKA_Q_STARCALL_{cast_index}",
                at_ms=at_ms,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("SorakaQ", "BaseDamage", context, Decimal(225))
                        + Decimal("0.35") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=1500,
                        magnitude=self.rank_value(
                            "SorakaQ", "MoveSpeedHaste", context, Decimal("0.30")
                        ),
                    ),
                    StatusOutput(
                        context.self_entity,
                        "SORAKA_Q_REJUVENATION",
                        self._Q_HOT_DURATION_MS,
                    ),
                    movement_speed(
                        context.self_entity,
                        context.snapshot.move_speed
                        * self.rank_value("SorakaQ", "MoveSpeedHaste", context, Decimal("0.30")),
                        duration_ms=self._Q_HOT_DURATION_MS,
                    ),
                ),
            ),
            action(
                f"SORAKA_Q_REJUVENATION_HEAL_{cast_index}",
                at_ms=at_ms + self._Q_HOT_DURATION_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(
                    healing(
                        context.self_entity,
                        self.rank_value("SorakaQ", "BaseHoT", context, Decimal(120))
                        + self.rank_value("SorakaQ", "MoveSpeedHaste", context, Decimal("0.30"))
                        * ap,
                    ),
                ),
                requires_living_opponent=False,
            ),
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Soraka's fixed Q5/W5/E1/R2 level-13 duel sequence.

        Equinox assumes the opponent remains in the field until expiration and
        therefore applies both damage instances and the delayed root. Wish heals
        Soraka at its normal rank-two value; its low-health amplification remains
        unresolved because event amounts are fixed before timeline health exists.

        :param context: Role-bound Soraka and opponent combat snapshots.
        :return: Deterministic spell, sustain, control, and attack events.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        e_damage = (
            self.rank_value("SorakaE", "BaseDamage", context, Decimal(70)) + Decimal("0.40") * ap
        )
        starcalls = (
            *self._starcall_events(
                context,
                at_ms=self._Q_FIRST_AT_MS,
                cast_index=1,
            ),
            *self._starcall_events(
                context,
                at_ms=self._Q_SECOND_AT_MS,
                cast_index=2,
            ),
        )
        fixed_events = (
            action(
                "SORAKA_E_EQUINOX_INITIAL",
                at_ms=self._E_CAST_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity,
                        "SILENCE",
                        duration_ms=1500,
                    ),
                ),
            ),
            action(
                "SORAKA_E_EQUINOX_EXPIRE",
                origin_event_id="SORAKA_E_EQUINOX_INITIAL",
                at_ms=self._E_EXPIRE_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity,
                        "ROOT",
                        duration_ms=1000,
                    ),
                ),
            ),
            action(
                "SORAKA_R_WISH_SELF",
                at_ms=self._R_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    healing(
                        context.self_entity,
                        self.rank_value("SorakaR", "BaseHeal", context, Decimal(250))
                        + Decimal("0.50") * ap,
                    ),
                ),
                requires_living_opponent=False,
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"SORAKA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "soraka_q5_w5_e1_r2_level13_locked_v1",
            tuple(
                sorted(
                    (*starcalls, *fixed_events, *self._basic_attacks(context)),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "SORAKA_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "SORAKA_Q_HIT_AND_RETURN_MISSILE_TRAVEL_UNVERIFIED",
                "SORAKA_Q_REJUVENATION_TICK_CADENCE_NOT_IN_LOCKED_SOURCE",
                "SORAKA_Q_DELAYED_HEAL_CANCEL_CAUSALITY_NOT_MODELED",
                "SORAKA_Q_MOVEMENT_SPEED_DECAY_NOT_MODELED",
                "SORAKA_W_ALLY_TARGET_NOT_REPRESENTABLE_IN_TWO_COMBATANT_DUEL",
                "SORAKA_W_HEALTH_COST_NOT_APPLIED_WITHOUT_VALID_ALLY_CAST",
                "SORAKA_W_REJUVENATION_TRANSFER_NOT_MODELED",
                "SORAKA_E_TARGET_REMAINS_IN_FIELD_FIXTURE",
                "SORAKA_E_EXPIRE_CANCEL_CAUSALITY_NOT_MODELED",
                "SORAKA_R_ALLY_HEALING_NOT_REPRESENTABLE_IN_TWO_COMBATANT_DUEL",
                "SORAKA_R_LOW_HEALTH_AMPLIFICATION_NOT_MODELED",
                "SORAKA_PASSIVE_LOW_HEALTH_ALLY_PURSUIT_NOT_MODELED",
                "SORAKA_CAST_AND_ATTACK_TIMING_UNVERIFIED",
                "SORAKA_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Equinox's silence, delayed root, and Starcall slows.

        :param context: Role-bound Soraka and opponent combat snapshots.
        :return: Control windows causally linked to Soraka action events.
        """
        windows: list[CastBlockWindow] = [
            CastBlockWindow(
                "soraka_e_equinox_silence",
                self._E_CAST_AT_MS,
                min(self._E_EXPIRE_AT_MS, context.duration_ms),
                (ActionChannel.ABILITY,),
                "SORAKA_E_EQUINOX_INITIAL",
                True,
                ControlType.SILENCE,
            ),
            CastBlockWindow(
                "soraka_e_equinox_root",
                self._E_EXPIRE_AT_MS,
                min(self._E_EXPIRE_AT_MS + 1000, context.duration_ms),
                (ActionChannel.MOVEMENT,),
                "SORAKA_E_EQUINOX_EXPIRE",
                True,
                ControlType.ROOT,
            ),
        ]
        for cast_index, at_ms in enumerate(
            (self._Q_FIRST_AT_MS, self._Q_SECOND_AT_MS),
            start=1,
        ):
            if at_ms < context.duration_ms:
                windows.append(
                    CastBlockWindow(
                        f"soraka_q_starcall_slow_{cast_index}",
                        at_ms,
                        min(at_ms + 1500, context.duration_ms),
                        (ActionChannel.MOVEMENT,),
                        f"SORAKA_Q_STARCALL_{cast_index}",
                        True,
                        ControlType.SLOW,
                    )
                )
        return ReactionPlan(
            "soraka_q5_e1_control_level13_locked_v1",
            cast_block_windows=tuple(windows),
            blockers=(
                "SORAKA_E_FIELD_CONTACT_AND_REENTRY_NOT_MODELED",
                "SORAKA_E_EXPIRE_ROOT_CONDITIONAL_ON_FIELD_OCCUPANCY",
                "SORAKA_Q_SLOW_HIT_ASSUMED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Decline to invent lane targets, mana, or repeated Starcall hits.

        :param context: Role-bound Soraka lane snapshot.
        :param duration_ms: Lane observation window in milliseconds.
        :param no_damage_delay_ms: Delay before out-of-combat recovery begins.
        :return: Zero extra health and explicit missing-schedule blockers.
        """
        return Decimal(0), (
            "SORAKA_LANE_Q_CHAMPION_HIT_SCHEDULE_NOT_MODELED",
            "SORAKA_LANE_W_ALLY_AND_HEALTH_COST_SCHEDULE_NOT_MODELED",
            "SORAKA_LANE_MANA_BUDGET_NOT_MODELED",
        )
