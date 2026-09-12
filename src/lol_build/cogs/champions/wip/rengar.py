"""Rengar combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatModifierOutput


class RengarCog(ChampionCog):
    """Model Rengar's R2/Q5/E5/W1 level-thirteen duel fixture.

    Thrill of the Hunt ends in a leap attack that strips its rank-two
    ``ArmorShred``. Savagery empowers the next attack with ``BaseDamage`` plus
    ``BaseADRatio`` of attack damage, Bola Strike lands its rank-five damage
    and slow, and Battle Roar deals its rank-one damage. Battle Roar's heal
    returns a share of the damage taken in the previous 1.5 seconds, which a
    fixed schedule cannot know in advance, and Ferocity-empowered casts depend
    on a resource this fixture does not track; both are excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Rengar.json",
        "data/raw/16.17.1/communitydragon/champions/107.json",
        "data/raw/16.17.1/communitydragon/champions/rengar.bin.json",
    )

    _LEAP_AT_MS = 0
    _ARMOR_SHRED_MS = 4000
    _Q_AT_MS = 400
    _E_AT_MS = 800
    _E_SLOW_MS = 1750
    _W_AT_MS = 1200
    _BASIC_ATTACKS_FROM_MS = 1600

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Rengar's leap, savagery, bola, and roar rotation.

        :param context: Role-bound Rengar and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        ad = context.snapshot.attack_damage
        fixed = [
            action(
                "RENGAR_R_LEAP_ATTACK",
                at_ms=self._LEAP_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    StatModifierOutput(
                        context.opponent_entity, "ARMOR", Decimal(-20), self._ARMOR_SHRED_MS
                    ),
                    damage(context.opponent_entity, ad, DamageType.PHYSICAL),
                ),
            ),
            action(
                "RENGAR_Q_SAVAGERY",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity,
                        ad + Decimal(125) + Decimal("0.05") * ad,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
            action(
                "RENGAR_E_BOLA_STRIKE",
                at_ms=self._E_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("RengarE", "BaseDamage", context, Decimal(235))
                        + Decimal("0.8") * context.snapshot.bonus_attack_damage,
                        DamageType.PHYSICAL,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=self._E_SLOW_MS,
                        magnitude=Decimal("0.75"),
                    ),
                ),
            ),
            action(
                "RENGAR_W_BATTLE_ROAR",
                at_ms=self._W_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(50) + Decimal("0.8") * context.snapshot.ability_power,
                        DamageType.MAGIC,
                    ),
                ),
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"RENGAR_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "rengar_r2_q5_e5_w1_leap_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "RENGAR_LEVEL13_R2_Q5_E5_W1_POLICY_UNVERIFIED",
                "RENGAR_W_RECENT_DAMAGE_HEAL_REQUIRES_DAMAGE_TRACE",
                "RENGAR_FEROCITY_EMPOWERED_ABILITIES_NOT_MODELED",
                "RENGAR_ABILITY_COOLDOWNS_NOT_IN_LOCKED_SPELL_DATA",
                "RENGAR_PASSIVE_BONETOOTH_STACKS_OUTSIDE_SCENARIO",
                "RENGAR_R_CAMOUFLAGE_AND_LEAP_RANGE_NOT_MODELED",
                "RENGAR_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time after the spell rotation with ordinary basic attacks.

        :param context: Role-bound Rengar and opponent combat snapshots.
        :return: Ordinary basic-attack damage events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 700
        events: list[ActionEvent] = []
        at_ms = self._BASIC_ATTACKS_FROM_MS
        index = 0
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"RENGAR_BASIC_ATTACK_{index}",
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
        """Report that Rengar's unempowered rotation applies no hard control.

        :param context: Role-bound Rengar and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "rengar_no_hard_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
