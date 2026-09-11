"""Akali combat Cog backed by the locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import Decimal

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


class AkaliCog(ChampionCog):
    """Model Akali's Q5/E5/W1/R2 level-13 confirmed-mark fixture.

    Perfect Execution establishes contact, both Shuriken Flip casts hit the
    same marked opponent, and Twilight Shroud supplies its rank-one decaying
    movement bonus. The three Q casts fit the fixed energy budget once Shroud's
    energy increase is assumed; energy regeneration itself is not simulated.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Akali.json",
        "data/raw/16.17.1/communitydragon/champions/84.json",
        "data/raw/16.17.1/communitydragon/champions/akali.bin.json",
    )

    _R1_AT_MS = 100
    _E1_AT_MS = 650
    _E2_AT_MS = 1050
    _Q_TIMES_MS = (1250, 2750, 4250)
    _W_AT_MS = 1400
    _R2_AT_MS = 3000

    @staticmethod
    def _q_damage(context: ParticipantContext) -> Decimal:
        """Calculate rank-five Five Point Strike raw magic damage.

        :param context: Snapshot supplying total AD and AP.
        :return: Raw single-target Q damage before resistance.
        """
        return (
            Decimal(145)
            + Decimal("0.65") * context.snapshot.attack_damage
            + Decimal("0.60") * context.snapshot.ability_power
        )

    @staticmethod
    def _e_total_damage(context: ParticipantContext) -> Decimal:
        """Calculate rank-five Shuriken Flip's combined two-cast damage.

        :param context: Snapshot supplying total AD and AP.
        :return: Raw damage shared between E1 and E2.
        """
        return (
            Decimal(350)
            + context.snapshot.attack_damage
            + Decimal("1.10") * context.snapshot.ability_power
        )

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks after the confirmed E recast.

        :param context: Snapshot supplying attack speed, AD, and role bindings.
        :return: Chronological non-passive basic attacks.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 300
        return tuple(
            action(
                f"AKALI_BASIC_ATTACK_{index}",
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
            for index, at_ms in enumerate(
                range(1800, context.duration_ms + 1, interval_ms),
                start=1,
            )
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Shroud's initial rank-one movement multiplier.

        :param context: Role-bound Akali encounter context.
        :return: Initial movement multiplier while Twilight Shroud accelerates.
        """
        return Decimal("1.30")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose the confirmed Shuriken Flip mark's displayed reach.

        :param context: Role-bound Akali encounter context.
        :return: Modeled engagement reach in game units.
        """
        return Decimal(825)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Akali's fixed fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Akali-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"AKALI_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the fixed R1-E1-E2-Q-W-R2 duel sequence.

        :param context: Role-bound Akali and opponent snapshots.
        :return: Deterministic spell, movement, and attack events.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        e_total = self._e_total_damage(context)
        events: list[ActionEvent] = [
            action(
                "AKALI_R1_PERFECT_EXECUTION",
                at_ms=self._R1_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.MOVEMENT,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(220)
                        + Decimal("0.50") * context.snapshot.bonus_attack_damage
                        + Decimal("0.30") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "AKALI_E1_SHURIKEN_FLIP",
                at_ms=self._E1_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal("0.30") * e_total,
                        DamageType.MAGIC,
                    ),
                    StatusOutput(context.opponent_entity, "AKALI_E_MARK", 3000),
                ),
            ),
            action(
                "AKALI_E2_SHURIKEN_FLIP_RECAST",
                at_ms=self._E2_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.MOVEMENT,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal("0.70") * e_total,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "AKALI_W_TWILIGHT_SHROUD",
                at_ms=self._W_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    movement_speed(
                        context.self_entity,
                        Decimal("0.30") * context.snapshot.move_speed,
                        duration_ms=2000,
                    ),
                    StatusOutput(context.self_entity, "AKALI_W_SHROUD", 5000),
                ),
                requires_living_opponent=False,
            ),
            action(
                "AKALI_R2_PERFECT_EXECUTION_MINIMUM",
                at_ms=self._R2_AT_MS,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.MOVEMENT,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(140) + Decimal("0.30") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
        ]
        for index, at_ms in enumerate(self._Q_TIMES_MS, start=1):
            if at_ms > context.duration_ms:
                continue
            events.append(
                action(
                    f"AKALI_Q_FIVE_POINT_STRIKE_{index}",
                    at_ms=at_ms,
                    sequence=base + 100 + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, self._q_damage(context), DamageType.MAGIC),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=500,
                            magnitude=Decimal("0.50"),
                        ),
                    ),
                )
            )
        events.extend(self._attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"AKALI_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "akali_q5_e5_w1_r2_level13_confirmed_mark_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "AKALI_LEVEL13_Q5_E5_W1_R2_LOCKED_RECOMMENDATION_UNVERIFIED",
                "AKALI_CAST_PROJECTILE_AND_DASH_TIMING_UNVERIFIED",
                "AKALI_E_MARK_AND_RECAST_HIT_ASSUMED",
                "AKALI_PASSIVE_RING_AND_EMPOWERED_ATTACK_NOT_MODELED",
                "AKALI_W_INVISIBILITY_AND_TARGETABILITY_NOT_MODELED",
                "AKALI_W_ENERGY_INCREASE_ASSUMED_WITHOUT_RESOURCE_TIMELINE",
                "AKALI_R2_MISSING_HEALTH_AMPLIFICATION_NOT_MODELED",
                "AKALI_Q_TIP_HIT_ASSUMED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Q tip slows without fabricating Shroud untargetability.

        :param context: Role-bound Akali and opponent snapshots.
        :return: Movement-only Q slow windows and explicit Shroud blockers.
        """
        windows = tuple(
            CastBlockWindow(
                f"akali_q_{index}_tip_slow",
                at_ms,
                min(at_ms + 500, context.duration_ms),
                (ActionChannel.MOVEMENT,),
                f"AKALI_Q_FIVE_POINT_STRIKE_{index}",
                True,
                ControlType.SLOW,
            )
            for index, at_ms in enumerate(self._Q_TIMES_MS, start=1)
            if at_ms < context.duration_ms
        )
        return ReactionPlan(
            "akali_q5_tip_slow_reaction_v1",
            cast_block_windows=windows,
            blockers=(
                "AKALI_Q_TIP_HIT_ASSUMED",
                "AKALI_W_INVISIBILITY_AND_TARGETABILITY_NOT_MODELED",
            ),
        )
