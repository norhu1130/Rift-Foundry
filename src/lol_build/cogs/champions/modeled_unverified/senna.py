"""Senna combat Cog backed by locked 16.17.1 champion sources."""

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


class SennaCog(ChampionCog):
    """Model Senna's Q5/W5/E1/R2 level-thirteen duel fixture.

    Last Embrace latches on after its ``DelayTime`` for rank-five damage and
    root, Piercing Darkness strikes for its rank-five damage and slow, and
    Dawning Shadow's beam lands its rank-two damage. Piercing Darkness heals
    and Dawning Shadow shields only allied champions, so a duel carries
    neither, and Absolution's soul stacks accrue outside the encounter.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Senna.json",
        "data/raw/16.17.1/communitydragon/champions/235.json",
        "data/raw/16.17.1/communitydragon/champions/senna.bin.json",
    )

    _W_AT_MS = 0
    _W_DELAY_MS = 1000
    _W_ROOT_MS = 2250
    _Q_AT_MS = 1300
    _Q_SLOW_MS = 2000
    _R_AT_MS = 2400
    _ATTACKS_FROM_MS = 500

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Senna's embrace, darkness, and dawning-shadow rotation.

        :param context: Role-bound Senna and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        bonus_ad = snapshot.bonus_attack_damage
        events: list[ActionEvent] = [
            action(
                "SENNA_W_LAST_EMBRACE",
                at_ms=self._W_AT_MS + self._W_DELAY_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(230) + Decimal("0.9") * bonus_ad,
                        DamageType.PHYSICAL,
                    ),
                    crowd_control(context.opponent_entity, "ROOT", duration_ms=self._W_ROOT_MS),
                ),
            ),
            action(
                "SENNA_Q_PIERCING_DARKNESS",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(130) + Decimal("0.6") * bonus_ad,
                        DamageType.PHYSICAL,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=self._Q_SLOW_MS,
                        magnitude=Decimal("0.15") + Decimal("0.0007") * snapshot.ability_power,
                    ),
                ),
            ),
            action(
                "SENNA_R_DAWNING_SHADOW",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(400)
                        + Decimal("0.7") * snapshot.ability_power
                        + Decimal("1.15") * bonus_ad,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
        ]
        interval = self._attack_interval_ms(snapshot.attack_speed)
        for index, at_ms in enumerate(
            range(self._ATTACKS_FROM_MS, context.duration_ms + 1, interval)
        ):
            events.append(
                action(
                    f"SENNA_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 700 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity, snapshot.attack_damage, DamageType.PHYSICAL
                        ),
                    ),
                )
            )
        level_blockers = (
            () if snapshot.level == 13 else (f"SENNA_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "senna_q5_w5_e1_r2_embrace_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "SENNA_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "SENNA_Q_HEAL_AND_R_SHIELD_REQUIRE_ALLIES",
                "SENNA_PASSIVE_SOUL_STACKS_AND_CURRENT_HEALTH_ATTACK_BONUS_NOT_MODELED",
                "SENNA_E_WRAITH_CAMOUFLAGE_NOT_MODELED",
                "SENNA_RESOURCE_COSTS_NOT_EVALUATED",
                "SENNA_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the Last Embrace root as this Cog's hostile control window.

        :param context: Role-bound Senna and opponent snapshots.
        :return: Deterministic control windows caused by Senna's rotation.
        """
        start = self._W_AT_MS + self._W_DELAY_MS
        return ReactionPlan(
            "senna_w_root_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "senna_w_last_embrace_root",
                    start,
                    min(start + self._W_ROOT_MS, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "SENNA_W_LAST_EMBRACE",
                    True,
                    ControlType.ROOT,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
