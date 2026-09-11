"""Irelia combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, DamageModifierWindow


class IreliaCog(ChampionCog):
    """Model Irelia's Q5/W5/E1/R2 marked-target duel fixture.

    Vanguard's Edge and Flawless Duet each supply one deterministic mark and
    therefore one Bladesurge reset. Four spell hits activate maximum Ionian
    Fervor before the sustained attack segment. Defiant Dance uses a fully
    charged damage event and a separate defensive reaction window.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Irelia.json",
        "data/raw/16.17.1/communitydragon/champions/39.json",
        "data/raw/16.17.1/communitydragon/champions/irelia.bin.json",
    )

    _R_AT_MS = 0
    _FIRST_Q_AT_MS = 250
    _E_AT_MS = 800
    _SECOND_Q_AT_MS = 1050
    _W_START_MS = 2000
    _W_RELEASE_MS = 2750
    _ATTACK_START_MS = 3000
    _ATTACK_SPEED_RATIO = Decimal("0.656")

    @staticmethod
    def _haste_adjusted_ms(base_ms: int, ability_haste: Decimal) -> int:
        """Apply ability haste to a cooldown.

        :param base_ms: Locked unmodified cooldown in milliseconds.
        :param ability_haste: Non-negative haste from Irelia's snapshot.
        :return: Rounded cooldown with a one-millisecond floor.
        :raises ValueError: If ability haste is negative.
        """
        if ability_haste < 0:
            raise ValueError("ability_haste must be non-negative")
        value = Decimal(base_ms) * Decimal(100) / (Decimal(100) + ability_haste)
        return max(1, int(value.to_integral_value()))

    @staticmethod
    def _passive_attack_speed_per_stack(level: int) -> Decimal:
        """Interpolate Ionian Fervor's per-stack attack-speed bonus.

        :param level: Current champion level in the supported game range.
        :return: Fractional attack-speed bonus granted by one stack.
        """
        return Decimal("0.10") + Decimal("0.15") * Decimal(level - 1) / Decimal(17)

    @staticmethod
    def _passive_on_hit(context: ParticipantContext) -> Decimal:
        """Calculate maximum-stack Ionian Fervor on-hit magic damage.

        :param context: Snapshot supplying level and bonus attack damage.
        :return: Raw magic damage attached to each empowered attack.
        """
        return (
            Decimal(10)
            + Decimal(3) * Decimal(context.snapshot.level)
            + Decimal("0.20") * context.snapshot.bonus_attack_damage
        )

    @staticmethod
    def _q_outputs(context: ParticipantContext) -> tuple:
        """Build rank-five Bladesurge damage and healing outputs.

        :param context: Role-bound snapshots identifying stats and recipients.
        :return: Atomic physical damage and self-healing outputs.
        """
        total_ad = context.snapshot.attack_damage
        return (
            damage(
                context.opponent_entity,
                Decimal(85) + Decimal("0.80") * total_ad,
                DamageType.PHYSICAL,
            ),
            healing(context.self_entity, Decimal("0.13") * total_ad),
        )

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule two marked resets and one natural-cooldown Bladesurge.

        :param context: Snapshot supplying haste and encounter duration.
        :return: Chronological rank-five Bladesurge events.
        """
        cast_times = [self._FIRST_Q_AT_MS, self._SECOND_Q_AT_MS]
        third_at = self._SECOND_Q_AT_MS + self._haste_adjusted_ms(
            6000, context.snapshot.ability_haste
        )
        if third_at <= context.duration_ms:
            cast_times.append(third_at)
        base = self._sequence_base(context) + 100
        return tuple(
            action(
                f"IRELIA_Q_BLADESURGE_{index}",
                at_ms=at_ms,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=self._q_outputs(context),
            )
            for index, at_ms in enumerate(cast_times, start=1)
        )

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks at maximum passive stacks after the spell opener.

        :param context: Snapshot supplying attack speed, AD, and duration.
        :return: Basic attacks with passive magic damage attached.
        """
        passive_bonus = self._passive_attack_speed_per_stack(context.snapshot.level) * Decimal(4)
        attack_speed = context.snapshot.attack_speed + self._ATTACK_SPEED_RATIO * passive_bonus
        interval_ms = self._attack_interval_ms(attack_speed)
        passive_damage = self._passive_on_hit(context)
        base = self._sequence_base(context) + 300
        return tuple(
            action(
                f"IRELIA_MAX_FERVOR_ATTACK_{index}",
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
                    damage(context.opponent_entity, passive_damage, DamageType.MAGIC),
                ),
            )
            for index, at_ms in enumerate(
                range(self._ATTACK_START_MS, context.duration_ms + 1, interval_ms),
                start=1,
            )
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Return neutral speed because the selected entry is a dash.

        :param context: Role-bound Irelia encounter context.
        :return: Neutral movement-speed multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Bladesurge's locked cast range as entry distance.

        :param context: Role-bound Irelia encounter context.
        :return: Dash distance in game units.
        """
        return Decimal(600)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats absent from the selected duel model.

        :param item: Normalized candidate from the locked catalog.
        :return: Irelia-scoped blocker, or ``None`` for represented stats.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"IRELIA_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build marked resets, full-charge W, and maximum-passive attacks.

        :param context: Role-bound Irelia and opponent snapshots.
        :return: Deterministic level-13 offensive event schedule.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        bonus_ad = context.snapshot.bonus_attack_damage
        fixed = (
            action(
                "IRELIA_R_VANGUARDS_EDGE_MISSILE",
                at_ms=self._R_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, Decimal(200) + ap, DamageType.MAGIC),),
            ),
            action(
                "IRELIA_E_FLAWLESS_DUET",
                at_ms=self._E_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, Decimal(70) + ap, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=750),
                ),
            ),
            action(
                "IRELIA_R_VANGUARDS_EDGE_WALL_CROSS",
                origin_event_id="IRELIA_R_VANGUARDS_EDGE_MISSILE",
                at_ms=1500,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(
                    damage(context.opponent_entity, Decimal(200) + ap, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=1500,
                        magnitude=Decimal("0.90"),
                    ),
                ),
            ),
            action(
                "IRELIA_W_DEFIANT_DANCE_FULL_CHARGE",
                at_ms=self._W_RELEASE_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(150) + Decimal("1.20") * bonus_ad + Decimal("1.50") * ap,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
        )
        events = (*fixed, *self._q_events(context), *self._attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"IRELIA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "irelia_q5_w5_e1_r2_mark_reset_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "IRELIA_LEVEL13_Q5_W5_E1_R2_ORDER_UNVERIFIED",
                "IRELIA_R_AND_E_MARKS_ASSUMED_TO_HIT_AND_RESET_Q",
                "IRELIA_R_TARGET_CROSSES_WALL_ONCE_ASSUMED",
                "IRELIA_FOUR_PASSIVE_STACKS_ESTABLISHED_BEFORE_ATTACKS_ASSUMED",
                "IRELIA_Q_ON_HIT_ITEM_INTERACTIONS_NOT_MODELED",
                "IRELIA_W_DAMAGE_REDUCTION_TIMING_SYNTHETIC",
                "IRELIA_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose W mitigation, E stun, and R wall slow windows.

        :param context: Role-bound Irelia and opponent snapshots.
        :return: Defensive and hostile-control reaction windows.
        """
        level_fraction = Decimal(context.snapshot.level - 1) / Decimal(17)
        physical_reduction = (
            Decimal("0.40")
            + Decimal("0.30") * level_fraction
            + Decimal("0.0008") * context.snapshot.ability_power
        )
        physical_multiplier = max(Decimal(0), Decimal(1) - physical_reduction)
        magic_multiplier = Decimal(1) - physical_reduction * Decimal("0.50")
        return ReactionPlan(
            "irelia_w5_e1_r2_reaction_v1",
            damage_windows=(
                DamageModifierWindow(
                    "irelia_w_physical_damage_reduction",
                    self._W_START_MS,
                    min(self._W_RELEASE_MS, context.duration_ms),
                    context.self_entity,
                    (DamageType.PHYSICAL,),
                    physical_multiplier,
                ),
                DamageModifierWindow(
                    "irelia_w_magic_damage_reduction",
                    self._W_START_MS,
                    min(self._W_RELEASE_MS, context.duration_ms),
                    context.self_entity,
                    (DamageType.MAGIC,),
                    magic_multiplier,
                ),
            ),
            cast_block_windows=(
                CastBlockWindow(
                    "irelia_e_flawless_duet_stun",
                    self._E_AT_MS,
                    min(self._E_AT_MS + 750, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "IRELIA_E_FLAWLESS_DUET",
                    True,
                    ControlType.STUN,
                ),
                CastBlockWindow(
                    "irelia_r_vanguards_edge_wall_slow",
                    1500,
                    min(3000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "IRELIA_R_VANGUARDS_EDGE_WALL_CROSS",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=(
                "IRELIA_W_CHANNEL_CANNOT_BE_INTERRUPTED_BY_DISABLES_LOCKED",
                "IRELIA_R_WALL_REENTRY_NOT_MODELED",
            ),
        )
