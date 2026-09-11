"""Naafiri combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing, movement_speed
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    MissingHealthDamageOutput,
    StatModifierOutput,
    StatusOutput,
)


class NaafiriCog(ChampionCog):
    """Model Naafiri's current W1/R2/Q5/E5 pack-assisted fixture.

    The locked patch places The Call of the Pack on W and Hounds' Pursuit on
    R. W adds two packmates and twenty percent total AD for five seconds. R
    then delivers Naafiri and six assumed living packmates, Q's second cast
    consumes the remaining bleed and heals, and E resolves both slashes.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Naafiri.json",
        "data/raw/16.17.1/communitydragon/champions/950.json",
        "data/raw/16.17.1/communitydragon/champions/naafiri.bin.json",
    )

    _W_AT_MS = 0
    _R_AT_MS = 1000
    _FIRST_Q_AT_MS = 1200
    _SECOND_Q_AT_MS = 1950
    _E_AT_MS = 2200

    @staticmethod
    def _w_bonus_ad(context: ParticipantContext) -> Decimal:
        """Return bonus AD while rank-one W's five-second hunt is active.

        :param context: Snapshot supplying permanent total and bonus AD.
        :return: Permanent bonus AD plus twenty percent of pre-W total AD.
        """
        return (
            context.snapshot.bonus_attack_damage + Decimal("0.20") * context.snapshot.attack_damage
        )

    def _packmate_damage(self, context: ParticipantContext) -> Decimal:
        """Calculate one level-13 packmate attack before mitigation.

        :param context: Snapshot supplying level and bonus AD.
        :return: One packmate's locked physical attack damage.
        """
        fraction = Decimal(context.snapshot.level - 1) / Decimal(17)
        return Decimal(10) + Decimal(10) * fraction + Decimal("0.04") * self._w_bonus_ad(context)

    def _packmate_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule two aggregated attacks from six W-empowered packmates.

        :param context: Snapshot supplying packmate scaling and role identities.
        :return: Aggregated packmate attack events during Q's taunt window.
        """
        amount = Decimal(6) * self._packmate_damage(context)
        base = self._sequence_base(context) + 200
        return tuple(
            action(
                f"NAAFIRI_PASSIVE_SIX_PACKMATES_ATTACK_{index}",
                at_ms=at_ms,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(damage(context.opponent_entity, amount, DamageType.PHYSICAL),),
            )
            for index, at_ms in enumerate((1450, 2900), start=1)
            if at_ms <= context.duration_ms
        )

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Naafiri attacks with W's temporary total-AD increase.

        :param context: Snapshot supplying attack speed, AD, and duration.
        :return: Chronological basic attacks outside fixed spell timestamps.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 400
        events: list[ActionEvent] = []
        for index, at_ms in enumerate(range(2600, context.duration_ms + 1, interval), start=1):
            amount = context.snapshot.attack_damage
            if at_ms < 5000:
                amount += Decimal("0.20") * context.snapshot.attack_damage
            events.append(
                action(
                    f"NAAFIRI_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(damage(context.opponent_entity, amount, DamageType.PHYSICAL),),
                )
            )
        return tuple(events)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose W1's locked twenty-percent movement-speed steroid.

        :param context: Role-bound Naafiri encounter context.
        :return: Hunt movement-speed multiplier.
        """
        return Decimal("1.20")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose R2's targeted nine-hundred-unit pursuit range.

        :param context: Role-bound Naafiri encounter context.
        :return: Hounds' Pursuit range in game units.
        """
        return Decimal(900)

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Avoid treating Q2 champion-hit healing as unconditional sustain.

        :param context: Role-bound Naafiri encounter context.
        :param duration_ms: Requested lane observation duration.
        :param no_damage_delay_ms: Time since the last incoming damage event.
        :return: Zero extra health and a hit/resource blocker.
        """
        return Decimal(0), ("NAAFIRI_Q2_HEAL_REQUIRES_BLEEDING_CHAMPION_HIT_AND_MANA",)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the selected fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Naafiri-scoped blocker, or ``None`` for represented channels.
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
            return f"NAAFIRI_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build W empowerment, R entry, both Q casts, E, packmates, and attacks.

        :param context: Role-bound Naafiri and opponent snapshots.
        :return: Deterministic level-13 action schedule.
        """
        bonus_ad = self._w_bonus_ad(context)
        base = self._sequence_base(context)
        r_single = Decimal(200) + bonus_ad
        r_total = r_single * Decimal("1.60")
        first_q = Decimal(55) + Decimal("0.20") * bonus_ad
        bleed_total = Decimal(135) + Decimal("0.80") * bonus_ad
        second_min = Decimal(80) + Decimal("0.40") * bonus_ad
        second_max = Decimal(2) * (Decimal(80) + Decimal("0.70") * bonus_ad)
        fixed = (
            action(
                "NAAFIRI_W_CALL_OF_THE_PACK",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(context.self_entity, "NAAFIRI_W_HUNT", 5000),
                    movement_speed(
                        context.self_entity,
                        Decimal("0.20") * context.snapshot.move_speed,
                        duration_ms=5000,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "NAAFIRI_R_HOUNDS_PURSUIT_SIX_PACKMATES",
                at_ms=self._R_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_total, DamageType.PHYSICAL),
                    StatModifierOutput(context.opponent_entity, "ARMOR", Decimal(-30), 3000),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=250,
                        magnitude=Decimal("0.99"),
                    ),
                ),
            ),
            action(
                "NAAFIRI_Q_DARKIN_DAGGERS_FIRST",
                at_ms=self._FIRST_Q_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, first_q, DamageType.PHYSICAL),),
            ),
            action(
                "NAAFIRI_Q_BLEED_TICK_BEFORE_RECAST",
                at_ms=self._FIRST_Q_AT_MS + 500,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(
                    damage(context.opponent_entity, bleed_total / Decimal(10), DamageType.PHYSICAL),
                ),
            ),
            action(
                "NAAFIRI_Q_DARKIN_DAGGERS_RECAST",
                at_ms=self._SECOND_Q_AT_MS,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity, bleed_total * Decimal("0.90"), DamageType.PHYSICAL
                    ),
                    MissingHealthDamageOutput(
                        context.opponent_entity,
                        second_min,
                        (second_max - second_min) / context.opponent_snapshot.max_hp,
                        DamageType.PHYSICAL,
                    ),
                    healing(context.self_entity, Decimal(105) + Decimal("0.40") * bonus_ad),
                ),
            ),
            action(
                "NAAFIRI_E_EVISCERATE_BOTH_SLASHES",
                at_ms=self._E_AT_MS,
                sequence=base + 5,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(55) + Decimal("0.40") * bonus_ad,
                        DamageType.PHYSICAL,
                    ),
                    damage(
                        context.opponent_entity,
                        Decimal(160) + Decimal("0.80") * bonus_ad,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
        )
        events = (*fixed, *self._packmate_events(context), *self._attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"NAAFIRI_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "naafiri_q5_w1_e5_r2_current_rework_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "NAAFIRI_LEVEL13_Q5_E5_W1_R2_ORDER_LOCKED_UNVERIFIED",
                "NAAFIRI_CURRENT_PATCH_W_IS_CALL_OF_THE_PACK_R_IS_HOUNDS_PURSUIT",
                "NAAFIRI_W_STARTS_WITH_FOUR_LIVING_PACKMATES_AND_ADDS_TWO_ASSUMED",
                "NAAFIRI_W_UNTARGETABLE_REQUIRES_TARGETABILITY_METADATA",
                "NAAFIRI_R_ALL_SIX_PACKMATES_CONNECT_ASSUMED",
                "NAAFIRI_R_FLAT_ARMOR_SHRED_LEVEL13_DERIVED_UNVERIFIED",
                "NAAFIRI_Q2_AT_750MS_CONSUMES_NINE_REMAINING_BLEED_TICKS_ASSUMED",
                "NAAFIRI_Q2_MISSING_HEALTH_INTERPOLATION_ASSUMED_LINEAR",
                "NAAFIRI_PACKMATE_ATTACK_CADENCE_SYNTHETIC",
                "NAAFIRI_E_RECALL_HEALS_PACKMATES_ONLY",
                "NAAFIRI_R_TAKEDOWN_RECAST_AND_SHIELD_NOT_AVAILABLE_WITHOUT_TAKEDOWN",
                "NAAFIRI_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose R's brief slow without treating W as universal immunity.

        :param context: Role-bound Naafiri and opponent snapshots.
        :return: Pursuit slow and targetability/recast blockers.
        """
        return ReactionPlan(
            "naafiri_r_slow_w_targetability_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "naafiri_r_hounds_pursuit_slow",
                    self._R_AT_MS,
                    min(self._R_AT_MS + 250, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "NAAFIRI_R_HOUNDS_PURSUIT_SIX_PACKMATES",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=(
                "NAAFIRI_W_UNTARGETABLE_REQUIRES_TARGETABILITY_METADATA",
                "NAAFIRI_R_RECAST_SHIELD_REQUIRES_TAKEDOWN_STATE",
            ),
        )
