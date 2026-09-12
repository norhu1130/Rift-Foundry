"""Zaahen combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent, DamageModifierWindow


class ZaahenCog(ChampionCog):
    """Model Zaahen's Q5/E5/W1/R2 level-thirteen duel fixture.

    Aureate Rush dashes in for its rank-five damage plus ``PercentHPDamage`` of
    the target's maximum health, Dreaded Return stabs and pulls for its
    rank-one hits, and The Darkin Glaive makes the next attack slash twice for
    ``InitialDamage`` and ``SecondHitDamage``. Grim Deliverance lands its
    rank-two ``DamageEndCalc`` with its ``ArmorPen`` and heals Zaahen for its
    locked ``HealPercent`` of the damage it deals, halving the damage he takes
    while he rises. The Darkin Glaive's ``HealPercent`` has no locked formula
    naming what it is a percentage of, so that heal is excluded rather than
    guessed, as are Determination stacks and revival.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Zaahen.json",
        "data/raw/16.17.1/communitydragon/champions/904.json",
        "data/raw/16.17.1/communitydragon/champions/zaahen.bin.json",
    )

    _E_AT_MS = 0
    _W_AT_MS = 500
    _W_PULL_MS = 250
    _Q_AT_MS = 1000
    _R_AT_MS = 2200
    _R_RISE_MS = 750
    _ATTACKS_FROM_MS = 1600

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Zaahen's rush, return, glaive, and deliverance rotation.

        :param context: Role-bound Zaahen and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        bonus_ad = snapshot.bonus_attack_damage
        events: list[ActionEvent] = [
            action(
                "ZAAHEN_E_AUREATE_RUSH",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("ZaahenE", "Damage_Base", context, Decimal(120))
                        + Decimal("0.5") * bonus_ad
                        + self.rank_value("ZaahenE", "PercentHPDamage", context, Decimal("0.06"))
                        * context.opponent_snapshot.max_hp,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
            action(
                "ZAAHEN_W_DREADED_RETURN",
                at_ms=self._W_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("ZaahenW", "InitialBaseDamage", context, Decimal(40))
                        + Decimal("0.5") * bonus_ad,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
            action(
                "ZAAHEN_W_DREADED_RETURN_PULL",
                origin_event_id="ZAAHEN_W_DREADED_RETURN",
                at_ms=self._W_AT_MS + self._W_PULL_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("ZaahenW", "SecondaryBaseDamage", context, Decimal(30))
                        + Decimal("0.3") * bonus_ad,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
            action(
                "ZAAHEN_Q_DARKIN_GLAIVE",
                at_ms=self._Q_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(context.opponent_entity, snapshot.attack_damage, DamageType.PHYSICAL),
                    damage(
                        context.opponent_entity,
                        self.rank_value("ZaahenQ", "Q1BaseDamage", context, Decimal(75))
                        + self.rank_value("ZaahenQ", "QCoeff", context, Decimal("0.4")) * bonus_ad,
                        DamageType.PHYSICAL,
                    ),
                    damage(
                        context.opponent_entity,
                        self.rank_value("ZaahenQ", "Q2BaseDamage", context, Decimal(125))
                        + self.rank_value("ZaahenQ", "QCoeff", context, Decimal("0.4")) * bonus_ad,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
        ]
        strike_ms = self._R_AT_MS + self._R_RISE_MS
        if strike_ms <= context.duration_ms:
            events.append(
                action(
                    "ZAAHEN_R_GRIM_DELIVERANCE",
                    at_ms=strike_ms,
                    sequence=base + 4,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            self.rank_value("ZaahenR", "EndDamage", context, Decimal(400))
                            + Decimal(2) * bonus_ad,
                            DamageType.PHYSICAL,
                            percent_resistance_penetration=self.rank_value(
                                "ZaahenR", "ArmorPen", context, Decimal("0.2")
                            ),
                            source_heal_ratio=Decimal("0.33"),
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
                    f"ZAAHEN_BASIC_ATTACK_{index}",
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
            () if snapshot.level == 13 else (f"ZAAHEN_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "zaahen_q5_e5_w1_r2_rush_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "ZAAHEN_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "ZAAHEN_Q_HEAL_PERCENT_BASIS_NOT_IN_LOCKED_DATA",
                "ZAAHEN_Q_RECAST_KNOCKUP_NOT_MODELED",
                "ZAAHEN_W_PULL_DISPLACEMENT_NOT_MODELED",
                "ZAAHEN_E_SWEET_SPOT_NOT_ASSUMED",
                "ZAAHEN_PASSIVE_DETERMINATION_STACKS_AND_REVIVE_NOT_MODELED",
                "ZAAHEN_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Halve incoming damage while Grim Deliverance rises.

        :param context: Role-bound Zaahen and opponent snapshots.
        :return: Reaction plan with Grim Deliverance's damage reduction window.
        """
        end_ms = min(self._R_AT_MS + self._R_RISE_MS, context.duration_ms)
        windows = (
            (
                DamageModifierWindow(
                    "zaahen_r_grim_deliverance_damage_reduction",
                    self._R_AT_MS,
                    end_ms,
                    context.self_entity,
                    (DamageType.PHYSICAL, DamageType.MAGIC, DamageType.TRUE),
                    Decimal("0.5"),
                ),
            )
            if end_ms > self._R_AT_MS
            else ()
        )
        return ReactionPlan(
            "zaahen_r_damage_reduction_reaction_v1",
            damage_windows=windows,
            blockers=(*self.verification_blockers(),),
        )
