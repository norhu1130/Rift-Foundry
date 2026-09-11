"""Viktor combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent


class ViktorCog(ChampionCog):
    """Model Viktor's Q5/E5/W1/R2 level-thirteen duel fixture.

    Siphon Power shields Viktor and empowers the following attack, Hextech
    Ray lands its laser and aftershock, and Arcane Storm applies its initial
    burst and three ticks of its rank-two storm. Gravity Field's stun is
    included at its locked stack timer, on the assumption the opponent
    remains inside the field for that long — a real assumption, not a
    guarantee, and named as one. The shield's level-scaling term uses linear
    interpolation between its locked level-one and level-eighteen values.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Viktor.json",
        "data/raw/16.17.1/communitydragon/champions/112.json",
        "data/raw/16.17.1/communitydragon/champions/viktor.bin.json",
    )

    _W_AT_MS = 0
    _W_STACK_CADENCE_MS = 500
    _W_STACKS_FOR_STUN = 6
    _W_STUN_MS = 1500
    _Q_AT_MS = 2000
    _E_AT_MS = 2700
    _E_DELAY_MS = 1000
    _E_AFTERSHOCK_DELAY_MS = 300
    _R_AT_MS = 4200
    _R_TICK_MS = 1000
    _R_TICK_COUNT = 3

    def _r_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Arcane Storm's initial burst and its rank-two ticks.

        :param context: Role-bound Viktor and opponent snapshots.
        :return: Initial burst followed by evenly spaced subsequent ticks.
        """
        base = self._sequence_base(context) + 400
        initial = Decimal(175) + Decimal("0.5") * context.snapshot.ability_power
        tick = Decimal(105) + Decimal("0.35") * context.snapshot.ability_power
        events: list[ActionEvent] = [
            action(
                "VIKTOR_R_ARCANE_STORM_INITIAL",
                at_ms=self._R_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, initial, DamageType.MAGIC),),
            )
        ]
        for index in range(1, self._R_TICK_COUNT + 1):
            at_ms = self._R_AT_MS + self._R_TICK_MS * index
            if at_ms > context.duration_ms:
                break
            events.append(
                action(
                    f"VIKTOR_R_ARCANE_STORM_TICK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, tick, DamageType.MAGIC),),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Viktor's shield-open, stun-field, laser, and storm rotation.

        :param context: Role-bound Viktor and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        # ByCharLevelInterpolation(40 at level 1, 140 at level 18), evaluated
        # at level 13: 40 + (140 - 40) * (13 - 1) / (18 - 1).
        shield_base = Decimal(40) + Decimal(100) * Decimal(12) / Decimal(17)
        q_shield = shield_base + Decimal("0.25") * context.snapshot.ability_power
        q_bonus = (
            Decimal(120)
            + Decimal("0.5") * context.snapshot.ability_power
            + context.snapshot.bonus_attack_damage
        )
        e_laser = Decimal(230) + Decimal("0.5") * context.snapshot.ability_power
        e_aftershock = Decimal(140) + Decimal("0.8") * context.snapshot.ability_power
        fixed = [
            action(
                "VIKTOR_W_GRAVITY_FIELD",
                at_ms=self._W_AT_MS + self._W_STACK_CADENCE_MS * self._W_STACKS_FOR_STUN,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    crowd_control(context.opponent_entity, "STUN", duration_ms=self._W_STUN_MS),
                ),
            ),
            action(
                "VIKTOR_Q_SIPHON_POWER_SHIELD",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(shielding(context.self_entity, q_shield, duration_ms=2500),),
                requires_living_opponent=False,
            ),
            action(
                "VIKTOR_Q_SIPHON_POWER_EMPOWERED_ATTACK",
                at_ms=self._Q_AT_MS + 200,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity,
                        context.snapshot.attack_damage,
                        DamageType.PHYSICAL,
                    ),
                    damage(context.opponent_entity, q_bonus, DamageType.MAGIC),
                ),
            ),
            action(
                "VIKTOR_E_HEXTECH_RAY_LASER",
                at_ms=self._E_AT_MS + self._E_DELAY_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, e_laser, DamageType.MAGIC),),
            ),
            action(
                "VIKTOR_E_HEXTECH_RAY_AFTERSHOCK",
                at_ms=self._E_AT_MS + self._E_DELAY_MS + self._E_AFTERSHOCK_DELAY_MS,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, e_aftershock, DamageType.MAGIC),),
            ),
        ]
        events = (
            *fixed,
            *self._r_events(context),
            *self._basic_attack_events(context, skip_at_ms=self._Q_AT_MS + 200),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"VIKTOR_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "viktor_q5_e5_w1_r2_field_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "VIKTOR_W_STAY_IN_FIELD_ASSUMPTION",
                "VIKTOR_Q_MISSILE_PICKUP_VARIANT_NOT_MODELED",
                "VIKTOR_PASSIVE_GLORIOUS_EVOLUTION_NOT_MODELED",
                "VIKTOR_RESOURCE_COSTS_NOT_EVALUATED",
                "VIKTOR_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(
        self, context: ParticipantContext, *, skip_at_ms: int
    ) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Viktor and opponent combat snapshots.
        :param skip_at_ms: Millisecond already covered by the empowered attack.
        :return: Ordinary basic-attack damage events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 700
        events: list[ActionEvent] = []
        at_ms = 200
        index = 0
        while at_ms <= context.duration_ms:
            if abs(at_ms - skip_at_ms) > 50:
                events.append(
                    action(
                        f"VIKTOR_BASIC_ATTACK_{index}",
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
        """Expose the Gravity Field stun as this Cog's hostile control window.

        :param context: Role-bound Viktor and opponent snapshots.
        :return: Deterministic control windows caused by Viktor's rotation.
        """
        start_ms = self._W_AT_MS + self._W_STACK_CADENCE_MS * self._W_STACKS_FOR_STUN
        return ReactionPlan(
            "viktor_w_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "viktor_w_gravity_field_stun",
                    start_ms,
                    min(start_ms + self._W_STUN_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "VIKTOR_W_GRAVITY_FIELD",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
