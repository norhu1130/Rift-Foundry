"""Yuumi combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class YuumiCog(ChampionCog):
    """Model an unattached Yuumi's E5/Q5/W1/R2 level-thirteen duel fixture.

    A duel leaves Yuumi with no ally to attach to. Zoomies shields her for its
    rank-five ``TotalShielding``, Final Chapter's five waves deal full damage
    on the first and ``MultiMissileReduction`` on each later wave, rooting on
    the third, and Feline Friendship heals her for its level-scaled
    ``HealAmount`` on the first champion hit, with its ``PassiveCooldown``
    longer than the rest of the encounter. Prowling Projectile's base damage
    is absent from the locked data values, and Final Chapter's wave healing
    and You and Me! require an ally, so all three are excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Yuumi.json",
        "data/raw/16.17.1/communitydragon/champions/350.json",
        "data/raw/16.17.1/communitydragon/champions/yuumi.bin.json",
    )

    _E_AT_MS = 0
    _E_SHIELD_MS = 3000
    _R_AT_MS = 600
    _R_WAVE_MS = 750
    _R_WAVES = 5
    _R_ROOT_WAVE = 3
    _R_ROOT_MS = 1250
    _FIRST_ATTACK_MS = 200

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build unattached Yuumi's zoomies, final-chapter, and attack rotation.

        :param context: Role-bound Yuumi and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        ap = snapshot.ability_power
        wave = Decimal(125) + Decimal("0.25") * ap
        passive_heal = (
            Decimal(20) + Decimal(90) * Decimal(snapshot.level - 1) / Decimal(17)
        ) + Decimal("0.3") * ap
        events: list[ActionEvent] = [
            action(
                "YUUMI_E_ZOOMIES",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(
                        context.self_entity,
                        Decimal(165) + Decimal("0.4") * ap,
                        duration_ms=self._E_SHIELD_MS,
                    ),
                ),
                requires_living_opponent=False,
            )
        ]
        for index in range(self._R_WAVES):
            at_ms = self._R_AT_MS + index * self._R_WAVE_MS
            outputs: list[object] = [
                damage(
                    context.opponent_entity,
                    wave if index == 0 else wave * Decimal("0.25"),
                    DamageType.MAGIC,
                )
            ]
            if index + 1 == self._R_ROOT_WAVE:
                outputs.append(
                    crowd_control(context.opponent_entity, "ROOT", duration_ms=self._R_ROOT_MS)
                )
            events.append(
                action(
                    f"YUUMI_R_FINAL_CHAPTER_WAVE_{index + 1}",
                    at_ms=at_ms,
                    sequence=base + 1 + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=tuple(outputs),
                )
            )
        interval = self._attack_interval_ms(snapshot.attack_speed)
        for index, at_ms in enumerate(
            range(self._FIRST_ATTACK_MS, context.duration_ms + 1, interval)
        ):
            outputs = [damage(context.opponent_entity, snapshot.attack_damage, DamageType.PHYSICAL)]
            if index == 0:
                outputs.append(healing(context.self_entity, passive_heal))
            events.append(
                action(
                    f"YUUMI_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 700 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
        level_blockers = (
            () if snapshot.level == 13 else (f"YUUMI_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "yuumi_e5_q5_w1_r2_unattached_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "YUUMI_LEVEL13_E5_Q5_W1_R2_POLICY_UNVERIFIED",
                "YUUMI_Q_BASE_DAMAGE_ABSENT_FROM_LOCKED_DATA_VALUES",
                "YUUMI_R_WAVE_HEALING_AND_W_ATTACH_REQUIRE_ALLY",
                "YUUMI_E_ATTACK_SPEED_NOT_APPLIED_TO_CADENCE",
                "YUUMI_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the third-wave Final Chapter root as a control window.

        :param context: Role-bound Yuumi and opponent snapshots.
        :return: Deterministic control windows caused by Yuumi's rotation.
        """
        start = self._R_AT_MS + (self._R_ROOT_WAVE - 1) * self._R_WAVE_MS
        return ReactionPlan(
            "yuumi_r_root_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "yuumi_r_final_chapter_root",
                    start,
                    min(start + self._R_ROOT_MS, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    f"YUUMI_R_FINAL_CHAPTER_WAVE_{self._R_ROOT_WAVE}",
                    True,
                    ControlType.ROOT,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
