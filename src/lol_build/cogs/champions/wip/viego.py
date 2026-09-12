"""Viego combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, CurrentHealthDamageOutput


class ViegoCog(ChampionCog):
    """Model Viego's Q5/E5/W1/R2 level-thirteen duel fixture.

    Spectral Maw is cast uncharged for its rank-one damage and minimum stun.
    Blade of the Ruined King's active thrust lands its rank-five damage, and
    its passive makes every attack deal ``PercentHealthOnHit`` of the target's
    current health. After each ability hit, the next attack strikes a second
    time for ``SecondAttackDamage`` and steals health, read here as
    ``HealModVsChamps`` times that strike's damage. Heartbreaker lands its
    physical damage plus ``MaxHealthDamage`` of the target's maximum health.
    Possession, Harrowed Path's mist, and charged Spectral Maw are excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Viego.json",
        "data/raw/16.17.1/communitydragon/champions/234.json",
        "data/raw/16.17.1/communitydragon/champions/viego.bin.json",
    )

    _W_AT_MS = 0
    _W_STUN_MS = 250
    _Q_AT_MS = 400
    _R_AT_MS = 3000
    _FIRST_ATTACK_MS = 300

    def _attack_outputs(self, context: ParticipantContext, *, double_strike: bool) -> tuple:
        """Build one attack with the Q passive and an optional second strike.

        :param context: Role-bound Viego and opponent snapshots.
        :param double_strike: Whether an ability hit primed the second strike.
        :return: Damage and heal-bearing outputs for the attack.
        """
        outputs = [
            damage(context.opponent_entity, context.snapshot.attack_damage, DamageType.PHYSICAL),
            CurrentHealthDamageOutput(
                context.opponent_entity, Decimal("0.06"), DamageType.PHYSICAL
            ),
        ]
        if double_strike:
            outputs.append(
                damage(
                    context.opponent_entity,
                    Decimal("0.2") * context.snapshot.attack_damage
                    + Decimal("0.15") * context.snapshot.ability_power,
                    DamageType.PHYSICAL,
                    source_heal_ratio=Decimal("1.5"),
                )
            )
        return tuple(outputs)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Viego's maw, thrust, double-strike, and heartbreaker rotation.

        :param context: Role-bound Viego and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        fixed = [
            action(
                "VIEGO_W_SPECTRAL_MAW",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("ViegoW", "Damage", context, Decimal(80))
                        + snapshot.ability_power,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=self._W_STUN_MS),
                ),
            ),
            action(
                "VIEGO_Q_BLADE_OF_THE_RUINED_KING",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("ViegoQ", "Damage", context, Decimal(85))
                        + Decimal("0.7") * snapshot.attack_damage,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
            action(
                "VIEGO_R_HEARTBREAKER",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal("1.2") * snapshot.bonus_attack_damage
                        + (
                            self.rank_value("ViegoR", "MaxHealthDamage", context, Decimal(16))
                            + Decimal("0.05") * snapshot.bonus_attack_damage
                        )
                        / Decimal(100)
                        * context.opponent_snapshot.max_hp,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
        ]
        interval = self._attack_interval_ms(snapshot.attack_speed)
        primers = [self._W_AT_MS, self._Q_AT_MS, self._R_AT_MS]
        attacks: list[ActionEvent] = []
        at_ms = self._FIRST_ATTACK_MS
        index = 0
        while at_ms <= context.duration_ms:
            primed = bool(primers) and at_ms > primers[0]
            if primed:
                while primers and at_ms > primers[0]:
                    primers.pop(0)
            attacks.append(
                action(
                    f"VIEGO_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 700 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=self._attack_outputs(context, double_strike=primed),
                )
            )
            index += 1
            at_ms += interval
        level_blockers = (
            () if snapshot.level == 13 else (f"VIEGO_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "viego_q5_e5_w1_r2_maw_open_level13_v1",
            tuple(sorted((*fixed, *attacks), key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "VIEGO_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "VIEGO_Q_SECOND_STRIKE_HEAL_READ_AS_HEALMODVSCHAMPS_TIMES_DAMAGE",
                "VIEGO_R_PERCENT_HEALTH_BASIS_READ_FROM_FIELD_NAME",
                "VIEGO_W_UNCHARGED_MINIMUM_STUN_SELECTED",
                "VIEGO_E_MIST_CAMOUFLAGE_REQUIRES_TERRAIN",
                "VIEGO_PASSIVE_POSSESSION_REQUIRES_TAKEDOWN",
                "VIEGO_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the Spectral Maw stun as this Cog's hostile control window.

        :param context: Role-bound Viego and opponent snapshots.
        :return: Deterministic control windows caused by Viego's rotation.
        """
        return ReactionPlan(
            "viego_w_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "viego_w_spectral_maw_stun",
                    self._W_AT_MS,
                    min(self._W_AT_MS + self._W_STUN_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "VIEGO_W_SPECTRAL_MAW",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
