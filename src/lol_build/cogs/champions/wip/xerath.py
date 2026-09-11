"""Xerath combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent


class XerathCog(ChampionCog):
    """Model Xerath's Q5/E5/W1/R2 level-thirteen duel fixture.

    Arcanopulse and Eye of Destruction resolve at their guaranteed minimum
    values rather than a charge time or a sweet-spot hit this fixture does
    not vary. Shocking Orb's stun uses its locked minimum duration, since the
    maximum only applies at long range. Rite of the Arcane fires its rank-two
    shot count at even intervals with each shot's locked ramp added on top,
    approximating a channel this engine cannot let a player aim shot-by-shot.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Xerath.json",
        "data/raw/16.17.1/communitydragon/champions/101.json",
        "data/raw/16.17.1/communitydragon/champions/xerath.bin.json",
    )

    _W_AT_MS = 0
    _W_DELAY_MS = 500
    _E_AT_MS = 1000
    _E_STUN_MS = 750
    _Q_AT_MS = 1800
    _R_AT_MS = 2600
    _R_SHOT_COUNT = 4
    _R_SHOT_INTERVAL_MS = 700

    def _r_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Rite of the Arcane's rank-two shots with their ramp.

        :param context: Role-bound Xerath and opponent snapshots.
        :return: Evenly spaced shot events with escalating damage.
        """
        base = self._sequence_base(context) + 300
        first_shot = Decimal(170) + Decimal("0.45") * context.snapshot.ability_power
        ramp = Decimal(20) + Decimal("0.05") * context.snapshot.ability_power
        events: list[ActionEvent] = []
        for index in range(self._R_SHOT_COUNT):
            at_ms = self._R_AT_MS + self._R_SHOT_INTERVAL_MS * index
            if at_ms > context.duration_ms:
                break
            shot_damage = first_shot + ramp * index
            events.append(
                action(
                    f"XERATH_R_RITE_OF_THE_ARCANE_{index + 1}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, shot_damage, DamageType.MAGIC),),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Xerath's barrage, stun, pulse, and ramping-shot rotation.

        :param context: Role-bound Xerath and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        w_damage = Decimal(50) + Decimal("0.65") * context.snapshot.ability_power
        e_damage = Decimal(190) + Decimal("0.45") * context.snapshot.ability_power
        q_damage = Decimal(230) + Decimal("0.9") * context.snapshot.ability_power
        fixed = [
            action(
                "XERATH_W_EYE_OF_DESTRUCTION",
                at_ms=self._W_AT_MS + self._W_DELAY_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, w_damage, DamageType.MAGIC),),
            ),
            action(
                "XERATH_E_SHOCKING_ORB",
                at_ms=self._E_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=self._E_STUN_MS),
                ),
            ),
            action(
                "XERATH_Q_ARCANOPULSE",
                at_ms=self._Q_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.MAGIC),),
            ),
        ]
        events = (*fixed, *self._r_events(context), *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"XERATH_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "xerath_q5_e5_w1_r2_barrage_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "XERATH_Q_CHARGE_TIME_AND_SLOW_NOT_MODELED",
                "XERATH_W_SWEET_SPOT_BONUS_NOT_MODELED",
                "XERATH_E_DISTANCE_SCALED_STUN_NOT_MODELED",
                "XERATH_R_PLAYER_AIMED_SHOTS_NOT_MODELED",
                "XERATH_PASSIVE_MANA_SURGE_NOT_MODELED",
                "XERATH_RESOURCE_COSTS_NOT_EVALUATED",
                "XERATH_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Xerath and opponent combat snapshots.
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
                    f"XERATH_BASIC_ATTACK_{index}",
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
        """Expose the Shocking Orb stun as this Cog's hostile control window.

        :param context: Role-bound Xerath and opponent snapshots.
        :return: Deterministic control windows caused by Xerath's rotation.
        """
        return ReactionPlan(
            "xerath_e_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "xerath_e_shocking_orb_stun",
                    self._E_AT_MS,
                    min(self._E_AT_MS + self._E_STUN_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "XERATH_E_SHOCKING_ORB",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
