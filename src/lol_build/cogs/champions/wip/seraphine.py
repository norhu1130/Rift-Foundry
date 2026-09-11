"""Seraphine combat Cog backed by locked 16.17.1 champion sources."""

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


class SeraphineCog(ChampionCog):
    """Model Seraphine's Q5/E5/W1/R2 level-thirteen duel fixture.

    High Note and Beat Drop land their rank-five damage, Beat Drop slowing by
    ``SlowValue``, and Encore lands its rank-two damage. Surround Sound grants
    Seraphine its rank-one shield; its heal only triggers while already
    shielded and scales per nearby ally, so it is excluded, as are the
    allied-note empowered attacks and the third-spell echo.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Seraphine.json",
        "data/raw/16.17.1/communitydragon/champions/147.json",
        "data/raw/16.17.1/communitydragon/champions/seraphine.bin.json",
    )

    _E_AT_MS = 0
    _E_SLOW_MS = 1500
    _Q_AT_MS = 600
    _W_AT_MS = 1100
    _W_SHIELD_MS = 2500
    _R_AT_MS = 1700
    _ATTACKS_FROM_MS = 2300

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Seraphine's beat-drop, high-note, shield, and encore rotation.

        :param context: Role-bound Seraphine and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        ap = snapshot.ability_power
        events: list[ActionEvent] = [
            action(
                "SERAPHINE_E_BEAT_DROP",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(190) + Decimal("0.5") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=self._E_SLOW_MS,
                        magnitude=Decimal("0.99"),
                    ),
                ),
            ),
            action(
                "SERAPHINE_Q_HIGH_NOTE",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(160) + Decimal("0.4") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "SERAPHINE_W_SURROUND_SOUND",
                at_ms=self._W_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(
                        context.self_entity,
                        Decimal(60) + Decimal("0.2") * ap,
                        duration_ms=self._W_SHIELD_MS,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "SERAPHINE_R_ENCORE",
                at_ms=self._R_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(150) + Decimal("0.4") * ap,
                        DamageType.MAGIC,
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
                    f"SERAPHINE_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 700 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(context.opponent_entity, snapshot.attack_damage, DamageType.MAGIC),
                    ),
                )
            )
        level_blockers = (
            () if snapshot.level == 13 else (f"SERAPHINE_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "seraphine_q5_e5_w1_r2_beat_drop_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "SERAPHINE_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "SERAPHINE_W_HEAL_REQUIRES_EXISTING_SHIELD_AND_ALLIES",
                "SERAPHINE_R_CHARM_DURATION_NOT_IN_LOCKED_DATA",
                "SERAPHINE_Q_LOW_HEALTH_DAMAGE_AMPLIFICATION_NOT_MODELED",
                "SERAPHINE_PASSIVE_ECHO_AND_ALLY_NOTES_NOT_MODELED",
                "SERAPHINE_BASIC_ATTACK_MAGIC_DAMAGE_ASSUMED",
                "SERAPHINE_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Report that Seraphine's modeled rotation applies no hard control.

        :param context: Role-bound Seraphine and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "seraphine_no_hard_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
