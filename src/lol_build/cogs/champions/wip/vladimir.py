"""Vladimir combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, damage, healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatModifierOutput


class VladimirCog(ChampionCog):
    """Model Vladimir's Q5/E5/W1/R2 level-thirteen duel fixture.

    Transfusion casts its base (non-empowered) hit and self-heal, Sanguine
    Pool deals its emerge damage, Tides of Blood resolves at its full-channel
    maximum, and Hemoplague infects the opponent for its locked ``Duration``
    (4 s), raising the damage it takes by ``DamageAmp`` (10%), then detonates
    and heals Vladimir for ``VampPercentFirstChamp`` (100%) of the damage it
    deals. Q's empowered second cast within the buff window and the health
    costs Vladimir pays for W and E are excluded rather than guessed.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Vladimir.json",
        "data/raw/16.17.1/communitydragon/champions/8.json",
        "data/raw/16.17.1/communitydragon/champions/vladimir.bin.json",
    )

    _W_AT_MS = 0
    _E_AT_MS = 800
    _E_CHANNEL_MS = 1500
    _Q_AT_MS = 2600
    _R_AT_MS = 3200
    _R_INFECTION_MS = 4000

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Vladimir's pool, channel, drain, and plague-burst rotation.

        :param context: Role-bound Vladimir and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        w_damage = Decimal(80) + Decimal("0.15") * context.snapshot.bonus_health
        e_damage = (
            Decimal(150)
            + Decimal("0.06") * context.snapshot.max_hp
            + (Decimal("0.8") * context.snapshot.ability_power)
        )
        q_damage = Decimal(160) + Decimal("0.6") * context.snapshot.ability_power
        q_heal = Decimal(40) + Decimal("0.35") * context.snapshot.ability_power
        r_damage = Decimal(250) + Decimal("0.7") * context.snapshot.ability_power
        fixed = [
            action(
                "VLADIMIR_W_SANGUINE_POOL",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, w_damage, DamageType.MAGIC),),
            ),
            action(
                "VLADIMIR_E_TIDES_OF_BLOOD",
                at_ms=self._E_AT_MS + self._E_CHANNEL_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, e_damage, DamageType.MAGIC),),
            ),
            action(
                "VLADIMIR_Q_TRANSFUSION",
                at_ms=self._Q_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q_damage, DamageType.MAGIC),
                    healing(context.self_entity, q_heal),
                ),
            ),
            action(
                "VLADIMIR_R_HEMOPLAGUE",
                at_ms=self._R_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatModifierOutput(
                        context.opponent_entity,
                        "DAMAGE_TAKEN_INCREASE_PERCENT",
                        Decimal("0.10"),
                        self._R_INFECTION_MS,
                    ),
                ),
            ),
        ]
        if context.duration_ms >= self._R_AT_MS + self._R_INFECTION_MS:
            fixed.append(
                action(
                    "VLADIMIR_R_HEMOPLAGUE_DETONATION",
                    at_ms=self._R_AT_MS + self._R_INFECTION_MS,
                    sequence=base + 4,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            r_damage,
                            DamageType.MAGIC,
                            source_heal_ratio=Decimal(1),
                        ),
                    ),
                )
            )
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"VLADIMIR_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "vladimir_q5_e5_w1_r2_pool_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "VLADIMIR_Q_EMPOWERED_SECOND_CAST_NOT_MODELED",
                "VLADIMIR_R_ADDITIONAL_CHAMPION_VAMP_REQUIRES_MORE_TARGETS",
                "VLADIMIR_HEALTH_COST_ABILITIES_NOT_EVALUATED",
                "VLADIMIR_PASSIVE_CRIMSON_PACT_NOT_MODELED",
                "VLADIMIR_RESOURCE_COSTS_NOT_EVALUATED",
                "VLADIMIR_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Vladimir and opponent combat snapshots.
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
                    f"VLADIMIR_BASIC_ATTACK_{index}",
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
        """Report that Vladimir's rotation applies no hostile hard control.

        :param context: Role-bound Vladimir and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "vladimir_no_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
