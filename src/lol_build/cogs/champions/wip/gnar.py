"""Gnar combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatModifierOutput, StatusOutput


class GnarCog(ChampionCog):
    """Model a deterministic Mini-to-Mega Gnar level-13 duel fixture.

    The fixture uses Q5/W5/E1/R2. Gnar begins in Mini form, attacks and casts
    through three seconds, then transforms and uses Mega Q, W, and R. The
    transformation time is a synthetic benchmark policy, not a prediction of
    rage generation from the opposing champion.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Gnar.json",
        "data/raw/16.17.1/communitydragon/champions/150.json",
        "data/raw/16.17.1/communitydragon/champions/gnar.bin.json",
    )
    _TRANSFORM_MS = 3000
    _MEGA_DURATION_MS = 5000

    @staticmethod
    def _mega_bonus(context: ParticipantContext, base: str, per_growth: str) -> Decimal:
        """Evaluate a locked Mega Gnar level interpolation.

        :param context: Snapshot supplying the benchmark champion level.
        :param base: Level-one form bonus encoded as decimal text.
        :param per_growth: Bonus per nonlinear growth unit encoded as decimal text.
        :return: Mega-form stat bonus at the requested level.
        """
        return Decimal(base) + Decimal(per_growth) * ChampionCog.growth_multiplier(
            context.snapshot.level
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Mini Hop's conservative locked cast distance.

        :param context: Role-bound snapshots for the evaluated encounter.
        :return: Mini Hop's first-leg distance in game units.
        """
        return Decimal(475)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels not consumed by the fixed Gnar schedule.

        :param item: Normalized candidate from the locked item catalog.
        :return: Gnar-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "MANA_REGEN",
            "OMNIVAMP",
        } & stats.keys()
        if unsupported:
            return f"GNAR_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def _mini_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build Mini Q, E, attacks, and deterministic Hyper procs.

        :param context: Role-bound snapshots supplying damage and attack cadence.
        :return: Chronological Mini-form events before the fixed transformation.
        """
        base = self._sequence_base(context) + 100
        shapes: list[tuple[int, str, ActionChannel, Decimal, DamageType]] = [
            (
                200,
                "GNAR_MINI_Q_BOOMERANG",
                ActionChannel.ABILITY,
                Decimal(165) + Decimal("1.25") * context.snapshot.attack_damage,
                DamageType.PHYSICAL,
            ),
            (
                1800,
                "GNAR_MINI_E_HOP",
                ActionChannel.ABILITY,
                Decimal(50) + Decimal("0.06") * context.snapshot.max_hp,
                DamageType.PHYSICAL,
            ),
        ]
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        at_ms = 500
        attack_index = 1
        while at_ms < self._TRANSFORM_MS:
            shapes.append(
                (
                    at_ms,
                    f"GNAR_MINI_ATTACK_{attack_index}",
                    ActionChannel.BASIC_ATTACK,
                    context.snapshot.attack_damage,
                    DamageType.PHYSICAL,
                )
            )
            attack_index += 1
            at_ms += interval_ms

        events: list[ActionEvent] = []
        for hit_index, shape in enumerate(sorted(shapes), start=1):
            at_ms, event_id, channel, amount, damage_type = shape
            outputs = [damage(context.opponent_entity, amount, damage_type)]
            if event_id == "GNAR_MINI_Q_BOOMERANG":
                outputs.append(
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=2000,
                        magnitude=Decimal("0.35"),
                    )
                )
            elif event_id == "GNAR_MINI_E_HOP":
                outputs.extend(
                    (
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=500,
                            magnitude=Decimal("0.80"),
                        ),
                        StatusOutput(
                            context.self_entity,
                            "GNAR_MINI_E_ATTACK_SPEED",
                            6000,
                            Decimal("0.40"),
                        ),
                    )
                )
            if hit_index % 3 == 0:
                outputs.append(
                    damage(
                        context.opponent_entity,
                        Decimal(40)
                        + context.snapshot.ability_power
                        + Decimal("0.14") * context.opponent_snapshot.max_hp,
                        DamageType.MAGIC,
                    )
                )
            events.append(
                action(
                    event_id,
                    at_ms=at_ms,
                    sequence=base + hit_index,
                    source=context.self_entity,
                    channel=channel,
                    outputs=tuple(outputs),
                )
            )
        return tuple(events)

    def _mega_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build transformation plus Mega E, Q, W, R, and basic attacks.

        :param context: Role-bound snapshots supplying form-scaled damage values.
        :return: Deterministic Mega-form events for the remainder of the duel.
        """
        base = self._sequence_base(context) + 300
        mega_ad = context.snapshot.attack_damage + self._mega_bonus(context, "6", "2.5")
        mega_hp = context.snapshot.max_hp + self._mega_bonus(context, "100", "43")
        transform = action(
            "GNAR_TRANSFORM_TO_MEGA",
            at_ms=self._TRANSFORM_MS,
            sequence=base,
            source=context.self_entity,
            channel=ActionChannel.PASSIVE,
            outputs=(StatusOutput(context.self_entity, "GNAR_FORM_MEGA", self._MEGA_DURATION_MS),),
            requires_living_opponent=False,
        )
        specifications = (
            (3100, "GNAR_MEGA_E_CRUNCH", Decimal(80) + Decimal("0.06") * mega_hp, None),
            (
                3500,
                "GNAR_MEGA_Q_BOULDER",
                Decimal(225) + Decimal("1.40") * mega_ad,
                ("SLOW", 2000, Decimal("0.50")),
            ),
            (
                4100,
                "GNAR_MEGA_W_WALLOP",
                Decimal(165) + mega_ad,
                ("STUN", 1250, Decimal(1)),
            ),
            (
                5400,
                "GNAR_MEGA_R_GNAR",
                Decimal(300)
                + context.snapshot.ability_power
                + Decimal("0.50") * context.snapshot.bonus_attack_damage,
                ("SLOW", 1500, Decimal("0.45")),
            ),
        )
        events = [transform]
        for index, (at_ms, event_id, amount, control) in enumerate(specifications, start=1):
            outputs = [damage(context.opponent_entity, amount, DamageType.PHYSICAL)]
            if control is not None:
                control_type, duration_ms, magnitude = control
                outputs.append(
                    crowd_control(
                        context.opponent_entity,
                        control_type,
                        duration_ms=duration_ms,
                        magnitude=magnitude,
                    )
                )
            events.append(
                action(
                    event_id,
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=tuple(outputs),
                )
            )
        for index, at_ms in enumerate((4800, 6500, 7900), start=1):
            events.append(
                action(
                    f"GNAR_MEGA_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 20 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(damage(context.opponent_entity, mega_ad, DamageType.PHYSICAL),),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked Q5/W5/E1/R2 Mini-to-Mega rotation.

        :param context: Role-bound Gnar and opponent snapshots.
        :return: Deterministic two-form actions and honest model blockers.
        """
        base = self._sequence_base(context)
        mini_form = action(
            "GNAR_START_MINI_FORM",
            at_ms=0,
            sequence=base,
            source=context.self_entity,
            channel=ActionChannel.PASSIVE,
            outputs=(StatusOutput(context.self_entity, "GNAR_FORM_MINI", self._TRANSFORM_MS),),
            requires_living_opponent=False,
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"GNAR_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "gnar_q5_w5_e1_r2_mini_to_mega_level13_synthetic_v1",
            tuple(
                sorted(
                    (mini_form, *self._mini_events(context), *self._mega_events(context)),
                    key=lambda event: (event.at_ms, event.sequence),
                )
            ),
            (
                *level_blockers,
                "GNAR_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "GNAR_TRANSFORM_AT_3000MS_SYNTHETIC",
                "GNAR_RAGE_GENERATION_AND_TIRED_STATE_NOT_EVALUATED",
                "GNAR_TRANSFORM_MAX_HP_CURRENT_HP_SEMANTICS_NOT_EVALUATED",
                "GNAR_Q_PICKUP_COOLDOWN_REFUND_NOT_EVALUATED",
                "GNAR_E_BOUNCE_GEOMETRY_NOT_EVALUATED",
                "GNAR_E_ATTACK_SPEED_STATUS_NOT_CAUSALLY_RESCHEDULING_ATTACKS",
                "GNAR_MEGA_E_SLOW_NOT_EVALUATED",
                "GNAR_HYPER_CONDITIONAL_MOVE_SPEED_NOT_EVALUATED",
                "GNAR_HYPER_STACKS_NOT_CAUSALLY_RECOUNTED_AFTER_CANCELLED_HITS",
                "GNAR_R_WALL_COLLISION_BONUS_AND_STUN_NOT_EVALUATED",
                "GNAR_MEGA_BASIC_ATTACK_CADENCE_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Apply Mega-form resistances and Wallop's reducible stun window.

        :param context: Role-bound Gnar encounter context.
        :return: Form defense events and causally linked control reactions.
        """
        base = self._sequence_base(context) + 900
        transform_resists = action(
            "GNAR_MEGA_FORM_RESISTANCES",
            at_ms=self._TRANSFORM_MS,
            sequence=base,
            source=context.self_entity,
            channel=ActionChannel.PASSIVE,
            outputs=(
                StatModifierOutput(
                    context.self_entity,
                    "ARMOR",
                    self._mega_bonus(context, "3.5", "3"),
                    self._MEGA_DURATION_MS,
                ),
                StatModifierOutput(
                    context.self_entity,
                    "MAGIC_RESISTANCE",
                    self._mega_bonus(context, "3.5", "3.5"),
                    self._MEGA_DURATION_MS,
                ),
            ),
            requires_living_opponent=False,
        )
        return ReactionPlan(
            "gnar_mega_resists_and_wallop_reaction_v1",
            events=(transform_resists,),
            cast_block_windows=(
                CastBlockWindow(
                    "gnar_mega_w_stun",
                    4100,
                    min(5350, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY),
                    "GNAR_MEGA_W_WALLOP",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(
                "GNAR_MEGA_RESIST_DURATION_TIED_TO_SYNTHETIC_TRANSFORM",
                "GNAR_R_KNOCKBACK_DURATION_NOT_EVALUATED",
                "GNAR_R_WALL_STUN_CONDITIONAL_GEOMETRY_NOT_EVALUATED",
            ),
        )
