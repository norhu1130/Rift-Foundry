"""Dr. Mundo combat Cog backed by the locked 16.17.1 sources."""

from __future__ import annotations

from decimal import Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    ChampionCog,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage, healing
from lol_build.core.combat import (
    DamageType,
    ResistanceModifiers,
    apply_resistance,
    apply_resistance_pipeline,
)
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class DrMundoCog(ChampionCog):
    """Model Dr. Mundo's Q5/W1/E5/R2 level-13 duel fixture.

    Q evaluates champion damage at opening health. W uses an explicit one-hit
    gray-health fixture because incoming timeline damage cannot yet feed later
    outputs. E uses its minimum missing-health multiplier. Each approximation
    remains an explicit verification blocker.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/DrMundo.json",
        "data/raw/16.17.1/communitydragon/champions/36.json",
        "data/raw/16.17.1/communitydragon/champions/drmundo.bin.json",
    )

    @staticmethod
    def _q_damage_for_health(current_hp: Decimal, *, target_is_monster: bool = False) -> Decimal:
        """Evaluate rank-five Bonesaw damage and target-class bounds.

        Champions have the locked 280 minimum and no maximum. The 550 maximum
        applies only to monsters and must never cap champion damage.

        :param current_hp: Target health when the projectile hits.
        :param target_is_monster: Apply the monster-only maximum when true.
        :return: Raw magic damage after applicable bounds.
        """
        result = max(Decimal(280), Decimal("0.30") * current_hp)
        return min(Decimal(550), result) if target_is_monster else result

    @staticmethod
    def _passive_bonus_ad(context: ParticipantContext) -> Decimal:
        """Calculate E5's permanent maximum-health conversion.

        :param context: Snapshot supplying Dr. Mundo's maximum health.
        :return: Attack damage equal to 3.2 percent of maximum health.
        """
        return Decimal("0.032") * context.snapshot.max_hp

    @staticmethod
    def _post_mitigation_opponent_attack(context: ParticipantContext) -> Decimal:
        """Evaluate the one-hit W storage fixture through Mundo's armor.

        :param context: Snapshots supplying opponent AD, penetration, and armor.
        :return: Post-mitigation damage from one opponent basic attack.
        """
        resistance = apply_resistance_pipeline(
            context.snapshot.armor,
            ResistanceModifiers(
                percent_penetration=context.opponent_snapshot.percent_armor_penetration,
                flat_penetration=context.opponent_snapshot.flat_armor_penetration,
            ),
        ).effective_resistance
        return apply_resistance(
            context.opponent_snapshot.attack_damage,
            DamageType.PHYSICAL,
            armor=resistance,
            magic_resistance=context.snapshot.magic_resistance,
        ).post_mitigation_damage

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose rank-two Maximum Dosage movement speed.

        :param context: Role-bound Dr. Mundo encounter context.
        :return: Movement-speed multiplier during the ultimate.
        """
        return Decimal("1.25")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Report that Dr. Mundo has no modeled dash.

        :param context: Role-bound Dr. Mundo encounter context.
        :return: Zero because pursuit uses movement speed.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats that the fixed schedule cannot value.

        :param item: Normalized candidate from the locked item catalog.
        :return: Mundo-scoped blocker, or ``None`` for represented stats.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "AP",
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "MANA_REGEN",
            "OMNIVAMP",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"DRMUNDO_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _ordinary_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks with E's passive health conversion.

        :param context: Snapshot supplying attack damage and cadence.
        :return: Blind-susceptible attacks through the benchmark.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        attack_damage = context.snapshot.attack_damage + self._passive_bonus_ad(context)
        base = self._sequence_base(context) + 300
        events: list[ActionEvent] = []
        at_ms = 1300
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"DRMUNDO_BASIC_ATTACK_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(damage(context.opponent_entity, attack_damage, DamageType.PHYSICAL),),
                )
            )
            at_ms += interval_ms
        return tuple(events)

    def _w_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build W1 activation, twelve damage ticks, and champion-hit recast.

        The gray-health fixture stores 25 percent of one opponent basic attack
        at 1000 ms. It is deliberately labeled synthetic until the engine can
        consume actual incoming damage into a later heal.

        :param context: Snapshots supplying bonus health and armor.
        :return: Heart Zapper health cost, damage, and fixed recovery.
        """
        base = self._sequence_base(context) + 100
        events = [
            action(
                "DRMUNDO_W_HEART_ZAPPER_START",
                at_ms=300,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.self_entity,
                        Decimal("0.08") * context.snapshot.max_hp,
                        DamageType.TRUE,
                    ),
                    StatusOutput(context.self_entity, "DRMUNDO_W_ACTIVE", 3000),
                ),
                requires_living_opponent=False,
            )
        ]
        for tick_index in range(1, 13):
            events.append(
                action(
                    f"DRMUNDO_W_HEART_ZAPPER_TICK_{tick_index}",
                    at_ms=300 + 250 * tick_index,
                    sequence=base + tick_index,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(damage(context.opponent_entity, Decimal(5), DamageType.MAGIC),),
                )
            )
        stored_health = Decimal("0.25") * self._post_mitigation_opponent_attack(context)
        events.append(
            action(
                "DRMUNDO_W_HEART_ZAPPER_RECAST",
                at_ms=3300,
                sequence=base + 20,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(20) + Decimal("0.07") * context.snapshot.bonus_health,
                        DamageType.MAGIC,
                    ),
                    healing(context.self_entity, stored_health),
                ),
            )
        )
        return tuple(events)

    def _ultimate_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule R2 movement and eight in-horizon regeneration ticks.

        :param context: Snapshot supplying maximum health.
        :return: Ultimate activation and max-health regeneration events.
        """
        base = self._sequence_base(context) + 200
        w_cost = Decimal("0.08") * context.snapshot.max_hp
        events = [
            action(
                "DRMUNDO_R_MAXIMUM_DOSAGE_START",
                at_ms=500,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    healing(context.self_entity, Decimal("0.20") * w_cost),
                    StatusOutput(context.self_entity, "DRMUNDO_R_MOVE_SPEED", 10000),
                ),
                requires_living_opponent=False,
            )
        ]
        heal_per_tick = Decimal("0.04") * context.snapshot.max_hp
        for tick_index, at_ms in enumerate(range(1500, 8000, 1000), start=1):
            events.append(
                action(
                    f"DRMUNDO_R_MAXIMUM_DOSAGE_HEAL_{tick_index}",
                    at_ms=at_ms,
                    sequence=base + tick_index,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(healing(context.self_entity, heal_per_tick),),
                    requires_living_opponent=False,
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked Q5/W1/E5/R2 level-13 duel schedule.

        :param context: Role-bound Dr. Mundo and opponent snapshots.
        :return: Deterministic damage, sustain, movement, and audit blockers.
        """
        base = self._sequence_base(context)
        q_damage = self._q_damage_for_health(context.opponent_snapshot.max_hp)
        passive_ad = self._passive_bonus_ad(context)
        e_damage = (
            context.snapshot.attack_damage
            + passive_ad
            + Decimal(45)
            + Decimal("0.05") * context.snapshot.bonus_health
        )
        fixed_events = (
            action(
                "DRMUNDO_Q_INFECTED_BONESAW_1",
                at_ms=100,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.self_entity, Decimal(90), DamageType.TRUE),
                    damage(context.opponent_entity, q_damage, DamageType.MAGIC),
                    healing(context.self_entity, Decimal(90)),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=2000,
                        magnitude=Decimal("0.40"),
                    ),
                ),
            ),
            action(
                "DRMUNDO_E_BLUNT_FORCE_TRAUMA",
                at_ms=2201,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(context.self_entity, Decimal(70), DamageType.TRUE),
                    damage(context.opponent_entity, e_damage, DamageType.PHYSICAL),
                ),
            ),
            action(
                "DRMUNDO_Q_INFECTED_BONESAW_2",
                at_ms=4100,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.self_entity, Decimal(90), DamageType.TRUE),
                    damage(context.opponent_entity, q_damage, DamageType.MAGIC),
                    healing(context.self_entity, Decimal(90)),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=2000,
                        magnitude=Decimal("0.40"),
                    ),
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"DRMUNDO_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "drmundo_q5_w1_e5_r2_level13_synthetic_v1",
            tuple(
                sorted(
                    (
                        *fixed_events,
                        *self._w_events(context),
                        *self._ultimate_events(context),
                        *self._ordinary_attack_events(context),
                    ),
                    key=lambda event: (event.at_ms, event.sequence),
                )
            ),
            (
                *level_blockers,
                "DRMUNDO_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "DRMUNDO_ROTATION_TIMING_UNVERIFIED",
                "DRMUNDO_Q_CURRENT_HEALTH_FROZEN_AT_OPENING_SNAPSHOT",
                "DRMUNDO_Q_PROJECTILE_COLLISION_NOT_EVALUATED",
                "DRMUNDO_W_CURRENT_HEALTH_COST_FROZEN_AT_OPENING_SNAPSHOT",
                "DRMUNDO_W_STORED_DAMAGE_FIXTURE_ONE_BASIC_ATTACK_AT_1000MS",
                "DRMUNDO_W_LIVE_GRAY_HEALTH_ACCUMULATION_NOT_MODELED",
                "DRMUNDO_E_MISSING_HEALTH_DAMAGE_AMPLIFICATION_NOT_MODELED",
                "DRMUNDO_E_KILL_SWAT_AND_NEARBY_TARGETS_NOT_MODELED",
                "DRMUNDO_R_INITIAL_MISSING_HEALTH_USES_KNOWN_W_COST_ONLY",
                "DRMUNDO_R_TAKEDOWN_EXTENSION_AND_R3_EFFECTS_OUTSIDE_FIXTURE",
                "DRMUNDO_PASSIVE_CC_IMMUNITY_CONSUMPTION_NOT_MODELED",
                "DRMUNDO_PASSIVE_CANISTER_PICKUP_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Keep dynamic passive immunity and gray-health reactions unresolved.

        :param context: Role-bound Dr. Mundo encounter context.
        :return: Neutral reaction plan with stateful-mechanic blockers.
        """
        return ReactionPlan(
            "drmundo_passive_w_reaction_unresolved_v1",
            blockers=(
                "DRMUNDO_PASSIVE_FIRST_IMMOBILIZING_EFFECT_ONLY_NOT_MODELED",
                "DRMUNDO_PASSIVE_HEALTH_COST_AND_CANISTER_STATE_NOT_MODELED",
                "DRMUNDO_W_INCOMING_DAMAGE_STORAGE_REQUIRES_LIVE_HEALTH_TRACE",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Decline to estimate passive regeneration without a health trace.

        :param context: Role-bound Dr. Mundo lane snapshot.
        :param duration_ms: Lane observation duration in milliseconds.
        :param no_damage_delay_ms: Required out-of-combat recovery delay.
        :return: Zero recovery and missing lane-state blockers.
        """
        return Decimal(0), (
            "DRMUNDO_LANE_PASSIVE_REGEN_HEALTH_TRACE_NOT_MODELED",
            "DRMUNDO_LANE_Q_HEALTH_COST_REFUND_HIT_RATE_NOT_MODELED",
        )
