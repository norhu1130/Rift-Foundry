"""Renekton combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, MaxHealthModifierOutput


class RenektonCog(ChampionCog):
    """Model Renekton's Q5/W5/E1/R2 level-thirteen duel fixture.

    Cleave opens with damage and self-heal, Pre-Execute lands its two-hit stun
    on the swing right after cast, Slice and Dice dashes in for a single hit,
    and Dominus grants bonus health and a magic-damage aura in half-second
    ticks. Fury and its empowered ability tiers are excluded rather than
    guessed: correctly tracking a resource that both abilities and basic
    attacks feed, at a rate the locked data does not fully resolve for this
    fixture's actual hit sequence, risks a wrong number presented as a real one.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Renekton.json",
        "data/raw/16.17.1/communitydragon/champions/58.json",
        "data/raw/16.17.1/communitydragon/champions/renekton.bin.json",
    )

    _Q_AT_MS = 0
    _W_AT_MS = 700
    _W_STUN_MS = 750
    _E_AT_MS = 1600
    _R_AT_MS = 2200
    _R_DURATION_MS = 15000
    _R_TICK_MS = 500

    def _r_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule the Dominus health buff and its half-second aura ticks.

        :param context: Role-bound Renekton and opponent snapshots.
        :return: Buff grant followed by evenly spaced aura ticks.
        """
        base = self._sequence_base(context) + 300
        tick_damage = (
            Decimal(150)
            + Decimal("0.1") * context.snapshot.bonus_attack_damage
            + Decimal("0.1") * context.snapshot.ability_power
        ) * Decimal("0.5")
        events: list[ActionEvent] = [
            action(
                "RENEKTON_R_DOMINUS_HEALTH",
                at_ms=self._R_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    MaxHealthModifierOutput(context.self_entity, Decimal(300), self._R_DURATION_MS),
                ),
                requires_living_opponent=False,
            )
        ]
        end_ms = min(context.duration_ms, self._R_AT_MS + self._R_DURATION_MS)
        at_ms = self._R_AT_MS + self._R_TICK_MS
        index = 0
        while at_ms <= end_ms:
            events.append(
                action(
                    f"RENEKTON_R_DOMINUS_AURA_TICK_{index}",
                    at_ms=at_ms,
                    sequence=base + 1 + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, tick_damage, DamageType.MAGIC),),
                )
            )
            index += 1
            at_ms += self._R_TICK_MS
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Renekton's cleave-open, stun-swing, dash, and aura rotation.

        :param context: Role-bound Renekton and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        q_damage = Decimal(180) + context.snapshot.bonus_attack_damage
        q_heal = Decimal(44) + Decimal("0.17") * context.snapshot.bonus_attack_damage
        w_hit = Decimal(65) + Decimal("0.75") * context.snapshot.attack_damage
        e_damage = Decimal(40) + Decimal("0.9") * context.snapshot.bonus_attack_damage
        fixed = [
            action(
                "RENEKTON_Q_CLEAVE",
                at_ms=self._Q_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q_damage, DamageType.PHYSICAL),
                    healing(context.self_entity, q_heal),
                ),
            ),
            action(
                "RENEKTON_W_PRE_EXECUTE_HIT_1",
                at_ms=self._W_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(context.opponent_entity, w_hit, DamageType.PHYSICAL),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=self._W_STUN_MS),
                ),
            ),
            action(
                "RENEKTON_W_PRE_EXECUTE_HIT_2",
                at_ms=self._W_AT_MS + 50,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(damage(context.opponent_entity, w_hit, DamageType.PHYSICAL),),
            ),
            action(
                "RENEKTON_E_SLICE_AND_DICE",
                at_ms=self._E_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, e_damage, DamageType.PHYSICAL),),
            ),
        ]
        events = (*fixed, *self._r_events(context), *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"RENEKTON_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "renekton_q5_w5_e1_r2_cleave_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "RENEKTON_FURY_RESOURCE_AND_EMPOWERED_TIERS_NOT_MODELED",
                "RENEKTON_W_NEXT_ATTACK_TIMING_ASSUMED",
                "RENEKTON_E_RECAST_NOT_MODELED",
                "RENEKTON_PASSIVE_LOW_HEALTH_FURY_RATE_NOT_MODELED",
                "RENEKTON_RESOURCE_COSTS_NOT_EVALUATED",
                "RENEKTON_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Renekton and opponent combat snapshots.
        :return: Ordinary basic-attack damage events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 700
        events: list[ActionEvent] = []
        at_ms = 200
        index = 0
        skip_windows = ((self._W_AT_MS - 100, self._W_AT_MS + 200),)
        while at_ms <= context.duration_ms:
            if not any(start <= at_ms < end for start, end in skip_windows):
                events.append(
                    action(
                        f"RENEKTON_BASIC_ATTACK_{index}",
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
        """Expose the Pre-Execute stun as this Cog's hostile control window.

        :param context: Role-bound Renekton and opponent snapshots.
        :return: Deterministic control windows caused by Renekton's rotation.
        """
        return ReactionPlan(
            "renekton_w_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "renekton_w_pre_execute_stun",
                    self._W_AT_MS,
                    min(self._W_AT_MS + self._W_STUN_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "RENEKTON_W_PRE_EXECUTE_HIT_1",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Slice and Dice's locked cast range as its closing distance.

        :param context: Concrete participant context.
        :return: Dash distance in game units.
        """
        return Decimal(450)
