"""Talon combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatModifierOutput


class TalonCog(ChampionCog):
    """Model Talon's Q5/W5/R2 level-thirteen duel fixture, E excluded.

    Noxian Diplomacy leaps in for its ranged-cast damage, Rake throws and
    returns, and Shadow Assault hits twice — on cast and when its invisibility
    ends. Q's melee-range critical variant and kill-triggered heal, and
    Assassin's Path's wall traversal, are excluded rather than guessed: the
    former depends on distance-to-target this fixture does not vary, and the
    latter carries no damage or control data at all, making it pure mobility
    outside this engine's scope.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Talon.json",
        "data/raw/16.17.1/communitydragon/champions/91.json",
        "data/raw/16.17.1/communitydragon/champions/talon.bin.json",
    )

    _Q_AT_MS = 0
    _W_AT_MS = 900
    _W_RETURN_DELAY_MS = 700
    _W_SLOW_MS = 1000
    _R_AT_MS = 1800
    _R_RETURN_DELAY_MS = 2500

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Talon's leap, throw-and-return, and twin-blade-ring rotation.

        :param context: Role-bound Talon and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        q_damage = Decimal(145) + context.snapshot.bonus_attack_damage
        w_initial = Decimal(90) + Decimal("0.4") * context.snapshot.bonus_attack_damage
        w_return = Decimal(180) + Decimal("0.9") * context.snapshot.bonus_attack_damage
        r_damage = Decimal(135) + context.snapshot.bonus_attack_damage
        fixed = [
            action(
                "TALON_Q_NOXIAN_DIPLOMACY",
                at_ms=self._Q_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.PHYSICAL),),
            ),
            action(
                "TALON_W_RAKE_INITIAL",
                at_ms=self._W_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, w_initial, DamageType.PHYSICAL),
                    StatModifierOutput(
                        context.opponent_entity,
                        "MOVE_SPEED_PERCENT",
                        Decimal("-0.60"),
                        self._W_SLOW_MS,
                    ),
                ),
            ),
            action(
                "TALON_W_RAKE_RETURN",
                at_ms=self._W_AT_MS + self._W_RETURN_DELAY_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, w_return, DamageType.PHYSICAL),),
            ),
            action(
                "TALON_R_SHADOW_ASSAULT_CAST",
                at_ms=self._R_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, r_damage, DamageType.PHYSICAL),),
                requires_living_opponent=False,
            ),
        ]
        r_return_ms = self._R_AT_MS + self._R_RETURN_DELAY_MS
        if r_return_ms <= context.duration_ms:
            fixed.append(
                action(
                    "TALON_R_SHADOW_ASSAULT_RETURN",
                    at_ms=r_return_ms,
                    sequence=base + 4,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, r_damage, DamageType.PHYSICAL),),
                )
            )
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"TALON_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "talon_q5_w5_r2_leap_throw_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "TALON_Q_MELEE_RANGE_CRITICAL_VARIANT_NOT_MODELED",
                "TALON_Q_KILL_HEAL_AND_COOLDOWN_REFUND_NOT_MODELED",
                "TALON_E_ASSASSINS_PATH_NOT_MODELED",
                "TALON_R_ATTACK_CANCEL_EARLY_RETURN_NOT_MODELED",
                "TALON_PASSIVE_BLADES_END_NOT_MODELED",
                "TALON_RESOURCE_COSTS_NOT_EVALUATED",
                "TALON_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Talon and opponent combat snapshots.
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
                    f"TALON_BASIC_ATTACK_{index}",
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
        """Report that Talon's rotation applies no hostile control.

        :param context: Role-bound Talon and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "talon_no_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Noxian Diplomacy's locked cast range as its closing distance.

        :param context: Concrete participant context.
        :return: Dash distance in game units.
        """
        return Decimal(575)
