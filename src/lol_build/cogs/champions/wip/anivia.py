"""Anivia combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    DeathPreventionOutput,
    StatusOutput,
)


class AniviaCog(ChampionCog):
    """Model Anivia's Q5/E5/W1/R2 level-13 duel fixture.

    The deterministic rotation detonates both parts of Flash Frost, consumes
    chill with Frostbite, then maintains Glacial Storm. Rebirth uses the
    engine's limited death-prevention primitive; Egg form remains unresolved.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Anivia.json",
        "data/raw/16.17.1/communitydragon/champions/34.json",
        "data/raw/16.17.1/communitydragon/champions/anivia.bin.json",
    )
    _Q_AT_MS = 100
    _Q_RECAST_DELAY_MS = 350
    _E_AT_MS = 700
    _R_AT_MS = 1800

    @staticmethod
    def _interval_ms(seconds: Decimal, ability_haste: Decimal) -> int:
        """Apply ability haste and round a cooldown to deterministic milliseconds.

        :param seconds: Locked cooldown before haste.
        :param ability_haste: Non-negative haste retained by the champion snapshot.
        :return: Positive nearest-even cooldown in milliseconds.
        """
        effective = seconds * Decimal(100) / (Decimal(100) + ability_haste)
        return max(
            1,
            int((effective * Decimal(1000)).to_integral_value(ROUND_HALF_EVEN)),
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose that the fixture grants Anivia no self-directed engage speed.

        :param context: Role-bound Anivia combat context.
        :return: Neutral movement-speed multiplier.
        """
        return Decimal(1)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels that the fixed Anivia fixture cannot resolve.

        AP, attack speed, and ability haste affect represented outputs. Shared
        snapshots resolve penetration, movement, and chassis stats.

        :param item: Normalized candidate from the locked item catalog.
        :return: Anivia-scoped blocker for unsupported stats, otherwise ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"ANIVIA_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks independently from spell damage.

        :param context: Role-bound snapshots supplying attack damage and cadence.
        :return: Deterministic physical attacks through the duel duration.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        sequence = self._sequence_base(context) + 500
        events: list[ActionEvent] = []
        at_ms = 1000
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"ANIVIA_BASIC_ATTACK_{index}",
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

    @staticmethod
    def _q_damage(context: ParticipantContext) -> tuple[Decimal, Decimal]:
        """Calculate rank-five Flash Frost pass and explosion damage.

        :param context: Role-bound snapshot supplying Anivia's ability power.
        :return: Raw pass and explosion magic damage in cast order.
        """
        ap = context.snapshot.ability_power
        return (
            Decimal(130) + Decimal("0.25") * ap,
            Decimal(200) + Decimal("0.45") * ap,
        )

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule every available two-hit Flash Frost cast in the horizon.

        :param context: Role-bound Anivia and opponent snapshots.
        :return: Pass-through and detonation events affected by ability haste.
        """
        pass_damage, explosion_damage = self._q_damage(context)
        cooldown_ms = self._interval_ms(Decimal(7), context.snapshot.ability_haste)
        sequence = self._sequence_base(context) + 10
        events: list[ActionEvent] = []
        cast_at_ms = self._Q_AT_MS
        cast_index = 1
        while cast_at_ms <= context.duration_ms:
            events.append(
                action(
                    f"ANIVIA_Q_FLASH_FROST_{cast_index}_PASSTHROUGH",
                    at_ms=cast_at_ms,
                    sequence=sequence + 2 * cast_index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, pass_damage, DamageType.MAGIC),),
                )
            )
            detonate_at_ms = cast_at_ms + self._Q_RECAST_DELAY_MS
            if detonate_at_ms <= context.duration_ms:
                events.append(
                    action(
                        f"ANIVIA_Q_FLASH_FROST_{cast_index}_DETONATION",
                        at_ms=detonate_at_ms,
                        sequence=sequence + 2 * cast_index + 1,
                        source=context.self_entity,
                        channel=ActionChannel.ABILITY,
                        outputs=(
                            damage(
                                context.opponent_entity,
                                explosion_damage,
                                DamageType.MAGIC,
                            ),
                            crowd_control(
                                context.opponent_entity,
                                "STUN",
                                duration_ms=1500,
                            ),
                        ),
                    )
                )
            cast_at_ms += cooldown_ms
            cast_index += 1
        return tuple(events)

    def _frostbite_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule rank-five Frostbite casts against fixture-guaranteed chill.

        :param context: Role-bound Anivia and opponent snapshots.
        :return: Haste-sensitive doubled Frostbite damage events.
        """
        damage_amount = Decimal(2) * (
            Decimal(155) + Decimal("0.55") * context.snapshot.ability_power
        )
        cooldown_ms = self._interval_ms(Decimal(4), context.snapshot.ability_haste)
        sequence = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = self._E_AT_MS
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"ANIVIA_E_FROSTBITE_{index}_CHILLED",
                    at_ms=at_ms,
                    sequence=sequence + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, damage_amount, DamageType.MAGIC),),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def _storm_ticks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build rank-two Glacial Storm half-second ticks through the horizon.

        The first three ticks use ordinary damage. Later ticks use the locked
        three-times fully formed damage multiplier after 1.5 seconds.

        :param context: Role-bound Anivia and opponent snapshots.
        :return: Ordered raw-magic-damage ticks for the maintained storm.
        """
        ap = context.snapshot.ability_power
        half_second_damage = (Decimal(75) + Decimal("0.125") * ap) / Decimal(2)
        sequence = self._sequence_base(context) + 200
        events: list[ActionEvent] = []
        for index, at_ms in enumerate(range(self._R_AT_MS, context.duration_ms + 1, 500), start=1):
            multiplier = Decimal(3) if at_ms >= self._R_AT_MS + 1500 else Decimal(1)
            events.append(
                action(
                    f"ANIVIA_R_GLACIAL_STORM_TICK_{index}",
                    at_ms=at_ms,
                    sequence=sequence + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            half_second_damage * multiplier,
                            DamageType.MAGIC,
                        ),
                    ),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the chilled burst, maintained storm, attacks, and Rebirth state.

        :param context: Role-bound Anivia and opponent combat snapshots.
        :return: Deterministic spell, attack, and limited passive events.
        """
        base = self._sequence_base(context)
        passive = action(
            "ANIVIA_PASSIVE_REBIRTH_READY",
            at_ms=0,
            sequence=base,
            source=context.self_entity,
            channel=ActionChannel.PASSIVE,
            outputs=(
                StatusOutput(context.self_entity, "ANIVIA_REBIRTH_READY", context.duration_ms),
                DeathPreventionOutput(
                    context.self_entity,
                    health_floor=Decimal(1),
                    duration_ms=context.duration_ms,
                    state_key="ANIVIA_REBIRTH_READY",
                ),
            ),
            requires_living_opponent=False,
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"ANIVIA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "anivia_q5_e5_w1_r2_level13_chilled_storm_v1",
            tuple(
                sorted(
                    (
                        passive,
                        *self._q_events(context),
                        *self._frostbite_events(context),
                        *self._storm_ticks(context),
                        *self._basic_attacks(context),
                    ),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "ANIVIA_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "ANIVIA_Q_PROJECTILE_DOUBLE_HIT_AND_RECAST_TIMING_ASSUMED",
                "ANIVIA_Q_AND_R_CHILL_CAUSALITY_FIXED_BY_FIXTURE",
                "ANIVIA_R_TARGET_REMAINS_IN_FULL_STORM_ASSUMED",
                "ANIVIA_R_TICK_PHASE_UNVERIFIED",
                "ANIVIA_R_CHANNEL_CANCEL_CAUSALITY_NOT_MODELED",
                "ANIVIA_W_WALL_TERRAIN_AND_DISPLACEMENT_NOT_MODELED",
                "ANIVIA_REBIRTH_REPLACEMENT_HEALTH_POOL_NOT_MODELED",
                "ANIVIA_REBIRTH_EGG_RESISTANCES_NOT_MODELED",
                "ANIVIA_REBIRTH_REVIVAL_CONDITION_NOT_MODELED",
                "ANIVIA_REBIRTH_COOLDOWN_READINESS_ASSUMED",
                "ANIVIA_CAST_PROJECTILE_AND_ATTACK_TIMING_UNVERIFIED",
                "ANIVIA_MANA_COSTS_AND_STORM_UPKEEP_NOT_MODELED",
                "ANIVIA_MULTI_TARGET_EFFECTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose haste-sensitive Flash Frost stuns and the storm slow.

        :param context: Role-bound snapshots identifying Anivia's opponent.
        :return: Tenacity-reducible stun and movement-slow windows.
        """
        windows: list[CastBlockWindow] = []
        for event in self._q_events(context):
            if not event.id.endswith("_DETONATION"):
                continue
            windows.append(
                CastBlockWindow(
                    event.id.casefold() + "_stun",
                    event.at_ms,
                    min(event.at_ms + 1500, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY),
                    event.id,
                    True,
                    ControlType.STUN,
                )
            )
        if context.duration_ms > self._R_AT_MS:
            windows.append(
                CastBlockWindow(
                    "anivia_r_glacial_storm_slow",
                    self._R_AT_MS,
                    context.duration_ms,
                    (ActionChannel.MOVEMENT,),
                    "ANIVIA_R_GLACIAL_STORM_TICK_1",
                    True,
                    ControlType.SLOW,
                )
            )
        return ReactionPlan(
            "anivia_q_stuns_r_slow_reaction_v1",
            cast_block_windows=tuple(windows),
            blockers=(
                "ANIVIA_R_SLOW_GROWTH_REPRESENTED_AS_ONE_CONTINUOUS_WINDOW",
                "ANIVIA_W_TERRAIN_CONTROL_NOT_MODELED",
            ),
        )
