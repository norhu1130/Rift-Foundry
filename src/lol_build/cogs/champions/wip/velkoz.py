"""Vel'Koz combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent, StatModifierOutput


class VelkozCog(ChampionCog):
    """Model Vel'Koz's Q5/E5/W1/R2 level-thirteen duel fixture.

    Plasma Fission, Void Rift's two hits, and Tectonic Disruption's knock-up
    resolve as direct hits. Life Form Disintegration Ray applies its full
    rank-two channel total as one hit at the channel's end rather than
    modeling individual ticks, since only the total is locked in the
    resolvable record. The bolt-split, second W charge, and the true-damage
    conversion against recently marked targets are excluded rather than
    guessed.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Velkoz.json",
        "data/raw/16.17.1/communitydragon/champions/161.json",
        "data/raw/16.17.1/communitydragon/champions/velkoz.bin.json",
    )

    _W_AT_MS = 0
    _W_SECOND_HIT_DELAY_MS = 400
    _E_AT_MS = 800
    _E_KNOCKUP_MS = 750
    _Q_AT_MS = 1600
    _Q_SLOW_MS = 2600
    _R_AT_MS = 2400
    _R_CHANNEL_MS = 2500

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Vel'Koz's rift, knock-up, bolt, and channel rotation.

        :param context: Role-bound Vel'Koz and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        w_initial = Decimal(30) + Decimal("0.2") * context.snapshot.ability_power
        w_secondary = Decimal(45) + Decimal("0.25") * context.snapshot.ability_power
        e_damage = Decimal(190) + Decimal("0.3") * context.snapshot.ability_power
        q_damage = Decimal(240) + Decimal("0.9") * context.snapshot.ability_power
        r_damage = Decimal(700) + Decimal("1.25") * context.snapshot.ability_power
        fixed = [
            action(
                "VELKOZ_W_VOID_RIFT_INITIAL",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, w_initial, DamageType.MAGIC),),
            ),
            action(
                "VELKOZ_W_VOID_RIFT_SECONDARY",
                at_ms=self._W_AT_MS + self._W_SECOND_HIT_DELAY_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, w_secondary, DamageType.MAGIC),),
            ),
            action(
                "VELKOZ_E_TECTONIC_DISRUPTION",
                at_ms=self._E_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity, "AIRBORNE", duration_ms=self._E_KNOCKUP_MS
                    ),
                ),
            ),
            action(
                "VELKOZ_Q_PLASMA_FISSION",
                at_ms=self._Q_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q_damage, DamageType.MAGIC),
                    StatModifierOutput(
                        context.opponent_entity,
                        "MOVE_SPEED_PERCENT",
                        Decimal("-0.70"),
                        self._Q_SLOW_MS,
                    ),
                ),
            ),
            action(
                "VELKOZ_R_LIFE_FORM_DISINTEGRATION_RAY",
                at_ms=self._R_AT_MS + self._R_CHANNEL_MS,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, r_damage, DamageType.MAGIC),),
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"VELKOZ_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "velkoz_q5_e5_w1_r2_rift_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "VELKOZ_Q_BOLT_SPLIT_NOT_MODELED",
                "VELKOZ_W_SECOND_CHARGE_NOT_MODELED",
                "VELKOZ_R_PER_TICK_TIMING_AND_TRUE_DAMAGE_NOT_MODELED",
                "VELKOZ_PASSIVE_ORGANIC_DECONSTRUCTION_NOT_MODELED",
                "VELKOZ_RESOURCE_COSTS_NOT_EVALUATED",
                "VELKOZ_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Vel'Koz and opponent combat snapshots.
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
                    f"VELKOZ_BASIC_ATTACK_{index}",
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
        """Expose the Tectonic Disruption knock-up as this Cog's control window.

        :param context: Role-bound Vel'Koz and opponent snapshots.
        :return: Deterministic control windows caused by Vel'Koz's rotation.
        """
        return ReactionPlan(
            "velkoz_e_knockup_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "velkoz_e_tectonic_disruption_knockup",
                    self._E_AT_MS,
                    min(self._E_AT_MS + self._E_KNOCKUP_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "VELKOZ_E_TECTONIC_DISRUPTION",
                    False,
                    ControlType.AIRBORNE,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
