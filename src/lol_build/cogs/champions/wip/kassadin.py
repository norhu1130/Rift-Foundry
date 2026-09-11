"""Kassadin combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, DamageModifierWindow


class KassadinCog(ChampionCog):
    """Model Kassadin's Q5/E5/W1/R2 level-13 duel fixture.

    Riftwalk starts with no pre-existing stack. The shared snapshot has no
    mana field, so locked level-13 innate maximum mana is used only for R
    damage scaling; affordability and Nether Blade restoration stay blocked.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Kassadin.json",
        "data/raw/16.17.1/communitydragon/champions/38.json",
        "data/raw/16.17.1/communitydragon/champions/kassadin.bin.json",
    )

    _R_FIRST_AT_MS = 0
    _Q_FIRST_AT_MS = 250
    _E_FIRST_AT_MS = 550
    _W_FIRST_AT_MS = 850
    _BASIC_ATTACK_FIRST_AT_MS = 1200
    _R_STACK_DURATION_MS = 15_000
    _R_MAX_STACKS = 4
    _LEVEL13_MAX_MANA = Decimal("1352.65")

    @staticmethod
    def _cooldown_ms(base_seconds: Decimal, ability_haste: Decimal) -> int:
        """Convert a base cooldown through the standard haste formula.

        :param base_seconds: Rank-specific cooldown before ability haste.
        :param ability_haste: Non-negative haste from the participant snapshot.
        :return: Deterministically rounded cooldown in milliseconds.
        :raises ValueError: If either cooldown input is negative.
        """
        if base_seconds < 0 or ability_haste < 0:
            raise ValueError("cooldown inputs cannot be negative")
        adjusted = base_seconds * Decimal(100_000) / (Decimal(100) + ability_haste)
        return max(1, int(adjusted.to_integral_value(ROUND_HALF_EVEN)))

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Riftwalk's locked cursor-clamped cast range.

        :param context: Role-bound Kassadin encounter context.
        :return: Rank-independent Riftwalk displacement in game units.
        """
        return Decimal(500)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the fixed Kassadin model.

        :param item: Normalized candidate from the locked item catalog.
        :return: Kassadin-scoped blocker for unsupported stats, otherwise ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"KASSADIN_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _riftwalk_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Riftwalk casts with deterministic consecutive stack damage.

        :param context: Snapshot supplying AP, haste, role IDs, and duration.
        :return: Movement-channel Riftwalk hits carrying stack-indexed damage.
        """
        cooldown_ms = self._cooldown_ms(Decimal("3.5"), context.snapshot.ability_haste)
        ap = context.snapshot.ability_power
        base_damage = (
            Decimal(90) + Decimal("0.50") * ap + (Decimal("0.02") * self._LEVEL13_MAX_MANA)
        )
        stack_damage = (
            Decimal(45) + Decimal("0.07") * ap + (Decimal("0.01") * self._LEVEL13_MAX_MANA)
        )
        sequence = self._sequence_base(context)
        events: list[ActionEvent] = []
        at_ms = self._R_FIRST_AT_MS
        previous_at_ms: int | None = None
        stacks = 0
        while at_ms <= context.duration_ms:
            if previous_at_ms is not None:
                if at_ms - previous_at_ms <= self._R_STACK_DURATION_MS:
                    stacks = min(self._R_MAX_STACKS, stacks + 1)
                else:
                    stacks = 0
            cast_index = len(events) + 1
            events.append(
                action(
                    f"KASSADIN_R_RIFTWALK_{cast_index}_STACK_{stacks}",
                    at_ms=at_ms,
                    sequence=sequence + cast_index,
                    source=context.self_entity,
                    channel=ActionChannel.MOVEMENT,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            base_damage + Decimal(stacks) * stack_damage,
                            DamageType.MAGIC,
                        ),
                    ),
                )
            )
            previous_at_ms = at_ms
            at_ms += cooldown_ms
        return tuple(events)

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Null Sphere damage and its self magic-shield approximation.

        :param context: Snapshot supplying AP, haste, role IDs, and duration.
        :return: Rank-five projectile events with damage and shield outputs.
        """
        cooldown_ms = self._cooldown_ms(Decimal(7), context.snapshot.ability_haste)
        ap = context.snapshot.ability_power
        sequence = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = self._Q_FIRST_AT_MS
        while at_ms <= context.duration_ms:
            cast_index = len(events) + 1
            events.append(
                action(
                    f"KASSADIN_Q_NULL_SPHERE_{cast_index}",
                    at_ms=at_ms,
                    sequence=sequence + cast_index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal(185) + Decimal("0.70") * ap,
                            DamageType.MAGIC,
                        ),
                        shielding(
                            context.self_entity,
                            Decimal(200) + Decimal("0.30") * ap,
                            duration_ms=1500,
                        ),
                    ),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def _e_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule rank-five Force Pulse without inferred cooldown refunds.

        :param context: Snapshot supplying AP, haste, role IDs, and duration.
        :return: Magic-damage cone events carrying the one-second slow.
        """
        cooldown_ms = self._cooldown_ms(Decimal(17), context.snapshot.ability_haste)
        sequence = self._sequence_base(context) + 200
        events: list[ActionEvent] = []
        at_ms = self._E_FIRST_AT_MS
        while at_ms <= context.duration_ms:
            cast_index = len(events) + 1
            events.append(
                action(
                    f"KASSADIN_E_FORCE_PULSE_{cast_index}",
                    at_ms=at_ms,
                    sequence=sequence + cast_index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal(190) + Decimal("0.70") * context.snapshot.ability_power,
                            DamageType.MAGIC,
                        ),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=1000,
                            magnitude=Decimal("0.70"),
                        ),
                    ),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build Nether Blade reset attacks and ordinary passive attacks.

        :param context: Snapshot supplying combat stats, haste, and duration.
        :return: Blind-susceptible physical and bonus-magic attack events.
        """
        attack_interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        w_cooldown_ms = self._cooldown_ms(Decimal(7), context.snapshot.ability_haste)
        sequence = self._sequence_base(context) + 300
        ap = context.snapshot.ability_power
        events: list[ActionEvent] = []
        next_w_ms = self._W_FIRST_AT_MS
        next_basic_ms = self._BASIC_ATTACK_FIRST_AT_MS
        w_index = 1
        basic_index = 1
        while min(next_w_ms, next_basic_ms) <= context.duration_ms:
            if next_w_ms <= next_basic_ms:
                event_id = f"KASSADIN_W_NETHER_BLADE_ATTACK_{w_index}"
                at_ms = next_w_ms
                magic = Decimal(50) + Decimal("0.80") * ap
                next_basic_ms = next_w_ms + attack_interval_ms
                next_w_ms += w_cooldown_ms
                w_index += 1
            else:
                event_id = f"KASSADIN_BASIC_ATTACK_{basic_index}"
                at_ms = next_basic_ms
                magic = Decimal(25) + Decimal("0.10") * ap
                next_basic_ms += attack_interval_ms
                basic_index += 1
            events.append(
                action(
                    event_id,
                    at_ms=at_ms,
                    sequence=sequence + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            context.snapshot.attack_damage,
                            DamageType.PHYSICAL,
                        ),
                        damage(context.opponent_entity, magic, DamageType.MAGIC),
                    ),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked Q5/E5/W1/R2 level-13 rotation.

        :param context: Role-bound Kassadin and opponent combat snapshots.
        :return: Deterministic spell, Riftwalk-stack, and attack events with blockers.
        """
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"KASSADIN_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        events = tuple(
            sorted(
                (
                    *self._riftwalk_events(context),
                    *self._q_events(context),
                    *self._e_events(context),
                    *self._attack_events(context),
                ),
                key=lambda event: (event.at_ms, event.sequence, event.id),
            )
        )
        return ActionPlan(
            "kassadin_q5_e5_w1_r2_level13_riftwalk_stack_v1",
            events,
            (
                *level_blockers,
                "KASSADIN_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "KASSADIN_MAX_MANA_FIXED_TO_LEVEL13_INNATE_VALUE",
                "KASSADIN_MANA_COSTS_AND_CAST_AFFORDABILITY_NOT_MODELED",
                "KASSADIN_W_MANA_RESTORE_AND_LIVE_MISSING_MANA_NOT_MODELED",
                "KASSADIN_R_PREEXISTING_STACKS_NOT_MODELED",
                "KASSADIN_R_DESTINATION_HIT_AND_TERRAIN_GEOMETRY_ASSUMED",
                "KASSADIN_E_NEARBY_CAST_COOLDOWN_REDUCTION_NOT_MODELED",
                "KASSADIN_Q_MAGIC_ONLY_SHIELD_APPROXIMATED_AS_GENERIC_SHIELD",
                "KASSADIN_Q_CHANNEL_INTERRUPT_NOT_MODELED",
                "KASSADIN_W_ATTACK_RESET_TIMING_UNVERIFIED",
                "KASSADIN_PASSIVE_UNIT_COLLISION_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Void Stone mitigation and Force Pulse movement slows.

        :param context: Role-bound snapshots identifying Kassadin and the opponent.
        :return: Continuous magic mitigation and source-linked slow windows.
        """
        e_events = self._e_events(context)
        return ReactionPlan(
            "kassadin_void_stone_q5_e5_reaction_v1",
            damage_windows=(
                DamageModifierWindow(
                    "kassadin_passive_void_stone_magic_reduction",
                    0,
                    context.duration_ms,
                    context.self_entity,
                    (DamageType.MAGIC,),
                    Decimal("0.90"),
                ),
            ),
            cast_block_windows=tuple(
                CastBlockWindow(
                    f"kassadin_e_force_pulse_slow_{index}",
                    event.at_ms,
                    min(event.at_ms + 1000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    event.id,
                    True,
                    ControlType.SLOW,
                )
                for index, event in enumerate(e_events, start=1)
            ),
            blockers=(
                "KASSADIN_Q_MAGIC_SHIELD_DAMAGE_TYPE_FILTER_NOT_MODELED",
                "KASSADIN_Q_CHANNEL_INTERRUPT_NOT_MODELED",
                "KASSADIN_E_HIT_AND_CONTROL_TIMING_UNVERIFIED",
                "KASSADIN_PASSIVE_MAGIC_REDUCTION_SOURCE_FILTERING_UNVERIFIED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Report no champion-native health recovery in Kassadin's kit.

        :param context: Role-bound Kassadin lane context.
        :param duration_ms: Lane observation duration in milliseconds.
        :param no_damage_delay_ms: Delay since incoming champion damage.
        :return: Zero additional health and no sustain-specific blocker.
        """
        return Decimal(0), ()
