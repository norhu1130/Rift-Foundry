"""Illaoi combat Cog for the locked level-13 duel benchmark."""

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
from lol_build.cogs.mechanics import action, damage, missing_health_healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class IllaoiCog(ChampionCog):
    """Model Illaoi's Q5/W1/E5/R2 level-13 duel sequence.

    The fixed policy includes damage that is independent of world geometry:
    Tentacle Smash, Harsh Lesson's empowered attack, Leap of Faith's impact,
    and ordinary attacks. Test of Spirit is deliberately not assigned damage;
    it creates a separate spirit whose damage echo requires entity and health
    state unavailable to the shared two-participant timeline. Likewise, no
    passive, W-commanded, E-vessel, or R-spawned tentacle hit is fabricated.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Illaoi.json",
        "data/raw/16.17.1/communitydragon/champions/420.json",
        "data/raw/16.17.1/communitydragon/champions/illaoi.bin.json",
    )

    @staticmethod
    def _level_base_tentacle_damage(level: int) -> Decimal:
        """Interpolate the locked 9-to-180 tentacle base-damage curve.

        :param level: Champion level selecting the linear curve point.
        :return: Raw base damage before offensive scaling and Q amplification.
        """
        bounded_level = min(18, max(1, level))
        return Decimal(9) + Decimal(171 * (bounded_level - 1)) / Decimal(17)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Harsh Lesson's displayed target acquisition range.

        :param context: Role-bound combat snapshots for the encounter.
        :return: Locked maximum W leap range in game units.
        """
        return Decimal(400)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Illaoi's fixed duel policy.

        AD, AP, attack speed, health, defenses, penetration, movement, and
        tenacity reach a modeled formula or shared snapshot. Fixed timestamps
        cannot value haste, while critical and sustain channels are omitted.

        :param item: Normalized candidate from the locked item catalog.
        :return: Illaoi-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "CRITICAL_STRIKE_CHANCE",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"ILLAOI_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _ordinary_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks independently of W attack resets.

        :param context: Role-bound snapshots supplying attack damage and cadence.
        :return: Deterministic physical basic attacks through the duel duration.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 600
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"ILLAOI_BASIC_ATTACK_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=base + len(events),
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
            at_ms += interval_ms
        return tuple(events)

    def _harsh_lesson_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule W resets at the locked two-second ultimate cooldown.

        The event contains only Illaoi's attack and W bonus. Nearby tentacle
        commands remain excluded because the context carries no placement data.

        :param context: Role-bound snapshots supplying total AD and target health.
        :return: Empowered basic attacks during the eight-second ultimate window.
        """
        total_ad = context.snapshot.attack_damage
        health_ratio = Decimal("0.03") + Decimal("0.00035") * total_ad
        bonus_damage = health_ratio * context.opponent_snapshot.max_hp
        base = self._sequence_base(context) + 200
        return tuple(
            action(
                f"ILLAOI_W_HARSH_LESSON_{index}",
                at_ms=at_ms,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity,
                        total_ad,
                        DamageType.PHYSICAL,
                    ),
                    damage(
                        context.opponent_entity,
                        bonus_damage,
                        DamageType.PHYSICAL,
                    ),
                ),
            )
            for index, at_ms in enumerate(range(2200, context.duration_ms + 1, 2000), 1)
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked Q5/W1/E5/R2 level-13 action policy.

        E is represented only by an audit blocker because the event model has no
        independent spirit entity. The rotation therefore starts its guaranteed
        damaging portion with R and retains E's intended opener in the model id.

        :param context: Role-bound Illaoi and opponent combat snapshots.
        :return: Deterministic direct damage plus geometry and state blockers.
        """
        base = self._sequence_base(context)
        tentacle_damage = Decimal("1.30") * (
            self._level_base_tentacle_damage(context.snapshot.level)
            + Decimal("1.10") * context.snapshot.attack_damage
            + Decimal("0.40") * context.snapshot.ability_power
        )
        r_damage = Decimal(250) + Decimal("0.50") * (context.snapshot.bonus_attack_damage)
        fixed_events = (
            action(
                "ILLAOI_R_LEAP_OF_FAITH",
                at_ms=100,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, r_damage, DamageType.PHYSICAL),),
            ),
            action(
                "ILLAOI_Q_TENTACLE_SMASH",
                at_ms=1500,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        tentacle_damage,
                        DamageType.PHYSICAL,
                    ),
                    # Prophet of an Elder God: a tentacle hitting a champion heals
                    # MissingHPPercentHeal (5%) of Illaoi's missing health.
                    missing_health_healing(context.self_entity, Decimal("0.05")),
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"ILLAOI_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "illaoi_q5_w1_e5_r2_level13_synthetic_v1",
            tuple(
                sorted(
                    (
                        *fixed_events,
                        *self._ordinary_attacks(context),
                        *self._harsh_lesson_events(context),
                    ),
                    key=lambda event: (event.at_ms, event.sequence),
                )
            ),
            (
                *level_blockers,
                "ILLAOI_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "ILLAOI_CAST_AND_HIT_TIMING_UNVERIFIED",
                "ILLAOI_E_SPIRIT_ENTITY_AND_DAMAGE_ECHO_NOT_MODELED",
                "ILLAOI_E_VESSEL_STATE_AND_SLOW_NOT_MODELED",
                "ILLAOI_TENTACLE_PLACEMENT_AND_HIT_GEOMETRY_NOT_MODELED",
                "ILLAOI_R_MULTI_TARGET_TENTACLE_COUNT_NOT_MODELED",
                "ILLAOI_W_DURING_R_COOLDOWN_FIXTURE_ASSUMED",
                "ILLAOI_RESOURCE_BUDGET_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Return a neutral reaction plan with E state limitations exposed.

        Illaoi's modeled rotation applies no direct crowd control. E's slow is
        conditional on destroying or outranging a separate spirit entity, so it
        cannot honestly become an unconditional cast-block window.

        :param context: Role-bound Illaoi encounter context.
        :return: Empty reaction effects and explicit spirit-state blockers.
        """
        return ReactionPlan(
            "illaoi_e_spirit_reaction_blocked_v1",
            blockers=(
                "ILLAOI_E_SPIRIT_ENTITY_AND_DAMAGE_ECHO_NOT_MODELED",
                "ILLAOI_E_VESSEL_STATE_AND_SLOW_NOT_MODELED",
                "ILLAOI_TENTACLE_PLACEMENT_AND_HIT_GEOMETRY_NOT_MODELED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Decline to infer tentacle healing without health and geometry traces.

        :param context: Role-bound snapshot for the lane participant.
        :param duration_ms: Lane observation duration in milliseconds.
        :param no_damage_delay_ms: Delay before out-of-combat recovery begins.
        :return: Zero recovery and the missing tentacle-state blocker.
        """
        return Decimal(0), ("ILLAOI_LANE_TENTACLE_HITS_AND_MISSING_HEALTH_NOT_MODELED",)
