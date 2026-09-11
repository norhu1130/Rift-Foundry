"""Katarina combat Cog backed by the locked 16.17.1 champion sources."""

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


class KatarinaCog(ChampionCog):
    """Model Katarina's Q5/W1/E5/R2 level-13 single-dagger channel fixture."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Katarina.json",
        "data/raw/16.17.1/communitydragon/champions/55.json",
        "data/raw/16.17.1/communitydragon/champions/katarina.bin.json",
    )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Shunpo's locked target range for engagement scoring.

        :param context: Role-bound Katarina encounter context.
        :return: Shunpo range in game units.
        """
        return Decimal(725)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject stat channels whose dynamic behavior cannot be credited.

        :param item: Normalized locked item candidate.
        :return: Katarina-scoped blocker or ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        return (
            f"KATARINA_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
            if unsupported
            else None
        )

    def _attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks outside the fixed ultimate channel.

        :param context: Role-bound combat snapshot.
        :return: Blind-susceptible physical attacks.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        return tuple(
            action(
                f"KATARINA_BASIC_ATTACK_{i}",
                at_ms=at,
                sequence=self._sequence_base(context) + 100 + i,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity, context.snapshot.attack_damage, DamageType.PHYSICAL
                    ),
                ),
            )
            for i, at in enumerate(range(1000, context.duration_ms + 1, interval), 1)
            if not 2500 <= at < 5000
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Q dagger, Shunpo pickup, and Death Lotus's fixed tick sequence.

        :param context: Role-bound level-13 duel context.
        :return: Chronological deterministic schedule.
        """
        ap, ad, base = (
            context.snapshot.ability_power,
            context.snapshot.attack_damage,
            self._sequence_base(context),
        )
        events = [
            action(
                "KATARINA_Q_BOUNCING_BLADE",
                at_ms=100,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(190) + Decimal("0.35") * ap,
                        DamageType.MAGIC,
                    ),
                    StatusOutput(context.opponent_entity, "KATARINA_DAGGER", 1500),
                ),
            ),
            action(
                "KATARINA_W_PREPARATION",
                at_ms=500,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.opponent_entity, "KATARINA_DAGGER", 1500),),
            ),
            action(
                "KATARINA_E_SHUNPO_DAGGER_PICKUP",
                at_ms=900,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(150) + Decimal("0.50") * ap + Decimal("0.40") * ad,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "KATARINA_R_DEATH_LOTUS_FULL_CHANNEL",
                at_ms=2500,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(700) + Decimal("2.85") * ap + Decimal("2.40") * ad,
                        DamageType.MAGIC,
                    ),
                    StatusOutput(context.self_entity, "KATARINA_R_CHANNELING", 2500),
                ),
            ),
        ]
        events.extend(self._attacks(context))
        return ActionPlan(
            "katarina_q5_w1_e5_r2_level13_dagger_channel_v1",
            tuple(
                sorted(
                    (e for e in events if e.at_ms <= context.duration_ms),
                    key=lambda e: (e.at_ms, e.sequence, e.id),
                )
            ),
            (
                (f"KATARINA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
                if context.snapshot.level != 13
                else ()
            )
            + (
                "KATARINA_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "KATARINA_Q_BOUNCE_AND_DAGGER_LANDING_GEOMETRY_NOT_MODELED",
                "KATARINA_W_DAGGER_PICKUP_POSITION_ASSUMED",
                "KATARINA_E_RESET_AND_TARGET_SELECTION_NOT_MODELED",
                "KATARINA_R_CHANNEL_INTERRUPTION_AND_PER_TARGET_TICKS_NOT_MODELED",
                "KATARINA_PASSIVE_TAKEDOWN_RESETS_NOT_MODELED",
                "KATARINA_MANALESS_COOLDOWN_STATE_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose no opponent control while retaining channel-interrupt uncertainty.

        :param context: Role-bound Katarina encounter context.
        :return: Empty reaction controls and explicit channel blocker.
        """
        return ReactionPlan(
            "katarina_no_control_reaction_v1",
            blockers=("KATARINA_R_CHANNEL_INTERRUPTION_AND_PER_TARGET_TICKS_NOT_MODELED",),
        )
