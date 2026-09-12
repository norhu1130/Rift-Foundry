"""Braum combat Cog backed by the locked 16.17.1 champion sources."""

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
    StatModifierOutput,
    StatusOutput,
)


class BraumCog(ChampionCog):
    """Model Braum's Q5/E5/W1/R2 level-13 single-target fixture.

    The deterministic duel assumes an ally is available for Stand Behind Me
    and that Braum faces the opponent while Unbreakable is raised. Concussive
    Blows is advanced only by Braum's own Q and attacks; allied stack sources
    remain outside the two-participant scenario.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Braum.json",
        "data/raw/16.17.1/communitydragon/champions/201.json",
        "data/raw/16.17.1/communitydragon/champions/braum.bin.json",
    )

    _PASSIVE_DAMAGE = Decimal(136)
    _PASSIVE_STUN_MS = 1750
    _PASSIVE_LOCKOUT_MS = 4000
    _E_START_MS = 0
    _E_END_MS = 4000
    _R_AT_MS = 250

    @staticmethod
    def _cooldown_ms(base_seconds: Decimal, haste: Decimal) -> int:
        """Convert a base cooldown and ability haste to rounded milliseconds.

        :param base_seconds: Locked spell cooldown in seconds.
        :param haste: Non-negative ability haste from the champion snapshot.
        :return: Deterministic effective cooldown in milliseconds.
        """
        return int(
            (base_seconds * Decimal(100000) / (Decimal(100) + haste)).to_integral_value(
                rounding=ROUND_HALF_EVEN
            )
        )

    def _bonus_resistance(self, context: ParticipantContext, stat: str) -> Decimal:
        """Recover item-provided armor or magic resistance from the snapshot.

        :param context: Role-bound Braum snapshot with optional item modifiers.
        :param stat: ``ARMOR`` or ``MAGIC_RESISTANCE``.
        :return: Non-negative item contribution to the requested resistance.
        """
        native = self.snapshot(level=context.snapshot.level)
        native_value = native.armor if stat == "ARMOR" else native.magic_resistance
        current = context.snapshot.armor if stat == "ARMOR" else context.snapshot.magic_resistance
        return max(Decimal(0), current - native_value)

    def _w_self_resistance(self, context: ParticipantContext, stat: str) -> Decimal:
        """Calculate rank-one W's self resistance grant.

        :param context: Role-bound Braum snapshot containing item resistances.
        :param stat: ``ARMOR`` or ``MAGIC_RESISTANCE``.
        :return: Locked base grant plus thirty-six percent of bonus resistance.
        """
        return self.rank_value("BraumW", "BaseResists", context, Decimal(20)) + Decimal(
            "0.36"
        ) * self._bonus_resistance(context, stat)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose rank-five Unbreakable's movement-speed increase.

        :param context: Role-bound snapshots for the fixed facing fixture.
        :return: Ten-percent movement-speed multiplier while E is raised.
        """
        return Decimal("1.10")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose W's ally-targeted maximum dash range.

        :param context: Role-bound snapshots for the ally-available fixture.
        :return: Locked Stand Behind Me cast range in game units.
        """
        return Decimal(650)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats absent from Braum's deterministic fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Braum-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"BRAUM_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule rank-five Winter's Bite using its haste-adjusted cooldown.

        :param context: Snapshot supplying health, haste, and encounter duration.
        :return: Q damage and decaying-slow events in chronological order.
        """
        base = self._sequence_base(context) + 100
        cooldown_ms = self._cooldown_ms(Decimal(6), context.snapshot.ability_haste)
        raw_damage = (
            self.rank_value("BraumQ", "BaseDamage", context, Decimal(255))
            + Decimal("0.025") * context.snapshot.max_hp
        )
        events: list[ActionEvent] = []
        at_ms = 100
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"BRAUM_Q_WINTERS_BITE_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, raw_damage, DamageType.MAGIC),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=2000,
                            magnitude=Decimal("0.70"),
                        ),
                        StatusOutput(
                            context.opponent_entity,
                            "BRAUM_CONCUSSIVE_STACK",
                            4000,
                        ),
                    ),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks at Braum's item-sensitive cadence.

        :param context: Snapshot supplying attack damage, speed, and duration.
        :return: Deterministic physical basic-attack events.
        """
        base = self._sequence_base(context) + 200
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        events: list[ActionEvent] = []
        at_ms = 500
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"BRAUM_BASIC_ATTACK_{index}",
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
                        StatusOutput(
                            context.opponent_entity,
                            "BRAUM_CONCUSSIVE_STACK",
                            4000,
                        ),
                    ),
                )
            )
            at_ms += interval_ms
        return tuple(events)

    def _passive_events(
        self,
        context: ParticipantContext,
        stack_sources: tuple[ActionEvent, ...],
    ) -> tuple[ActionEvent, ...]:
        """Resolve four-stack procs and post-stun Braum attack damage.

        :param context: Role-bound entities and benchmark duration.
        :param stack_sources: Chronological Q and attack events applying stacks.
        :return: Deterministic passive damage and stun events.
        """
        base = self._sequence_base(context) + 500
        stacks = 0
        lockout_until = -1
        proc_count = 0
        events: list[ActionEvent] = []
        for source in sorted(stack_sources, key=lambda event: (event.at_ms, event.sequence)):
            if source.at_ms < lockout_until:
                if source.channel is ActionChannel.BASIC_ATTACK:
                    events.append(
                        action(
                            f"BRAUM_PASSIVE_POST_STUN_HIT_{len(events) + 1}",
                            at_ms=source.at_ms,
                            sequence=base + len(events),
                            source=context.self_entity,
                            channel=ActionChannel.PASSIVE,
                            outputs=(
                                damage(
                                    context.opponent_entity,
                                    self._PASSIVE_DAMAGE * Decimal("0.40"),
                                    DamageType.MAGIC,
                                ),
                            ),
                        )
                    )
                continue
            stacks += 1
            if stacks != 4:
                continue
            proc_count += 1
            events.append(
                action(
                    f"BRAUM_PASSIVE_CONCUSSIVE_PROC_{proc_count}",
                    at_ms=source.at_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            self._PASSIVE_DAMAGE,
                            DamageType.MAGIC,
                        ),
                        crowd_control(
                            context.opponent_entity,
                            "STUN",
                            duration_ms=self._PASSIVE_STUN_MS,
                        ),
                    ),
                )
            )
            stacks = 0
            lockout_until = source.at_ms + self._PASSIVE_LOCKOUT_MS
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build W, E, R, Q, attacks, and Concussive Blows for level 13.

        :param context: Role-bound Braum and opponent combat snapshots.
        :return: Deterministic Q5/E5/W1/R2 schedule with honest blockers.
        """
        base = self._sequence_base(context)
        q_events = self._q_events(context)
        attacks = self._attack_events(context)
        fixed = (
            action(
                "BRAUM_W_STAND_BEHIND_ME",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatModifierOutput(
                        context.self_entity,
                        "ARMOR",
                        self._w_self_resistance(context, "ARMOR"),
                        3000,
                    ),
                    StatModifierOutput(
                        context.self_entity,
                        "MAGIC_RESISTANCE",
                        self._w_self_resistance(context, "MAGIC_RESISTANCE"),
                        3000,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "BRAUM_E_UNBREAKABLE",
                at_ms=self._E_START_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    movement_speed(
                        context.self_entity,
                        context.snapshot.move_speed * Decimal("0.10"),
                        duration_ms=self._E_END_MS,
                    ),
                    StatusOutput(
                        context.self_entity,
                        "BRAUM_E_FACING_SHIELD",
                        self._E_END_MS,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "BRAUM_R_GLACIAL_FISSURE",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(250) + Decimal("0.60") * context.snapshot.ability_power,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "AIRBORNE",
                        duration_ms=1500,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=4000,
                        magnitude=Decimal("0.50"),
                    ),
                ),
            ),
        )
        passive = self._passive_events(context, (*q_events, *attacks))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"BRAUM_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        events = (*fixed, *q_events, *attacks, *passive)
        return ActionPlan(
            "braum_q5_e5_w1_r2_level13_self_stack_v1",
            tuple(
                sorted(
                    events,
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "BRAUM_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "BRAUM_CAST_ATTACK_AND_PROJECTILE_HIT_TIMING_UNVERIFIED",
                "BRAUM_PASSIVE_ALLIED_STACK_SOURCES_NOT_MODELED",
                "BRAUM_PASSIVE_STACK_RESOLUTION_NOT_CAUSALLY_MODELED",
                "BRAUM_W_ALLY_AVAILABILITY_AND_POSITION_ASSUMED",
                "BRAUM_W_ALLY_RESISTANCE_GRANT_OUTSIDE_TWO_PARTICIPANT_MODEL",
                "BRAUM_E_DIRECTION_AND_PROJECTILE_CLASSIFICATION_NOT_MODELED",
                "BRAUM_E_FIRST_PROJECTILE_NULLIFICATION_NOT_MODELED",
                "BRAUM_R_DISTANCE_BASED_FIRST_KNOCKUP_FIXED_AT_RANK_VALUE",
                "BRAUM_R_MULTI_TARGET_EFFECTS_NOT_MODELED",
                "BRAUM_SLOW_MOVEMENT_EFFECTS_NOT_INTEGRATED",
                "BRAUM_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose E mitigation and the passive/R crowd-control windows.

        :param context: Role-bound snapshots for the fixed Braum fixture.
        :return: Direction-assumed mitigation and causally linked control.
        """
        passive_sources = self._passive_events(
            context,
            (*self._q_events(context), *self._attack_events(context)),
        )
        passive_windows = tuple(
            CastBlockWindow(
                f"{event.id.lower()}_stun",
                event.at_ms,
                min(event.at_ms + self._PASSIVE_STUN_MS, context.duration_ms),
                (
                    ActionChannel.BASIC_ATTACK,
                    ActionChannel.ABILITY,
                    ActionChannel.MOVEMENT,
                ),
                event.id,
                True,
                ControlType.STUN,
            )
            for event in passive_sources
            if event.id.startswith("BRAUM_PASSIVE_CONCUSSIVE_PROC_")
            and event.at_ms < context.duration_ms
        )
        damage_windows = (
            (
                DamageModifierWindow(
                    "braum_e_facing_damage_reduction",
                    self._E_START_MS,
                    min(self._E_END_MS, context.duration_ms),
                    context.self_entity,
                    (DamageType.PHYSICAL, DamageType.MAGIC),
                    Decimal("0.45"),
                ),
            )
            if context.duration_ms > self._E_START_MS
            else ()
        )
        r_windows = (
            CastBlockWindow(
                "braum_r_first_target_knockup",
                self._R_AT_MS,
                min(self._R_AT_MS + 1500, context.duration_ms),
                (
                    ActionChannel.BASIC_ATTACK,
                    ActionChannel.ABILITY,
                    ActionChannel.MOVEMENT,
                ),
                "BRAUM_R_GLACIAL_FISSURE",
                False,
                ControlType.AIRBORNE,
            ),
            CastBlockWindow(
                "braum_r_slow_zone",
                self._R_AT_MS,
                min(self._R_AT_MS + 4000, context.duration_ms),
                (ActionChannel.MOVEMENT,),
                "BRAUM_R_GLACIAL_FISSURE",
                True,
                ControlType.SLOW,
            ),
        )
        return ReactionPlan(
            "braum_e5_passive_r2_reaction_v1",
            damage_windows=damage_windows,
            cast_block_windows=(*r_windows, *passive_windows),
            blockers=(
                "BRAUM_E_DIRECTION_AND_PROJECTILE_CLASSIFICATION_NOT_MODELED",
                "BRAUM_E_ALL_INCOMING_DAMAGE_ASSUMED_FROM_FACING_DIRECTION",
                "BRAUM_E_FIRST_PROJECTILE_NULLIFICATION_NOT_MODELED",
                "BRAUM_E_WINDOW_NOT_CANCEL_LINKED_TO_CAST",
                "BRAUM_R_DISTANCE_BASED_FIRST_KNOCKUP_FIXED_AT_RANK_VALUE",
                "BRAUM_R_SLOW_ZONE_CONTACT_REFRESH_NOT_MODELED",
                "BRAUM_PASSIVE_PROC_DEPENDS_ON_SYNTHETIC_SELF_ONLY_STACK_POLICY",
            ),
        )
