"""Rammus combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent, StatModifierOutput


class RammusCog(ChampionCog):
    """Model Rammus's Q5/E5/W1/R2 level-thirteen duel fixture.

    Defensive Ball Curl opens as a resist buff, Powerball rolls into a
    collision hit, Puncturing Taunt locks the opponent's actions the way this
    codebase already models taunt for Galio, and Soaring Slam lands as a flat
    area hit. Powerball's knockback and Defensive Ball Curl's on-attack damage
    reflection are excluded rather than guessed: repositioning is outside this
    engine's scope, and the reflection triggers off the opponent's own attack
    events rather than Rammus's own schedule.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Rammus.json",
        "data/raw/16.17.1/communitydragon/champions/33.json",
        "data/raw/16.17.1/communitydragon/champions/rammus.bin.json",
    )

    _W_AT_MS = 0
    _W_DURATION_MS = 7000
    _Q_AT_MS = 400
    _Q_SLOW_MS = 1000
    _E_AT_MS = 1200
    _E_TAUNT_MS = 1800
    _R_AT_MS = 2200

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Rammus's defense-open, roll-collide, taunt, and slam rotation.

        :param context: Role-bound Rammus and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        q_damage = Decimal(240) + context.snapshot.ability_power
        r_damage = Decimal(150) + Decimal("0.6") * context.snapshot.ability_power
        fixed = [
            action(
                "RAMMUS_W_DEFENSIVE_BALL_CURL",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatModifierOutput(
                        context.self_entity,
                        "ARMOR",
                        context.snapshot.armor * Decimal("0.30") + Decimal(27),
                        self._W_DURATION_MS,
                    ),
                    StatModifierOutput(
                        context.self_entity,
                        "MAGIC_RESISTANCE",
                        context.snapshot.magic_resistance * Decimal("0.30") + Decimal(20),
                        self._W_DURATION_MS,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "RAMMUS_Q_POWERBALL",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q_damage, DamageType.MAGIC),
                    StatModifierOutput(
                        context.opponent_entity,
                        "MOVE_SPEED_PERCENT",
                        Decimal("-0.80"),
                        self._Q_SLOW_MS,
                    ),
                ),
            ),
            action(
                "RAMMUS_E_PUNCTURING_TAUNT",
                at_ms=self._E_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    crowd_control(context.opponent_entity, "TAUNT", duration_ms=self._E_TAUNT_MS),
                ),
            ),
            action(
                "RAMMUS_R_SOARING_SLAM",
                at_ms=self._R_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.MAGIC),
                    StatModifierOutput(
                        context.opponent_entity,
                        "MOVE_SPEED_PERCENT",
                        Decimal("-0.30"),
                        1500,
                    ),
                ),
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"RAMMUS_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "rammus_q5_e5_w1_r2_curl_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "RAMMUS_Q_KNOCKBACK_NOT_MODELED",
                "RAMMUS_W_ATTACK_REFLECT_DAMAGE_NOT_MODELED",
                "RAMMUS_R_LANDING_KNOCKUP_AND_TREMOR_PULSES_NOT_MODELED",
                "RAMMUS_PASSIVE_SPIKED_SHELL_BONUS_DAMAGE_NOT_MODELED",
                "RAMMUS_RESOURCE_COSTS_NOT_EVALUATED",
                "RAMMUS_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Rammus and opponent combat snapshots.
        :return: Ordinary basic-attack damage events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 500
        events: list[ActionEvent] = []
        at_ms = 200
        index = 0
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"RAMMUS_BASIC_ATTACK_{index}",
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
        """Expose the Puncturing Taunt lock as this Cog's hostile control window.

        :param context: Role-bound Rammus and opponent snapshots.
        :return: Deterministic control windows caused by Rammus's rotation.
        """
        return ReactionPlan(
            "rammus_e_taunt_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "rammus_e_puncturing_taunt",
                    self._E_AT_MS,
                    min(self._E_AT_MS + self._E_TAUNT_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "RAMMUS_E_PUNCTURING_TAUNT",
                    True,
                    ControlType.TAUNT,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Powerball's roll as a closing-distance benchmark.

        :param context: Concrete participant context.
        :return: Dash distance in game units.
        """
        return Decimal(300)
