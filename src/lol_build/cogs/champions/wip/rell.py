"""Rell combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    ResistanceReductionOutput,
    StatModifierOutput,
)


class RellCog(ChampionCog):
    """Model Rell's Q5/W5/E1/R2 level-thirteen engage fixture.

    Ferromancy: Crash Down knocks up and stuns on landing, grants its shield,
    and dismounts Rell for ``ResistanceIncrease``. Shattering Strike stuns,
    Full Tilt's empowered attack deals ``MaxHealthDamageCalc`` of the target's
    maximum health up to ``PercentHealthDamageCap``, and Magnet Storm ticks for
    its rank-two damage per second. Every hit applies one Break the Mold stack,
    stripping ``StealPercent`` of armor and magic resistance up to
    ``MaxStacks``. Break the Mold's on-hit damage reads two stat identifiers
    this engine does not map with confidence, so it is excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Rell.json",
        "data/raw/16.17.1/communitydragon/champions/526.json",
        "data/raw/16.17.1/communitydragon/champions/rell.bin.json",
    )

    _W_AT_MS = 0
    _W_KNOCKUP_MS = 400
    _W_STUN_MS = 800
    _Q_AT_MS = 1400
    _Q_STUN_MS = 650
    _E_ATTACK_MS = 2300
    _R_AT_MS = 2800
    _R_TICK_MS = 500
    _R_DURATION_MS = 2000
    _SHRED_MS = 5000
    _ATTACKS_FROM_MS = 3000

    def _shred(self, context: ParticipantContext) -> tuple[ResistanceReductionOutput, ...]:
        """Apply one Break the Mold armor and magic-resistance stack.

        :param context: Role-bound Rell and opponent snapshots.
        :return: Stacking resistance-reduction outputs for both resistances.
        """
        return tuple(
            ResistanceReductionOutput(
                recipient=context.opponent_entity,
                stat=stat,
                fraction_per_stack=Decimal("0.03"),
                max_stacks=5,
                duration_ms=self._SHRED_MS,
                state_key=f"RELL_PASSIVE_BREAK_THE_MOLD_{stat}",
            )
            for stat in ("ARMOR", "MAGIC_RESISTANCE")
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Rell's crash-down, strike, full-tilt, and magnet-storm rotation.

        :param context: Role-bound Rell and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        ap = snapshot.ability_power
        e_cap = Decimal(150) + Decimal(150) * Decimal(snapshot.level - 1) / Decimal(17)
        e_damage = min(
            e_cap,
            (Decimal("0.05") + Decimal("0.0003") * ap) * context.opponent_snapshot.max_hp,
        )
        events: list[ActionEvent] = [
            action(
                "RELL_W_CRASH_DOWN",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(180) + Decimal("0.6") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity, "AIRBORNE", duration_ms=self._W_KNOCKUP_MS
                    ),
                    shielding(
                        context.self_entity, Decimal(100) + Decimal("0.11") * snapshot.max_hp
                    ),
                    StatModifierOutput(
                        context.self_entity, "ARMOR", Decimal("0.15") * snapshot.armor, None
                    ),
                    StatModifierOutput(
                        context.self_entity,
                        "MAGIC_RESISTANCE",
                        Decimal("0.15") * snapshot.magic_resistance,
                        None,
                    ),
                    *self._shred(context),
                ),
            ),
            action(
                "RELL_W_CRASH_DOWN_STUN",
                at_ms=self._W_AT_MS + self._W_KNOCKUP_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    crowd_control(context.opponent_entity, "STUN", duration_ms=self._W_STUN_MS),
                ),
            ),
            action(
                "RELL_Q_SHATTERING_STRIKE",
                at_ms=self._Q_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(220) + Decimal("0.6") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=self._Q_STUN_MS),
                    *self._shred(context),
                ),
            ),
            action(
                "RELL_E_FULL_TILT_EXPLOSION",
                at_ms=self._E_ATTACK_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(context.opponent_entity, snapshot.attack_damage, DamageType.PHYSICAL),
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    *self._shred(context),
                ),
            ),
        ]
        tick = (Decimal(125) + Decimal("0.55") * ap) * Decimal(self._R_TICK_MS) / Decimal(1000)
        for index in range(self._R_DURATION_MS // self._R_TICK_MS):
            at_ms = self._R_AT_MS + (index + 1) * self._R_TICK_MS
            if at_ms > context.duration_ms:
                break
            events.append(
                action(
                    f"RELL_R_MAGNET_STORM_TICK_{index + 1}",
                    at_ms=at_ms,
                    sequence=base + 10 + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, tick, DamageType.MAGIC),),
                )
            )
        interval = self._attack_interval_ms(snapshot.attack_speed)
        for index, at_ms in enumerate(
            range(self._ATTACKS_FROM_MS, context.duration_ms + 1, interval)
        ):
            events.append(
                action(
                    f"RELL_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 700 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity, snapshot.attack_damage, DamageType.PHYSICAL
                        ),
                        *self._shred(context),
                    ),
                )
            )
        level_blockers = (
            () if snapshot.level == 13 else (f"RELL_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "rell_q5_w5_e1_r2_crash_down_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "RELL_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "RELL_PASSIVE_ON_HIT_DAMAGE_STAT_IDS_NOT_MAPPED",
                "RELL_PASSIVE_STOLEN_RESISTANCES_NOT_GRANTED_TO_RELL",
                "RELL_W_SHIELD_DURATION_NOT_IN_LOCKED_DATA",
                "RELL_R_TICK_CADENCE_ASSUMED_HALF_SECOND",
                "RELL_R_PULL_DISPLACEMENT_NOT_MODELED",
                "RELL_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Crash Down's knock-up and stun and Shattering Strike's stun.

        :param context: Role-bound Rell and opponent snapshots.
        :return: Deterministic control windows caused by Rell's rotation.
        """
        channels = (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT)
        stun_start = self._W_AT_MS + self._W_KNOCKUP_MS
        return ReactionPlan(
            "rell_w_q_control_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "rell_w_crash_down_knockup",
                    self._W_AT_MS,
                    min(stun_start, context.duration_ms),
                    channels,
                    "RELL_W_CRASH_DOWN",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "rell_w_crash_down_stun",
                    stun_start,
                    min(stun_start + self._W_STUN_MS, context.duration_ms),
                    channels,
                    "RELL_W_CRASH_DOWN_STUN",
                    True,
                    ControlType.STUN,
                ),
                CastBlockWindow(
                    "rell_q_shattering_strike_stun",
                    self._Q_AT_MS,
                    min(self._Q_AT_MS + self._Q_STUN_MS, context.duration_ms),
                    channels,
                    "RELL_Q_SHATTERING_STRIKE",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
