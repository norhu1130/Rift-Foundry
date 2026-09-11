"""Qiyana combat Cog backed by locked 16.17.1 champion sources."""

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


class QiyanaCog(ChampionCog):
    """Model a terrain-less Qiyana's Q5/E5/W1/R2 level-thirteen duel fixture.

    Every element Terrashape grants comes from nearby grass, water, or wall,
    and Supreme Display of Talent only damages and stuns where its shockwave
    detonates terrain; the encounter has no terrain, so both are excluded and
    Qiyana fights unenchanted. Audacity dashes in for its rank-five damage,
    Royal Privilege adds its level-scaled ``FinalDamage`` to her first hit
    (its internal cooldown outlasts the encounter), and Edge of Ixtal lands its
    unenchanted ``VanillaDamage``.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Qiyana.json",
        "data/raw/16.17.1/communitydragon/champions/246.json",
        "data/raw/16.17.1/communitydragon/champions/qiyana.bin.json",
    )

    _E_AT_MS = 0
    _Q_AT_MS = 400
    _ATTACKS_FROM_MS = 700

    def _royal_privilege(self, context: ParticipantContext) -> Decimal:
        """Evaluate Royal Privilege's first-hit bonus damage.

        :param context: Role-bound Qiyana snapshot.
        :return: Level-curve damage plus bonus attack damage and AP ratios.
        """
        curve = self._level_breakpoint_value(
            Decimal(15), Decimal(4), ((6, Decimal(4)), (11, Decimal(4))), context.snapshot.level
        )
        return (
            curve
            + Decimal("0.25") * context.snapshot.bonus_attack_damage
            + Decimal("0.3") * context.snapshot.ability_power
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build unenchanted Qiyana's audacity and edge-of-ixtal rotation.

        :param context: Role-bound Qiyana and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        bonus_ad = snapshot.bonus_attack_damage
        events: list[ActionEvent] = [
            action(
                "QIYANA_E_AUDACITY",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(210) + Decimal("0.5") * bonus_ad,
                        DamageType.PHYSICAL,
                    ),
                    damage(
                        context.opponent_entity, self._royal_privilege(context), DamageType.PHYSICAL
                    ),
                ),
            ),
            action(
                "QIYANA_Q_EDGE_OF_IXTAL",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(200) + Decimal("0.9") * bonus_ad,
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
                    f"QIYANA_BASIC_ATTACK_{index}",
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
            () if snapshot.level == 13 else (f"QIYANA_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "qiyana_q5_e5_w1_r2_terrainless_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "QIYANA_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "QIYANA_W_ELEMENTS_REQUIRE_TERRAIN",
                "QIYANA_R_DAMAGE_AND_STUN_REQUIRE_TERRAIN",
                "QIYANA_PASSIVE_LEVEL_CURVE_CONVENTION_ASSUMED",
                "QIYANA_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Report that terrain-less Qiyana applies no hard control.

        :param context: Role-bound Qiyana and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "qiyana_no_hard_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
