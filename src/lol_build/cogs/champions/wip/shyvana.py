"""Shyvana combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class ShyvanaCog(ChampionCog):
    """Model Shyvana's human-form W5/Q5/E1 level-thirteen duel fixture.

    Dragon's Descent needs a full Fury bar the encounter does not start with,
    so Shyvana stays in human form and the dragon-only Inferno Aegis heal is
    excluded. Inferno Aegis grants its rank-five flat shield and detonates for
    its ``Damage``; Emberstrike empowers the next attack with ``Calc_Damage``;
    and Molten Burst deals its rank-one ``Damage`` plus ``MaxHealthDamage`` of
    the target's maximum health and slows.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Shyvana.json",
        "data/raw/16.17.1/communitydragon/champions/102.json",
        "data/raw/16.17.1/communitydragon/champions/shyvana.bin.json",
    )

    _W_AT_MS = 0
    _W_SHIELD_MS = 2500
    _W_DETONATION_MS = 500
    _E_AT_MS = 700
    _E_SLOW_MS = 2000
    _Q_AT_MS = 1200
    _ATTACKS_FROM_MS = 1700

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Shyvana's aegis, molten-burst, and emberstrike rotation.

        :param context: Role-bound Shyvana and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        ap = snapshot.ability_power
        events: list[ActionEvent] = [
            action(
                "SHYVANA_W_INFERNO_AEGIS",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(
                        context.self_entity,
                        self.rank_value("ShyvanaW", "Shield", context, Decimal(140)),
                        duration_ms=self._W_SHIELD_MS,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "SHYVANA_W_INFERNO_AEGIS_DETONATION",
                at_ms=self._W_AT_MS + self._W_DETONATION_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("ShyvanaW", "BaseDamage", context, Decimal(160))
                        + Decimal("0.65") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "SHYVANA_E_MOLTEN_BURST",
                at_ms=self._E_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(50)
                        + self.rank_value("ShyvanaE", "DamageAPRatio", context, Decimal("0.6")) * ap
                        + Decimal("0.05") * context.opponent_snapshot.max_hp,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=self._E_SLOW_MS,
                        magnitude=Decimal("0.30"),
                    ),
                ),
            ),
            action(
                "SHYVANA_Q_EMBERSTRIKE",
                at_ms=self._Q_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("ShyvanaQ", "Base_Damage", context, Decimal(30))
                        + Decimal("1.1") * snapshot.attack_damage
                        + Decimal("0.3") * ap,
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
                    f"SHYVANA_BASIC_ATTACK_{index}",
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
            () if snapshot.level == 13 else (f"SHYVANA_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "shyvana_w5_q5_e1_human_form_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "SHYVANA_LEVEL13_W5_Q5_E1_R2_POLICY_UNVERIFIED",
                "SHYVANA_R_DRAGON_FORM_REQUIRES_FURY_NOT_TRACKED",
                "SHYVANA_W_HEAL_IS_DRAGON_FORM_ONLY",
                "SHYVANA_W_SHIELD_MAX_HEALTH_RATIO_ABSENT_FROM_DATA_VALUES",
                "SHYVANA_Q_RECAST_AND_TARGET_HEALTH_DAMAGE_NOT_MODELED",
                "SHYVANA_E_GROUND_BURN_NOT_MODELED",
                "SHYVANA_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Report that human-form Shyvana applies no hard control.

        :param context: Role-bound Shyvana and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "shyvana_no_hard_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
