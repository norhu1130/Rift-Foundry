"""Renata Glasc combat Cog backed by locked 16.17.1 champion sources."""

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


class RenataCog(ChampionCog):
    """Model Renata Glasc's Q5/E5/W1/R2 level-thirteen duel fixture.

    Handshake roots the opponent for ``RootDuration``, Loyalty Program damages
    and slows, and Hostile Takeover sends the opponent Berserk for its
    rank-two ``BerserkDuration``. With no allies to turn on, a Berserk duel
    opponent is read as unable to cast or move while it lasts. Loyalty
    Program's shield and Bailout only reach allied champions, and Leverage's
    percent-health mark reads a truncated level curve, so all three are
    excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Renata.json",
        "data/raw/16.17.1/communitydragon/champions/888.json",
        "data/raw/16.17.1/communitydragon/champions/renata.bin.json",
    )

    _Q_AT_MS = 0
    _Q_ROOT_MS = 1000
    _E_AT_MS = 600
    _E_SLOW_MS = 2000
    _R_AT_MS = 1500
    _R_BERSERK_MS = 1750
    _ATTACKS_FROM_MS = 1100

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Renata's handshake, loyalty-program, and takeover rotation.

        :param context: Role-bound Renata and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        ap = snapshot.ability_power
        events: list[ActionEvent] = [
            action(
                "RENATA_Q_HANDSHAKE",
                at_ms=self._Q_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("RenataQ", "Damage", context, Decimal(260))
                        + Decimal("0.8") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "ROOT", duration_ms=self._Q_ROOT_MS),
                ),
            ),
            action(
                "RENATA_E_LOYALTY_PROGRAM",
                at_ms=self._E_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("RenataE", "Damage", context, Decimal(185))
                        + Decimal("0.55") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=self._E_SLOW_MS,
                        magnitude=Decimal("0.30"),
                    ),
                ),
            ),
            action(
                "RENATA_R_HOSTILE_TAKEOVER",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    crowd_control(
                        context.opponent_entity, "BERSERK", duration_ms=self._R_BERSERK_MS
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
                    f"RENATA_BASIC_ATTACK_{index}",
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
            () if snapshot.level == 13 else (f"RENATA_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "renata_q5_e5_w1_r2_handshake_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "RENATA_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "RENATA_R_BERSERK_IN_A_DUEL_READ_AS_LOSS_OF_CONTROL",
                "RENATA_E_SHIELD_AND_W_BAILOUT_REQUIRE_ALLIES",
                "RENATA_PASSIVE_LEVERAGE_LEVEL_CURVE_TRUNCATED_IN_SOURCE_READ",
                "RENATA_Q_RECAST_THROW_NOT_MODELED",
                "RENATA_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the Handshake root and Hostile Takeover berserk windows.

        :param context: Role-bound Renata and opponent snapshots.
        :return: Deterministic control windows caused by Renata's rotation.
        """
        return ReactionPlan(
            "renata_q_r_control_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "renata_q_handshake_root",
                    self._Q_AT_MS,
                    min(self._Q_AT_MS + self._Q_ROOT_MS, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "RENATA_Q_HANDSHAKE",
                    True,
                    ControlType.ROOT,
                ),
                CastBlockWindow(
                    "renata_r_hostile_takeover_berserk",
                    self._R_AT_MS,
                    min(self._R_AT_MS + self._R_BERSERK_MS, context.duration_ms),
                    (ActionChannel.ABILITY, ActionChannel.MOVEMENT),
                    "RENATA_R_HOSTILE_TAKEOVER",
                    True,
                    ControlType.UNSPECIFIED,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
