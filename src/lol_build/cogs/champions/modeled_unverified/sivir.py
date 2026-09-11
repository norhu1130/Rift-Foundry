"""Sivir combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class SivirCog(ChampionCog):
    """Model Sivir's Q5/W5/E1/R2 level-thirteen duel fixture.

    Spell Shield opens the fight for ``SpellShieldDuration``; if it blocks an
    enemy ability, Sivir heals for its rank-one ``TotalHeal`` (``HealRatio`` of
    attack damage plus ``HealAPRatio`` of ability power). If nothing is blocked
    she does not heal. Boomerang Blade strikes on the way out and on the way
    back for its rank-five damage. Ricochet's bounces need further targets,
    and On The Hunt's speed and cooldown refunds are excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Sivir.json",
        "data/raw/16.17.1/communitydragon/champions/15.json",
        "data/raw/16.17.1/communitydragon/champions/sivir.bin.json",
    )

    _E_AT_MS = 0
    _E_SHIELD_MS = 1500
    _Q_AT_MS = 400
    _Q_RETURN_MS = 800
    _FIRST_ATTACK_MS = 200

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Sivir's spell-shield, boomerang, and attack rotation.

        :param context: Role-bound Sivir and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        blade = (
            Decimal(160)
            + Decimal("0.7") * snapshot.bonus_attack_damage
            + Decimal("0.6") * snapshot.ability_power
        )
        heal = Decimal("0.6") * snapshot.attack_damage + Decimal("0.5") * snapshot.ability_power
        events: list[ActionEvent] = [
            action(
                "SIVIR_E_SPELL_SHIELD",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(context.self_entity, "SPELL_SHIELD", self._E_SHIELD_MS),
                    StatusOutput(context.self_entity, "SPELL_SHIELD_HEAL", self._E_SHIELD_MS, heal),
                ),
                requires_living_opponent=False,
            ),
            action(
                "SIVIR_Q_BOOMERANG_BLADE_OUT",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, blade, DamageType.PHYSICAL),),
            ),
            action(
                "SIVIR_Q_BOOMERANG_BLADE_RETURN",
                at_ms=self._Q_AT_MS + self._Q_RETURN_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, blade, DamageType.PHYSICAL),),
            ),
        ]
        interval = self._attack_interval_ms(snapshot.attack_speed)
        for index, at_ms in enumerate(
            range(self._FIRST_ATTACK_MS, context.duration_ms + 1, interval)
        ):
            events.append(
                action(
                    f"SIVIR_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 700 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity, snapshot.attack_damage, DamageType.PHYSICAL
                        ),
                    ),
                )
            )
        level_blockers = (
            () if snapshot.level == 13 else (f"SIVIR_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "sivir_q5_w5_e1_r2_spell_shield_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "SIVIR_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "SIVIR_E_OPENING_CAST_TIMING_ASSUMED",
                "SIVIR_W_RICOCHET_BOUNCES_REQUIRE_MORE_TARGETS",
                "SIVIR_W_AND_R_ATTACK_SPEED_NOT_APPLIED_TO_CADENCE",
                "SIVIR_R_COOLDOWN_REFUNDS_NOT_MODELED",
                "SIVIR_CRITICAL_STRIKE_NOT_MODELED",
                "SIVIR_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Report that Sivir's rotation applies no hostile control.

        :param context: Role-bound Sivir and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "sivir_no_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
