"""Volibear combat Cog for the locked level-13 duel benchmark."""

from __future__ import annotations

from decimal import Decimal

from lol_build.cogs.base import (
    ActionPlan,
    CastBlockWindow,
    ChampionCog,
    CogCapability,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import (
    action,
    crowd_control,
    damage,
    missing_health_healing,
    shielding,
)
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class VolibearCog(ChampionCog):
    """Model Volibear's Q5/W5/E1/R2 level-13 duel sequence.

    The schedule treats W's five-second cooldown as independent of attack speed.
    Attack speed affects only regular attacks and the passive's stacking attack-
    speed bonus. The model assumes R's sweet spot, both E effects, and two W casts
    hit the same champion; every such assumption is exposed as a blocker.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = frozenset(
        {
            CogCapability.BASIC_ATTACK,
            CogCapability.ABILITY_ROTATION,
            CogCapability.REACTION_MODEL,
            CogCapability.ENGAGEMENT,
            CogCapability.ITEM_POLICY,
            CogCapability.RECOMMENDATION,
        }
    )
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Volibear.json",
        "data/raw/16.17.1/communitydragon/champions/106.json",
        "data/raw/16.17.1/communitydragon/champions/volibear.bin.json",
    )

    @staticmethod
    def _passive_damage(level: int, ability_power: Decimal) -> Decimal:
        """Calculate max-stack chain-lightning damage from locked breakpoints.

        :param level: Champion level used by the breakpoint curve.
        :param ability_power: Current ability power contributing to the passive.
        :return: Raw magic damage dealt to the primary attack target.
        """
        base = Decimal(11)
        for gained_level in range(2, level + 1):
            if gained_level >= 14:
                base += Decimal(4)
            elif gained_level >= 7:
                base += Decimal(3)
            elif gained_level >= 4:
                base += Decimal(2)
            else:
                base += Decimal(1)
        return base + Decimal("0.45") * ability_power

    @staticmethod
    def _passive_attack_speed_per_stack(ability_power: Decimal) -> Decimal:
        """Calculate the additive attack-speed fraction granted by one stack.

        :param ability_power: Current ability power used by the locked scaling.
        :return: Additive attack-speed fraction granted by one passive stack.
        """
        return Decimal("0.05") + Decimal("0.0003") * ability_power

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Return rank-five Q movement speed toward an enemy champion.

        :param context: Role-bound combat snapshots for the encounter.
        :return: Pursuit movement multiplier during Thundering Smash.
        """
        return Decimal("1.52")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Stormbringer's locked cast range as approach displacement.

        :param context: Role-bound combat snapshots for the encounter.
        :return: Maximum modeled leap distance in game units.
        """
        return Decimal(700)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats whose value this fixed rotation cannot represent.

        Ability haste cannot reschedule the fixed spell policy and mana is not
        consumed. Life steal, omnivamp, heal and shield power, and plain-attack
        expected critical-strike damage are resolved by the shared timeline.

        :param item: Normalized item candidate from the locked catalog.
        :return: Champion-scoped blocker code, or ``None`` when representable.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "MANA",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"VOLIBEAR_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _regular_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks after the fixed opener reaches five passive stacks.

        R, Q, W1, and E supply four assumed prior stacks. The first regular
        attack supplies the fifth, after which every scheduled attack carries
        the passive's primary-target magic damage. Passive attack speed is added
        through the locked attack-speed ratio and never changes W cooldown.

        :param context: Role-bound combat snapshots used for cadence and damage.
        :return: Regular max-stack attacks in deterministic timestamp order.
        """
        ratio = Decimal("0.70")
        stack_bonus = self._passive_attack_speed_per_stack(context.snapshot.ability_power)
        max_stack_attack_speed = context.snapshot.attack_speed + ratio * stack_bonus * 5
        interval_ms = self._attack_interval_ms(max_stack_attack_speed)
        passive_damage = self._passive_damage(
            context.snapshot.level,
            context.snapshot.ability_power,
        )
        sequence = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 1400
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"VOLIBEAR_PASSIVE_ATTACK_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=sequence,
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
            sequence += 1
            at_ms += interval_ms
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked Q5/W5/E1/R2 action and sustain sequence.

        W2 restores its rank-five ``BaseHeal`` plus ``HealPercent`` (20%) of the
        health missing when the bite resolves.

        :param context: Role-bound combat snapshots for Volibear and the opponent.
        :return: Deterministic damage, healing, and control events with blockers.
        """
        base = self._sequence_base(context)
        total_ad = context.snapshot.attack_damage
        bonus_ad = context.snapshot.bonus_attack_damage
        bonus_hp = context.snapshot.bonus_health
        ability_power = context.snapshot.ability_power

        q_damage = Decimal(50) + total_ad + Decimal("1.60") * bonus_ad
        w_damage = Decimal(105) + Decimal("1.10") * total_ad + Decimal("0.06") * bonus_hp
        w2_damage = w_damage * (Decimal("1.50") + Decimal("0.0025") * bonus_ad)
        e_damage = (
            Decimal(80)
            + Decimal("0.70") * ability_power
            + Decimal("0.11") * context.opponent_snapshot.max_hp
        )
        r_damage = Decimal(500) + Decimal("1.25") * ability_power + Decimal("2.50") * bonus_ad
        fixed_events = (
            action(
                "VOLIBEAR_R_STORMBRINGER",
                at_ms=300,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.PHYSICAL),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=1000,
                        magnitude=Decimal("0.50"),
                    ),
                ),
            ),
            action(
                "VOLIBEAR_Q_THUNDERING_SMASH",
                at_ms=650,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(context.opponent_entity, q_damage, DamageType.PHYSICAL),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=1000),
                ),
            ),
            action(
                "VOLIBEAR_W1_FRENZIED_MAUL",
                at_ms=900,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, w_damage, DamageType.PHYSICAL),),
            ),
            action(
                "VOLIBEAR_E_SKY_SPLITTER",
                at_ms=1200,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=2000,
                        magnitude=Decimal("0.40"),
                    ),
                ),
            ),
            action(
                "VOLIBEAR_W2_FRENZIED_MAUL",
                at_ms=5900,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, w2_damage, DamageType.PHYSICAL),
                    missing_health_healing(
                        context.self_entity, Decimal("0.20"), base_amount=Decimal(80)
                    ),
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"VOLIBEAR_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "volibear_q5_w5_e1_r2_level13_synthetic_v1",
            tuple(
                sorted(
                    (*fixed_events, *self._regular_attack_events(context)),
                    key=lambda event: (event.at_ms, event.sequence),
                )
            ),
            (
                *level_blockers,
                "VOLIBEAR_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "VOLIBEAR_ROTATION_TIMING_UNVERIFIED",
                "VOLIBEAR_R_SWEET_SPOT_HIT_ASSUMED",
                "VOLIBEAR_R_BONUS_HEALTH_NOT_EVALUATED",
                "VOLIBEAR_E_HIT_AND_SELF_SHIELD_ASSUMED",
                "VOLIBEAR_W_MARK_TARGET_CONTINUITY_ASSUMED",
                "VOLIBEAR_W_ON_HIT_ITEM_EFFECTS_NOT_EVALUATED",
                "VOLIBEAR_PASSIVE_STACK_TIMING_UNVERIFIED",
                "VOLIBEAR_RESOURCE_COSTS_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Q stun, E shield, and movement slows as causal reactions.

        :param context: Role-bound snapshots for the current participant.
        :return: Self-protection and opponent-control events linked to abilities.
        """
        base = self._sequence_base(context)
        shield_amount = (
            Decimal("0.14") * context.snapshot.max_hp
            + Decimal("0.75") * context.snapshot.ability_power
        )
        return ReactionPlan(
            "volibear_q_e_r_reaction_v1",
            events=(
                action(
                    "VOLIBEAR_E_SELF_SHIELD",
                    at_ms=1200,
                    sequence=base + 500,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        shielding(
                            context.self_entity,
                            shield_amount,
                            duration_ms=3000,
                        ),
                    ),
                    requires_living_opponent=False,
                ),
            ),
            cast_block_windows=(
                CastBlockWindow(
                    "volibear_q_stun",
                    650,
                    min(1650, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY),
                    "VOLIBEAR_Q_THUNDERING_SMASH",
                    True,
                ),
                CastBlockWindow(
                    "volibear_r_slow",
                    300,
                    min(1300, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "VOLIBEAR_R_STORMBRINGER",
                    True,
                ),
                CastBlockWindow(
                    "volibear_e_slow",
                    1200,
                    min(3200, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "VOLIBEAR_E_SKY_SPLITTER",
                    True,
                ),
            ),
            blockers=(
                "VOLIBEAR_Q_STUN_HIT_TIMING_UNVERIFIED",
                "VOLIBEAR_E_SHIELD_HIT_TIMING_UNVERIFIED",
                "VOLIBEAR_E_DEPENDENT_SHIELD_CANCELLATION_NOT_EVALUATED",
                "VOLIBEAR_E_R_SLOW_MOVEMENT_INTERACTION_UNVERIFIED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Decline to fabricate W2 lane healing without target continuity.

        :param context: Role-bound combat snapshots for the lane participant.
        :param duration_ms: Lane observation window in milliseconds.
        :param no_damage_delay_ms: Delay before out-of-combat recovery begins.
        :return: Zero extra recovery and a precise unresolved-model blocker.
        """
        return Decimal(0), ("VOLIBEAR_LANE_W_MARK_TARGET_CONTINUITY_NOT_MODELED",)
