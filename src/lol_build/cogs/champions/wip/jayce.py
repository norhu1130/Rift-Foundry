"""Jayce combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    ResistanceReductionOutput,
    StatModifierOutput,
    StatusOutput,
)


class JayceCog(ChampionCog):
    """Model a deterministic Cannon-to-Hammer level-13 Jayce rotation.

    The fixture uses Q6/W1/E6, begins with a primed Cannon stance, fires an
    Acceleration Gate-empowered Shock Blast, consumes all three Hyper Charge
    attacks, then changes to Hammer for Q, the empowered stance attack, W, and
    E. Geometry and resource legality are not inferred by the fixed benchmark.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Jayce.json",
        "data/raw/16.17.1/communitydragon/champions/126.json",
        "data/raw/16.17.1/communitydragon/champions/jayce.bin.json",
    )

    _HAMMER_START_MS = 1200

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose To the Skies!' locked target-cast range.

        :param context: Role-bound Jayce encounter context.
        :return: Maximum modeled leap distance in game units.
        """
        return Decimal(600)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the fixed Jayce fixture.

        Attack damage and ability power reach spell formulas, while health,
        defenses, penetration, movement, and tenacity retain shared semantics.
        The three Hyper Charge attacks are fixed, so attack speed and haste do
        not change this schedule.

        :param item: Normalized candidate from the locked item catalog.
        :return: Jayce-scoped blocker for unsupported stats, otherwise ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "ATTACK_SPEED",
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"JAYCE_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _cannon_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build the locked empowered Shock Blast and Hyper Charge attacks.

        :param context: Snapshot supplying Jayce's attack and ability stats.
        :return: Cannon-form actions before the fixed stance change.
        """
        base = self._sequence_base(context)
        bonus_ad = context.snapshot.bonus_attack_damage
        empowered_q = (Decimal(285) + Decimal("1.30") * bonus_ad) * Decimal("1.40")
        hyper_attack = Decimal("0.62") * context.snapshot.attack_damage
        events = [
            action(
                "JAYCE_START_CANNON_STANCE_PRIMED",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(StatusOutput(context.self_entity, "JAYCE_CANNON_STANCE", 1200),),
                requires_living_opponent=False,
            ),
            action(
                "JAYCE_CANNON_E_ACCELERATION_GATE",
                at_ms=200,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    movement_speed(
                        context.self_entity,
                        context.snapshot.move_speed * Decimal("0.60"),
                        duration_ms=3000,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "JAYCE_CANNON_Q_EMPOWERED_SHOCK_BLAST",
                at_ms=300,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, empowered_q, DamageType.PHYSICAL),),
            ),
            action(
                "JAYCE_CANNON_W_HYPER_CHARGE",
                at_ms=600,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "JAYCE_HYPER_CHARGE_3", 3600),),
                requires_living_opponent=False,
            ),
        ]
        for index, at_ms in enumerate((700, 850, 1000), start=1):
            outputs = [damage(context.opponent_entity, hyper_attack, DamageType.PHYSICAL)]
            if index == 1:
                outputs.extend(
                    (
                        ResistanceReductionOutput(
                            context.opponent_entity,
                            "ARMOR",
                            Decimal("0.30"),
                            1,
                            5000,
                            f"JAYCE_CANNON_R_SHRED_{context.self_entity.value}",
                        ),
                        ResistanceReductionOutput(
                            context.opponent_entity,
                            "MAGIC_RESISTANCE",
                            Decimal("0.30"),
                            1,
                            5000,
                            f"JAYCE_CANNON_R_SHRED_{context.self_entity.value}",
                        ),
                    )
                )
            events.append(
                action(
                    f"JAYCE_HYPER_CHARGE_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 3 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
        return tuple(events)

    def _hammer_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build the locked Hammer stance switch and four damaging actions.

        :param context: Snapshot supplying Jayce and opponent combat stats.
        :return: Hammer-form events after the fixed stance transition.
        """
        base = self._sequence_base(context) + 100
        bonus_ad = context.snapshot.bonus_attack_damage
        return (
            action(
                "JAYCE_R_TRANSFORM_TO_HAMMER",
                at_ms=self._HAMMER_START_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(context.self_entity, "JAYCE_HAMMER_STANCE", 6800),
                    movement_speed(context.self_entity, Decimal(30), duration_ms=750),
                ),
                requires_living_opponent=False,
            ),
            action(
                "JAYCE_HAMMER_Q_TO_THE_SKIES",
                at_ms=1350,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(310) + Decimal("1.35") * bonus_ad,
                        DamageType.PHYSICAL,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=2000,
                        magnitude=Decimal("0.60"),
                    ),
                ),
            ),
            action(
                "JAYCE_HAMMER_R_EMPOWERED_ATTACK",
                at_ms=1600,
                sequence=base + 2,
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
                        Decimal(95) + Decimal("0.30") * bonus_ad,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "JAYCE_HAMMER_W_LIGHTNING_FIELD",
                at_ms=1800,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(140) + context.snapshot.ability_power,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "JAYCE_HAMMER_E_THUNDERING_BLOW",
                at_ms=2200,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal("0.192") * context.opponent_snapshot.max_hp,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=350),
                    StatusOutput(context.opponent_entity, "JAYCE_E_KNOCKBACK_600", 350),
                ),
            ),
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked Q6/W1/E6 Cannon-to-Hammer fixture.

        :param context: Role-bound Jayce and opponent combat snapshots.
        :return: Deterministic two-stance actions and honest model blockers.
        """
        events = tuple(
            sorted(
                (*self._cannon_events(context), *self._hammer_events(context)),
                key=lambda event: (event.at_ms, event.sequence, event.id),
            )
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"JAYCE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "jayce_q6_w1_e6_cannon_to_hammer_level13_synthetic_v1",
            events,
            (
                *level_blockers,
                "JAYCE_LEVEL13_Q6_W1_E6_POLICY_UNVERIFIED",
                "JAYCE_START_CANNON_FIRST_ATTACK_PRIMED_SYNTHETIC",
                "JAYCE_GATE_SHOCK_BLAST_INTERSECTION_ASSUMED",
                "JAYCE_PROJECTILE_TRAVEL_AND_COLLISION_NOT_EVALUATED",
                "JAYCE_MANA_BUDGET_NOT_EVALUATED",
                "JAYCE_COOLDOWN_RECASTS_NOT_EVALUATED",
                "JAYCE_HYPER_CHARGE_ATTACK_TIMING_SYNTHETIC",
                "JAYCE_LIGHTNING_FIELD_TOTAL_DAMAGE_AT_CAST",
                "JAYCE_KNOCKBACK_GEOMETRY_NOT_EVALUATED",
                "JAYCE_POST_KNOCKBACK_ATTACK_ACCESS_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Apply Hammer resistances and Thundering Blow's airborne window.

        :param context: Role-bound Jayce encounter context.
        :return: Stance defense event and causally linked control reaction.
        """
        base = self._sequence_base(context) + 900
        resist_bonus = Decimal(19) + Decimal("0.075") * context.snapshot.bonus_attack_damage
        duration_ms = max(0, context.duration_ms - self._HAMMER_START_MS)
        stance_resists = action(
            "JAYCE_HAMMER_STANCE_RESISTANCES",
            at_ms=self._HAMMER_START_MS,
            sequence=base,
            source=context.self_entity,
            channel=ActionChannel.PASSIVE,
            outputs=(
                StatModifierOutput(context.self_entity, "ARMOR", resist_bonus, duration_ms),
                StatModifierOutput(
                    context.self_entity,
                    "MAGIC_RESISTANCE",
                    resist_bonus,
                    duration_ms,
                ),
            ),
            requires_living_opponent=False,
        )
        return ReactionPlan(
            "jayce_hammer_resists_and_thundering_blow_reaction_v1",
            events=(stance_resists,),
            cast_block_windows=(
                CastBlockWindow(
                    "jayce_hammer_e_airborne",
                    2200,
                    min(2550, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY),
                    "JAYCE_HAMMER_E_THUNDERING_BLOW",
                    False,
                    ControlType.AIRBORNE,
                ),
            ),
            blockers=(
                "JAYCE_HAMMER_RESIST_DURATION_TIED_TO_FIXED_STANCE",
                "JAYCE_E_DISPLACEMENT_NOT_CAUSALLY_CHANGING_ENGAGEMENT",
            ),
        )
