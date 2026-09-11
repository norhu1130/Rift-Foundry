"""Yorick combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, missing_health_healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    CurrentHealthDamageOutput,
    ResistanceReductionOutput,
)


class YorickCog(ChampionCog):
    """Model Yorick's Q5/E5/W1/R2 level-thirteen duel fixture.

    Eulogy of the Isles summons the Maiden, whose mark makes Yorick's attacks
    deal ``RMarkDamagePercent`` of the target's maximum health. Mourning Mist
    deals its current-health magic damage, slows, and strips ``ArmorShred``
    of the target's armor. Last Rites empowers the next attack with
    ``BaseDamage`` plus ``BonusDamageAD`` of attack damage and heals Yorick for
    ``QHeal`` plus ``MissingHealthRatio`` of his missing health. Mist Walkers,
    the Maiden's own attacks, and Dark Procession's wall are summons or
    terrain this two-participant timeline cannot host.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Yorick.json",
        "data/raw/16.17.1/communitydragon/champions/83.json",
        "data/raw/16.17.1/communitydragon/champions/yorick.bin.json",
    )

    _R_AT_MS = 0
    _R_SUMMON_DELAY_MS = 1000
    _E_AT_MS = 300
    _E_SLOW_MS = 1500
    _E_MARK_MS = 4000
    _Q_AT_MS = 700
    _BASIC_ATTACKS_FROM_MS = 1500

    def _q_heal(self, level: int) -> Decimal:
        """Evaluate the locked ``QHeal`` level curve.

        :param level: Champion level.
        :return: Flat Last Rites heal before the missing-health portion.
        """
        return self._level_breakpoint_value(
            Decimal(10), Decimal(2), ((7, Decimal(3)), (13, Decimal(5))), level
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Yorick's maiden, mist, and last-rites rotation.

        :param context: Role-bound Yorick and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        ad = context.snapshot.attack_damage
        ap = context.snapshot.ability_power
        mark_damage = Decimal("0.02") * context.opponent_snapshot.max_hp
        fixed = [
            action(
                "YORICK_E_MOURNING_MIST",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    CurrentHealthDamageOutput(
                        context.opponent_entity,
                        (Decimal(8) + Decimal("0.03") * ap) / Decimal(100),
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=self._E_SLOW_MS,
                        magnitude=Decimal("0.30"),
                    ),
                    ResistanceReductionOutput(
                        recipient=context.opponent_entity,
                        stat="ARMOR",
                        fraction_per_stack=Decimal("0.25"),
                        max_stacks=1,
                        duration_ms=self._E_MARK_MS,
                        state_key="YORICK_E_MOURNING_MIST",
                    ),
                ),
            ),
            action(
                "YORICK_Q_LAST_RITES",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity,
                        ad + Decimal(110) + Decimal("0.5") * ad,
                        DamageType.PHYSICAL,
                    ),
                    missing_health_healing(
                        context.self_entity,
                        Decimal("0.10"),
                        base_amount=self._q_heal(context.snapshot.level),
                    ),
                ),
            ),
        ]
        attacks = self._basic_attack_events(context, mark_damage)
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"YORICK_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "yorick_q5_e5_w1_r2_maiden_open_level13_v1",
            tuple(sorted((*fixed, *attacks), key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "YORICK_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "YORICK_Q_HEAL_LEVEL_CURVE_CONVENTION_ASSUMED",
                "YORICK_Q_MISSING_HEALTH_RATIO_READ_AS_HEAL_FRACTION",
                "YORICK_SUMMONS_MAIDEN_AND_WALKERS_NOT_REPRESENTABLE",
                "YORICK_W_WALL_TERRAIN_NOT_MODELED",
                "YORICK_RESOURCE_COSTS_NOT_EVALUATED",
                "YORICK_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(
        self, context: ParticipantContext, mark_damage: Decimal
    ) -> tuple[ActionEvent, ...]:
        """Schedule attacks, marked by the Maiden once she has arrived.

        :param context: Role-bound Yorick and opponent combat snapshots.
        :param mark_damage: Maiden mark bonus per attack on the marked target.
        :return: Basic-attack damage events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 700
        events: list[ActionEvent] = []
        at_ms = self._BASIC_ATTACKS_FROM_MS
        index = 0
        while at_ms <= context.duration_ms:
            outputs = [
                damage(context.opponent_entity, context.snapshot.attack_damage, DamageType.PHYSICAL)
            ]
            if at_ms >= self._R_AT_MS + self._R_SUMMON_DELAY_MS:
                outputs.append(damage(context.opponent_entity, mark_damage, DamageType.MAGIC))
            events.append(
                action(
                    f"YORICK_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
            index += 1
            at_ms += interval
        return tuple(events)

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Report that Yorick's rotation applies no hard control.

        :param context: Role-bound Yorick and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "yorick_no_hard_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
