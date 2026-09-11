"""Tryndamere combat Cog for the locked level-13 duel benchmark."""

from __future__ import annotations

from decimal import Decimal

from lol_build.cogs.base import (
    ActionPlan,
    ChampionCog,
    CogCapability,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, DeathPreventionOutput, StatusOutput


class TryndamereCog(ChampionCog):
    """Model Tryndamere's attack-centric Q5/E5/R2 benchmark behavior."""

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
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Tryndamere.json",
        "data/raw/16.17.1/communitydragon/champions/23.json",
        "data/raw/16.17.1/communitydragon/champions/tryndamere.bin.json",
    )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Spinning Slash's locked traversal distance.

        :param context: Role-bound Tryndamere combat context.
        :return: Maximum E displacement in game units.
        """
        return Decimal(650)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item values absent from the fixed attack schedule.

        :param item: Normalized candidate item from the locked catalog.
        :return: Champion-scoped blocker, or ``None`` when represented.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "CRITICAL_STRIKE_CHANCE",
        } & stats.keys()
        if unsupported:
            return f"TRYNDAMERE_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build rank-five Spinning Slash followed by continuous attacks.

        Undying Rage applies its locked rank-two 50-health floor for five seconds.
        Fury, random critical strikes, and missing-health AD remain explicit blockers.

        :param context: Role-bound snapshots for Tryndamere and his opponent.
        :return: Deterministic attack schedule with unresolved-state blockers.
        """
        base = self._sequence_base(context)
        events = [
            action(
                "TRYNDAMERE_R_UNDYING_RAGE",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(context.self_entity, "TRYNDAMERE_UNDYING_RAGE", 5000),
                    DeathPreventionOutput(
                        context.self_entity,
                        health_floor=Decimal(50),
                        duration_ms=5000,
                        state_key="TRYNDAMERE_R_UNDYING_RAGE",
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "TRYNDAMERE_E_SPINNING_SLASH",
                at_ms=100,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(240)
                        + context.snapshot.bonus_attack_damage
                        + Decimal("0.80") * context.snapshot.ability_power,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
        ]
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        for index, at_ms in enumerate(range(300, context.duration_ms + 1, interval_ms), start=1):
            events.append(
                action(
                    f"TRYNDAMERE_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 100 + index,
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
            )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"TRYNDAMERE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "tryndamere_q5_w1_e5_r2_level13_locked_v1",
            tuple(events),
            (
                *level_blockers,
                "TRYNDAMERE_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "TRYNDAMERE_FURY_AND_CRITICAL_STRIKES_NOT_MODELED",
                "TRYNDAMERE_Q_MISSING_HEALTH_AD_NOT_MODELED",
                "TRYNDAMERE_W_DIRECTION_AND_AD_REDUCTION_NOT_MODELED",
                "TRYNDAMERE_R_REACTIVE_CAST_TIMING_NOT_MODELED",
                "TRYNDAMERE_E_CRIT_COOLDOWN_REFUND_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Declare that Undying Rage is already owned by the action timeline.

        :param context: Role-bound snapshots for Tryndamere and his opponent.
        :return: Neutral reaction plan without duplicate defensive events.
        """
        return ReactionPlan(
            "tryndamere_r_owned_by_action_timeline_v1",
        )
