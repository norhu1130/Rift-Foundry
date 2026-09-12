"""Samira combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent


class SamiraCog(ChampionCog):
    """Model Samira's Q5/E5/W1 level-thirteen ranged duel fixture.

    Flair fires for its rank-five ``DamageCalc`` and applies Samira's life
    steal at its locked ``LifestealMod``. Wild Rush dashes through for its
    rank-five ``DashDamage``, and Blade Whirl slashes twice for its rank-one
    damage. Inferno Trigger's shot count is absent from the locked data values
    and its Style-grade gate is a combo resource this fixture does not track,
    so it is excluded, as is the melee-range passive magic damage.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Samira.json",
        "data/raw/16.17.1/communitydragon/champions/360.json",
        "data/raw/16.17.1/communitydragon/champions/samira.bin.json",
    )

    _Q_TIMES_MS = (300, 2500, 4700)
    _E_AT_MS = 1200
    _W_AT_MS = 1700
    _W_SLASH_MS = 750
    _FIRST_ATTACK_MS = 0

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Samira's flair, wild-rush, and blade-whirl rotation.

        :param context: Role-bound Samira and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        bonus_ad = snapshot.bonus_attack_damage
        events: list[ActionEvent] = [
            action(
                f"SAMIRA_Q_FLAIR_{index}",
                at_ms=at_ms,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(20) + Decimal("1.1") * snapshot.attack_damage,
                        DamageType.PHYSICAL,
                        source_heal_ratio=snapshot.life_steal,
                    ),
                ),
            )
            for index, at_ms in enumerate(self._Q_TIMES_MS, start=1)
            if at_ms <= context.duration_ms
        ]
        events.append(
            action(
                "SAMIRA_E_WILD_RUSH",
                at_ms=self._E_AT_MS,
                sequence=base + 10,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("SamiraE", "BaseDamage", context, Decimal(90))
                        + Decimal("0.2") * bonus_ad,
                        DamageType.MAGIC,
                    ),
                ),
            )
        )
        for index in range(2):
            events.append(
                action(
                    f"SAMIRA_W_BLADE_WHIRL_{index + 1}",
                    at_ms=self._W_AT_MS + index * self._W_SLASH_MS,
                    sequence=base + 20 + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal(20) + Decimal("0.5") * bonus_ad,
                            DamageType.PHYSICAL,
                        ),
                    ),
                )
            )
        interval = self._attack_interval_ms(snapshot.attack_speed)
        for index, at_ms in enumerate(
            range(self._FIRST_ATTACK_MS, context.duration_ms + 1, interval)
        ):
            events.append(
                action(
                    f"SAMIRA_BASIC_ATTACK_{index}",
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
            () if snapshot.level == 13 else (f"SAMIRA_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "samira_q5_e5_w1_ranged_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "SAMIRA_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "SAMIRA_R_SHOT_COUNT_ABSENT_FROM_LOCKED_DATA_VALUES",
                "SAMIRA_PASSIVE_STYLE_COMBO_NOT_TRACKED",
                "SAMIRA_PASSIVE_MELEE_MAGIC_DAMAGE_NOT_MODELED",
                "SAMIRA_E_ATTACK_SPEED_NOT_APPLIED_TO_CADENCE",
                "SAMIRA_W_MISSILE_DESTRUCTION_NOT_MODELED",
                "SAMIRA_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Report that Samira's modeled rotation applies no hard control.

        :param context: Role-bound Samira and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "samira_no_hard_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
