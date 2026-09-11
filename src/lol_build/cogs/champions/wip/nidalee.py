"""Nidalee combat Cog backed by locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    ChampionCog,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, damage, missing_health_healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    MissingHealthDamageOutput,
    StatusOutput,
)


class NidaleeCog(ChampionCog):
    """Model a maximum-range human opener into a hunted cougar rotation.

    Q5 marks the target from maximum range, E5 heals Nidalee and grants attack
    speed, then rank-three cougar Pounce, Swipe, and Takedown resolve. The BIN
    exposes cougar effect arrays but not a structured hunted-Takedown formula,
    so only its base missing-health amplification is calculated.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Nidalee.json",
        "data/raw/16.17.1/communitydragon/champions/76.json",
        "data/raw/16.17.1/communitydragon/champions/nidalee.bin.json",
    )

    _SPEAR_AT_MS = 0
    _HEAL_AT_MS = 100
    _TRANSFORM_AT_MS = 200
    _POUNCE_AT_MS = 300
    _SWIPE_AT_MS = 500
    _TAKEDOWN_AT_MS = 700

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks using E5's seven-second attack-speed steroid.

        :param context: Snapshot supplying AD, attack speed, and duration.
        :return: Chronological cougar-form basic attacks after Takedown.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed * Decimal("1.70"))
        base = self._sequence_base(context) + 300
        return tuple(
            action(
                f"NIDALEE_COUGAR_BASIC_ATTACK_{index}",
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
            for index, at_ms in enumerate(range(1000, context.duration_ms + 1, interval), start=1)
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Prowl's hunted-target thirty-percent movement bonus.

        :param context: Role-bound Nidalee encounter context.
        :return: Hunted pursuit movement multiplier.
        """
        return Decimal("1.30")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose hunted Pounce's locked enhanced range.

        :param context: Role-bound Nidalee encounter context.
        :return: Enhanced Pounce distance in game units.
        """
        return Decimal(750)

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Avoid repeating Primal Surge without mana and missing-health state.

        :param context: Role-bound Nidalee encounter context.
        :param duration_ms: Requested lane observation duration.
        :param no_damage_delay_ms: Time since the last incoming damage event.
        :return: Zero extra health and a resource-state blocker.
        """
        return Decimal(0), ("NIDALEE_E_HEAL_REQUIRES_MANA_COOLDOWN_AND_MISSING_HEALTH",)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the selected fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Nidalee-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            return f"NIDALEE_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build spear, heal, transform, cougar skills, and accelerated attacks.

        :param context: Role-bound Nidalee and opponent snapshots.
        :return: Deterministic level-13 action schedule.
        """
        ap = context.snapshot.ability_power
        base = self._sequence_base(context)
        spear = Decimal("3.25") * (Decimal(150) + Decimal("0.50") * ap)
        takedown_min = (
            Decimal(55) + Decimal("0.75") * context.snapshot.attack_damage + Decimal("0.40") * ap
        )
        fixed = (
            action(
                "NIDALEE_Q_JAVELIN_TOSS_MAX_RANGE",
                at_ms=self._SPEAR_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, spear, DamageType.MAGIC),
                    StatusOutput(context.opponent_entity, "NIDALEE_HUNTED", 4000),
                ),
            ),
            action(
                "NIDALEE_E_PRIMAL_SURGE_SELF_MINIMUM",
                at_ms=self._HEAL_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                # MaxHealing doubles TotalHealing at MaxHealThreshold (5%) health;
                # read linearly: h * (1 + missing / (0.95 * max)).
                outputs=(
                    missing_health_healing(
                        context.self_entity,
                        min(
                            Decimal(1),
                            (Decimal(150) + Decimal("0.35") * ap)
                            / (Decimal("0.95") * context.snapshot.max_hp),
                        ),
                        base_amount=Decimal(150) + Decimal("0.35") * ap,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "NIDALEE_R_ASPECT_OF_THE_COUGAR",
                at_ms=self._TRANSFORM_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "NIDALEE_COUGAR_FORM", 7800),),
                requires_living_opponent=False,
            ),
            action(
                "NIDALEE_W_HUNTED_POUNCE_RANK3",
                at_ms=self._POUNCE_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(160) + Decimal("0.30") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "NIDALEE_E_SWIPE_RANK3",
                at_ms=self._SWIPE_AT_MS,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(200) + Decimal("0.45") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "NIDALEE_Q_TAKEDOWN_BASE_MISSING_HEALTH",
                at_ms=self._TAKEDOWN_AT_MS,
                sequence=base + 5,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    MissingHealthDamageOutput(
                        context.opponent_entity,
                        takedown_min,
                        takedown_min / context.opponent_snapshot.max_hp,
                        DamageType.MAGIC,
                    ),
                ),
            ),
        )
        events = (*fixed, *self._attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"NIDALEE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "nidalee_q5_w1_e5_r3_hunted_cougar_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "NIDALEE_LEVEL13_Q5_E5_W1_AUTO_R3_ORDER_LOCKED_UNVERIFIED",
                "NIDALEE_JAVELIN_MAXIMUM_DISTANCE_DAMAGE_ASSUMED",
                "NIDALEE_E_MISSING_HEALTH_AMPLIFICATION_READ_AS_LINEAR",
                "NIDALEE_HUNTED_TAKEDOWN_EXTRA_MULTIPLIER_NOT_STRUCTURED_IN_LOCKED_BIN",
                "NIDALEE_TAKEDOWN_BASE_MISSING_HEALTH_SCALING_ASSUMED_TO_DOUBLE",
                "NIDALEE_COUGAR_EFFECT_ARRAY_RANK3_MAPPING_UNVERIFIED",
                "NIDALEE_HUMAN_BUSHWHACK_NOT_USED_IN_SELECTED_ROTATION",
                "NIDALEE_FORM_SPECIFIC_BASE_STATS_NOT_MODELED",
                "NIDALEE_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Return a neutral reaction plan because selected skills add no CC.

        :param context: Role-bound Nidalee and opponent snapshots.
        :return: Empty reactions with form and Hunt verification blockers.
        """
        return ReactionPlan(
            "nidalee_no_control_reaction_v1",
            blockers=(
                "NIDALEE_FORM_SPECIFIC_DEFENSIVE_STATS_NOT_MODELED",
                "NIDALEE_BRUSH_MOVEMENT_ROUTE_NOT_MODELED",
            ),
        )
