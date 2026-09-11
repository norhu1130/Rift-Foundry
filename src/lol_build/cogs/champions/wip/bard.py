"""Bard combat Cog backed by the locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

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
from lol_build.core.timeline import ActionChannel, ActionEvent, DamageModifierWindow, StatusOutput


class BardCog(ChampionCog):
    """Model Bard's Q5/W5/E1/R2 level-13 single-target fixture.

    The fixture begins with exactly fifteen collected chimes and one ready meep.
    The first attack consumes that meep, while later attacks are ordinary because
    the eight-second meep respawn lands outside the modeled horizon. A shrine was
    placed at least five seconds before combat, so Bard consumes its fully charged
    rank-five heal. The first Q pins the target to terrain; later haste-enabled Q
    casts use the non-collision slow branch. R places only the duel opponent in
    stasis. Terrain traversal and multi-unit outcomes remain explicit blockers.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Bard.json",
        "data/raw/16.17.1/communitydragon/champions/432.json",
        "data/raw/16.17.1/communitydragon/champions/bard.bin.json",
    )

    _FIXTURE_CHIMES = 15
    _Q_FIRST_AT_MS = 250
    _MEEP_ATTACK_AT_MS = 2100
    _W_CONSUME_AT_MS = 2200
    _R_AT_MS = 3000
    _Q_BASE_COOLDOWN_MS = 7000
    _Q_CONTROL_DURATION_MS = 1800
    _R_STASIS_DURATION_MS = 2500

    @staticmethod
    def _cooldown_ms(base_ms: int, ability_haste: Decimal) -> int:
        """Apply ability haste to one locked base cooldown.

        :param base_ms: Rank-specific cooldown in milliseconds.
        :param ability_haste: Non-negative ability haste from Bard's snapshot.
        :return: Cooldown rounded upward to a deterministic millisecond.
        """
        haste = max(Decimal(0), ability_haste)
        return int(
            (Decimal(base_ms) * Decimal(100) / (Decimal(100) + haste)).to_integral_value(
                ROUND_CEILING
            )
        )

    @classmethod
    def _meep_damage(cls, ability_power: Decimal) -> Decimal:
        """Resolve the fixed fifteen-chime meep's single-target magic damage.

        The locked passive data grants 30 base damage, 6 more damage for every
        five-chime checkpoint, and a 40 percent AP ratio. Fifteen chimes therefore
        contribute three checkpoints without extrapolating a time-based chime count.

        :param ability_power: Bard's aggregated ability power.
        :return: Raw magic damage added to the fixture's first basic attack.
        """
        checkpoints = cls._FIXTURE_CHIMES // 5
        return Decimal(30 + checkpoints * 6) + Decimal("0.40") * ability_power

    @staticmethod
    def _shrine_speed_fraction(ability_power: Decimal) -> Decimal:
        """Resolve rank-five Caretaker's Shrine movement speed.

        :param ability_power: Bard's aggregated ability power.
        :return: Movement-speed fraction before its documented decay.
        """
        return Decimal("0.30") + Decimal("0.0006") * ability_power

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose the initial speed of the precharged self-consumed shrine.

        :param context: Role-bound Bard encounter context.
        :return: Initial multiplicative movement-speed factor from rank-five W.
        """
        return Decimal(1) + self._shrine_speed_fraction(context.snapshot.ability_power)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Decline to invent a Magical Journey path without terrain geometry.

        :param context: Role-bound Bard encounter context.
        :return: Zero because portal displacement depends on unmodeled terrain.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Bard's fixed combat policy.

        AP affects Q, meep, shrine healing, and shrine speed; attack speed and AD
        affect basic attacks; ability haste changes Q recasts. Resource spending,
        crit outcomes, and item-derived sustain are not represented.

        :param item: Normalized candidate from the locked item catalog.
        :return: Bard-scoped blocker, or ``None`` for represented stat channels.
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
            return f"BARD_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule rank-five Q casts under a fixed terrain-collision policy.

        :param context: Bard snapshot supplying AP, haste, and entity roles.
        :return: Q damage events with a first-cast stun and later-cast slows.
        """
        cooldown_ms = self._cooldown_ms(self._Q_BASE_COOLDOWN_MS, context.snapshot.ability_haste)
        amount = Decimal(240) + Decimal("0.80") * context.snapshot.ability_power
        base = self._sequence_base(context)
        events: list[ActionEvent] = []
        at_ms = self._Q_FIRST_AT_MS
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            control = "STUN" if index == 1 else "SLOW"
            events.append(
                action(
                    f"BARD_Q_COSMIC_BINDING_{control}_{index}",
                    at_ms=at_ms,
                    sequence=base + index - 1,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, amount, DamageType.MAGIC),
                        crowd_control(
                            context.opponent_entity,
                            control,
                            duration_ms=self._Q_CONTROL_DURATION_MS,
                            magnitude=Decimal("0.60") if control == "SLOW" else Decimal(1),
                        ),
                    ),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule one meep attack followed by cadence-based ordinary attacks.

        :param context: Role-bound snapshot supplying attack damage and speed.
        :return: Chronological attack events with one fixed meep payload.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = self._MEEP_ATTACK_AT_MS
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            outputs = [
                damage(
                    context.opponent_entity,
                    context.snapshot.attack_damage,
                    DamageType.PHYSICAL,
                )
            ]
            if index == 1:
                outputs.append(
                    damage(
                        context.opponent_entity,
                        self._meep_damage(context.snapshot.ability_power),
                        DamageType.MAGIC,
                    )
                )
            events.append(
                action(
                    f"BARD_MEEP_ATTACK_{index}" if index == 1 else f"BARD_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
            at_ms += interval_ms
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Bard's deterministic fifteen-chime duel action schedule.

        :param context: Role-bound Bard and opponent combat snapshots.
        :return: Q, W, R, meep, and ordinary-attack events with scope blockers.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        speed_fraction = self._shrine_speed_fraction(ap)
        fixed_events = (
            action(
                "BARD_W_PRECHARGED_SHRINE_SELF_CONSUME",
                at_ms=self._W_CONSUME_AT_MS,
                sequence=base + 20,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    healing(context.self_entity, Decimal(200) + Decimal("0.70") * ap),
                    movement_speed(
                        context.self_entity,
                        context.snapshot.move_speed * speed_fraction,
                        duration_ms=1500,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "BARD_R_TEMPERED_FATE_TARGET_FIXTURE",
                at_ms=self._R_AT_MS,
                sequence=base + 21,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(
                        context.opponent_entity,
                        "CC_STASIS",
                        self._R_STASIS_DURATION_MS,
                    ),
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"BARD_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "bard_q5_w5_e1_r2_chime15_meep1_level13_v1",
            tuple(
                sorted(
                    (*self._q_events(context), *fixed_events, *self._basic_attacks(context)),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "BARD_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "BARD_CHIME_COUNT_FIXED_AT_15_AND_MEEP_COUNT_FIXED_AT_1",
                "BARD_CHIME_COLLECTION_TIMELINE_AND_SCALING_PROGRESSION_NOT_MODELED",
                "BARD_MEEP_SLOW_MAGNITUDE_NOT_PRESENT_IN_LOCKED_SOURCE",
                "BARD_MEEP_SPLASH_AND_MULTI_TARGET_EFFECTS_NOT_MODELED",
                "BARD_Q_FIRST_CAST_WALL_COLLISION_ASSUMED",
                "BARD_Q_SECOND_TARGET_AND_PROJECTILE_GEOMETRY_NOT_MODELED",
                "BARD_W_SHRINE_PRECHARGED_FOR_FIVE_SECONDS_FIXTURE",
                "BARD_W_MOVEMENT_SPEED_DECAY_NOT_MODELED",
                "BARD_E_TERRAIN_PORTAL_GEOMETRY_AND_TRAVEL_NOT_MODELED",
                "BARD_R_TARGET_ONLY_STASIS_FIXTURE",
                "BARD_R_GLOBAL_MULTI_TARGET_AND_STRUCTURE_STASIS_NOT_MODELED",
                "BARD_RESOURCE_COSTS_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Q control and target-only R stasis as source-linked windows.

        R prevents the target's actions and incoming damage in the fixed duel.
        The shared timeline does not model untargetability or simultaneous stasis
        for arbitrary nearby units. Its damage window also cannot be causally
        disabled if the R cast itself is canceled, so that limitation is explicit.

        :param context: Role-bound Bard and opponent combat snapshots.
        :return: Q control plus action and damage suppression for target-only R.
        """
        q_windows: list[CastBlockWindow] = []
        cooldown_ms = self._cooldown_ms(self._Q_BASE_COOLDOWN_MS, context.snapshot.ability_haste)
        at_ms = self._Q_FIRST_AT_MS
        while at_ms <= context.duration_ms:
            index = len(q_windows) + 1
            is_stun = index == 1
            control = ControlType.STUN if is_stun else ControlType.SLOW
            q_windows.append(
                CastBlockWindow(
                    f"bard_q_{control.value.casefold()}_{index}",
                    at_ms,
                    min(at_ms + self._Q_CONTROL_DURATION_MS, context.duration_ms),
                    (
                        (
                            ActionChannel.BASIC_ATTACK,
                            ActionChannel.ABILITY,
                            ActionChannel.MOVEMENT,
                            ActionChannel.ITEM_ACTIVE,
                        )
                        if is_stun
                        else (ActionChannel.MOVEMENT,)
                    ),
                    f"BARD_Q_COSMIC_BINDING_{control.value}_{index}",
                    True,
                    control,
                )
            )
            at_ms += cooldown_ms
        r_end_ms = min(self._R_AT_MS + self._R_STASIS_DURATION_MS, context.duration_ms)
        return ReactionPlan(
            "bard_q5_r2_target_control_level13_v1",
            damage_windows=(
                DamageModifierWindow(
                    "bard_r_target_stasis_damage_immunity",
                    self._R_AT_MS,
                    r_end_ms,
                    context.opponent_entity,
                    (DamageType.PHYSICAL, DamageType.MAGIC, DamageType.TRUE),
                    Decimal(0),
                ),
            ),
            cast_block_windows=(
                *q_windows,
                CastBlockWindow(
                    "bard_r_target_stasis_action_block",
                    self._R_AT_MS,
                    r_end_ms,
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                        ActionChannel.ITEM_ACTIVE,
                    ),
                    "BARD_R_TEMPERED_FATE_TARGET_FIXTURE",
                    False,
                    ControlType.ALL,
                ),
            ),
            blockers=(
                "BARD_Q_PROJECTILE_CONTACT_AND_WALL_COLLISION_UNVERIFIED",
                "BARD_R_TARGET_ONLY_STASIS_FIXTURE",
                "BARD_R_DAMAGE_IMMUNITY_CAUSAL_LINK_NOT_MODELED",
                "BARD_R_UNTARGETABILITY_AND_TARGET_SELECTION_NOT_MODELED",
                "BARD_R_MULTI_UNIT_AND_STRUCTURE_STASIS_NOT_MODELED",
                "BARD_CONTROL_AND_CAST_TIMING_UNVERIFIED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Decline to fabricate shrine placement, charge, and mana schedules.

        :param context: Role-bound Bard lane snapshot.
        :param duration_ms: Lane observation window in milliseconds.
        :param no_damage_delay_ms: Delay since champion damage for gated recovery.
        :return: Zero added health with the missing lane-state evidence blockers.
        """
        return Decimal(0), (
            "BARD_LANE_W_PLACEMENT_AND_CONSUMPTION_SCHEDULE_NOT_MODELED",
            "BARD_LANE_W_CHARGE_STATE_NOT_MODELED",
            "BARD_LANE_CHIME_AND_MANA_TIMELINE_NOT_MODELED",
        )
