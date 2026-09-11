"""Alistar combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    DamageModifierWindow,
    RemoveStatusOutput,
    StatusOutput,
)


class AlistarCog(ChampionCog):
    """Model Alistar's Q5/W5/E1/R2 level-13 W-Q engage fixture.

    Headbutt establishes contact before Pulverize, Trample deals its locked
    total damage over a deterministic ten-pulse approximation, and the first
    attack after five champion-contact seconds consumes the empowered attack.
    Triumphant Roar counts only represented champion displacement and stun
    events; nearby-unit deaths remain outside the duel model.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Alistar.json",
        "data/raw/16.17.1/communitydragon/champions/12.json",
        "data/raw/16.17.1/communitydragon/champions/alistar.bin.json",
    )

    _W_FIRST_MS = 200
    _Q_AFTER_W_MS = 250
    _E_FIRST_MS = 700
    _E_TICK_MS = 500
    _R_DURATION_MS = 7000
    _PASSIVE_MAX_STACKS = 7

    @staticmethod
    def _cooldown_ms(seconds: Decimal, ability_haste: Decimal) -> int:
        """Convert a base cooldown and non-negative haste into milliseconds.

        :param seconds: Locked base cooldown in seconds.
        :param ability_haste: Ability haste supplied by the champion snapshot.
        :return: Deterministically rounded cooldown in milliseconds.
        """
        bounded_haste = max(Decimal(0), ability_haste)
        return int(
            (seconds * Decimal(100_000) / (Decimal(100) + bounded_haste)).to_integral_value(
                ROUND_HALF_EVEN
            )
        )

    @staticmethod
    def _passive_self_heal(context: ParticipantContext) -> Decimal:
        """Calculate Triumphant Roar's locked five-percent self heal.

        :param context: Snapshot supplying Alistar's current maximum health.
        :return: Raw self-healing amount for one fully charged roar.
        """
        return Decimal("0.05") * context.snapshot.max_hp

    @staticmethod
    def _e_empowered_damage(context: ParticipantContext) -> Decimal:
        """Calculate the level-scaled magic damage on Trample's attack.

        :param context: Snapshot supplying the fixed benchmark level.
        :return: Raw bonus magic damage dealt by the empowered attack.
        """
        return Decimal(20) + Decimal(15) * Decimal(context.snapshot.level - 1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Headbutt's locked target-cast range as approach reach.

        :param context: Role-bound encounter context for Alistar.
        :return: Maximum modeled Headbutt approach distance in game units.
        """
        return Decimal(650)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Alistar's deterministic fixture.

        Ability haste is accepted because sufficiently large values schedule a
        later W-Q or E cast inside the eight-second benchmark.

        :param item: Normalized candidate from the locked item catalog.
        :return: Alistar-scoped blocker, or ``None`` for represented channels.
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
            return f"ALISTAR_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _combo_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule every haste-permitted W-Q combo in the benchmark.

        :param context: Snapshot supplying AP, haste, roles, and duration.
        :return: Headbutt and Pulverize events in chronological pairs.
        """
        base = self._sequence_base(context) + 10
        cooldown_ms = self._cooldown_ms(Decimal(10), context.snapshot.ability_haste)
        ap = context.snapshot.ability_power
        events: list[ActionEvent] = []
        at_ms = self._W_FIRST_MS
        combo = 1
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"ALISTAR_W_HEADBUTT_{combo}",
                    at_ms=at_ms,
                    sequence=base + combo * 2,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, Decimal(275) + ap, DamageType.MAGIC),
                        crowd_control(context.opponent_entity, "KNOCKBACK", duration_ms=750),
                    ),
                )
            )
            q_ms = at_ms + self._Q_AFTER_W_MS
            if q_ms <= context.duration_ms:
                events.append(
                    action(
                        f"ALISTAR_Q_PULVERIZE_{combo}",
                        at_ms=q_ms,
                        sequence=base + combo * 2 + 1,
                        source=context.self_entity,
                        channel=ActionChannel.ABILITY,
                        outputs=(
                            damage(
                                context.opponent_entity,
                                Decimal(220) + Decimal("0.80") * ap,
                                DamageType.MAGIC,
                            ),
                            crowd_control(context.opponent_entity, "KNOCKUP", duration_ms=1000),
                        ),
                    )
                )
            combo += 1
            at_ms += cooldown_ms
        return tuple(events)

    def _trample_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule haste-permitted Trample casts and in-range damage pulses.

        :param context: Snapshot supplying AP, haste, roles, and duration.
        :return: Trample start and single-target damage-pulse events.
        """
        base = self._sequence_base(context) + 100
        cooldown_ms = self._cooldown_ms(Decimal(12), context.snapshot.ability_haste)
        total_damage = Decimal(80) + Decimal("0.70") * context.snapshot.ability_power
        pulse_damage = total_damage / Decimal(10)
        events: list[ActionEvent] = []
        cast_ms = self._E_FIRST_MS
        cast_index = 1
        while cast_ms <= context.duration_ms:
            events.append(
                action(
                    f"ALISTAR_E_TRAMPLE_START_{cast_index}",
                    at_ms=cast_ms,
                    sequence=base + cast_index * 20,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(StatusOutput(context.self_entity, "ALISTAR_E_TRAMPLE", 5000),),
                    requires_living_opponent=False,
                )
            )
            for pulse in range(1, 11):
                pulse_ms = cast_ms + pulse * self._E_TICK_MS
                if pulse_ms > context.duration_ms:
                    break
                events.append(
                    action(
                        f"ALISTAR_E_TRAMPLE_{cast_index}_PULSE_{pulse}",
                        at_ms=pulse_ms,
                        sequence=base + cast_index * 20 + pulse,
                        source=context.self_entity,
                        channel=ActionChannel.PASSIVE,
                        outputs=(damage(context.opponent_entity, pulse_damage, DamageType.MAGIC),),
                    )
                )
            cast_index += 1
            cast_ms += cooldown_ms
        return tuple(events)

    def _attack_events(
        self,
        context: ParticipantContext,
        trample_events: tuple[ActionEvent, ...],
    ) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks and consume completed Trample charges.

        :param context: Snapshot supplying attack speed, AD, and role bindings.
        :param trample_events: Trample schedule used to locate full-charge times.
        :return: Chronological basic attacks, including empowered stun attacks.
        """
        completed_at = tuple(
            event.at_ms for event in trample_events if event.id.endswith("PULSE_10")
        )
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 500
        events: list[ActionEvent] = []
        pending = list(completed_at)
        at_ms = 1600
        while at_ms <= context.duration_ms:
            outputs = [
                damage(context.opponent_entity, context.snapshot.attack_damage, DamageType.PHYSICAL)
            ]
            empowered = bool(pending and pending[0] <= at_ms)
            if empowered:
                pending.pop(0)
                outputs.extend(
                    (
                        damage(
                            context.opponent_entity,
                            self._e_empowered_damage(context),
                            DamageType.MAGIC,
                        ),
                        crowd_control(context.opponent_entity, "STUN", duration_ms=1000),
                    )
                )
            index = len(events) + 1
            event_name = "E_EMPOWERED_ATTACK" if empowered else "BASIC_ATTACK"
            events.append(
                action(
                    f"ALISTAR_{event_name}_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
            at_ms += interval_ms
        return tuple(events)

    def _attach_passive_heals(
        self,
        context: ParticipantContext,
        events: tuple[ActionEvent, ...],
    ) -> tuple[ActionEvent, ...]:
        """Attach self heals to every seventh represented champion control.

        :param context: Snapshot supplying Alistar's maximum health.
        :param events: Complete outgoing schedule before passive charge resolution.
        :return: Schedule with causally adjacent Triumphant Roar heal outputs.
        """
        charges = 0
        resolved: list[ActionEvent] = []
        for event in sorted(events, key=lambda value: (value.at_ms, value.sequence, value.id)):
            applies_control = any(
                isinstance(output, StatusOutput) and output.status.startswith("CC_")
                for output in event.outputs
            )
            if applies_control:
                charges += 1
            if charges >= self._PASSIVE_MAX_STACKS:
                event = replace(
                    event,
                    outputs=(
                        *event.outputs,
                        healing(context.self_entity, self._passive_self_heal(context)),
                    ),
                )
                charges = 0
            resolved.append(event)
        return tuple(resolved)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Alistar's locked W-Q, Trample, attack, passive, and R plan.

        :param context: Role-bound Alistar and opponent snapshots.
        :return: Deterministic level-13 duel schedule with evidence blockers.
        """
        base = self._sequence_base(context)
        ultimate = action(
            "ALISTAR_R_UNBREAKABLE_WILL",
            at_ms=0,
            sequence=base,
            source=context.self_entity,
            channel=ActionChannel.ABILITY,
            outputs=(
                RemoveStatusOutput(
                    context.self_entity,
                    "CROWD_CONTROL_EXCEPT_AIRBORNE_AND_SUPPRESSION",
                ),
                StatusOutput(context.self_entity, "ALISTAR_R_DAMAGE_REDUCTION", 7000),
            ),
            requires_living_opponent=False,
        )
        combos = self._combo_events(context)
        trample = self._trample_events(context)
        attacks = self._attack_events(context, trample)
        events = self._attach_passive_heals(context, (ultimate, *combos, *trample, *attacks))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"ALISTAR_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "alistar_q5_w5_e1_r2_level13_wq_fixture_v1",
            events,
            (
                *level_blockers,
                "ALISTAR_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "ALISTAR_ROTATION_TIMING_UNVERIFIED",
                "ALISTAR_W_Q_DISPLACEMENT_COMPOSITION_APPROXIMATED",
                "ALISTAR_W_COLLISION_AND_LANDING_GEOMETRY_NOT_MODELED",
                "ALISTAR_E_TEN_PULSE_CADENCE_UNVERIFIED",
                "ALISTAR_E_REQUIRES_CONTINUOUS_CHAMPION_PROXIMITY",
                "ALISTAR_PASSIVE_NEARBY_UNIT_DEATH_CHARGES_NOT_MODELED",
                "ALISTAR_PASSIVE_CHARGES_NOT_RECOUNTED_AFTER_EVENT_CANCELLATION",
                "ALISTAR_R_EXACT_CLEANSE_EXCLUSIONS_UNVERIFIED",
                "ALISTAR_RESOURCE_COSTS_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Alistar's R reduction and W, Q, and E control windows.

        :param context: Role-bound Alistar and opponent snapshots.
        :return: Damage reduction and causally linked opponent action blocks.
        """
        actions = self.build_action_plan(context)
        windows: list[CastBlockWindow] = []
        for event in actions.events:
            if event.id.startswith("ALISTAR_W_HEADBUTT_"):
                windows.append(
                    CastBlockWindow(
                        event.id.casefold(),
                        event.at_ms,
                        min(event.at_ms + 750, context.duration_ms),
                        (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT),
                        event.id,
                        False,
                        ControlType.AIRBORNE,
                    )
                )
            elif event.id.startswith("ALISTAR_Q_PULVERIZE_"):
                windows.append(
                    CastBlockWindow(
                        event.id.casefold(),
                        event.at_ms,
                        min(event.at_ms + 1000, context.duration_ms),
                        (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT),
                        event.id,
                        False,
                        ControlType.AIRBORNE,
                    )
                )
            elif "E_EMPOWERED_ATTACK" in event.id:
                windows.append(
                    CastBlockWindow(
                        event.id.casefold(),
                        event.at_ms,
                        min(event.at_ms + 1000, context.duration_ms),
                        (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT),
                        event.id,
                        True,
                        ControlType.STUN,
                    )
                )
        return ReactionPlan(
            "alistar_wq_e_control_and_r2_reduction_v1",
            damage_windows=(
                DamageModifierWindow(
                    "alistar_r_unbreakable_will_damage_reduction",
                    0,
                    min(self._R_DURATION_MS, context.duration_ms),
                    context.self_entity,
                    (DamageType.PHYSICAL, DamageType.MAGIC),
                    Decimal("0.35"),
                ),
            ),
            cast_block_windows=tuple(windows),
            blockers=(
                "ALISTAR_R_CAST_WHILE_DISABLED_NOT_ENFORCED_BY_STATIC_CAST_BLOCK_MODEL",
                "ALISTAR_R_CLEANSE_DOES_NOT_REWRITE_STATIC_CAST_BLOCK_WINDOWS",
                "ALISTAR_W_Q_DISPLACEMENT_COMPOSITION_APPROXIMATED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Decline to invent passive lane healing without nearby-death input.

        :param context: Role-bound Alistar lane snapshot.
        :param duration_ms: Lane observation window in milliseconds.
        :param no_damage_delay_ms: Delay before out-of-combat recovery begins.
        :return: Zero recovery and blockers identifying absent charge inputs.
        """
        return Decimal(0), (
            "ALISTAR_LANE_NEARBY_UNIT_DEATH_SCHEDULE_NOT_MODELED",
            "ALISTAR_LANE_CHAMPION_CONTROL_SCHEDULE_NOT_MODELED",
        )
