"""Heimerdinger combat Cog backed by the locked 16.17.1 sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class HeimerdingerCog(ChampionCog):
    """Model a level-13 Q5/W5/E1/R2 single-target fixture.

    One regular Q turret is placed beside Heimerdinger at combat start. Its
    presence enables the passive movement-speed assumption, but its autonomous
    attacks are deliberately excluded: the shared timeline has no turret
    entity, charge gauge, target selection, or pet attack clock. The active
    rotation lands E in its stun center and all missiles from R-upgraded W.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Heimerdinger.json",
        "data/raw/16.17.1/communitydragon/champions/74.json",
        "data/raw/16.17.1/communitydragon/champions/heimerdinger.bin.json",
    )

    _Q_AT_MS = 0
    _E_FIRST_AT_MS = 200
    _R_AT_MS = 450
    _UPGRADED_W_AT_MS = 600
    _BASIC_ATTACK_FIRST_AT_MS = 1200

    @staticmethod
    def _cooldown_ms(base_ms: int, ability_haste: Decimal) -> int:
        """Apply the standard ability-haste divisor to a cooldown.

        :param base_ms: Rank-specific cooldown before haste.
        :param ability_haste: Non-negative haste from the champion snapshot.
        :return: Deterministically rounded cooldown in milliseconds.
        :raises ValueError: If either input is negative.
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

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Techmaturgical Repair Bots near the fixture turret.

        :param context: Role-bound encounter containing the placed-turret fixture.
        :return: Locked 20% movement-speed multiplier while near that turret.
        """
        return Decimal("1.20")

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject stats absent from the fixed Heimerdinger event model.

        AP, AD, attack speed, haste, penetration, movement, and defensive stats
        reach represented calculations. Resources and on-damage sustain do not,
        and ordinary critical strikes are not synthesized by this timeline.

        :param item: Normalized candidate from the locked item catalog.
        :return: Champion-scoped blocker, or ``None`` for represented stats.
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
            return f"HEIMERDINGER_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _e_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule E1 center hits and haste-sensitive recasts.

        :param context: Snapshot supplying AP, haste, duration, and role binding.
        :return: In-horizon grenade damage, stun, and slow events.
        """
        cooldown_ms = self._cooldown_ms(11_000, context.snapshot.ability_haste)
        raw_damage = Decimal(60) + Decimal("0.60") * context.snapshot.ability_power
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = self._E_FIRST_AT_MS
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"HEIMERDINGER_E_ELECTRON_STORM_CENTER_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, raw_damage, DamageType.MAGIC),
                        crowd_control(context.opponent_entity, "STUN", duration_ms=1500),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=2000,
                            magnitude=Decimal("0.35"),
                        ),
                    ),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def _w_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule the upgraded volley and subsequent W5 volleys.

        :param context: Snapshot supplying AP, haste, duration, and role binding.
        :return: Aggregate all-missiles-hit magic-damage events.
        """
        ap = context.snapshot.ability_power
        cooldown_ms = self._cooldown_ms(7000, context.snapshot.ability_haste)
        base = self._sequence_base(context) + 200
        events: list[ActionEvent] = []
        at_ms = self._UPGRADED_W_AT_MS
        if at_ms <= context.duration_ms:
            events.append(
                action(
                    "HEIMERDINGER_RW_HEXTECH_ROCKET_SWARM_ALL_HITS",
                    at_ms=at_ms,
                    sequence=base,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal("697.5") + Decimal("1.83") * ap,
                            DamageType.MAGIC,
                        ),
                    ),
                )
            )
        at_ms += cooldown_ms
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"HEIMERDINGER_W_MICRO_ROCKETS_ALL_HITS_{len(events)}",
                    at_ms=at_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal(270) + Decimal("1.03") * ap,
                            DamageType.MAGIC,
                        ),
                    ),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Heimerdinger's ordinary ranged basic attacks.

        :param context: Snapshot supplying attack damage, speed, and entity roles.
        :return: In-horizon physical basic-attack events.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 300
        events: list[ActionEvent] = []
        at_ms = self._BASIC_ATTACK_FIRST_AT_MS
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"HEIMERDINGER_BASIC_ATTACK_{len(events) + 1}",
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
        """Build the locked Q5/W5/E1/R2 level-13 combat fixture.

        :param context: Role-bound Heimerdinger and opponent snapshots.
        :return: Deterministic deployment, spells, attacks, and explicit blockers.
        """
        base = self._sequence_base(context)
        fixed_events = (
            action(
                "HEIMERDINGER_Q_SINGLE_TURRET_PROXIMITY_FIXTURE",
                at_ms=self._Q_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(
                        context.self_entity,
                        "HEIMERDINGER_NEAR_OWN_TURRET",
                        max(1, context.duration_ms),
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "HEIMERDINGER_R_UPGRADE_W",
                at_ms=self._R_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "HEIMERDINGER_UPGRADE_W", 150),),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"HEIMERDINGER_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "heimerdinger_q5_w5_e1_r2_single_turret_level13_locked_v1",
            tuple(
                sorted(
                    (
                        *fixed_events,
                        *self._e_events(context),
                        *self._w_events(context),
                        *self._basic_attacks(context),
                    ),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "HEIMERDINGER_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "HEIMERDINGER_SINGLE_TURRET_NEAR_SELF_FIXTURE",
                "HEIMERDINGER_Q_TURRET_ATTACKS_AND_BEAMS_NOT_MODELED",
                "HEIMERDINGER_Q_TURRET_ENTITY_HEALTH_AND_TARGETING_NOT_MODELED",
                "HEIMERDINGER_Q_AMMO_AND_CHARGE_NOT_MODELED",
                "HEIMERDINGER_E_CENTER_HIT_ASSUMED",
                "HEIMERDINGER_E_TURRET_CHARGE_TRIGGER_NOT_MODELED",
                "HEIMERDINGER_RW_ALL_ROCKETS_HIT_SINGLE_TARGET_ASSUMED",
                "HEIMERDINGER_ROCKET_TRAVEL_AND_CAST_TIMING_UNVERIFIED",
                "HEIMERDINGER_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose each E center stun and surrounding slow window.

        :param context: Role-bound snapshots used to bind control recipients.
        :return: Haste-aware, source-linked stun and slow cast blocks.
        """
        windows: list[CastBlockWindow] = []
        for index, event in enumerate(self._e_events(context), start=1):
            windows.extend(
                (
                    CastBlockWindow(
                        f"heimerdinger_e_center_stun_{index}",
                        event.at_ms,
                        min(event.at_ms + 1500, context.duration_ms),
                        (
                            ActionChannel.BASIC_ATTACK,
                            ActionChannel.ABILITY,
                            ActionChannel.MOVEMENT,
                        ),
                        event.id,
                        True,
                        ControlType.STUN,
                    ),
                    CastBlockWindow(
                        f"heimerdinger_e_area_slow_{index}",
                        event.at_ms,
                        min(event.at_ms + 2000, context.duration_ms),
                        (ActionChannel.MOVEMENT,),
                        event.id,
                        True,
                        ControlType.SLOW,
                    ),
                )
            )
        return ReactionPlan(
            "heimerdinger_e1_center_control_reaction_v1",
            cast_block_windows=tuple(windows),
            blockers=(
                "HEIMERDINGER_E_CENTER_HIT_ASSUMED",
                "HEIMERDINGER_E_STUN_AND_SLOW_OVERLAP_RUNTIME_UNVERIFIED",
                "HEIMERDINGER_PASSIVE_TURRET_PROXIMITY_FIXED_FOR_ENGAGEMENT",
            ),
        )
