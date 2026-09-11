"""Sejuani combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent


class SejuaniCog(ChampionCog):
    """Model Sejuani's Q5/W5/E1/R2 level-thirteen duel fixture.

    Arctic Assault dashes into a knock-up hit, Winter's Wrath lands both
    strikes, and Glacial Prison resolves at its guaranteed minimum stun and
    damage. Permafrost's active requires four pre-applied stacks this fixture
    does not track, so it is excluded rather than assumed applied; R's
    extended stun and ice storm, which require the bola to travel a quarter
    of its range, are excluded for the same reason.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Sejuani.json",
        "data/raw/16.17.1/communitydragon/champions/113.json",
        "data/raw/16.17.1/communitydragon/champions/sejuani.bin.json",
    )

    _W_AT_MS = 0
    _W_SECOND_HIT_DELAY_MS = 250
    _Q_AT_MS = 900
    _Q_KNOCKUP_MS = 500
    _R_AT_MS = 1900
    _R_STUN_MS = 1000

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Sejuani's double-strike, dash-knockup, and stun rotation.

        :param context: Role-bound Sejuani and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        w_first = (
            Decimal(45)
            + Decimal("0.3") * context.snapshot.ability_power
            + Decimal("0.04") * context.snapshot.bonus_health
        )
        w_second = (
            Decimal(85)
            + Decimal("0.6") * context.snapshot.ability_power
            + Decimal("0.08") * context.snapshot.bonus_health
        )
        q_damage = Decimal(290) + Decimal("0.75") * context.snapshot.ability_power
        r_damage = Decimal(150) + Decimal("0.4") * context.snapshot.ability_power
        fixed = [
            action(
                "SEJUANI_W_WINTERS_WRATH_1",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, w_first, DamageType.PHYSICAL),),
            ),
            action(
                "SEJUANI_W_WINTERS_WRATH_2",
                at_ms=self._W_AT_MS + self._W_SECOND_HIT_DELAY_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, w_second, DamageType.PHYSICAL),),
            ),
            action(
                "SEJUANI_Q_ARCTIC_ASSAULT",
                at_ms=self._Q_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity, "AIRBORNE", duration_ms=self._Q_KNOCKUP_MS
                    ),
                ),
            ),
            action(
                "SEJUANI_R_GLACIAL_PRISON",
                at_ms=self._R_AT_MS,
                sequence=base + 3,
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
            else (f"SEJUANI_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "sejuani_q5_w5_e1_r2_double_strike_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "SEJUANI_E_PERMAFROST_REQUIRES_UNTRACKED_STACKS_NOT_MODELED",
                "SEJUANI_R_EMPOWERED_TRAVEL_DISTANCE_VARIANT_NOT_MODELED",
                "SEJUANI_PASSIVE_FURY_OF_THE_NORTH_NOT_MODELED",
                "SEJUANI_RESOURCE_COSTS_NOT_EVALUATED",
                "SEJUANI_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Sejuani and opponent combat snapshots.
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
                    f"SEJUANI_BASIC_ATTACK_{index}",
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
        """Expose the Q knock-up and R stun as Sejuani's control windows.

        :param context: Role-bound Sejuani and opponent snapshots.
        :return: Deterministic control windows caused by Sejuani's rotation.
        """
        all_channels = (
            ActionChannel.BASIC_ATTACK,
            ActionChannel.ABILITY,
            ActionChannel.MOVEMENT,
        )
        return ReactionPlan(
            "sejuani_q_r_control_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "sejuani_q_arctic_assault_knockup",
                    self._Q_AT_MS,
                    min(self._Q_AT_MS + self._Q_KNOCKUP_MS, context.duration_ms),
                    all_channels,
                    "SEJUANI_Q_ARCTIC_ASSAULT",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "sejuani_r_glacial_prison_stun",
                    self._R_AT_MS,
                    min(self._R_AT_MS + self._R_STUN_MS, context.duration_ms),
                    all_channels,
                    "SEJUANI_R_GLACIAL_PRISON",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Arctic Assault's locked cast range as its closing distance.

        :param context: Concrete participant context.
        :return: Dash distance in game units.
        """
        return Decimal(625)
