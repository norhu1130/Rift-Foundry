"""Poppy combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    CurrentHealthDamageOutput,
    StatModifierOutput,
)


class PoppyCog(ChampionCog):
    """Model Poppy's Q5/E5/W1/R2 level-thirteen duel fixture.

    Hammer Shock lands as two locked hits one second apart, Heroic Charge dashes
    and stuns on impact, and Steadfast Presence grants its self-armor and
    magic-resistance bonus as a percentage of Poppy's own current values. The
    ultimate's charge-and-knockback mechanic and W's grounding/interrupt proc
    are excluded rather than guessed: both depend on the opponent's own cast
    choices, which this fixed rotation does not simulate.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Poppy.json",
        "data/raw/16.17.1/communitydragon/champions/78.json",
        "data/raw/16.17.1/communitydragon/champions/poppy.bin.json",
    )

    _W_AT_MS = 0
    _W_RESIST_DURATION_MS = 2000
    _E_AT_MS = 700
    _E_STUN_MS = 2000
    _Q_AT_MS = 2000
    _Q_SECOND_HIT_DELAY_MS = 1000
    #: Rank-five slow from Hammer Shock's locked BaseMoveSpeedMod.
    _Q_SLOW_DURATION_MS = 500

    def _q_hit_outputs(self, context: ParticipantContext) -> tuple[object, ...]:
        """Build one Hammer Shock hit's damage and slow outputs.

        :param context: Role-bound Poppy and opponent snapshots.
        :return: Physical damage, current-health damage, and a slow.
        """
        flat = Decimal(130) + Decimal("0.75") * context.snapshot.bonus_attack_damage
        return (
            damage(context.opponent_entity, flat, DamageType.PHYSICAL),
            CurrentHealthDamageOutput(
                context.opponent_entity, Decimal("0.09"), DamageType.PHYSICAL
            ),
            StatModifierOutput(
                context.opponent_entity,
                "MOVE_SPEED_PERCENT",
                Decimal("-0.32"),
                self._Q_SLOW_DURATION_MS,
            ),
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Poppy's resist-open, tackle-stun, and double-hit rotation.

        :param context: Role-bound Poppy and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        e_damage = Decimal(120) + Decimal("0.6") * context.snapshot.bonus_attack_damage
        fixed = [
            action(
                "POPPY_W_STEADFAST_PRESENCE_RESIST",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatModifierOutput(
                        context.self_entity,
                        "ARMOR",
                        context.snapshot.armor * Decimal("0.16"),
                        self._W_RESIST_DURATION_MS,
                    ),
                    StatModifierOutput(
                        context.self_entity,
                        "MAGIC_RESISTANCE",
                        context.snapshot.magic_resistance * Decimal("0.16"),
                        self._W_RESIST_DURATION_MS,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "POPPY_E_HEROIC_CHARGE",
                at_ms=self._E_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.PHYSICAL),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=self._E_STUN_MS),
                ),
            ),
            action(
                "POPPY_Q_HAMMER_SHOCK_1",
                at_ms=self._Q_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=self._q_hit_outputs(context),
            ),
        ]
        second_hit_ms = self._Q_AT_MS + self._Q_SECOND_HIT_DELAY_MS
        if second_hit_ms <= context.duration_ms:
            fixed.append(
                action(
                    "POPPY_Q_HAMMER_SHOCK_2",
                    at_ms=second_hit_ms,
                    sequence=base + 3,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=self._q_hit_outputs(context),
                )
            )
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"POPPY_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "poppy_q5_e5_w1_r2_tackle_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "POPPY_R_KEEPERS_VERDICT_CHARGE_AND_KNOCKBACK_NOT_MODELED",
                "POPPY_W_GROUNDING_AND_INTERRUPT_DAMAGE_NOT_MODELED",
                "POPPY_E_WALL_COLLISION_BONUS_DAMAGE_NOT_MODELED",
                "POPPY_PASSIVE_BUCKLER_THROW_AND_PICKUP_NOT_MODELED",
                "POPPY_RESOURCE_COSTS_NOT_EVALUATED",
                "POPPY_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Poppy and opponent combat snapshots.
        :return: Ordinary basic-attack damage events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 500
        events: list[ActionEvent] = []
        at_ms = 200
        index = 0
        cast_windows = ((self._E_AT_MS, self._E_AT_MS + 100),)
        while at_ms <= context.duration_ms:
            if not any(start <= at_ms < end for start, end in cast_windows):
                events.append(
                    action(
                        f"POPPY_BASIC_ATTACK_{index}",
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
        """Expose the Heroic Charge stun as this Cog's hostile control window.

        :param context: Role-bound Poppy and opponent snapshots.
        :return: Deterministic control windows caused by Poppy's rotation.
        """
        return ReactionPlan(
            "poppy_e_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "poppy_e_heroic_charge_stun",
                    self._E_AT_MS,
                    min(self._E_AT_MS + self._E_STUN_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "POPPY_E_HEROIC_CHARGE",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Heroic Charge's locked cast range as its closing distance.

        :param context: Concrete participant context.
        :return: Dash distance in game units.
        """
        return Decimal(475)
