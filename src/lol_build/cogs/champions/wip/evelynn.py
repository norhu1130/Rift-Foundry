"""Evelynn combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    DamageModifierWindow,
    ResistanceReductionOutput,
    StatusOutput,
)


class EvelynnCog(ChampionCog):
    """Model Evelynn's Q5/W5/E1/R2 level-13 assassination fixture.

    The fixture waits for a fully armed Allure, opens with Hate Spike, consumes
    its three marks with recasts, uses empowered Whiplash after Demon Shade,
    and closes with Last Caress under an explicit below-thirty-percent target
    assumption. Dynamic stealth, health thresholds, geometry, and multi-target
    behavior remain visible as blockers rather than invented state.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Evelynn.json",
        "data/raw/16.17.1/communitydragon/champions/28.json",
        "data/raw/16.17.1/communitydragon/champions/evelynn.bin.json",
    )

    _W_CAST_AT_MS = 0
    _W_TRIGGER_AT_MS = 2500
    _E_AT_MS = 4400
    _R_AT_MS = 5200

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

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose empowered Whiplash's target-directed dash range.

        :param context: Role-bound Evelynn encounter context.
        :return: Locked empowered-E target range in game units.
        """
        return Decimal(400)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Evelynn's fixed event policy.

        AP, AD, attack speed, haste, penetration, movement, health, and resists
        affect represented events or snapshots, and plain attacks deal expected
        critical-strike damage through the shared engine. Resource budgets and
        generic sustain modifiers are deliberately not inferred.

        :param item: Normalized candidate from the locked item catalog.
        :return: Evelynn-scoped blocker for unsupported stats, otherwise ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"EVELYNN_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _allure_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Arm and fully trigger rank-five Allure before the opening damage.

        :param context: Role-bound snapshots and participant identifiers.
        :return: Mark and trigger events carrying charm and MR reduction.
        """
        base = self._sequence_base(context)
        return (
            action(
                "EVELYNN_W_ALLURE_MARK",
                at_ms=self._W_CAST_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.opponent_entity, "EVELYNN_W_MARK", 5000),),
            ),
            action(
                "EVELYNN_W_ALLURE_FULL_TRIGGER",
                origin_event_id="EVELYNN_W_ALLURE_MARK",
                at_ms=self._W_TRIGGER_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(
                    ResistanceReductionOutput(
                        context.opponent_entity,
                        "MAGIC_RESISTANCE",
                        self.rank_value("EvelynnW", "MRShred", context, Decimal("0.45")),
                        1,
                        4000,
                        f"EVELYNN_W_MR_SHRED_{context.self_entity.value}",
                    ),
                    crowd_control(context.opponent_entity, "CHARM", duration_ms=2250),
                ),
            ),
        )

    def _hate_spike_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule rank-five Q missiles and their three marked recasts.

        Each initial missile applies a three-charge mark. The fixed fixture
        consumes every charge with one recast at half-second intervals. Haste
        changes the next initial-cast timestamp through the locked four-second
        cooldown while the first cast remains fixed to the Allure arm time.

        :param context: Snapshot supplying AP, haste, roles, and duration.
        :return: Initial and recast magic-damage events within the benchmark.
        """
        ap = context.snapshot.ability_power
        missile_damage = (
            self.rank_value("EvelynnQ", "HateSpikeBaseDamage", context, Decimal(45))
            + Decimal("0.25") * ap
        )
        marked_bonus = (
            self.rank_value("EvelynnQ", "BonusDamageBase", context, Decimal(55))
            + Decimal("0.25") * ap
        )
        cooldown_ms = self._cooldown_ms(
            self.rank_value("EvelynnW", "MonsterCharm", context, Decimal(4)),
            context.snapshot.ability_haste,
        )
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        cast_at_ms = self._W_TRIGGER_AT_MS + 1
        cast_index = 1
        while cast_at_ms <= context.duration_ms:
            events.append(
                action(
                    f"EVELYNN_Q_HATE_SPIKE_{cast_index}",
                    at_ms=cast_at_ms,
                    sequence=base + cast_index * 10,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, missile_damage, DamageType.MAGIC),
                        StatusOutput(context.opponent_entity, "EVELYNN_Q_MARK_3", 4000),
                    ),
                )
            )
            for recast_index in range(1, 4):
                recast_at_ms = cast_at_ms + recast_index * 500
                if recast_at_ms > context.duration_ms:
                    break
                events.append(
                    action(
                        f"EVELYNN_Q_RECAST_{cast_index}_{recast_index}",
                        at_ms=recast_at_ms,
                        sequence=base + cast_index * 10 + recast_index,
                        source=context.self_entity,
                        channel=ActionChannel.ABILITY,
                        outputs=(
                            damage(context.opponent_entity, missile_damage, DamageType.MAGIC),
                            damage(context.opponent_entity, marked_bonus, DamageType.MAGIC),
                        ),
                    )
                )
            cast_at_ms += cooldown_ms
            cast_index += 1
        return tuple(events)

    def _ordinary_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks through the shared clock during the fixed combo.

        :param context: Snapshot supplying attack speed and total attack damage.
        :return: Deterministic physical basic attacks during the benchmark.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 300
        events: list[ActionEvent] = []
        at_ms = 2700
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"EVELYNN_BASIC_ATTACK_{len(events) + 1}",
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

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Evelynn's fixed level-13 assassination sequence.

        :param context: Role-bound Evelynn and opponent combat snapshots.
        :return: Deterministic Q/W/E/R actions, attacks, and honesty blockers.
        """
        ap = context.snapshot.ability_power
        base = self._sequence_base(context) + 200
        empowered_e_ratio = Decimal("0.04") + Decimal("0.00025") * ap
        ultimate_damage = (
            self.rank_value("EvelynnR", "BaseDamage", context, Decimal(250)) + Decimal("0.75") * ap
        ) * Decimal("2.4")
        fixed_events = (
            action(
                "EVELYNN_E_EMPOWERED_WHIPLASH",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        context.opponent_snapshot.max_hp * empowered_e_ratio,
                        DamageType.MAGIC,
                    ),
                    movement_speed(
                        context.self_entity,
                        context.snapshot.move_speed * Decimal("0.30"),
                        duration_ms=2000,
                    ),
                    StatusOutput(context.self_entity, "EVELYNN_E_DASH", 150),
                ),
            ),
            action(
                "EVELYNN_R_LAST_CARESS_EXECUTE_AMPLIFIED",
                at_ms=self._R_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, ultimate_damage, DamageType.MAGIC),
                    StatusOutput(context.self_entity, "EVELYNN_R_UNTARGETABLE", 350),
                    StatusOutput(context.self_entity, "EVELYNN_R_BACKWARD_WARP", 350),
                ),
            ),
        )
        events = tuple(
            sorted(
                (
                    *self._allure_events(context),
                    *self._hate_spike_events(context),
                    *fixed_events,
                    *self._ordinary_attacks(context),
                ),
                key=lambda event: (event.at_ms, event.sequence, event.id),
            )
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"EVELYNN_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "evelynn_q5_w5_e1_r2_level13_assassination_fixture_v1",
            events,
            (
                *level_blockers,
                "EVELYNN_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "EVELYNN_DEMON_SHADE_STEALTH_AND_DETECTION_NOT_MODELED",
                "EVELYNN_W_FULL_ARM_TIME_AND_TRIGGER_HIT_ASSUMED",
                "EVELYNN_Q_PROJECTILE_AND_NEAREST_TARGET_SELECTION_NOT_MODELED",
                "EVELYNN_Q_MARK_CONSUMPTION_AFTER_CANCELLED_EVENTS_NOT_MODELED",
                "EVELYNN_E_DEMON_SHADE_EMPOWERED_STATE_ASSUMED",
                "EVELYNN_E_DASH_POSITION_AND_MULTI_TARGET_PATH_NOT_MODELED",
                "EVELYNN_R_TARGET_CURRENT_HP_BELOW_30_PERCENT_ASSUMED",
                "EVELYNN_R_BACKWARD_POSITION_AND_MULTI_TARGET_AREA_NOT_MODELED",
                "EVELYNN_RESOURCE_COSTS_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Allure charm and Last Caress untargetability.

        :param context: Role-bound Evelynn and opponent combat snapshots.
        :return: Source-linked crowd-control and incoming-damage windows.
        """
        return ReactionPlan(
            "evelynn_w5_r2_reaction_v1",
            damage_windows=(
                DamageModifierWindow(
                    "evelynn_r_last_caress_untargetable",
                    self._R_AT_MS,
                    min(self._R_AT_MS + 350, context.duration_ms),
                    context.self_entity,
                    (DamageType.PHYSICAL, DamageType.MAGIC, DamageType.TRUE),
                    Decimal(0),
                ),
            ),
            cast_block_windows=(
                CastBlockWindow(
                    "evelynn_w_allure_charm",
                    self._W_TRIGGER_AT_MS,
                    min(self._W_TRIGGER_AT_MS + 2250, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                        ActionChannel.ITEM_ACTIVE,
                    ),
                    "EVELYNN_W_ALLURE_FULL_TRIGGER",
                    True,
                    ControlType.CHARM,
                ),
            ),
            blockers=(
                "EVELYNN_W_FULL_ARM_TIME_AND_TRIGGER_HIT_ASSUMED",
                "EVELYNN_R_UNTARGETABILITY_CAUSAL_LINK_NOT_MODELED",
                "EVELYNN_CONTROL_AND_CAST_TIMING_UNVERIFIED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Estimate Demon Shade's maximum recoverable lane-health envelope.

        The returned amount assumes zero starting health and therefore caps the
        locked per-second healing at the level-and-AP recovery threshold. This
        represents item sensitivity without pretending the missing current-HP
        trace is known.

        :param context: Role-bound Evelynn lane snapshot.
        :param duration_ms: Lane observation window in milliseconds.
        :param no_damage_delay_ms: Required delay since champion damage.
        :return: Maximum recovery envelope and explicit state blockers.
        """
        recovery_start_ms = max(4000, no_damage_delay_ms)
        recovery_ms = max(0, duration_ms - recovery_start_ms)
        level = Decimal(context.snapshot.level)
        healing_per_second = Decimal(15) + Decimal(135) * (level - 1) / Decimal(17)
        threshold = (
            self.rank_value("EvelynnR", "BaseDamage", context, Decimal(250))
            + Decimal(20) * (level - 1)
            + Decimal("2.5") * (context.snapshot.ability_power)
        )
        recovered = min(
            threshold,
            healing_per_second * Decimal(recovery_ms) / Decimal(1000),
        )
        return recovered, (
            "EVELYNN_LANE_PASSIVE_CURRENT_HP_AND_THRESHOLD_HEADROOM_NOT_MODELED",
            "EVELYNN_LANE_PASSIVE_ZERO_HP_MAXIMUM_RECOVERY_PROXY",
            "EVELYNN_LANE_PASSIVE_STEALTH_AND_DAMAGE_RESET_NOT_MODELED",
        )
