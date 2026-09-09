"""Olaf combat Cog for the locked level-13 duel benchmark."""

from __future__ import annotations

from decimal import Decimal

from lol_build.cogs.base import (
    ActionPlan,
    ChampionCog,
    CogCapability,
    CogMaturity,
    ControlImmunityWindow,
    ControlType,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, StatusOutput


class OlafCog(ChampionCog):
    """Model Olaf's Q5/W1/E5/R2 benchmark rotation from locked data."""

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
        "data/raw/16.17.1/en_US/champion/Olaf.json",
        "data/raw/16.17.1/communitydragon/champions/2.json",
        "data/raw/16.17.1/communitydragon/champions/olaf.bin.json",
    )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Ragnarok rank two's initial pursuit multiplier.

        :param context: Role-bound Olaf combat context.
        :return: Locked R2 movement-speed multiplier.
        """
        return Decimal("1.45")

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats absent from the fixed Olaf schedule.

        :param item: Normalized candidate item from the locked catalog.
        :return: Champion-scoped blocker, or ``None`` when represented.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "OMNIVAMP",
        } & stats.keys()
        if unsupported:
            return f"OLAF_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build one Q, W-enhanced attacks, two E casts, and Ragnarok status.

        :param context: Role-bound snapshots for Olaf and his opponent.
        :return: Deterministic Olaf schedule with explicit state blockers.
        """
        base = self._sequence_base(context)
        r_bonus_ad = Decimal(20) + Decimal("0.25") * context.snapshot.attack_damage
        r_total_ad = context.snapshot.attack_damage + r_bonus_ad
        events = [
            action(
                "OLAF_R_RAGNAROK",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "OLAF_CC_IMMUNE", 8000),),
                requires_living_opponent=False,
            ),
            action(
                "OLAF_Q_UNDERTOW",
                at_ms=100,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(270) + context.snapshot.bonus_attack_damage + r_bonus_ad,
                        DamageType.PHYSICAL,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=3000,
                        magnitude=Decimal("0.50"),
                    ),
                ),
            ),
            action(
                "OLAF_W_TOUGH_IT_OUT",
                at_ms=150,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(shielding(context.self_entity, Decimal(10), duration_ms=2500),),
                requires_living_opponent=False,
            ),
        ]
        for index, at_ms in enumerate((500, 7500), start=1):
            events.append(
                action(
                    f"OLAF_E_RECKLESS_SWING_{index}",
                    at_ms=at_ms,
                    sequence=base + 10 + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal(250) + Decimal("0.50") * r_total_ad,
                            DamageType.TRUE,
                        ),
                    ),
                )
            )
        attack_speed_ratio = Decimal(
            str(
                (self.detail_root or {})
                .get("attackSpeedRatioModifiable", {})
                .get("baseValue", self.document["stats"]["attackspeed"])
            )
        )
        boosted_interval = self._attack_interval_ms(
            context.snapshot.attack_speed + attack_speed_ratio * Decimal("0.40")
        )
        normal_interval = self._attack_interval_ms(context.snapshot.attack_speed)
        at_ms = 300
        index = 1
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"OLAF_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 100 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            r_total_ad,
                            DamageType.PHYSICAL,
                        ),
                    ),
                )
            )
            at_ms += boosted_interval if at_ms < 5150 else normal_interval
            index += 1
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"OLAF_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "olaf_q5_w1_e5_r2_level13_locked_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            (
                *level_blockers,
                "OLAF_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "OLAF_R_DURATION_EXTENSION_ASSUMED_CONTINUOUS",
                "OLAF_PASSIVE_MISSING_HEALTH_SCALING_NOT_MODELED",
                "OLAF_W_MISSING_HEALTH_SHIELD_NOT_MODELED",
                "OLAF_Q_PICKUP_RESET_NOT_MODELED",
                "OLAF_E_ATTACK_REFUND_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Ragnarok's causally linked discrete control immunity.

        :param context: Role-bound snapshots for Olaf and his opponent.
        :return: Immunity active while the locked continuous Ragnarok window lasts.
        """
        return ReactionPlan(
            "olaf_r_cc_immunity_window_v1",
            control_immunity_windows=(
                ControlImmunityWindow(
                    "olaf_r_ragnarok_control_immunity",
                    0,
                    min(8000, context.duration_ms),
                    context.self_entity,
                    (ControlType.ALL,),
                    "OLAF_R_RAGNAROK",
                ),
            ),
            blockers=(
                "OLAF_R_CLEANSE_ON_CAST_NOT_MODELED",
            ),
        )
