"""Yone combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class YoneCog(ChampionCog):
    """Model Yone's Q5/W5/E1/R2 level-thirteen duel fixture.

    Mortal Steel casts three times at the same locked damage, the third
    knocking up on a wind-wave dash; Spirit Cleave splits its hit and
    maximum-health bonus evenly between physical and magic and grants a
    shield; Fate Sealed strikes for its full locked value in both damage
    types at once and knocks up. Soul Unbound is excluded rather than
    guessed: its real damage is a percentage of whatever Yone deals while in
    spirit form, repeated back on return, which this fixed rotation cannot
    resolve without assuming a specific window of prior damage.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Yone.json",
        "data/raw/16.17.1/communitydragon/champions/777.json",
        "data/raw/16.17.1/communitydragon/champions/yone.bin.json",
    )

    _W_AT_MS = 0
    _Q_AT_MS = 900
    _Q_INTERVAL_MS = 450
    _Q3_KNOCKUP_MS = 750
    _R_DELAY_AFTER_Q3_MS = 100
    _R_KNOCKUP_MS = 750

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule the three Mortal Steel casts, the third a knock-up dash.

        :param context: Role-bound Yone and opponent snapshots.
        :return: Three thrust-hit events, the last carrying a knock-up.
        """
        base = self._sequence_base(context)
        hit = Decimal(125) + Decimal("1.1") * context.snapshot.bonus_attack_damage
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
                    f"YONE_Q_MORTAL_STEEL_{index + 1}",
                    at_ms=self._Q_AT_MS + self._Q_INTERVAL_MS * index,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=outputs,
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Yone's cleave-open, triple-thrust, and fate-sealed rotation.

        :param context: Role-bound Yone and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context) + 100
        w_split = Decimal(25) + Decimal("0.06") * context.opponent_snapshot.max_hp
        # ByCharLevelInterpolation(40 at level 1, 90 at level 18), evaluated at
        # level 13: 40 + (90 - 40) * (13 - 1) / (18 - 1).
        w_shield = (
            Decimal(40)
            + Decimal(50) * Decimal(12) / Decimal(17)
            + Decimal("0.65") * context.snapshot.bonus_attack_damage
        )
        r_damage = Decimal(400) + Decimal("0.8") * context.snapshot.bonus_attack_damage
        r_at_ms = self._Q_AT_MS + self._Q_INTERVAL_MS * 2 + self._R_DELAY_AFTER_Q3_MS
        fixed = [
            action(
                "YONE_W_SPIRIT_CLEAVE",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, w_split, DamageType.PHYSICAL),
                    damage(context.opponent_entity, w_split, DamageType.MAGIC),
                    shielding(context.self_entity, w_shield, duration_ms=1500),
                ),
            ),
            action(
                "YONE_R_FATE_SEALED",
                at_ms=r_at_ms,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.PHYSICAL),
                    damage(context.opponent_entity, r_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity, "AIRBORNE", duration_ms=self._R_KNOCKUP_MS
                    ),
                ),
            ),
        ]
        events = (*self._q_events(context), *fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"YONE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "yone_q5_w5_e1_r2_cleave_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "YONE_E_SOUL_UNBOUND_DEATHMARK_NOT_MODELED",
                "YONE_PASSIVE_WAY_OF_THE_HUNTER_NOT_MODELED",
                "YONE_RESOURCE_COSTS_NOT_EVALUATED",
                "YONE_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts with ordinary basic attacks.

        :param context: Role-bound Yone and opponent combat snapshots.
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
                        f"YONE_BASIC_ATTACK_{index}",
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
        """Expose the Q3 and R knock-ups as Yone's control windows.

        :param context: Role-bound Yone and opponent snapshots.
        :return: Deterministic control windows caused by Yone's rotation.
        """
        all_channels = (
            ActionChannel.BASIC_ATTACK,
            ActionChannel.ABILITY,
            ActionChannel.MOVEMENT,
        )
        q3_at_ms = self._Q_AT_MS + self._Q_INTERVAL_MS * 2
        r_at_ms = q3_at_ms + self._R_DELAY_AFTER_Q3_MS
        return ReactionPlan(
            "yone_q3_r_knockup_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "yone_q3_wind_wave_knockup",
                    q3_at_ms,
                    min(q3_at_ms + self._Q3_KNOCKUP_MS, context.duration_ms),
                    all_channels,
                    "YONE_Q_MORTAL_STEEL_3",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "yone_r_fate_sealed_knockup",
                    r_at_ms,
                    min(r_at_ms + self._R_KNOCKUP_MS, context.duration_ms),
                    all_channels,
                    "YONE_R_FATE_SEALED",
                    False,
                    ControlType.AIRBORNE,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
