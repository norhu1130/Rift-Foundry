"""Zed combat Cog backed by locked 16.17.1 champion sources."""

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


class ZedCog(ChampionCog):
    """Model Zed's Q5/E5/W1/R2 level-thirteen duel fixture.

    Razor Shuriken and Shadow Slash land as direct hits, and Death Mark applies
    its immediate bonus-AD damage. Living Shadow's clone — which mirrors Q and
    E for extra hits — and Death Mark's delayed bonus damage, worth a percent
    of everything dealt to the target during the mark, are both excluded
    rather than guessed: the clone depends on manual repositioning, and the
    delayed bonus needs the timeline's own damage log inside a live window,
    which a Cog cannot read while building its fixed event schedule.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Zed.json",
        "data/raw/16.17.1/communitydragon/champions/238.json",
        "data/raw/16.17.1/communitydragon/champions/zed.bin.json",
    )

    _E_AT_MS = 0
    _E_SLOW_MS = 1500
    _Q_AT_MS = 800
    _R_AT_MS = 1600

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Zed's slash-open, shuriken, and mark rotation.

        :param context: Role-bound Zed and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        e_damage = Decimal(160) + Decimal("0.7") * context.snapshot.bonus_attack_damage
        q_damage = Decimal(240) + context.snapshot.bonus_attack_damage
        r_damage = context.snapshot.bonus_attack_damage
        fixed = [
            action(
                "ZED_E_SHADOW_SLASH",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.PHYSICAL),
                    StatModifierOutput(
                        context.opponent_entity,
                        "MOVE_SPEED_PERCENT",
                        Decimal("-0.40"),
                        self._E_SLOW_MS,
                    ),
                ),
            ),
            action(
                "ZED_Q_RAZOR_SHURIKEN",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.PHYSICAL),),
            ),
            action(
                "ZED_R_DEATH_MARK",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, r_damage, DamageType.PHYSICAL),),
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"ZED_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "zed_q5_e5_w1_r2_slash_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "ZED_W_LIVING_SHADOW_CLONE_DAMAGE_NOT_MODELED",
                "ZED_R_DELAYED_DAMAGE_AMPLIFICATION_NOT_MODELED",
                "ZED_Q_SHADOW_PASS_THROUGH_BONUS_NOT_MODELED",
                "ZED_PASSIVE_CONTEMPT_FOR_THE_WEAK_NOT_MODELED",
                "ZED_RESOURCE_COSTS_NOT_EVALUATED",
                "ZED_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Zed and opponent combat snapshots.
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
                    f"ZED_BASIC_ATTACK_{index}",
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
        """Report that Zed's rotation applies no hostile hard control.

        :param context: Role-bound Zed and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "zed_no_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Living Shadow's swap range as a closing-distance benchmark.

        :param context: Concrete participant context.
        :return: Dash distance in game units.
        """
        return Decimal(650)
