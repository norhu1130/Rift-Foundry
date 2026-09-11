"""Cho'Gath combat Cog backed by the locked 16.17.1 sources."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    CastBlockWindow,
    ChampionCog,
    ChampionSnapshot,
    CogMaturity,
    ControlType,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class ChogathCog(ChampionCog):
    """Model Cho'Gath's Q5/W1/E5/R2 level-13 duel fixture.

    The fixture starts with six Feast stacks, the documented cap obtainable
    from ordinary minions and non-epic monsters. Those stacks grant rank-two
    maximum health and increase Vorpal Spikes damage. The model never awards a
    new stack during combat because executing the target is live-health state.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Chogath.json",
        "data/raw/16.17.1/communitydragon/champions/31.json",
        "data/raw/16.17.1/communitydragon/champions/chogath.bin.json",
    )

    feast_stack_fixture = 6
    _R2_HEALTH_PER_STACK = Decimal(120)
    _E5_BASE_MAX_HEALTH_RATIO = Decimal("0.039")
    _E_FEAST_STACK_RATIO = Decimal("0.005")

    @staticmethod
    def _haste_adjusted_ms(base_ms: int, ability_haste: Decimal) -> int:
        """Apply ability haste to one locked base cooldown.

        :param base_ms: Cooldown before ability haste, in milliseconds.
        :param ability_haste: Non-negative haste from the combat snapshot.
        :return: Deterministically rounded cooldown with a one-ms floor.
        """
        adjusted = Decimal(base_ms) * Decimal(100) / (Decimal(100) + ability_haste)
        return max(1, int(adjusted.to_integral_value()))

    def snapshot(
        self,
        *,
        level: int,
        item_stats: dict[str, Decimal] | None = None,
    ) -> ChampionSnapshot:
        """Build a snapshot including the fixed six-stack Feast fixture.

        Feast health is bonus health, so it also reaches the ultimate's
        bonus-health ratio. Dynamic stack acquisition remains outside scope.

        :param level: Champion level used by the shared stat-growth model.
        :param item_stats: Optional normalized permanent item modifiers.
        :return: Combat snapshot with the fixed Feast health applied.
        """
        base = super().snapshot(level=level, item_stats=item_stats)
        feast_health = self._R2_HEALTH_PER_STACK * self.feast_stack_fixture
        return replace(
            base,
            max_hp=base.max_hp + feast_health,
            bonus_health=base.bonus_health + feast_health,
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Keep Cho'Gath's self movement speed unchanged.

        :param context: Role-bound Cho'Gath encounter context.
        :return: Neutral movement-speed multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose successful Rupture reach as deterministic approach control.

        This mirrors the shared hook-style engagement convention: Cho'Gath
        does not dash, but a hit at the locked 950-unit cast range lets him
        close while the target is knocked up and slowed.

        :param context: Role-bound Cho'Gath encounter context.
        :return: Locked Rupture range in game units.
        """
        return Decimal(950)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the fixed Cho'Gath fixture.

        AP, attack speed, haste, health, defenses, penetration, movement, AD,
        and tenacity reach represented calculations or shared engine channels.

        :param item: Normalized candidate from the locked item catalog.
        :return: Cho'Gath-scoped blocker, or ``None`` when represented.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "MANA_REGEN",
            "OMNIVAMP",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"CHOGATH_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _rupture_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule successful rank-five Rupture hits through the horizon.

        :param context: Snapshot supplying AP, haste, roles, and duration.
        :return: Haste-sensitive damage and control events.
        """
        interval_ms = self._haste_adjusted_ms(6000, context.snapshot.ability_haste)
        amount = Decimal(300) + context.snapshot.ability_power
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 800
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"CHOGATH_Q_RUPTURE_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, amount, DamageType.MAGIC),
                        crowd_control(
                            context.opponent_entity,
                            "AIRBORNE",
                            duration_ms=1000,
                        ),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=1500,
                            magnitude=Decimal("0.60"),
                        ),
                    ),
                )
            )
            at_ms += interval_ms
        return tuple(events)

    def _scream_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule rank-one Feral Scream damage and silence.

        :param context: Snapshot supplying AP, haste, roles, and duration.
        :return: Haste-sensitive cone-hit events for the single target.
        """
        interval_ms = self._haste_adjusted_ms(11000, context.snapshot.ability_haste)
        amount = Decimal(80) + Decimal("0.70") * context.snapshot.ability_power
        base = self._sequence_base(context) + 200
        events: list[ActionEvent] = []
        at_ms = 1900
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"CHOGATH_W_FERAL_SCREAM_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, amount, DamageType.MAGIC),
                        crowd_control(
                            context.opponent_entity,
                            "SILENCE",
                            duration_ms=1600,
                        ),
                    ),
                )
            )
            at_ms += interval_ms
        return tuple(events)

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build three E attacks followed by ordinary basic attacks.

        :param context: Snapshot supplying AD, AP, attack speed, and target HP.
        :return: Blind-susceptible attack events in timestamp order.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        max_health_ratio = self._E5_BASE_MAX_HEALTH_RATIO + (
            self._E_FEAST_STACK_RATIO * self.feast_stack_fixture
        )
        spike_damage = (
            Decimal(110)
            + Decimal("0.30") * context.snapshot.ability_power
            + max_health_ratio * context.opponent_snapshot.max_hp
        )
        base = self._sequence_base(context) + 300
        events: list[ActionEvent] = []
        at_ms = 2350
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            empowered = index <= 3
            outputs = [
                damage(
                    context.opponent_entity,
                    context.snapshot.attack_damage,
                    DamageType.PHYSICAL,
                )
            ]
            event_id = f"CHOGATH_BASIC_ATTACK_{index}"
            if empowered:
                event_id = f"CHOGATH_E_VORPAL_SPIKES_ATTACK_{index}"
                outputs.extend(
                    (
                        damage(
                            context.opponent_entity,
                            spike_damage,
                            DamageType.MAGIC,
                        ),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=1500,
                            magnitude=Decimal("0.50"),
                        ),
                    )
                )
            events.append(
                action(
                    event_id,
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
            at_ms += interval_ms
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the fixed Q5/W1/E5/R2 level-13 combat sequence.

        :param context: Role-bound Cho'Gath and opponent snapshots.
        :return: Deterministic spell, empowered-attack, and sustain blockers.
        """
        base = self._sequence_base(context)
        ultimate_damage = (
            Decimal(475)
            + Decimal("0.50") * context.snapshot.ability_power
            + Decimal("0.10") * context.snapshot.bonus_health
        )
        fixed_events = (
            action(
                "CHOGATH_E_VORPAL_SPIKES_ACTIVATE",
                at_ms=2250,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(
                        context.self_entity,
                        "CHOGATH_E_THREE_EMPOWERED_ATTACKS",
                        6000,
                        Decimal(3),
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "CHOGATH_R_FEAST",
                at_ms=5000,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        ultimate_damage,
                        DamageType.TRUE,
                    ),
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"CHOGATH_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        events = (
            *self._rupture_events(context),
            *self._scream_events(context),
            *fixed_events,
            *self._attack_events(context),
        )
        return ActionPlan(
            "chogath_q5_w1_e5_r2_six_feast_stacks_level13_locked_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "CHOGATH_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "CHOGATH_ROTATION_AND_HIT_TIMING_UNVERIFIED",
                "CHOGATH_FEAST_STACK_FIXTURE_SIX_MINION_STACKS_ASSUMED",
                "CHOGATH_FEAST_DYNAMIC_STACK_ACQUISITION_NOT_MODELED",
                "CHOGATH_FEAST_EXECUTE_INDICATOR_NOT_MODELED",
                "CHOGATH_Q_DELAY_AND_TARGET_POSITION_NOT_MODELED",
                "CHOGATH_E_ATTACK_RESET_TIMING_UNVERIFIED",
                "CHOGATH_E_SPIKE_MULTITARGET_NOT_MODELED",
                "CHOGATH_PASSIVE_MINION_KILLS_NOT_MODELED",
                "CHOGATH_RESOURCE_COSTS_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Q knock-up and slow, W silence, and E slow windows.

        :param context: Role-bound snapshots for the Cho'Gath participant.
        :return: Causal control windows for opponent action processing.
        """
        action_plan = self.build_action_plan(context)
        windows: list[CastBlockWindow] = []
        for event in action_plan.events:
            if event.id.startswith("CHOGATH_Q_RUPTURE_"):
                windows.extend(
                    (
                        CastBlockWindow(
                            f"{event.id.casefold()}_knockup",
                            event.at_ms,
                            min(event.at_ms + 1000, context.duration_ms),
                            (
                                ActionChannel.BASIC_ATTACK,
                                ActionChannel.ABILITY,
                                ActionChannel.MOVEMENT,
                            ),
                            event.id,
                            False,
                            ControlType.AIRBORNE,
                        ),
                        CastBlockWindow(
                            f"{event.id.casefold()}_slow",
                            event.at_ms,
                            min(event.at_ms + 1500, context.duration_ms),
                            (ActionChannel.MOVEMENT,),
                            event.id,
                            True,
                            ControlType.SLOW,
                        ),
                    )
                )
            elif event.id.startswith("CHOGATH_W_FERAL_SCREAM_"):
                windows.append(
                    CastBlockWindow(
                        f"{event.id.casefold()}_silence",
                        event.at_ms,
                        min(event.at_ms + 1600, context.duration_ms),
                        (ActionChannel.ABILITY,),
                        event.id,
                        True,
                        ControlType.SILENCE,
                    )
                )
            elif event.id.startswith("CHOGATH_E_VORPAL_SPIKES_ATTACK_"):
                windows.append(
                    CastBlockWindow(
                        f"{event.id.casefold()}_slow",
                        event.at_ms,
                        min(event.at_ms + 1500, context.duration_ms),
                        (ActionChannel.MOVEMENT,),
                        event.id,
                        True,
                        ControlType.SLOW,
                    )
                )
        return ReactionPlan(
            "chogath_q5_w1_e5_control_reaction_v1",
            cast_block_windows=tuple(windows),
            blockers=(
                "CHOGATH_Q_KNOCKUP_AND_SLOW_OVERLAP_UNVERIFIED",
                "CHOGATH_Q_W_HIT_SUCCESS_FIXTURE_ASSUMED",
                "CHOGATH_E_SLOW_DECAY_NOT_MODELED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Decline to fabricate Carnivore healing without a kill schedule.

        The locked passive heals 18 plus two per champion level per killed
        unit, but the lane profile supplies neither minions nor last-hit events.

        :param context: Role-bound Cho'Gath lane snapshot.
        :param duration_ms: Lane observation duration in milliseconds.
        :param no_damage_delay_ms: Required out-of-combat recovery delay.
        :return: Zero recovery and the missing-event blocker.
        """
        return Decimal(0), ("CHOGATH_LANE_PASSIVE_MINION_KILL_SCHEDULE_NOT_MODELED",)
