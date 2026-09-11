"""Shen combat Cog backed by locked 16.17.1 champion sources."""

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


class ShenCog(ChampionCog):
    """Model Shen's Q5/E5/W1/R2 level-thirteen duel fixture.

    Twilight Assault's percent-health bonus is computed against the known
    opponent snapshot and applied to the next three attacks in place, and
    Shadow Dash lands its dash-taunt hit. Spirit's Refuge blocks no combat
    output in this timeline (it carries no locked damage or shield data of
    its own) and Stand United shields an ally rather than Shen, so neither
    contributes to a solo duel; both are excluded rather than guessed.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Shen.json",
        "data/raw/16.17.1/communitydragon/champions/98.json",
        "data/raw/16.17.1/communitydragon/champions/shen.bin.json",
    )

    _Q_AT_MS = 200
    _E_AT_MS = 1400
    _E_TAUNT_MS = 1500

    def _q_percent_damage(self, context: ParticipantContext) -> Decimal:
        """Compute Twilight Assault's per-hit percent-health bonus.

        :param context: Role-bound Shen and opponent snapshots.
        :return: Flat magic damage equal to the locked percent of the
            opponent's known max health at this snapshot.
        """
        percent = Decimal("0.04") + Decimal("0.00015") * context.snapshot.ability_power
        return percent * context.opponent_snapshot.max_hp

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule the three Twilight Assault empowered attacks.

        :param context: Role-bound Shen and opponent snapshots.
        :return: Three empowered basic-attack events.
        """
        base = self._sequence_base(context)
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        bonus = self._q_percent_damage(context)
        events: list[ActionEvent] = []
        for index in range(3):
            events.append(
                action(
                    f"SHEN_Q_TWILIGHT_ASSAULT_{index + 1}",
                    at_ms=self._Q_AT_MS + interval * index,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            context.snapshot.attack_damage,
                            DamageType.PHYSICAL,
                        ),
                        damage(context.opponent_entity, bonus, DamageType.MAGIC),
                    ),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Shen's empowered-attack and dash-taunt rotation.

        :param context: Role-bound Shen and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context) + 100
        e_damage = Decimal(160) + Decimal("0.11") * context.snapshot.bonus_health
        fixed = [
            action(
                "SHEN_E_SHADOW_DASH",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.PHYSICAL),
                    crowd_control(context.opponent_entity, "TAUNT", duration_ms=self._E_TAUNT_MS),
                ),
            ),
        ]
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        events = (
            *self._q_events(context),
            *fixed,
            *self._basic_attack_events(context, start_ms=self._Q_AT_MS + interval * 3),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"SHEN_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "shen_q5_e5_w1_r2_empowered_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "SHEN_W_SPIRITS_REFUGE_NOT_MODELED",
                "SHEN_R_STAND_UNITED_NOT_APPLICABLE_IN_DUEL",
                "SHEN_PASSIVE_KI_BARRIER_SHIELD_NOT_MODELED",
                "SHEN_RESOURCE_COSTS_NOT_EVALUATED",
                "SHEN_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(
        self, context: ParticipantContext, *, start_ms: int
    ) -> tuple[ActionEvent, ...]:
        """Fill remaining time with ordinary basic attacks after Q's empowerment.

        :param context: Role-bound Shen and opponent combat snapshots.
        :param start_ms: First millisecond eligible for a plain basic attack.
        :return: Ordinary basic-attack damage events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 700
        events: list[ActionEvent] = []
        at_ms = start_ms
        index = 0
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"SHEN_BASIC_ATTACK_{index}",
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
        """Expose the Shadow Dash taunt as this Cog's hostile control window.

        :param context: Role-bound Shen and opponent snapshots.
        :return: Deterministic control windows caused by Shen's rotation.
        """
        return ReactionPlan(
            "shen_e_taunt_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "shen_e_shadow_dash_taunt",
                    self._E_AT_MS,
                    min(self._E_AT_MS + self._E_TAUNT_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "SHEN_E_SHADOW_DASH",
                    True,
                    ControlType.TAUNT,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Shadow Dash's locked cast range as its closing distance.

        :param context: Concrete participant context.
        :return: Dash distance in game units.
        """
        return Decimal(600)
