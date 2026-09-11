"""Maokai combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent


class MaokaiCog(ChampionCog):
    """Model Maokai's E5/Q5/W1/R2 non-brush engage fixture.

    Nature's Grasp catches at the fixed maximum-root benchmark, a normal
    Sapling follows, and Twisted Advance closes into Bramble Smash. One Sap
    Magic attack is modeled as ready at combat start; later cooldown reductions
    remain explicit rather than inventing an additional proc time.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Maokai.json",
        "data/raw/16.17.1/communitydragon/champions/57.json",
        "data/raw/16.17.1/communitydragon/champions/maokai.bin.json",
    )

    _R_AT_MS = 0
    _E_AT_MS = 500
    _W_AT_MS = 900
    _Q_AT_MS = 1100
    _PASSIVE_AT_MS = 1300

    @staticmethod
    def _passive_heal_ratio(level: int) -> Decimal:
        """Calculate Sap Magic's level-breakpoint maximum-health ratio.

        :param level: Current champion level.
        :return: Fraction of maximum health restored by one empowered attack.
        """
        ratio = Decimal("0.04")
        for current_level in range(2, level + 1):
            ratio += Decimal("0.0065") if current_level >= 7 else Decimal("0.002")
        return ratio

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule one Sap Magic attack and ordinary follow-up attacks.

        :param context: Snapshot supplying health, AD, attack speed, and duration.
        :return: Chronological basic attacks with one passive heal.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = [
            action(
                "MAOKAI_PASSIVE_SAP_MAGIC_ATTACK",
                at_ms=self._PASSIVE_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity,
                        context.snapshot.attack_damage,
                        DamageType.PHYSICAL,
                    ),
                    healing(
                        context.self_entity,
                        context.snapshot.max_hp * self._passive_heal_ratio(context.snapshot.level),
                    ),
                ),
            )
        ]
        for index, at_ms in enumerate(
            range(self._PASSIVE_AT_MS + interval, context.duration_ms + 1, interval),
            start=1,
        ):
            events.append(
                action(
                    f"MAOKAI_BASIC_ATTACK_{index}",
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
        return tuple(events)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose R2's post-hit movement-speed multiplier.

        :param context: Role-bound Maokai encounter context.
        :return: Movement multiplier after Nature's Grasp catches a champion.
        """
        return Decimal("1.50")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Twisted Advance's locked target range.

        :param context: Role-bound Maokai encounter context.
        :return: Targeted dash distance in game units.
        """
        return Decimal(525)

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Avoid converting combat-only Sap Magic into free lane sustain.

        :param context: Role-bound Maokai encounter context.
        :param duration_ms: Requested lane observation duration.
        :param no_damage_delay_ms: Time since the last incoming damage event.
        :return: Zero healing and an attack dependency blocker.
        """
        return Decimal(0), ("MAOKAI_PASSIVE_REQUIRES_BASIC_ATTACK_TARGET",)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats absent from Maokai's fixed fixture.

        :param item: Normalized candidate from the locked catalog.
        :return: Maokai-scoped blocker, or ``None`` for represented stats.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"MAOKAI_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build R catch, normal E, W entry, Q displacement, and attacks.

        :param context: Role-bound Maokai and opponent snapshots.
        :return: Deterministic level-13 action schedule.
        """
        ap = context.snapshot.ability_power
        bonus_hp = context.snapshot.bonus_health
        base = self._sequence_base(context)
        fixed = (
            action(
                "MAOKAI_R_NATURES_GRASP_MAX_ROOT",
                at_ms=self._R_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(225) + Decimal("0.75") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "ROOT", duration_ms=2250),
                ),
            ),
            action(
                "MAOKAI_E_SAPLING_NORMAL_EXPLOSION",
                at_ms=self._E_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(150) + Decimal("0.25") * ap + Decimal("0.05") * bonus_hp,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=2000,
                        magnitude=Decimal("0.45"),
                    ),
                ),
            ),
            action(
                "MAOKAI_W_TWISTED_ADVANCE",
                at_ms=self._W_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(60) + Decimal("0.40") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "ROOT", duration_ms=1000),
                ),
            ),
            action(
                "MAOKAI_Q_BRAMBLE_SMASH",
                at_ms=self._Q_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(255)
                        + Decimal("0.50") * ap
                        + Decimal("0.04") * context.opponent_snapshot.max_hp,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=421),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=250,
                        magnitude=Decimal("0.99"),
                    ),
                ),
            ),
        )
        events = (*fixed, *self._attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"MAOKAI_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "maokai_e5_q5_w1_r2_non_brush_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "MAOKAI_LEVEL13_E5_Q5_W1_R2_ORDER_LOCKED_UNVERIFIED",
                "MAOKAI_R_MAXIMUM_ROOT_TRAVEL_ASSUMED",
                "MAOKAI_E_NON_BRUSH_VARIANT_SELECTED",
                "MAOKAI_W_UNTARGETABLE_TRAVEL_SELECTION_NOT_MODELED",
                "MAOKAI_PASSIVE_READY_AT_FIRST_ATTACK_ASSUMED",
                "MAOKAI_PASSIVE_DYNAMIC_COOLDOWN_REDUCTION_NOT_MODELED",
                "MAOKAI_Q_KNOCKBACK_DURATION_DERIVED_FROM_DISTANCE_AND_SPEED",
                "MAOKAI_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose R/W roots, E slow, and Q displacement/slow windows.

        :param context: Role-bound Maokai and opponent snapshots.
        :return: Typed control windows linked to the selected source events.
        """
        return ReactionPlan(
            "maokai_e5_q5_w1_r2_control_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "maokai_r_root",
                    0,
                    min(2250, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "MAOKAI_R_NATURES_GRASP_MAX_ROOT",
                    True,
                    ControlType.ROOT,
                ),
                CastBlockWindow(
                    "maokai_e_slow",
                    500,
                    min(2500, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "MAOKAI_E_SAPLING_NORMAL_EXPLOSION",
                    True,
                    ControlType.SLOW,
                ),
                CastBlockWindow(
                    "maokai_w_root",
                    900,
                    min(1900, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "MAOKAI_W_TWISTED_ADVANCE",
                    True,
                    ControlType.ROOT,
                ),
                CastBlockWindow(
                    "maokai_q_knockback",
                    1100,
                    min(1521, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT),
                    "MAOKAI_Q_BRAMBLE_SMASH",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "maokai_q_slow",
                    1100,
                    min(1350, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "MAOKAI_Q_BRAMBLE_SMASH",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=("MAOKAI_W_UNTARGETABILITY_REQUIRES_TARGET_SELECTION_MODEL",),
        )
