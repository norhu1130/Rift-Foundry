"""Urgot combat Cog backed by locked 16.17.1 champion sources."""

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


class UrgotCog(ChampionCog):
    """Model Urgot's Q5/E5/W1/R2 level-thirteen duel fixture.

    Corrosive Charge detonates on its locked delay, Purge is applied as one
    representative shot rather than its full rapid-fire channel, Disdain
    dashes into a shield and stun, and Fear Beyond Death resolves at its
    non-execute damage. The below-25%-health execute variant of R, the
    channel duration of W, and Q's slow-halt interaction with W are excluded
    rather than guessed.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Urgot.json",
        "data/raw/16.17.1/communitydragon/champions/6.json",
        "data/raw/16.17.1/communitydragon/champions/urgot.bin.json",
    )

    _Q_AT_MS = 0
    _Q_DELAY_MS = 400
    _Q_SLOW_MS = 1250
    _W_AT_MS = 900
    _E_AT_MS = 1600
    _E_STUN_MS = 1500
    _R_AT_MS = 2600
    _R_FEAR_MS = 1500

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Urgot's charge, single-shot, dash-stun, and fear rotation.

        :param context: Role-bound Urgot and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        q_damage = Decimal(205) + Decimal("0.7") * context.snapshot.bonus_attack_damage
        w_damage = Decimal(12) + Decimal("0.2") * context.snapshot.bonus_attack_damage
        e_damage = Decimal(210) + context.snapshot.bonus_attack_damage
        r_damage = Decimal(225) + Decimal("0.5") * context.snapshot.bonus_attack_damage
        fixed = [
            action(
                "URGOT_Q_CORROSIVE_CHARGE",
                at_ms=self._Q_AT_MS + self._Q_DELAY_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q_damage, DamageType.PHYSICAL),
                    StatModifierOutput(
                        context.opponent_entity,
                        "MOVE_SPEED_PERCENT",
                        Decimal("-0.65"),
                        self._Q_SLOW_MS,
                    ),
                ),
            ),
            action(
                "URGOT_W_PURGE",
                at_ms=self._W_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, w_damage, DamageType.PHYSICAL),),
            ),
            action(
                "URGOT_E_DISDAIN",
                at_ms=self._E_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.PHYSICAL),
                    crowd_control(
                        context.opponent_entity, "STUN", duration_ms=self._E_STUN_MS
                    ),
                ),
            ),
            action(
                "URGOT_R_FEAR_BEYOND_DEATH",
                at_ms=self._R_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.PHYSICAL),
                    crowd_control(
                        context.opponent_entity, "FEAR", duration_ms=self._R_FEAR_MS
                    ),
                ),
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"URGOT_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "urgot_q5_e5_w1_r2_charge_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "URGOT_W_FULL_CHANNEL_NOT_MODELED",
                "URGOT_R_EXECUTE_THRESHOLD_VARIANT_NOT_MODELED",
                "URGOT_PASSIVE_ECHOING_FLAMES_NOT_MODELED",
                "URGOT_RESOURCE_COSTS_NOT_EVALUATED",
                "URGOT_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Urgot and opponent combat snapshots.
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
                    f"URGOT_BASIC_ATTACK_{index}",
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
        """Expose the E stun and R fear as Urgot's control windows.

        :param context: Role-bound Urgot and opponent snapshots.
        :return: Deterministic control windows caused by Urgot's rotation.
        """
        all_channels = (
            ActionChannel.BASIC_ATTACK,
            ActionChannel.ABILITY,
            ActionChannel.MOVEMENT,
        )
        return ReactionPlan(
            "urgot_e_r_control_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "urgot_e_disdain_stun",
                    self._E_AT_MS,
                    min(self._E_AT_MS + self._E_STUN_MS, context.duration_ms),
                    all_channels,
                    "URGOT_E_DISDAIN",
                    True,
                    ControlType.STUN,
                ),
                CastBlockWindow(
                    "urgot_r_fear_beyond_death",
                    self._R_AT_MS,
                    min(self._R_AT_MS + self._R_FEAR_MS, context.duration_ms),
                    all_channels,
                    "URGOT_R_FEAR_BEYOND_DEATH",
                    True,
                    ControlType.FEAR,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Disdain's locked cast range as its closing distance.

        :param context: Concrete participant context.
        :return: Dash distance in game units.
        """
        return Decimal(475)
