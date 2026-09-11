"""Tristana combat Cog backed by locked 16.17.1 champion sources."""

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


class TristanaCog(ChampionCog):
    """Model Tristana's W5/E5/Q1/R2 level-thirteen duel fixture.

    Rocket Jump lands its area damage and slow, Explosive Charge is cast at
    its active-detonate value with no pre-applied stacks, and Buster Shot
    lands its damage and stun. Rapid Fire grants only an attack-speed buff
    with no damage of its own and is excluded from combat output; the
    passive charge auto-detonation and R's knockback are excluded rather
    than guessed.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Tristana.json",
        "data/raw/16.17.1/communitydragon/champions/18.json",
        "data/raw/16.17.1/communitydragon/champions/tristana.bin.json",
    )

    _W_AT_MS = 0
    _W_SLOW_MS = 2000
    _E_AT_MS = 900
    _R_AT_MS = 1800
    _R_STUN_MS = 400

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Tristana's jump-landing, detonation, and buster-shot rotation.

        :param context: Role-bound Tristana and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        w_damage = (
            Decimal(210)
            + context.snapshot.bonus_attack_damage
            + Decimal("0.5") * context.snapshot.ability_power
        )
        e_damage = (
            Decimal(160)
            + Decimal("0.8") * context.snapshot.bonus_attack_damage
            + Decimal("0.5") * context.snapshot.ability_power
        )
        r_damage = (
            Decimal(225)
            + Decimal("0.7") * context.snapshot.bonus_attack_damage
            + context.snapshot.ability_power
        )
        fixed = [
            action(
                "TRISTANA_W_ROCKET_JUMP",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, w_damage, DamageType.MAGIC),
                    StatModifierOutput(
                        context.opponent_entity,
                        "MOVE_SPEED_PERCENT",
                        Decimal("-0.40"),
                        self._W_SLOW_MS,
                    ),
                ),
            ),
            action(
                "TRISTANA_E_EXPLOSIVE_CHARGE",
                at_ms=self._E_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, e_damage, DamageType.PHYSICAL),),
            ),
            action(
                "TRISTANA_R_BUSTER_SHOT",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=self._R_STUN_MS),
                ),
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"TRISTANA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "tristana_w5_e5_q1_r2_jump_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "TRISTANA_E_PASSIVE_STACK_DETONATION_NOT_MODELED",
                "TRISTANA_R_KNOCKBACK_NOT_MODELED",
                "TRISTANA_Q_NO_DIRECT_DAMAGE_EXCLUDED",
                "TRISTANA_PASSIVE_DRAW_A_BEAD_NOT_MODELED",
                "TRISTANA_RESOURCE_COSTS_NOT_EVALUATED",
                "TRISTANA_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Tristana and opponent combat snapshots.
        :return: Ordinary basic-attack damage events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 500
        events: list[ActionEvent] = []
        at_ms = 200
        index = 0
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"TRISTANA_BASIC_ATTACK_{index}",
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
        """Expose the Buster Shot stun as this Cog's hostile control window.

        :param context: Role-bound Tristana and opponent snapshots.
        :return: Deterministic control windows caused by Tristana's rotation.
        """
        return ReactionPlan(
            "tristana_r_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "tristana_r_buster_shot_stun",
                    self._R_AT_MS,
                    min(self._R_AT_MS + self._R_STUN_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "TRISTANA_R_BUSTER_SHOT",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Rocket Jump's locked cast range as a closing-distance benchmark.

        :param context: Concrete participant context.
        :return: Dash distance in game units.
        """
        return Decimal(900)
