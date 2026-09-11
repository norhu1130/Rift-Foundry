"""Graves combat Cog backed by the locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    ChampionCog,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    StatModifierOutput,
    StatusOutput,
)


class GravesCog(ChampionCog):
    """Model Graves's Q5/W1/E5/R2 level-13 single-target fixture.

    The fixture begins with two shells, uses Quickdraw once to load one more,
    and then applies a fixed two-second reload after each later pair. Every
    assumed close-range attack exposes four separate pellet outputs. Geometry,
    collision, dynamic ammunition, and exact reload scaling remain blockers.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Graves.json",
        "data/raw/16.17.1/communitydragon/champions/104.json",
        "data/raw/16.17.1/communitydragon/champions/graves.bin.json",
    )

    _LEVEL_13_SINGLE_PELLET_AD_RATIO = Decimal("0.8879742622375488")
    _SECONDARY_PELLET_RATIO = Decimal("0.3330000042915344")
    _EXPECTED_CRIT_BONUS = Decimal("0.375")
    _FIXED_RELOAD_MS = 2000

    @staticmethod
    def _cooldown_ms(base_ms: int, ability_haste: Decimal) -> int:
        """Apply standard ability haste to one locked base cooldown.

        :param base_ms: Rank-specific base cooldown in milliseconds.
        :param ability_haste: Non-negative haste on Graves's snapshot.
        :return: Deterministically rounded effective cooldown in milliseconds.
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

    @classmethod
    def _pellet_amounts(cls, context: ParticipantContext) -> tuple[Decimal, ...]:
        """Calculate four assumed-hit shotgun pellets for one normal attack.

        The locked passive supplies the level-13 first-pellet AD ratio and a
        0.333 multiplier for each additional pellet. Critical chance is folded
        into a deterministic expected first-pellet multiplier; critical pellet
        count and spread remain explicitly outside this fixture.

        :param context: Graves snapshot supplying total AD and critical chance.
        :return: First-pellet damage followed by three secondary-pellet amounts.
        """
        expected_crit = Decimal(1) + (
            context.snapshot.critical_strike_chance * cls._EXPECTED_CRIT_BONUS
        )
        first = (
            context.snapshot.attack_damage * cls._LEVEL_13_SINGLE_PELLET_AD_RATIO * expected_crit
        )
        secondary = first * cls._SECONDARY_PELLET_RATIO
        return (first, secondary, secondary, secondary)

    @classmethod
    def _attack_times(cls, context: ParticipantContext) -> tuple[int, ...]:
        """Schedule a fixed two-shell magazine with one Quickdraw reload.

        Quickdraw is assumed to restore one shell before the ordinary second
        shot, producing three shots in the first magazine. Later magazines hold
        two shells and use the fixture's fixed reload delay.

        :param context: Graves snapshot supplying attack speed and duration.
        :return: Ordered attack timestamps inside the encounter horizon.
        """
        interval_ms = cls._attack_interval_ms(context.snapshot.attack_speed)
        attack_times: list[int] = []
        at_ms = 500
        shells = 3
        while at_ms <= context.duration_ms:
            attack_times.append(at_ms)
            shells -= 1
            if shells == 0:
                at_ms += cls._FIXED_RELOAD_MS
                shells = 2
            else:
                at_ms += interval_ms
        return tuple(attack_times)

    @classmethod
    def _attack_events(cls, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Create pellet-separated attacks on the blindable attack channel.

        :param context: Role-bound Graves encounter context.
        :return: Fixed-ammunition attack events with four physical outputs each.
        """
        base = cls._sequence_base(context) + 300
        amounts = cls._pellet_amounts(context)
        return tuple(
            action(
                f"GRAVES_NEW_DESTINY_ATTACK_{index}",
                at_ms=at_ms,
                sequence=base + index,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=tuple(
                    damage(context.opponent_entity, amount, DamageType.PHYSICAL)
                    for amount in amounts
                ),
            )
            for index, at_ms in enumerate(cls._attack_times(context), start=1)
        )

    @classmethod
    def _q_events(cls, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule rank-five outbound shells and delayed explosions.

        :param context: Graves snapshot supplying bonus AD, haste, and duration.
        :return: Assumed-hit Q outbound and one-second detonation events.
        """
        cooldown_ms = cls._cooldown_ms(6000, context.snapshot.ability_haste)
        outbound = Decimal(150) + Decimal("0.55") * context.snapshot.bonus_attack_damage
        explosion = Decimal(260) + Decimal("1.05") * context.snapshot.bonus_attack_damage
        base = cls._sequence_base(context) + 100
        events: list[ActionEvent] = []
        cast_ms = 200
        cast_number = 1
        while cast_ms <= context.duration_ms:
            events.append(
                action(
                    f"GRAVES_Q_END_OF_THE_LINE_OUTBOUND_{cast_number}",
                    at_ms=cast_ms,
                    sequence=base + cast_number * 2,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, outbound, DamageType.PHYSICAL),),
                )
            )
            if cast_ms + 1000 <= context.duration_ms:
                events.append(
                    action(
                        f"GRAVES_Q_END_OF_THE_LINE_EXPLOSION_{cast_number}",
                        at_ms=cast_ms + 1000,
                        sequence=base + cast_number * 2 + 1,
                        source=context.self_entity,
                        channel=ActionChannel.PASSIVE,
                        outputs=(damage(context.opponent_entity, explosion, DamageType.PHYSICAL),),
                    )
                )
            cast_ms += cooldown_ms
            cast_number += 1
        return tuple(events)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Quickdraw's locked maximum displacement for engagement.

        :param context: Role-bound Graves encounter context.
        :return: Three-hundred-seventy-five-unit maximum dash distance.
        """
        return Decimal(375)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stat channels absent from Graves's fixed fixture.

        AD, AP, attack speed, critical chance, haste, penetration, movement,
        health, and resistances reach modeled outputs or shared calculations.
        Resource expenditure and generic healing attribution remain unresolved.

        :param item: Normalized candidate from the locked item catalog.
        :return: Graves-scoped blocker for unsupported stats, otherwise ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"GRAVES_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked Q5/W1/E5/R2 level-13 Graves sequence.

        The model assumes E points toward the opponent and therefore grants two
        True Grit stacks. R applies only its first-target damage; its backward
        recoil is preserved as a status rather than mislabeled as engagement.

        :param context: Role-bound Graves and opponent combat snapshots.
        :return: Chronological attack, spell, movement, and resistance events.
        """
        base = self._sequence_base(context)
        w_damage = Decimal(60) + Decimal("0.60") * context.snapshot.ability_power
        r_damage = Decimal(425) + Decimal("1.50") * context.snapshot.bonus_attack_damage
        fixed_events = (
            action(
                "GRAVES_E_QUICKDRAW_RELOAD",
                at_ms=100,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.MOVEMENT,
                outputs=(
                    StatusOutput(context.self_entity, "GRAVES_E_RELOADED_ONE_SHELL", 1),
                    StatModifierOutput(context.self_entity, "ARMOR", Decimal(38), 4000),
                    StatModifierOutput(context.self_entity, "MAGIC_RESISTANCE", Decimal(19), 4000),
                ),
                requires_living_opponent=False,
            ),
            action(
                "GRAVES_W_SMOKE_SCREEN_IMPACT",
                at_ms=300,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, w_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=500,
                        magnitude=Decimal("0.50"),
                    ),
                    StatusOutput(context.opponent_entity, "GRAVES_SMOKE_SCREEN_VISION", 4000),
                ),
            ),
            action(
                "GRAVES_R_COLLATERAL_DAMAGE",
                at_ms=6500,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.PHYSICAL),
                    StatusOutput(context.self_entity, "GRAVES_R_BACKWARD_RECOIL", 1),
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"GRAVES_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        events = (*fixed_events, *self._q_events(context), *self._attack_events(context))
        return ActionPlan(
            "graves_q5_w1_e5_r2_level13_fixed_ammo_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "GRAVES_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "GRAVES_ROTATION_AND_ANIMATION_TIMING_UNVERIFIED",
                "GRAVES_INITIAL_AMMO_TWO_AND_E_RELOAD_TIMING_ASSUMED",
                "GRAVES_FIXED_RELOAD_DURATION_NOT_PRESENT_IN_LOCKED_SOURCES",
                "GRAVES_DYNAMIC_AMMO_AND_E_ATTACK_COOLDOWN_REFUND_NOT_MODELED",
                "GRAVES_PELLET_GEOMETRY_AND_DISTANCE_FALLOFF_NOT_MODELED",
                "GRAVES_PROJECTILE_UNIT_AND_WALL_COLLISION_NOT_MODELED",
                "GRAVES_CRITICAL_PELLET_COUNT_AND_SPREAD_NOT_MODELED",
                "GRAVES_Q_OUTBOUND_AND_DELAYED_EXPLOSION_BOTH_ASSUMED_TO_HIT",
                "GRAVES_Q_TERRAIN_COLLISION_DELAY_NOT_MODELED",
                "GRAVES_E_DIRECTION_TOWARD_CHAMPION_ASSUMED_TWO_STACKS",
                "GRAVES_R_CONE_AND_MULTI_TARGET_DAMAGE_NOT_MODELED",
                "GRAVES_R_RECOIL_POSITION_NOT_CAUSALLY_MODELED",
                "GRAVES_W_VISION_DENIAL_NOT_CAUSALLY_MODELED",
                "GRAVES_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose unresolved smoke and reactive-dash policy without invention.

        :param context: Role-bound Graves and opponent combat snapshots.
        :return: Neutral reaction plan with explicit positional limitations.
        """
        return ReactionPlan(
            "graves_smoke_and_quickdraw_reaction_v1",
            blockers=(
                "GRAVES_W_VISION_DENIAL_ACTION_SELECTION_NOT_MODELED",
                "GRAVES_E_REACTIVE_DASH_POLICY_NOT_MODELED",
                "GRAVES_R_REACTIVE_RECOIL_POLICY_NOT_MODELED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Report that Graves's locked kit supplies no native lane healing.

        :param context: Role-bound Graves encounter context.
        :param duration_ms: Lane observation duration in milliseconds.
        :param no_damage_delay_ms: Delay before recovery may begin.
        :return: Zero champion-native recovery without extra blockers.
        """
        return Decimal(0), ()
