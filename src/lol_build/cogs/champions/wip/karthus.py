"""Karthus combat Cog backed by the locked 16.17.1 sources."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    CastBlockWindow,
    ChampionCog,
    CogCapability,
    CogMaturity,
    ControlType,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    ResistanceReductionOutput,
    StatusOutput,
)


class KarthusCog(ChampionCog):
    """Model Karthus' Q5/W1/E5/R2 level-13 isolated-target fixture.

    Wall of Pain opens the fixture, Defile remains toggled on, and Lay Waste
    repeatedly hits only the opposing champion. Requiem begins at four seconds
    and resolves after its locked three-second channel. Nearby-unit isolation,
    post-death casting, and Requiem's other global recipients stay unresolved.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES | {CogCapability.MULTI_TARGET}
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Karthus.json",
        "data/raw/16.17.1/communitydragon/champions/30.json",
        "data/raw/16.17.1/communitydragon/champions/karthus.bin.json",
    )

    _W_AT_MS = 100
    _E_START_MS = 300
    _Q_FIRST_AT_MS = 500
    _R_START_MS = 4000
    _R_DAMAGE_AT_MS = 7000
    _TICK_MS = 250

    @staticmethod
    def _cooldown_ms(base_seconds: Decimal, ability_haste: Decimal) -> int:
        """Apply ability haste to one locked cooldown or ammo recharge time.

        :param base_seconds: Base duration in seconds from the locked spell data.
        :param ability_haste: Non-negative haste from Karthus' snapshot.
        :return: Positive nearest-even duration in milliseconds.
        """
        effective = base_seconds * Decimal(100) / (Decimal(100) + ability_haste)
        return max(
            1,
            int((effective * Decimal(1000)).to_integral_value(ROUND_HALF_EVEN)),
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose that Karthus has no self-directed pursuit-speed effect.

        :param context: Role-bound Karthus encounter context.
        :return: Neutral movement-speed multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose that Karthus has no displacement for closing distance.

        :param context: Role-bound Karthus encounter context.
        :return: Zero game units.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels the deterministic fixture cannot consume.

        AP, ability haste, attack speed, penetration, and chassis stats reach
        represented formulas or shared snapshots. Resource and combat-sustain
        stats cannot be valued because mana spending and healing are absent.

        :param item: Normalized candidate from the locked item catalog.
        :return: Karthus-scoped blocker, or ``None`` when represented.
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
            return f"KARTHUS_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _lay_waste_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule isolated rank-five Lay Waste hits outside the R channel.

        The locked tooltip calculation uses 116 base damage plus 35% AP and a
        two-times single-target modifier. Its one-second ammo recharge is
        haste-sensitive; two initial charges are not separately front-loaded.

        :param context: Role-bound snapshot supplying AP, haste, and roles.
        :return: Chronological isolated magic-damage events.
        """
        amount = Decimal(2) * (Decimal(116) + Decimal("0.35") * context.snapshot.ability_power)
        interval_ms = self._cooldown_ms(Decimal(1), context.snapshot.ability_haste)
        sequence = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = self._Q_FIRST_AT_MS
        while at_ms <= context.duration_ms:
            if self._R_START_MS <= at_ms < self._R_DAMAGE_AT_MS:
                at_ms = self._R_DAMAGE_AT_MS
                continue
            index = len(events) + 1
            events.append(
                action(
                    f"KARTHUS_Q_LAY_WASTE_ISOLATED_{index}",
                    at_ms=at_ms,
                    sequence=sequence + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, amount, DamageType.MAGIC),),
                )
            )
            at_ms += interval_ms
        return tuple(events)

    def _defile_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build a toggle marker and quarter-second rank-five Defile ticks.

        :param context: Role-bound snapshot supplying AP and participant roles.
        :return: Toggle activation followed by in-horizon aura damage ticks.
        """
        sequence = self._sequence_base(context) + 200
        damage_per_tick = (
            Decimal(110) + Decimal("0.20") * context.snapshot.ability_power
        ) / Decimal(4)
        events = [
            action(
                "KARTHUS_E_DEFILE_TOGGLE_ON",
                at_ms=self._E_START_MS,
                sequence=sequence,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(
                        context.self_entity,
                        "KARTHUS_E_DEFILE_ACTIVE",
                        max(1, context.duration_ms - self._E_START_MS + 1),
                    ),
                ),
            )
        ]
        for index, at_ms in enumerate(
            range(self._E_START_MS + self._TICK_MS, context.duration_ms + 1, self._TICK_MS),
            start=1,
        ):
            events.append(
                action(
                    f"KARTHUS_E_DEFILE_TICK_{index}",
                    at_ms=at_ms,
                    sequence=sequence + index,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(
                        *self.area_outputs(
                            context,
                            lambda entity: damage(entity, damage_per_tick, DamageType.MAGIC),
                            centered_on_self=True,
                        ),
                    ),
                )
            )
        return tuple(events)

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks while Karthus is not channeling Requiem.

        :param context: Role-bound snapshot supplying attack damage and cadence.
        :return: Blind-susceptible physical basic attacks.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        sequence = self._sequence_base(context) + 500
        events: list[ActionEvent] = []
        at_ms = 1000
        while at_ms <= context.duration_ms:
            if self._R_START_MS <= at_ms < self._R_DAMAGE_AT_MS:
                at_ms += interval_ms
                continue
            index = len(events) + 1
            events.append(
                action(
                    f"KARTHUS_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=sequence + index,
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
        """Build the level-13 isolated-target damage fixture and its blockers.

        :param context: Role-bound Karthus and opponent combat snapshots.
        :return: Deterministic W, E, Q, R, and basic-attack schedule.
        """
        base = self._sequence_base(context)
        wall = action(
            "KARTHUS_W_WALL_OF_PAIN_CONTACT",
            at_ms=self._W_AT_MS,
            sequence=base,
            source=context.self_entity,
            channel=ActionChannel.ABILITY,
            outputs=(
                ResistanceReductionOutput(
                    context.opponent_entity,
                    "MAGIC_RESISTANCE",
                    Decimal("0.25"),
                    1,
                    5000,
                    f"KARTHUS_W_MR_SHRED_{context.self_entity.value}",
                ),
                crowd_control(
                    context.opponent_entity,
                    "SLOW",
                    duration_ms=5000,
                    magnitude=Decimal("0.40"),
                ),
            ),
        )
        requiem_events: tuple[ActionEvent, ...] = ()
        if context.duration_ms >= self._R_START_MS:
            events = [
                action(
                    "KARTHUS_R_REQUIEM_CHANNEL_START",
                    at_ms=self._R_START_MS,
                    sequence=base + 300,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(StatusOutput(context.self_entity, "KARTHUS_R_CHANNELING", 3000),),
                    requires_living_opponent=False,
                )
            ]
            if context.duration_ms >= self._R_DAMAGE_AT_MS:
                amount = Decimal(350) + Decimal("0.70") * context.snapshot.ability_power
                events.append(
                    action(
                        "KARTHUS_R_REQUIEM_SINGLE_REPRESENTED_TARGET",
                        at_ms=self._R_DAMAGE_AT_MS,
                        sequence=base + 301,
                        source=context.self_entity,
                        channel=ActionChannel.PASSIVE,
                        outputs=(damage(context.opponent_entity, amount, DamageType.MAGIC),),
                    )
                )
            requiem_events = tuple(events)
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"KARTHUS_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "karthus_q5_w1_e5_r2_level13_isolated_target_v1",
            tuple(
                sorted(
                    (
                        wall,
                        *self._defile_events(context),
                        *self._lay_waste_events(context),
                        *requiem_events,
                        *self._basic_attacks(context),
                    ),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "KARTHUS_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "KARTHUS_Q_SINGLE_TARGET_ISOLATION_FIXED_BY_FIXTURE",
                "KARTHUS_Q_NEARBY_UNIT_ISOLATION_NOT_MODELED",
                "KARTHUS_Q_AMMO_INITIAL_CHARGES_AND_HIT_TIMING_UNVERIFIED",
                "KARTHUS_W_TARGET_CROSSES_WALL_ASSUMED",
                "KARTHUS_W_DECAYING_SLOW_REPRESENTED_AS_CONSTANT_WINDOW",
                "KARTHUS_E_TARGET_REMAINS_IN_AURA_ASSUMED",
                "KARTHUS_E_TICK_PHASE_UNVERIFIED",
                "KARTHUS_R_CHANNEL_CANCELLATION_CAUSALITY_NOT_MODELED",
                "KARTHUS_R_GLOBAL_OTHER_CHAMPION_TARGETS_NOT_MODELED",
                "KARTHUS_R_TARGET_AVAILABILITY_AND_DISTANCE_NOT_MODELED",
                "KARTHUS_PASSIVE_POST_DEATH_SEVEN_SECOND_CASTING_NOT_MODELED",
                "KARTHUS_PASSIVE_DEATH_TRIGGER_AND_SPELL_COST_STATE_NOT_MODELED",
                "KARTHUS_MANA_COSTS_KILL_REFUNDS_AND_TOGGLE_UPKEEP_NOT_MODELED",
                "KARTHUS_Q_ISOLATION_BONUS_KEEPS_LAY_WASTE_SINGLE_TARGET",
                "KARTHUS_CAST_ATTACK_AND_CHANNEL_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Wall of Pain's fixture-guaranteed movement-slow window.

        :param context: Role-bound snapshots identifying Karthus' opponent.
        :return: Source-linked, tenacity-reducible movement control.
        """
        return ReactionPlan(
            "karthus_w1_wall_slow_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "karthus_w_wall_of_pain_slow",
                    self._W_AT_MS,
                    min(self._W_AT_MS + 5000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "KARTHUS_W_WALL_OF_PAIN_CONTACT",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=(
                "KARTHUS_W_TARGET_CROSSES_WALL_ASSUMED",
                "KARTHUS_W_DECAYING_SLOW_REPRESENTED_AS_CONSTANT_WINDOW",
                "KARTHUS_W_WALL_GEOMETRY_AND_REENTRY_NOT_MODELED",
            ),
        )
