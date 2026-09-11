"""Gangplank combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import (
    action,
    crowd_control,
    damage,
    missing_health_healing,
    movement_speed,
)
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, RemoveStatusOutput, StatusOutput


class GangplankCog(ChampionCog):
    """Model Gangplank's Q5/E5/W1/R2 level-13 barrel fixture.

    Parrrley detonates one prepared rank-five keg, resetting Trial by Fire for
    a second empowered attack. Cannon Barrage assumes the opponent remains in
    its unupgraded zone for all twelve tooltip waves. Keg-specific armor ignore
    remain explicit engine blockers; Remove Scurvy heals its base amount plus
    ``PercentHeal`` (13%) of the health missing when it resolves.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Gangplank.json",
        "data/raw/16.17.1/communitydragon/champions/41.json",
        "data/raw/16.17.1/communitydragon/champions/gangplank.bin.json",
    )

    _BARREL_AT_MS = 1200
    _BARREL_SLOW_MS = 2000
    _R_FIRST_WAVE_MS = 500
    _R_LAST_WAVE_MS = 7650
    _R_WAVES = 12

    @staticmethod
    def _cooldown_ms(seconds: Decimal, ability_haste: Decimal) -> int:
        """Convert a cooldown through the shared ability-haste formula.

        :param seconds: Locked base cooldown in seconds.
        :param ability_haste: Non-negative haste supplied by the snapshot.
        :return: Deterministically rounded cooldown in milliseconds.
        :raises ValueError: If ability haste is negative.
        """
        if ability_haste < 0:
            raise ValueError("ability_haste must be non-negative")
        value = seconds * Decimal(100_000) / (Decimal(100) + ability_haste)
        return max(1, int(value.to_integral_value(ROUND_HALF_EVEN)))

    @staticmethod
    def _passive_damage(context: ParticipantContext) -> Decimal:
        """Calculate level-scaled Trial by Fire true damage.

        :param context: Snapshot supplying level and bonus attack damage.
        :return: Raw true damage for one empowered attack.
        """
        level_fraction = Decimal(context.snapshot.level - 1) / Decimal(17)
        return Decimal(50) + Decimal(200) * level_fraction + context.snapshot.bonus_attack_damage

    @staticmethod
    def _passive_speed_fraction(context: ParticipantContext) -> Decimal:
        """Calculate Trial by Fire's level-interpolated movement bonus.

        :param context: Snapshot supplying the champion level.
        :return: Movement-speed fraction active after an empowered attack.
        """
        return Decimal("0.15") + Decimal("0.15") * Decimal(context.snapshot.level - 1) / Decimal(17)

    def _passive_attack(
        self,
        context: ParticipantContext,
        *,
        event_id: str,
        at_ms: int,
        sequence: int,
    ) -> ActionEvent:
        """Build one Trial by Fire empowered basic attack.

        :param context: Snapshot supplying attack damage, level, and movement speed.
        :param event_id: Stable event identifier.
        :param at_ms: Attack timestamp in the fixture.
        :param sequence: Stable cross-participant ordering key.
        :return: Physical attack, true burn, and self-speed event.
        """
        return action(
            event_id,
            at_ms=at_ms,
            sequence=sequence,
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
                    self._passive_damage(context),
                    DamageType.TRUE,
                ),
                movement_speed(
                    context.self_entity,
                    context.snapshot.move_speed * self._passive_speed_fraction(context),
                    duration_ms=2000,
                ),
            ),
        )

    def _r_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule twelve maximum-contact Cannon Barrage waves.

        :param context: Snapshot supplying AP, duration, and role bindings.
        :return: Wave damage and slow events within the benchmark.
        """
        if context.duration_ms < self._R_FIRST_WAVE_MS:
            return ()
        step = (self._R_LAST_WAVE_MS - self._R_FIRST_WAVE_MS) // (self._R_WAVES - 1)
        amount = Decimal(70) + Decimal("0.10") * context.snapshot.ability_power
        base = self._sequence_base(context) + 500
        events: list[ActionEvent] = []
        for index in range(self._R_WAVES):
            at_ms = self._R_FIRST_WAVE_MS + step * index
            if at_ms > context.duration_ms:
                break
            events.append(
                action(
                    f"GANGPLANK_R_CANNON_BARRAGE_WAVE_{index + 1}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY if index == 0 else ActionChannel.PASSIVE,
                    outputs=(
                        damage(context.opponent_entity, amount, DamageType.MAGIC),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=500,
                            magnitude=Decimal("0.30"),
                        ),
                    ),
                )
            )
        return tuple(events)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Trial by Fire's initial level-scaled chase multiplier.

        :param context: Role-bound Gangplank encounter context.
        :return: Initial movement multiplier after an empowered attack.
        """
        return Decimal(1) + self._passive_speed_fraction(context)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return zero because Gangplank has no displacement ability.

        :param context: Role-bound Gangplank encounter context.
        :return: Zero dash distance.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the fixed barrel fixture.

        :param item: Normalized candidate from the locked catalog.
        :return: Gangplank-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "CRITICAL_STRIKE_CHANCE",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"GANGPLANK_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the passive, barrel, Parrrley, citrus, and ultimate fixture.

        :param context: Role-bound Gangplank and opponent snapshots.
        :return: Deterministic level-13 action schedule with blockers.
        """
        base = self._sequence_base(context)
        q_damage = Decimal(130) + context.snapshot.attack_damage
        events: list[ActionEvent] = [
            self._passive_attack(
                context,
                event_id="GANGPLANK_PASSIVE_TRIAL_BY_FIRE_INITIAL",
                at_ms=100,
                sequence=base,
            ),
            action(
                "GANGPLANK_E_Q_POWDER_KEG_DETONATION",
                at_ms=self._BARREL_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity,
                        q_damage + Decimal(80),
                        DamageType.PHYSICAL,
                        percent_resistance_penetration=Decimal("0.40"),
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=self._BARREL_SLOW_MS,
                        magnitude=Decimal("0.80"),
                    ),
                    StatusOutput(context.self_entity, "GANGPLANK_PASSIVE_RESET", 1),
                ),
            ),
            self._passive_attack(
                context,
                event_id="GANGPLANK_PASSIVE_TRIAL_BY_FIRE_AFTER_KEG",
                at_ms=1700,
                sequence=base + 2,
            ),
            action(
                "GANGPLANK_W_REMOVE_SCURVY",
                at_ms=3500,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    RemoveStatusOutput(
                        context.self_entity,
                        "CROWD_CONTROL_EXCEPT_AIRBORNE",
                    ),
                    missing_health_healing(
                        context.self_entity,
                        Decimal("0.13"),
                        base_amount=Decimal(45) + Decimal("0.90") * context.snapshot.ability_power,
                    ),
                ),
                requires_living_opponent=False,
            ),
        ]
        q_recast_ms = self._BARREL_AT_MS + self._cooldown_ms(
            Decimal("4.5"), context.snapshot.ability_haste
        )
        if q_recast_ms <= context.duration_ms:
            events.append(
                action(
                    "GANGPLANK_Q_PARRRLEY_DIRECT",
                    at_ms=q_recast_ms,
                    sequence=base + 100,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, q_damage, DamageType.PHYSICAL),),
                )
            )
        events.extend(self._r_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"GANGPLANK_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "gangplank_q5_e5_w1_r2_level13_barrel_fixture_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "GANGPLANK_LEVEL13_Q5_E5_W1_R2_LOCKED_RECOMMENDATION_UNVERIFIED",
                "GANGPLANK_BARREL_PLACEMENT_DECAY_AND_DETONATION_TIMING_ASSUMED",
                "GANGPLANK_BARREL_CHAIN_AND_ENEMY_DEFUSE_NOT_MODELED",
                "GANGPLANK_Q_ON_HIT_AND_CRITICAL_STRIKE_NOT_MODELED",
                "GANGPLANK_R_ALL_TWELVE_WAVES_HIT_ASSUMED",
                "GANGPLANK_R_SHOP_UPGRADES_EXCLUDED",
                "GANGPLANK_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose barrel and Cannon Barrage movement-control windows.

        :param context: Role-bound Gangplank and opponent snapshots.
        :return: Causal slow windows plus citrus-cleanse limitations.
        """
        return ReactionPlan(
            "gangplank_e5_r2_slow_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "gangplank_e_powder_keg_slow",
                    self._BARREL_AT_MS,
                    min(self._BARREL_AT_MS + self._BARREL_SLOW_MS, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "GANGPLANK_E_Q_POWDER_KEG_DETONATION",
                    True,
                    ControlType.SLOW,
                ),
                CastBlockWindow(
                    "gangplank_r_center_zone_repeated_slow",
                    self._R_FIRST_WAVE_MS,
                    min(8000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "GANGPLANK_R_CANNON_BARRAGE_WAVE_1",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=(
                "GANGPLANK_R_TARGET_REMAINS_IN_ZONE_ASSUMED",
                "GANGPLANK_W_CLEANSE_CASTABILITY_DURING_CONTROL_NOT_FULLY_MODELED",
            ),
        )
