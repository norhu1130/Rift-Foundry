"""Taliyah combat Cog backed by locked 16.17.1 champion sources."""

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


class TaliyahCog(ChampionCog):
    """Model Taliyah's Q5/E5/W1/R2 level-thirteen minefield combo.

    Unraveled Earth scatters its rank-five mines and slows, Seismic Shove then
    throws the opponent through the field after its ``KnockupDelay`` so one
    mine detonates for ``DetonationDamage`` and stuns for ``StunDuration``, and
    Threaded Volley lands its single-target total (``MaxDamageTooltip`` times
    ``RockDamage``). Seismic Shove's own knock-up duration is absent from the
    locked data, Worked Ground's boulder and Weaver's Wall are excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Taliyah.json",
        "data/raw/16.17.1/communitydragon/champions/163.json",
        "data/raw/16.17.1/communitydragon/champions/taliyah.bin.json",
    )

    _E_AT_MS = 0
    _E_SLOW_MS = 4000
    _W_CAST_MS = 400
    _W_KNOCKUP_DELAY_MS = 500
    _STUN_MS = 750
    _Q_AT_MS = 1700
    _ATTACKS_FROM_MS = 2400

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Taliyah's minefield, shove, and volley combo.

        :param context: Role-bound Taliyah and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        ap = snapshot.ability_power
        shove_ms = self._W_CAST_MS + self._W_KNOCKUP_DELAY_MS
        events: list[ActionEvent] = [
            action(
                "TALIYAH_E_UNRAVELED_EARTH",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("TaliyahE", "BaseDamage", context, Decimal(240))
                        + Decimal("0.6") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=self._E_SLOW_MS,
                        magnitude=Decimal("0.20"),
                    ),
                ),
            ),
            action(
                "TALIYAH_W_SEISMIC_SHOVE_MINE_DETONATION",
                at_ms=shove_ms,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("TaliyahE", "BaseDetonationDamage", context, Decimal(85))
                        + Decimal("0.3") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=self._STUN_MS),
                ),
            ),
            action(
                "TALIYAH_Q_THREADED_VOLLEY",
                at_ms=self._Q_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal("2.6")
                        * (
                            self.rank_value("TaliyahQ", "BaseDamage", context, Decimal(125))
                            + Decimal("0.5") * ap
                        ),
                        DamageType.MAGIC,
                    ),
                ),
            ),
        ]
        interval = self._attack_interval_ms(snapshot.attack_speed)
        for index, at_ms in enumerate(
            range(self._ATTACKS_FROM_MS, context.duration_ms + 1, interval)
        ):
            events.append(
                action(
                    f"TALIYAH_BASIC_ATTACK_{index}",
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
            () if snapshot.level == 13 else (f"TALIYAH_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "taliyah_q5_e5_w1_r2_minefield_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "TALIYAH_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "TALIYAH_W_KNOCKUP_DURATION_NOT_IN_LOCKED_DATA",
                "TALIYAH_E_SINGLE_MINE_DETONATION_ASSUMED",
                "TALIYAH_Q_WORKED_GROUND_BOULDER_NOT_MODELED",
                "TALIYAH_R_WEAVERS_WALL_TERRAIN_NOT_MODELED",
                "TALIYAH_BASIC_ATTACK_MAGIC_DAMAGE_ASSUMED",
                "TALIYAH_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the minefield detonation stun as a control window.

        :param context: Role-bound Taliyah and opponent snapshots.
        :return: Deterministic control windows caused by Taliyah's rotation.
        """
        start = self._W_CAST_MS + self._W_KNOCKUP_DELAY_MS
        return ReactionPlan(
            "taliyah_e_mine_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "taliyah_e_mine_detonation_stun",
                    start,
                    min(start + self._STUN_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "TALIYAH_W_SEISMIC_SHOVE_MINE_DETONATION",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
