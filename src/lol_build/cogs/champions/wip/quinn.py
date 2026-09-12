"""Quinn combat Cog backed by locked 16.17.1 champion sources."""

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


class QuinnCog(ChampionCog):
    """Model Quinn's Q5/E5/W1/R2 level-thirteen ranged duel fixture.

    Harrier marks the opponent at the start and again through Blinding
    Assault and Vault; the first attack against each mark deals Harrier's
    level-scaled ``BonusDamage`` (plus ``ADRatio`` of bonus attack damage).
    Blinding Assault and Vault land their rank-five damage, Vault slowing.
    Vault's knockback interruption, Heightened Senses' attack speed, and
    Behind Enemy Lines' Skystrike are excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Quinn.json",
        "data/raw/16.17.1/communitydragon/champions/133.json",
        "data/raw/16.17.1/communitydragon/champions/quinn.bin.json",
    )

    _Q_AT_MS = 900
    _E_AT_MS = 2600
    _E_SLOW_MS = 1500
    _FIRST_ATTACK_MS = 200

    def _harrier(self, context: ParticipantContext) -> Decimal:
        """Evaluate Harrier's level-scaled bonus physical damage.

        :param context: Role-bound Quinn snapshot.
        :return: Bonus damage of one Harrier-consuming attack.
        """
        level = Decimal(context.snapshot.level - 1)
        return (
            Decimal(15)
            + Decimal(105) * level / Decimal(17)
            + Decimal("0.4") * context.snapshot.bonus_attack_damage
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Quinn's harrier, blinding-assault, and vault rotation.

        :param context: Role-bound Quinn and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        bonus_ad = snapshot.bonus_attack_damage
        events: list[ActionEvent] = [
            action(
                "QUINN_Q_BLINDING_ASSAULT",
                at_ms=self._Q_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("QuinnQ", "BaseDamage", context, Decimal(205))
                        + bonus_ad
                        + Decimal("0.5") * snapshot.ability_power,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
            action(
                "QUINN_E_VAULT",
                at_ms=self._E_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("QuinnE", "BaseDamage", context, Decimal(140))
                        + self.rank_value("QuinnW", "MovespeedAmount", context, Decimal("0.2"))
                        * bonus_ad,
                        DamageType.PHYSICAL,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=self._E_SLOW_MS,
                        magnitude=Decimal("0.50"),
                    ),
                ),
            ),
        ]
        harrier = self._harrier(context)
        marks = [0, self._Q_AT_MS, self._E_AT_MS]
        interval = self._attack_interval_ms(snapshot.attack_speed)
        for index, at_ms in enumerate(
            range(self._FIRST_ATTACK_MS, context.duration_ms + 1, interval)
        ):
            consumes = bool(marks) and at_ms > marks[0]
            if consumes:
                while marks and at_ms > marks[0]:
                    marks.pop(0)
            outputs = [damage(context.opponent_entity, snapshot.attack_damage, DamageType.PHYSICAL)]
            if consumes:
                outputs.append(damage(context.opponent_entity, harrier, DamageType.PHYSICAL))
            events.append(
                action(
                    f"QUINN_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 700 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
        level_blockers = (
            () if snapshot.level == 13 else (f"QUINN_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "quinn_q5_e5_w1_r2_harrier_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "QUINN_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "QUINN_E_KNOCKBACK_INTERRUPT_DURATION_NOT_IN_LOCKED_DATA",
                "QUINN_W_ATTACK_SPEED_NOT_APPLIED_TO_CADENCE",
                "QUINN_R_SKYSTRIKE_NOT_MODELED",
                "QUINN_Q_NEARSIGHT_NOT_MODELED",
                "QUINN_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Report that Quinn's modeled rotation applies no hard control.

        :param context: Role-bound Quinn and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "quinn_no_hard_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
