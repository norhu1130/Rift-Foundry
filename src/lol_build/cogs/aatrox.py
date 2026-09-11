"""Aatrox synthetic combat Cog for the locked level-13 benchmark."""

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
    StatModifierOutput,
    StatusOutput,
)


class AatroxCog(ChampionCog):
    """Model Q5/W1/E5/R2 without assuming Aatrox is always the defender."""

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
        """Return Aatrox E's assumed approach displacement.

        :param context: Concrete participant context.
        :return: Dash distance in game units.
        """
        return Decimal(300)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats absent from the synthetic Aatrox model.

        :param item: Normalized item candidate.
        :return: Blocker code or ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {"AP", "MANA"} & stats.keys()
        if unsupported:
            return f"AATROX_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Aatrox's deterministic passive, Q, W, and healing sequence.

        :param context: Role-bound combat snapshots.
        :return: Synthetic action plan with evidence blockers.
        """
        sequence = self._sequence_base(context)
        total_ad = context.snapshot.attack_damage
        # Q2/Q3 are 1.25x/1.5x; the current sweet spot adds 75% multiplicatively.
        q_factors = (Decimal("1.75"), Decimal("2.1875"), Decimal("2.625"))
        q_times = (500, 1400, 2400)
        passive_ratio = Decimal("0.04") + Decimal("0.06") * Decimal(
            context.snapshot.level - 1
        ) / Decimal(17)
        passive_raw = context.opponent_snapshot.max_hp * passive_ratio
        # Umbral Dash's passive (ESpellVamp 16% plus EVampHPRatio 1.1% per 100
        # bonus health) heals from all post-mitigation champion damage; the
        # timeline resolves it from each damage output, amplified by the R bonus.
        e_vamp = (Decimal("0.16") + Decimal("0.00011") * context.snapshot.bonus_health) * Decimal(
            "1.35"
        )
        events: list[ActionEvent] = [
            ActionEvent(
                "AATROX_E_UMBRAL_DASH_VAMP",
                0,
                sequence + 90,
                context.self_entity,
                ActionChannel.PASSIVE,
                (StatModifierOutput(context.self_entity, "OMNIVAMP", e_vamp, None),),
                requires_living_opponent=False,
            ),
            ActionEvent(
                "AATROX_PASSIVE_ATTACK",
                200,
                sequence,
                context.self_entity,
                ActionChannel.BASIC_ATTACK,
                (
                    DamageOutput(context.opponent_entity, total_ad, DamageType.PHYSICAL),
                    # PHealingRatio: the passive heals for 100% of its damage.
                    DamageOutput(
                        context.opponent_entity,
                        passive_raw,
                        DamageType.MAGIC,
                        source_heal_ratio=Decimal(1),
                    ),
                ),
            ),
        ]
        sequence += 1
        for index, (at_ms, factor) in enumerate(zip(q_times, q_factors, strict=True), start=1):
            raw = (Decimal(120) + Decimal("0.90") * total_ad) * factor
            events.append(
                ActionEvent(
                    f"AATROX_Q{index}_SWEETSPOT",
                    at_ms,
                    sequence,
                    context.self_entity,
                    ActionChannel.ABILITY,
                    (
                        DamageOutput(context.opponent_entity, raw, DamageType.PHYSICAL),
                        StatusOutput(context.opponent_entity, "CC_AIRBORNE", 250),
                    ),
                )
            )
            sequence += 1
        w_raw = Decimal(80) + Decimal("0.40") * total_ad
        events.append(
            ActionEvent(
                "AATROX_W_INFERNAL_CHAINS",
                800,
                sequence,
                context.self_entity,
                ActionChannel.ABILITY,
                (
                    DamageOutput(context.opponent_entity, w_raw, DamageType.PHYSICAL),
                    StatusOutput(context.opponent_entity, "CC_SLOW", 1500, Decimal("0.25")),
                ),
            )
        )
        return ActionPlan(
            "aatrox_q5_w1_e5_r2_level13_synthetic_v1",
            tuple(events),
            (
                "AATROX_FORMULAS_CURATED_UNVERIFIED",
                "AATROX_Q_SWEETSPOT_ASSUMPTION_UNVERIFIED",
                "AATROX_E_VAMP_AMPLIFICATION_BY_R_ASSUMED_CONSTANT",
                "AATROX_R_HEALING_AMPLIFICATION_ASSUMED_ACTIVE",
                "AATROX_PASSIVE_LEVEL_SCALING_INTERPOLATED_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Build causally linked Q sweet-spot airborne windows.

        :param context: Role-bound combat snapshots.
        :return: Airborne reaction plan.
        """
        windows = tuple(
            CastBlockWindow(
                f"aatrox_q{index}_airborne",
                at_ms,
                min(at_ms + 250, context.duration_ms),
                (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY),
                f"AATROX_Q{index}_SWEETSPOT",
            )
            for index, at_ms in enumerate((500, 1400, 2400), start=1)
        )
        return ReactionPlan(
            "aatrox_q_sweetspot_reaction_v1",
            cast_block_windows=windows,
            blockers=("AATROX_Q_HIT_CONFIRMATION_UNVERIFIED",),
        )
