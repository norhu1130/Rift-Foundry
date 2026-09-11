"""Draven combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class DravenCog(ChampionCog):
    """Model Draven's Q5/W5/E1/R2 level-13 single-target fixture."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Draven.json",
        "data/raw/16.17.1/communitydragon/champions/119.json",
        "data/raw/16.17.1/communitydragon/champions/draven.bin.json",
    )

    _CRITICAL_DAMAGE_MULTIPLIER = Decimal(2)
    _W_ATTACK_SPEED_BONUS = Decimal("0.40")
    _W_MOVE_SPEED_BONUS = Decimal("0.70")
    _FIRST_ATTACK_MS = 350
    _AXE_FLIGHT_MS = 500
    _E_FIRST_MS = 150

    @classmethod
    def _expected_critical_multiplier(cls, context: ParticipantContext) -> Decimal:
        """Calculate deterministic expected damage from critical-strike chance.

        :param context: Draven context containing critical-strike chance.
        :return: Expected multiplier for a critical-capable attack packet.
        """
        return Decimal(1) + context.snapshot.critical_strike_chance * (
            cls._CRITICAL_DAMAGE_MULTIPLIER - Decimal(1)
        )

    @classmethod
    def _spinning_attack_damage(cls, context: ParticipantContext) -> Decimal:
        """Calculate one Q5 Spinning Axe attack in the fixed catch fixture.

        :param context: Draven context containing total and bonus attack damage.
        :return: Raw physical attack damage including Q's bonus packet.
        """
        q_bonus = Decimal(60) + Decimal("1.15") * context.snapshot.bonus_attack_damage
        return (context.snapshot.attack_damage + q_bonus) * cls._expected_critical_multiplier(
            context
        )

    @classmethod
    def _w_attack_speed(cls, context: ParticipantContext) -> Decimal:
        """Calculate attack speed while rank-five Blood Rush is active.

        :param context: Draven context containing base and item attack speed.
        :return: Attacks per second after W's ratio-scaled forty-percent bonus.
        """
        return context.snapshot.attack_speed + Decimal("0.679") * cls._W_ATTACK_SPEED_BONUS

    def _spinning_axe_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Q attacks, deterministic catches, and W resets.

        Every emitted catch is an explicit fixture assumption. It renews one
        axe and permits an immediate Blood Rush recast, but does not claim the
        landing position is reachable in a real encounter.

        :param context: Role-bound snapshots and benchmark duration.
        :return: Chronological Q attack, catch, and W-recast events.
        """
        base = self._sequence_base(context) + 100
        interval_ms = self._attack_interval_ms(self._w_attack_speed(context))
        events: list[ActionEvent] = []
        at_ms = self._FIRST_ATTACK_MS
        attack_index = 1
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"DRAVEN_Q_SPINNING_AXE_ATTACK_{attack_index}",
                    at_ms=at_ms,
                    sequence=base + attack_index * 3,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            self._spinning_attack_damage(context),
                            DamageType.PHYSICAL,
                        ),
                    ),
                )
            )
            catch_ms = at_ms + self._AXE_FLIGHT_MS
            if catch_ms <= context.duration_ms:
                events.extend(
                    (
                        action(
                            f"DRAVEN_Q_FIXED_AXE_CATCH_{attack_index}",
                            at_ms=catch_ms,
                            sequence=base + attack_index * 3 + 1,
                            source=context.self_entity,
                            channel=ActionChannel.PASSIVE,
                            outputs=(StatusOutput(context.self_entity, "DRAVEN_Q_AXE_CAUGHT", 1),),
                            requires_living_opponent=False,
                        ),
                        action(
                            f"DRAVEN_W_BLOOD_RUSH_RESET_RECAST_{attack_index}",
                            at_ms=catch_ms + 1,
                            sequence=base + attack_index * 3 + 2,
                            source=context.self_entity,
                            channel=ActionChannel.ABILITY,
                            outputs=(
                                StatusOutput(context.self_entity, "DRAVEN_W_ACTIVE", 3000),
                                movement_speed(
                                    context.self_entity,
                                    context.snapshot.move_speed * self._W_MOVE_SPEED_BONUS,
                                    duration_ms=1500,
                                ),
                            ),
                            requires_living_opponent=False,
                        ),
                    )
                )
            attack_index += 1
            at_ms += interval_ms
        return tuple(events)

    @staticmethod
    def _e_cooldown_ms(context: ParticipantContext) -> int:
        """Convert E1's cooldown through the snapshot's ability haste.

        :param context: Draven context containing nonnegative ability haste.
        :return: Rounded Stand Aside cooldown in milliseconds.
        """
        cooldown = (
            Decimal(16000)
            * Decimal(100)
            / (Decimal(100) + max(Decimal(0), context.snapshot.ability_haste))
        )
        return int(cooldown.to_integral_value(rounding=ROUND_HALF_EVEN))

    def _stand_aside_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule E1 casts whose cooldown fits inside the benchmark.

        :param context: Role-bound snapshots supplying bonus AD and haste.
        :return: Physical damage, displacement, and slow events for each cast.
        """
        base = self._sequence_base(context) + 500
        raw_damage = Decimal(75) + Decimal("0.50") * context.snapshot.bonus_attack_damage
        cooldown_ms = self._e_cooldown_ms(context)
        events: list[ActionEvent] = []
        at_ms = self._E_FIRST_MS
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"DRAVEN_E_STAND_ASIDE_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, raw_damage, DamageType.PHYSICAL),
                        crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=500),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=2000,
                            magnitude=Decimal("0.20"),
                        ),
                    ),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Blood Rush's initial movement-speed gain for engagement.

        :param context: Role-bound snapshots for the current encounter.
        :return: Rank-five initial movement-speed multiplier before decay.
        """
        return Decimal(1) + self._W_MOVE_SPEED_BONUS

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stat channels absent from Draven's fixed fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Draven-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "AP",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "MANA_REGEN",
            "OMNIVAMP",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"DRAVEN_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Draven's deterministic level-13 duel rotation.

        :param context: Role-bound Draven and opponent snapshots.
        :return: Q attacks, W resets, E casts, and both R passes.
        """
        base = self._sequence_base(context)
        r_damage = Decimal(300) + Decimal("1.30") * context.snapshot.bonus_attack_damage
        fixed_events = [
            action(
                "DRAVEN_Q_SPINNING_AXE_READY",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "DRAVEN_Q_READY", 5750),),
                requires_living_opponent=False,
            ),
            action(
                "DRAVEN_W_BLOOD_RUSH_INITIAL",
                at_ms=1,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(context.self_entity, "DRAVEN_W_ACTIVE", 3000),
                    movement_speed(
                        context.self_entity,
                        context.snapshot.move_speed * self._W_MOVE_SPEED_BONUS,
                        duration_ms=1500,
                    ),
                ),
                requires_living_opponent=False,
            ),
        ]
        if context.duration_ms >= 700:
            fixed_events.append(
                action(
                    "DRAVEN_R_WHIRLING_DEATH_OUTWARD",
                    at_ms=700,
                    sequence=base + 2,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, r_damage, DamageType.PHYSICAL),),
                )
            )
        if context.duration_ms >= 1400:
            fixed_events.append(
                action(
                    "DRAVEN_R_WHIRLING_DEATH_RETURN",
                    at_ms=1400,
                    sequence=base + 3,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(damage(context.opponent_entity, r_damage, DamageType.PHYSICAL),),
                )
            )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"DRAVEN_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "draven_q5_w5_e1_r2_fixed_catches_level13_v1",
            tuple(
                sorted(
                    (
                        *fixed_events,
                        *self._stand_aside_events(context),
                        *self._spinning_axe_events(context),
                    ),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "DRAVEN_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "DRAVEN_ROTATION_AND_ANIMATION_TIMING_UNVERIFIED",
                "DRAVEN_Q_AXE_LANDING_POSITION_NOT_MODELED",
                "DRAVEN_Q_EVERY_AXE_CATCH_ASSUMED",
                "DRAVEN_Q_CRITICAL_MODIFIER_INTERACTION_UNVERIFIED",
                "DRAVEN_W_RESET_RECAST_AFTER_EACH_CATCH_ASSUMED",
                "DRAVEN_W_MOVEMENT_SPEED_DECAY_NOT_INTEGRATED",
                "DRAVEN_E_DISPLACEMENT_DISTANCE_AND_DIRECTION_NOT_MODELED",
                "DRAVEN_R_GLOBAL_RETURN_GEOMETRY_ASSUMED",
                "DRAVEN_R_MULTI_TARGET_DAMAGE_REDUCTION_NOT_MODELED",
                "DRAVEN_R_ADORATION_EXECUTE_NOT_MODELED",
                "DRAVEN_PROJECTILE_HIT_AND_RANGE_CONTINUITY_ASSUMED",
                "DRAVEN_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose E displacement and slow as causal control windows.

        :param context: Role-bound snapshots for Draven and the opponent.
        :return: Nonreducible airborne windows followed by reducible slows.
        """
        windows: list[CastBlockWindow] = []
        for event in self._stand_aside_events(context):
            windows.extend(
                (
                    CastBlockWindow(
                        f"{event.id.casefold()}_displacement",
                        event.at_ms,
                        min(event.at_ms + 500, context.duration_ms),
                        (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT),
                        event.id,
                        False,
                        ControlType.AIRBORNE,
                    ),
                    CastBlockWindow(
                        f"{event.id.casefold()}_slow",
                        event.at_ms,
                        min(event.at_ms + 2000, context.duration_ms),
                        (ActionChannel.MOVEMENT,),
                        event.id,
                        True,
                        ControlType.SLOW,
                    ),
                )
            )
        return ReactionPlan(
            "draven_e1_displacement_slow_reaction_v1",
            cast_block_windows=tuple(windows),
            blockers=(
                "DRAVEN_E_DISPLACEMENT_DISTANCE_AND_DIRECTION_NOT_MODELED",
                "DRAVEN_E_PROJECTILE_HIT_TIMING_UNVERIFIED",
            ),
        )
