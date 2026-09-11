"""Karma combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, movement_speed, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class KarmaCog(ChampionCog):
    """Model Karma's Q5/W1/E5/R2 level-13 Soulflare fixture.

    The deterministic Mantra choice is RQ: Soulflare hits one opponent and its
    field detonates after the locked 1.5-second fixture delay. Focused Resolve
    completes its tether, Inspire targets Karma herself, and ordinary attacks
    fill the remaining duel window. Ally-only and alternate Mantra effects stay
    explicit blockers rather than being redirected to an enemy.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Karma.json",
        "data/raw/16.17.1/communitydragon/champions/43.json",
        "data/raw/16.17.1/communitydragon/champions/karma.bin.json",
    )

    _RQ_IMPACT_AT_MS = 100
    _RQ_FIELD_AT_MS = 1600
    _W_INITIAL_AT_MS = 2200
    _W_COMPLETE_AT_MS = 4200
    _E_SELF_AT_MS = 4500
    _Q_SECOND_AT_MS = 5300

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose rank-five Inspire's self-targeted pursuit option.

        :param context: Role-bound Karma encounter context.
        :return: Locked forty-percent movement-speed multiplier.
        """
        return Decimal("1.40")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Report that Karma has no displacement-based gap closer.

        :param context: Role-bound Karma encounter context.
        :return: Zero game units.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Karma's fixed duel policy.

        AP changes every modeled spell and shield, while attack damage and
        attack speed reach ordinary attacks. The fixed schedule does not spend
        mana, scale cooldowns, sample critical strikes, or apply sustain and
        shield amplification stats that are absent from champion snapshots.

        :param item: Normalized candidate from the locked item catalog.
        :return: Karma-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"KARMA_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule deterministic ordinary attacks after Soulflare impact.

        The passive's Mantra refund is not emitted because the event model has
        no cooldown-resource output and the selected fixture casts Mantra once.

        :param context: Role-bound snapshots supplying attack damage and cadence.
        :return: Chronological attacks on the basic-attack channel.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 650
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"KARMA_BASIC_ATTACK_{len(events) + 1}",
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

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Soulflare, Focused Resolve, Inspire, Q, and attacks.

        Soulflare combines rank-five Q with the rank-two Mantra impact bonus,
        then applies the rank-two field damage separately. W assumes its tether
        remains intact for two seconds. E is a valid self cast; no ally or RE
        area recipient exists in the engine's two-opponent contract.

        :param context: Role-bound Karma and opponent combat snapshots.
        :return: Deterministic level-13 events with unresolved assumptions.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        q_damage = Decimal(260) + Decimal("0.70") * ap
        w_damage = Decimal(40) + Decimal("0.45") * ap
        rq_impact_bonus = Decimal(100) + Decimal("0.30") * ap
        rq_field_damage = Decimal(130) + Decimal("0.50") * ap
        e_shield = Decimal(280) + Decimal("0.60") * ap
        events = (
            action(
                "KARMA_RQ_SOULFLARE_IMPACT",
                at_ms=self._RQ_IMPACT_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        q_damage + rq_impact_bonus,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=1500,
                        magnitude=Decimal("0.50"),
                    ),
                ),
            ),
            action(
                "KARMA_RQ_SOULFLARE_FIELD_DETONATION",
                at_ms=self._RQ_FIELD_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(
                    damage(
                        context.opponent_entity,
                        rq_field_damage,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=1500,
                        magnitude=Decimal("0.50"),
                    ),
                ),
            ),
            action(
                "KARMA_W_FOCUSED_RESOLVE_INITIAL",
                at_ms=self._W_INITIAL_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, w_damage, DamageType.MAGIC),),
            ),
            action(
                "KARMA_W_FOCUSED_RESOLVE_COMPLETE",
                at_ms=self._W_COMPLETE_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(
                    damage(context.opponent_entity, w_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity,
                        "ROOT",
                        duration_ms=1600,
                    ),
                ),
            ),
            action(
                "KARMA_E_INSPIRE_SELF",
                at_ms=self._E_SELF_AT_MS,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(context.self_entity, e_shield, duration_ms=2500),
                    movement_speed(
                        context.self_entity,
                        context.snapshot.move_speed * Decimal("0.40"),
                        duration_ms=2000,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "KARMA_Q_INNER_FLAME_SECOND",
                at_ms=self._Q_SECOND_AT_MS,
                sequence=base + 5,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=1500,
                        magnitude=Decimal("0.40"),
                    ),
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"KARMA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "karma_q5_w1_e5_r2_soulflare_level13_locked_v1",
            tuple(
                sorted(
                    (*events, *self._basic_attacks(context)),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "KARMA_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "KARMA_MANTRA_RQ_VARIANT_SELECTION_UNVERIFIED",
                "KARMA_RW_RENEWAL_VARIANT_NOT_SELECTED",
                "KARMA_RE_DEFIANCE_VARIANT_NOT_SELECTED",
                "KARMA_RQ_PROJECTILE_HIT_AND_FIELD_OCCUPANCY_UNVERIFIED",
                "KARMA_W_TETHER_REMAINS_IN_RANGE_FIXTURE",
                "KARMA_W_COMPLETION_CANCEL_CAUSALITY_NOT_MODELED",
                "KARMA_E_ALLY_TARGET_NOT_REPRESENTED_IN_TWO_COMBATANT_DUEL",
                "KARMA_RE_ALLY_AREA_SHIELDS_NOT_REPRESENTED_IN_TWO_COMBATANT_DUEL",
                "KARMA_PASSIVE_MANTRA_COOLDOWN_REFUND_NOT_MODELED",
                "KARMA_MULTI_TARGET_EFFECTS_NOT_MODELED",
                "KARMA_CAST_AND_ATTACK_TIMING_UNVERIFIED",
                "KARMA_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Soulflare slows, W's delayed root, and ordinary Q slow.

        :param context: Role-bound Karma and opponent combat snapshots.
        :return: Source-linked, tenacity-reducible movement-control windows.
        """
        windows = (
            CastBlockWindow(
                "karma_rq_soulflare_impact_slow",
                self._RQ_IMPACT_AT_MS,
                min(self._RQ_FIELD_AT_MS, context.duration_ms),
                (ActionChannel.MOVEMENT,),
                "KARMA_RQ_SOULFLARE_IMPACT",
                True,
                ControlType.SLOW,
            ),
            CastBlockWindow(
                "karma_rq_soulflare_field_slow",
                self._RQ_FIELD_AT_MS,
                min(self._RQ_FIELD_AT_MS + 1500, context.duration_ms),
                (ActionChannel.MOVEMENT,),
                "KARMA_RQ_SOULFLARE_FIELD_DETONATION",
                True,
                ControlType.SLOW,
            ),
            CastBlockWindow(
                "karma_w_focused_resolve_root",
                self._W_COMPLETE_AT_MS,
                min(self._W_COMPLETE_AT_MS + 1600, context.duration_ms),
                (ActionChannel.MOVEMENT,),
                "KARMA_W_FOCUSED_RESOLVE_COMPLETE",
                True,
                ControlType.ROOT,
            ),
            CastBlockWindow(
                "karma_q_inner_flame_second_slow",
                self._Q_SECOND_AT_MS,
                min(self._Q_SECOND_AT_MS + 1500, context.duration_ms),
                (ActionChannel.MOVEMENT,),
                "KARMA_Q_INNER_FLAME_SECOND",
                True,
                ControlType.SLOW,
            ),
        )
        return ReactionPlan(
            "karma_rq_q5_w1_control_level13_locked_v1",
            cast_block_windows=windows,
            blockers=(
                "KARMA_RQ_SLOW_FIELD_CONTACT_NOT_CAUSALLY_MODELED",
                "KARMA_W_ROOT_REQUIRES_UNBROKEN_TETHER",
                "KARMA_Q_PROJECTILE_HITS_ASSUMED",
                "KARMA_MOVEMENT_SPEED_REDUCTION_NOT_INTEGRATED_IN_TIMELINE",
            ),
        )
