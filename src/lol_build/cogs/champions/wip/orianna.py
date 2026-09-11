"""Orianna combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.core.combat import (
    DamageType,
    ResistanceModifiers,
    apply_resistance_pipeline,
    resistance_multiplier,
)
from lol_build.core.timeline import ActionChannel, ActionEvent, DamageModifierWindow


class OriannaCog(ChampionCog):
    """Model Orianna's Q5/W5/E1/R2 level-13 single-target sequence.

    The ball starts attached to Orianna, moves through the opponent with Q,
    supplies W and R there, then returns through the opponent with E. A second
    W after its cooldown samples self movement speed while the ball is attached.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Orianna.json",
        "data/raw/16.17.1/communitydragon/champions/61.json",
        "data/raw/16.17.1/communitydragon/champions/orianna.bin.json",
    )
    _Q_AT_MS = 100
    _W_TARGET_AT_MS = 450
    _R_AT_MS = 800
    _E_AT_MS = 1400
    _W_SELF_AT_MS = 7450

    @staticmethod
    def _passive_base_damage(level: int, ability_power: Decimal) -> Decimal:
        """Evaluate Clockwork Windup's locked level interpolation and AP ratio.

        :param level: Champion level selecting the level-one to eighteen curve.
        :param ability_power: Aggregated ability power for the on-hit formula.
        :return: Raw magic damage before consecutive-target multipliers.
        """
        bounded_level = min(18, max(1, level))
        level_damage = Decimal(10) + (Decimal(40) * Decimal(bounded_level - 1) / Decimal(17))
        return level_damage + Decimal("0.15") * ability_power

    @staticmethod
    def _resistance_grant_multiplier(
        resistance: Decimal,
        *,
        bonus: Decimal,
        percent_penetration: Decimal,
        flat_penetration: Decimal,
    ) -> Decimal:
        """Convert E's attached-ball resistance grant into damage reduction.

        :param resistance: Permanent resistance on Orianna's snapshot.
        :param bonus: Flat resistance supplied by the attached ball.
        :param percent_penetration: Opponent penetration fraction for the channel.
        :param flat_penetration: Opponent flat penetration for the channel.
        :return: Ratio of post-grant to pre-grant incoming damage multipliers.
        """
        modifiers = ResistanceModifiers(
            percent_penetration=percent_penetration,
            flat_penetration=flat_penetration,
        )
        before = apply_resistance_pipeline(resistance, modifiers).effective_resistance
        after = apply_resistance_pipeline(resistance + bonus, modifiers).effective_resistance
        return resistance_multiplier(after) / resistance_multiplier(before)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose rank-five W's attached-ball pursuit option.

        :param context: Role-bound Orianna combat context.
        :return: Locked forty-percent initial movement-speed multiplier.
        """
        return Decimal("1.40")

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Orianna's fixed event policy.

        :param item: Normalized candidate from the locked item catalog.
        :return: Orianna-scoped blocker for unsupported stats, otherwise ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"ORIANNA_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks with Clockwork Windup consecutive-target stacks.

        :param context: Role-bound snapshots supplying attack cadence and damage.
        :return: Physical attacks paired with passive magic damage.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        passive_base = self._passive_base_damage(
            context.snapshot.level, context.snapshot.ability_power
        )
        sequence = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 1750
        while at_ms <= context.duration_ms:
            stacks = min(len(events), 2)
            passive_amount = passive_base * (Decimal(1) + Decimal("0.15") * stacks)
            events.append(
                action(
                    f"ORIANNA_BASIC_ATTACK_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=sequence + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            context.snapshot.attack_damage,
                            DamageType.PHYSICAL,
                        ),
                        damage(
                            context.opponent_entity,
                            passive_amount,
                            DamageType.MAGIC,
                        ),
                    ),
                )
            )
            at_ms += interval_ms
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the fixed ball-position spell and passive-attack schedule.

        :param context: Role-bound Orianna and opponent combat snapshots.
        :return: Deterministic Q/W/E/R, shielding, movement, and attack events.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        fixed_events = (
            action(
                "ORIANNA_Q_COMMAND_ATTACK_TARGET_FIXTURE",
                at_ms=self._Q_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(180) + Decimal("0.55") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "ORIANNA_W_COMMAND_DISSONANCE_TARGET",
                at_ms=self._W_TARGET_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(230) + Decimal("0.80") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity, "SLOW", duration_ms=2000, magnitude=Decimal("0.40")
                    ),
                ),
            ),
            action(
                "ORIANNA_R_COMMAND_SHOCKWAVE",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(350) + Decimal("1.10") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=750),
                ),
            ),
            action(
                "ORIANNA_E_COMMAND_PROTECT_RETURN_SELF",
                at_ms=self._E_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(60) + Decimal("0.30") * ap,
                        DamageType.MAGIC,
                    ),
                    shielding(
                        context.self_entity, Decimal(55) + Decimal("0.45") * ap, duration_ms=2500
                    ),
                ),
            ),
            action(
                "ORIANNA_W_COMMAND_DISSONANCE_SELF_HASTE",
                at_ms=self._W_SELF_AT_MS,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    movement_speed(
                        context.self_entity,
                        context.snapshot.move_speed * Decimal("0.40"),
                        duration_ms=2000,
                    ),
                ),
                requires_living_opponent=False,
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"ORIANNA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "orianna_q5_w5_e1_r2_ball_fixture_v1",
            tuple(
                sorted(
                    (*fixed_events, *self._basic_attacks(context)),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "ORIANNA_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "ORIANNA_BALL_STARTS_ATTACHED_SELF_FIXTURE",
                "ORIANNA_BALL_POSITION_AND_TRAVEL_CAUSALITY_NOT_MODELED",
                "ORIANNA_Q_PROJECTILE_HIT_AND_TRAVEL_TIME_UNVERIFIED",
                "ORIANNA_W_FIELD_REAPPLICATION_NOT_MODELED",
                "ORIANNA_W_MOVEMENT_SPEED_DECAY_NOT_MODELED",
                "ORIANNA_R_DISPLACEMENT_DISTANCE_AND_DIRECTION_NOT_MODELED",
                "ORIANNA_E_RETURN_PATH_HIT_ASSUMED",
                "ORIANNA_MULTI_TARGET_EFFECTS_NOT_MODELED",
                "ORIANNA_PASSIVE_STACK_ADVANCE_AFTER_CANCEL_NOT_MODELED",
                "ORIANNA_CAST_AND_ATTACK_TIMING_UNVERIFIED",
                "ORIANNA_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose W/R control and attached-ball E defenses.

        :param context: Role-bound snapshots for Orianna and the opponent.
        :return: Control and incoming-damage windows tied to the fixed fixture.
        """
        damage_windows = ()
        if context.duration_ms > self._E_AT_MS:
            damage_windows = (
                DamageModifierWindow(
                    "orianna_e_attached_ball_armor",
                    self._E_AT_MS,
                    context.duration_ms,
                    context.self_entity,
                    (DamageType.PHYSICAL,),
                    self._resistance_grant_multiplier(
                        context.snapshot.armor,
                        bonus=Decimal(6),
                        percent_penetration=context.opponent_snapshot.percent_armor_penetration,
                        flat_penetration=context.opponent_snapshot.flat_armor_penetration,
                    ),
                ),
                DamageModifierWindow(
                    "orianna_e_attached_ball_magic_resistance",
                    self._E_AT_MS,
                    context.duration_ms,
                    context.self_entity,
                    (DamageType.MAGIC,),
                    self._resistance_grant_multiplier(
                        context.snapshot.magic_resistance,
                        bonus=Decimal(6),
                        percent_penetration=context.opponent_snapshot.percent_magic_penetration,
                        flat_penetration=context.opponent_snapshot.flat_magic_penetration,
                    ),
                ),
            )
        return ReactionPlan(
            "orianna_w5_e1_r2_ball_fixture_reaction_v1",
            damage_windows=damage_windows,
            cast_block_windows=(
                CastBlockWindow(
                    "orianna_w_target_slow",
                    self._W_TARGET_AT_MS,
                    min(self._W_TARGET_AT_MS + 2000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "ORIANNA_W_COMMAND_DISSONANCE_TARGET",
                    True,
                    ControlType.SLOW,
                ),
                CastBlockWindow(
                    "orianna_r_shockwave_displacement",
                    self._R_AT_MS,
                    min(self._R_AT_MS + 750, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT),
                    "ORIANNA_R_COMMAND_SHOCKWAVE",
                    False,
                    ControlType.AIRBORNE,
                ),
            ),
            blockers=(
                "ORIANNA_W_FIELD_CONTACT_REFRESH_NOT_MODELED",
                "ORIANNA_R_DISPLACEMENT_TIMING_UNVERIFIED",
                "ORIANNA_E_RESISTANCE_ATTACHMENT_WINDOW_UNVERIFIED",
                "ORIANNA_BALL_POSITION_FIXTURE_UNVERIFIED",
            ),
        )
