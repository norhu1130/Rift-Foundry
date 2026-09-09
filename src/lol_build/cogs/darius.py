"""Darius champion Cog."""

from __future__ import annotations

from decimal import Decimal

from lol_build.cogs.base import (
    ActionPlan,
    CastBlockWindow,
    ChampionCog,
    CogCapability,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    DamageOutput,
    EntityId,
    StatusOutput,
    opponent_sequence_offset,
)


class DariusCog(ChampionCog):
    """Own Darius's role-neutral rotation and reaction behavior."""

    rotation_model_id = "darius_five_stack_execute_8s_v1"
    recommendation_model_id = "generic_cog_build_preview_v1"
    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = frozenset(
        {
            CogCapability.BASIC_ATTACK,
            CogCapability.ABILITY_ROTATION,
            CogCapability.REACTION_MODEL,
            CogCapability.ITEM_POLICY,
            CogCapability.RECOMMENDATION,
        }
    )

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats absent from the synthetic Darius model.

        :param item: Normalized item candidate.
        :return: Blocker code or ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {"AP", "HEAL_SHIELD_POWER", "CRITICAL_STRIKE_CHANCE"} & stats.keys()
        if unsupported:
            return f"DARIUS_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Darius's generic Cog timeline for arbitrary opponents.

        :param context: Role-bound combat snapshots.
        :return: Basic attacks, W, Q, and fixed-stack R actions.
        """
        sequence = self._sequence_base(context)
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        schedule: list[tuple[int, str, Decimal, DamageType]] = [
            (200, "ATTACK", context.snapshot.attack_damage, DamageType.PHYSICAL),
            (450, "W", Decimal("1.4") * context.snapshot.attack_damage, DamageType.PHYSICAL),
            (
                1700,
                "Q",
                Decimal(170) + Decimal("1.4") * context.snapshot.attack_damage,
                DamageType.PHYSICAL,
            ),
            (
                3000,
                "R",
                (Decimal(250) + Decimal("0.75") * context.snapshot.bonus_attack_damage)
                * Decimal(2),
                DamageType.TRUE,
            ),
        ]
        at_ms = 200 + interval
        while at_ms <= context.duration_ms:
            schedule.append((at_ms, "ATTACK", context.snapshot.attack_damage, DamageType.PHYSICAL))
            at_ms += interval
        events: list[ActionEvent] = []
        for at_ms, name, amount, damage_type in sorted(schedule):
            events.append(
                ActionEvent(
                    f"DARIUS_{name}_{sequence}",
                    at_ms,
                    sequence,
                    context.self_entity,
                    ActionChannel.BASIC_ATTACK
                    if name in {"ATTACK", "W"}
                    else ActionChannel.ABILITY,
                    (DamageOutput(context.opponent_entity, amount, damage_type),),
                )
            )
            sequence += 1
        return ActionPlan(
            "darius_five_stack_execute_8s_cog_v1",
            tuple(events),
            (
                "DARIUS_COG_FIXED_FIVE_STACK_R_TIMING_UNVERIFIED",
                "DARIUS_COG_HEMORRHAGE_NOT_EVALUATED",
                "DARIUS_COG_Q_HEAL_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Build Darius E pull and W slow reactions.

        :param context: Role-bound combat snapshots.
        :return: Synthetic control reaction plan.
        """
        return ReactionPlan(
            "darius_e_w_control_reaction_v1",
            events=(
                ActionEvent(
                    "DARIUS_W_SLOW",
                    450,
                    (20_000 if context.self_entity is EntityId.ACTOR else 30_000)
                    + opponent_sequence_offset(context.self_entity),
                    context.self_entity,
                    ActionChannel.BASIC_ATTACK,
                    (StatusOutput(context.opponent_entity, "CC_SLOW", 1000, Decimal("0.90")),),
                ),
            ),
            cast_block_windows=(
                CastBlockWindow(
                    "darius_e_pull",
                    100,
                    min(350, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY),
                ),
            ),
            blockers=("DARIUS_E_W_CONTROL_TIMING_UNVERIFIED",),
        )
