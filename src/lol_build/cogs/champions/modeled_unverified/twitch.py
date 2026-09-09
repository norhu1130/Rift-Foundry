"""Twitch combat Cog backed by locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    ChampionCog,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatModifierOutput


class TwitchCog(ChampionCog):
    """Model Twitch's Q1/W5/E5/R2 level-thirteen duel fixture.

    Ambush grants its attack-speed buff, Venom Cask lands its slow, Spray and
    Pray grants bonus attack damage, and Expunge detonates Deadly Venom
    stacks. Stacks are not individually tracked from basic-attack or Venom
    Cask application; Expunge instead assumes four of its six-stack maximum,
    a fixed middle-of-the-road count disclosed as an assumption rather than
    presented as tracked. R's own bonus attack damage does not feed back into
    the flat damage this fixture already scheduled for earlier attacks.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Twitch.json",
        "data/raw/16.17.1/communitydragon/champions/29.json",
        "data/raw/16.17.1/communitydragon/champions/twitch.bin.json",
    )

    _ASSUMED_VENOM_STACKS = 4

    _Q_AT_MS = 0
    _Q_AS_DURATION_MS = 6000
    _W_AT_MS = 600
    _W_SLOW_MS = 3000
    _R_AT_MS = 1400
    _R_DURATION_MS = 6000
    _E_AT_MS = 2200

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Twitch's stealth-open, slow, buff, and poison-burst rotation.

        :param context: Role-bound Twitch and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        e_physical = Decimal(50) + self._ASSUMED_VENOM_STACKS * (
            Decimal(30) + Decimal("0.35") * context.snapshot.bonus_attack_damage
        )
        e_magic = self._ASSUMED_VENOM_STACKS * Decimal("0.35") * context.snapshot.ability_power
        fixed = [
            action(
                "TWITCH_Q_AMBUSH",
                at_ms=self._Q_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatModifierOutput(
                        context.self_entity,
                        "ATTACK_SPEED",
                        Decimal("0.35"),
                        self._Q_AS_DURATION_MS,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "TWITCH_W_VENOM_CASK",
                at_ms=self._W_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatModifierOutput(
                        context.opponent_entity,
                        "MOVE_SPEED_PERCENT",
                        Decimal("-0.50"),
                        self._W_SLOW_MS,
                    ),
                ),
            ),
            action(
                "TWITCH_R_SPRAY_AND_PRAY",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatModifierOutput(
                        context.self_entity,
                        "BONUS_ATTACK_DAMAGE",
                        Decimal(30),
                        self._R_DURATION_MS,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "TWITCH_E_EXPUNGE",
                at_ms=self._E_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_physical, DamageType.PHYSICAL),
                    damage(context.opponent_entity, e_magic, DamageType.MAGIC),
                ),
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"TWITCH_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "twitch_q1_w5_e5_r2_stealth_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "TWITCH_E_STACK_COUNT_ASSUMED_NOT_TRACKED",
                "TWITCH_PASSIVE_VENOM_STACK_APPLICATION_NOT_MODELED",
                "TWITCH_R_FALLOFF_AND_BONUS_RANGE_NOT_MODELED",
                "TWITCH_Q_STEALTH_DETECTION_NOT_MODELED",
                "TWITCH_RESOURCE_COSTS_NOT_EVALUATED",
                "TWITCH_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Twitch and opponent combat snapshots.
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
                    f"TWITCH_BASIC_ATTACK_{index}",
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
        """Report that Twitch's rotation applies no hostile hard control.

        :param context: Role-bound Twitch and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "twitch_no_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
