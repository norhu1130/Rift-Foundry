"""Xayah combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class XayahCog(ChampionCog):
    """Model Xayah's Q5/E5/W1/R2 level-thirteen feather combo.

    Double Daggers hits with both daggers, the second at ``MultiHitRatio``,
    and drops two Feathers; Clean Cuts makes the next three attacks drop a
    Feather each. Bladecaller then recalls all five, each after the first
    losing ``FeatherFalloff``, and roots at ``FeatherThreshold`` feathers.
    Featherstorm makes Xayah untargetable for ``RUntargetable`` before its
    daggers land. Deadly Plumage's attack speed and bonus damage are excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Xayah.json",
        "data/raw/16.17.1/communitydragon/champions/498.json",
        "data/raw/16.17.1/communitydragon/champions/xayah.bin.json",
    )

    _Q_AT_MS = 0
    _FIRST_ATTACK_MS = 300
    _PASSIVE_FEATHERS = 3
    _E_AFTER_ATTACKS_MS = 200
    _E_ROOT_MS = 1250
    _R_OFFSET_MS = 1500
    _R_UNTARGETABLE_MS = 1250

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Xayah's daggers, feather attacks, bladecaller, and featherstorm.

        :param context: Role-bound Xayah and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        bonus_ad = snapshot.bonus_attack_damage
        dagger = Decimal(105) + Decimal("0.5") * bonus_ad
        feather = Decimal(110) + Decimal("0.4") * bonus_ad
        feathers = 2 + self._PASSIVE_FEATHERS
        recall = feather * sum(
            (Decimal(1) - Decimal("0.05") * index for index in range(feathers)), Decimal(0)
        )
        interval = self._attack_interval_ms(snapshot.attack_speed)
        attack_times = tuple(range(self._FIRST_ATTACK_MS, context.duration_ms + 1, interval))
        e_ms = (
            attack_times[self._PASSIVE_FEATHERS - 1] + self._E_AFTER_ATTACKS_MS
            if len(attack_times) >= self._PASSIVE_FEATHERS
            else None
        )
        events: list[ActionEvent] = [
            action(
                "XAYAH_Q_DOUBLE_DAGGERS",
                at_ms=self._Q_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, dagger, DamageType.PHYSICAL),
                    damage(context.opponent_entity, dagger * Decimal("0.5"), DamageType.PHYSICAL),
                ),
            )
        ]
        if e_ms is not None and e_ms <= context.duration_ms:
            events.append(
                action(
                    "XAYAH_E_BLADECALLER",
                    at_ms=e_ms,
                    sequence=base + 1,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, recall, DamageType.PHYSICAL),
                        crowd_control(context.opponent_entity, "ROOT", duration_ms=self._E_ROOT_MS),
                    ),
                )
            )
            r_ms = e_ms + self._R_OFFSET_MS
            if r_ms + self._R_UNTARGETABLE_MS <= context.duration_ms:
                events.append(
                    action(
                        "XAYAH_R_FEATHERSTORM",
                        at_ms=r_ms,
                        sequence=base + 2,
                        source=context.self_entity,
                        channel=ActionChannel.ABILITY,
                        outputs=(
                            StatusOutput(context.self_entity, "STASIS", self._R_UNTARGETABLE_MS),
                        ),
                        requires_living_opponent=False,
                    )
                )
                events.append(
                    action(
                        "XAYAH_R_FEATHERSTORM_DAGGERS",
                        at_ms=r_ms + self._R_UNTARGETABLE_MS,
                        sequence=base + 3,
                        source=context.self_entity,
                        channel=ActionChannel.ABILITY,
                        outputs=(
                            damage(
                                context.opponent_entity,
                                Decimal(300) + bonus_ad,
                                DamageType.PHYSICAL,
                            ),
                        ),
                    )
                )
        for index, at_ms in enumerate(attack_times):
            events.append(
                action(
                    f"XAYAH_BASIC_ATTACK_{index}",
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
            () if snapshot.level == 13 else (f"XAYAH_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "xayah_q5_e5_w1_r2_feather_combo_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "XAYAH_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "XAYAH_E_ALL_FEATHERS_PASS_THROUGH_TARGET_ASSUMED",
                "XAYAH_W_ATTACK_SPEED_AND_BONUS_DAMAGE_NOT_MODELED",
                "XAYAH_R_UNTARGETABILITY_READ_AS_STASIS",
                "XAYAH_R_FEATHERS_NOT_RECALLED_IN_ENCOUNTER",
                "XAYAH_CRITICAL_STRIKE_NOT_MODELED",
                "XAYAH_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the Bladecaller root as this Cog's hostile control window.

        :param context: Role-bound Xayah and opponent snapshots.
        :return: Deterministic control windows caused by Xayah's rotation.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        e_ms = (
            self._FIRST_ATTACK_MS
            + (self._PASSIVE_FEATHERS - 1) * interval
            + self._E_AFTER_ATTACKS_MS
        )
        windows = (
            (
                CastBlockWindow(
                    "xayah_e_bladecaller_root",
                    e_ms,
                    min(e_ms + self._E_ROOT_MS, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "XAYAH_E_BLADECALLER",
                    True,
                    ControlType.ROOT,
                ),
            )
            if e_ms < context.duration_ms
            else ()
        )
        return ReactionPlan(
            "xayah_e_root_reaction_v1",
            cast_block_windows=windows,
            blockers=(*self.verification_blockers(),),
        )
