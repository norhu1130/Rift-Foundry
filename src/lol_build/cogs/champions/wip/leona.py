"""Leona combat Cog backed by the locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    CastBlockWindow,
    ChampionCog,
    CogCapability,
    CogMaturity,
    ControlType,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    StatModifierOutput,
    StatusOutput,
)


class LeonaCog(ChampionCog):
    """Model Leona's Q1/W5/E5/R2 level-13 center-hit engage.

    The fixture assumes Solar Flare lands in its stunning center and Zenith
    Blade hits the duel opponent as its last champion. Eclipse detonations are
    assumed to hit, so their resistance buffs last six seconds. Sunlight is
    applied as a status, but its ally-only detonation is deliberately omitted.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES | {CogCapability.MULTI_TARGET}
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Leona.json",
        "data/raw/16.17.1/communitydragon/champions/89.json",
        "data/raw/16.17.1/communitydragon/champions/leona.bin.json",
    )

    _R_AT_MS = 100
    _E_FIRST_MS = 350
    _Q_FIRST_MS = 700
    _W_FIRST_MS = 0
    _W_DETONATION_DELAY_MS = 3000
    _W_EXTENDED_DURATION_MS = 6000

    @staticmethod
    def _cooldown_ms(base_seconds: Decimal, ability_haste: Decimal) -> int:
        """Convert a locked cooldown through the shared haste convention.

        :param base_seconds: Spell cooldown before ability haste, in seconds.
        :param ability_haste: Non-negative ability haste from the snapshot.
        :return: Deterministically rounded effective cooldown in milliseconds.
        :raises ValueError: If ability haste is negative.
        """
        if ability_haste < 0:
            raise ValueError("ability_haste must be non-negative")
        milliseconds = base_seconds * Decimal(100_000) / (Decimal(100) + ability_haste)
        return max(1, int(milliseconds.to_integral_value(ROUND_HALF_EVEN)))

    def _bonus_resistance(self, context: ParticipantContext, stat: str) -> Decimal:
        """Recover item-provided armor or magic resistance from a snapshot.

        :param context: Role-bound Leona snapshot with permanent item stats.
        :param stat: Either ``ARMOR`` or ``MAGIC_RESISTANCE``.
        :return: Non-negative resistance above Leona's native level value.
        :raises ValueError: If the requested stat is not a supported resistance.
        """
        native = self.snapshot(level=context.snapshot.level)
        if stat == "ARMOR":
            return max(Decimal(0), context.snapshot.armor - native.armor)
        if stat == "MAGIC_RESISTANCE":
            return max(
                Decimal(0),
                context.snapshot.magic_resistance - native.magic_resistance,
            )
        raise ValueError(f"unsupported Eclipse resistance: {stat}")

    def _eclipse_resistance(
        self,
        context: ParticipantContext,
        stat: str,
    ) -> Decimal:
        """Calculate rank-five Eclipse's resistance grant.

        :param context: Role-bound Leona snapshot containing item resistances.
        :param stat: Either ``ARMOR`` or ``MAGIC_RESISTANCE``.
        :return: Fifty plus twenty percent of the matching bonus resistance.
        """
        return Decimal(50) + Decimal("0.20") * self._bonus_resistance(context, stat)

    def _sunlight(self, context: ParticipantContext) -> StatusOutput:
        """Create Leona's ally-consumable Sunlight mark.

        :param context: Role binding used to identify the hostile recipient.
        :return: A locked 1.5-second Sunlight status output.
        """
        return StatusOutput(context.opponent_entity, "LEONA_SUNLIGHT", 1500)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Avoid inventing movement speed absent from Leona's locked kit.

        :param context: Role-bound Leona encounter context.
        :return: Neutral movement-speed multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Zenith Blade's displayed range as approach reach.

        :param context: Role-bound Leona encounter context.
        :return: Maximum modeled Zenith Blade approach distance in game units.
        """
        return Decimal(875)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stat channels absent from Leona's deterministic model.

        :param item: Normalized candidate from the locked item catalog.
        :return: Leona-scoped blocker, or ``None`` for represented channels.
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
            return f"LEONA_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _w_cast_times(self, context: ParticipantContext) -> tuple[int, ...]:
        """Schedule every haste-permitted Eclipse cast in the duel window.

        :param context: Snapshot supplying haste and encounter duration.
        :return: Chronological Eclipse cast timestamps.
        """
        cooldown_ms = self._cooldown_ms(Decimal(10), context.snapshot.ability_haste)
        return tuple(range(self._W_FIRST_MS, context.duration_ms + 1, cooldown_ms))

    def _w_action_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build Eclipse casts and successful single-target detonations.

        :param context: Role-bound snapshots supplying AP and duration.
        :return: Eclipse activation and explosion events in chronological order.
        """
        base = self._sequence_base(context) + 100
        raw_damage = Decimal(175) + Decimal("0.40") * context.snapshot.ability_power
        events: list[ActionEvent] = []
        for index, cast_ms in enumerate(self._w_cast_times(context), start=1):
            events.append(
                action(
                    f"LEONA_W_ECLIPSE_CAST_{index}",
                    at_ms=cast_ms,
                    sequence=base + index * 2,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        StatusOutput(
                            context.self_entity,
                            "LEONA_W_ECLIPSE",
                            self._W_EXTENDED_DURATION_MS,
                        ),
                    ),
                    requires_living_opponent=False,
                )
            )
            detonation_ms = cast_ms + self._W_DETONATION_DELAY_MS
            if detonation_ms <= context.duration_ms:
                events.append(
                    action(
                        f"LEONA_W_ECLIPSE_DETONATION_{index}",
                        at_ms=detonation_ms,
                        sequence=base + index * 2 + 1,
                        source=context.self_entity,
                        channel=ActionChannel.ABILITY,
                        outputs=(
                            *self.area_outputs(
                                context,
                                lambda entity: damage(
                                    entity, raw_damage, DamageType.MAGIC
                                ),
                                centered_on_self=True,
                            ),
                            self._sunlight(context),
                        ),
                    )
                )
        return tuple(events)

    def _e_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule rank-five Zenith Blade hits and roots.

        :param context: Snapshot supplying AP, haste, and encounter duration.
        :return: Chronological Zenith Blade damage and control events.
        """
        base = self._sequence_base(context) + 200
        cooldown_ms = self._cooldown_ms(Decimal(6), context.snapshot.ability_haste)
        raw_damage = Decimal(210) + Decimal("0.40") * context.snapshot.ability_power
        events: list[ActionEvent] = []
        at_ms = self._E_FIRST_MS
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"LEONA_E_ZENITH_BLADE_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, raw_damage, DamageType.MAGIC),
                        crowd_control(
                            context.opponent_entity,
                            "ROOT",
                            duration_ms=500,
                        ),
                        self._sunlight(context),
                    ),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule rank-one Shield of Daybreak empowered attacks.

        :param context: Snapshot supplying attack stats, AP, haste, and duration.
        :return: Chronological physical attacks, bonus magic damage, and stuns.
        """
        base = self._sequence_base(context) + 300
        cooldown_ms = self._cooldown_ms(Decimal(5), context.snapshot.ability_haste)
        bonus_damage = Decimal(10) + Decimal("0.30") * context.snapshot.ability_power
        events: list[ActionEvent] = []
        at_ms = self._Q_FIRST_MS
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"LEONA_Q_SHIELD_OF_DAYBREAK_ATTACK_{index}",
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
                        damage(
                            context.opponent_entity,
                            bonus_damage,
                            DamageType.MAGIC,
                        ),
                        crowd_control(
                            context.opponent_entity,
                            "STUN",
                            duration_ms=1000,
                        ),
                        self._sunlight(context),
                    ),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def _ordinary_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule non-empowered attacks at Leona's item-sensitive cadence.

        :param context: Snapshot supplying attack damage, speed, and duration.
        :return: Chronological ordinary physical basic attacks.
        """
        base = self._sequence_base(context) + 400
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        events: list[ActionEvent] = []
        at_ms = 1400
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"LEONA_BASIC_ATTACK_{index}",
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
            )
            at_ms += interval_ms
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Leona's center-R, E, Q, W, and attack sequence.

        :param context: Role-bound Leona and opponent combat snapshots.
        :return: Deterministic Q1/W5/E5/R2 level-13 plan with blockers.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        ultimate = action(
            "LEONA_R_SOLAR_FLARE_CENTER",
            at_ms=self._R_AT_MS,
            sequence=base,
            source=context.self_entity,
            channel=ActionChannel.ABILITY,
            outputs=(
                *self.area_outputs(
                    context,
                    lambda entity: damage(
                        entity, Decimal(225) + Decimal("0.80") * ap, DamageType.MAGIC
                    ),
                ),
                *self.area_outputs(
                    context,
                    lambda entity: crowd_control(entity, "STUN", duration_ms=1750),
                ),
                self._sunlight(context),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"LEONA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        events = (
            ultimate,
            *self._w_action_events(context),
            *self._e_events(context),
            *self._q_events(context),
            *self._ordinary_attacks(context),
        )
        return ActionPlan(
            "leona_q1_w5_e5_r2_level13_center_engage_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "LEONA_LEVEL13_Q1_W5_E5_R2_POLICY_UNVERIFIED",
                "LEONA_ROTATION_AND_HIT_TIMING_UNVERIFIED",
                "LEONA_R_CENTER_HIT_ASSUMED_OUTER_SLOW_NOT_MODELED",
                "LEONA_E_LAST_CHAMPION_HIT_AND_DASH_LANDING_ASSUMED",
                "LEONA_Q_ATTACK_RESET_CADENCE_NOT_CAUSALLY_MODELED",
                "LEONA_W_TARGET_PROXIMITY_AND_EXTENSION_ASSUMED",
                "LEONA_W_FLAT_DAMAGE_REDUCTION_NOT_MODELED",
                "LEONA_SUNLIGHT_ALLIED_DETONATION_NOT_MODELED",
                "LEONA_E_ZENITH_BLADE_SINGLE_TARGET_LANDING_ASSUMED",
                "LEONA_RESOURCE_COSTS_NOT_EVALUATED",
            ),
        )

    def _w_reaction_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Apply Eclipse's item-sensitive armor and MR bonuses.

        Each buff ends at the next haste-permitted cast when that occurs before
        its six-second extension, preventing synthetic overlapping copies.

        :param context: Role-bound Leona snapshot and encounter duration.
        :return: Eclipse resistance modifier events for the reaction timeline.
        """
        base = self._sequence_base(context) + 900
        cast_times = self._w_cast_times(context)
        events: list[ActionEvent] = []
        for position, cast_ms in enumerate(cast_times):
            next_cast_ms = (
                cast_times[position + 1]
                if position + 1 < len(cast_times)
                else cast_ms + self._W_EXTENDED_DURATION_MS
            )
            duration_ms = min(
                self._W_EXTENDED_DURATION_MS,
                max(1, next_cast_ms - cast_ms),
            )
            events.append(
                action(
                    f"LEONA_W_ECLIPSE_DEFENSE_{position + 1}",
                    at_ms=cast_ms,
                    sequence=base + position,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        StatModifierOutput(
                            context.self_entity,
                            "ARMOR",
                            self._eclipse_resistance(context, "ARMOR"),
                            duration_ms,
                        ),
                        StatModifierOutput(
                            context.self_entity,
                            "MAGIC_RESISTANCE",
                            self._eclipse_resistance(context, "MAGIC_RESISTANCE"),
                            duration_ms,
                        ),
                    ),
                    requires_living_opponent=False,
                )
            )
        return tuple(events)

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Eclipse defenses and Leona's causally linked control windows.

        :param context: Role-bound snapshots for the Leona participant.
        :return: Resistance events plus R, E, and Q cast-block windows.
        """
        controls: list[CastBlockWindow] = [
            CastBlockWindow(
                "leona_r_solar_flare_center_stun",
                self._R_AT_MS,
                min(self._R_AT_MS + 1750, context.duration_ms),
                (
                    ActionChannel.BASIC_ATTACK,
                    ActionChannel.ABILITY,
                    ActionChannel.MOVEMENT,
                ),
                "LEONA_R_SOLAR_FLARE_CENTER",
                True,
                ControlType.STUN,
            )
        ]
        for event in self._e_events(context):
            controls.append(
                CastBlockWindow(
                    f"{event.id.casefold()}_root",
                    event.at_ms,
                    min(event.at_ms + 500, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    event.id,
                    True,
                    ControlType.ROOT,
                )
            )
        for event in self._q_events(context):
            controls.append(
                CastBlockWindow(
                    f"{event.id.casefold()}_stun",
                    event.at_ms,
                    min(event.at_ms + 1000, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    event.id,
                    True,
                    ControlType.STUN,
                )
            )
        return ReactionPlan(
            "leona_w5_q1_e5_r2_defense_and_control_v1",
            events=self._w_reaction_events(context),
            cast_block_windows=tuple(
                sorted(controls, key=lambda window: (window.start_ms, window.id))
            ),
            blockers=(
                "LEONA_W_FLAT_DAMAGE_REDUCTION_NOT_MODELED",
                "LEONA_W_TARGET_PROXIMITY_AND_EXTENSION_ASSUMED",
                "LEONA_W_BUFF_REFRESH_CAUSALITY_APPROXIMATED",
                "LEONA_R_CENTER_HIT_ASSUMED_OUTER_SLOW_NOT_MODELED",
                "LEONA_E_DASH_DISPLACEMENT_PATH_NOT_MODELED",
            ),
        )
