"""Pyke combat Cog backed by locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

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
from lol_build.core.timeline import ActionChannel, ActionEvent, StatModifierOutput, StatusOutput


class PykeCog(ChampionCog):
    """Model Pyke's Q5/E5/W1/R2 level-thirteen duel fixture.

    W opens with Camouflage and its move-speed buff, E dashes into a stun and
    single hit, and Q's tap cast lands the slow. Q's hold-cast pull, R's
    global-teleport execute, and the passive's max-health-to-AD conversion are
    excluded rather than guessed: the pull depends on a held cast duration
    this fixture does not model, the execute's death condition is an absolute
    health threshold the timeline's ratio-based execute primitive does not
    express, and the conversion is a stat-budget rule rather than a rotation
    event.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Pyke.json",
        "data/raw/16.17.1/communitydragon/champions/555.json",
        "data/raw/16.17.1/communitydragon/champions/pyke.bin.json",
    )

    _W_AT_MS = 0
    _W_SPEED_DURATION_MS = 5000
    _E_AT_MS = 600
    _E_STUN_MS = 1250
    _Q_AT_MS = 1600
    _Q_SLOW_MS = 1000
    #: Rank-five Bone Skewer base cooldown before haste, in milliseconds.
    _Q_BASE_COOLDOWN_MS = 8000

    @staticmethod
    def _haste_cooldown_ms(base_ms: int, ability_haste: Decimal) -> int:
        """Apply ability haste to one locked base cooldown.

        :param base_ms: Locked cooldown in milliseconds before haste.
        :param ability_haste: Non-negative ability haste from items.
        :return: Rounded cooldown in milliseconds.
        """
        haste = max(Decimal(0), ability_haste)
        return int(
            (Decimal(base_ms) * Decimal(100) / (Decimal(100) + haste)).to_integral_value(
                ROUND_CEILING
            )
        )

    def _q_damage(self, context: ParticipantContext) -> Decimal:
        """Compute rank-five Bone Skewer tap damage.

        :param context: Snapshot supplying bonus attack damage.
        :return: Raw physical damage before mitigation.
        """
        return Decimal(300) + Decimal("0.75") * context.snapshot.bonus_attack_damage

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Pyke's stealth-open, dash-stun, and tap-slow rotation.

        :param context: Role-bound Pyke and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        q_damage = self._q_damage(context)
        e_damage = Decimal(300) + context.snapshot.bonus_attack_damage
        fixed = [
            action(
                "PYKE_W_GHOSTWATER_DIVE",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatModifierOutput(
                        context.self_entity,
                        "MOVE_SPEED_FLAT",
                        Decimal(45),
                        self._W_SPEED_DURATION_MS,
                    ),
                    StatusOutput(context.self_entity, "PYKE_W_CAMOUFLAGE", 5000),
                ),
                requires_living_opponent=False,
            ),
            action(
                "PYKE_E_PHANTOM_UNDERTOW",
                at_ms=self._E_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.PHYSICAL),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=self._E_STUN_MS),
                ),
            ),
            action(
                "PYKE_Q_BONE_SKEWER_TAP_1",
                at_ms=self._Q_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q_damage, DamageType.PHYSICAL),
                    StatModifierOutput(
                        context.opponent_entity,
                        "MOVE_SPEED_PERCENT",
                        Decimal("-0.90"),
                        self._Q_SLOW_MS,
                    ),
                ),
            ),
        ]
        second_q_ms = self._Q_AT_MS + self._haste_cooldown_ms(
            self._Q_BASE_COOLDOWN_MS, context.snapshot.ability_haste
        )
        if second_q_ms <= context.duration_ms:
            fixed.append(
                action(
                    "PYKE_Q_BONE_SKEWER_TAP_2",
                    at_ms=second_q_ms,
                    sequence=base + 3,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, q_damage, DamageType.PHYSICAL),
                        StatModifierOutput(
                            context.opponent_entity,
                            "MOVE_SPEED_PERCENT",
                            Decimal("-0.90"),
                            self._Q_SLOW_MS,
                        ),
                    ),
                )
            )
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"PYKE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "pyke_q5_e5_w1_r2_dash_stun_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "PYKE_Q_HOLD_CAST_AND_PULL_NOT_MODELED",
                "PYKE_R_DEATH_FROM_BELOW_EXECUTE_NOT_MODELED",
                "PYKE_E_PHANTOM_RETURN_SECOND_HIT_NOT_MODELED",
                "PYKE_PASSIVE_HEALTH_TO_AD_CONVERSION_NOT_MODELED",
                "PYKE_PASSIVE_HIDDEN_REGENERATION_NOT_MODELED",
                "PYKE_RESOURCE_COSTS_NOT_EVALUATED",
                "PYKE_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Pyke and opponent combat snapshots.
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
                    f"PYKE_BASIC_ATTACK_{index}",
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
        """Expose the Phantom Undertow stun as this Cog's hostile control window.

        :param context: Role-bound Pyke and opponent snapshots.
        :return: Deterministic control windows caused by Pyke's rotation.
        """
        return ReactionPlan(
            "pyke_e_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "pyke_e_phantom_undertow_stun",
                    self._E_AT_MS,
                    min(self._E_AT_MS + self._E_STUN_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "PYKE_E_PHANTOM_UNDERTOW",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Phantom Undertow's locked cast range as its closing distance.

        :param context: Concrete participant context.
        :return: Dash distance in game units.
        """
        return Decimal(550)
