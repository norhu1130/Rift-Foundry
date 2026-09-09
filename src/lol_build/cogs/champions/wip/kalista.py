"""Kalista combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class KalistaCog(ChampionCog):
    """Model Kalista's Q5/W1/E5/R2 level-13 isolated spear-stack fixture."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Kalista.json",
        "data/raw/16.17.1/communitydragon/champions/429.json",
        "data/raw/16.17.1/communitydragon/champions/kalista.bin.json",
    )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Report Fate's Call's unrepresented ally-dependent engage as no solo dash.

        :param context: Role-bound Kalista encounter context.
        :return: Zero game units.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Block stats whose resource or sustain behavior is outside this fixture.

        :param item: Normalized locked item candidate.
        :return: A Kalista-specific blocker or ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "MANA_REGEN",
            "OMNIVAMP",
        } & stats.keys()
        return (
            f"KALISTA_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
            if unsupported
            else None
        )

    def _attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Create spear-applying basic attacks from the live attack-speed snapshot.

        :param context: Role-bound combat context.
        :return: Physical attacks that add deterministic Rend stacks.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        return tuple(
            action(
                f"KALISTA_BASIC_ATTACK_SPEAR_{index}",
                at_ms=at_ms,
                sequence=self._sequence_base(context) + 100 + index,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity,
                        context.snapshot.attack_damage * Decimal("0.90"),
                        DamageType.PHYSICAL,
                    ),
                    StatusOutput(context.opponent_entity, "KALISTA_REND_SPEAR", 4000),
                ),
            )
            for index, at_ms in enumerate(range(700, context.duration_ms + 1, interval), 1)
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build a fixed Q hit, attacks, and three-spear Rend release.

        :param context: Role-bound level-13 duel context.
        :return: Deterministic action schedule with honest ally blockers.
        """
        ad, base = context.snapshot.attack_damage, self._sequence_base(context)
        events = [
            action(
                "KALISTA_Q_PIERCE_ASSUMED_HIT",
                at_ms=100,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, Decimal(280) + ad, DamageType.PHYSICAL),
                    StatusOutput(context.opponent_entity, "KALISTA_REND_SPEAR", 4000),
                ),
            ),
            action(
                "KALISTA_E_REND_THREE_STACK_RELEASE",
                at_ms=3100,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(60) + Decimal(3) * (Decimal(40) + Decimal("0.70") * ad),
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
        ]
        events.extend(self._attacks(context))
        return ActionPlan(
            "kalista_q5_w1_e5_r2_level13_rend_v1",
            tuple(
                sorted(
                    (e for e in events if e.at_ms <= context.duration_ms),
                    key=lambda e: (e.at_ms, e.sequence, e.id),
                )
            ),
            (
                (f"KALISTA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
                if context.snapshot.level != 13
                else ()
            )
            + (
                "KALISTA_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "KALISTA_E_STACK_COUNT_FIXED_TO_THREE",
                "KALISTA_E_KILL_RESET_NOT_MODELED",
                "KALISTA_PASSIVE_HOP_GEOMETRY_AND_ATTACK_WINDUP_NOT_MODELED",
                "KALISTA_W_SENTINEL_AND_MARK_ALLY_EFFECT_NOT_MODELED",
                "KALISTA_R_BOUND_ALLY_REQUIRED_NOT_MODELED",
                "KALISTA_Q_PIERCE_AND_SECONDARY_TARGETS_NOT_MODELED",
                "KALISTA_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Declare no solo opponent control from Kalista's represented rotation.

        :param context: Role-bound Kalista encounter context.
        :return: Empty control plan with Fate's Call blocker.
        """
        return ReactionPlan(
            "kalista_no_solo_control_reaction_v1",
            blockers=(
                "KALISTA_R_BOUND_ALLY_KNOCKUP_NOT_MODELED",
                "KALISTA_W_SENTINEL_VISION_NOT_MODELED",
            ),
        )
