"""Ornn combat Cog backed by locked 16.17.1 champion sources."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    CastBlockWindow,
    ChampionCog,
    ChampionSnapshot,
    CogMaturity,
    ControlImmunityWindow,
    ControlType,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput

#: Channels a displacement interrupts: the target can neither attack, cast, nor
#: move while it is being moved.
_ALL_CHANNELS = (
    ActionChannel.BASIC_ATTACK,
    ActionChannel.ABILITY,
    ActionChannel.MOVEMENT,
)


class OrnnCog(ChampionCog):
    """Model Ornn's W5/Q5/E1/R2 level-13 brittle combination."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Ornn.json",
        "data/raw/16.17.1/communitydragon/champions/516.json",
        "data/raw/16.17.1/communitydragon/champions/ornn.bin.json",
    )

    _Q_AT_MS = 0
    _E_AT_MS = 1000
    _W_AT_MS = 2500
    _BRITTLE_ATTACK_AT_MS = 3400
    _R1_AT_MS = 4200
    _R2_AT_MS = 5200

    def snapshot(
        self,
        *,
        level: int,
        item_stats: dict[str, Decimal] | None = None,
    ) -> ChampionSnapshot:
        """Apply Living Forge's base amplification to item armor and MR.

        :param level: Champion level used by the shared growth model.
        :param item_stats: Optional normalized permanent item modifiers.
        :return: Snapshot with ten percent additional item resistances.
        """
        items = item_stats or {}
        base = super().snapshot(level=level, item_stats=items)
        return replace(
            base,
            armor=base.armor + Decimal("0.10") * items.get("ARMOR", Decimal(0)),
            magic_resistance=(
                base.magic_resistance + Decimal("0.10") * items.get("MAGIC_RESISTANCE", Decimal(0))
            ),
        )

    @staticmethod
    def _brittle_ratio(level: int) -> Decimal:
        """Interpolate Brittle's maximum-health damage from level 1 to 18.

        :param level: Champion level in the inclusive range 1 through 18.
        :return: Fraction of target maximum health dealt when Brittle is consumed.
        """
        bounded = min(18, max(1, level))
        return Decimal("0.09") + Decimal("0.08") * Decimal(bounded - 1) / Decimal(17)

    def _bonus_resistances(self, context: ParticipantContext) -> tuple[Decimal, Decimal]:
        """Derive item bonus armor and MR from the amplified snapshot.

        :param context: Ornn snapshot and fixed level.
        :return: Bonus armor and magic resistance after Living Forge amplification.
        """
        naked = self.snapshot(level=context.snapshot.level)
        return (
            max(Decimal(0), context.snapshot.armor - naked.armor),
            max(Decimal(0), context.snapshot.magic_resistance - naked.magic_resistance),
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Keep Ornn's own approach speed unchanged.

        :param context: Role-bound Ornn encounter context.
        :return: Neutral self movement multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Searing Charge's locked dash range.

        :param context: Role-bound Ornn encounter context.
        :return: Rank-independent dash distance in game units.
        """
        return Decimal(650)

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Report no champion-native healing in the selected lane model.

        :param context: Role-bound Ornn lane context.
        :param duration_ms: Requested lane observation duration.
        :param no_damage_delay_ms: Time since the last incoming damage event.
        :return: Zero additional recovered health and no sustain blocker.
        """
        return Decimal(0), ()

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the fixed Ornn rotation.

        :param item: Normalized candidate from the locked item catalog.
        :return: Ornn-scoped blocker, or ``None`` for represented stats.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        return (
            f"ORNN_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
            if unsupported
            else None
        )

    def _w_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Emit Bellows Breath as five maximum-health magic-damage ticks.

        :param context: Snapshots supplying roles and opposing maximum health.
        :return: Five chronological flame ticks, with Brittle on the last.
        """
        per_tick = max(Decimal(56), Decimal("0.032") * context.opponent_snapshot.max_hp)
        base = self._sequence_base(context) + 20
        events = []
        for index in range(5):
            outputs = [damage(context.opponent_entity, per_tick, DamageType.MAGIC)]
            if index == 4:
                outputs.append(StatusOutput(context.opponent_entity, "ORNN_BRITTLE", 3000))
            events.append(
                action(
                    f"ORNN_W_BELLOWS_BREATH_TICK_{index + 1}",
                    at_ms=self._W_AT_MS + index * 150,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=tuple(outputs),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Q-pillar E, W-Brittle attack, and both ultimate passes.

        :param context: Role-bound level-13 Ornn encounter context.
        :return: Deterministic brittle-combination action schedule.
        """
        ad = context.snapshot.attack_damage
        ap = context.snapshot.ability_power
        bonus_armor, bonus_mr = self._bonus_resistances(context)
        brittle = self._brittle_ratio(context.snapshot.level) * context.opponent_snapshot.max_hp
        base = self._sequence_base(context)
        r_damage = Decimal(175) + Decimal("0.20") * ap
        fixed = (
            action(
                "ORNN_Q_VOLCANIC_RUPTURE",
                at_ms=self._Q_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(120) + Decimal("1.10") * ad,
                        DamageType.PHYSICAL,
                    ),
                    StatusOutput(context.opponent_entity, "ORNN_Q_SLOWED", 2000),
                ),
            ),
            action(
                "ORNN_E_SEARING_CHARGE_PILLAR_COLLISION",
                at_ms=self._E_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.MOVEMENT,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(80) + Decimal("0.40") * (bonus_armor + bonus_mr),
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
            action(
                "ORNN_BRITTLE_BASIC_ATTACK",
                at_ms=self._BRITTLE_ATTACK_AT_MS,
                sequence=base + 30,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(context.opponent_entity, ad, DamageType.PHYSICAL),
                    damage(context.opponent_entity, brittle, DamageType.MAGIC),
                ),
            ),
            action(
                "ORNN_R_CALL_FIRST_PASS",
                at_ms=self._R1_AT_MS,
                sequence=base + 40,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.MAGIC),
                    StatusOutput(context.opponent_entity, "ORNN_BRITTLE", 3000),
                ),
            ),
            action(
                "ORNN_R_CALL_REDIRECTED_PASS",
                at_ms=self._R2_AT_MS,
                sequence=base + 41,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.MAGIC),
                    damage(context.opponent_entity, brittle, DamageType.MAGIC),
                    StatusOutput(context.opponent_entity, "ORNN_BRITTLE", 3000),
                ),
            ),
        )
        events = (*fixed, *self._w_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"ORNN_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "ornn_w5_q5_e1_r2_brittle_combo_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "ORNN_LEVEL13_W5_Q5_E1_R2_ORDER_LOCKED_UNVERIFIED",
                "ORNN_Q_PILLAR_AND_E_TERRAIN_COLLISION_ASSUMED",
                "ORNN_W_ALL_FIVE_TICKS_ASSUMED_TO_HIT",
                "ORNN_R_BOTH_PASSES_ASSUMED_TO_HIT_PRIMARY_TARGET",
                "ORNN_MASTERWORK_ITEM_UPGRADE_NOT_REPRESENTED_BY_ITEM_STATS",
                "ORNN_FIELD_FORGING_OUT_OF_DUEL_SCOPE",
                "ORNN_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Q slow, E knockup, W unstoppable, and Brittle controls.

        :param context: Role-bound Ornn and opponent snapshots.
        :return: Hostile control and self control-immunity windows.
        """
        return ReactionPlan(
            "ornn_q5_w5_e1_r2_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "ornn_q_slow",
                    0,
                    2000,
                    (ActionChannel.MOVEMENT,),
                    "ORNN_Q_VOLCANIC_RUPTURE",
                    True,
                    ControlType.SLOW,
                ),
                CastBlockWindow(
                    "ornn_e_knockup",
                    1000,
                    2250,
                    _ALL_CHANNELS,
                    "ORNN_E_SEARING_CHARGE_PILLAR_COLLISION",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "ornn_brittle_attack_knockback",
                    3400,
                    3900,
                    _ALL_CHANNELS,
                    "ORNN_BRITTLE_BASIC_ATTACK",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "ornn_r_first_pass_slow",
                    4200,
                    6200,
                    (ActionChannel.MOVEMENT,),
                    "ORNN_R_CALL_FIRST_PASS",
                    True,
                    ControlType.SLOW,
                ),
                CastBlockWindow(
                    "ornn_r_redirected_brittle_knockup",
                    5200,
                    6500,
                    _ALL_CHANNELS,
                    "ORNN_R_CALL_REDIRECTED_PASS",
                    False,
                    ControlType.AIRBORNE,
                ),
            ),
            control_immunity_windows=(
                ControlImmunityWindow(
                    "ornn_w_unstoppable",
                    2500,
                    3250,
                    context.self_entity,
                    (ControlType.ALL,),
                    "ORNN_W_BELLOWS_BREATH_TICK_1",
                ),
            ),
            blockers=(
                "ORNN_BRITTLE_CONTROL_DURATION_AMPLIFICATION_ONLY_APPLIED_TO_SELECTED_R2",
                "ORNN_DISPLACEMENT_DISTANCE_NOT_MODELED",
            ),
        )
