"""Azir combat Cog backed by the locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

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
from lol_build.cogs.mechanics import action, crowd_control, damage, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class AzirCog(ChampionCog):
    """Model Azir's Q5/W5/E1/R2 level-13 single-soldier fixture.

    One soldier is summoned at the start and remains able to attack the duel
    target for the complete encounter. Conquering Sands moves that soldier
    through the opponent, Shifting Sands then collides with the opponent on the
    route to it, and Emperor's Divide displaces the opponent. This deterministic
    arrangement exposes the kit's damage, cadence, shield, control, and approach
    channels without pretending to solve soldier placement geometry.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Azir.json",
        "data/raw/16.17.1/communitydragon/champions/268.json",
        "data/raw/16.17.1/communitydragon/champions/azir.bin.json",
    )

    _W_AT_MS = 0
    _Q_FIRST_AT_MS = 200
    _SOLDIER_FIRST_ATTACK_AT_MS = 550
    _E_AT_MS = 800
    _R_AT_MS = 1200
    _R_DISPLACEMENT_FIXTURE_MS = 500

    @staticmethod
    def _cooldown_ms(base_ms: int, ability_haste: Decimal) -> int:
        """Apply the standard ability-haste divisor to a cooldown.

        :param base_ms: Rank-specific cooldown before ability haste.
        :param ability_haste: Non-negative haste supplied by the snapshot.
        :return: Deterministically rounded cooldown in milliseconds.
        :raises ValueError: If the base cooldown or haste is negative.
        """
        if base_ms < 0 or ability_haste < 0:
            raise ValueError("cooldown inputs cannot be negative")
        return max(
            1,
            int(
                (
                    Decimal(base_ms) * Decimal(100) / (Decimal(100) + ability_haste)
                ).to_integral_value(ROUND_HALF_EVEN)
            ),
        )

    @staticmethod
    def _soldier_base_damage(level: int) -> Decimal:
        """Evaluate W5's locked post-level-nine damage progression.

        The BIN calculation uses rank-five base damage 110 and adds eight for
        every champion level beginning at level ten.

        :param level: Champion level selecting the breakpoint contribution.
        :return: Raw base damage for one primary-target soldier strike.
        """
        bounded_level = min(18, max(1, level))
        return Decimal(110) + Decimal(8) * Decimal(max(0, bounded_level - 9))

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Shifting Sands' locked maximum soldier dash range.

        :param context: Role-bound Azir encounter context.
        :return: Maximum modeled dash distance in game units.
        """
        return Decimal(1100)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats absent from the single-soldier event model.

        AP, attack speed, ability haste, penetration, movement, and defensive
        chassis stats reach represented calculations. Soldier attacks do not use
        Azir's attack damage, so only his own plain attacks gain expected
        critical-strike damage; resource consumption and generic item sustain
        remain outside this fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Azir-scoped blocker, or ``None`` when all stats are represented.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "AD",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"AZIR_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Q5 soldier reposition hits with haste-sensitive recasts.

        :param context: Snapshot supplying AP, haste, duration, and role binding.
        :return: In-horizon Conquering Sands damage and slow events.
        """
        cooldown_ms = self._cooldown_ms(6000, context.snapshot.ability_haste)
        raw_damage = Decimal(155) + Decimal("0.55") * context.snapshot.ability_power
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = self._Q_FIRST_AT_MS
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"AZIR_Q_CONQUERING_SANDS_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, raw_damage, DamageType.MAGIC),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=1000,
                            magnitude=Decimal("0.25"),
                        ),
                    ),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def _soldier_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule W5 soldier commands through the shared attack clock.

        :param context: Snapshot supplying level, AP, attack speed, and roles.
        :return: Primary-target magic attacks made by the fixed single soldier.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        raw_damage = self._soldier_base_damage(context.snapshot.level) + (
            Decimal("0.65") * context.snapshot.ability_power
        )
        base = self._sequence_base(context) + 200
        events: list[ActionEvent] = []
        at_ms = self._SOLDIER_FIRST_ATTACK_AT_MS
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"AZIR_W_SOLDIER_ATTACK_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(damage(context.opponent_entity, raw_damage, DamageType.MAGIC),),
                )
            )
            at_ms += interval_ms
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked single-soldier Q5/W5/E1/R2 rotation.

        :param context: Role-bound Azir and opponent combat snapshots.
        :return: Deterministic spell, soldier-attack, shield, and control events.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        fixed_events = (
            action(
                "AZIR_W_ARISE_SINGLE_SOLDIER_FIXTURE",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "AZIR_SINGLE_SOLDIER_ACTIVE", 10_000),),
                requires_living_opponent=False,
            ),
            action(
                "AZIR_E_SHIFTING_SANDS_COLLISION_FIXTURE",
                at_ms=self._E_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(70) + Decimal("0.60") * ap,
                        DamageType.MAGIC,
                    ),
                    shielding(
                        context.self_entity,
                        Decimal(70) + Decimal("0.60") * ap,
                        duration_ms=1500,
                    ),
                ),
            ),
            action(
                "AZIR_R_EMPERORS_DIVIDE",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(400) + Decimal("0.75") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "AIRBORNE",
                        duration_ms=self._R_DISPLACEMENT_FIXTURE_MS,
                    ),
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"AZIR_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "azir_q5_w5_e1_r2_single_soldier_level13_locked_v1",
            tuple(
                sorted(
                    (*fixed_events, *self._q_events(context), *self._soldier_attacks(context)),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "AZIR_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "AZIR_SINGLE_SOLDIER_COUNT_AND_POSITION_FIXTURE",
                "AZIR_SOLDIER_TARGET_IN_ATTACK_RANGE_ASSUMED",
                "AZIR_SOLDIER_ATTACK_WINDUP_AND_COMMAND_TIMING_UNVERIFIED",
                "AZIR_Q_SOLDIER_TRAVEL_AND_HIT_TIMING_UNVERIFIED",
                "AZIR_E_ROUTE_COLLISION_AND_STOP_ASSUMED",
                "AZIR_E_TRAVEL_TIME_NOT_MODELED",
                "AZIR_R_DISPLACEMENT_DURATION_FIXTURE_UNVERIFIED",
                "AZIR_MULTI_SOLDIER_DAMAGE_REDUCTION_NOT_MODELED",
                "AZIR_MULTI_TARGET_SOLDIER_PIERCE_NOT_MODELED",
                "AZIR_PASSIVE_SUN_DISC_TURRET_NOT_MODELED",
                "AZIR_RESOURCE_AND_SOLDIER_AMMO_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Q slow and R displacement cancellation windows.

        :param context: Role-bound snapshots used to bind control recipients.
        :return: Haste-aware Q slows and the fixed R knockback interval.
        """
        q_windows = tuple(
            CastBlockWindow(
                f"azir_q_slow_{index}",
                event.at_ms,
                min(event.at_ms + 1000, context.duration_ms),
                (ActionChannel.MOVEMENT,),
                event.id,
                True,
                ControlType.SLOW,
            )
            for index, event in enumerate(self._q_events(context), start=1)
        )
        r_end = min(self._R_AT_MS + self._R_DISPLACEMENT_FIXTURE_MS, context.duration_ms)
        r_windows = (
            (
                CastBlockWindow(
                    "azir_r_emperors_divide_knockback",
                    self._R_AT_MS,
                    r_end,
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT),
                    "AZIR_R_EMPERORS_DIVIDE",
                    False,
                    ControlType.AIRBORNE,
                ),
            )
            if context.duration_ms > self._R_AT_MS
            else ()
        )
        return ReactionPlan(
            "azir_q5_r2_control_fixture_reaction_v1",
            cast_block_windows=(*q_windows, *r_windows),
            blockers=(
                "AZIR_Q_SLOW_CONTACT_TIMING_UNVERIFIED",
                "AZIR_R_DISPLACEMENT_DURATION_FIXTURE_UNVERIFIED",
                "AZIR_R_WALL_GEOMETRY_AND_REACQUISITION_NOT_MODELED",
            ),
        )
