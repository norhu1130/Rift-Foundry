"""Zoe combat Cog backed by locked 16.17.1 champion sources."""

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


class ZoeCog(ChampionCog):
    """Model Zoe's Q5/E5/W1/R2 level-thirteen duel fixture.

    Paddle Star hits with its base damage plus its locked level-scaling
    bonus, and Sleepy Trouble Bubble lands its hit and its delayed sleep.
    Spell Thief and Portal Jump deal no damage of their own — the first is a
    passive shard-pickup and cast-speed mechanic, the second pure
    repositioning — so this fixture correctly contributes nothing from them.
    The sleep-break bonus damage and terrain range extension are excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Zoe.json",
        "data/raw/16.17.1/communitydragon/champions/142.json",
        "data/raw/16.17.1/communitydragon/champions/zoe.bin.json",
    )

    _E_AT_MS = 0
    _E_SLEEP_DELAY_MS = 1400
    _E_SLEEP_MS = 2250
    _Q_AT_MS = 900

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Zoe's bubble-sleep and paddle-star rotation.

        :param context: Role-bound Zoe and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        level_bonus = self._level_breakpoint_value(
            Decimal(2), Decimal(2), ((10, Decimal(3)), (14, Decimal(4))), context.snapshot.level
        )
        q_damage = Decimal(170) + level_bonus + Decimal("0.6") * context.snapshot.ability_power
        e_damage = Decimal(230) + Decimal("0.45") * context.snapshot.ability_power
        fixed = [
            action(
                "ZOE_E_SLEEPY_TROUBLE_BUBBLE",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, e_damage, DamageType.MAGIC),),
            ),
            action(
                "ZOE_E_SLEEPY_TROUBLE_BUBBLE_SLEEP",
                at_ms=self._E_AT_MS + self._E_SLEEP_DELAY_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    crowd_control(context.opponent_entity, "SLEEP", duration_ms=self._E_SLEEP_MS),
                ),
                requires_living_opponent=False,
            ),
            action(
                "ZOE_Q_PADDLE_STAR",
                at_ms=self._Q_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.MAGIC),),
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"ZOE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "zoe_q5_e5_w1_r2_bubble_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "ZOE_E_SLEEP_BREAK_BONUS_DAMAGE_NOT_MODELED",
                "ZOE_W_SPELL_THIEF_NOT_APPLICABLE_IN_DUEL",
                "ZOE_R_PORTAL_JUMP_NOT_APPLICABLE_IN_DUEL",
                "ZOE_PASSIVE_MORE_SPARKLES_NOT_MODELED",
                "ZOE_RESOURCE_COSTS_NOT_EVALUATED",
                "ZOE_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Zoe and opponent combat snapshots.
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
                    f"ZOE_BASIC_ATTACK_{index}",
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
        """Expose the delayed Sleep as this Cog's hostile control window.

        :param context: Role-bound Zoe and opponent snapshots.
        :return: Deterministic control windows caused by Zoe's rotation.
        """
        start_ms = self._E_AT_MS + self._E_SLEEP_DELAY_MS
        return ReactionPlan(
            "zoe_e_sleep_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "zoe_e_sleepy_trouble_bubble_sleep",
                    start_ms,
                    min(start_ms + self._E_SLEEP_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "ZOE_E_SLEEPY_TROUBLE_BUBBLE_SLEEP",
                    True,
                    ControlType.SLEEP,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
