"""Sona combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent


class SonaCog(ChampionCog):
    """Model Sona's Q5/R2/W3/E3 level-thirteen duel fixture.

    Hymn of Valor lands its cast damage, and Crescendo lands its damage and
    stun. Aria of Perseverance heals Sona for its locked rank-three
    ``TotalHeal`` (``BaseHeal`` plus ``HealRatio`` of ability power); its
    second heal target and the aura shield only reach allies, which a duel
    has none of. Song of Celerity is pure movement utility. Power Chord's rotating
    empowered-attack passive is excluded rather than guessed, since which
    variant is active depends on which ability was cast most recently.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Sona.json",
        "data/raw/16.17.1/communitydragon/champions/37.json",
        "data/raw/16.17.1/communitydragon/champions/sona.bin.json",
    )

    _Q_AT_MS = 0
    _R_AT_MS = 900
    _R_STUN_MS = 1500
    _W_AT_MS = 1800

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Sona's aura-hymn and crescendo-stun rotation.

        :param context: Role-bound Sona and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        q_damage = Decimal(190) + Decimal("0.4") * context.snapshot.ability_power
        r_damage = Decimal(250) + Decimal("0.5") * context.snapshot.ability_power
        w_heal = Decimal(60) + Decimal("0.30") * context.snapshot.ability_power
        fixed = [
            action(
                "SONA_Q_HYMN_OF_VALOR",
                at_ms=self._Q_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.MAGIC),),
            ),
            action(
                "SONA_R_CRESCENDO",
                at_ms=self._R_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=self._R_STUN_MS),
                ),
            ),
            action(
                "SONA_W_ARIA_OF_PERSEVERANCE",
                at_ms=self._W_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(healing(context.self_entity, w_heal),),
                requires_living_opponent=False,
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"SONA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "sona_q5_r2_w3_e3_hymn_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "SONA_PASSIVE_POWER_CHORD_NOT_MODELED",
                "SONA_W_ALLY_HEAL_AND_AURA_SHIELD_REQUIRE_ALLIES",
                "SONA_Q_ON_HIT_AURA_NOT_MODELED",
                "SONA_RESOURCE_COSTS_NOT_EVALUATED",
                "SONA_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Sona and opponent combat snapshots.
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
                    f"SONA_BASIC_ATTACK_{index}",
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
        """Expose the Crescendo stun as this Cog's hostile control window.

        :param context: Role-bound Sona and opponent snapshots.
        :return: Deterministic control windows caused by Sona's rotation.
        """
        return ReactionPlan(
            "sona_r_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "sona_r_crescendo_stun",
                    self._R_AT_MS,
                    min(self._R_AT_MS + self._R_STUN_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "SONA_R_CRESCENDO",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
