"""Fizz combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, DamageModifierWindow, StatusOutput


class FizzCog(ChampionCog):
    """Model Fizz's E5/W5/Q1/R2 level-13 maximum-range fixture.

    Chum the Waters is fixed to its large-shark tier, Urchin Strike applies
    one ordinary on-hit attack, and Seastone Trident resets the attack timer.
    Playful / Trickster uses the unrecast landing so its slow remains present.
    Geometry and target-selection behavior stay explicit verification blockers.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Fizz.json",
        "data/raw/16.17.1/communitydragon/champions/105.json",
        "data/raw/16.17.1/communitydragon/champions/fizz.bin.json",
    )

    _R_CAST_AT_MS = 0
    _R_DETONATE_AT_MS = 2000
    _Q_FIRST_AT_MS = 2150
    _E_START_AT_MS = 2500
    _E_LAND_AT_MS = 3250
    _W_RESET_ATTACK_AT_MS = 3350
    _BLEED_TICK_MS = 500
    _BLEED_DURATION_MS = 3000

    @staticmethod
    def _cooldown_ms(base_ms: int, ability_haste: Decimal) -> int:
        """Apply the standard ability-haste divisor to one cooldown.

        :param base_ms: Rank-specific cooldown before ability haste.
        :param ability_haste: Non-negative haste from the participant snapshot.
        :return: Deterministically rounded cooldown in milliseconds.
        :raises ValueError: If either cooldown input is negative.
        """
        if base_ms < 0 or ability_haste < 0:
            raise ValueError("cooldown inputs cannot be negative")
        adjusted = Decimal(base_ms) * Decimal(100) / (Decimal(100) + ability_haste)
        return max(1, int(adjusted.to_integral_value(ROUND_HALF_EVEN)))

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Urchin Strike's target dash range.

        :param context: Role-bound Fizz encounter context.
        :return: Locked Urchin Strike cast range in game units.
        """
        return Decimal(550)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats absent from Fizz's fixed combat model.

        :param item: Normalized candidate from the locked item catalog.
        :return: Fizz-scoped blocker for unsupported stats, otherwise ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"FIZZ_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Q1 dashes separately from their on-hit attack component.

        :param context: Snapshot supplying total AD, AP, haste, and role IDs.
        :return: Haste-sensitive ability and blind-susceptible on-hit events.
        """
        cooldown_ms = self._cooldown_ms(8000, context.snapshot.ability_haste)
        magic = Decimal(10) + Decimal("0.55") * context.snapshot.ability_power
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = self._Q_FIRST_AT_MS
        while at_ms <= context.duration_ms:
            index = len(events) // 2 + 1
            events.extend(
                (
                    action(
                        f"FIZZ_Q_URCHIN_STRIKE_{index}",
                        at_ms=at_ms,
                        sequence=base + index * 2,
                        source=context.self_entity,
                        channel=ActionChannel.ABILITY,
                        outputs=(damage(context.opponent_entity, magic, DamageType.MAGIC),),
                    ),
                    action(
                        f"FIZZ_Q_ON_HIT_{index}",
                        at_ms=at_ms,
                        sequence=base + index * 2 + 1,
                        source=context.self_entity,
                        channel=ActionChannel.BASIC_ATTACK,
                        outputs=(
                            damage(
                                context.opponent_entity,
                                context.snapshot.attack_damage,
                                DamageType.PHYSICAL,
                            ),
                        ),
                    ),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build W reset attacks and intervening empowered ordinary attacks.

        :param context: Snapshot supplying total AD, AP, attack speed, and duration.
        :return: Blind-susceptible attacks with haste-sensitive W resets.
        """
        attack_interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        reset_interval_ms = self._cooldown_ms(3000, context.snapshot.ability_haste)
        ap = context.snapshot.ability_power
        active_magic = (
            self.rank_value("FizzW", "ActiveBaseDamage", context, Decimal(150))
            + Decimal("0.45") * ap
        )
        buff_magic = (
            self.rank_value("FizzW", "OnHitBuffBaseDamage", context, Decimal(40))
            + Decimal("0.30") * ap
        )
        base = self._sequence_base(context) + 200
        events: list[ActionEvent] = []
        reset_at_ms = self._W_RESET_ATTACK_AT_MS
        reset_index = 1
        ordinary_index = 1
        while reset_at_ms <= context.duration_ms:
            reset_id = (
                "FIZZ_W_SEASTONE_RESET_ATTACK"
                if reset_index == 1
                else f"FIZZ_W_SEASTONE_RESET_ATTACK_{reset_index}"
            )
            events.append(
                action(
                    reset_id,
                    at_ms=reset_at_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            context.snapshot.attack_damage,
                            DamageType.PHYSICAL,
                        ),
                        damage(context.opponent_entity, active_magic, DamageType.MAGIC),
                    ),
                )
            )
            next_reset_ms = reset_at_ms + reset_interval_ms
            at_ms = reset_at_ms + attack_interval_ms
            while at_ms < next_reset_ms and at_ms <= context.duration_ms:
                events.append(
                    action(
                        f"FIZZ_BASIC_ATTACK_{ordinary_index}",
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
                            damage(context.opponent_entity, buff_magic, DamageType.MAGIC),
                        ),
                    )
                )
                ordinary_index += 1
                at_ms += attack_interval_ms
            reset_at_ms = next_reset_ms
            reset_index += 1
        return tuple(events)

    def _bleed_events(
        self,
        context: ParticipantContext,
        attack_events: tuple[ActionEvent, ...],
    ) -> tuple[ActionEvent, ...]:
        """Approximate W's non-stacking bleed under repeated refreshes.

        :param context: Snapshot supplying Fizz's AP and encounter duration.
        :param attack_events: Chronological Q and ordinary attacks applying W passive.
        :return: Passive-channel magic-damage ticks inside the horizon.
        """
        if not attack_events:
            return ()
        total_bleed = (
            self.rank_value("FizzW", "DoTBaseDamage", context, Decimal(90))
            + Decimal("0.25") * context.snapshot.ability_power
        )
        tick_damage = total_bleed / Decimal(6)
        final_expiry = min(context.duration_ms, attack_events[-1].at_ms + self._BLEED_DURATION_MS)
        base = self._sequence_base(context) + 400
        events: list[ActionEvent] = []
        at_ms = attack_events[0].at_ms + self._BLEED_TICK_MS
        while at_ms <= final_expiry:
            events.append(
                action(
                    f"FIZZ_W_SEASTONE_BLEED_TICK_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(damage(context.opponent_entity, tick_damage, DamageType.MAGIC),),
                )
            )
            at_ms += self._BLEED_TICK_MS
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Fizz's locked maximum-range shark duel sequence.

        :param context: Role-bound Fizz and opponent combat snapshots.
        :return: Deterministic R, Q, E, W, attack, and bleed events with blockers.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        q_events = self._q_events(context)
        attack_events = self._attack_events(context)
        fixed_events = (
            action(
                "FIZZ_R_CHUM_THE_WATERS_ATTACH_MAX_RANGE",
                at_ms=self._R_CAST_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(context.opponent_entity, "FIZZ_R_TRUE_SIGHT", 2000),
                    crowd_control(
                        context.opponent_entity, "SLOW", duration_ms=2000, magnitude=Decimal("0.80")
                    ),
                ),
            ),
            action(
                "FIZZ_R_CHUM_THE_WATERS_LARGE_SHARK",
                at_ms=self._R_DETONATE_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(450) + Decimal("0.90") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=1000),
                ),
            ),
            action(
                "FIZZ_E_PLAYFUL_START",
                at_ms=self._E_START_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.MOVEMENT,
                outputs=(StatusOutput(context.self_entity, "FIZZ_E_UNTARGETABLE", 750),),
                requires_living_opponent=False,
            ),
            action(
                "FIZZ_E_TRICKSTER_LANDING",
                at_ms=self._E_LAND_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("FizzE", "BaseDamage", context, Decimal(280))
                        + Decimal("0.95") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=2000,
                        magnitude=self.rank_value("FizzE", "SlowAmount", context, Decimal("0.60")),
                    ),
                ),
            ),
        )
        on_hit_events = tuple(event for event in q_events if "_ON_HIT_" in event.id)
        all_attacks = tuple(sorted((*on_hit_events, *attack_events), key=lambda event: event.at_ms))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"FIZZ_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "fizz_e5_w5_q1_r2_level13_large_shark_v1",
            tuple(
                sorted(
                    (
                        *fixed_events,
                        *q_events,
                        *attack_events,
                        *self._bleed_events(context, all_attacks),
                    ),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "FIZZ_LEVEL13_E5_W5_Q1_R2_POLICY_UNVERIFIED",
                "FIZZ_R_MAXIMUM_DISTANCE_LARGE_SHARK_HIT_ASSUMED",
                "FIZZ_R_DISTANCE_TIER_AND_PROJECTILE_COLLISION_NOT_MODELED",
                "FIZZ_R_KNOCKBACK_AND_MULTI_TARGET_NOT_MODELED",
                "FIZZ_Q_TARGET_SELECTION_AND_DASH_PATH_NOT_MODELED",
                "FIZZ_Q_ON_HIT_EFFECT_SET_PARTIAL",
                "FIZZ_W_BLEED_STATIC_SCHEDULE_IGNORES_CANCELLED_ON_HIT",
                "FIZZ_E_UNRECAST_LANDING_AND_HIT_ASSUMED",
                "FIZZ_E_TERRAIN_AND_DASH_GEOMETRY_NOT_MODELED",
                "FIZZ_W_ATTACK_RESET_TIMING_UNVERIFIED",
                "FIZZ_W_RECAST_RESOURCE_AND_CAST_AVAILABILITY_ASSUMED",
                "FIZZ_W_BLEED_TICK_ALIGNMENT_AND_REFRESH_SIMPLIFIED",
                "FIZZ_PASSIVE_GHOSTING_AND_BASIC_ATTACK_REDUCTION_NOT_MODELED",
                "FIZZ_RESOURCE_COSTS_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose R and E slows, R knockup, and E's untargetable interval.

        :param context: Role-bound snapshots identifying Fizz and the opponent.
        :return: Source-linked control and incoming-damage reaction windows.
        """
        return ReactionPlan(
            "fizz_r2_e5_reaction_v1",
            damage_windows=(
                DamageModifierWindow(
                    "fizz_e_untargetable",
                    self._E_START_AT_MS,
                    min(self._E_LAND_AT_MS, context.duration_ms),
                    context.self_entity,
                    (DamageType.PHYSICAL, DamageType.MAGIC, DamageType.TRUE),
                    Decimal(0),
                ),
            ),
            cast_block_windows=(
                CastBlockWindow(
                    "fizz_r_attached_slow",
                    self._R_CAST_AT_MS,
                    min(self._R_DETONATE_AT_MS, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "FIZZ_R_CHUM_THE_WATERS_ATTACH_MAX_RANGE",
                    True,
                    ControlType.SLOW,
                ),
                CastBlockWindow(
                    "fizz_r_large_shark_knockup",
                    self._R_DETONATE_AT_MS,
                    min(self._R_DETONATE_AT_MS + 1000, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                        ActionChannel.ITEM_ACTIVE,
                    ),
                    "FIZZ_R_CHUM_THE_WATERS_LARGE_SHARK",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "fizz_e_landing_slow",
                    self._E_LAND_AT_MS,
                    min(self._E_LAND_AT_MS + 2000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "FIZZ_E_TRICKSTER_LANDING",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=(
                "FIZZ_E_UNTARGETABLE_SOURCE_FILTERING_NOT_MODELED",
                "FIZZ_E_ALREADY_ATTACHED_EFFECTS_AND_TURRET_INTERACTIONS_NOT_MODELED",
                "FIZZ_R_MAXIMUM_DISTANCE_LARGE_SHARK_HIT_ASSUMED",
                "FIZZ_CONTROL_AND_CAST_TIMING_UNVERIFIED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Report that Fizz's modeled kit supplies no native lane healing.

        :param context: Role-bound Fizz lane context.
        :param duration_ms: Lane observation duration in milliseconds.
        :param no_damage_delay_ms: Delay since incoming champion damage.
        :return: Zero additional health and no sustain-specific blocker.
        """
        return Decimal(0), ()
