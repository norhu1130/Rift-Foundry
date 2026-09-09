"""Sion combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent, StatModifierOutput


class SionCog(ChampionCog):
    """Model Sion's Q5/E5/W1/R2 level-thirteen duel fixture.

    Decimating Smash and Unstoppable Onslaught both scale their damage with
    hold time; this fixture uses the guaranteed minimum-charge value for both,
    the same conservative reading this codebase already applies to other
    charge-based casts. Soul Furnace's detonate recast is included at a fixed
    one-second delay, but its locked max-health damage ratio did not resolve
    to a confirmed formula and is excluded rather than guessed. The passive's
    death-and-decay state is out of scope for a single fixed encounter.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Sion.json",
        "data/raw/16.17.1/communitydragon/champions/14.json",
        "data/raw/16.17.1/communitydragon/champions/sion.bin.json",
    )

    _W_AT_MS = 0
    _W_DETONATE_DELAY_MS = 1000
    _E_AT_MS = 900
    _E_SLOW_MS = 2500
    _E_SHRED_MS = 4000
    _Q_AT_MS = 1700
    _Q_STUN_MS = 1250
    _R_AT_MS = 2600
    _R_TRAVEL_DELAY_MS = 800
    _R_STUN_MS = 750

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Sion's shield-open, shred, smash-stun, and charge rotation.

        :param context: Role-bound Sion and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        w_shield = (
            Decimal(60)
            + Decimal("0.4") * context.snapshot.ability_power
            + Decimal("0.06") * context.snapshot.max_hp
        )
        w_detonate = Decimal(15) + Decimal("0.4") * context.snapshot.ability_power
        e_damage = Decimal(205) + Decimal("0.55") * context.snapshot.ability_power
        q_damage = Decimal(90) + Decimal("0.8") * context.snapshot.bonus_attack_damage
        r_damage = Decimal(300) + Decimal("0.6") * context.snapshot.bonus_attack_damage
        fixed = [
            action(
                "SION_W_SOUL_FURNACE_SHIELD",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(shielding(context.self_entity, w_shield, duration_ms=6000),),
                requires_living_opponent=False,
            ),
            action(
                "SION_W_SOUL_FURNACE_DETONATE",
                at_ms=self._W_AT_MS + self._W_DETONATE_DELAY_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, w_detonate, DamageType.MAGIC),),
            ),
            action(
                "SION_E_ROAR_OF_THE_SLAYER",
                at_ms=self._E_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    StatModifierOutput(
                        context.opponent_entity,
                        "MOVE_SPEED_PERCENT",
                        Decimal("-0.60"),
                        self._E_SLOW_MS,
                    ),
                    StatModifierOutput(
                        context.opponent_entity, "ARMOR", Decimal(-25), self._E_SHRED_MS
                    ),
                ),
            ),
            action(
                "SION_Q_DECIMATING_SMASH",
                at_ms=self._Q_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q_damage, DamageType.PHYSICAL),
                    crowd_control(
                        context.opponent_entity, "STUN", duration_ms=self._Q_STUN_MS
                    ),
                ),
            ),
            action(
                "SION_R_UNSTOPPABLE_ONSLAUGHT",
                at_ms=self._R_AT_MS + self._R_TRAVEL_DELAY_MS,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.PHYSICAL),
                    crowd_control(
                        context.opponent_entity, "STUN", duration_ms=self._R_STUN_MS
                    ),
                ),
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"SION_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "sion_q5_e5_w1_r2_shield_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "SION_Q_MAX_CHARGE_DAMAGE_NOT_MODELED",
                "SION_R_MAX_CHARGE_DAMAGE_NOT_MODELED",
                "SION_W_MAX_HEALTH_DAMAGE_RATIO_NOT_MODELED",
                "SION_PASSIVE_UNDEAD_DEATH_STATE_NOT_MODELED",
                "SION_RESOURCE_COSTS_NOT_EVALUATED",
                "SION_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Sion and opponent combat snapshots.
        :return: Ordinary basic-attack damage events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 700
        events: list[ActionEvent] = []
        at_ms = 200
        index = 0
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"SION_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            context.snapshot.attack_damage,
                            DamageType.PHYSICAL,
                        ),
                    ),
                )
            )
            index += 1
            at_ms += interval
        return tuple(events)

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the Q and R stuns as this Cog's hostile control windows.

        :param context: Role-bound Sion and opponent snapshots.
        :return: Deterministic control windows caused by Sion's rotation.
        """
        all_channels = (
            ActionChannel.BASIC_ATTACK,
            ActionChannel.ABILITY,
            ActionChannel.MOVEMENT,
        )
        r_start = self._R_AT_MS + self._R_TRAVEL_DELAY_MS
        return ReactionPlan(
            "sion_q_r_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "sion_q_decimating_smash_stun",
                    self._Q_AT_MS,
                    min(self._Q_AT_MS + self._Q_STUN_MS, context.duration_ms),
                    all_channels,
                    "SION_Q_DECIMATING_SMASH",
                    True,
                    ControlType.STUN,
                ),
                CastBlockWindow(
                    "sion_r_unstoppable_onslaught_stun",
                    r_start,
                    min(r_start + self._R_STUN_MS, context.duration_ms),
                    all_channels,
                    "SION_R_UNSTOPPABLE_ONSLAUGHT",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Unstoppable Onslaught's charge as a closing-distance benchmark.

        :param context: Concrete participant context.
        :return: Dash distance in game units.
        """
        return Decimal(600)
