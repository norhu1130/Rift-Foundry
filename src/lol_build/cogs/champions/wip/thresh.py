"""Thresh combat Cog backed by locked 16.17.1 champion sources."""

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


class ThreshCog(ChampionCog):
    """Model Thresh's Q5/E5/W1/R2 level-thirteen duel fixture.

    Death Sentence binds the opponent for ``TauntLength``, Flay's active lands
    its rank-five damage and slow, and The Box is broken once for its rank-two
    damage and slow. Flay's passive charges over ``FullChargeDuration``: each
    attack adds up to its rank-five ``PassiveADRatio`` of attack damage as
    magic damage in proportion to the time since the previous attack, with the
    opening attack fully charged. Dark Passage only shields allied champions,
    and soul stacks accrue outside the encounter.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Thresh.json",
        "data/raw/16.17.1/communitydragon/champions/412.json",
        "data/raw/16.17.1/communitydragon/champions/thresh.bin.json",
    )

    _Q_AT_MS = 0
    _Q_BIND_MS = 1500
    _E_AT_MS = 1700
    _E_SLOW_MS = 1000
    _R_AT_MS = 2400
    _R_BREAK_DELAY_MS = 500
    _R_SLOW_MS = 2000
    _FULL_CHARGE_MS = 10_000
    _ATTACKS_FROM_MS = 1500

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Thresh's hook, flay, box, and charged-attack rotation.

        :param context: Role-bound Thresh and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        ap = snapshot.ability_power
        events: list[ActionEvent] = [
            action(
                "THRESH_Q_DEATH_SENTENCE",
                at_ms=self._Q_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("ThreshQ", "BaseDamage", context, Decimal(300))
                        + Decimal("0.9") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=self._Q_BIND_MS),
                ),
            ),
            action(
                "THRESH_E_FLAY",
                at_ms=self._E_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("ThreshE", "ActiveBaseDamage", context, Decimal(245))
                        + Decimal("0.6") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=self._E_SLOW_MS,
                        magnitude=Decimal("0.40"),
                    ),
                ),
            ),
        ]
        box_ms = self._R_AT_MS + self._R_BREAK_DELAY_MS
        if box_ms <= context.duration_ms:
            events.append(
                action(
                    "THRESH_R_THE_BOX_WALL_BROKEN",
                    at_ms=box_ms,
                    sequence=base + 2,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, Decimal(400) + ap, DamageType.MAGIC),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=self._R_SLOW_MS,
                            magnitude=Decimal("0.99"),
                        ),
                    ),
                )
            )
        interval = self._attack_interval_ms(snapshot.attack_speed)
        previous: int | None = None
        for index, at_ms in enumerate(
            range(self._ATTACKS_FROM_MS, context.duration_ms + 1, interval)
        ):
            charge = (
                Decimal(1)
                if previous is None
                else min(Decimal(1), Decimal(at_ms - previous) / Decimal(self._FULL_CHARGE_MS))
            )
            previous = at_ms
            events.append(
                action(
                    f"THRESH_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 700 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity, snapshot.attack_damage, DamageType.PHYSICAL
                        ),
                        damage(
                            context.opponent_entity,
                            self.rank_value("ThreshE", "PassiveADRatioTT", context, Decimal("2.10"))
                            * snapshot.attack_damage
                            * charge,
                            DamageType.MAGIC,
                        ),
                    ),
                )
            )
        level_blockers = (
            () if snapshot.level == 13 else (f"THRESH_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "thresh_q5_e5_w1_r2_hook_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "THRESH_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "THRESH_W_LANTERN_SHIELD_REQUIRES_ALLIES",
                "THRESH_PASSIVE_SOUL_STACKS_OUTSIDE_SCENARIO",
                "THRESH_E_KNOCKBACK_DURATION_NOT_IN_LOCKED_DATA",
                "THRESH_R_SINGLE_WALL_BROKEN_ASSUMED",
                "THRESH_Q_RECAST_LEAP_NOT_MODELED",
                "THRESH_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the Death Sentence bind as this Cog's hostile control window.

        :param context: Role-bound Thresh and opponent snapshots.
        :return: Deterministic control windows caused by Thresh's rotation.
        """
        return ReactionPlan(
            "thresh_q_bind_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "thresh_q_death_sentence_bind",
                    self._Q_AT_MS,
                    min(self._Q_AT_MS + self._Q_BIND_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "THRESH_Q_DEATH_SENTENCE",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
