"""Zilean combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, DeathPreventionOutput


class ZileanCog(ChampionCog):
    """Model Zilean's Q5/E5/W1/R2 level-thirteen duel fixture.

    Time Bomb detonates on its locked fuse timer for damage and a stun, and
    Chronoshift grants its shield alongside the death prevention it exists
    for. Rewind and Time Warp carry no locked damage or control data at all —
    they are pure cooldown and movement utility — so this fixture correctly
    contributes nothing from them rather than inventing an effect neither
    ability has.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Zilean.json",
        "data/raw/16.17.1/communitydragon/champions/26.json",
        "data/raw/16.17.1/communitydragon/champions/zilean.bin.json",
    )

    _R_AT_MS = 0
    _R_DURATION_MS = 5000
    _Q_AT_MS = 600
    _Q_FUSE_MS = 3000
    _Q_STUN_MS = 1500

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Zilean's shield-open and delayed-bomb rotation.

        :param context: Role-bound Zilean and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        r_shield = Decimal(600) + Decimal(2) * context.snapshot.ability_power
        q_damage = Decimal(300) + Decimal("0.9") * context.snapshot.ability_power
        fixed = [
            action(
                "ZILEAN_R_CHRONOSHIFT",
                at_ms=self._R_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(context.self_entity, r_shield, duration_ms=self._R_DURATION_MS),
                    DeathPreventionOutput(
                        context.self_entity,
                        health_floor=Decimal(1),
                        duration_ms=self._R_DURATION_MS,
                        state_key="ZILEAN_R_CHRONOSHIFT",
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "ZILEAN_Q_TIME_BOMB",
                at_ms=self._Q_AT_MS + self._Q_FUSE_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q_damage, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=self._Q_STUN_MS),
                ),
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"ZILEAN_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "zilean_q5_e5_w1_r2_shield_bomb_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "ZILEAN_Q_DOUBLE_BOMB_INSTANT_DETONATE_NOT_MODELED",
                "ZILEAN_PASSIVE_EXPERIENCE_SHARE_NOT_APPLICABLE",
                "ZILEAN_RESOURCE_COSTS_NOT_EVALUATED",
                "ZILEAN_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Zilean and opponent combat snapshots.
        :return: Ordinary basic-attack damage events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 700
        events: list[ActionEvent] = []
        at_ms = 200
        index = 0
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"ZILEAN_BASIC_ATTACK_{index}",
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
        """Expose the Time Bomb stun as this Cog's hostile control window.

        :param context: Role-bound Zilean and opponent snapshots.
        :return: Deterministic control windows caused by Zilean's rotation.
        """
        start_ms = self._Q_AT_MS + self._Q_FUSE_MS
        return ReactionPlan(
            "zilean_q_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "zilean_q_time_bomb_stun",
                    start_ms,
                    min(start_ms + self._Q_STUN_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "ZILEAN_Q_TIME_BOMB",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
