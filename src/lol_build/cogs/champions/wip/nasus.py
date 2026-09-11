"""Nasus combat Cog for the locked level-13 duel benchmark."""

from __future__ import annotations

from decimal import Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    AttackCadenceModifierWindow,
    ChampionCog,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import (
    DamageType,
    ResistanceModifiers,
    apply_resistance_pipeline,
    resistance_multiplier,
)
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    DamageModifierWindow,
    ResistanceReductionOutput,
    StatModifierOutput,
    StatusOutput,
)


class NasusCog(ChampionCog):
    """Model Nasus's Q5/W1/E5/R2 level-13 duel sequence.

    Siphoning Strike uses an explicit 300-stack fixture because pre-combat
    farming is outside the eight-second scenario. Fury of the Sands halves
    Q's locked cooldown, emits its maximum-health aura, and grants the fixed
    rank-two resistances through reaction windows. Its maximum-health grant
    remains excluded because the timeline cannot change maximum and current
    health atomically without pretending that the grant is a shield.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Nasus.json",
        "data/raw/16.17.1/communitydragon/champions/75.json",
        "data/raw/16.17.1/communitydragon/champions/nasus.bin.json",
    )
    q_stack_fixture = Decimal(300)

    @staticmethod
    def _resistance_multiplier(
        resistance: Decimal,
        bonus: Decimal,
        *,
        percent_penetration: Decimal,
        flat_penetration: Decimal,
    ) -> Decimal:
        """Translate a resistance grant into an incoming-damage multiplier.

        The level-13 snapshot keeps both base resistances positive. Expressing
        the rank-two R grant as a ratio of post-mitigation damage lets the
        existing reaction-window contract preserve the nonlinear resistance
        formula and the opponent's permanent penetration without mutating a
        combatant snapshot at runtime.

        :param resistance: Permanent resistance before Fury of the Sands.
        :param bonus: Temporary additive resistance granted by the ultimate.
        :param percent_penetration: Opponent's permanent percentage penetration.
        :param flat_penetration: Opponent's permanent flat penetration.
        :return: Incoming post-mitigation multiplier while the grant is active.
        """
        if resistance < 0:
            raise ValueError("Nasus R resistance window requires non-negative resistance")
        modifiers = ResistanceModifiers(
            percent_penetration=percent_penetration,
            flat_penetration=flat_penetration,
        )
        before = apply_resistance_pipeline(resistance, modifiers).effective_resistance
        after = apply_resistance_pipeline(
            resistance + bonus,
            modifiers,
        ).effective_resistance
        return resistance_multiplier(after) / resistance_multiplier(before)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Keep self movement unchanged because Wither slows the opponent.

        :param context: Role-bound Nasus combat context.
        :return: Neutral self movement-speed multiplier.
        """
        return Decimal(1)

    def engagement_target_slow_fraction(self, context: ParticipantContext) -> Decimal:
        """Slow a retreating opponent with Wither's opening ``SlowBase``.

        Wither's slow grows each tick (``SlowPerTick``); only the locked 35%
        opening value is credited, and the growth stays a blocker.

        :param context: Role-bound Nasus combat context.
        :return: Wither's opening slow fraction.
        """
        return Decimal("0.35")

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the fixed Nasus policy.

        Attack damage, attack speed, ability power, health, defenses, movement,
        penetration, and tenacity reach a modeled snapshot or spell channel.
        Ability haste cannot alter the fixed schedule, mana is not consumed,
        and healing or critical outputs lack causal attribution.

        :param item: Normalized candidate from the locked item catalog.
        :return: Nasus-scoped blocker, or ``None`` when the channel is represented.
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
            return f"NASUS_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _ordinary_attack_events(
        self,
        context: ParticipantContext,
    ) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks independently of Q attack resets.

        Q casts are additional basic-attack-channel events inserted immediately
        after the opening ordinary attack and on the R-reduced cooldown. This
        preserves blind interaction and the extra attacks created by resets.

        :param context: Role-bound snapshots used for attack cadence and damage.
        :return: Ordinary basic attacks in deterministic timestamp order.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 400
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"NASUS_BASIC_ATTACK_{len(events) + 1}",
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
                    ),
                )
            )
            at_ms += interval_ms
        return tuple(events)

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Q-enhanced attacks with the rank-two R cooldown reduction.

        :param context: Role-bound snapshots used for Q damage and duration.
        :return: Q reset attacks carrying total AD, rank damage, and the fixture.
        """
        q_damage = context.snapshot.attack_damage + Decimal(120) + self.q_stack_fixture
        base = self._sequence_base(context) + 200
        events: list[ActionEvent] = []
        at_ms = 450
        q_cooldown_ms = 1750
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"NASUS_Q_SIPHONING_STRIKE_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            q_damage,
                            DamageType.PHYSICAL,
                        ),
                    ),
                )
            )
            at_ms += q_cooldown_ms
        return tuple(events)

    def _spirit_fire_events(
        self,
        context: ParticipantContext,
    ) -> tuple[ActionEvent, ...]:
        """Create E's initial hit, armor reduction, and five damage ticks.

        :param context: Role-bound snapshots supplying AP and the target entity.
        :return: Initial and periodic Spirit Fire events.
        """
        base = self._sequence_base(context) + 300
        ap = context.snapshot.ability_power
        initial = action(
            "NASUS_E_SPIRIT_FIRE_INITIAL",
            at_ms=100,
            sequence=base,
            source=context.self_entity,
            channel=ActionChannel.ABILITY,
            outputs=(
                damage(
                    context.opponent_entity,
                    Decimal(170) + Decimal("0.60") * ap,
                    DamageType.MAGIC,
                ),
                ResistanceReductionOutput(
                    context.opponent_entity,
                    "ARMOR",
                    Decimal("0.50"),
                    1,
                    5000,
                    f"NASUS_E_ARMOR_REDUCTION_{context.self_entity.value}",
                ),
            ),
        )
        tick_damage = Decimal(34) + Decimal("0.12") * ap
        ticks = tuple(
            action(
                f"NASUS_E_SPIRIT_FIRE_TICK_{index}",
                at_ms=100 + index * 1000,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(
                    damage(
                        context.opponent_entity,
                        tick_damage,
                        DamageType.MAGIC,
                    ),
                ),
            )
            for index in range(1, 6)
            if 100 + index * 1000 <= context.duration_ms
        )
        return (initial, *ticks)

    def _fury_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Create R activation and half-second maximum-health aura ticks.

        :param context: Role-bound snapshots supplying AP and target maximum HP.
        :return: Ultimate status followed by deterministic aura ticks.
        """
        base = self._sequence_base(context) + 400
        activation = action(
            "NASUS_R_FURY_OF_THE_SANDS",
            at_ms=0,
            sequence=base,
            source=context.self_entity,
            channel=ActionChannel.ABILITY,
            outputs=(StatusOutput(context.self_entity, "NASUS_R_ACTIVE", 15000),),
            requires_living_opponent=False,
        )
        damage_per_second = context.opponent_snapshot.max_hp * (
            Decimal("0.04") + Decimal("0.0001") * context.snapshot.ability_power
        )
        ticks = tuple(
            action(
                f"NASUS_R_SANDSTORM_TICK_{index}",
                at_ms=index * 500,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(
                    damage(
                        context.opponent_entity,
                        damage_per_second / 2,
                        DamageType.MAGIC,
                    ),
                ),
            )
            for index in range(1, context.duration_ms // 500 + 1)
        )
        return (activation, *ticks)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked Q5/W1/E5/R2 level-13 duel action plan.

        :param context: Role-bound snapshots for Nasus and the opponent.
        :return: Deterministic attacks, spells, aura damage, and audit blockers.
        """
        base = self._sequence_base(context)
        wither = action(
            "NASUS_W_WITHER",
            at_ms=150,
            sequence=base + 1,
            source=context.self_entity,
            channel=ActionChannel.ABILITY,
            outputs=(
                crowd_control(
                    context.opponent_entity,
                    "SLOW",
                    duration_ms=5000,
                    magnitude=Decimal("0.35"),
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"NASUS_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        # Soul Eater: 10% life steal, +5% at levels 7 and 13 (locked tooltip).
        life_steal = Decimal("0.10") + sum(
            (Decimal("0.05") for at_level in (7, 13) if context.snapshot.level >= at_level),
            Decimal(0),
        )
        soul_eater = action(
            "NASUS_PASSIVE_SOUL_EATER",
            at_ms=0,
            sequence=base + 90,
            source=context.self_entity,
            channel=ActionChannel.PASSIVE,
            outputs=(StatModifierOutput(context.self_entity, "LIFESTEAL", life_steal, None),),
            requires_living_opponent=False,
        )
        events = (
            soul_eater,
            *self._fury_events(context),
            *self._spirit_fire_events(context),
            wither,
            *self._ordinary_attack_events(context),
            *self._q_events(context),
        )
        return ActionPlan(
            "nasus_q5_w1_e5_r2_level13_synthetic_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            (
                *level_blockers,
                "NASUS_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "NASUS_ROTATION_TIMING_UNVERIFIED",
                "NASUS_Q_STACK_FIXTURE_300_ASSUMED",
                "NASUS_Q_ATTACK_RESET_TIMING_UNVERIFIED",
                "NASUS_Q_STACK_GROWTH_OUTSIDE_SCENARIO",
                "NASUS_W_MOVEMENT_SLOW_PROGRESSION_NOT_CONSUMED_BY_ENGAGEMENT",
                "NASUS_W_TENACITY_NOT_APPLIED_TO_ATTACK_CADENCE",
                "NASUS_E_FULL_ZONE_DURATION_ASSUMED",
                "NASUS_R_MAXIMUM_HEALTH_450_NOT_APPLIED",
                "NASUS_R_ATTACK_RANGE_50_NOT_APPLIED",
                "NASUS_RESOURCE_COSTS_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Wither's attack slow and R's temporary resistances.

        Wither's five one-second windows follow the locked 35-to-47-percent
        rank-one slow progression. Its attack-speed reduction is seventy-five
        percent of each movement-slow value. R's fixed rank-two resistance grant
        is converted into exact positive-resistance damage multipliers.

        :param context: Role-bound snapshots for Nasus and the opponent.
        :return: Causally linked cadence and incoming-damage windows.
        """
        cadence_windows = tuple(
            AttackCadenceModifierWindow(
                f"nasus_w_attack_speed_reduction_{second + 1}",
                150 + second * 1000,
                min(1150 + second * 1000, context.duration_ms),
                Decimal(1) - Decimal("0.75") * (Decimal("0.35") + Decimal("0.03") * second),
                "NASUS_W_WITHER",
            )
            for second in range(5)
            if 150 + second * 1000 < context.duration_ms
        )
        damage_windows = ()
        if context.duration_ms > 0:
            damage_windows = (
                DamageModifierWindow(
                    "nasus_r_bonus_armor",
                    0,
                    context.duration_ms,
                    context.self_entity,
                    (DamageType.PHYSICAL,),
                    self._resistance_multiplier(
                        context.snapshot.armor,
                        Decimal(55),
                        percent_penetration=(context.opponent_snapshot.percent_armor_penetration),
                        flat_penetration=context.opponent_snapshot.flat_armor_penetration,
                    ),
                ),
                DamageModifierWindow(
                    "nasus_r_bonus_magic_resistance",
                    0,
                    context.duration_ms,
                    context.self_entity,
                    (DamageType.MAGIC,),
                    self._resistance_multiplier(
                        context.snapshot.magic_resistance,
                        Decimal(55),
                        percent_penetration=(context.opponent_snapshot.percent_magic_penetration),
                        flat_penetration=context.opponent_snapshot.flat_magic_penetration,
                    ),
                ),
            )
        return ReactionPlan(
            "nasus_w1_r2_reaction_v1",
            damage_windows=damage_windows,
            attack_cadence_windows=cadence_windows,
            blockers=(
                "NASUS_W_ATTACK_SPEED_SLOW_TICK_PHASE_UNVERIFIED",
                "NASUS_W_TENACITY_NOT_APPLIED_TO_ATTACK_CADENCE",
                "NASUS_R_BONUS_RESISTANCE_WINDOW_RUNTIME_UNVERIFIED",
                "NASUS_R_RESISTANCE_DYNAMIC_REDUCTIONS_NOT_MODELED",
            ),
        )
