"""Rumble combat Cog backed by locked 16.17.1 champion sources."""

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


class RumbleCog(ChampionCog):
    """Model Rumble's Q5/E5/W1/R2 level-thirteen duel fixture.

    Flamespitter's twelve-tick channel is applied as one combined hit equal
    to its full locked total, rather than modeling each 0.25-second tick.
    Electro Harpoon lands its direct hit and slow. The Equalizer assumes the
    opponent stays inside the zone for its full five-second maximum burn and
    applies that total as a single hit at the zone's end. The Heat resource,
    its overheat-empowered variants, and Scrap Shield's defensive-only
    output are excluded rather than guessed.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Rumble.json",
        "data/raw/16.17.1/communitydragon/champions/68.json",
        "data/raw/16.17.1/communitydragon/champions/rumble.bin.json",
    )

    _E_AT_MS = 0
    _E_SLOW_MS = 2000
    _Q_AT_MS = 700
    _Q_CHANNEL_MS = 3000
    _R_AT_MS = 4200
    _R_BURN_MS = 5000

    def engagement_target_slow_fraction(self, context: ParticipantContext) -> Decimal:
        """Slow a retreating opponent with a rank-five Electro Harpoon.

        :param context: Role-bound Rumble encounter context.
        :return: Locked rank-five ``BaseSlowAmount`` as a fraction.
        """
        return Decimal("0.35")

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Rumble's harpoon, flame-channel, and zone-burn rotation.

        :param context: Role-bound Rumble and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        e_damage = Decimal(155) + Decimal("0.5") * context.snapshot.ability_power
        q_damage = Decimal(150) + Decimal("1.05") * context.snapshot.ability_power
        r_dps = Decimal(200) + Decimal("0.35") * context.snapshot.ability_power
        r_total = r_dps * Decimal(5)
        fixed = [
            action(
                "RUMBLE_E_ELECTRO_HARPOON",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    StatModifierOutput(
                        context.opponent_entity,
                        "MOVE_SPEED_PERCENT",
                        Decimal("-0.35"),
                        self._E_SLOW_MS,
                    ),
                ),
            ),
            action(
                "RUMBLE_Q_FLAMESPITTER",
                at_ms=self._Q_AT_MS + self._Q_CHANNEL_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.MAGIC),),
            ),
            action(
                "RUMBLE_R_THE_EQUALIZER",
                at_ms=self._R_AT_MS + self._R_BURN_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, r_total, DamageType.MAGIC),),
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"RUMBLE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "rumble_q5_e5_w1_r2_harpoon_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "RUMBLE_HEAT_RESOURCE_AND_OVERHEAT_VARIANTS_NOT_MODELED",
                "RUMBLE_Q_CHANNEL_MODELED_AS_ONE_TOTAL_HIT",
                "RUMBLE_R_FULL_BURN_EXPOSURE_ASSUMED",
                "RUMBLE_W_SCRAP_SHIELD_NOT_MODELED",
                "RUMBLE_PASSIVE_JUNKYARD_TITAN_NOT_MODELED",
                "RUMBLE_RESOURCE_COSTS_NOT_EVALUATED",
                "RUMBLE_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Rumble and opponent combat snapshots.
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
                    f"RUMBLE_BASIC_ATTACK_{index}",
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
        """Report that Rumble's rotation applies no hostile hard control.

        :param context: Role-bound Rumble and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "rumble_no_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
