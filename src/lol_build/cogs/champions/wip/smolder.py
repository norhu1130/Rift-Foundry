"""Smolder combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class SmolderCog(ChampionCog):
    """Model Smolder's Q5/W5/E1/R2 level-thirteen duel fixture.

    Super Scorcher Breath lands its rank-five ``TotalDamage`` and applies
    Smolder's life steal at its locked ``LifestealMod``. Achooo! hits and
    explodes on the champion and slows, Flap, Flap, Flap bombards the lone
    opponent ``NumOfAttacksBase`` times, and MMOOOMMMM! breathes its rank-two
    damage and slow while healing Smolder for ``MomHealCalc`` as he stands in
    it. Dragon Practice stacks accrue outside the encounter.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Smolder.json",
        "data/raw/16.17.1/communitydragon/champions/901.json",
        "data/raw/16.17.1/communitydragon/champions/smolder.bin.json",
    )

    _Q_TIMES_MS = (0, 4000)
    _W_AT_MS = 700
    _W_SLOW_MS = 1500
    _E_AT_MS = 1400
    _E_HITS = 5
    _E_DURATION_MS = 1250
    _R_AT_MS = 3000
    _R_MOM_DELAY_MS = 1000
    _R_SLOW_MS = 2000
    _ATTACKS_FROM_MS = 2800

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Smolder's breath, sneeze, flight, and mom rotation.

        :param context: Role-bound Smolder and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        bonus_ad = snapshot.bonus_attack_damage
        ap = snapshot.ability_power
        q_damage = Decimal(100) + Decimal("1.3") * bonus_ad
        events: list[ActionEvent] = [
            action(
                f"SMOLDER_Q_SUPER_SCORCHER_BREATH_{index}",
                at_ms=at_ms,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        q_damage,
                        DamageType.PHYSICAL,
                        source_heal_ratio=Decimal("0.5") * snapshot.life_steal,
                    ),
                ),
            )
            for index, at_ms in enumerate(self._Q_TIMES_MS, start=1)
            if at_ms <= context.duration_ms
        ]
        events.append(
            action(
                "SMOLDER_W_ACHOOO",
                at_ms=self._W_AT_MS,
                sequence=base + 10,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(100) + Decimal("0.6") * bonus_ad,
                        DamageType.PHYSICAL,
                    ),
                    damage(
                        context.opponent_entity,
                        self.rank_value("SmolderW", "ExplosionBaseDamage", context, Decimal(110))
                        + Decimal("0.5") * bonus_ad
                        + Decimal("0.8") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=self._W_SLOW_MS,
                        magnitude=Decimal("0.35"),
                    ),
                ),
            )
        )
        for index in range(self._E_HITS):
            events.append(
                action(
                    f"SMOLDER_E_FLAP_BOMBARD_{index + 1}",
                    at_ms=self._E_AT_MS + index * self._E_DURATION_MS // self._E_HITS,
                    sequence=base + 20 + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            self.rank_value("SmolderE", "BaseDamage", context, Decimal(10))
                            + Decimal("0.3") * snapshot.attack_damage,
                            DamageType.PHYSICAL,
                        ),
                    ),
                )
            )
        mom_ms = self._R_AT_MS + self._R_MOM_DELAY_MS
        if mom_ms <= context.duration_ms:
            events.append(
                action(
                    "SMOLDER_R_MMOOOMMMM",
                    at_ms=mom_ms,
                    sequence=base + 30,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            self.rank_value("SmolderR", "BaseDamage", context, Decimal(250))
                            + bonus_ad
                            + ap,
                            DamageType.MAGIC,
                        ),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=self._R_SLOW_MS,
                            magnitude=Decimal("0.40"),
                        ),
                        healing(
                            context.self_entity,
                            self.rank_value("SmolderR", "MomHeal", context, Decimal(135))
                            + Decimal("0.5") * bonus_ad
                            + Decimal("0.75") * ap,
                        ),
                    ),
                )
            )
        interval = self._attack_interval_ms(snapshot.attack_speed)
        for index, at_ms in enumerate(
            range(self._ATTACKS_FROM_MS, context.duration_ms + 1, interval)
        ):
            events.append(
                action(
                    f"SMOLDER_BASIC_ATTACK_{index}",
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
            () if snapshot.level == 13 else (f"SMOLDER_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "smolder_q5_w5_e1_r2_breath_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "SMOLDER_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "SMOLDER_PASSIVE_DRAGON_PRACTICE_STACKS_OUTSIDE_SCENARIO",
                "SMOLDER_R_SELF_HEAL_ASSUMES_STANDING_IN_BREATH",
                "SMOLDER_R_SWEETSPOT_NOT_ASSUMED",
                "SMOLDER_Q_CRITICAL_STRIKE_NOT_MODELED",
                "SMOLDER_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Report that Smolder's rotation applies no hard control.

        :param context: Role-bound Smolder and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "smolder_no_hard_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
