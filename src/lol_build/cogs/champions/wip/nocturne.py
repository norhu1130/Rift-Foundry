"""Nocturne combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, damage, healing, movement_speed
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class NocturneCog(ChampionCog):
    """Model Nocturne's Q5/W1/E5/R2 level-13 assassination fixture.

    Paranoia closes the initial distance, Duskbringer establishes its five-second
    trail, Shroud of Darkness exposes a consumable spell shield, and Unspeakable
    Horror deals four tether ticks before fear. Umbra Blades begins ready and
    refreshes after four champion attacks under its locked cooldown reduction.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Nocturne.json",
        "data/raw/16.17.1/communitydragon/champions/56.json",
        "data/raw/16.17.1/communitydragon/champions/nocturne.bin.json",
    )

    _R_AT_MS = 0
    _Q_AT_MS = 100
    _W_AT_MS = 200
    _E_AT_MS = 300
    _FEAR_AT_MS = 2300

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose rank-five Duskbringer trail movement speed.

        :param context: Role-bound Nocturne encounter context.
        :return: Thirty-five-percent pursuit multiplier while on the trail.
        """
        return Decimal("1.35")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose rank-two Paranoia's target acquisition distance.

        :param context: Role-bound Nocturne encounter context.
        :return: Locked rank-two dash range in game units.
        """
        return Decimal(4250)

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Decline to infer Umbra Blades targets and attack cadence in lane.

        :param context: Role-bound Nocturne lane context.
        :param duration_ms: Requested lane observation duration.
        :param no_damage_delay_ms: Time since the last incoming damage event.
        :return: Zero recovery and an explicit target-state blocker.
        """
        return Decimal(0), ("NOCTURNE_PASSIVE_LANE_HEAL_REQUIRES_ATTACK_TARGET_TIMELINE",)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels not represented by the fixed rotation.

        :param item: Normalized candidate from the locked item catalog.
        :return: Nocturne-scoped blocker, or ``None`` for represented stats.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        return (
            f"NOCTURNE_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
            if unsupported
            else None
        )

    @staticmethod
    def _passive_heal(context: ParticipantContext) -> Decimal:
        """Interpolate Umbra Blades healing at the modeled level.

        :param context: Snapshot supplying level and ability power.
        :return: Raw self-healing for one empowered attack.
        """
        level_fraction = Decimal(context.snapshot.level - 1) / Decimal(17)
        return (
            Decimal(13)
            + Decimal(19) * level_fraction
            + Decimal("0.30") * context.snapshot.ability_power
        )

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks with W attack speed and passive cooldown refunds.

        :param context: Snapshot supplying AD, crit chance, AP, and duration.
        :return: Chronological attacks with first and fifth Umbra Blades procs.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed * Decimal("1.30"))
        trail_ad = context.snapshot.attack_damage + Decimal(55)
        expected_attack = trail_ad * (Decimal(1) + context.snapshot.critical_strike_chance)
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        for index, at_ms in enumerate(range(500, context.duration_ms + 1, interval), start=1):
            passive_ready = index in {1, 5}
            outputs = [
                damage(
                    context.opponent_entity,
                    trail_ad * Decimal("1.20") if passive_ready else expected_attack,
                    DamageType.PHYSICAL,
                )
            ]
            if passive_ready:
                outputs.append(healing(context.self_entity, self._passive_heal(context)))
            events.append(
                action(
                    f"NOCTURNE_UMBRA_BLADES_ATTACK_{index}"
                    if passive_ready
                    else f"NOCTURNE_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
        return tuple(events)

    def _tether_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Split rank-five Unspeakable Horror damage over its two-second tether.

        :param context: Snapshot supplying AP, roles, and duration.
        :return: Four evenly divided magic-damage ticks.
        """
        tick = (Decimal(260) + context.snapshot.ability_power) / Decimal(4)
        base = self._sequence_base(context) + 50
        return tuple(
            action(
                f"NOCTURNE_E_UNSPEAKABLE_HORROR_TICK_{index}",
                at_ms=self._E_AT_MS + index * 500,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, tick, DamageType.MAGIC),),
            )
            for index in range(1, 5)
            if self._E_AT_MS + index * 500 <= context.duration_ms
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Paranoia, trail, spell shield, tether, and attack events.

        :param context: Role-bound level-13 Nocturne encounter context.
        :return: Deterministic assassination action schedule.
        """
        bonus_ad = context.snapshot.bonus_attack_damage
        base = self._sequence_base(context)
        events = (
            action(
                "NOCTURNE_R_PARANOIA_DASH",
                at_ms=self._R_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.MOVEMENT,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(275) + Decimal("1.20") * bonus_ad,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
            action(
                "NOCTURNE_Q_DUSKBRINGER",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(225) + Decimal("0.85") * bonus_ad,
                        DamageType.PHYSICAL,
                    ),
                    movement_speed(
                        context.self_entity,
                        context.snapshot.move_speed * Decimal("0.35"),
                        duration_ms=5000,
                    ),
                    StatusOutput(context.self_entity, "NOCTURNE_DUSK_TRAIL", 5000),
                ),
            ),
            action(
                "NOCTURNE_W_SHROUD_OF_DARKNESS",
                at_ms=self._W_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "SPELL_SHIELD", 1500),),
                requires_living_opponent=False,
            ),
            *self._tether_events(context),
            *self._attack_events(context),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"NOCTURNE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "nocturne_q5_w1_e5_r2_assassination_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "NOCTURNE_LEVEL13_Q5_E5_W1_R2_ORDER_LOCKED_UNVERIFIED",
                "NOCTURNE_R_AND_Q_ASSUMED_TO_HIT_PRIMARY_TARGET",
                "NOCTURNE_E_TETHER_ASSUMED_UNBROKEN_FOR_TWO_SECONDS",
                "NOCTURNE_W_SUCCESSFUL_BLOCK_DOUBLE_ATTACK_SPEED_NOT_SCHEDULED",
                "NOCTURNE_PASSIVE_CRITICAL_PACKET_MAPPING_UNVERIFIED",
                "NOCTURNE_PARANOIA_VISION_DENIAL_OUT_OF_DUEL_METRICS",
                "NOCTURNE_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the delayed rank-five fear as hostile action cancellation.

        :param context: Role-bound Nocturne and opponent snapshots.
        :return: Tenacity-reducible fear window linked to the tether event.
        """
        return ReactionPlan(
            "nocturne_e5_fear_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "nocturne_e_unspeakable_horror_fear",
                    self._FEAR_AT_MS,
                    min(self._FEAR_AT_MS + 2250, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "NOCTURNE_E_UNSPEAKABLE_HORROR_TICK_4",
                    True,
                    ControlType.FEAR,
                ),
            ),
            blockers=(
                "NOCTURNE_E_FEAR_MOVEMENT_DIRECTION_NOT_MODELED",
                "NOCTURNE_W_SHIELD_CONSUMPTION_DEPENDS_ON_OPPONENT_EVENT_ORDER",
            ),
        )
