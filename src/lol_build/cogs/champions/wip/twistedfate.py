"""Twisted Fate combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent


class TwistedFateCog(ChampionCog):
    """Model Twisted Fate's Q5/W5/E1/R2 level-thirteen duel fixture.

    Wild Cards hits the opponent with one card for its rank-five damage. Pick
    a Card locks the Blue Card, whose empowered attack deals ``BlueDamage``
    in place of the attack's own damage; the Gold Card's stun duration is
    absent from the locked spell data, so the stun-card choice is excluded.
    Stacked Deck adds its rank-one bonus damage to every fourth attack.
    Destiny is a teleport with no combat effect.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/TwistedFate.json",
        "data/raw/16.17.1/communitydragon/champions/4.json",
        "data/raw/16.17.1/communitydragon/champions/twistedfate.bin.json",
    )

    _Q_AT_MS = 300
    _BLUE_CARD_ATTACK_INDEX = 1
    _FIRST_ATTACK_MS = 200

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Twisted Fate's wild-cards, blue-card, and stacked-deck rotation.

        :param context: Role-bound Twisted Fate and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        ap = snapshot.ability_power
        bonus_ad = snapshot.bonus_attack_damage
        events: list[ActionEvent] = [
            action(
                "TWISTEDFATE_Q_WILD_CARDS",
                at_ms=self._Q_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(240) + Decimal("0.5") * bonus_ad + Decimal("0.85") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            )
        ]
        stacked_deck = Decimal(65) + Decimal("0.2") * bonus_ad + Decimal("0.4") * ap
        interval = self._attack_interval_ms(snapshot.attack_speed)
        for index, at_ms in enumerate(
            range(self._FIRST_ATTACK_MS, context.duration_ms + 1, interval)
        ):
            if index == self._BLUE_CARD_ATTACK_INDEX:
                outputs = [
                    damage(
                        context.opponent_entity,
                        Decimal(120) + snapshot.attack_damage + ap,
                        DamageType.MAGIC,
                    )
                ]
            else:
                outputs = [
                    damage(context.opponent_entity, snapshot.attack_damage, DamageType.PHYSICAL)
                ]
            if index % 4 == 3:
                outputs.append(damage(context.opponent_entity, stacked_deck, DamageType.MAGIC))
            events.append(
                action(
                    f"TWISTEDFATE_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 700 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
        level_blockers = (
            ()
            if snapshot.level == 13
            else (f"TWISTEDFATE_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "twistedfate_q5_w5_e1_r2_blue_card_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "TWISTEDFATE_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "TWISTEDFATE_GOLD_CARD_STUN_DURATION_NOT_IN_LOCKED_DATA",
                "TWISTEDFATE_Q_SINGLE_CARD_HIT_ASSUMED",
                "TWISTEDFATE_E_ATTACK_SPEED_NOT_APPLIED_TO_CADENCE",
                "TWISTEDFATE_RESOURCE_COSTS_NOT_EVALUATED",
                "TWISTEDFATE_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Report that the blue-card rotation applies no hard control.

        :param context: Role-bound Twisted Fate and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "twistedfate_no_hard_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
