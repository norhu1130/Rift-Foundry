"""Taric combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatModifierOutput


class TaricCog(ChampionCog):
    """Model Taric's E5/W5/Q1/R2 level-thirteen duel fixture.

    Bastion grants its armor buff and shield, Starlight's Touch heals, and
    Dazzle lands its charged stun and damage. Cosmic Radiance is excluded
    rather than guessed: it grants allies (not Taric alone, meaningfully)
    invulnerability after a 2.5-second delay and deals no damage of its own,
    so it has no combat contribution to model in a solo duel.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Taric.json",
        "data/raw/16.17.1/communitydragon/champions/44.json",
        "data/raw/16.17.1/communitydragon/champions/taric.bin.json",
    )

    _W_AT_MS = 0
    _W_SHIELD_MS = 2500
    _Q_AT_MS = 600
    _E_AT_MS = 1200
    _E_CHARGE_MS = 1000
    _E_STUN_MS = 1500

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Taric's shield-open, heal, and charged-stun rotation.

        :param context: Role-bound Taric and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        w_shield = Decimal("0.11") * context.snapshot.max_hp
        q_heal = (
            Decimal(25)
            + Decimal("0.15") * context.snapshot.ability_power
            + Decimal("0.01") * context.snapshot.bonus_health
        )
        e_damage = (
            Decimal(250)
            + Decimal("0.5") * context.snapshot.ability_power
            + Decimal("0.5") * (context.snapshot.armor * Decimal("0.10"))
        )
        fixed = [
            action(
                "TARIC_W_BASTION",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatModifierOutput(
                        context.self_entity,
                        "ARMOR",
                        context.snapshot.armor * Decimal("0.10"),
                        999_999,
                    ),
                    shielding(context.self_entity, w_shield, duration_ms=self._W_SHIELD_MS),
                ),
                requires_living_opponent=False,
            ),
            action(
                "TARIC_Q_STARLIGHTS_TOUCH",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(healing(context.self_entity, q_heal),),
                requires_living_opponent=False,
            ),
            action(
                "TARIC_E_DAZZLE",
                at_ms=self._E_AT_MS + self._E_CHARGE_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity, "STUN", duration_ms=self._E_STUN_MS
                    ),
                ),
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"TARIC_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "taric_e5_w5_q1_r2_shield_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "TARIC_R_COSMIC_RADIANCE_NOT_APPLICABLE_IN_DUEL",
                "TARIC_PASSIVE_BRAVADO_EMPOWERED_ATTACK_NOT_MODELED",
                "TARIC_W_ALLY_ARMOR_SHARE_NOT_MODELED",
                "TARIC_RESOURCE_COSTS_NOT_EVALUATED",
                "TARIC_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Taric and opponent combat snapshots.
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
                    f"TARIC_BASIC_ATTACK_{index}",
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
        """Expose the Dazzle stun as this Cog's hostile control window.

        :param context: Role-bound Taric and opponent snapshots.
        :return: Deterministic control windows caused by Taric's rotation.
        """
        start_ms = self._E_AT_MS + self._E_CHARGE_MS
        return ReactionPlan(
            "taric_e_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "taric_e_dazzle_stun",
                    start_ms,
                    min(start_ms + self._E_STUN_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "TARIC_E_DAZZLE",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
