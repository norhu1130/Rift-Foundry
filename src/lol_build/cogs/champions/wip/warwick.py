"""Warwick combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import (
    DamageType,
    ResistanceModifiers,
    apply_resistance,
    apply_resistance_pipeline,
)
from lol_build.core.timeline import ActionChannel, ActionEvent, DamageModifierWindow, StatusOutput


class WarwickCog(ChampionCog):
    """Model Warwick's W5/Q5/E1/R2 level-13 duel fixture.

    Blood Hunt supplies its base eight-second pursuit and attack-speed effects
    without guessing when the opponent crosses a health threshold. Eternal
    Hunger damage is attached to on-hit actions, while its missing-health-based
    healing remains explicitly outside the model.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Warwick.json",
        "data/raw/16.17.1/communitydragon/champions/19.json",
        "data/raw/16.17.1/communitydragon/champions/warwick.bin.json",
    )

    _ATTACK_SPEED_RATIO = Decimal("0.638")
    _W5_ATTACK_SPEED_BONUS = Decimal("1.10")

    @staticmethod
    def _passive_damage(context: ParticipantContext) -> Decimal:
        """Calculate level-scaled Eternal Hunger on-hit magic damage.

        :param context: Warwick snapshot supplying level, bonus AD, and AP.
        :return: Raw magic damage added by one passive application.
        """
        level_fraction = Decimal(context.snapshot.level - 1) / Decimal(17)
        return (
            Decimal(6)
            + Decimal(49) * level_fraction
            + Decimal("0.15") * context.snapshot.bonus_attack_damage
            + Decimal("0.10") * context.snapshot.ability_power
        )

    @staticmethod
    def _post_mitigation_magic(
        context: ParticipantContext,
        raw_damage: Decimal,
    ) -> Decimal:
        """Resolve magic damage through target MR and Warwick penetration.

        :param context: Snapshots providing resistance and penetration.
        :param raw_damage: Magic damage before target mitigation.
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
        """Expose W5's base movement bonus toward the hunted opponent.

        :param context: Role-bound snapshots for the Blood Hunt fixture.
        :return: Pursuit movement-speed multiplier.
        """
        return Decimal("1.65")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Decline to invent Infinite Duress range from absent geometry.

        :param context: Role-bound encounter snapshots.
        :return: Zero because the locked sources lack an evaluable range formula.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Warwick's fixed action model.

        :param item: Normalized candidate from the locked item catalog.
        :return: Warwick-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "CRITICAL_STRIKE_CHANCE",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"WARWICK_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _ordinary_attack_events(
        self,
        context: ParticipantContext,
    ) -> tuple[ActionEvent, ...]:
        """Schedule Blood-Hunt-accelerated attacks and passive damage.

        :param context: Role-bound snapshots used for cadence and damage.
        :return: Chronological basic attacks susceptible to blind.
        """
        attack_speed = (
            context.snapshot.attack_speed + self._ATTACK_SPEED_RATIO * self._W5_ATTACK_SPEED_BONUS
        )
        interval_ms = self._attack_interval_ms(attack_speed)
        passive_damage = self._passive_damage(context)
        base = self._sequence_base(context) + 200
        events: list[ActionEvent] = []
        at_ms = 2400
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"WARWICK_PASSIVE_ATTACK_{len(events) + 1}",
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
                        damage(
                            context.opponent_entity,
                            passive_damage,
                            DamageType.MAGIC,
                        ),
                    ),
                )
            )
            at_ms += interval_ms
        return tuple(events)

    def _ultimate_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Create three Infinite Duress hits that heal for their own damage.

        :param context: Role-bound snapshots supplying damage and mitigation.
        :return: Three ability-channel events across the 1.5-second channel.
        """
        base = self._sequence_base(context) + 100
        passive_damage = self._passive_damage(context)
        spell_damage = (
            Decimal(350) + Decimal("1.67") * context.snapshot.bonus_attack_damage
        ) / Decimal(3)
        events: list[ActionEvent] = []
        for index, at_ms in enumerate((300, 800, 1300), start=1):
            outputs = [
                # Infinite Duress heals for 100% of the damage it deals.
                damage(
                    context.opponent_entity,
                    spell_damage,
                    DamageType.MAGIC,
                    source_heal_ratio=Decimal(1),
                ),
                damage(
                    context.opponent_entity,
                    passive_damage,
                    DamageType.MAGIC,
                    source_heal_ratio=Decimal(1),
                ),
            ]
            if index == 1:
                outputs.append(
                    crowd_control(
                        context.opponent_entity,
                        "SUPPRESSION",
                        duration_ms=1500,
                    )
                )
            events.append(
                action(
                    f"WARWICK_R_INFINITE_DURESS_HIT_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=tuple(outputs),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Warwick's W5/Q5/E1/R2 level-13 duel sequence.

        :param context: Role-bound Warwick and opponent snapshots.
        :return: Deterministic attacks, spells, sustain, and blockers.
        """
        base = self._sequence_base(context)
        passive_damage = self._passive_damage(context)
        q_damage = (
            Decimal("1.20") * context.snapshot.attack_damage
            + context.snapshot.ability_power
            + Decimal("0.10") * context.opponent_snapshot.max_hp
        )
        fixed_events = (
            action(
                "WARWICK_W_BLOOD_HUNT_ACTIVE",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "WARWICK_W_HUNT", 8000),),
                requires_living_opponent=False,
            ),
            action(
                "WARWICK_E_PRIMAL_HOWL_START",
                at_ms=100,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "WARWICK_E_DAMAGE_REDUCTION", 1900),),
                requires_living_opponent=False,
            ),
            action(
                "WARWICK_Q_JAWS_OF_THE_BEAST",
                at_ms=1900,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    # Rank-five LifestealPercent: the bite heals 75% of its damage.
                    damage(
                        context.opponent_entity,
                        q_damage,
                        DamageType.MAGIC,
                        source_heal_ratio=Decimal("0.75"),
                    ),
                    damage(
                        context.opponent_entity,
                        passive_damage,
                        DamageType.MAGIC,
                        source_heal_ratio=Decimal("0.75"),
                    ),
                ),
            ),
            action(
                "WARWICK_E_PRIMAL_HOWL_RECAST",
                at_ms=2000,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(crowd_control(context.opponent_entity, "FEAR", duration_ms=1000),),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"WARWICK_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        events = (
            *fixed_events,
            *self._ultimate_events(context),
            *self._ordinary_attack_events(context),
        )
        return ActionPlan(
            "warwick_w5_q5_e1_r2_level13_locked_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            (
                *level_blockers,
                "WARWICK_LEVEL13_W5_Q5_E1_R2_POLICY_UNVERIFIED",
                "WARWICK_ROTATION_TIMING_UNVERIFIED",
                "WARWICK_PASSIVE_LEVEL_INTERPOLATION_UNVERIFIED",
                "WARWICK_PASSIVE_SELF_HEALTH_THRESHOLDS_NOT_MODELED",
                "WARWICK_W_TARGET_HEALTH_THRESHOLDS_NOT_MODELED",
                "WARWICK_W_CHAMPION_DAMAGE_MOVEMENT_BREAK_NOT_MODELED",
                "WARWICK_Q_HOLD_FOLLOW_GEOMETRY_NOT_MODELED",
                "WARWICK_R_COLLISION_AND_MOVE_SPEED_RANGE_NOT_MODELED",
                "WARWICK_R_CHANNEL_INTERRUPTION_PARTIALLY_MODELED",
                "WARWICK_E_RECAST_TIMING_ASSUMED",
                "WARWICK_RESOURCE_COSTS_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose E damage reduction, E fear, and R suppression windows.

        :param context: Role-bound snapshots for the Warwick participant.
        :return: Incoming-damage and opponent-control windows.
        """
        return ReactionPlan(
            "warwick_e1_r2_reaction_v1",
            damage_windows=(
                DamageModifierWindow(
                    "warwick_e_damage_reduction",
                    100,
                    min(2000, context.duration_ms),
                    context.self_entity,
                    (DamageType.PHYSICAL, DamageType.MAGIC),
                    Decimal("0.65"),
                ),
            ),
            cast_block_windows=(
                CastBlockWindow(
                    "warwick_r_suppression",
                    300,
                    min(1800, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                        ActionChannel.ITEM_ACTIVE,
                    ),
                    "WARWICK_R_INFINITE_DURESS_HIT_1",
                    False,
                    ControlType.SUPPRESSION,
                ),
                CastBlockWindow(
                    "warwick_e_fear",
                    2000,
                    min(3000, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                        ActionChannel.ITEM_ACTIVE,
                    ),
                    "WARWICK_E_PRIMAL_HOWL_RECAST",
                    True,
                    ControlType.FEAR,
                ),
            ),
            blockers=(
                "WARWICK_E_DURATION_BIN_TOOLTIP_DISAGREEMENT_UNVERIFIED",
                "WARWICK_E_RECAST_TIMING_ASSUMED",
                "WARWICK_R_CHANNEL_INTERRUPTION_PARTIALLY_MODELED",
                "WARWICK_R_SUPPRESSION_HIT_TIMING_UNVERIFIED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Decline to fabricate lane healing without a health trace.

        :param context: Role-bound Warwick lane snapshot.
        :param duration_ms: Lane observation duration in milliseconds.
        :param no_damage_delay_ms: Required out-of-combat recovery delay.
        :return: Zero recovery and precise unresolved-state blockers.
        """
        return Decimal(0), (
            "WARWICK_LANE_SELF_HEALTH_THRESHOLD_TRACE_NOT_MODELED",
            "WARWICK_LANE_Q_TARGET_AND_RESOURCE_SCHEDULE_NOT_MODELED",
        )
