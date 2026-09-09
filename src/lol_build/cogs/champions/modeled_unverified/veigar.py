"""Veigar combat Cog backed by locked 16.17.1 champion sources."""

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


class VeigarCog(ChampionCog):
    """Model Veigar's Q5/W5/E1/R2 level-thirteen duel fixture.

    Event Horizon's cage only stuns an enemy that crosses its edge, which this
    fixture assumes happens once at the cage's locked delay — the same
    guaranteed-hit assumption this codebase already applies to other
    zone-and-skillshot abilities. Primordial Burst's execute-threshold bonus
    against low-health targets is excluded rather than guessed, since its
    locked formula parts did not resolve to a confirmed number.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Veigar.json",
        "data/raw/16.17.1/communitydragon/champions/45.json",
        "data/raw/16.17.1/communitydragon/champions/veigar.bin.json",
    )

    _E_AT_MS = 0
    _E_CAGE_DELAY_MS = 500
    _E_STUN_MS = 2250
    _Q_AT_MS = 600
    _W_AT_MS = 1200
    _W_IMPACT_DELAY_MS = 1200
    _R_AT_MS = 2600

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Veigar's cage-open, strike, delayed-impact, and burst rotation.

        :param context: Role-bound Veigar and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        q_damage = Decimal(240) + Decimal("0.7") * context.snapshot.ability_power
        w_damage = Decimal(305) + Decimal("1.1") * context.snapshot.ability_power
        r_damage = Decimal(175) + Decimal("0.65") * context.snapshot.ability_power
        fixed = [
            action(
                "VEIGAR_E_EVENT_HORIZON",
                at_ms=self._E_AT_MS + self._E_CAGE_DELAY_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    crowd_control(
                        context.opponent_entity, "STUN", duration_ms=self._E_STUN_MS
                    ),
                ),
            ),
            action(
                "VEIGAR_Q_BALEFUL_STRIKE",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.MAGIC),),
            ),
            action(
                "VEIGAR_W_DARK_MATTER",
                at_ms=self._W_AT_MS + self._W_IMPACT_DELAY_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, w_damage, DamageType.MAGIC),),
            ),
            action(
                "VEIGAR_R_PRIMORDIAL_BURST",
                at_ms=self._R_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, r_damage, DamageType.MAGIC),),
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"VEIGAR_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "veigar_q5_w5_e1_r2_cage_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "VEIGAR_E_STUN_ON_ESCAPE_ATTEMPT_ASSUMED",
                "VEIGAR_R_EXECUTE_THRESHOLD_BONUS_NOT_MODELED",
                "VEIGAR_PASSIVE_STACKING_AP_NOT_MODELED",
                "VEIGAR_RESOURCE_COSTS_NOT_EVALUATED",
                "VEIGAR_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Veigar and opponent combat snapshots.
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
                    f"VEIGAR_BASIC_ATTACK_{index}",
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
        """Expose the Event Horizon stun as this Cog's hostile control window.

        :param context: Role-bound Veigar and opponent snapshots.
        :return: Deterministic control windows caused by Veigar's rotation.
        """
        start_ms = self._E_AT_MS + self._E_CAGE_DELAY_MS
        return ReactionPlan(
            "veigar_e_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "veigar_e_event_horizon_stun",
                    start_ms,
                    min(start_ms + self._E_STUN_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "VEIGAR_E_EVENT_HORIZON",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
