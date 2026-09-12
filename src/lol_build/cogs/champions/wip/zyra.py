"""Zyra combat Cog backed by locked 16.17.1 champion sources."""

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


class ZyraCog(ChampionCog):
    """Model Zyra's Q5/E5/W1/R2 level-thirteen duel fixture without plants.

    Grasping Roots roots the opponent for its rank-five ``RootDuration``,
    Deadly Spines lands its rank-five damage, and Stranglethorns deals its
    rank-two damage and knocks up for ``KnockupDuration`` as it contracts.
    Thorn Spitters and Vine Lashers are pets this two-participant timeline
    cannot host, so Garden of Thorns and every plant are excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Zyra.json",
        "data/raw/16.17.1/communitydragon/champions/143.json",
        "data/raw/16.17.1/communitydragon/champions/zyra.bin.json",
    )

    _E_AT_MS = 0
    _E_ROOT_MS = 2000
    _Q_AT_MS = 700
    _R_AT_MS = 1400
    _R_CONTRACT_MS = 2000
    _R_KNOCKUP_MS = 1000
    _ATTACKS_FROM_MS = 1000

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Zyra's roots, spines, and stranglethorns rotation.

        :param context: Role-bound Zyra and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        ap = snapshot.ability_power
        events: list[ActionEvent] = [
            action(
                "ZYRA_E_GRASPING_ROOTS",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("ZyraE", "BaseDamage", context, Decimal(200))
                        + Decimal("0.6") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "ROOT", duration_ms=self._E_ROOT_MS),
                ),
            ),
            action(
                "ZYRA_Q_DEADLY_SPINES",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("ZyraQ", "BaseDamage", context, Decimal(220))
                        + Decimal("0.65") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "ZYRA_R_STRANGLETHORNS",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("ZyraR", "BaseDamage", context, Decimal(300))
                        + Decimal("0.7") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
        ]
        contract_ms = self._R_AT_MS + self._R_CONTRACT_MS
        if contract_ms <= context.duration_ms:
            events.append(
                action(
                    "ZYRA_R_STRANGLETHORNS_CONTRACTION",
                    at_ms=contract_ms,
                    sequence=base + 3,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        crowd_control(
                            context.opponent_entity, "AIRBORNE", duration_ms=self._R_KNOCKUP_MS
                        ),
                    ),
                )
            )
        interval = self._attack_interval_ms(snapshot.attack_speed)
        for index, at_ms in enumerate(
            range(self._ATTACKS_FROM_MS, context.duration_ms + 1, interval)
        ):
            events.append(
                action(
                    f"ZYRA_BASIC_ATTACK_{index}",
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
            () if snapshot.level == 13 else (f"ZYRA_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "zyra_q5_e5_w1_r2_roots_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "ZYRA_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "ZYRA_PLANTS_ARE_PETS_NOT_REPRESENTABLE",
                "ZYRA_R_CONTRACTION_TIMING_NOT_IN_LOCKED_DATA",
                "ZYRA_BASIC_ATTACK_MAGIC_DAMAGE_ASSUMED",
                "ZYRA_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the Grasping Roots root and Stranglethorns knock-up.

        :param context: Role-bound Zyra and opponent snapshots.
        :return: Deterministic control windows caused by Zyra's rotation.
        """
        contract_ms = self._R_AT_MS + self._R_CONTRACT_MS
        windows = [
            CastBlockWindow(
                "zyra_e_grasping_roots_root",
                self._E_AT_MS,
                min(self._E_AT_MS + self._E_ROOT_MS, context.duration_ms),
                (ActionChannel.MOVEMENT,),
                "ZYRA_E_GRASPING_ROOTS",
                True,
                ControlType.ROOT,
            )
        ]
        if contract_ms < context.duration_ms:
            windows.append(
                CastBlockWindow(
                    "zyra_r_stranglethorns_knockup",
                    contract_ms,
                    min(contract_ms + self._R_KNOCKUP_MS, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT),
                    "ZYRA_R_STRANGLETHORNS_CONTRACTION",
                    False,
                    ControlType.AIRBORNE,
                )
            )
        return ReactionPlan(
            "zyra_e_r_control_reaction_v1",
            cast_block_windows=tuple(windows),
            blockers=(*self.verification_blockers(),),
        )
