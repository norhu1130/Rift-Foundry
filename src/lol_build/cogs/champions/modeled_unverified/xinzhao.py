"""Xin Zhao combat Cog backed by locked 16.17.1 champion sources."""

from __future__ import annotations

from dataclasses import replace
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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    CurrentHealthDamageOutput,
    StatModifierOutput,
)


class XinZhaoCog(ChampionCog):
    """Model Xin Zhao's Q5/E5/W1/R2 level-thirteen duel fixture.

    Three Talon Strike empowers the next three attacks in place, ending in a
    knock-up; Wind Becomes Lightning lands its slash and thrust in sequence;
    Audacious Charge dashes in with damage, self attack speed, and a slow; and
    Crescent Guard's flat and current-health damage both apply. Its knockback
    and post-cast missile immunity are excluded rather than guessed, since
    they depend on whether the opponent is already Challenged and on
    projectile-source distinctions this engine does not track, and one
    unresolved secondary coefficient on the flat damage term is left out
    rather than presented as a verified number.

    Determination makes every third attack — the empowered Three Talon Strikes
    included — deal bonus physical damage and heal Xin Zhao, using the locked
    ``XinZhaoP`` level breakpoints: ``TotalDamage`` (45% AD plus 15% AP at
    level 13) and ``TotalHealing`` (``HealHPRatio`` 5% of maximum health plus
    ``HealAPRatio`` 70% of ability power at level 13).
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/XinZhao.json",
        "data/raw/16.17.1/communitydragon/champions/5.json",
        "data/raw/16.17.1/communitydragon/champions/xinzhao.bin.json",
    )

    _Q_AT_MS = 200
    _Q_KNOCKUP_MS = 750
    _W_AT_MS = 1200
    _E_AT_MS = 2000
    _E_SLOW_MS = 500
    _E_AS_DURATION_MS = 5000
    _R_AT_MS = 2800

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule the three Three Talon Strike empowered attacks.

        :param context: Role-bound Xin Zhao and opponent snapshots.
        :return: Three empowered basic-attack events, the last with a knock-up.
        """
        base = self._sequence_base(context)
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        bonus = Decimal(75) + Decimal("0.4") * context.snapshot.bonus_attack_damage
        events: list[ActionEvent] = []
        for index in range(3):
            at_ms = self._Q_AT_MS + interval * index
            outputs: tuple[object, ...] = (
                damage(
                    context.opponent_entity,
                    context.snapshot.attack_damage + bonus,
                    DamageType.PHYSICAL,
                ),
            )
            if index == 2:
                outputs = (
                    *outputs,
                    crowd_control(
                        context.opponent_entity, "AIRBORNE", duration_ms=self._Q_KNOCKUP_MS
                    ),
                )
            events.append(
                action(
                    f"XINZHAO_Q_THREE_TALON_STRIKE_{index + 1}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=outputs,
                )
            )
        return tuple(events)

    @staticmethod
    def _step_value(
        level: int, level1_value: Decimal, steps: tuple[tuple[int, Decimal], ...]
    ) -> Decimal:
        """Evaluate a locked ``mAdditionalBonusAtThisLevel`` breakpoint formula.

        Each breakpoint adds its bonus once, from its level onward — unlike the
        per-level ``mBonusPerLevelAtAndAfter`` form handled by the base Cog.

        :param level: Champion level to evaluate.
        :param level1_value: Locked value at level one.
        :param steps: ``(level, one-time bonus)`` pairs.
        :return: Formula value at ``level``.
        """
        return level1_value + sum(
            (bonus for at_level, bonus in steps if level >= at_level), Decimal(0)
        )

    def _with_determination(
        self, context: ParticipantContext, events: tuple[ActionEvent, ...]
    ) -> tuple[ActionEvent, ...]:
        """Attach Determination's bonus damage and heal to every third attack.

        :param context: Role-bound Xin Zhao and opponent snapshots.
        :param events: Scheduled rotation events.
        :return: The same events, every third basic attack carrying the passive.
        """
        level = context.snapshot.level
        damage_ratio = self._step_value(
            level,
            Decimal("0.15"),
            ((6, Decimal("0.15")), (11, Decimal("0.15")), (16, Decimal("0.15"))),
        )
        damage_ap_ratio = self._step_value(
            level,
            Decimal("0.05"),
            ((6, Decimal("0.05")), (11, Decimal("0.05")), (16, Decimal("0.05"))),
        )
        heal_health_ratio = self._step_value(
            level, Decimal("0.02"), ((6, Decimal("0.015")), (11, Decimal("0.015")))
        )
        heal_ap_ratio = self._step_value(
            level, Decimal("0.4"), ((6, Decimal("0.1")), (11, Decimal("0.2")))
        )
        bonus = (
            damage_ratio * context.snapshot.attack_damage
            + damage_ap_ratio * context.snapshot.ability_power
        )
        heal = (
            heal_health_ratio * context.snapshot.max_hp
            + heal_ap_ratio * context.snapshot.ability_power
        )
        attacks = sorted(
            (event for event in events if event.channel is ActionChannel.BASIC_ATTACK),
            key=lambda event: (event.at_ms, event.sequence),
        )
        empowered = {event.id for index, event in enumerate(attacks) if index % 3 == 2}
        return tuple(
            replace(
                event,
                outputs=(
                    *event.outputs,
                    damage(context.opponent_entity, bonus, DamageType.PHYSICAL),
                    healing(context.self_entity, heal),
                ),
            )
            if event.id in empowered
            else event
            for event in events
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Xin Zhao's empowered-attack, slash-thrust, and sweep rotation.

        :param context: Role-bound Xin Zhao and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context) + 100
        slash = Decimal(30) + Decimal("0.3") * context.snapshot.attack_damage
        thrust = Decimal(50) + Decimal("0.9") * context.snapshot.attack_damage
        e_damage = Decimal(150) + Decimal("1.2") * context.snapshot.ability_power
        r_flat = Decimal(175) + context.snapshot.bonus_attack_damage
        fixed = [
            action(
                "XINZHAO_W_SLASH",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, slash, DamageType.PHYSICAL),),
            ),
            action(
                "XINZHAO_W_THRUST",
                at_ms=self._W_AT_MS + 200,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, thrust, DamageType.PHYSICAL),),
            ),
            action(
                "XINZHAO_E_AUDACIOUS_CHARGE",
                at_ms=self._E_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    StatModifierOutput(
                        context.opponent_entity,
                        "MOVE_SPEED_PERCENT",
                        Decimal("-0.30"),
                        self._E_SLOW_MS,
                    ),
                    StatModifierOutput(
                        context.self_entity,
                        "ATTACK_SPEED",
                        Decimal("0.70"),
                        self._E_AS_DURATION_MS,
                    ),
                ),
            ),
            action(
                "XINZHAO_R_CRESCENT_GUARD",
                at_ms=self._R_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_flat, DamageType.PHYSICAL),
                    CurrentHealthDamageOutput(
                        context.opponent_entity, Decimal("0.15"), DamageType.PHYSICAL
                    ),
                ),
            ),
        ]
        events = self._with_determination(
            context, (*self._q_events(context), *fixed, *self._basic_attack_events(context))
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"XINZHAO_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "xinzhao_q5_e5_w1_r2_empowered_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "XINZHAO_R_KNOCKBACK_AND_MISSILE_IMMUNITY_NOT_MODELED",
                "XINZHAO_R_SECONDARY_COEFFICIENT_UNRESOLVED",
                "XINZHAO_PASSIVE_CHALLENGE_MARK_NOT_MODELED",
                "XINZHAO_RESOURCE_COSTS_NOT_EVALUATED",
                "XINZHAO_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Xin Zhao and opponent combat snapshots.
        :return: Ordinary basic-attack damage events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 700
        events: list[ActionEvent] = []
        at_ms = self._Q_AT_MS + interval * 3
        index = 0
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"XINZHAO_BASIC_ATTACK_{index}",
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
            )
            index += 1
            at_ms += interval
        return tuple(events)

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the Q knock-up as this Cog's hostile control window.

        :param context: Role-bound Xin Zhao and opponent snapshots.
        :return: Deterministic control windows caused by Xin Zhao's rotation.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        knockup_at_ms = self._Q_AT_MS + interval * 2
        return ReactionPlan(
            "xinzhao_q_knockup_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "xinzhao_q_three_talon_strike_knockup",
                    knockup_at_ms,
                    min(knockup_at_ms + self._Q_KNOCKUP_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "XINZHAO_Q_THREE_TALON_STRIKE_3",
                    False,
                    ControlType.AIRBORNE,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Audacious Charge's locked cast range as its closing distance.

        :param context: Concrete participant context.
        :return: Dash distance in game units.
        """
        return Decimal(650)
