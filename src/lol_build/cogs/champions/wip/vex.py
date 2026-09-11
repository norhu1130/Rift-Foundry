"""Vex combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, damage, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatModifierOutput


class VexCog(ChampionCog):
    """Model Vex's Q5/E5/W1/R2 level-thirteen duel fixture.

    Mistral Bolt, Personal Space, and Looming Darkness resolve as direct
    hits, and Shadow Surge fires its initial mark and its recast on arrival
    shortly after, matching the combo the ability's own locked text
    describes. Gloom's cooldown-reduction consumption and the takedown reset
    on a kill are excluded rather than guessed.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Vex.json",
        "data/raw/16.17.1/communitydragon/champions/711.json",
        "data/raw/16.17.1/communitydragon/champions/vex.bin.json",
    )

    _W_AT_MS = 0
    _E_AT_MS = 800
    _E_SLOW_MS = 2000
    _Q_AT_MS = 1600
    _R_AT_MS = 2400
    _R_RECAST_DELAY_MS = 800

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Vex's shield-open, slow, bolt, and mark-recast rotation.

        :param context: Role-bound Vex and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        w_shield = Decimal(50) + Decimal("0.75") * context.snapshot.ability_power
        w_damage = Decimal(80) + Decimal("0.3") * context.snapshot.ability_power
        e_damage = Decimal(130) + Decimal("0.6") * context.snapshot.ability_power
        q_damage = Decimal(250) + Decimal("0.7") * context.snapshot.ability_power
        r_damage = Decimal(125) + Decimal("0.2") * context.snapshot.ability_power
        r_recast_damage = Decimal(250) + Decimal("0.5") * context.snapshot.ability_power
        fixed = [
            action(
                "VEX_W_PERSONAL_SPACE",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(context.self_entity, w_shield, duration_ms=2500),
                    damage(context.opponent_entity, w_damage, DamageType.MAGIC),
                ),
                requires_living_opponent=False,
            ),
            action(
                "VEX_E_LOOMING_DARKNESS",
                at_ms=self._E_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    StatModifierOutput(
                        context.opponent_entity,
                        "MOVE_SPEED_PERCENT",
                        Decimal("-0.50"),
                        self._E_SLOW_MS,
                    ),
                ),
            ),
            action(
                "VEX_Q_MISTRAL_BOLT",
                at_ms=self._Q_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.MAGIC),),
            ),
            action(
                "VEX_R_SHADOW_SURGE",
                at_ms=self._R_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, r_damage, DamageType.MAGIC),),
            ),
            action(
                "VEX_R_SHADOW_SURGE_RECAST",
                at_ms=self._R_AT_MS + self._R_RECAST_DELAY_MS,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, r_recast_damage, DamageType.MAGIC),),
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"VEX_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "vex_q5_e5_w1_r2_shield_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "VEX_PASSIVE_GLOOM_AND_COOLDOWN_REDUCTION_NOT_MODELED",
                "VEX_R_TAKEDOWN_RESET_NOT_MODELED",
                "VEX_RESOURCE_COSTS_NOT_EVALUATED",
                "VEX_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Vex and opponent combat snapshots.
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
                    f"VEX_BASIC_ATTACK_{index}",
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
        """Report that Vex's rotation applies no hostile hard control.

        :param context: Role-bound Vex and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "vex_no_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
