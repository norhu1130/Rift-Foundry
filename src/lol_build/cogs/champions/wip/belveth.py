"""Bel'Veth combat Cog backed by the locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal

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
from lol_build.core.combat import (
    DamageType,
    ResistanceModifiers,
    apply_resistance,
    apply_resistance_pipeline,
)
from lol_build.core.timeline import ActionChannel, ActionEvent, DamageModifierWindow, StatusOutput


class BelvethCog(ChampionCog):
    """Model Bel'Veth's Q5/W1/E5/R2 level-13 duel fixture.

    The fixture starts in rank-two True Form with twenty permanent Lavender
    stacks. It uses one available Q direction, refreshes that direction with a
    champion-hit W, channels E for its minimum missing-health damage, and then
    resumes attacks. Coral creation, terrain, directional cooldown state, and
    health-dependent execute amplification remain explicit blockers.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Belveth.json",
        "data/raw/16.17.1/communitydragon/champions/200.json",
        "data/raw/16.17.1/communitydragon/champions/belveth.bin.json",
    )

    _BASE_ATTACK_SPEED = Decimal("0.67")
    _FIXED_LAVENDER_STACKS = 20
    _LEVEL13_AS_PER_LAVENDER_STACK = Decimal("0.0125")
    _R2_TOTAL_ATTACK_SPEED_MULTIPLIER = Decimal("1.13")
    _E5_DAMAGE_REDUCTION_MULTIPLIER = Decimal("0.40")
    _E5_LIFESTEAL = Decimal("0.40")

    @staticmethod
    def _haste_adjusted_ms(base_ms: int, ability_haste: Decimal) -> int:
        """Apply the standard ability-haste divisor to one cooldown.

        :param base_ms: Unmodified cooldown in milliseconds.
        :param ability_haste: Non-negative ability haste from the snapshot.
        :return: Deterministically rounded cooldown with a one-ms floor.
        """
        cooldown = Decimal(base_ms) * Decimal(100) / (Decimal(100) + ability_haste)
        return max(1, int(cooldown.to_integral_value(rounding=ROUND_HALF_EVEN)))

    def _fixture_attack_speed(self, context: ParticipantContext) -> Decimal:
        """Combine item attack speed with the fixed Lavender and form state.

        :param context: Snapshot supplying the item-adjusted attack speed.
        :return: Attacks per second used by the deterministic fixture.
        """
        permanent_bonus = (
            self._BASE_ATTACK_SPEED
            * self._LEVEL13_AS_PER_LAVENDER_STACK
            * Decimal(self._FIXED_LAVENDER_STACKS)
        )
        return (
            context.snapshot.attack_speed + permanent_bonus
        ) * self._R2_TOTAL_ATTACK_SPEED_MULTIPLIER

    @staticmethod
    def _post_mitigation_physical(
        context: ParticipantContext,
        raw_damage: Decimal,
    ) -> Decimal:
        """Resolve physical damage for E's deterministic lifesteal output.

        :param context: Snapshots supplying armor and Bel'Veth's penetration.
        :param raw_damage: Physical damage before target mitigation.
        :return: Post-mitigation damage before runtime reaction modifiers.
        """
        resistance = apply_resistance_pipeline(
            context.opponent_snapshot.armor,
            ResistanceModifiers(
                percent_penetration=context.snapshot.percent_armor_penetration,
                flat_penetration=context.snapshot.flat_armor_penetration,
            ),
        ).effective_resistance
        return apply_resistance(
            raw_damage,
            DamageType.PHYSICAL,
            armor=resistance,
            magic_resistance=context.opponent_snapshot.magic_resistance,
        ).post_mitigation_damage

    @staticmethod
    def _r_passive_damage(context: ParticipantContext, proc_index: int) -> Decimal:
        """Calculate one escalating rank-two Endless Banquet passive proc.

        :param context: Snapshot supplying Bel'Veth's bonus attack damage.
        :param proc_index: One-based consecutive proc count on the same target.
        :return: Raw true damage for that proc.
        """
        per_stack = Decimal(10) + Decimal("0.03") * context.snapshot.bonus_attack_damage
        return per_stack * Decimal(proc_index)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose one locked Void Surge dash distance.

        :param context: Role-bound snapshots for the evaluated encounter.
        :return: Rank-independent dash distance in game units.
        """
        return Decimal(400)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Avoid inventing a movement-speed steroid for the fixed duel.

        :param context: Role-bound snapshots for the evaluated encounter.
        :return: Neutral movement-speed multiplier.
        """
        return Decimal(1)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Bel'Veth's fixed duel model.

        AD, attack speed, haste, health, resistances, penetration, movement,
        and tenacity reach modeled calculations or shared comparison channels.

        :param item: Normalized candidate from the locked item catalog.
        :return: Bel'Veth-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "AP",
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "MANA_REGEN",
            "OMNIVAMP",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"BELVETH_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _q_event(
        self,
        context: ParticipantContext,
        *,
        at_ms: int,
        sequence: int,
        event_id: str,
    ) -> ActionEvent:
        """Create one successful Q5 champion pass-through.

        :param context: Snapshot supplying Bel'Veth's total attack damage.
        :param at_ms: Deterministic dash-hit timestamp.
        :param sequence: Stable global event ordering key.
        :param event_id: Champion-scoped event identifier.
        :return: One ability-channel dash damage event.
        """
        return action(
            event_id,
            at_ms=at_ms,
            sequence=sequence,
            source=context.self_entity,
            channel=ActionChannel.ABILITY,
            outputs=(
                damage(
                    context.opponent_entity,
                    Decimal(20) + Decimal("1.05") * context.snapshot.attack_damage,
                    DamageType.PHYSICAL,
                ),
            ),
        )

    def _w_q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule W1 hits and the Q direction each hit refreshes.

        Ability haste can make a second W fit inside the eight-second fixture.
        This supplies a measurable haste channel without claiming knowledge of
        the four independent Q direction cooldowns.

        :param context: Snapshot supplying damage, haste, and encounter length.
        :return: W impacts followed by their deterministic refreshed-Q uses.
        """
        cooldown_ms = self._haste_adjusted_ms(12000, context.snapshot.ability_haste)
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 700
        cast_index = 1
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"BELVETH_W_ABOVE_AND_BELOW_{cast_index}",
                    at_ms=at_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal(80) + Decimal("1.50") * context.snapshot.bonus_attack_damage,
                            DamageType.MAGIC,
                        ),
                        crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=600),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=2000,
                            magnitude=Decimal("0.30"),
                        ),
                    ),
                )
            )
            q_at_ms = at_ms + 550
            if q_at_ms <= context.duration_ms:
                events.append(
                    self._q_event(
                        context,
                        at_ms=q_at_ms,
                        sequence=base + len(events),
                        event_id=f"BELVETH_Q_VOID_SURGE_W_RESET_{cast_index}",
                    )
                )
            cast_index += 1
            at_ms += cooldown_ms
        return tuple(events)

    def _e_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build E5's 1.5-second minimum-damage channel and sustain.

        :param context: Snapshot supplying total AD, attack speed, and armor data.
        :return: Channel start plus attack-speed-sensitive physical strikes.
        """
        base = self._sequence_base(context) + 300
        fixture_speed = self._fixture_attack_speed(context)
        bonus_attack_speed = max(
            Decimal(0),
            fixture_speed / self._BASE_ATTACK_SPEED - Decimal(1),
        )
        extra_strikes = int(
            (Decimal(6) * bonus_attack_speed * Decimal("0.40")).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
        strike_count = 6 + extra_strikes
        raw_damage = Decimal(18) + Decimal("0.12") * context.snapshot.attack_damage
        healing_per_strike = (
            self._post_mitigation_physical(context, raw_damage) * self._E5_LIFESTEAL
        )
        events = [
            action(
                "BELVETH_E_ROYAL_MAELSTROM_START",
                at_ms=2500,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "BELVETH_E_CHANNEL", 1500),),
                requires_living_opponent=False,
            )
        ]
        for index in range(1, strike_count + 1):
            at_ms = 2500 + int(Decimal(1500) * Decimal(index) / Decimal(strike_count))
            events.append(
                action(
                    f"BELVETH_E_ROYAL_MAELSTROM_STRIKE_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, raw_damage, DamageType.PHYSICAL),
                        healing(context.self_entity, healing_per_strike),
                    ),
                )
            )
        return tuple(events)

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule True-Form attacks and every-second-hit R passive procs.

        :param context: Snapshot supplying total AD, bonus AD, and attack speed.
        :return: Blind-susceptible basic attacks outside the E channel.
        """
        interval_ms = self._attack_interval_ms(self._fixture_attack_speed(context))
        base = self._sequence_base(context) + 500
        events: list[ActionEvent] = []
        at_ms = 1500
        attack_index = 1
        proc_index = 0
        while at_ms <= context.duration_ms:
            if 2500 <= at_ms <= 4000:
                at_ms = 4200
                continue
            outputs = [
                damage(
                    context.opponent_entity,
                    Decimal("0.75") * context.snapshot.attack_damage,
                    DamageType.PHYSICAL,
                )
            ]
            if attack_index % 2 == 0:
                proc_index += 1
                outputs.append(
                    damage(
                        context.opponent_entity,
                        self._r_passive_damage(context, proc_index),
                        DamageType.TRUE,
                    )
                )
            events.append(
                action(
                    f"BELVETH_BASIC_ATTACK_{attack_index}",
                    at_ms=at_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
            attack_index += 1
            at_ms += interval_ms
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Bel'Veth's fixed level-13 True-Form duel sequence.

        :param context: Role-bound Bel'Veth and opponent snapshots.
        :return: Q, W, E, attack, true-damage, sustain, and blocker events.
        """
        base = self._sequence_base(context)
        fixture = action(
            "BELVETH_TRUE_FORM_FIXTURE",
            at_ms=0,
            sequence=base,
            source=context.self_entity,
            channel=ActionChannel.PASSIVE,
            outputs=(
                StatusOutput(context.self_entity, "BELVETH_R2_TRUE_FORM", context.duration_ms),
                StatusOutput(
                    context.self_entity,
                    "BELVETH_PASSIVE_LAVENDER_STACKS",
                    context.duration_ms,
                    Decimal(self._FIXED_LAVENDER_STACKS),
                ),
            ),
            requires_living_opponent=False,
        )
        initial_q = self._q_event(
            context,
            at_ms=100,
            sequence=base + 1,
            event_id="BELVETH_Q_VOID_SURGE_INITIAL_DIRECTION",
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"BELVETH_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        events = (
            fixture,
            initial_q,
            *self._w_q_events(context),
            *self._e_events(context),
            *self._attack_events(context),
        )
        return ActionPlan(
            "belveth_q5_w1_e5_r2_level13_true_form_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "BELVETH_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "BELVETH_ROTATION_TIMING_UNVERIFIED",
                "BELVETH_PASSIVE_20_STACK_TRUE_FORM_FIXTURE_SYNTHETIC",
                "BELVETH_PASSIVE_TEMPORARY_ATTACK_SPEED_STACKS_NOT_MODELED",
                "BELVETH_BASIC_ATTACK_DAMAGE_MODIFIER_UNVERIFIED",
                "BELVETH_Q_DIRECTIONAL_COOLDOWNS_NOT_MODELED",
                "BELVETH_Q_ATTACK_SPEED_COOLDOWN_SCALING_NOT_MODELED",
                "BELVETH_Q_ON_HIT_AND_ATTACK_RESET_NOT_MODELED",
                "BELVETH_W_DIRECTIONAL_Q_RESET_ASSUMED_SUCCESS",
                "BELVETH_E_LOWEST_HEALTH_TARGET_SELECTION_NOT_MODELED",
                "BELVETH_E_MISSING_HEALTH_DAMAGE_USES_MINIMUM",
                "BELVETH_E_CHANNEL_INTERRUPTION_SUPPORTED_BY_SHARED_CONTROL_ONLY",
                "BELVETH_E_HEAL_PRECOMPUTED_BEFORE_RUNTIME_TARGET_MODIFIERS",
                "BELVETH_R_PASSIVE_E_ON_HIT_INTERACTION_NOT_MODELED",
                "BELVETH_R_CORAL_ACTIVE_AND_CURRENT_HP_EXECUTE_NOT_MODELED",
                "BELVETH_R_VOID_EPIC_FORM_AND_REMORA_NOT_MODELED",
                "BELVETH_R_TRUE_FORM_TERRAIN_TRAVERSAL_NOT_MODELED",
                "BELVETH_RESOURCE_COSTS_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose W control and E's rank-five defensive channel.

        :param context: Role-bound snapshots for the Bel'Veth participant.
        :return: Incoming-damage and opponent-control windows with blockers.
        """
        w_times = []
        cooldown_ms = self._haste_adjusted_ms(12000, context.snapshot.ability_haste)
        at_ms = 700
        while at_ms <= context.duration_ms:
            w_times.append(at_ms)
            at_ms += cooldown_ms

        windows: list[CastBlockWindow] = []
        for index, w_at_ms in enumerate(w_times, start=1):
            windows.extend(
                (
                    CastBlockWindow(
                        f"belveth_w_airborne_{index}",
                        w_at_ms,
                        min(w_at_ms + 600, context.duration_ms),
                        (
                            ActionChannel.BASIC_ATTACK,
                            ActionChannel.ABILITY,
                            ActionChannel.MOVEMENT,
                            ActionChannel.ITEM_ACTIVE,
                        ),
                        f"BELVETH_W_ABOVE_AND_BELOW_{index}",
                        False,
                        ControlType.AIRBORNE,
                    ),
                    CastBlockWindow(
                        f"belveth_w_slow_{index}",
                        w_at_ms,
                        min(w_at_ms + 2000, context.duration_ms),
                        (ActionChannel.MOVEMENT,),
                        f"BELVETH_W_ABOVE_AND_BELOW_{index}",
                        True,
                        ControlType.SLOW,
                    ),
                )
            )
        return ReactionPlan(
            "belveth_w1_e5_reaction_v1",
            damage_windows=(
                DamageModifierWindow(
                    "belveth_e_damage_reduction",
                    2500,
                    min(4000, context.duration_ms),
                    context.self_entity,
                    (DamageType.PHYSICAL, DamageType.MAGIC, DamageType.TRUE),
                    self._E5_DAMAGE_REDUCTION_MULTIPLIER,
                ),
            ),
            cast_block_windows=tuple(windows),
            blockers=(
                "BELVETH_W_HIT_AND_Q_DIRECTION_GEOMETRY_ASSUMED",
                "BELVETH_E_CHANNEL_SELF_ROOT_NOT_APPLIED_TO_ENGAGEMENT_METRIC",
                "BELVETH_E_CHANNEL_INTERRUPTION_SUPPORTED_BY_SHARED_CONTROL_ONLY",
            ),
        )
