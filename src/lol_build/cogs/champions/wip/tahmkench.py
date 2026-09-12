"""Tahm Kench combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, missing_health_healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class TahmKenchCog(ChampionCog):
    """Model Tahm Kench's Q5/W5/E1/R2 level-thirteen duel fixture.

    Abyssal Dive surfaces under the opponent after its channel for rank-five
    damage and a knock-up. An Acquired Taste adds its level-thirteen
    ``TotalDamage`` (level curve plus 4% of bonus health) to every attack, and
    each damaging hit builds a stack. Tongue Lash deals its rank-five damage,
    slows, heals ``BaseHeal`` plus ``PercentHealthHealing`` of Tahm Kench's
    missing health, and — with three stacks — stuns. Thick Skin's grey health
    needs the damage trace this fixed schedule cannot know, and Devour
    competes with Tongue Lash for the same stacks, so both are excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/TahmKench.json",
        "data/raw/16.17.1/communitydragon/champions/223.json",
        "data/raw/16.17.1/communitydragon/champions/tahmkench.bin.json",
    )

    _W_AT_MS = 0
    _W_LANDING_MS = 1500
    _W_KNOCKUP_MS = 1000
    _Q_STUN_MS = 1500
    _Q_SLOW_MS = 2000
    _ATTACKS_FROM_MS = 1700

    def _passive_damage(self, context: ParticipantContext) -> Decimal:
        """Evaluate An Acquired Taste's on-attack magic damage.

        :param context: Role-bound Tahm Kench snapshot.
        :return: Level-curve damage plus 4% of bonus health.
        """
        level = context.snapshot.level
        curve = Decimal(5) + Decimal(5) * Decimal(level - 1) + (Decimal(5) if level >= 12 else 0)
        return curve + Decimal("0.04") * context.snapshot.bonus_health

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Tahm Kench's dive, stacking attacks, and tongue-lash stun.

        :param context: Role-bound Tahm Kench and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        passive = self._passive_damage(context)
        interval = self._attack_interval_ms(snapshot.attack_speed)
        attack_times = tuple(range(self._ATTACKS_FROM_MS, context.duration_ms + 1, interval))
        # The dive and two attacks give three stacks; Tongue Lash follows them.
        q_at_ms = attack_times[1] + 100 if len(attack_times) > 1 else None
        events: list[ActionEvent] = [
            action(
                "TAHMKENCH_W_ABYSSAL_DIVE",
                at_ms=self._W_LANDING_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("TahmKenchW", "BaseDamage", context, Decimal(240))
                        + Decimal("1.5") * snapshot.ability_power,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity, "AIRBORNE", duration_ms=self._W_KNOCKUP_MS
                    ),
                ),
            )
        ]
        if q_at_ms is not None and q_at_ms <= context.duration_ms:
            events.append(
                action(
                    "TAHMKENCH_Q_TONGUE_LASH",
                    at_ms=q_at_ms,
                    sequence=base + 1,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            self.rank_value("TahmKenchQ", "BaseDamage", context, Decimal(255))
                            + snapshot.ability_power,
                            DamageType.MAGIC,
                        ),
                        crowd_control(context.opponent_entity, "STUN", duration_ms=self._Q_STUN_MS),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=self._Q_SLOW_MS,
                            magnitude=self.rank_value(
                                "TahmKenchW", "ChampRefund", context, Decimal("0.50")
                            ),
                        ),
                        missing_health_healing(
                            context.self_entity,
                            self.rank_value(
                                "TahmKenchQ", "PercentHealthHealing", context, Decimal("0.07")
                            ),
                            base_amount=self.rank_value(
                                "TahmKenchQ", "BaseHeal", context, Decimal(30)
                            ),
                        ),
                    ),
                )
            )
        for index, at_ms in enumerate(attack_times):
            events.append(
                action(
                    f"TAHMKENCH_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 700 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity, snapshot.attack_damage, DamageType.PHYSICAL
                        ),
                        damage(context.opponent_entity, passive, DamageType.MAGIC),
                    ),
                )
            )
        level_blockers = (
            () if snapshot.level == 13 else (f"TAHMKENCH_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "tahmkench_q5_w5_e1_r2_dive_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "TAHMKENCH_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "TAHMKENCH_E_GREY_HEALTH_REQUIRES_DAMAGE_TRACE",
                "TAHMKENCH_R_DEVOUR_COMPETES_WITH_Q_FOR_STACKS",
                "TAHMKENCH_PASSIVE_AP_SCALING_TERM_EXCLUDED",
                "TAHMKENCH_RESOURCE_COSTS_NOT_EVALUATED",
                "TAHMKENCH_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the dive knock-up and tongue-lash stun as control windows.

        :param context: Role-bound Tahm Kench and opponent snapshots.
        :return: Deterministic control windows caused by Tahm Kench's rotation.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        q_at_ms = self._ATTACKS_FROM_MS + interval + 100
        channels = (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT)
        windows = [
            CastBlockWindow(
                "tahmkench_w_abyssal_dive_knockup",
                self._W_LANDING_MS,
                min(self._W_LANDING_MS + self._W_KNOCKUP_MS, context.duration_ms),
                channels,
                "TAHMKENCH_W_ABYSSAL_DIVE",
                False,
                ControlType.AIRBORNE,
            )
        ]
        if q_at_ms < context.duration_ms:
            windows.append(
                CastBlockWindow(
                    "tahmkench_q_tongue_lash_stun",
                    q_at_ms,
                    min(q_at_ms + self._Q_STUN_MS, context.duration_ms),
                    channels,
                    "TAHMKENCH_Q_TONGUE_LASH",
                    True,
                    ControlType.STUN,
                )
            )
        return ReactionPlan(
            "tahmkench_w_q_control_reaction_v1",
            cast_block_windows=tuple(windows),
            blockers=(*self.verification_blockers(),),
        )
