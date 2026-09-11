"""Blitzcrank combat Cog backed by the locked 16.17.1 sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, movement_speed
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class BlitzcrankCog(ChampionCog):
    """Model Blitzcrank's Q5/E5/W1/R2 level-13 hook fixture.

    Rocket Grab establishes the deterministic melee-entry assumption. Overdrive
    accelerates ordinary attacks for five seconds, Power Fist replaces one
    attack, and Static Field marks successful modeled attacks until its active
    cast. Geometry, collision, shield destruction, and Mana Barrier's health
    threshold remain explicit blockers instead of optimistic outputs.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Blitzcrank.json",
        "data/raw/16.17.1/communitydragon/champions/53.json",
        "data/raw/16.17.1/communitydragon/champions/blitzcrank.bin.json",
    )

    _W_END_MS = 5000
    _R_ACTIVE_MS = 5000
    _ATTACK_SPEED_RATIO = Decimal("0.625")

    def _base_max_mana(self, context: ParticipantContext) -> Decimal:
        """Evaluate level-scaled mana needed by Static Field's passive.

        Item mana is deliberately absent because ``ChampionSnapshot`` does not
        expose it and the item policy rejects that unsupported channel.

        :param context: Snapshot supplying the fixed benchmark level.
        :return: Native maximum mana before item contributions.
        """
        stats = self.document["stats"]
        return Decimal(str(stats["mp"])) + Decimal(str(stats["mpperlevel"])) * (
            self.growth_multiplier(context.snapshot.level)
        )

    def _static_field_passive_damage(self, context: ParticipantContext) -> Decimal:
        """Calculate rank-two Static Field mark damage.

        :param context: Snapshot supplying AP and the level-scaled native mana.
        :return: Raw magic damage dealt by one delayed lightning mark.
        """
        return (
            Decimal(100)
            + Decimal("0.40") * context.snapshot.ability_power
            + Decimal("0.02") * self._base_max_mana(context)
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose rank-one Overdrive's initial pursuit multiplier.

        :param context: Role-bound snapshots for the evaluated encounter.
        :return: Locked initial sixty-percent movement-speed multiplier.
        """
        return Decimal("1.60")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Represent a successful Rocket Grab as removable approach distance.

        The shared engagement interface names this quantity a dash even though
        Blitzcrank displaces the opponent. The exact landing point and collision
        result remain blockers on the action plan.

        :param context: Role-bound snapshots for the hook fixture.
        :return: CommunityDragon's 1079-unit displayed Rocket Grab range.
        """
        return Decimal(1079)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject stats that cannot alter Blitzcrank's fixed fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Blitzcrank-scoped blocker, or ``None`` for represented stats.
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
            return f"BLITZCRANK_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _ordinary_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule W-accelerated attacks and pre-active passive marks.

        :param context: Role-bound snapshots supplying attack stats and duration.
        :return: Ordinary attacks plus causally adjacent delayed lightning events.
        """
        boosted_speed = context.snapshot.attack_speed + self._ATTACK_SPEED_RATIO * Decimal("0.30")
        boosted_interval = self._attack_interval_ms(boosted_speed)
        normal_interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 100
        attacks: list[ActionEvent] = []
        zaps: list[ActionEvent] = []
        at_ms = 2300
        while at_ms <= context.duration_ms:
            index = len(attacks) + 1
            attacks.append(
                action(
                    f"BLITZCRANK_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
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
            zap_ms = at_ms + 1000
            if at_ms < self._R_ACTIVE_MS and zap_ms <= self._R_ACTIVE_MS:
                zaps.append(
                    action(
                        f"BLITZCRANK_R_PASSIVE_ZAP_ATTACK_{index}",
                        at_ms=zap_ms,
                        sequence=base + 200 + index,
                        source=context.self_entity,
                        channel=ActionChannel.PASSIVE,
                        outputs=(
                            damage(
                                context.opponent_entity,
                                self._static_field_passive_damage(context),
                                DamageType.MAGIC,
                            ),
                        ),
                    )
                )
            interval = boosted_interval if at_ms < self._W_END_MS else normal_interval
            at_ms += interval
        return (*attacks, *zaps)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the fixed hook, Overdrive, Power Fist, and Static Field sequence.

        :param context: Role-bound Blitzcrank and opponent combat snapshots.
        :return: Deterministic Q5/E5/W1/R2 actions and evidence blockers.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        passive_damage = self._static_field_passive_damage(context)
        fixed_events = (
            action(
                "BLITZCRANK_W_OVERDRIVE_START",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    movement_speed(
                        context.self_entity,
                        context.snapshot.move_speed * Decimal("0.60"),
                        duration_ms=2500,
                    ),
                    StatusOutput(
                        context.self_entity,
                        "BLITZCRANK_W_ATTACK_SPEED",
                        5000,
                        Decimal("0.30"),
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "BLITZCRANK_Q_ROCKET_GRAB_HIT",
                at_ms=400,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(290) + Decimal("1.20") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=500),
                ),
            ),
            action(
                "BLITZCRANK_E_POWER_FIST_ATTACK",
                at_ms=1100,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(2) * context.snapshot.attack_damage + Decimal("0.25") * ap,
                        DamageType.PHYSICAL,
                    ),
                    crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=1000),
                ),
            ),
            action(
                "BLITZCRANK_R_PASSIVE_ZAP_POWER_FIST",
                at_ms=2100,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(damage(context.opponent_entity, passive_damage, DamageType.MAGIC),),
            ),
            action(
                "BLITZCRANK_W_OVERDRIVE_SELF_SLOW",
                at_ms=self._W_END_MS,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(
                    movement_speed(
                        context.self_entity,
                        -context.snapshot.move_speed * Decimal("0.30"),
                        duration_ms=1500,
                    ),
                    crowd_control(
                        context.self_entity,
                        "SLOW",
                        duration_ms=1500,
                        magnitude=Decimal("0.30"),
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "BLITZCRANK_R_STATIC_FIELD_ACTIVE",
                at_ms=self._R_ACTIVE_MS,
                sequence=base + 5,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, Decimal(400) + ap, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "SILENCE", duration_ms=500),
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"BLITZCRANK_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "blitzcrank_q5_e5_w1_r2_hook_fixture_level13_v1",
            tuple(
                sorted(
                    (*fixed_events, *self._ordinary_attacks(context)),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "BLITZCRANK_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "BLITZCRANK_ROTATION_TIMING_UNVERIFIED",
                "BLITZCRANK_Q_DAMAGE_LOCKED_SOURCES_DISAGREE_290_VS_310",
                "BLITZCRANK_Q_PROJECTILE_COLLISION_AND_HIT_NOT_EVALUATED",
                "BLITZCRANK_Q_PULL_DISTANCE_LANDING_POINT_NOT_EVALUATED",
                "BLITZCRANK_Q_CONTROL_DURATION_ASSUMED_500MS",
                "BLITZCRANK_W_MOVEMENT_SPEED_DECAY_APPROXIMATED_INITIAL_WINDOW",
                "BLITZCRANK_W_ATTACK_CADENCE_PHASE_UNVERIFIED",
                "BLITZCRANK_R_PASSIVE_MARK_STACKING_AND_CANCEL_CAUSALITY_UNVERIFIED",
                "BLITZCRANK_R_ACTIVE_SHIELD_DESTRUCTION_NOT_MODELED",
                "BLITZCRANK_MANA_BARRIER_HEALTH_THRESHOLD_NOT_MODELED",
                "BLITZCRANK_ITEM_MANA_NOT_AVAILABLE_TO_PASSIVE_FORMULAS",
                "BLITZCRANK_MULTI_TARGET_EFFECTS_NOT_MODELED",
                "BLITZCRANK_RESOURCE_COSTS_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose hook displacement, Power Fist knock-up, and R silence windows.

        :param context: Role-bound snapshots for the Blitzcrank participant.
        :return: Causal control windows and unresolved defensive semantics.
        """
        return ReactionPlan(
            "blitzcrank_q5_e5_r2_control_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "blitzcrank_q_rocket_grab_pull",
                    400,
                    min(900, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT),
                    "BLITZCRANK_Q_ROCKET_GRAB_HIT",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "blitzcrank_e_power_fist_knockup",
                    1100,
                    min(2100, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT),
                    "BLITZCRANK_E_POWER_FIST_ATTACK",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "blitzcrank_r_static_field_silence",
                    self._R_ACTIVE_MS,
                    min(self._R_ACTIVE_MS + 500, context.duration_ms),
                    (ActionChannel.ABILITY,),
                    "BLITZCRANK_R_STATIC_FIELD_ACTIVE",
                    True,
                    ControlType.SILENCE,
                ),
            ),
            blockers=(
                "BLITZCRANK_Q_PULL_CONTROL_DURATION_UNVERIFIED",
                "BLITZCRANK_Q_DISPLACEMENT_PATH_NOT_MODELED",
                "BLITZCRANK_R_SHIELD_DESTRUCTION_REACTION_NOT_MODELED",
                "BLITZCRANK_MANA_BARRIER_REACTION_NOT_MODELED",
            ),
        )
