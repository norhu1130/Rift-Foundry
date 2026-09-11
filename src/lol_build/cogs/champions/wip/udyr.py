"""Udyr combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent, StatModifierOutput


class UdyrCog(ChampionCog):
    """Model Udyr's Q5/E5/W2/R1 level-thirteen stance-dance fixture.

    Blazing Stampede makes the first attack stun for ``StunDuration``.
    Wilding Claw adds its rank-five ``AttackSpeedBase`` for four seconds and
    empowers two attacks with ``OnHitDamage`` (``BaseDamage`` plus 20% bonus
    attack damage) and ``MaxHPOnHit1`` of the target's maximum health. Iron
    Mantle grants its rank-two shield (``ShieldBase`` plus ``ShieldPercentHealth``
    of maximum health plus ``ShieldAPRatio``) and makes the next two attacks
    heal ``LifeOnHit`` while granting its rank-two ``LifeSteal``. Recast
    awakenings, Wingborne Storm, and Bridge Between's attack speed are excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Udyr.json",
        "data/raw/16.17.1/communitydragon/champions/77.json",
        "data/raw/16.17.1/communitydragon/champions/udyr.bin.json",
    )

    _E_AT_MS = 0
    _STUN_MS = 750
    _Q_AT_MS = 300
    _Q_DURATION_MS = 4000
    _W_AT_MS = 4400
    _W_SHIELD_MS = 4000
    _FIRST_ATTACK_MS = 200

    def _attack_times(self, context: ParticipantContext) -> tuple[int, ...]:
        """Schedule attacks, faster while Wilding Claw's attack speed lasts.

        :param context: Role-bound Udyr and opponent snapshots.
        :return: Chronological attack timestamps.
        """
        normal = self._attack_interval_ms(context.snapshot.attack_speed)
        clawed = self._attack_interval_ms(
            context.snapshot.attack_speed + Decimal("0.68") * self._attack_speed_ratio()
        )
        times: list[int] = []
        at_ms = self._FIRST_ATTACK_MS
        while at_ms <= context.duration_ms:
            times.append(at_ms)
            in_claw = self._Q_AT_MS <= at_ms < self._Q_AT_MS + self._Q_DURATION_MS
            at_ms += clawed if in_claw else normal
        return tuple(times)

    def _attack_speed_ratio(self) -> Decimal:
        """Return the locked attack-speed ratio that scales bonus attack speed.

        :return: Attack-speed ratio from the champion record.
        """
        detail = self.detail_root or {}
        raw = detail.get("attackSpeedRatioModifiable")
        if isinstance(raw, dict) and "baseValue" in raw:
            return Decimal(str(raw["baseValue"]))
        return Decimal(str(self.document["stats"]["attackspeed"]))

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Udyr's stun, claw, and mantle stance rotation.

        :param context: Role-bound Udyr and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        claw_bonus = Decimal(30) + Decimal("0.2") * snapshot.bonus_attack_damage
        claw_health_ratio = Decimal("0.07") + Decimal("0.00035") * snapshot.bonus_attack_damage
        shield = (
            Decimal(65)
            + Decimal("0.023") * snapshot.max_hp
            + Decimal("0.4") * snapshot.ability_power
        )
        life_on_hit = Decimal("0.012") * snapshot.max_hp + Decimal("0.08") * snapshot.ability_power
        attack_times = self._attack_times(context)
        claw_attacks = [at for at in attack_times if at >= self._Q_AT_MS][:2]
        mantle_attacks = [at for at in attack_times if at >= self._W_AT_MS][:2]
        fixed = [
            action(
                "UDYR_E_BLAZING_STAMPEDE",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatModifierOutput(
                        context.self_entity, "MOVE_SPEED_PERCENT", Decimal("0.43"), 4000
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "UDYR_Q_WILDING_CLAW",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatModifierOutput(
                        context.self_entity, "ATTACK_SPEED", Decimal("0.68"), self._Q_DURATION_MS
                    ),
                ),
                requires_living_opponent=False,
            ),
        ]
        if context.duration_ms >= self._W_AT_MS:
            fixed.append(
                action(
                    "UDYR_W_IRON_MANTLE",
                    at_ms=self._W_AT_MS,
                    sequence=base + 2,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        shielding(context.self_entity, shield, duration_ms=self._W_SHIELD_MS),
                        StatModifierOutput(
                            context.self_entity, "LIFESTEAL", Decimal("0.15"), self._W_SHIELD_MS
                        ),
                    ),
                    requires_living_opponent=False,
                )
            )
        attacks: list[ActionEvent] = []
        for index, at_ms in enumerate(attack_times):
            outputs: list[object] = [
                damage(context.opponent_entity, snapshot.attack_damage, DamageType.PHYSICAL)
            ]
            if at_ms == attack_times[0]:
                outputs.append(
                    crowd_control(context.opponent_entity, "STUN", duration_ms=self._STUN_MS)
                )
            if at_ms in claw_attacks:
                outputs.append(damage(context.opponent_entity, claw_bonus, DamageType.PHYSICAL))
                outputs.append(
                    damage(
                        context.opponent_entity,
                        claw_health_ratio * context.opponent_snapshot.max_hp,
                        DamageType.PHYSICAL,
                    )
                )
            if at_ms in mantle_attacks:
                outputs.append(healing(context.self_entity, life_on_hit))
            attacks.append(
                action(
                    f"UDYR_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 700 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
        level_blockers = (
            () if snapshot.level == 13 else (f"UDYR_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "udyr_q5_e5_w2_r1_stance_level13_v1",
            tuple(sorted((*fixed, *attacks), key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "UDYR_LEVEL13_Q5_E5_W2_R1_POLICY_UNVERIFIED",
                "UDYR_RECAST_AWAKENINGS_NOT_MODELED",
                "UDYR_R_WINGBORNE_STORM_TICK_CADENCE_NOT_IN_LOCKED_DATA",
                "UDYR_W_SHIELD_BONUS_AD_COEFFICIENT_TRUNCATED_IN_SOURCE_READ",
                "UDYR_PASSIVE_BRIDGE_BETWEEN_ATTACK_SPEED_NOT_MODELED",
                "UDYR_E_STUN_INTERNAL_COOLDOWN_SINGLE_TARGET_ASSUMED",
                "UDYR_RESOURCE_COSTS_NOT_EVALUATED",
                "UDYR_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the Blazing Stampede stun as this Cog's hostile control window.

        :param context: Role-bound Udyr and opponent snapshots.
        :return: Deterministic control windows caused by Udyr's rotation.
        """
        return ReactionPlan(
            "udyr_e_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "udyr_e_blazing_stampede_stun",
                    self._FIRST_ATTACK_MS,
                    min(self._FIRST_ATTACK_MS + self._STUN_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "UDYR_BASIC_ATTACK_0",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Blazing Stampede's rank-five movement speed toward the target.

        :param context: Role-bound Udyr encounter context.
        :return: Movement multiplier from ``BaseMoveSpeed``.
        """
        return Decimal("1.43")
