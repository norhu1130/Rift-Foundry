"""Zeri combat Cog backed by locked 16.17.1 champion sources."""

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


class ZeriCog(ChampionCog):
    """Model Zeri's Q5/E5/W1/R2 level-thirteen burst-fire fixture.

    Burst Fire replaces Zeri's attacks: it is treated as an attack, fires on
    her attack timer with attack speed capped at ``AttackSpeedCap``, and deals
    its rank-five ``ActiveDamageThatCanCrit``. Spark Surge energizes Burst Fire
    for ``BuffDuration`` with its ``BonusDamageTotal`` magic on-hit, Ultrashock
    Laser slows and damages, and Lightning Crash's nova deals its
    ``TotalActiveDamage`` and overcharges Burst Fire with ``TotalBonusDamage``
    for ``RDuration``. Living Battery's charged shot and the wall laser need
    movement and terrain this fixture does not track.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Zeri.json",
        "data/raw/16.17.1/communitydragon/champions/221.json",
        "data/raw/16.17.1/communitydragon/champions/zeri.bin.json",
    )

    _ATTACK_SPEED_CAP = Decimal("1.5")
    _E_AT_MS = 0
    _E_DURATION_MS = 5000
    _W_AT_MS = 300
    _W_SLOW_MS = 2000
    _R_AT_MS = 1500
    _R_DURATION_MS = 5000
    _FIRST_BURST_MS = 100

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Zeri's energized, overcharged burst-fire rotation.

        :param context: Role-bound Zeri and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        ap = snapshot.ability_power
        burst = Decimal(38) + Decimal("1.1") * snapshot.attack_damage
        energized = Decimal(30) + Decimal("0.2") * ap
        overcharged = Decimal(10) + Decimal("0.15") * ap
        events: list[ActionEvent] = [
            action(
                "ZERI_W_ULTRASHOCK_LASER",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(30) + Decimal("1.2") * snapshot.attack_damage + Decimal("0.5") * ap,
                        DamageType.PHYSICAL,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=self._W_SLOW_MS,
                        magnitude=Decimal("0.30"),
                    ),
                ),
            ),
            action(
                "ZERI_R_LIGHTNING_CRASH",
                at_ms=self._R_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(250)
                        + Decimal("1.1") * ap
                        + Decimal("0.6") * snapshot.bonus_attack_damage,
                        DamageType.MAGIC,
                    ),
                ),
            ),
        ]
        interval = self._attack_interval_ms(min(snapshot.attack_speed, self._ATTACK_SPEED_CAP))
        for index, at_ms in enumerate(
            range(self._FIRST_BURST_MS, context.duration_ms + 1, interval)
        ):
            outputs = [damage(context.opponent_entity, burst, DamageType.PHYSICAL)]
            if self._E_AT_MS <= at_ms < self._E_AT_MS + self._E_DURATION_MS:
                outputs.append(damage(context.opponent_entity, energized, DamageType.MAGIC))
            if self._R_AT_MS <= at_ms < self._R_AT_MS + self._R_DURATION_MS:
                outputs.append(damage(context.opponent_entity, overcharged, DamageType.MAGIC))
            events.append(
                action(
                    f"ZERI_Q_BURST_FIRE_{index}",
                    at_ms=at_ms,
                    sequence=base + 700 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
        level_blockers = (
            () if snapshot.level == 13 else (f"ZERI_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "zeri_q5_e5_w1_r2_burst_fire_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "ZERI_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "ZERI_PASSIVE_CHARGED_SHOT_REQUIRES_MOVEMENT_TRACE",
                "ZERI_W_WALL_LASER_REQUIRES_TERRAIN",
                "ZERI_E_PIERCE_REQUIRES_MORE_TARGETS",
                "ZERI_R_ATTACK_SPEED_AND_CHAIN_LIGHTNING_NOT_MODELED",
                "ZERI_CRITICAL_STRIKE_NOT_MODELED",
                "ZERI_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Report that Zeri's rotation applies no hard control.

        :param context: Role-bound Zeri and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "zeri_no_hard_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
