"""Singed combat Cog backed by locked 16.17.1 champion sources."""

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


class SingedCog(ChampionCog):
    """Model Singed's Q5/E5/W1/R2 level-thirteen duel fixture.

    Poison Trail is treated as toggled on for the whole encounter and ticks
    at its locked rate, and Fling lands its damage and root. Insanity
    Potion's own stat gain is applied through the two stats this engine's
    combat math actually consumes; its other stat bonuses and its nearby
    grievous wounds aura are excluded, since the aura's contact is not
    guaranteed. Mega Adhesive slows but deals no damage of its own and is
    excluded for the same reason as Taric's and Zilean's pure-utility spells.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Singed.json",
        "data/raw/16.17.1/communitydragon/champions/27.json",
        "data/raw/16.17.1/communitydragon/champions/singed.bin.json",
    )

    _Q_TICK_MS = 250
    _R_AT_MS = 0
    _R_DURATION_MS = 25000
    _E_AT_MS = 900
    _E_ROOT_MS = 2000

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Poison Trail's ticks, treating it as toggled on throughout.

        :param context: Role-bound Singed and opponent snapshots.
        :return: Evenly spaced poison-tick damage events.
        """
        base = self._sequence_base(context) + 400
        per_second = Decimal(60) + Decimal("0.425") * context.snapshot.ability_power
        tick_damage = per_second * Decimal(self._Q_TICK_MS) / Decimal(1000)
        events: list[ActionEvent] = []
        at_ms = self._Q_TICK_MS
        index = 0
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"SINGED_Q_POISON_TRAIL_TICK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, tick_damage, DamageType.MAGIC),),
                )
            )
            index += 1
            at_ms += self._Q_TICK_MS
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Singed's stat-buff, poison-trail, and fling-root rotation.

        :param context: Role-bound Singed and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        e_damage = (
            Decimal(90)
            + Decimal("0.55") * context.snapshot.ability_power
            + Decimal("0.08") * context.opponent_snapshot.max_hp
        )
        fixed = [
            action(
                "SINGED_R_INSANITY_POTION",
                at_ms=self._R_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatModifierOutput(
                        context.self_entity, "ARMOR", Decimal(55), self._R_DURATION_MS
                    ),
                    StatModifierOutput(
                        context.self_entity,
                        "MAGIC_RESISTANCE",
                        Decimal(55),
                        self._R_DURATION_MS,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "SINGED_E_FLING",
                at_ms=self._E_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity, "ROOT", duration_ms=self._E_ROOT_MS
                    ),
                ),
            ),
        ]
        events = (*fixed, *self._q_events(context), *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"SINGED_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "singed_q5_e5_w1_r2_toggle_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "SINGED_R_FULL_STAT_BONUS_NOT_MODELED",
                "SINGED_R_GRIEVOUS_WOUNDS_AURA_NOT_MODELED",
                "SINGED_W_MEGA_ADHESIVE_NOT_MODELED",
                "SINGED_PASSIVE_NOXIOUS_SLIPSTREAM_NOT_MODELED",
                "SINGED_RESOURCE_COSTS_NOT_EVALUATED",
                "SINGED_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Singed and opponent combat snapshots.
        :return: Ordinary basic-attack damage events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 900
        events: list[ActionEvent] = []
        at_ms = 200
        index = 0
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"SINGED_BASIC_ATTACK_{index}",
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
        """Expose the Fling root as this Cog's hostile control window.

        :param context: Role-bound Singed and opponent snapshots.
        :return: Deterministic control windows caused by Singed's rotation.
        """
        return ReactionPlan(
            "singed_e_root_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "singed_e_fling_root",
                    self._E_AT_MS,
                    min(self._E_AT_MS + self._E_ROOT_MS, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "SINGED_E_FLING",
                    True,
                    ControlType.ROOT,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
