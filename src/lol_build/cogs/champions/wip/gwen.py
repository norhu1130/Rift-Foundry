"""Gwen combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.core.combat import DamageType, resistance_multiplier
from lol_build.core.timeline import ActionChannel, ActionEvent, DamageModifierWindow, StatusOutput


class GwenCog(ChampionCog):
    """Model Gwen's P/Q5/W1/E5/R2 level-13 duel fixture.

    The deterministic policy opens with Skip 'n Slash, casts all three
    Needlework volleys at their locked one-second lockout, and spends four
    attack stacks on one six-snip Q sweet spot. Hallowed Mist assumes the duel
    opponent remains inside the zone; its bonus resistances are represented,
    while outside-zone untargetability remains an explicit blocker.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Gwen.json",
        "data/raw/16.17.1/communitydragon/champions/887.json",
        "data/raw/16.17.1/communitydragon/champions/gwen.bin.json",
    )

    _ATTACK_SPEED_RATIO = Decimal("0.69")
    _E5_ATTACK_SPEED_BONUS = Decimal("0.80")
    _E_BUFF_END_MS = 4000
    _W_START_MS = 100
    _W_END_MS = 4100
    _R_CAST_TIMES = (250, 1250, 2250)
    _R_NEEDLES = (1, 3, 5)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Skip 'n Slash's locked directional dash distance.

        :param context: Role-bound snapshots for the current encounter.
        :return: Rank-independent dash distance in game units.
        """
        return Decimal(350)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Gwen's fixed duel model.

        AP, AD, attack speed, health, defenses, penetration, movement, and
        tenacity reach modeled formulas or shared combat channels. The fixed
        single-cast policy cannot value haste, resources, crits, or item sustain.

        :param item: Normalized candidate from the locked item catalog.
        :return: Gwen-scoped blocker, or ``None`` for represented channels.
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
            return f"GWEN_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    @staticmethod
    def _passive_damage(context: ParticipantContext) -> Decimal:
        """Calculate one A Thousand Cuts proc against a champion.

        :param context: Snapshot supplying Gwen AP and opponent maximum health.
        :return: Raw magic damage for one passive application.
        """
        ratio = Decimal("0.01") + Decimal("0.00006") * context.snapshot.ability_power
        return context.opponent_snapshot.max_hp * ratio

    def _passive_outputs(self, context: ParticipantContext, *, applications: int) -> tuple:
        """Build aggregated passive damage and its locked healing fraction.

        :param context: Role-bound snapshots identifying damage and heal recipients.
        :param applications: Positive number of passive applications to aggregate.
        :return: Magic damage and self-healing outputs for the applications.
        """
        passive_damage = self._passive_damage(context) * Decimal(applications)
        return (
            damage(
                context.opponent_entity,
                passive_damage,
                DamageType.MAGIC,
                source_heal_ratio=Decimal("0.67"),
            ),
        )

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule E-empowered and ordinary passive-bearing attacks.

        :param context: Snapshot supplying attack damage, AP, speed, and duration.
        :return: Deterministic basic attacks through the benchmark duration.
        """
        empowered_speed = (
            context.snapshot.attack_speed + self._ATTACK_SPEED_RATIO * self._E5_ATTACK_SPEED_BONUS
        )
        empowered_interval = self._attack_interval_ms(empowered_speed)
        normal_interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 400
        while at_ms <= min(self._E_BUFF_END_MS, context.duration_ms):
            events.append(
                action(
                    f"GWEN_E_EMPOWERED_ATTACK_{len(events) + 1}",
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
                        damage(
                            context.opponent_entity,
                            Decimal(15) + Decimal("0.20") * context.snapshot.ability_power,
                            DamageType.MAGIC,
                        ),
                        *self._passive_outputs(context, applications=1),
                    ),
                )
            )
            at_ms += empowered_interval

        at_ms = max(self._E_BUFF_END_MS + 1, at_ms)
        ordinary_index = 1
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"GWEN_BASIC_ATTACK_{ordinary_index}",
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
                        *self._passive_outputs(context, applications=1),
                    ),
                )
            )
            ordinary_index += 1
            at_ms += normal_interval
        return tuple(events)

    def _q_event(
        self, context: ParticipantContext, attacks: tuple[ActionEvent, ...]
    ) -> ActionEvent:
        """Build one max-stack center-hit Snip Snip cast.

        :param context: Snapshot supplying Gwen AP and role-bound recipients.
        :param attacks: Scheduled attacks used to anchor the fourth stack.
        :return: Six-snip mixed-damage Q event with six passive applications.
        """
        fourth_attack_ms = attacks[min(3, len(attacks) - 1)].at_ms
        q_at_ms = min(context.duration_ms, fourth_attack_ms + 200)
        spell_damage = (
            Decimal(5) * (Decimal(26) + Decimal("0.05") * context.snapshot.ability_power)
            + Decimal(160)
            + Decimal("0.35") * context.snapshot.ability_power
        )
        return action(
            "GWEN_Q_SNIP_SNIP_MAX_CENTER",
            at_ms=q_at_ms,
            sequence=self._sequence_base(context) + 10,
            source=context.self_entity,
            channel=ActionChannel.ABILITY,
            outputs=(
                damage(context.opponent_entity, spell_damage / 2, DamageType.MAGIC),
                damage(context.opponent_entity, spell_damage / 2, DamageType.TRUE),
                *self._passive_outputs(context, applications=6),
            ),
        )

    def _needlework_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build Needlework's locked one-, three-, and five-needle casts.

        :param context: Snapshot supplying Gwen AP and opponent maximum health.
        :return: In-horizon R2 volley events with passive applications and slows.
        """
        per_needle = Decimal(50) + Decimal("0.10") * context.snapshot.ability_power
        base = self._sequence_base(context) + 20
        events: list[ActionEvent] = []
        for index, (at_ms, needles) in enumerate(
            zip(self._R_CAST_TIMES, self._R_NEEDLES, strict=True)
        ):
            if at_ms > context.duration_ms:
                continue
            slow = Decimal("0.50") if index == 0 else Decimal("0.20")
            events.append(
                action(
                    f"GWEN_R_NEEDLEWORK_{index + 1}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            per_needle * Decimal(needles),
                            DamageType.MAGIC,
                        ),
                        *self._passive_outputs(context, applications=needles),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=1500,
                            magnitude=slow,
                        ),
                    ),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Gwen's locked P/Q5/W1/E5/R2 level-13 duel sequence.

        :param context: Role-bound snapshots for Gwen and the opponent.
        :return: Dash, mist, attacks, snips, needles, sustain, and blockers.
        """
        base = self._sequence_base(context)
        attacks = self._attack_events(context)
        fixed_events = (
            action(
                "GWEN_E_SKIP_N_SLASH",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "GWEN_E_EMPOWERED", 4000),),
                requires_living_opponent=False,
            ),
            action(
                "GWEN_W_HALLOWED_MIST",
                at_ms=self._W_START_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "GWEN_W_INSIDE_MIST", 4000),),
                requires_living_opponent=False,
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"GWEN_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        events = (
            *fixed_events,
            *self._needlework_events(context),
            *attacks,
            self._q_event(context, attacks),
        )
        return ActionPlan(
            "gwen_p_q5_w1_e5_r2_level13_locked_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "GWEN_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "GWEN_CAST_HIT_AND_ATTACK_TIMING_UNVERIFIED",
                "GWEN_Q_FOUR_STACKS_AND_CENTER_HIT_ASSUMED",
                "GWEN_Q_INDIVIDUAL_SNIP_TIMING_NOT_MODELED",
                "GWEN_W_OPPONENT_INSIDE_MIST_ASSUMED",
                "GWEN_W_OUTSIDE_SOURCE_UNTARGETABILITY_NOT_MODELED",
                "GWEN_E_FIRST_HIT_COOLDOWN_REFUND_NOT_VALUED",
                "GWEN_R_PROJECTILE_COLLISION_AND_MULTI_TARGETS_NOT_MODELED",
                "GWEN_PASSIVE_CURRENT_HEALTH_EXECUTE_NOT_MODELED",
                "GWEN_RESOURCE_COSTS_NOT_EVALUATED",
            ),
        )

    @staticmethod
    def _mist_resistance_multiplier(resistance: Decimal, bonus: Decimal) -> Decimal:
        """Convert temporary bonus resistance to a post-mitigation scalar.

        :param resistance: Gwen's baseline armor or magic resistance.
        :param bonus: Hallowed Mist's temporary resistance bonus.
        :return: Relative incoming-damage multiplier during the mist window.
        """
        return resistance_multiplier(resistance + bonus) / resistance_multiplier(resistance)

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Hallowed Mist resistances and Needlework slows.

        :param context: Role-bound snapshots for the Gwen participant.
        :return: Incoming-damage modifiers and opponent movement blocks.
        """
        mist_end = min(self._W_END_MS, context.duration_ms)
        mist_bonus = Decimal(22) + Decimal("0.07") * context.snapshot.ability_power
        damage_windows: tuple[DamageModifierWindow, ...] = ()
        if mist_end > self._W_START_MS:
            damage_windows = (
                DamageModifierWindow(
                    "gwen_w_hallowed_mist_armor",
                    self._W_START_MS,
                    mist_end,
                    context.self_entity,
                    (DamageType.PHYSICAL,),
                    self._mist_resistance_multiplier(context.snapshot.armor, mist_bonus),
                ),
                DamageModifierWindow(
                    "gwen_w_hallowed_mist_magic_resistance",
                    self._W_START_MS,
                    mist_end,
                    context.self_entity,
                    (DamageType.MAGIC,),
                    self._mist_resistance_multiplier(context.snapshot.magic_resistance, mist_bonus),
                ),
            )
        slow_windows = tuple(
            CastBlockWindow(
                f"gwen_r_needlework_{index + 1}_slow",
                at_ms,
                min(at_ms + 1500, context.duration_ms),
                (ActionChannel.MOVEMENT,),
                f"GWEN_R_NEEDLEWORK_{index + 1}",
                True,
                ControlType.SLOW,
            )
            for index, at_ms in enumerate(self._R_CAST_TIMES)
            if at_ms < context.duration_ms
        )
        return ReactionPlan(
            "gwen_w1_r2_reaction_v1",
            damage_windows=damage_windows,
            cast_block_windows=slow_windows,
            blockers=(
                "GWEN_W_OPPONENT_INSIDE_MIST_ASSUMED",
                "GWEN_W_OUTSIDE_SOURCE_UNTARGETABILITY_NOT_MODELED",
                "GWEN_W_RESISTANCE_PENETRATION_ORDER_APPROXIMATED",
                "GWEN_R_SLOW_AND_HIT_TIMING_UNVERIFIED",
            ),
        )
