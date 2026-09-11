"""Fiddlesticks combat Cog backed by the locked 16.17.1 sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import (
    DamageType,
    ResistanceModifiers,
    apply_resistance,
    apply_resistance_pipeline,
)
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    CurrentHealthDamageOutput,
    MissingHealthDamageOutput,
    StatusOutput,
)


class FiddlesticksCog(ChampionCog):
    """Model Fiddlesticks' W5/Q5/E1/R2 level-13 ambush fixture.

    The deterministic policy assumes Crowstorm is cast while unseen, so its
    first quarter-second tick fears the opponent. Terrify then uses its
    recently-feared branch, Reap hits the center, and Bountiful Harvest
    completes one uninterrupted two-second channel. Vision, geometry, and
    channel interruption remain explicit blockers rather than hidden claims.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Fiddlesticks.json",
        "data/raw/16.17.1/communitydragon/champions/9.json",
        "data/raw/16.17.1/communitydragon/champions/fiddlesticks.bin.json",
    )

    _R_CHANNEL_START_MS = 0
    _R_LAND_MS = 1500
    _Q_AT_MS = 1850
    _E_FIRST_AT_MS = 2150
    _W_START_MS = 2500
    _W_TICK_MS = 250

    @staticmethod
    def _cooldown_ms(base_seconds: Decimal, ability_haste: Decimal) -> int:
        """Convert a base cooldown and ability haste to milliseconds.

        :param base_seconds: Cooldown recorded by the locked spell source.
        :param ability_haste: Non-negative haste from the champion snapshot.
        :return: Positive nearest-even deterministic cooldown in milliseconds.
        """
        seconds = base_seconds * Decimal(100) / (Decimal(100) + ability_haste)
        return max(
            1,
            int((seconds * Decimal(1000)).to_integral_value(ROUND_HALF_EVEN)),
        )

    @staticmethod
    def _post_mitigation_magic(
        context: ParticipantContext,
        raw_damage: Decimal,
    ) -> Decimal:
        """Resolve fixed magic damage for a precomputed drain heal.

        :param context: Snapshots supplying target MR and Fiddlesticks penetration.
        :param raw_damage: Raw magic damage dealt by one ordinary drain tick.
        :return: Post-mitigation damage before runtime reaction modifiers.
        """
        resistance = apply_resistance_pipeline(
            context.opponent_snapshot.magic_resistance,
            ResistanceModifiers(
                percent_penetration=context.snapshot.percent_magic_penetration,
                flat_penetration=context.snapshot.flat_magic_penetration,
            ),
        ).effective_resistance
        return apply_resistance(
            raw_damage,
            DamageType.MAGIC,
            armor=context.opponent_snapshot.armor,
            magic_resistance=resistance,
        ).post_mitigation_damage

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose that Fiddlesticks gains no self movement-speed multiplier.

        :param context: Role-bound Fiddlesticks encounter context.
        :return: Neutral movement-speed multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Crowstorm's locked nominal teleport range.

        :param context: Role-bound Fiddlesticks encounter context.
        :return: Eight hundred game units from the Data Dragon spell record.
        """
        return Decimal(800)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels not consumed by the fixed ambush model.

        AP changes all modeled spells, haste can add Reap casts, and attack
        speed changes ordinary attacks. Mana and generic healing modifiers are
        not present in the snapshot or event contracts.

        :param item: Normalized candidate from the locked item catalog.
        :return: Fiddlesticks-scoped blocker, or ``None`` when represented.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"FIDDLESTICKS_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks after Fiddlesticks finishes its drain channel.

        :param context: Role-bound snapshots supplying attack damage and cadence.
        :return: Chronological physical attacks susceptible to blind.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        sequence = self._sequence_base(context) + 500
        events: list[ActionEvent] = []
        at_ms = 1700
        while at_ms <= context.duration_ms:
            if self._W_START_MS < at_ms <= self._W_START_MS + 2000:
                at_ms += interval_ms
                continue
            index = len(events) + 1
            events.append(
                action(
                    f"FIDDLESTICKS_BASIC_ATTACK_{index}",
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

    def _crowstorm_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build Crowstorm's channel marker and twenty quarter-second ticks.

        The first tick carries the fixture-guaranteed unseen fear. Later ticks
        remain passive effects so silence does not incorrectly cancel an
        already active storm.

        :param context: Role-bound snapshot supplying AP and participant roles.
        :return: Channel start plus in-horizon Crowstorm damage events.
        """
        sequence = self._sequence_base(context) + 10
        tick_damage = (Decimal(250) + Decimal("0.50") * context.snapshot.ability_power) / Decimal(4)
        events = [
            action(
                "FIDDLESTICKS_R_CROWSTORM_CHANNEL_START",
                at_ms=self._R_CHANNEL_START_MS,
                sequence=sequence,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(
                        context.self_entity,
                        "FIDDLESTICKS_R_CHANNELING",
                        1500,
                    ),
                ),
                requires_living_opponent=False,
            )
        ]
        for tick_index in range(1, 21):
            at_ms = self._R_LAND_MS + self._W_TICK_MS * (tick_index - 1)
            if at_ms > context.duration_ms:
                break
            outputs = [damage(context.opponent_entity, tick_damage, DamageType.MAGIC)]
            if tick_index == 1:
                outputs.append(
                    crowd_control(
                        context.opponent_entity,
                        "FEAR",
                        duration_ms=2000,
                    )
                )
            events.append(
                action(
                    f"FIDDLESTICKS_R_CROWSTORM_TICK_{tick_index}",
                    at_ms=at_ms,
                    sequence=sequence + tick_index,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=tuple(outputs),
                )
            )
        return tuple(events)

    def _reap_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule rank-one center-hit Reap casts using ability haste.

        :param context: Role-bound snapshot supplying AP and ability haste.
        :return: One or more magic-damage, slow, and silence events.
        """
        amount = Decimal(70) + Decimal("0.50") * context.snapshot.ability_power
        cooldown_ms = self._cooldown_ms(Decimal(10), context.snapshot.ability_haste)
        sequence = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = self._E_FIRST_AT_MS
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"FIDDLESTICKS_E_REAP_CENTER_{index}",
                    at_ms=at_ms,
                    sequence=sequence + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, amount, DamageType.MAGIC),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=1250,
                            magnitude=Decimal("0.30"),
                        ),
                        crowd_control(
                            context.opponent_entity,
                            "SILENCE",
                            duration_ms=1250,
                        ),
                    ),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def _harvest_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build one completed rank-five Bountiful Harvest channel.

        Eight ordinary ticks use the locked four-ticks-per-second cadence. The
        final event also applies the rank-five missing-health damage primitive.
        Ordinary ticks heal for rank-five ``VampPercentage`` (55%) of the damage
        they deal; final missing-health healing cannot yet be causally linked
        because missing-health damage outputs carry no heal ratio.

        :param context: Role-bound snapshots supplying AP, MR, and penetration.
        :return: Channel marker and eight drain tick events.
        """
        sequence = self._sequence_base(context) + 200
        tick_damage = (Decimal(180) + Decimal("0.45") * context.snapshot.ability_power) / Decimal(4)
        events = [
            action(
                "FIDDLESTICKS_W_BOUNTIFUL_HARVEST_START",
                at_ms=self._W_START_MS,
                sequence=sequence,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(
                        context.self_entity,
                        "FIDDLESTICKS_W_CHANNELING",
                        2000,
                    ),
                ),
            )
        ]
        for tick_index in range(1, 9):
            outputs = [
                damage(
                    context.opponent_entity,
                    tick_damage,
                    DamageType.MAGIC,
                    source_heal_ratio=Decimal("0.55"),
                ),
            ]
            if tick_index == 8:
                outputs.append(
                    MissingHealthDamageOutput(
                        context.opponent_entity,
                        Decimal(0),
                        Decimal("0.22"),
                        DamageType.MAGIC,
                    )
                )
            events.append(
                action(
                    f"FIDDLESTICKS_W_BOUNTIFUL_HARVEST_TICK_{tick_index}",
                    at_ms=self._W_START_MS + self._W_TICK_MS * tick_index,
                    sequence=sequence + tick_index,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=tuple(outputs),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked level-13 unseen Crowstorm ambush sequence.

        :param context: Role-bound Fiddlesticks and opponent snapshots.
        :return: Deterministic spells, drain sustain, attacks, and blockers.
        """
        base = self._sequence_base(context)
        q_ratio = Decimal(2) * (
            Decimal("0.06") + Decimal("0.0003") * context.snapshot.ability_power
        )
        q = action(
            "FIDDLESTICKS_Q_TERRIFY_RECENTLY_FEARED",
            at_ms=self._Q_AT_MS,
            sequence=base + 50,
            source=context.self_entity,
            channel=ActionChannel.ABILITY,
            outputs=(
                CurrentHealthDamageOutput(
                    context.opponent_entity,
                    q_ratio,
                    DamageType.MAGIC,
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"FIDDLESTICKS_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "fiddlesticks_w5_q5_e1_r2_level13_unseen_ambush_v1",
            tuple(
                sorted(
                    (
                        *self._crowstorm_events(context),
                        q,
                        *self._reap_events(context),
                        *self._harvest_events(context),
                        *self._basic_attacks(context),
                    ),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "FIDDLESTICKS_LEVEL13_W5_Q5_E1_R2_POLICY_UNVERIFIED",
                "FIDDLESTICKS_UNSEEN_CROWSTORM_FEAR_FIXED_BY_FIXTURE",
                "FIDDLESTICKS_UNSEEN_OUT_OF_COMBAT_AND_VISION_STATE_NOT_MODELED",
                "FIDDLESTICKS_EFFIGY_IMPERSONATION_AND_VISION_NOT_MODELED",
                "FIDDLESTICKS_R_TELEPORT_GEOMETRY_AND_TARGET_STAY_ASSUMED",
                "FIDDLESTICKS_R_CHANNEL_CANCELLATION_CAUSALITY_NOT_MODELED",
                "FIDDLESTICKS_R_TICK_PHASE_UNVERIFIED",
                "FIDDLESTICKS_Q_RECENTLY_FEARED_BRANCH_FIXED_BY_FIXTURE",
                "FIDDLESTICKS_Q_MINIMUM_DAMAGE_FLOOR_NOT_REPRESENTABLE",
                "FIDDLESTICKS_Q_CURRENT_HEALTH_RUNTIME_EXACTNESS_UNVERIFIED",
                "FIDDLESTICKS_E_CENTER_HIT_FIXED_BY_FIXTURE",
                "FIDDLESTICKS_W_FULL_CHANNEL_AND_TARGET_STAY_ASSUMED",
                "FIDDLESTICKS_W_CHANNEL_CANCELLATION_CAUSALITY_NOT_MODELED",
                "FIDDLESTICKS_W_FINAL_MISSING_HEALTH_HEAL_NOT_CAUSALLY_MODELED",
                "FIDDLESTICKS_W_SUCCESSFUL_CHANNEL_COOLDOWN_REFUND_NOT_SCHEDULED",
                "FIDDLESTICKS_MULTI_TARGET_DAMAGE_AND_HEALING_NOT_MODELED",
                "FIDDLESTICKS_CAST_ATTACK_AND_PROJECTILE_TIMING_UNVERIFIED",
                "FIDDLESTICKS_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose unseen Crowstorm fear and every center-hit Reap control window.

        :param context: Role-bound snapshots identifying Fiddlesticks' opponent.
        :return: Source-linked fear, silence, and movement-slow windows.
        """
        windows: list[CastBlockWindow] = [
            CastBlockWindow(
                "fiddlesticks_r_unseen_fear",
                self._R_LAND_MS,
                min(self._R_LAND_MS + 2000, context.duration_ms),
                (
                    ActionChannel.BASIC_ATTACK,
                    ActionChannel.ABILITY,
                    ActionChannel.MOVEMENT,
                    ActionChannel.ITEM_ACTIVE,
                ),
                "FIDDLESTICKS_R_CROWSTORM_TICK_1",
                True,
                ControlType.FEAR,
            )
        ]
        for event in self._reap_events(context):
            windows.extend(
                (
                    CastBlockWindow(
                        event.id.casefold() + "_silence",
                        event.at_ms,
                        min(event.at_ms + 1250, context.duration_ms),
                        (ActionChannel.ABILITY,),
                        event.id,
                        True,
                        ControlType.SILENCE,
                    ),
                    CastBlockWindow(
                        event.id.casefold() + "_slow",
                        event.at_ms,
                        min(event.at_ms + 1250, context.duration_ms),
                        (ActionChannel.MOVEMENT,),
                        event.id,
                        True,
                        ControlType.SLOW,
                    ),
                )
            )
        return ReactionPlan(
            "fiddlesticks_r2_q5_e1_control_level13_locked_v1",
            cast_block_windows=tuple(windows),
            blockers=(
                "FIDDLESTICKS_UNSEEN_CROWSTORM_FEAR_FIXED_BY_FIXTURE",
                "FIDDLESTICKS_Q_RECENTLY_FEARED_DOES_NOT_REFRESH_FEAR_ASSUMED",
                "FIDDLESTICKS_E_CENTER_HIT_FIXED_BY_FIXTURE",
                "FIDDLESTICKS_CHANNEL_INTERRUPTION_NOT_CAUSALLY_PROPAGATED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Decline to invent lane drain targets, health traces, or mana budgets.

        :param context: Role-bound Fiddlesticks lane snapshot.
        :param duration_ms: Lane observation window in milliseconds.
        :param no_damage_delay_ms: Delay before out-of-combat recovery begins.
        :return: Zero extra recovery and precise missing-schedule blockers.
        """
        return Decimal(0), (
            "FIDDLESTICKS_LANE_W_TARGET_CONTACT_SCHEDULE_NOT_MODELED",
            "FIDDLESTICKS_LANE_W_DAMAGE_TO_HEAL_TRACE_NOT_MODELED",
            "FIDDLESTICKS_LANE_MANA_BUDGET_NOT_MODELED",
        )
