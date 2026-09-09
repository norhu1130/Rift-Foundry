"""Ziggs combat Cog backed by locked 16.17.1 champion sources."""

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


class ZiggsCog(ChampionCog):
    """Model Ziggs's Q5/E5/W1/R2 level-thirteen duel fixture.

    Bouncing Bomb hits on cast; Satchel Charge and Hexplosive Minefield are
    placed charges resolved at a fixed trigger delay rather than the player
    choice their real timers allow; Mega Inferno Bomb lands its inner-ring
    value after a travel delay. The minefield's multiple mines collapse to
    one trigger, and the ultimate's reduced outer-ring damage is excluded,
    rather than guessing either without locked support.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Ziggs.json",
        "data/raw/16.17.1/communitydragon/champions/115.json",
        "data/raw/16.17.1/communitydragon/champions/ziggs.bin.json",
    )

    _Q_AT_MS = 0
    _E_AT_MS = 900
    _E_TRIGGER_DELAY_MS = 600
    _E_SLOW_MS = 1500
    _W_AT_MS = 1900
    _W_TRIGGER_DELAY_MS = 500
    _R_AT_MS = 2900
    _R_TRAVEL_DELAY_MS = 1000

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Ziggs's bomb, minefield, satchel, and ultimate rotation.

        :param context: Role-bound Ziggs and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        q_damage = Decimal(280) + Decimal("0.8") * context.snapshot.ability_power
        e_damage = Decimal(190) + Decimal("0.45") * context.snapshot.ability_power
        w_damage = Decimal(35) + Decimal("0.5") * context.snapshot.ability_power
        r_damage = Decimal(300) + context.snapshot.ability_power
        fixed = [
            action(
                "ZIGGS_Q_BOUNCING_BOMB",
                at_ms=self._Q_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.MAGIC),),
            ),
            action(
                "ZIGGS_E_HEXPLOSIVE_MINEFIELD",
                at_ms=self._E_AT_MS + self._E_TRIGGER_DELAY_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    StatModifierOutput(
                        context.opponent_entity,
                        "MOVE_SPEED_PERCENT",
                        Decimal("-0.50"),
                        self._E_SLOW_MS,
                    ),
                ),
            ),
            action(
                "ZIGGS_W_SATCHEL_CHARGE",
                at_ms=self._W_AT_MS + self._W_TRIGGER_DELAY_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, w_damage, DamageType.MAGIC),),
            ),
            action(
                "ZIGGS_R_MEGA_INFERNO_BOMB",
                at_ms=self._R_AT_MS + self._R_TRAVEL_DELAY_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, r_damage, DamageType.MAGIC),),
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"ZIGGS_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "ziggs_q5_e5_w1_r2_bomb_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "ZIGGS_W_KNOCKBACK_AND_TURRET_DAMAGE_NOT_MODELED",
                "ZIGGS_E_MULTIPLE_MINE_TRIGGERS_NOT_MODELED",
                "ZIGGS_R_OUTER_RING_REDUCED_DAMAGE_NOT_MODELED",
                "ZIGGS_PASSIVE_SHORT_FUSE_BONUS_DAMAGE_NOT_MODELED",
                "ZIGGS_RESOURCE_COSTS_NOT_EVALUATED",
                "ZIGGS_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Ziggs and opponent combat snapshots.
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
                    f"ZIGGS_BASIC_ATTACK_{index}",
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
        """Report that Ziggs's rotation applies no hostile hard control.

        :param context: Role-bound Ziggs and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "ziggs_no_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
