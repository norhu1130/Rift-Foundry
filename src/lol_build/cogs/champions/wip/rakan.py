"""Rakan combat Cog backed by locked 16.17.1 champion sources."""

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


class RakanCog(ChampionCog):
    """Model Rakan's W5/Q5/R2/E1 level-thirteen engage fixture.

    Fey Feathers opens with its charged passive shield. Grand Entrance dashes
    in for its rank-five damage and knock-up, The Quickness charms on touch
    for its rank-two damage, and Gleaming Quill strikes the opponent, arming
    its level-scaled ``TotalHeal`` on Rakan after ``HealDelay``. Battle Dance
    targets an allied champion, which a duel has none of.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Rakan.json",
        "data/raw/16.17.1/communitydragon/champions/497.json",
        "data/raw/16.17.1/communitydragon/champions/rakan.bin.json",
    )

    _W_LANDING_MS = 300
    _W_KNOCKUP_MS = 1000
    _R_TOUCH_MS = 1300
    _R_CHARM_MS = 1250
    _Q_AT_MS = 2600
    _Q_HEAL_DELAY_MS = 3000
    _ATTACKS_FROM_MS = 1900

    @staticmethod
    def _interpolated(level: int, start: Decimal, end: Decimal) -> Decimal:
        """Evaluate a locked level interpolation from level 1 to 18.

        :param level: Champion level.
        :param start: Value at level 1.
        :param end: Value at level 18.
        :return: Linearly interpolated value.
        """
        return start + (end - start) * Decimal(level - 1) / Decimal(17)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Rakan's feather shield, dash, charm, and quill rotation.

        :param context: Role-bound Rakan and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        ap = snapshot.ability_power
        feather_shield = (
            self._interpolated(snapshot.level, Decimal(30), Decimal(225)) + Decimal("0.95") * ap
        )
        quill_heal = (
            self._interpolated(snapshot.level, Decimal(40), Decimal(210)) + Decimal("0.55") * ap
        )
        events: list[ActionEvent] = [
            action(
                "RAKAN_PASSIVE_FEY_FEATHERS",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(shielding(context.self_entity, feather_shield),),
                requires_living_opponent=False,
            ),
            action(
                "RAKAN_W_GRAND_ENTRANCE",
                at_ms=self._W_LANDING_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(270) + Decimal("0.8") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity, "AIRBORNE", duration_ms=self._W_KNOCKUP_MS
                    ),
                ),
            ),
            action(
                "RAKAN_R_THE_QUICKNESS",
                at_ms=self._R_TOUCH_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(200) + Decimal("0.5") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "CHARM", duration_ms=self._R_CHARM_MS),
                ),
            ),
            action(
                "RAKAN_Q_GLEAMING_QUILL",
                at_ms=self._Q_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(250) + Decimal("0.7") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
        ]
        if context.duration_ms >= self._Q_AT_MS + self._Q_HEAL_DELAY_MS:
            events.append(
                action(
                    "RAKAN_Q_GLEAMING_QUILL_HEAL",
                    at_ms=self._Q_AT_MS + self._Q_HEAL_DELAY_MS,
                    sequence=base + 4,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(healing(context.self_entity, quill_heal),),
                    requires_living_opponent=False,
                )
            )
        interval = self._attack_interval_ms(snapshot.attack_speed)
        for index, at_ms in enumerate(
            range(self._ATTACKS_FROM_MS, context.duration_ms + 1, interval)
        ):
            events.append(
                action(
                    f"RAKAN_BASIC_ATTACK_{index}",
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
            () if snapshot.level == 13 else (f"RAKAN_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "rakan_w5_q5_r2_e1_engage_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "RAKAN_LEVEL13_W5_Q5_R2_E1_POLICY_UNVERIFIED",
                "RAKAN_E_BATTLE_DANCE_REQUIRES_ALLY",
                "RAKAN_Q_HEAL_EARLY_ALLY_TOUCH_NOT_MODELED",
                "RAKAN_PASSIVE_SHIELD_DURATION_NOT_IN_LOCKED_DATA",
                "RAKAN_BASIC_ATTACK_MAGIC_DAMAGE_ASSUMED",
                "RAKAN_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the dash knock-up and ultimate charm as control windows.

        :param context: Role-bound Rakan and opponent snapshots.
        :return: Deterministic control windows caused by Rakan's rotation.
        """
        channels = (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT)
        return ReactionPlan(
            "rakan_w_r_control_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "rakan_w_grand_entrance_knockup",
                    self._W_LANDING_MS,
                    min(self._W_LANDING_MS + self._W_KNOCKUP_MS, context.duration_ms),
                    channels,
                    "RAKAN_W_GRAND_ENTRANCE",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "rakan_r_the_quickness_charm",
                    self._R_TOUCH_MS,
                    min(self._R_TOUCH_MS + self._R_CHARM_MS, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY),
                    "RAKAN_R_THE_QUICKNESS",
                    True,
                    ControlType.CHARM,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
