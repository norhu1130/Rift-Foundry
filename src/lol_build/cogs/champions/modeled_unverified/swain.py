"""Swain combat Cog backed by locked 16.17.1 champion sources."""

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


class SwainCog(ChampionCog):
    """Model Swain's Q5/E5/W1/R2 level-thirteen duel fixture.

    Death's Hand lands its single-bolt hit, Vision of Empire strikes after
    its long-range cast delay, and Nevermove's pull lands its root and
    secondary damage. Demonic Ascension is applied as three half-second
    drain ticks rather than a full channel with its Demonflare recast, since
    the recast depends on a separate Demon Power resource this fixture does
    not track. Q's extra-bolt bonus at maximum range is excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Swain.json",
        "data/raw/16.17.1/communitydragon/champions/50.json",
        "data/raw/16.17.1/communitydragon/champions/swain.bin.json",
    )

    _E_AT_MS = 0
    _E_ROOT_MS = 1500
    _Q_AT_MS = 900
    _W_AT_MS = 1600
    _W_DELAY_MS = 1000
    _W_SLOW_MS = 1500
    _R_AT_MS = 2900
    _R_TICK_MS = 500
    _R_TICK_COUNT = 3

    def _r_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Demonic Ascension's half-second drain ticks.

        :param context: Role-bound Swain and opponent snapshots.
        :return: Evenly spaced drain-tick events.
        """
        base = self._sequence_base(context) + 300
        tick = Decimal(25) + Decimal("0.04") * context.snapshot.ability_power
        events: list[ActionEvent] = []
        for index in range(self._R_TICK_COUNT):
            at_ms = self._R_AT_MS + self._R_TICK_MS * index
            if at_ms > context.duration_ms:
                break
            events.append(
                action(
                    f"SWAIN_R_DEMONIC_ASCENSION_TICK_{index + 1}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, tick, DamageType.MAGIC),),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Swain's root-pull, bolt, vision-strike, and drain rotation.

        :param context: Role-bound Swain and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        e_damage = Decimal(250) + Decimal("0.7") * context.snapshot.ability_power
        q_damage = Decimal(180) + Decimal("0.45") * context.snapshot.ability_power
        w_damage = Decimal(70) + Decimal("0.6") * context.snapshot.ability_power
        fixed = [
            action(
                "SWAIN_E_NEVERMOVE",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity, "ROOT", duration_ms=self._E_ROOT_MS
                    ),
                ),
            ),
            action(
                "SWAIN_Q_DEATHS_HAND",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.MAGIC),),
            ),
            action(
                "SWAIN_W_VISION_OF_EMPIRE",
                at_ms=self._W_AT_MS + self._W_DELAY_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, w_damage, DamageType.MAGIC),
                    StatModifierOutput(
                        context.opponent_entity,
                        "MOVE_SPEED_PERCENT",
                        Decimal("-0.50"),
                        self._W_SLOW_MS,
                    ),
                ),
            ),
        ]
        events = (*fixed, *self._r_events(context), *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"SWAIN_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "swain_q5_e5_w1_r2_root_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "SWAIN_R_DEMONFLARE_AND_DEMON_POWER_NOT_MODELED",
                "SWAIN_Q_MAX_RANGE_EXTRA_BOLT_NOT_MODELED",
                "SWAIN_PASSIVE_RAVENOUS_FLOCK_NOT_MODELED",
                "SWAIN_RESOURCE_COSTS_NOT_EVALUATED",
                "SWAIN_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Swain and opponent combat snapshots.
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
                    f"SWAIN_BASIC_ATTACK_{index}",
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
        """Expose the Nevermove root as this Cog's hostile control window.

        :param context: Role-bound Swain and opponent snapshots.
        :return: Deterministic control windows caused by Swain's rotation.
        """
        return ReactionPlan(
            "swain_e_root_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "swain_e_nevermove_root",
                    self._E_AT_MS,
                    min(self._E_AT_MS + self._E_ROOT_MS, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "SWAIN_E_NEVERMOVE",
                    True,
                    ControlType.ROOT,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
