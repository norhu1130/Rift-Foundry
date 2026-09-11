"""Skarner combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class SkarnerCog(ChampionCog):
    """Model Skarner's Q5/W5/E1/R2 level-thirteen duel fixture.

    Seismic Bastion shields Skarner for ``InitialShield`` of his maximum health
    and its shockwave damages and slows. Impale suppresses for ``Duration``
    with its rank-two damage. Shattered Earth empowers every attack for
    ``RockHoldDuration`` with its ``AbilityDamage`` (rank-five base plus bonus
    attack damage and bonus health ratios). Each attack and Impale applies a
    Quaking stack; the third deals the level-scaled ``PercentHealthDamage`` of
    the target's maximum health over ``Duration`` in ``TickFrequency`` ticks.
    Ixtal's Impact needs a wall to stun against, and the thrown boulder is not
    used, so both are excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Skarner.json",
        "data/raw/16.17.1/communitydragon/champions/72.json",
        "data/raw/16.17.1/communitydragon/champions/skarner.bin.json",
    )

    _W_AT_MS = 0
    _W_SHIELD_MS = 2500
    _W_SLOW_MS = 1000
    _R_AT_MS = 300
    _R_SUPPRESS_MS = 1500
    _Q_AT_MS = 1900
    _Q_HOLD_MS = 5000
    _FIRST_ATTACK_MS = 2000
    _QUAKE_STACKS = 3
    _QUAKE_DURATION_MS = 4000
    _QUAKE_TICK_MS = 500

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Skarner's bastion, impale, empowered attacks, and quaking burn.

        :param context: Role-bound Skarner and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        ap = snapshot.ability_power
        rock = (
            Decimal(50)
            + Decimal("0.9") * snapshot.bonus_attack_damage
            + Decimal("0.03") * snapshot.bonus_health
        )
        events: list[ActionEvent] = [
            action(
                "SKARNER_W_SEISMIC_BASTION",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(
                        context.self_entity,
                        Decimal("0.08") * snapshot.max_hp,
                        duration_ms=self._W_SHIELD_MS,
                    ),
                    damage(
                        context.opponent_entity,
                        Decimal(130) + Decimal("0.8") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=self._W_SLOW_MS,
                        magnitude=Decimal("0.20"),
                    ),
                ),
            ),
            action(
                "SKARNER_R_IMPALE",
                at_ms=self._R_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, Decimal(250) + ap, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity, "SUPPRESSION", duration_ms=self._R_SUPPRESS_MS
                    ),
                ),
            ),
        ]
        interval = self._attack_interval_ms(snapshot.attack_speed)
        attack_times = tuple(range(self._FIRST_ATTACK_MS, context.duration_ms + 1, interval))
        for index, at_ms in enumerate(attack_times):
            outputs = [damage(context.opponent_entity, snapshot.attack_damage, DamageType.PHYSICAL)]
            if self._Q_AT_MS <= at_ms < self._Q_AT_MS + self._Q_HOLD_MS:
                outputs.append(damage(context.opponent_entity, rock, DamageType.PHYSICAL))
            events.append(
                action(
                    f"SKARNER_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 700 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
        # Impale plus the first two attacks bring Quaking to three stacks.
        if len(attack_times) >= self._QUAKE_STACKS - 1:
            quake_start = attack_times[self._QUAKE_STACKS - 2]
            ratio = (Decimal(5) + Decimal(4) * Decimal(snapshot.level - 1) / Decimal(17)) / Decimal(
                100
            )
            ticks = self._QUAKE_DURATION_MS // self._QUAKE_TICK_MS
            tick = ratio * context.opponent_snapshot.max_hp / Decimal(ticks)
            for index in range(ticks):
                at_ms = quake_start + (index + 1) * self._QUAKE_TICK_MS
                if at_ms > context.duration_ms:
                    break
                events.append(
                    action(
                        f"SKARNER_PASSIVE_QUAKING_TICK_{index + 1}",
                        at_ms=at_ms,
                        sequence=base + 20 + index,
                        source=context.self_entity,
                        channel=ActionChannel.PASSIVE,
                        outputs=(damage(context.opponent_entity, tick, DamageType.MAGIC),),
                    )
                )
        level_blockers = (
            () if snapshot.level == 13 else (f"SKARNER_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "skarner_q5_w5_e1_r2_impale_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "SKARNER_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "SKARNER_E_WALL_STUN_REQUIRES_TERRAIN",
                "SKARNER_Q_BOULDER_THROW_NOT_USED",
                "SKARNER_Q_ATTACK_SPEED_NOT_APPLIED_TO_CADENCE",
                "SKARNER_R_DRAG_REPOSITIONING_NOT_MODELED",
                "SKARNER_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the Impale suppression as this Cog's hostile control window.

        :param context: Role-bound Skarner and opponent snapshots.
        :return: Deterministic control windows caused by Skarner's rotation.
        """
        return ReactionPlan(
            "skarner_r_suppression_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "skarner_r_impale_suppression",
                    self._R_AT_MS,
                    min(self._R_AT_MS + self._R_SUPPRESS_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "SKARNER_R_IMPALE",
                    False,
                    ControlType.SUPPRESSION,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
