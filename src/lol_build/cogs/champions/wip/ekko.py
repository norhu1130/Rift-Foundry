"""Ekko combat Cog backed by the locked 16.17.1 champion sources."""

from __future__ import annotations

from dataclasses import replace
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
from lol_build.cogs.mechanics import (
    action,
    crowd_control,
    damage,
    healing,
    movement_speed,
    shielding,
)
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, DamageModifierWindow, StatusOutput


class EkkoCog(ChampionCog):
    """Model Ekko's Q5/E5/W1/R2 level-13 single-target fixture.

    Timewinder's outgoing and returning hits, Phase Dive's empowered attack,
    and ordinary attacks feed one deterministic Z-Drive Resonance tracker.
    Parallel Convergence assumes a predicted champion hit, while Chronobreak
    assumes its return area overlaps the opponent without pretending that the
    four-second position and health history are known.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Ekko.json",
        "data/raw/16.17.1/communitydragon/champions/245.json",
        "data/raw/16.17.1/communitydragon/champions/ekko.bin.json",
    )

    _Q_FIRST_AT_MS = 100
    _Q_RETURN_DELAY_MS = 1400
    _E_FIRST_AT_MS = 500
    _E_ATTACK_DELAY_MS = 300
    _W_DETONATE_AT_MS = 3000
    _R_AT_MS = 4300
    _PASSIVE_LOCKOUT_MS = 4000

    @staticmethod
    def _cooldown_ms(base_seconds: Decimal, ability_haste: Decimal) -> int:
        """Convert a locked base cooldown through the standard haste formula.

        :param base_seconds: Rank-specific cooldown before ability haste.
        :param ability_haste: Non-negative ability haste from the snapshot.
        :return: Deterministically rounded cooldown in milliseconds.
        :raises ValueError: If either input is negative.
        """
        if base_seconds < 0 or ability_haste < 0:
            raise ValueError("cooldown inputs cannot be negative")
        return int(
            (base_seconds * Decimal(100_000) / (Decimal(100) + ability_haste)).to_integral_value(
                ROUND_HALF_EVEN
            )
        )

    @staticmethod
    def _passive_damage(level: int, ability_power: Decimal) -> Decimal:
        """Evaluate Z-Drive Resonance's locked breakpoint and AP scaling.

        The BIN curve starts at thirty damage, gains ten per level through
        level six, then gains five per level from level seven onward.

        :param level: Champion level selecting the passive breakpoint value.
        :param ability_power: Aggregated ability power for the passive ratio.
        :return: Raw magic damage dealt by one three-hit proc.
        """
        bounded_level = min(18, max(1, level))
        base = Decimal(30)
        for gained_level in range(2, bounded_level + 1):
            base += Decimal(5 if gained_level >= 7 else 10)
        return base + Decimal("0.80") * ability_power

    @staticmethod
    def _passive_speed_fraction(level: int) -> Decimal:
        """Resolve the level-breakpoint movement bonus after a champion proc.

        :param level: Champion level selecting the fifty-to-eighty-percent curve.
        :return: Fractional movement-speed bonus granted by the passive.
        """
        bounded_level = min(18, max(1, level))
        return Decimal("0.50") + Decimal("0.10") * sum(
            bounded_level >= breakpoint for breakpoint in (6, 11, 16)
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose only Phase Dive's locked first displacement.

        :param context: Role-bound Ekko encounter context.
        :return: CommunityDragon's 350-unit Phase Dive dash distance.
        """
        return Decimal(350)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Ekko's fixed event policy.

        AP, attack speed, ability haste, penetration, AD, and chassis stats
        affect represented snapshots or events. Resource use, critical strikes,
        and generic healing modifiers are deliberately not inferred.

        :param item: Normalized candidate from the locked item catalog.
        :return: Ekko-scoped blocker for unsupported stats, otherwise ``None``.
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
            return f"EKKO_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule rank-five Timewinder casts and eligible haste recasts.

        :param context: Ekko snapshot supplying AP, haste, and role identifiers.
        :return: Outgoing and returning projectile damage inside the duration.
        """
        ap = context.snapshot.ability_power
        cooldown_ms = self._cooldown_ms(Decimal(7), context.snapshot.ability_haste)
        base = self._sequence_base(context)
        events: list[ActionEvent] = []
        cast_at_ms = self._Q_FIRST_AT_MS
        cast_index = 1
        while cast_at_ms <= context.duration_ms:
            events.append(
                action(
                    f"EKKO_Q_TIMEWINDER_OUT_{cast_index}",
                    at_ms=cast_at_ms,
                    sequence=base + cast_index * 10,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal(130) + Decimal("0.30") * ap,
                            DamageType.MAGIC,
                        ),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=1750,
                            magnitude=Decimal("0.60"),
                        ),
                    ),
                )
            )
            return_at_ms = cast_at_ms + self._Q_RETURN_DELAY_MS
            if return_at_ms <= context.duration_ms:
                events.append(
                    action(
                        f"EKKO_Q_TIMEWINDER_RETURN_{cast_index}",
                        at_ms=return_at_ms,
                        sequence=base + cast_index * 10 + 1,
                        source=context.self_entity,
                        channel=ActionChannel.ABILITY,
                        outputs=(
                            damage(
                                context.opponent_entity,
                                Decimal(140) + Decimal("0.60") * ap,
                                DamageType.MAGIC,
                            ),
                        ),
                    )
                )
            cast_at_ms += cooldown_ms
            cast_index += 1
        return tuple(events)

    def _e_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Phase Dive and its empowered, blind-susceptible attacks.

        :param context: Ekko snapshot supplying AP, AD, haste, and participant role.
        :return: Dash markers and empowered basic-attack events.
        """
        cooldown_ms = self._cooldown_ms(Decimal(7), context.snapshot.ability_haste)
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        cast_at_ms = self._E_FIRST_AT_MS
        cast_index = 1
        while cast_at_ms <= context.duration_ms:
            events.append(
                action(
                    f"EKKO_E_PHASE_DIVE_{cast_index}",
                    at_ms=cast_at_ms,
                    sequence=base + cast_index * 10,
                    source=context.self_entity,
                    channel=ActionChannel.MOVEMENT,
                    outputs=(StatusOutput(context.self_entity, "EKKO_E_EMPOWERED", 3000),),
                    requires_living_opponent=False,
                )
            )
            attack_at_ms = cast_at_ms + self._E_ATTACK_DELAY_MS
            if attack_at_ms <= context.duration_ms:
                events.append(
                    action(
                        f"EKKO_E_PHASE_DIVE_ATTACK_{cast_index}",
                        at_ms=attack_at_ms,
                        sequence=base + cast_index * 10 + 1,
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
                                Decimal(150) + Decimal("0.40") * context.snapshot.ability_power,
                                DamageType.MAGIC,
                            ),
                        ),
                    )
                )
            cast_at_ms += cooldown_ms
            cast_index += 1
        return tuple(events)

    def _ordinary_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks using the shared attack-interval helper.

        :param context: Snapshot supplying Ekko's post-item attack speed and AD.
        :return: Deterministic physical attacks after the opening combo.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 300
        events: list[ActionEvent] = []
        at_ms = 1900
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"EKKO_BASIC_ATTACK_{len(events) + 1}",
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

    def _apply_resonance(
        self,
        context: ParticipantContext,
        events: tuple[ActionEvent, ...],
    ) -> tuple[ActionEvent, ...]:
        """Attach deterministic three-hit passive procs to eligible actions.

        Static assignment preserves causal cancellation for the proc's owning
        action. A blocker records that canceled earlier actions do not currently
        rewind the precomputed stack counter.

        :param context: Snapshot supplying passive level, AP, and movement speed.
        :param events: Complete action set before passive outputs are attached.
        :return: Chronological events with Z-Drive damage and speed on each proc.
        """
        damaging = tuple(
            sorted(
                (
                    event
                    for event in events
                    if any(hasattr(output, "damage_type") for output in event.outputs)
                ),
                key=lambda event: (event.at_ms, event.sequence, event.id),
            )
        )
        stack = 0
        last_proc_at_ms = -self._PASSIVE_LOCKOUT_MS
        proc_ids: set[str] = set()
        for event in damaging:
            if event.at_ms < last_proc_at_ms + self._PASSIVE_LOCKOUT_MS:
                continue
            stack += 1
            if stack == 3:
                proc_ids.add(event.id)
                last_proc_at_ms = event.at_ms
                stack = 0
        passive_damage = self._passive_damage(
            context.snapshot.level, context.snapshot.ability_power
        )
        passive_speed = context.snapshot.move_speed * self._passive_speed_fraction(
            context.snapshot.level
        )
        return tuple(
            replace(
                event,
                outputs=(
                    *event.outputs,
                    damage(context.opponent_entity, passive_damage, DamageType.MAGIC),
                    movement_speed(context.self_entity, passive_speed, duration_ms=3000),
                ),
            )
            if event.id in proc_ids
            else event
            for event in events
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Ekko's fixed Q5/E5/W1/R2 level-13 duel sequence.

        :param context: Role-bound Ekko and opponent combat snapshots.
        :return: Deterministic spells, attacks, sustain, passive procs, and blockers.
        """
        base = self._sequence_base(context) + 200
        ap = context.snapshot.ability_power
        fixed_events = (
            action(
                "EKKO_W_PARALLEL_CONVERGENCE_ARM",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "EKKO_W_ZONE_ARMED", 3000),),
                requires_living_opponent=False,
            ),
            action(
                "EKKO_W_PARALLEL_CONVERGENCE_DETONATE",
                at_ms=self._W_DETONATE_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(
                        context.self_entity,
                        Decimal(100) + Decimal("1.50") * ap,
                        duration_ms=2000,
                    ),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=2250),
                ),
            ),
            action(
                "EKKO_R_CHRONOBREAK_RETURN",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(350) + Decimal("1.75") * ap,
                        DamageType.MAGIC,
                    ),
                    healing(context.self_entity, Decimal(150) + Decimal("0.60") * ap),
                    StatusOutput(context.self_entity, "EKKO_R_REWIND_RETURN", 250),
                ),
            ),
        )
        events = tuple(
            sorted(
                (
                    *self._q_events(context),
                    *self._e_events(context),
                    *fixed_events,
                    *self._ordinary_attacks(context),
                ),
                key=lambda event: (event.at_ms, event.sequence, event.id),
            )
        )
        events = self._apply_resonance(context, events)
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"EKKO_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "ekko_q5_e5_w1_r2_level13_rewind_fixture_v1",
            events,
            (
                *level_blockers,
                "EKKO_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "EKKO_Q_OUTGOING_DAMAGE_DDRAGON_BIN_DISAGREEMENT",
                "EKKO_Q_TRAVEL_AND_RETURN_TIMING_UNVERIFIED",
                "EKKO_W_PREDICTED_AREA_HIT_ASSUMED",
                "EKKO_W_MISSING_HEALTH_PASSIVE_NOT_MODELED",
                "EKKO_R_FOUR_SECOND_POSITION_HISTORY_NOT_MODELED",
                "EKKO_R_RECENT_HEALTH_LOSS_HEAL_AMPLIFICATION_NOT_MODELED",
                "EKKO_R_ARRIVAL_OVERLAP_ASSUMED",
                "EKKO_PASSIVE_STACK_ADVANCE_AFTER_CANCELLATION_NOT_MODELED",
                "EKKO_PASSIVE_MONSTER_MULTIPLIER_NOT_MODELED",
                "EKKO_MULTI_TARGET_EFFECTS_NOT_MODELED",
                "EKKO_RESOURCE_COSTS_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Timewinder slow, W stun, and Chronobreak untargetability.

        :param context: Role-bound Ekko and opponent combat snapshots.
        :return: Source-linked control and incoming-damage windows.
        """
        q_cooldown_ms = self._cooldown_ms(Decimal(7), context.snapshot.ability_haste)
        q_slow_windows: list[CastBlockWindow] = []
        cast_at_ms = self._Q_FIRST_AT_MS
        cast_index = 1
        while cast_at_ms <= context.duration_ms:
            q_slow_windows.append(
                CastBlockWindow(
                    f"ekko_q_timewinder_slow_{cast_index}",
                    cast_at_ms,
                    min(cast_at_ms + 1750, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    f"EKKO_Q_TIMEWINDER_OUT_{cast_index}",
                    True,
                    ControlType.SLOW,
                )
            )
            cast_at_ms += q_cooldown_ms
            cast_index += 1
        return ReactionPlan(
            "ekko_q5_w1_r2_reaction_v1",
            damage_windows=(
                DamageModifierWindow(
                    "ekko_r_chronobreak_untargetable",
                    self._R_AT_MS,
                    min(self._R_AT_MS + 250, context.duration_ms),
                    context.self_entity,
                    (DamageType.PHYSICAL, DamageType.MAGIC, DamageType.TRUE),
                    Decimal(0),
                ),
            ),
            cast_block_windows=(
                *q_slow_windows,
                CastBlockWindow(
                    "ekko_w_parallel_convergence_stun",
                    self._W_DETONATE_AT_MS,
                    min(self._W_DETONATE_AT_MS + 2250, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                        ActionChannel.ITEM_ACTIVE,
                    ),
                    "EKKO_W_PARALLEL_CONVERGENCE_DETONATE",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(
                "EKKO_Q_SLOW_FIELD_CONTACT_DURATION_ASSUMED",
                "EKKO_W_PREDICTED_AREA_HIT_ASSUMED",
                "EKKO_R_UNTARGETABILITY_CAUSAL_LINK_NOT_MODELED",
                "EKKO_CONTROL_AND_CAST_TIMING_UNVERIFIED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Decline to reuse Chronobreak as deterministic lane recovery.

        :param context: Role-bound Ekko lane context.
        :param duration_ms: Lane observation duration in milliseconds.
        :param no_damage_delay_ms: Required delay since champion damage.
        :return: Zero recovery with the missing four-second trace blocker.
        """
        return Decimal(0), ("EKKO_LANE_R_FOUR_SECOND_HEALTH_AND_POSITION_TRACE_NOT_MODELED",)
