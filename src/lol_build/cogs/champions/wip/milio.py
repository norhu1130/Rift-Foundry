"""Milio combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import (
    action,
    crowd_control,
    damage,
    healing,
    movement_speed,
    shielding,
)
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class MilioCog(ChampionCog):
    """Model Milio's E5/W5/Q1/R2 self-support duel fixture.

    The fixture uses both E charges, keeps Milio inside his six-second W, lands
    Q on the opponent, and casts R once. Ally selection, Fired Up transfer,
    attack-range changes, cleansing, and temporary tenacity remain blockers
    instead of being silently treated as self-only effects.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Milio.json",
        "data/raw/16.17.1/communitydragon/champions/902.json",
        "data/raw/16.17.1/communitydragon/champions/milio.bin.json",
    )

    _FIRST_E_AT_MS = 0
    _Q_IMPACT_AT_MS = 800
    _SECOND_E_AT_MS = 1000
    _W_AT_MS = 1250
    _R_AT_MS = 4000

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks without claiming Fired Up ownership.

        :param context: Snapshot supplying attack damage, speed, and duration.
        :return: Chronological basic attacks after Q resolves.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 500
        return tuple(
            action(
                f"MILIO_BASIC_ATTACK_{index}",
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
            for index, at_ms in enumerate(range(1500, context.duration_ms + 1, interval), start=1)
        )

    def _campfire_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Split W5's total self-heal across six one-second ticks.

        :param context: Snapshot supplying AP, roles, and duration.
        :return: Six deterministic Cozy Campfire healing events.
        """
        total = Decimal(150) + Decimal("0.15") * context.snapshot.ability_power
        tick = total / Decimal(6)
        base = self._sequence_base(context) + 200
        return tuple(
            action(
                f"MILIO_W_COZY_CAMPFIRE_HEAL_{index}",
                at_ms=at_ms,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(healing(context.self_entity, tick),),
                requires_living_opponent=False,
            )
            for index, at_ms in enumerate(
                range(
                    self._W_AT_MS + 1000, min(self._W_AT_MS + 6000, context.duration_ms) + 1, 1000
                ),
                start=1,
            )
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose one E5 charge's locked twenty-percent movement boost.

        :param context: Role-bound Milio encounter context.
        :return: Initial Warm Hugs movement multiplier.
        """
        return Decimal("1.20")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return zero because Milio has no displacement movement ability.

        :param context: Role-bound Milio encounter context.
        :return: Zero dash distance.
        """
        return Decimal(0)

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Avoid repeating mana-gated W as unconditional lane recovery.

        :param context: Role-bound Milio encounter context.
        :param duration_ms: Requested lane observation duration.
        :param no_damage_delay_ms: Time since the last incoming damage event.
        :return: Zero extra health and a resource-state blocker.
        """
        return Decimal(0), ("MILIO_W_REQUIRES_MANA_AND_SELF_TARGET_VALIDATION",)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the selected fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Milio-scoped blocker, or ``None`` for represented channels.
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
            return f"MILIO_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build shields, Q damage, campfire healing, R, and attacks.

        :param context: Role-bound Milio and opponent snapshots.
        :return: Deterministic level-13 action schedule.
        """
        ap = context.snapshot.ability_power
        base = self._sequence_base(context)
        shield = Decimal(165) + Decimal("0.45") * ap
        fixed: list[ActionEvent] = []
        for index, at_ms in enumerate((self._FIRST_E_AT_MS, self._SECOND_E_AT_MS), start=1):
            fixed.append(
                action(
                    f"MILIO_E_WARM_HUGS_CHARGE_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        shielding(
                            context.self_entity,
                            shield,
                            duration_ms=2500,
                            decay_delay_ms=150,
                        ),
                        movement_speed(
                            context.self_entity,
                            Decimal("0.20") * context.snapshot.move_speed,
                            duration_ms=2500,
                        ),
                    ),
                    requires_living_opponent=False,
                )
            )
        fixed.extend(
            (
                action(
                    "MILIO_Q_ULTRA_MEGA_FIRE_KICK",
                    at_ms=self._Q_IMPACT_AT_MS,
                    sequence=base + 10,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal(80) + Decimal("1.20") * ap,
                            DamageType.MAGIC,
                        ),
                        crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=800),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=1500,
                            magnitude=Decimal("0.40") + Decimal("0.0005") * ap,
                        ),
                    ),
                ),
                action(
                    "MILIO_R_BREATH_OF_LIFE_SELF_HEAL",
                    at_ms=self._R_AT_MS,
                    sequence=base + 300,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(healing(context.self_entity, Decimal(250) + Decimal("0.50") * ap),),
                    requires_living_opponent=False,
                ),
            )
        )
        events = (*fixed, *self._campfire_events(context), *self._attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"MILIO_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "milio_e5_w5_q1_r2_self_support_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "MILIO_LEVEL13_E5_W5_Q1_R2_ORDER_LOCKED_UNVERIFIED",
                "MILIO_E_SELF_TARGET_AND_TWO_CHARGES_AVAILABLE_ASSUMED",
                "MILIO_E_SHIELD_DURATION_FROM_MOVE_SPEED_DURATION_ASSUMED",
                "MILIO_W_SELF_TARGET_AND_FULL_SIX_SECOND_RESIDENCE_ASSUMED",
                "MILIO_W_HEAL_TICK_CADENCE_SYNTHETIC",
                "MILIO_Q_DIRECT_TARGET_ALSO_HIT_BY_LANDING_EXPLOSION_ASSUMED",
                "MILIO_PASSIVE_FIRED_UP_ALLY_TRANSFER_NOT_MODELED",
                "MILIO_W_ATTACK_RANGE_INCREASE_NOT_MODELED",
                "MILIO_R_CLEANSE_AND_TEMPORARY_TENACITY_NOT_MODELED",
                "MILIO_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Q displacement and slow while preserving R cleanse blockers.

        :param context: Role-bound Milio and opponent snapshots.
        :return: Q control windows and unsupported R reaction semantics.
        """
        return ReactionPlan(
            "milio_q_airborne_slow_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "milio_q_ultra_mega_fire_kick_airborne",
                    self._Q_IMPACT_AT_MS,
                    min(self._Q_IMPACT_AT_MS + 800, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "MILIO_Q_ULTRA_MEGA_FIRE_KICK",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "milio_q_ultra_mega_fire_kick_slow",
                    self._Q_IMPACT_AT_MS + 800,
                    min(self._Q_IMPACT_AT_MS + 2300, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "MILIO_Q_ULTRA_MEGA_FIRE_KICK",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=(
                "MILIO_Q_KNOCKBACK_DURATION_DERIVED_FROM_LOCKED_FALL_TIME",
                "MILIO_R_CLEANSE_REQUIRES_RUNTIME_STATUS_REMOVAL",
                "MILIO_R_TEMPORARY_TENACITY_REQUIRES_DYNAMIC_CONTROL_MODIFIER",
            ),
        )
