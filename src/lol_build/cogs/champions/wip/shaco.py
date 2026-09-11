"""Shaco combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class ShacoCog(ChampionCog):
    """Model an AD Shaco's E5/Q5/W1/R2 level-thirteen ambush fixture.

    Deceive teleports behind the opponent and empowers the first attack with
    its rank-five ``TotalDamage``. Two-Shiv Poison's passive adds its
    level-scaled ``ShivDamage`` to every attack and slows, and the thrown shiv
    lands its rank-five damage and slow. Jack In The Box needs a box placed
    before the fight and Hallucinate's clone is a pet, so both are excluded,
    as are critical backstabs and the low-health shiv execute.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Shaco.json",
        "data/raw/16.17.1/communitydragon/champions/35.json",
        "data/raw/16.17.1/communitydragon/champions/shaco.bin.json",
    )

    _DECEIVE_ATTACK_MS = 200
    _E_AT_MS = 900
    _E_SLOW_MS = 3000
    _PASSIVE_SLOW_MS = 2000

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Shaco's deceive, poisoned-attack, and shiv rotation.

        :param context: Role-bound Shaco and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        bonus_ad = snapshot.bonus_attack_damage
        ap = snapshot.ability_power
        shiv = (
            Decimal(15)
            + Decimal(35) * Decimal(snapshot.level - 1) / Decimal(17)
            + Decimal("0.1") * ap
        )
        events: list[ActionEvent] = [
            action(
                "SHACO_E_TWO_SHIV_POISON",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(170) + Decimal("0.8") * bonus_ad + Decimal("0.6") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=self._E_SLOW_MS,
                        magnitude=Decimal("0.30"),
                    ),
                ),
            )
        ]
        interval = self._attack_interval_ms(snapshot.attack_speed)
        for index, at_ms in enumerate(
            range(self._DECEIVE_ATTACK_MS, context.duration_ms + 1, interval)
        ):
            outputs = [
                damage(context.opponent_entity, snapshot.attack_damage, DamageType.PHYSICAL),
                damage(context.opponent_entity, shiv, DamageType.MAGIC),
                crowd_control(
                    context.opponent_entity,
                    "SLOW",
                    duration_ms=self._PASSIVE_SLOW_MS,
                    magnitude=Decimal("0.30"),
                ),
            ]
            if index == 0:
                outputs.append(
                    damage(
                        context.opponent_entity,
                        Decimal(65) + Decimal("0.6") * bonus_ad,
                        DamageType.PHYSICAL,
                    )
                )
            events.append(
                action(
                    f"SHACO_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 700 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
        level_blockers = (
            () if snapshot.level == 13 else (f"SHACO_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "shaco_e5_q5_w1_r2_deceive_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "SHACO_LEVEL13_E5_Q5_W1_R2_POLICY_UNVERIFIED",
                "SHACO_W_BOXES_REQUIRE_PRE_PLACEMENT",
                "SHACO_R_HALLUCINATE_CLONE_IS_A_PET",
                "SHACO_BACKSTAB_POSITION_AND_CRITICAL_STRIKE_NOT_MODELED",
                "SHACO_E_LOW_HEALTH_EXECUTE_NOT_MODELED",
                "SHACO_PASSIVE_SHIV_SLOW_MAGNITUDE_READ_FROM_ACTIVE_RANK",
                "SHACO_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Report that Shaco's modeled rotation applies no hard control.

        :param context: Role-bound Shaco and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "shaco_no_hard_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
