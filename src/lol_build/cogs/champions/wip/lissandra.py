"""Lissandra combat Cog backed by locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    CastBlockWindow,
    ChampionCog,
    CogMaturity,
    ControlImmunityWindow,
    ControlType,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage, missing_health_healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, DamageModifierWindow


class LissandraCog(ChampionCog):
    """Model Lissandra's Q5/W5/E1/R2 self-tomb duel fixture.

    Glacial Path supplies the deterministic entry, followed by Ring of Frost
    and Ice Shard. Frozen Tomb is self-cast so the same fixture represents its
    minimum heal and 2.5-second invulnerability without inventing two ultimate
    casts. Its surrounding ice still damages and slows the nearby opponent.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Lissandra.json",
        "data/raw/16.17.1/communitydragon/champions/127.json",
        "data/raw/16.17.1/communitydragon/champions/lissandra.bin.json",
    )

    _E_AT_MS = 0
    _W_AT_MS = 300
    _FIRST_Q_AT_MS = 500
    _R_AT_MS = 2500
    _R_END_MS = 5000

    @staticmethod
    def _cooldown_ms(base_ms: int, haste: Decimal) -> int:
        """Apply ability haste to a locked cooldown.

        :param base_ms: Unmodified cooldown in milliseconds.
        :param haste: Non-negative ability haste from the snapshot.
        :return: Truncated positive cooldown in milliseconds.
        :raises ValueError: If haste is negative.
        """
        if haste < 0:
            raise ValueError("haste must be non-negative")
        return max(1, int(Decimal(base_ms) * Decimal(100) / (Decimal(100) + haste)))

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Q5 casts while respecting the self-tomb interval.

        :param context: Snapshot supplying AP, haste, and encounter duration.
        :return: Chronological Ice Shard damage-and-slow events.
        """
        interval = self._cooldown_ms(3000, context.snapshot.ability_haste)
        cast_times: list[int] = []
        at_ms = self._FIRST_Q_AT_MS
        while at_ms <= context.duration_ms:
            if self._R_AT_MS <= at_ms < self._R_END_MS:
                at_ms = self._R_END_MS
            cast_times.append(at_ms)
            at_ms += interval
        amount = Decimal(220) + Decimal("0.75") * context.snapshot.ability_power
        base = self._sequence_base(context) + 100
        return tuple(
            action(
                f"LISSANDRA_Q_ICE_SHARD_{index}",
                at_ms=at_ms,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, amount, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=1500,
                        magnitude=Decimal("0.36"),
                    ),
                ),
            )
            for index, at_ms in enumerate(cast_times, start=1)
        )

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks after Frozen Tomb releases Lissandra.

        :param context: Snapshot supplying attack damage, speed, and duration.
        :return: Chronological follow-up basic attacks.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 300
        return tuple(
            action(
                f"LISSANDRA_BASIC_ATTACK_{index}",
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
            for index, at_ms in enumerate(range(5500, context.duration_ms + 1, interval), start=1)
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Return neutral speed because Glacial Path provides displacement.

        :param context: Role-bound Lissandra encounter context.
        :return: Neutral movement-speed multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Glacial Path's locked display range as entry distance.

        :param context: Role-bound Lissandra encounter context.
        :return: Teleport distance in game units.
        """
        return Decimal(1050)

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Avoid treating ultimate healing as repeatable lane sustain.

        :param context: Role-bound Lissandra encounter context.
        :param duration_ms: Requested lane observation duration.
        :param no_damage_delay_ms: Time since the last incoming damage event.
        :return: Zero healing and an ultimate-cooldown blocker.
        """
        return Decimal(0), ("LISSANDRA_R_NOT_REPEATABLE_LANE_SUSTAIN",)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the selected fixture.

        :param item: Normalized candidate from the locked catalog.
        :return: Lissandra-scoped blocker, or ``None`` for represented stats.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "CRITICAL_STRIKE_CHANCE",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"LISSANDRA_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build entry, root, shards, and the self-cast Frozen Tomb.

        :param context: Role-bound Lissandra and opponent snapshots.
        :return: Deterministic level-13 combat schedule.
        """
        ap = context.snapshot.ability_power
        base = self._sequence_base(context)
        fixed = (
            action(
                "LISSANDRA_E_GLACIAL_PATH_HIT_AND_RECAST",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(70) + Decimal("0.60") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "LISSANDRA_W_RING_OF_FROST",
                at_ms=self._W_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(210) + Decimal("0.70") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "ROOT", duration_ms=1650),
                ),
            ),
            action(
                "LISSANDRA_R_FROZEN_TOMB_SELF_CAST",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(250) + Decimal("0.75") * ap,
                        DamageType.MAGIC,
                    ),
                    # HealAmount grows by up to 100% (SelfCastMissingHPRatio) with
                    # missing health: h * (1 + missing / max).
                    missing_health_healing(
                        context.self_entity,
                        (Decimal(150) + Decimal("0.55") * ap) / context.snapshot.max_hp,
                        base_amount=Decimal(150) + Decimal("0.55") * ap,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=3000,
                        magnitude=Decimal("0.60"),
                    ),
                ),
            ),
        )
        events = (*fixed, *self._q_events(context), *self._attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"LISSANDRA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "lissandra_q5_w5_e1_r2_self_tomb_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "LISSANDRA_LEVEL13_Q5_W5_E1_R2_ORDER_UNVERIFIED",
                "LISSANDRA_E_HITS_TARGET_BEFORE_RECAST_ASSUMED",
                "LISSANDRA_R_MISSING_HEALTH_AMPLIFICATION_READ_AS_LINEAR",
                "LISSANDRA_R_AURA_HITS_NEARBY_TARGET_ONCE_ASSUMED",
                "LISSANDRA_ENEMY_CAST_R_VARIANT_OUTSIDE_SELECTED_FIXTURE",
                "LISSANDRA_PASSIVE_THRALL_REQUIRES_TAKEDOWN_AND_IS_NOT_MODELED",
                "LISSANDRA_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose self-tomb immunity plus W root and Q/R slow windows.

        :param context: Role-bound Lissandra and opponent snapshots.
        :return: Defensive, immunity, and hostile-control reaction windows.
        """
        q_windows = tuple(
            CastBlockWindow(
                f"lissandra_q_slow_{index}",
                event.at_ms,
                min(event.at_ms + 1500, context.duration_ms),
                (ActionChannel.MOVEMENT,),
                event.id,
                True,
                ControlType.SLOW,
            )
            for index, event in enumerate(self._q_events(context), start=1)
        )
        return ReactionPlan(
            "lissandra_q5_w5_r2_self_tomb_reaction_v1",
            damage_windows=(
                DamageModifierWindow(
                    "lissandra_r_self_invulnerability",
                    self._R_AT_MS,
                    min(self._R_END_MS, context.duration_ms),
                    context.self_entity,
                    (DamageType.PHYSICAL, DamageType.MAGIC, DamageType.TRUE),
                    Decimal(0),
                ),
            ),
            cast_block_windows=(
                CastBlockWindow(
                    "lissandra_w_root",
                    self._W_AT_MS,
                    min(self._W_AT_MS + 1650, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "LISSANDRA_W_RING_OF_FROST",
                    True,
                    ControlType.ROOT,
                ),
                CastBlockWindow(
                    "lissandra_r_aura_slow",
                    self._R_AT_MS,
                    min(self._R_AT_MS + 3000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "LISSANDRA_R_FROZEN_TOMB_SELF_CAST",
                    True,
                    ControlType.SLOW,
                ),
                *q_windows,
            ),
            control_immunity_windows=(
                ControlImmunityWindow(
                    "lissandra_r_self_control_immunity",
                    self._R_AT_MS,
                    min(self._R_END_MS, context.duration_ms),
                    context.self_entity,
                    (ControlType.ALL,),
                    "LISSANDRA_R_FROZEN_TOMB_SELF_CAST",
                ),
            ),
            blockers=("LISSANDRA_R_UNTARGETABILITY_TARGET_SELECTION_NOT_MODELED",),
        )
