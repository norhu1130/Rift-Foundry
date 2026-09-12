"""Rek'Sai combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent, MissingHealthDamageOutput


class RekSaiCog(ChampionCog):
    """Model an unburrowed Rek'Sai's Q5/E5/W1/R2 level-thirteen duel fixture.

    Queen's Wrath empowers the next three attacks with ``UnburrowedADRatio``
    of attack damage. Every attack and ability hit generates
    ``FuryFromAttacks`` Fury, so the fourth hit fills the bar and Furious Bite
    lands at max Fury as true damage scaled by ``EmpoweredRatio``. Void Rush
    finishes with its rank-two damage plus ``PercentMissingHealthDamage`` of
    the target's missing health. Fury spent on the bite is not available to
    Fury of the Xer'Sai's burrowed heal, which is therefore excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/RekSai.json",
        "data/raw/16.17.1/communitydragon/champions/421.json",
        "data/raw/16.17.1/communitydragon/champions/reksai.bin.json",
    )

    _FIRST_ATTACK_MS = 200
    _Q_EMPOWERED_ATTACKS = 3
    _FURY_HITS_FOR_MAX = 4
    _R_AT_MS = 5000

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Rek'Sai's queen's-wrath, max-fury bite, and void-rush rotation.

        :param context: Role-bound Rek'Sai and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        bonus_ad = snapshot.bonus_attack_damage
        interval = self._attack_interval_ms(snapshot.attack_speed)
        attack_times = tuple(range(self._FIRST_ATTACK_MS, context.duration_ms + 1, interval))
        events: list[ActionEvent] = []
        for index, at_ms in enumerate(attack_times):
            outputs = [damage(context.opponent_entity, snapshot.attack_damage, DamageType.PHYSICAL)]
            if index < self._Q_EMPOWERED_ATTACKS:
                outputs.append(
                    damage(
                        context.opponent_entity,
                        self.rank_value("RekSaiQ", "UnburrowedBaseDamage", context, Decimal(25))
                        + Decimal("0.45") * snapshot.attack_damage,
                        DamageType.PHYSICAL,
                    )
                )
            events.append(
                action(
                    f"REKSAI_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 700 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
        if len(attack_times) >= self._FURY_HITS_FOR_MAX:
            events.append(
                action(
                    "REKSAI_E_FURIOUS_BITE_MAX_FURY",
                    at_ms=attack_times[self._FURY_HITS_FOR_MAX - 1] + 100,
                    sequence=base,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal("1.2") * (Decimal(170) + Decimal("0.6") * bonus_ad),
                            DamageType.TRUE,
                        ),
                    ),
                )
            )
        if context.duration_ms >= self._R_AT_MS:
            events.append(
                action(
                    "REKSAI_R_VOID_RUSH",
                    at_ms=self._R_AT_MS,
                    sequence=base + 1,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        MissingHealthDamageOutput(
                            context.opponent_entity,
                            self.rank_value("RekSaiRWrapper", "RBaseDamage", context, Decimal(300))
                            + bonus_ad,
                            Decimal("0.30"),
                            DamageType.PHYSICAL,
                        ),
                    ),
                )
            )
        level_blockers = (
            () if snapshot.level == 13 else (f"REKSAI_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "reksai_q5_e5_w1_r2_unburrowed_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "REKSAI_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "REKSAI_PASSIVE_BURROWED_HEAL_FURY_SPENT_ON_EMPOWERED_BITE",
                "REKSAI_W_UNBURROW_DAMAGE_AND_KNOCKUP_NOT_IN_LOCKED_DATA_VALUES",
                "REKSAI_Q_ATTACK_SPEED_NOT_APPLIED_TO_CADENCE",
                "REKSAI_R_UNTARGETABLE_LUNGE_NOT_MODELED",
                "REKSAI_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Report that unburrowed Rek'Sai applies no hard control.

        :param context: Role-bound Rek'Sai and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "reksai_no_hard_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
