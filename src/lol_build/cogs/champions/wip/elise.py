"""Elise combat Cog backed by the locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    CastBlockWindow,
    ChampionCog,
    CogMaturity,
    ControlImmunityWindow,
    ControlType,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage, healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    CurrentHealthDamageOutput,
    DamageModifierWindow,
    MissingHealthDamageOutput,
    StatusOutput,
)


class EliseCog(ChampionCog):
    """Model Elise's Q5/W5/E3/R3 level-13 two-form duel fixture.

    Elise opens in Human Form with Cocoon, Neurotoxin, and Volatile
    Spiderling. She then transforms, uses Rappel to descend on the opponent,
    casts Venomous Bite and Skittering Frenzy, and attacks in Spider Form.
    Both Q health ratios resolve from runtime target health; Spiderling AI and
    target geometry remain explicit blockers.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Elise.json",
        "data/raw/16.17.1/communitydragon/champions/60.json",
        "data/raw/16.17.1/communitydragon/champions/elise.bin.json",
    )

    _ATTACK_SPEED_RATIO = Decimal("0.625")
    _SPIDER_W_PASSIVE_ATTACK_SPEED = Decimal("0.25")
    _SPIDER_W_ACTIVE_ATTACK_SPEED = Decimal("1.20")
    _RAPPEL_AMPLIFICATION = Decimal("0.70")
    _RAPPEL_START_MS = 1400
    _RAPPEL_DESCENT_MS = 1900
    _SPIDER_W_AT_MS = 2200
    _SPIDER_W_END_MS = 5200

    @staticmethod
    def _cooldown_ms(seconds: Decimal, ability_haste: Decimal) -> int:
        """Apply ability haste to a locked base cooldown.

        :param seconds: Rank-specific cooldown in seconds before haste.
        :param ability_haste: Non-negative haste supplied by the snapshot.
        :return: Cooldown rounded to a deterministic positive millisecond.
        """
        effective = seconds * Decimal(100_000) / (Decimal(100) + max(Decimal(0), ability_haste))
        return max(1, int(effective.to_integral_value(ROUND_HALF_EVEN)))

    @staticmethod
    def _q_health_ratio(ability_power: Decimal, base_percent: str) -> Decimal:
        """Resolve a Q percentage-health ratio from locked BIN coefficients.

        :param ability_power: Elise's current ability power.
        :param base_percent: Base percent encoded as decimal text.
        :return: Fractional current- or missing-health ratio for the timeline.
        """
        return Decimal(base_percent) / Decimal(100) + Decimal("0.0003") * ability_power

    @staticmethod
    def _spider_passive_damage(context: ParticipantContext) -> Decimal:
        """Calculate rank-three Spider Queen on-hit magic damage.

        :param context: Elise snapshot supplying ability power.
        :return: Raw magic damage before the Rappel amplification.
        """
        return Decimal(32) + Decimal("0.15") * context.snapshot.ability_power

    @staticmethod
    def _spider_passive_heal(context: ParticipantContext) -> Decimal:
        """Calculate rank-three Spider Queen healing per basic attack.

        :param context: Elise snapshot supplying ability power.
        :return: Health restored before the Rappel amplification.
        """
        return Decimal(10) + Decimal("0.08") * context.snapshot.ability_power

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose the locked targeted Rappel descent range.

        :param context: Role-bound Elise encounter context.
        :return: CommunityDragon's 825-unit descent targeting distance.
        """
        return Decimal(825)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats that the fixed Elise fixture cannot consume.

        AP, AD, attack speed, ability haste, penetration, movement, and chassis
        stats reach represented calculations. Mana costs and generic sustain
        conversions are not inferred from the locked action sequence.

        :param item: Normalized candidate from the locked item catalog.
        :return: Elise-scoped blocker for unsupported stats, otherwise ``None``.
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
            return f"ELISE_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _spider_q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule rank-five Venomous Bite casts with runtime missing health.

        :param context: Elise snapshot supplying AP, haste, and role identifiers.
        :return: Dynamic missing-health damage events within the duel horizon.
        """
        ratio = self._q_health_ratio(context.snapshot.ability_power, "8")
        cooldown_ms = self._cooldown_ms(Decimal(6), context.snapshot.ability_haste)
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 2050
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"ELISE_SPIDER_Q_VENOMOUS_BITE_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        MissingHealthDamageOutput(
                            context.opponent_entity,
                            Decimal(170),
                            ratio,
                            DamageType.MAGIC,
                        ),
                    ),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def _spider_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Spider Form attacks across active and passive W cadence.

        :param context: Elise snapshot supplying AD, AP, and base attack speed.
        :return: Blind-susceptible attacks carrying passive damage and healing.
        """
        active_speed = context.snapshot.attack_speed + self._ATTACK_SPEED_RATIO * (
            self._SPIDER_W_PASSIVE_ATTACK_SPEED + self._SPIDER_W_ACTIVE_ATTACK_SPEED
        )
        passive_speed = context.snapshot.attack_speed + (
            self._ATTACK_SPEED_RATIO * self._SPIDER_W_PASSIVE_ATTACK_SPEED
        )
        active_interval = self._attack_interval_ms(active_speed)
        passive_interval = self._attack_interval_ms(passive_speed)
        passive_damage = self._spider_passive_damage(context)
        passive_heal = self._spider_passive_heal(context)
        base = self._sequence_base(context) + 200
        events: list[ActionEvent] = []
        at_ms = 2300
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            amplified = at_ms < self._RAPPEL_DESCENT_MS + 5000
            multiplier = Decimal(1) + self._RAPPEL_AMPLIFICATION if amplified else Decimal(1)
            events.append(
                action(
                    f"ELISE_SPIDER_ATTACK_{index}",
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
                        damage(
                            context.opponent_entity,
                            passive_damage * multiplier,
                            DamageType.MAGIC,
                        ),
                        healing(context.self_entity, passive_heal * multiplier),
                    ),
                )
            )
            at_ms += active_interval if at_ms < self._SPIDER_W_END_MS else passive_interval
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked Human-to-Spider level-13 combat sequence.

        :param context: Role-bound Elise and opponent combat snapshots.
        :return: Deterministic two-form spells, attacks, sustain, and blockers.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        fixed_events = (
            action(
                "ELISE_HUMAN_E_COCOON",
                at_ms=100,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(crowd_control(context.opponent_entity, "STUN", duration_ms=2000),),
            ),
            action(
                "ELISE_HUMAN_Q_NEUROTOXIN",
                at_ms=300,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    CurrentHealthDamageOutput(
                        context.opponent_entity,
                        self._q_health_ratio(ap, "4"),
                        DamageType.MAGIC,
                    ),
                    damage(context.opponent_entity, Decimal(160), DamageType.MAGIC),
                ),
            ),
            action(
                "ELISE_HUMAN_W_VOLATILE_SPIDERLING",
                at_ms=700,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(220) + Decimal("0.75") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "ELISE_R_TRANSFORM_SPIDER",
                at_ms=1200,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "ELISE_FORM_SPIDER", 6800),),
                requires_living_opponent=False,
            ),
            action(
                "ELISE_SPIDER_E_RAPPEL_ASCEND",
                at_ms=self._RAPPEL_START_MS,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.MOVEMENT,
                outputs=(StatusOutput(context.self_entity, "ELISE_RAPPEL_UNTARGETABLE", 500),),
                requires_living_opponent=False,
            ),
            action(
                "ELISE_SPIDER_E_RAPPEL_DESCEND",
                at_ms=self._RAPPEL_DESCENT_MS,
                sequence=base + 5,
                source=context.self_entity,
                channel=ActionChannel.MOVEMENT,
                outputs=(
                    StatusOutput(
                        context.self_entity,
                        "ELISE_SPIDER_QUEEN_AMPLIFIED",
                        5000,
                        self._RAPPEL_AMPLIFICATION,
                    ),
                ),
            ),
            action(
                "ELISE_SPIDER_W_SKITTERING_FRENZY",
                at_ms=self._SPIDER_W_AT_MS,
                sequence=base + 6,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(
                        context.self_entity,
                        "ELISE_SPIDER_W_ATTACK_SPEED",
                        3000,
                        self._SPIDER_W_ACTIVE_ATTACK_SPEED,
                    ),
                ),
                requires_living_opponent=False,
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"ELISE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "elise_q5_w5_e3_r3_human_to_spider_level13_locked_v1",
            tuple(
                sorted(
                    (
                        *fixed_events,
                        *self._spider_q_events(context),
                        *self._spider_attacks(context),
                    ),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "ELISE_LEVEL13_Q5_W5_E3_R3_POLICY_UNVERIFIED",
                "ELISE_FORM_TRANSITION_AND_CAST_TIMING_UNVERIFIED",
                "ELISE_Q_RUNTIME_CURRENT_HEALTH_CLIENT_VALIDATION_PENDING",
                "ELISE_HUMAN_W_TRAVEL_AND_TARGET_SELECTION_NOT_MODELED",
                "ELISE_SPIDERLING_AI_AND_ATTACKS_NOT_MODELED",
                "ELISE_SPIDERLING_TARGETABILITY_NOT_MODELED",
                "ELISE_RAPPEL_TARGET_GEOMETRY_NOT_MODELED",
                "ELISE_RAPPEL_ASCEND_DURATION_SYNTHETIC",
                "ELISE_RAPPEL_WINDOW_CAUSAL_CANCELLATION_NOT_MODELED",
                "ELISE_SPIDER_W_ATTACK_RESET_NOT_MODELED",
                "ELISE_SPIDER_ATTACK_CADENCE_TRANSITION_SIMPLIFIED",
                "ELISE_HUMAN_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Cocoon control and Rappel's fixed untargetable window.

        :param context: Role-bound Elise encounter context.
        :return: Stun, damage immunity, and control immunity reactions.
        """
        return ReactionPlan(
            "elise_cocoon_and_rappel_reaction_v1",
            damage_windows=(
                DamageModifierWindow(
                    "elise_rappel_untargetable_damage",
                    self._RAPPEL_START_MS,
                    min(self._RAPPEL_DESCENT_MS, context.duration_ms),
                    context.self_entity,
                    (DamageType.PHYSICAL, DamageType.MAGIC, DamageType.TRUE),
                    Decimal(0),
                ),
            ),
            cast_block_windows=(
                CastBlockWindow(
                    "elise_human_e_cocoon_stun",
                    100,
                    min(2100, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "ELISE_HUMAN_E_COCOON",
                    True,
                    ControlType.STUN,
                ),
            ),
            control_immunity_windows=(
                ControlImmunityWindow(
                    "elise_rappel_control_immunity",
                    self._RAPPEL_START_MS,
                    min(self._RAPPEL_DESCENT_MS, context.duration_ms),
                    context.self_entity,
                    (ControlType.ALL,),
                    "ELISE_SPIDER_E_RAPPEL_ASCEND",
                ),
            ),
            blockers=(
                "ELISE_COCOON_PROJECTILE_COLLISION_NOT_MODELED",
                "ELISE_RAPPEL_TARGET_GEOMETRY_NOT_MODELED",
                "ELISE_RAPPEL_ASCEND_DURATION_SYNTHETIC",
                "ELISE_RAPPEL_WINDOW_CAUSAL_CANCELLATION_NOT_MODELED",
            ),
        )
