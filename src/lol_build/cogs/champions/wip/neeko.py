"""Neeko combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, movement_speed
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class NeekoCog(ChampionCog):
    """Model Neeko's Q5/E5/W1/R2 single-target ambush fixture.

    W grants its movement window without inventing clone damage or immunity. E
    uses its unempowered root because the duel contains no intervening unit. Q
    blooms three times after hitting the champion, R separates airborne setup
    from landing damage and stun, and every third attack gains W damage.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Neeko.json",
        "data/raw/16.17.1/communitydragon/champions/518.json",
        "data/raw/16.17.1/communitydragon/champions/neeko.bin.json",
    )

    _W_AT_MS = 0
    _E_AT_MS = 500
    _Q_AT_MS = 600
    _R_CAST_AT_MS = 1000
    _R_AIRBORNE_AT_MS = 2250
    _R_LAND_AT_MS = 2850

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Create Q5's initial bloom and two champion-triggered repeats.

        :param context: Snapshot supplying AP, roles, and duration.
        :return: Three Blooming Burst damage events.
        """
        ap = context.snapshot.ability_power
        amounts = (
            Decimal(260) + Decimal("0.60") * ap,
            Decimal(135) + Decimal("0.25") * ap,
            Decimal(135) + Decimal("0.25") * ap,
        )
        base = self._sequence_base(context) + 100
        return tuple(
            action(
                f"NEEKO_Q_BLOOMING_BURST_{index}",
                at_ms=self._Q_AT_MS + (index - 1) * 750,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.ABILITY if index == 1 else ActionChannel.PASSIVE,
                outputs=(damage(context.opponent_entity, amount, DamageType.MAGIC),),
            )
            for index, amount in enumerate(amounts, start=1)
            if self._Q_AT_MS + (index - 1) * 750 <= context.duration_ms
        )

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks and W1 bonus magic damage every third hit.

        :param context: Snapshot supplying AD, AP, speed, and duration.
        :return: Chronological basic attacks with deterministic third-hit procs.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        bonus = Decimal(30) + Decimal("0.60") * context.snapshot.ability_power
        base = self._sequence_base(context) + 400
        events: list[ActionEvent] = []
        for index, at_ms in enumerate(range(3100, context.duration_ms + 1, interval), start=1):
            outputs = [
                damage(
                    context.opponent_entity,
                    context.snapshot.attack_damage,
                    DamageType.PHYSICAL,
                )
            ]
            if index % 3 == 0:
                outputs.append(damage(context.opponent_entity, bonus, DamageType.MAGIC))
            events.append(
                action(
                    f"NEEKO_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
        return tuple(events)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose W1's locked twenty-percent active movement boost.

        :param context: Role-bound Neeko encounter context.
        :return: Shapesplitter movement-speed multiplier.
        """
        return Decimal("1.20")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return zero because Neeko has no displacement ability.

        :param context: Role-bound Neeko encounter context.
        :return: Zero dash distance.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the selected fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Neeko-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "CRITICAL_STRIKE_CHANCE",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            return f"NEEKO_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build W approach, basic E, three Q blooms, R phases, and attacks.

        :param context: Role-bound Neeko and opponent snapshots.
        :return: Deterministic level-13 action schedule.
        """
        ap = context.snapshot.ability_power
        base = self._sequence_base(context)
        fixed = (
            action(
                "NEEKO_W_SHAPESPLITTER",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(context.self_entity, "NEEKO_W_CLONE_ACTIVE", 3000),
                    movement_speed(
                        context.self_entity,
                        Decimal("0.20") * context.snapshot.move_speed,
                        duration_ms=3000,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "NEEKO_E_TANGLE_BARBS_UNEMPOWERED",
                at_ms=self._E_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(210) + Decimal("0.65") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "ROOT", duration_ms=1500),
                ),
            ),
            action(
                "NEEKO_R_POP_BLOSSOM_PREPARE",
                at_ms=self._R_CAST_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "NEEKO_R_PREPARING", 1850),),
                requires_living_opponent=False,
            ),
            action(
                "NEEKO_R_POP_BLOSSOM_AIRBORNE",
                at_ms=self._R_AIRBORNE_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=600),),
            ),
            action(
                "NEEKO_R_POP_BLOSSOM_LAND",
                at_ms=self._R_LAND_AT_MS,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(350) + Decimal("1.20") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=750),
                ),
            ),
        )
        events = (*fixed, *self._q_events(context), *self._attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"NEEKO_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "neeko_q5_w1_e5_r2_unempowered_e_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "NEEKO_LEVEL13_Q5_E5_W1_R2_ORDER_LOCKED_UNVERIFIED",
                "NEEKO_E_NO_INTERVENING_UNIT_SO_BASIC_ROOT_USED",
                "NEEKO_Q_TARGET_REMAINS_FOR_TWO_REPEAT_BLOOMS_ASSUMED",
                "NEEKO_R_PREPARATION_AND_LANDING_TIMING_DERIVED_UNVERIFIED",
                "NEEKO_R_LOCKED_TOOLTIP_DOES_NOT_DECLARE_SHIELD_SO_STALE_BIN_VALUES_IGNORED",
                "NEEKO_W_STEALTH_AND_CLONE_TARGET_DECEPTION_NOT_MODELED",
                "NEEKO_PASSIVE_DISGUISE_AND_UNIT_FORM_STATS_NOT_MODELED",
                "NEEKO_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose E root and R airborne-to-stun control sequence.

        :param context: Role-bound Neeko and opponent snapshots.
        :return: Three hostile control windows without clone immunity claims.
        """
        all_active = (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT)
        return ReactionPlan(
            "neeko_e_root_r_airborne_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "neeko_e_tangle_barbs_root",
                    self._E_AT_MS,
                    min(self._E_AT_MS + 1500, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "NEEKO_E_TANGLE_BARBS_UNEMPOWERED",
                    True,
                    ControlType.ROOT,
                ),
                CastBlockWindow(
                    "neeko_r_pop_blossom_airborne",
                    self._R_AIRBORNE_AT_MS,
                    min(self._R_LAND_AT_MS, context.duration_ms),
                    all_active,
                    "NEEKO_R_POP_BLOSSOM_AIRBORNE",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "neeko_r_pop_blossom_stun",
                    self._R_LAND_AT_MS,
                    min(self._R_LAND_AT_MS + 750, context.duration_ms),
                    all_active,
                    "NEEKO_R_POP_BLOSSOM_LAND",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(
                "NEEKO_W_STEALTH_AND_CLONE_REQUIRE_TARGET_SELECTION_MODEL",
                "NEEKO_R_TIMING_DERIVED_UNVERIFIED",
            ),
        )
