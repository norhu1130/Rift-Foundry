"""Ahri synthetic combat Cog for the locked level-13 benchmark."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent, DamageOutput, StatusOutput


class AhriCog(ChampionCog):
    """Model Q5/W5/E1/R2 with deterministic skill-hit assumptions."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = frozenset(
        {
            CogCapability.BASIC_ATTACK,
            CogCapability.ABILITY_ROTATION,
            CogCapability.REACTION_MODEL,
            CogCapability.ENGAGEMENT,
            CogCapability.ITEM_POLICY,
            CogCapability.RECOMMENDATION,
        }
    )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return one assumed Spirit Rush approach displacement.

        :param context: Concrete participant context.
        :return: Dash distance in game units.
        """
        return Decimal(450)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats absent from the synthetic Ahri model.

        :param item: Normalized item candidate.
        :return: Blocker code or ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {"AD", "CRITICAL_STRIKE_CHANCE"} & stats.keys()
        if unsupported:
            return f"AHRI_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Ahri's deterministic E, W, Q, and R hit sequence.

        :param context: Role-bound combat snapshots.
        :return: Synthetic action plan with evidence blockers.
        """
        sequence = self._sequence_base(context)
        ap = context.snapshot.ability_power
        shapes = (
            ("AHRI_E_CHARM", 100, Decimal(80) + Decimal("0.75") * ap, DamageType.MAGIC),
            ("AHRI_W_FOX_FIRE", 250, Decimal(140) + Decimal("0.30") * ap, DamageType.MAGIC),
            ("AHRI_Q_OUTBOUND", 500, Decimal(140) + Decimal("0.45") * ap, DamageType.MAGIC),
            ("AHRI_Q_RETURN", 1000, Decimal(140) + Decimal("0.45") * ap, DamageType.TRUE),
            ("AHRI_R1_SPIRIT_RUSH", 1300, Decimal(120) + Decimal("0.35") * ap, DamageType.MAGIC),
            ("AHRI_R2_SPIRIT_RUSH", 2600, Decimal(120) + Decimal("0.35") * ap, DamageType.MAGIC),
            ("AHRI_R3_SPIRIT_RUSH", 3900, Decimal(120) + Decimal("0.35") * ap, DamageType.MAGIC),
        )
        events = []
        for event_id, at_ms, amount, damage_type in shapes:
            outputs = [DamageOutput(context.opponent_entity, amount, damage_type)]
            if event_id == "AHRI_E_CHARM":
                outputs.append(StatusOutput(context.opponent_entity, "CC_CHARM", 1200))
            events.append(
                ActionEvent(
                    event_id,
                    at_ms,
                    sequence,
                    context.self_entity,
                    ActionChannel.ABILITY,
                    tuple(outputs),
                )
            )
            sequence += 1
        return ActionPlan(
            "ahri_q5_w5_e1_r2_level13_synthetic_v1",
            tuple(events),
            (
                "AHRI_FORMULAS_CURATED_UNVERIFIED",
                "AHRI_ALL_SKILLS_HIT_ASSUMPTION_UNVERIFIED",
                "AHRI_R_THREE_CAST_TIMING_UNVERIFIED",
                "AHRI_PASSIVE_HEAL_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Build the causally linked Charm action-block window.

        :param context: Role-bound combat snapshots.
        :return: Charm reaction plan.
        """
        return ReactionPlan(
            "ahri_e_charm_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "ahri_e_charm",
                    100,
                    min(1300, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY),
                    "AHRI_E_CHARM",
                    True,
                ),
            ),
            blockers=("AHRI_E_HIT_CONFIRMATION_UNVERIFIED",),
        )
