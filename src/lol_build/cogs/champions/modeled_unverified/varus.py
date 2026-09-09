"""Varus combat Cog backed by locked 16.17.1 champion sources."""

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


class VarusCog(ChampionCog):
    """Model Varus's Q5/E5/W1/R2 level-thirteen duel fixture.

    Piercing Arrow resolves at its guaranteed minimum-charge value, since full
    charge and range falloff depend on hold time and distance this fixture
    does not vary. Hail of Arrows lands its direct hit, and Chain of
    Corruption roots and deals its area damage. Blighted Quiver's stacking
    on-hit debuff and its interaction with Q's execute and R's stack grant are
    excluded rather than guessed, since they depend on a stack count this
    fixture does not track.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Varus.json",
        "data/raw/16.17.1/communitydragon/champions/110.json",
        "data/raw/16.17.1/communitydragon/champions/varus.bin.json",
    )

    _E_AT_MS = 0
    _E_SLOW_MS = 4000
    _Q_AT_MS = 900
    _R_AT_MS = 1800
    _R_ROOT_MS = 2000

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Varus's grievous-open, piercing-shot, and root rotation.

        :param context: Role-bound Varus and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        q_max = Decimal(360) + Decimal("1.2") * context.snapshot.bonus_attack_damage
        q_damage = Decimal("0.33") * q_max
        e_damage = Decimal(180) + Decimal("0.9") * context.snapshot.bonus_attack_damage
        r_damage = Decimal(250) + context.snapshot.ability_power
        fixed = [
            action(
                "VARUS_E_HAIL_OF_ARROWS",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.PHYSICAL),
                    StatModifierOutput(
                        context.opponent_entity,
                        "MOVE_SPEED_PERCENT",
                        Decimal("-0.50"),
                        self._E_SLOW_MS,
                    ),
                ),
            ),
            action(
                "VARUS_Q_PIERCING_ARROW",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.PHYSICAL),),
            ),
            action(
                "VARUS_R_CHAIN_OF_CORRUPTION",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity, "ROOT", duration_ms=self._R_ROOT_MS
                    ),
                ),
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"VARUS_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "varus_q5_e5_w1_r2_grievous_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "VARUS_Q_FULL_CHARGE_AND_FALLOFF_NOT_MODELED",
                "VARUS_W_BLIGHT_STACKING_AND_EXECUTE_NOT_MODELED",
                "VARUS_E_GRIEVOUS_WOUNDS_NOT_MODELED",
                "VARUS_PASSIVE_LIVING_VENGEANCE_NOT_MODELED",
                "VARUS_RESOURCE_COSTS_NOT_EVALUATED",
                "VARUS_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Varus and opponent combat snapshots.
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
                    f"VARUS_BASIC_ATTACK_{index}",
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
        """Expose the Chain of Corruption root as this Cog's control window.

        :param context: Role-bound Varus and opponent snapshots.
        :return: Deterministic control windows caused by Varus's rotation.
        """
        return ReactionPlan(
            "varus_r_root_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "varus_r_chain_of_corruption_root",
                    self._R_AT_MS,
                    min(self._R_AT_MS + self._R_ROOT_MS, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "VARUS_R_CHAIN_OF_CORRUPTION",
                    True,
                    ControlType.ROOT,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
