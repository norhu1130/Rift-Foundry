"""Morgana combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    MissingHealthDamageOutput,
    StatModifierOutput,
)


class MorganaCog(ChampionCog):
    """Model Morgana's Q5/E5/W1/R2 locked-target duel fixture.

    Dark Binding holds the opponent in Tormented Shadow, whose ten ticks scale
    continuously with missing health. Soul Shackles applies initial damage and
    a delayed second hit. Black Shield is magic-only; its conditional control
    protection remains unclaimed because it ends when that shield breaks.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Morgana.json",
        "data/raw/16.17.1/communitydragon/champions/25.json",
        "data/raw/16.17.1/communitydragon/champions/morgana.bin.json",
    )

    _Q_AT_MS = 0
    _W_AT_MS = 50
    _E_AT_MS = 100
    _R_AT_MS = 300
    _R_FINISH_MS = 3300

    def _shadow_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ten missing-health-amplified W1 ticks.

        :param context: Snapshot supplying AP, target maximum health, and roles.
        :return: Half-second Tormented Shadow events.
        """
        base_tick = (Decimal(18) + Decimal("0.20") * context.snapshot.ability_power) / Decimal(2)
        missing_ratio = base_tick / context.opponent_snapshot.max_hp
        base = self._sequence_base(context) + 100
        return tuple(
            action(
                f"MORGANA_W_TORMENTED_SHADOW_{index}",
                at_ms=self._W_AT_MS + index * 500,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(
                    MissingHealthDamageOutput(
                        context.opponent_entity,
                        base_tick,
                        missing_ratio,
                        DamageType.MAGIC,
                    ),
                ),
            )
            for index in range(1, 11)
            if self._W_AT_MS + index * 500 <= context.duration_ms
        )

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ordinary ranged attacks after the spell opener.

        :param context: Snapshot supplying attack damage, speed, and duration.
        :return: Chronological basic attacks.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 400
        return tuple(
            action(
                f"MORGANA_BASIC_ATTACK_{index}",
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
            for index, at_ms in enumerate(range(700, context.duration_ms + 1, interval), start=1)
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose R2's locked forty-percent tether movement boost.

        :param context: Role-bound Morgana encounter context.
        :return: Initial Soul Shackles movement multiplier.
        """
        return Decimal("1.40")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return zero because Morgana has no displacement ability.

        :param context: Role-bound Morgana encounter context.
        :return: Zero dash distance.
        """
        return Decimal(0)

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Avoid treating damage-dependent Soul Siphon as free recovery.

        :param context: Role-bound Morgana encounter context.
        :param duration_ms: Requested lane observation duration.
        :param no_damage_delay_ms: Time since the last incoming damage event.
        :return: Zero extra health and a damage-target blocker.
        """
        return Decimal(0), ("MORGANA_PASSIVE_REQUIRES_POST_MITIGATION_CHAMPION_DAMAGE",)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the selected fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Morgana-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            return f"MORGANA_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Q, W ticks, self E, both R hits, and attacks.

        :param context: Role-bound Morgana and opponent snapshots.
        :return: Deterministic level-13 action schedule.
        """
        ap = context.snapshot.ability_power
        base = self._sequence_base(context)
        r_damage = Decimal(275) + Decimal("0.80") * ap
        fixed = (
            action(
                "MORGANA_Q_DARK_BINDING",
                at_ms=self._Q_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(300) + Decimal("0.90") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "ROOT", duration_ms=3000),
                ),
            ),
            action(
                "MORGANA_E_BLACK_SHIELD_SELF",
                at_ms=self._E_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(
                        context.self_entity,
                        Decimal(320) + Decimal("0.70") * ap,
                        duration_ms=5000,
                        damage_types=(DamageType.MAGIC,),
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "MORGANA_R_SOUL_SHACKLES_INITIAL",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=3000,
                        magnitude=Decimal("0.20"),
                    ),
                ),
            ),
            action(
                "MORGANA_R_SOUL_SHACKLES_FINISH",
                at_ms=self._R_FINISH_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=1750),
                ),
            ),
        )
        soul_siphon = action(
            "MORGANA_PASSIVE_SOUL_SIPHON",
            at_ms=0,
            sequence=base + 90,
            source=context.self_entity,
            channel=ActionChannel.PASSIVE,
            # Locked HealPercent: 18% of champion ability damage.
            outputs=(
                StatModifierOutput(context.self_entity, "ABILITY_VAMP", Decimal("0.18"), None),
            ),
            requires_living_opponent=False,
        )
        events = (
            soul_siphon,
            *fixed,
            *self._shadow_events(context),
            *self._attack_events(context),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"MORGANA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "morgana_q5_e5_w1_r2_full_tether_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "MORGANA_LEVEL13_Q5_E5_W1_R2_SUPPORT_ORDER_UNVERIFIED",
                "MORGANA_Q_AND_ALL_W_TICKS_HIT_ASSUMED",
                "MORGANA_R_TARGET_REMAINS_TETHERED_FOR_THREE_SECONDS_ASSUMED",
                "MORGANA_W_COOLDOWN_REFUND_NOT_MODELED",
                "MORGANA_E_CONTROL_PROTECTION_DEPENDS_ON_REMAINING_MAGIC_SHIELD",
                "MORGANA_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Q root, R slow and stun, and conditional E limitations.

        :param context: Role-bound Morgana and opponent snapshots.
        :return: Hostile control windows without unconditional E immunity.
        """
        return ReactionPlan(
            "morgana_q_root_r_slow_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "morgana_q_dark_binding_root",
                    self._Q_AT_MS,
                    min(3000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "MORGANA_Q_DARK_BINDING",
                    True,
                    ControlType.ROOT,
                ),
                CastBlockWindow(
                    "morgana_r_soul_shackles_slow",
                    self._R_AT_MS,
                    min(self._R_FINISH_MS, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "MORGANA_R_SOUL_SHACKLES_INITIAL",
                    True,
                    ControlType.SLOW,
                ),
                CastBlockWindow(
                    "morgana_r_soul_shackles_stun",
                    self._R_FINISH_MS,
                    min(self._R_FINISH_MS + 1750, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT),
                    "MORGANA_R_SOUL_SHACKLES_FINISH",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(
                "MORGANA_E_CONTROL_PROTECTION_REQUIRES_SHIELD_BREAK_COUPLING",
                "MORGANA_R_TETHER_BREAK_DISTANCE_NOT_MODELED",
            ),
        )
