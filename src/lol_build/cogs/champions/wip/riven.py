"""Riven combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent, MissingHealthDamageOutput


class RivenCog(ChampionCog):
    """Model Riven's Q5/W5/E1/R2 level-thirteen duel fixture.

    Broken Wings casts three times at the same locked damage, the third with
    a knock-up; Ki Burst bursts and stuns; Valor grants its shield; and Blade
    of the Exile's recast wind-slash uses the engine's missing-health damage
    primitive to interpolate between its locked minimum and maximum. The
    ultimate's bonus attack damage and range grant, and Broken Wings' third
    cast being a location leap rather than a target dash, are excluded rather
    than guessed.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Riven.json",
        "data/raw/16.17.1/communitydragon/champions/92.json",
        "data/raw/16.17.1/communitydragon/champions/riven.bin.json",
    )

    _E_AT_MS = 0
    _W_AT_MS = 600
    _W_STUN_MS = 750
    _Q_AT_MS = 1400
    _Q_INTERVAL_MS = 500
    _Q_KNOCKUP_MS = 750
    _R_AT_MS = 3200

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule the three identical Broken Wings casts.

        :param context: Role-bound Riven and opponent snapshots.
        :return: Three dash-hit events, the last carrying a knock-up.
        """
        base = self._sequence_base(context) + 200
        hit = Decimal(165) + Decimal("0.8") * context.snapshot.bonus_attack_damage
        events: list[ActionEvent] = []
        for index in range(3):
            outputs: tuple[object, ...] = (
                damage(context.opponent_entity, hit, DamageType.PHYSICAL),
            )
            if index == 2:
                outputs = (
                    *outputs,
                    crowd_control(
                        context.opponent_entity, "AIRBORNE", duration_ms=self._Q_KNOCKUP_MS
                    ),
                )
            events.append(
                action(
                    f"RIVEN_Q_BROKEN_WINGS_{index + 1}",
                    at_ms=self._Q_AT_MS + self._Q_INTERVAL_MS * index,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=outputs,
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Riven's shield-open, stun-burst, triple-slash, and R rotation.

        :param context: Role-bound Riven and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        e_shield = Decimal(45) + Decimal("1.1") * context.snapshot.bonus_attack_damage
        w_damage = Decimal(185) + context.snapshot.bonus_attack_damage
        r_min = Decimal(150) + Decimal("0.55") * context.snapshot.bonus_attack_damage
        r_max = Decimal(450) + Decimal("1.65") * context.snapshot.bonus_attack_damage
        r_ratio = (r_max - r_min) / context.opponent_snapshot.max_hp
        fixed = [
            action(
                "RIVEN_E_VALOR",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(shielding(context.self_entity, e_shield, duration_ms=1500),),
                requires_living_opponent=False,
            ),
            action(
                "RIVEN_W_KI_BURST",
                at_ms=self._W_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, w_damage, DamageType.PHYSICAL),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=self._W_STUN_MS),
                ),
            ),
            action(
                "RIVEN_R_BLADE_OF_THE_EXILE",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    MissingHealthDamageOutput(
                        context.opponent_entity, r_min, r_ratio, DamageType.PHYSICAL
                    ),
                ),
            ),
        ]
        events = (*fixed, *self._q_events(context), *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"RIVEN_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "riven_q5_w5_e1_r2_shield_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "RIVEN_R_BONUS_AD_AND_RANGE_BUFF_NOT_MODELED",
                "RIVEN_Q_THIRD_CAST_LEAP_POSITIONING_NOT_MODELED",
                "RIVEN_PASSIVE_RUNIC_BLADE_ON_HIT_NOT_MODELED",
                "RIVEN_RESOURCE_COSTS_NOT_EVALUATED",
                "RIVEN_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Riven and opponent combat snapshots.
        :return: Ordinary basic-attack damage events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 700
        events: list[ActionEvent] = []
        at_ms = 200
        index = 0
        skip_windows = ((self._Q_AT_MS - 100, self._Q_AT_MS + self._Q_INTERVAL_MS * 3),)
        while at_ms <= context.duration_ms:
            if not any(start <= at_ms < end for start, end in skip_windows):
                events.append(
                    action(
                        f"RIVEN_BASIC_ATTACK_{index}",
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
        """Expose the W stun and third-Q knock-up as Riven's control windows.

        :param context: Role-bound Riven and opponent snapshots.
        :return: Deterministic control windows caused by Riven's rotation.
        """
        all_channels = (
            ActionChannel.BASIC_ATTACK,
            ActionChannel.ABILITY,
            ActionChannel.MOVEMENT,
        )
        knockup_at_ms = self._Q_AT_MS + self._Q_INTERVAL_MS * 2
        return ReactionPlan(
            "riven_w_q_control_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "riven_w_ki_burst_stun",
                    self._W_AT_MS,
                    min(self._W_AT_MS + self._W_STUN_MS, context.duration_ms),
                    all_channels,
                    "RIVEN_W_KI_BURST",
                    True,
                    ControlType.STUN,
                ),
                CastBlockWindow(
                    "riven_q_broken_wings_knockup",
                    knockup_at_ms,
                    min(knockup_at_ms + self._Q_KNOCKUP_MS, context.duration_ms),
                    all_channels,
                    "RIVEN_Q_BROKEN_WINGS_3",
                    False,
                    ControlType.AIRBORNE,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose the rotation's dashes as a closing-distance benchmark.

        The rotation casts Broken Wings three times and Valor once, so all four
        dashes are credited at their Data Dragon ranges.

        :param context: Concrete participant context.
        :return: Three Broken Wings ranges plus one Valor range, in game units.
        """
        return Decimal(275) * 3 + Decimal(250)
