"""Yasuo combat Cog backed by locked 16.17.1 champion sources."""

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


class YasuoCog(ChampionCog):
    """Model Yasuo's Q5/E5/W1/R2 level-thirteen duel fixture.

    Steel Tempest casts three times at the same locked damage, the third
    firing an empowered tornado once two stacks are up; Last Breath follows
    immediately while that tornado holds the target airborne, matching the
    combo the kit's own locked text describes rather than guessing an
    unconditional cast. Sweeping Blade lands a single dash hit without its
    stacking bonus, and Wind Wall is excluded, since it blocks projectiles
    rather than dealing damage.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Yasuo.json",
        "data/raw/16.17.1/communitydragon/champions/157.json",
        "data/raw/16.17.1/communitydragon/champions/yasuo.bin.json",
    )

    _Q_AT_MS = 0
    _Q_INTERVAL_MS = 450
    _Q3_KNOCKUP_MS = 1000
    _R_DELAY_AFTER_Q3_MS = 100
    _R_EXTRA_KNOCKUP_MS = 1000
    _E_AT_MS = 2400

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule the three Steel Tempest casts, the third a knock-up tornado.

        :param context: Role-bound Yasuo and opponent snapshots.
        :return: Three dash-hit events, the last carrying a knock-up.
        """
        base = self._sequence_base(context)
        hit = Decimal(120) + Decimal("1.05") * context.snapshot.bonus_attack_damage
        events: list[ActionEvent] = []
        for index in range(3):
            outputs: tuple[object, ...] = (
                damage(context.opponent_entity, hit, DamageType.PHYSICAL),
            )
            if index == 2:
                outputs = (
                    *outputs,
                    crowd_control(
                        context.opponent_entity, "AIRBORNE", duration_ms=self._Q3_KNOCKUP_MS
                    ),
                )
            events.append(
                action(
                    f"YASUO_Q_STEEL_TEMPEST_{index + 1}",
                    at_ms=self._Q_AT_MS + self._Q_INTERVAL_MS * index,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=outputs,
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Yasuo's triple-thrust, airborne-follow, and dash rotation.

        :param context: Role-bound Yasuo and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context) + 100
        r_damage = Decimal(350) + Decimal("1.5") * context.snapshot.bonus_attack_damage
        e_damage = (
            Decimal(130)
            + Decimal("0.2") * context.snapshot.bonus_attack_damage
            + Decimal("0.6") * context.snapshot.ability_power
        )
        r_at_ms = self._Q_AT_MS + self._Q_INTERVAL_MS * 2 + self._R_DELAY_AFTER_Q3_MS
        fixed = [
            action(
                "YASUO_R_LAST_BREATH",
                at_ms=r_at_ms,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.PHYSICAL),
                    crowd_control(
                        context.opponent_entity,
                        "AIRBORNE",
                        duration_ms=self._R_EXTRA_KNOCKUP_MS,
                    ),
                ),
            ),
            action(
                "YASUO_E_SWEEPING_BLADE",
                at_ms=self._E_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, e_damage, DamageType.MAGIC),),
            ),
        ]
        events = (*self._q_events(context), *fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"YASUO_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "yasuo_q5_e5_w1_r2_tornado_follow_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "YASUO_E_STACKING_BONUS_DAMAGE_NOT_MODELED",
                "YASUO_W_WIND_WALL_NOT_APPLICABLE_IN_DUEL",
                "YASUO_R_ARMOR_PENETRATION_BUFF_NOT_MODELED",
                "YASUO_PASSIVE_SHIELD_AND_CRIT_NOT_MODELED",
                "YASUO_RESOURCE_COSTS_NOT_EVALUATED",
                "YASUO_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Yasuo and opponent combat snapshots.
        :return: Ordinary basic-attack damage events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 700
        events: list[ActionEvent] = []
        at_ms = 200
        index = 0
        skip_windows = ((self._Q_AT_MS - 100, self._Q_AT_MS + self._Q_INTERVAL_MS * 3),)
        while at_ms <= context.duration_ms:
            if not any(start <= at_ms < end for start, end in skip_windows):
                events.append(
                    action(
                        f"YASUO_BASIC_ATTACK_{index}",
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
        """Expose the Q3 and R knock-ups as Yasuo's control windows.

        :param context: Role-bound Yasuo and opponent snapshots.
        :return: Deterministic control windows caused by Yasuo's rotation.
        """
        all_channels = (
            ActionChannel.BASIC_ATTACK,
            ActionChannel.ABILITY,
            ActionChannel.MOVEMENT,
        )
        q3_at_ms = self._Q_AT_MS + self._Q_INTERVAL_MS * 2
        r_at_ms = q3_at_ms + self._R_DELAY_AFTER_Q3_MS
        return ReactionPlan(
            "yasuo_q3_r_knockup_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "yasuo_q3_tornado_knockup",
                    q3_at_ms,
                    min(q3_at_ms + self._Q3_KNOCKUP_MS, context.duration_ms),
                    all_channels,
                    "YASUO_Q_STEEL_TEMPEST_3",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "yasuo_r_last_breath_knockup",
                    r_at_ms,
                    min(r_at_ms + self._R_EXTRA_KNOCKUP_MS, context.duration_ms),
                    all_channels,
                    "YASUO_R_LAST_BREATH",
                    False,
                    ControlType.AIRBORNE,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
