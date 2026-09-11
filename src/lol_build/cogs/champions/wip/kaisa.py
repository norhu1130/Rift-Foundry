"""Kai'Sa combat Cog backed by the locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    ChampionCog,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, damage, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    MissingHealthDamageOutput,
    StatusOutput,
)


class KaisaCog(ChampionCog):
    """Model Kai'Sa's Q5/W1/E5/R2 level-13 single-target fixture.

    Void Seeker supplies the Plasma required by Killer Instinct. Icathian Rain
    resolves under an explicitly isolated-target assumption, Supercharge delays
    attacks while charging and accelerates them for four seconds, and ordinary
    attacks advance Plasma through deterministic five-hit detonations.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Kaisa.json",
        "data/raw/16.17.1/communitydragon/champions/145.json",
        "data/raw/16.17.1/communitydragon/champions/kaisa.bin.json",
    )
    _BASE_ATTACK_SPEED = Decimal("0.644")
    _ATTACK_SPEED_RATIO = Decimal("0.644")
    _E5_ATTACK_SPEED_BONUS = Decimal("0.80")
    _E_AT_MS = 800

    @classmethod
    def _bonus_attack_speed(cls, context: ParticipantContext) -> Decimal:
        """Infer aggregate bonus attack speed from the final snapshot.

        :param context: Kai'Sa snapshot after level and item aggregation.
        :return: Non-negative aggregate bonus attack-speed fraction.
        """
        return max(
            Decimal(0),
            context.snapshot.attack_speed / cls._BASE_ATTACK_SPEED - Decimal(1),
        )

    @classmethod
    def _supercharge_end_ms(cls, context: ParticipantContext) -> int:
        """Calculate when rank-five Supercharge finishes charging.

        :param context: Kai'Sa snapshot supplying aggregate bonus attack speed.
        :return: Absolute fixture timestamp when attacks may resume.
        """
        cast_seconds = max(
            Decimal("0.60"),
            Decimal("1.20") - Decimal("0.40") * cls._bonus_attack_speed(context),
        )
        cast_ms = int((cast_seconds * Decimal(1000)).to_integral_value(ROUND_HALF_EVEN))
        return cls._E_AT_MS + cast_ms

    @staticmethod
    def _critical_multiplier(context: ParticipantContext) -> Decimal:
        """Return deterministic expected basic-attack critical damage.

        :param context: Kai'Sa snapshot containing critical-strike chance.
        :return: Expected multiplier for the locked 2.0 critical modifier.
        """
        return Decimal(1) + context.snapshot.critical_strike_chance

    @staticmethod
    def _passive_base_damage(context: ParticipantContext) -> Decimal:
        """Evaluate Second Skin's level-scaled base on-hit damage.

        :param context: Kai'Sa snapshot supplying level and ability power.
        :return: Raw magic damage before Plasma's stack increment.
        """
        level_fraction = Decimal(context.snapshot.level - 1) / Decimal(17)
        return (
            Decimal(4)
            + Decimal(26) * level_fraction
            + Decimal("0.12") * context.snapshot.ability_power
        )

    @staticmethod
    def _passive_per_stack_damage(context: ParticipantContext) -> Decimal:
        """Evaluate Second Skin's bonus damage per existing Plasma stack.

        :param context: Kai'Sa snapshot supplying level and ability power.
        :return: Raw magic damage added per pre-hit Plasma stack.
        """
        level_fraction = Decimal(context.snapshot.level - 1) / Decimal(17)
        return (
            Decimal(1)
            + Decimal(7) * level_fraction
            + Decimal("0.03") * context.snapshot.ability_power
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose rank-five Supercharge's initial movement-speed multiplier.

        :param context: Kai'Sa snapshot supplying aggregate bonus attack speed.
        :return: Initial pursuit multiplier before movement-speed soft caps.
        """
        scaling = min(
            Decimal(2),
            max(Decimal(1), Decimal(1) + self._bonus_attack_speed(context)),
        )
        return Decimal(1) + Decimal("0.75") * scaling

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose rank-two Killer Instinct's Plasma-target dash range.

        :param context: Role-bound Kai'Sa encounter context.
        :return: Maximum rank-two dash range in game units.
        """
        return Decimal(2500)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stat channels absent from Kai'Sa's fixed fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Kai'Sa-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "MANA_REGEN",
            "OMNIVAMP",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"KAISA_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks, increasing Plasma damage, and detonations.

        :param context: Role-bound snapshots used for cadence and damage.
        :return: Chronological attack events with passive magic outputs.
        """
        base = self._sequence_base(context) + 100
        e_end_ms = self._supercharge_end_ms(context)
        e_buff_end_ms = e_end_ms + 4000
        empowered_speed = (
            context.snapshot.attack_speed + self._ATTACK_SPEED_RATIO * self._E5_ATTACK_SPEED_BONUS
        )
        passive_base = self._passive_base_damage(context)
        passive_per_stack = self._passive_per_stack_damage(context)
        plasma_stacks = 2
        events: list[ActionEvent] = []
        at_ms = e_end_ms + 150
        while at_ms <= context.duration_ms:
            current_stacks = plasma_stacks
            outputs = [
                damage(
                    context.opponent_entity,
                    context.snapshot.attack_damage * self._critical_multiplier(context),
                    DamageType.PHYSICAL,
                ),
                damage(
                    context.opponent_entity,
                    passive_base + passive_per_stack * current_stacks,
                    DamageType.MAGIC,
                ),
            ]
            plasma_stacks += 1
            detonates = plasma_stacks >= 5
            if detonates:
                outputs.append(
                    MissingHealthDamageOutput(
                        context.opponent_entity,
                        Decimal(0),
                        Decimal("0.15") + Decimal("0.0006") * context.snapshot.ability_power,
                        DamageType.MAGIC,
                    )
                )
                plasma_stacks = 0
            attack_number = len(events) + 1
            events.append(
                action(
                    (
                        f"KAISA_PASSIVE_PLASMA_DETONATION_ATTACK_{attack_number}"
                        if detonates
                        else f"KAISA_BASIC_ATTACK_{attack_number}"
                    ),
                    at_ms=at_ms,
                    sequence=base + attack_number,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
            speed = empowered_speed if at_ms < e_buff_end_ms else context.snapshot.attack_speed
            at_ms += self._attack_interval_ms(speed)
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Kai'Sa's W-R-Q-E opening and Plasma attack schedule.

        :param context: Role-bound Kai'Sa and opponent snapshots.
        :return: Deterministic spell, shield, attack, and passive events.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        total_ad = context.snapshot.attack_damage
        q_missile = (
            Decimal(100)
            + Decimal("0.55") * context.snapshot.bonus_attack_damage
            + Decimal("0.20") * ap
        )
        q_isolated_total = q_missile * Decimal("2.25")
        fixed_events = (
            action(
                "KAISA_W_VOID_SEEKER",
                at_ms=100,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(30) + Decimal("1.30") * total_ad + Decimal("0.45") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "KAISA_R_KILLER_INSTINCT",
                at_ms=400,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(
                        context.self_entity,
                        Decimal(150) + Decimal("1.35") * total_ad + Decimal("1.20") * ap,
                        duration_ms=2000,
                    ),
                ),
            ),
            action(
                "KAISA_Q_ICATHIAN_RAIN_ISOLATED",
                at_ms=600,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_isolated_total, DamageType.PHYSICAL),),
            ),
            action(
                "KAISA_E_SUPERCHARGE",
                at_ms=self._E_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(
                        context.self_entity,
                        "KAISA_E_SUPERCHARGE_CHARGING",
                        self._supercharge_end_ms(context) - self._E_AT_MS,
                    ),
                ),
                requires_living_opponent=False,
            ),
        )
        events = (*fixed_events, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"KAISA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "kaisa_q5_w1_e5_r2_level13_isolated_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "KAISA_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "KAISA_ROTATION_AND_ANIMATION_TIMING_UNVERIFIED",
                "KAISA_W_PROJECTILE_HIT_AND_TRAVEL_TIME_ASSUMED",
                "KAISA_W_SUPPLIES_EXACTLY_TWO_OPENING_PLASMA_STACKS",
                "KAISA_R_DASH_DESTINATION_AND_TRAVEL_TIME_NOT_MODELED",
                "KAISA_R_REQUIRES_W_PLASMA_FIXTURE",
                "KAISA_Q_ALL_SIX_MISSILES_HIT_ONE_ISOLATED_CHAMPION",
                "KAISA_Q_MULTI_TARGET_SPLIT_NOT_MODELED",
                "KAISA_Q_EVOLUTION_STATE_NOT_MODELED",
                "KAISA_W_EVOLUTION_STATE_NOT_MODELED",
                "KAISA_E_EVOLUTION_STATE_AND_INVISIBILITY_NOT_MODELED",
                "KAISA_EVOLUTION_THRESHOLDS_NOT_EVALUATED",
                "KAISA_E_CHARGE_PREVENTS_ATTACKS_BY_SCHEDULE_ASSUMPTION",
                "KAISA_E_ATTACK_COOLDOWN_REDUCTION_NOT_RESCHEDULED",
                "KAISA_PASSIVE_ALLY_IMMOBILIZE_STACKS_NOT_MODELED",
                "KAISA_PASSIVE_STACK_EXPIRY_AND_TARGET_SWITCHING_NOT_MODELED",
                "KAISA_PASSIVE_CANCELLED_HIT_STACK_RECOMPUTATION_NOT_MODELED",
                "KAISA_CRITICAL_ATTACKS_USE_EXPECTED_VALUE",
                "KAISA_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Return neutral reactions while retaining positional uncertainties.

        :param context: Role-bound Kai'Sa and opponent snapshots.
        :return: Neutral reaction plan with explicit evolution blockers.
        """
        return ReactionPlan(
            "kaisa_r2_shield_e5_base_reaction_v1",
            blockers=(
                "KAISA_R_POSITIONAL_EVASION_NOT_MODELED",
                "KAISA_E_EVOLUTION_STATE_AND_INVISIBILITY_NOT_MODELED",
            ),
        )
