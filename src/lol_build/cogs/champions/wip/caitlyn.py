"""Caitlyn combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent


class CaitlynCog(ChampionCog):
    """Model Caitlyn's Q5/W5/E1/R2 level-13 duel fixture."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Caitlyn.json",
        "data/raw/16.17.1/communitydragon/champions/51.json",
        "data/raw/16.17.1/communitydragon/champions/caitlyn.bin.json",
    )

    _CRITICAL_DAMAGE_MULTIPLIER = Decimal(2)
    _R_CHANNEL_START_MS = 6000

    @classmethod
    def _critical_multiplier(cls, context: ParticipantContext) -> Decimal:
        """Calculate expected basic-attack damage from critical-strike chance.

        The locked character record supplies a 2.0 critical-damage multiplier.
        Expected damage keeps the otherwise random roll deterministic.

        :param context: Caitlyn combat context containing critical-strike chance.
        :return: Expected multiplier applied to a basic attack's total AD.
        """
        return Decimal(1) + context.snapshot.critical_strike_chance * (
            cls._CRITICAL_DAMAGE_MULTIPLIER - Decimal(1)
        )

    @classmethod
    def _headshot_bonus(cls, context: ParticipantContext) -> Decimal:
        """Calculate level-13 Headshot bonus damage against a champion.

        At level 13 the locked passive breakpoint contributes 1.0 total AD.
        The same source scales that coefficient with critical chance and the
        character record's critical-damage multiplier.

        :param context: Caitlyn combat context containing offensive stats.
        :return: Physical bonus damage added by a champion Headshot.
        """
        return context.snapshot.attack_damage * cls._critical_multiplier(context)

    @classmethod
    def _attack_event(
        cls,
        context: ParticipantContext,
        *,
        event_id: str,
        at_ms: int,
        sequence: int,
        headshot_bonus: Decimal = Decimal(0),
    ) -> ActionEvent:
        """Create one expected-value attack on the basic-attack channel.

        :param context: Role-bound Caitlyn and opponent snapshots.
        :param event_id: Champion-scoped timeline identifier.
        :param at_ms: Attack timestamp in the eight-second fixture.
        :param sequence: Stable ordering key for equal timestamps.
        :param headshot_bonus: Extra physical damage supplied by Headshot.
        :return: Basic-attack event that remains susceptible to blind.
        """
        amount = (
            context.snapshot.attack_damage * cls._critical_multiplier(context)
            + headshot_bonus
        )
        return action(
            event_id,
            at_ms=at_ms,
            sequence=sequence,
            source=context.self_entity,
            channel=ActionChannel.BASIC_ATTACK,
            outputs=(damage(context.opponent_entity, amount, DamageType.PHYSICAL),),
        )

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats that Caitlyn's fixed fixture cannot consume.

        AD, attack speed, critical chance, AP, defenses, penetration, and movement
        stats reach modeled calculations. The schedule does not yet spend mana,
        scale cooldowns with haste, or attribute sustain to Caitlyn.

        :param item: Normalized item candidate from the locked catalog.
        :return: Caitlyn-specific blocker or ``None`` for represented stat channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "MANA_REGEN",
            "OMNIVAMP",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"CAITLYN_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Keep movement unchanged while the shared model uses Caitlyn's range.

        Net recoil moves away from its target and therefore must not be presented
        as a generic closing dash. Spell reach is retained as an explicit blocker.

        :param context: Role-bound encounter snapshots.
        :return: Neutral pursuit-speed multiplier.
        """
        return Decimal(1)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build an E-W setup, Headshots, Q, attacks, and a late R shot.

        The deterministic fixture assumes E hits and one previously armed trap is
        triggered. These assumptions expose the locked spell formulas without
        claiming that projectile hits or trap activation are guaranteed in play.
        R damage lands late and normal attacks stop at the assumed channel start.

        :param context: Role-bound snapshots for Caitlyn and her opponent.
        :return: Chronological level-13 action schedule with evidence blockers.
        """
        base = self._sequence_base(context)
        events: list[ActionEvent] = []

        if context.duration_ms >= 100:
            events.append(
                action(
                    "CAITLYN_E_90_CALIBER_NET",
                    at_ms=100,
                    sequence=base + 1,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal(80) + Decimal("0.80") * context.snapshot.ability_power,
                            DamageType.MAGIC,
                        ),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=1000,
                            magnitude=Decimal("0.50"),
                        ),
                    ),
                )
            )
        if context.duration_ms >= 400:
            events.append(
                self._attack_event(
                    context,
                    event_id="CAITLYN_E_EMPOWERED_HEADSHOT",
                    at_ms=400,
                    sequence=base + 2,
                    headshot_bonus=self._headshot_bonus(context),
                )
            )
        if context.duration_ms >= 1000:
            events.append(
                action(
                    "CAITLYN_Q_PILTOVER_PEACEMAKER",
                    at_ms=1000,
                    sequence=base + 3,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal(210)
                            + Decimal("2.05") * context.snapshot.attack_damage,
                            DamageType.PHYSICAL,
                        ),
                    ),
                )
            )
        if context.duration_ms >= 2500:
            events.append(
                action(
                    "CAITLYN_W_ASSUMED_TRAP_TRIGGER",
                    at_ms=2500,
                    sequence=base + 4,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(
                        crowd_control(
                            context.opponent_entity,
                            "ROOT",
                            duration_ms=1500,
                        ),
                    ),
                )
            )
        if context.duration_ms >= 2750:
            trap_bonus = (
                self._headshot_bonus(context)
                + Decimal(215)
                + Decimal("0.30") * context.snapshot.bonus_attack_damage
            )
            events.append(
                self._attack_event(
                    context,
                    event_id="CAITLYN_W_EMPOWERED_HEADSHOT",
                    at_ms=2750,
                    sequence=base + 5,
                    headshot_bonus=trap_bonus,
                )
            )

        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        attack_ms = 1500
        attack_index = 1
        while attack_ms < min(context.duration_ms + 1, self._R_CHANNEL_START_MS):
            normal_headshot = attack_index % 5 == 0
            events.append(
                self._attack_event(
                    context,
                    event_id=(
                        f"CAITLYN_PASSIVE_HEADSHOT_{attack_index}"
                        if normal_headshot
                        else f"CAITLYN_ATTACK_{attack_index}"
                    ),
                    at_ms=attack_ms,
                    sequence=base + 100 + attack_index,
                    headshot_bonus=(
                        self._headshot_bonus(context)
                        if normal_headshot
                        else Decimal(0)
                    ),
                )
            )
            attack_index += 1
            attack_ms += interval_ms

        if context.duration_ms >= 7600:
            critical_scale = Decimal(1) + Decimal("0.30") * (
                context.snapshot.critical_strike_chance
                * (self._CRITICAL_DAMAGE_MULTIPLIER - Decimal(1))
            )
            events.append(
                action(
                    "CAITLYN_R_ACE_IN_THE_HOLE",
                    at_ms=7600,
                    sequence=base + 300,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            (Decimal(475) + context.snapshot.bonus_attack_damage)
                            * critical_scale,
                            DamageType.PHYSICAL,
                        ),
                    ),
                )
            )

        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"CAITLYN_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "caitlyn_q5_w5_e1_r2_level13_locked_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "CAITLYN_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "CAITLYN_ROTATION_AND_ANIMATION_TIMING_UNVERIFIED",
                "CAITLYN_PROJECTILE_HIT_AND_RANGE_CONTINUITY_ASSUMED",
                "CAITLYN_E_HIT_AND_RECOIL_POSITION_NOT_CAUSALLY_MODELED",
                "CAITLYN_E_HEADSHOT_WINDOW_CONSUMPTION_ASSUMED",
                "CAITLYN_W_PREARMED_TRAP_TRIGGER_ASSUMED",
                "CAITLYN_W_PLACEMENT_TRIGGER_CAUSALITY_NOT_MODELED",
                "CAITLYN_W_HEADSHOT_WINDOW_CONSUMPTION_ASSUMED",
                "CAITLYN_PASSIVE_INITIAL_STACK_COUNT_ASSUMED_ZERO",
                "CAITLYN_PASSIVE_ATTACK_COUNT_TRIGGER_PHASE_UNVERIFIED",
                "CAITLYN_CRITICAL_ATTACKS_USE_EXPECTED_VALUE",
                "CAITLYN_R_CHANNEL_INTERRUPTION_NOT_CAUSALLY_MODELED",
                "CAITLYN_R_PROJECTILE_INTERCEPTION_AND_TRAVEL_UNVERIFIED",
                "CAITLYN_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose trap root and net slow semantics to the shared engine.

        Root prevents movement without preventing attacks or ordinary spell casts.
        Slow remains a status because pursuit-speed integration is not causal yet.

        :param context: Role-bound snapshots for Caitlyn and her opponent.
        :return: Trap movement block plus unresolved positional blockers.
        """
        windows = (
            (
                CastBlockWindow(
                    "caitlyn_w_assumed_trap_root",
                    2500,
                    min(4000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "CAITLYN_W_ASSUMED_TRAP_TRIGGER",
                    True,
                    ControlType.ROOT,
                ),
            )
            if context.duration_ms > 2500
            else ()
        )
        return ReactionPlan(
            "caitlyn_w_root_e_slow_reaction_v1",
            cast_block_windows=windows,
            blockers=(
                "CAITLYN_W_PREARMED_TRAP_TRIGGER_ASSUMED",
                "CAITLYN_E_SLOW_AND_RECOIL_POSITION_NOT_INTEGRATED",
            ),
        )
