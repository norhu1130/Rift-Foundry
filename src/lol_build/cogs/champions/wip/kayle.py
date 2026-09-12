"""Kayle combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, damage, healing, movement_speed
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class KayleCog(ChampionCog):
    """Model Kayle's Q5/W1/E5/R2 level-13 ranged, exalted single-target fixture."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Kayle.json",
        "data/raw/16.17.1/communitydragon/champions/10.json",
        "data/raw/16.17.1/communitydragon/champions/kayle.bin.json",
    )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Celestial Blessing's modeled self movement bonus.

        :param context: Role-bound Kayle encounter context.
        :return: Forty-percent movement multiplier.
        """
        return Decimal("1.40")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Report that Kayle has no displacement engage.

        :param context: Role-bound Kayle encounter context.
        :return: Zero game units.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Block resource and sustain channels not consumed by this fixture.

        :param item: Normalized locked item candidate.
        :return: Kayle-scoped blocker or ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        return (
            f"KAYLE_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
            if unsupported
            else None
        )

    def _attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule level-13 ranged, exalted attacks with fire-wave magic damage.

        :param context: Role-bound combat snapshot.
        :return: Chronological hybrid attacks.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        return tuple(
            action(
                f"KAYLE_EXALTED_BASIC_ATTACK_{i}",
                at_ms=at,
                sequence=self._sequence_base(context) + 100 + i,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity, context.snapshot.attack_damage, DamageType.PHYSICAL
                    ),
                    damage(
                        context.opponent_entity,
                        self.rank_value("KayleE", "PassiveDamage", context, Decimal(35))
                        + Decimal("0.20") * context.snapshot.ability_power,
                        DamageType.MAGIC,
                    ),
                ),
            )
            for i, at in enumerate(range(700, context.duration_ms + 1, interval), 1)
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Kayle's ranged Q, self W, E reset, and self-cast ultimate fixture.

        :param context: Role-bound level-13 duel context.
        :return: Deterministic plan and explicit self-ultimate limitation.
        """
        ap, ad, base = (
            context.snapshot.ability_power,
            context.snapshot.attack_damage,
            self._sequence_base(context),
        )
        events = [
            action(
                "KAYLE_Q_RADIANT_BLAST",
                at_ms=100,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(260) + Decimal("0.60") * ap + Decimal("1.00") * ad,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "KAYLE_W_CELESTIAL_BLESSING_SELF",
                at_ms=700,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    movement_speed(context.self_entity, Decimal("40"), duration_ms=2000),
                    # Rank-one TotalHeal: Heal plus 25% ability power.
                    healing(
                        context.self_entity,
                        self.rank_value("KayleW", "Heal", context, Decimal(55))
                        + Decimal("0.25") * ap,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "KAYLE_E_STARFIRE_SPELLBLADE",
                at_ms=1100,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(70) + Decimal("0.25") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "KAYLE_R_DIVINE_JUDGMENT_SELF",
                at_ms=3000,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(context.self_entity, "KAYLE_R_INVULNERABLE", 2500),
                    damage(
                        context.opponent_entity,
                        Decimal(350) + Decimal("0.80") * ap + Decimal("1.00") * ad,
                        DamageType.MAGIC,
                    ),
                ),
            ),
        ]
        events.extend(self._attacks(context))
        return ActionPlan(
            "kayle_q5_w1_e5_r2_level13_exalted_v1",
            tuple(
                sorted(
                    (e for e in events if e.at_ms <= context.duration_ms),
                    key=lambda e: (e.at_ms, e.sequence, e.id),
                )
            ),
            (
                (f"KAYLE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
                if context.snapshot.level != 13
                else ()
            )
            + (
                "KAYLE_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "KAYLE_PASSIVE_STACK_ENTRY_FIXED_TO_EXALTED",
                "KAYLE_Q_ARMOR_MAGIC_RESISTANCE_SHRED_NOT_MODELED",
                "KAYLE_W_ALLY_TARGET_REQUIRES_ALLIES",
                "KAYLE_E_MISSING_HEALTH_DAMAGE_AND_ATTACK_RESET_NOT_MODELED",
                "KAYLE_R_SELF_TARGET_AND_LANDING_DAMAGE_ASSUMED",
                "KAYLE_R_ALLY_TARGET_SELECTION_NOT_MODELED",
                "KAYLE_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose no opponent control and state self-ultimate timing uncertainty.

        :param context: Role-bound Kayle encounter context.
        :return: Empty opponent-control reaction plan.
        """
        return ReactionPlan(
            "kayle_no_control_reaction_v1",
            blockers=("KAYLE_R_INVULNERABILITY_REACTION_TIMING_NOT_MODELED",),
        )
