"""Galio combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    DamageModifierWindow,
    StatusOutput,
)


class GalioCog(ChampionCog):
    """Model Galio's Q5/W5/E1/R2 level-13 fixed ally-anchor fixture.

    Hero's Entrance assumes that an unmodeled allied anchor is already beside
    the hostile duel participant. The two-participant timeline can therefore
    resolve Galio's landing against the opponent, but it deliberately does not
    grant the ally-only magic shield to Galio or to that opponent.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Galio.json",
        "data/raw/16.17.1/communitydragon/champions/3.json",
        "data/raw/16.17.1/communitydragon/champions/galio.bin.json",
    )

    @staticmethod
    def _cooldown_ms(base_seconds: Decimal, ability_haste: Decimal) -> int:
        """Convert one base cooldown through the shared haste convention.

        :param base_seconds: Cooldown before ability haste, in seconds.
        :param ability_haste: Non-negative ability haste from the snapshot.
        :return: Deterministically rounded cooldown in milliseconds.
        :raises ValueError: If ability haste is below zero.
        """
        if ability_haste < 0:
            raise ValueError("ability_haste must be non-negative")
        milliseconds = base_seconds * Decimal(100_000) / (Decimal(100) + ability_haste)
        return max(1, int(milliseconds.to_integral_value(ROUND_HALF_EVEN)))

    def _bonus_magic_resistance(self, context: ParticipantContext) -> Decimal:
        """Recover item-granted MR without mistaking level growth for bonus MR.

        :param context: Role-bound Galio snapshot and its locked level.
        :return: Non-negative magic resistance above Galio's native value.
        """
        native = self.snapshot(level=context.snapshot.level).magic_resistance
        return max(Decimal(0), context.snapshot.magic_resistance - native)

    def _passive_magic_damage(self, context: ParticipantContext) -> Decimal:
        """Calculate Colossal Smash's bonus magic damage at the fixture level.

        :param context: Galio snapshot supplying level, AP, and bonus MR.
        :return: Raw bonus magic damage for one empowered attack.
        """
        level_fraction = Decimal(context.snapshot.level - 1) / Decimal(17)
        level_damage = Decimal(15) + Decimal(100) * level_fraction
        return (
            level_damage
            + Decimal("0.40") * context.snapshot.ability_power
            + Decimal("0.60") * self._bonus_magic_resistance(context)
        )

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Q missile hits and four deterministic tornado ticks per cast.

        :param context: Galio and opponent snapshots used by Q formulas.
        :return: Chronological Winds of War events inside the benchmark.
        """
        ap = context.snapshot.ability_power
        missile_damage = Decimal(210) + Decimal("0.70") * ap
        tick_damage = context.opponent_snapshot.max_hp * (Decimal("0.02") + Decimal("0.0001") * ap)
        cooldown_ms = self._cooldown_ms(Decimal(7), context.snapshot.ability_haste)
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        cast_ms = 3350
        cast_index = 1
        while cast_ms <= context.duration_ms:
            events.append(
                action(
                    f"GALIO_Q_WINDS_OF_WAR_{cast_index}",
                    at_ms=cast_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, missile_damage, DamageType.MAGIC),),
                )
            )
            for tick_index, offset_ms in enumerate((500, 1000, 1500, 2000), start=1):
                tick_ms = cast_ms + offset_ms
                if tick_ms > context.duration_ms:
                    break
                events.append(
                    action(
                        f"GALIO_Q_TORNADO_{cast_index}_TICK_{tick_index}",
                        at_ms=tick_ms,
                        sequence=base + len(events),
                        source=context.self_entity,
                        channel=ActionChannel.PASSIVE,
                        outputs=(damage(context.opponent_entity, tick_damage, DamageType.MAGIC),),
                    )
                )
            cast_index += 1
            cast_ms += cooldown_ms
        return tuple(events)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Avoid inventing pursuit speed from charge slows or ally teleports.

        :param context: Role-bound Galio encounter context.
        :return: Neutral movement-speed multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Justice Punch's locked display range as direct engagement.

        :param context: Role-bound Galio encounter context.
        :return: E's maximum displayed dash range in game units.
        """
        return Decimal(650)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Galio's fixed action model.

        :param item: Normalized candidate item from the locked catalog.
        :return: Galio-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"GALIO_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the fixed R landing, E, Q, full-charge W, and attack sequence.

        :param context: Role-bound Galio and opponent snapshots.
        :return: Deterministic ability and basic-attack events with blockers.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        bonus_mr = self._bonus_magic_resistance(context)
        r_damage = Decimal(250) + Decimal("0.70") * ap + bonus_mr
        e_damage = Decimal(100) + ap
        w_damage = Decimal(180) + Decimal("0.90") * ap
        events: list[ActionEvent] = [
            action(
                "GALIO_R_HEROS_ENTRANCE_LANDING",
                at_ms=2750,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=750),
                ),
            ),
            action(
                "GALIO_E_JUSTICE_PUNCH",
                at_ms=3200,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=750),
                ),
            ),
            action(
                "GALIO_W_SHIELD_OF_DURAND_START",
                at_ms=4500,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "GALIO_W_CHANNELING", 2000),),
                requires_living_opponent=False,
            ),
            action(
                "GALIO_W_SHIELD_OF_DURAND_FULL_RELEASE",
                at_ms=6500,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, w_damage, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "TAUNT", duration_ms=1500),
                ),
            ),
            action(
                "GALIO_PASSIVE_COLOSSAL_SMASH",
                at_ms=6800,
                sequence=base + 4,
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
                        self._passive_magic_damage(context),
                        DamageType.MAGIC,
                    ),
                ),
            ),
        ]
        events.extend(self._q_events(context))
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        for index, at_ms in enumerate(range(7000, context.duration_ms + 1, interval_ms), start=1):
            events.append(
                action(
                    f"GALIO_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 300 + index,
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
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"GALIO_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "galio_q5_w5_e1_r2_level13_ally_anchor_fixture_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            (
                *level_blockers,
                "GALIO_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "GALIO_ROTATION_TIMING_UNVERIFIED",
                "GALIO_R_ALLIED_ANCHOR_POSITION_ASSUMED",
                "GALIO_R_ALLY_MAGIC_SHIELD_OUTSIDE_TWO_PARTICIPANT_MODEL",
                "GALIO_R_GLOBAL_GEOMETRY_AND_CHANNEL_INTERRUPTION_NOT_MODELED",
                "GALIO_Q_PROJECTILE_CONVERGENCE_AND_TARGET_STAY_ASSUMED",
                "GALIO_Q_TORNADO_TICK_PHASE_UNVERIFIED",
                "GALIO_W_FULL_CHARGE_AND_TARGET_PROXIMITY_ASSUMED",
                "GALIO_PASSIVE_SPLASH_EXCLUDED_SINGLE_TARGET_BENCHMARK",
                "GALIO_PASSIVE_ABILITY_HIT_COOLDOWN_REFUNDS_NOT_MODELED",
                "GALIO_RESOURCE_COSTS_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose W defenses, W passive shield, taunt, and airborne windows.

        :param context: Role-bound snapshots for the Galio participant.
        :return: Causally linked defense and opponent-control windows.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        bonus_mr = self._bonus_magic_resistance(context)
        magic_reduction = (
            Decimal("0.45")
            + Decimal("0.0004") * ap
            + Decimal("0.0008") * bonus_mr
            + Decimal("0.0001") * context.snapshot.bonus_health
        )
        magic_multiplier = max(Decimal(0), Decimal(1) - magic_reduction)
        physical_multiplier = Decimal(1) - magic_reduction * Decimal("0.50")
        shield_amount = Decimal("0.135") * context.snapshot.max_hp
        return ReactionPlan(
            "galio_w5_r2_defense_and_control_v1",
            events=(
                action(
                    "GALIO_W_PASSIVE_MAGIC_SHIELD_READY",
                    at_ms=0,
                    sequence=base + 900,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(
                        shielding(
                            context.self_entity,
                            shield_amount,
                            damage_types=(DamageType.MAGIC,),
                        ),
                    ),
                    requires_living_opponent=False,
                ),
            ),
            damage_windows=(
                DamageModifierWindow(
                    "galio_w_magic_damage_reduction",
                    4500,
                    min(8000, context.duration_ms),
                    context.self_entity,
                    (DamageType.MAGIC,),
                    magic_multiplier,
                ),
                DamageModifierWindow(
                    "galio_w_physical_damage_reduction",
                    4500,
                    min(8000, context.duration_ms),
                    context.self_entity,
                    (DamageType.PHYSICAL,),
                    physical_multiplier,
                ),
            ),
            cast_block_windows=(
                CastBlockWindow(
                    "galio_r_outer_knockup",
                    2750,
                    min(3500, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "GALIO_R_HEROS_ENTRANCE_LANDING",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "galio_e_knockup",
                    3200,
                    min(3950, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "GALIO_E_JUSTICE_PUNCH",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "galio_w_full_charge_taunt",
                    6500,
                    min(8000, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "GALIO_W_SHIELD_OF_DURAND_FULL_RELEASE",
                    True,
                    ControlType.TAUNT,
                ),
            ),
            blockers=(
                "GALIO_W_PASSIVE_ASSUMES_READY_AT_BENCHMARK_START",
                "GALIO_W_PASSIVE_RECHARGE_AFTER_DAMAGE_NOT_MODELED",
                "GALIO_W_CHARGE_INTERRUPTION_AND_SELF_SLOW_NOT_MODELED",
                "GALIO_W_DAMAGE_REDUCTION_CAP_UNVERIFIED",
                "GALIO_R_OUTER_KNOCKUP_VARIANT_ASSUMED",
            ),
        )
