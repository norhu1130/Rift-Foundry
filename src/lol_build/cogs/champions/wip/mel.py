"""Mel combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, movement_speed, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class MelCog(ChampionCog):
    """Model Mel's W1/E5/Q5/R2 level-13 duel fixture.

    The timeline lands E's center and four area ticks, then all ten Q
    explosions before R consumes fifteen Overwhelm stacks. W contributes its
    locked shield and movement boost. Reflection remains missing because a
    hostile event does not yet identify whether it is a reflectable projectile.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Mel.json",
        "data/raw/16.17.1/communitydragon/champions/800.json",
        "data/raw/16.17.1/communitydragon/champions/mel.bin.json",
    )

    _W_AT_MS = 0
    _E_AT_MS = 250
    _Q_AT_MS = 800
    _R_AT_MS = 1500
    _FIRST_ATTACK_AT_MS = 1800

    @staticmethod
    def _cooldown_ms(base_ms: int, haste: Decimal) -> int:
        """Apply non-negative ability haste to a locked cooldown.

        :param base_ms: Unmodified cooldown in milliseconds.
        :param haste: Ability haste supplied by the current snapshot.
        :return: Positive truncated cooldown in milliseconds.
        :raises ValueError: If ability haste is negative.
        """
        if haste < 0:
            raise ValueError("haste must be non-negative")
        return max(1, int(Decimal(base_ms) * Decimal(100) / (Decimal(100) + haste)))

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule every Q5 explosion for each available cast.

        :param context: Snapshot supplying AP, haste, roles, and duration.
        :return: Individually cancellable Radiant Volley explosion events.
        """
        ap = context.snapshot.ability_power
        first = Decimal(160) + Decimal("0.55") * ap
        subsequent = Decimal(13) + Decimal("0.05") * ap
        interval = self._cooldown_ms(6000, context.snapshot.ability_haste)
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        cast_at = self._Q_AT_MS
        cast_index = 1
        while cast_at <= context.duration_ms:
            for hit_index in range(10):
                at_ms = cast_at + hit_index * 50
                if at_ms > context.duration_ms:
                    break
                events.append(
                    action(
                        f"MEL_Q_RADIANT_VOLLEY_{cast_index}_{hit_index + 1}",
                        at_ms=at_ms,
                        sequence=base + cast_index * 20 + hit_index,
                        source=context.self_entity,
                        channel=ActionChannel.ABILITY,
                        outputs=(
                            damage(
                                context.opponent_entity,
                                first if hit_index == 0 else subsequent,
                                DamageType.MAGIC,
                            ),
                        ),
                    )
                )
            cast_at += interval
            cast_index += 1
        return tuple(events)

    def _e_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build E5's center impact and four locked area ticks.

        :param context: Snapshot supplying AP, roles, and duration.
        :return: Center hit followed by half-second Solar Snare area damage.
        """
        ap = context.snapshot.ability_power
        center = Decimal(240) + Decimal("0.70") * ap
        tick = (Decimal(64) + Decimal("0.08") * ap) / Decimal(8)
        base = self._sequence_base(context) + 20
        events = [
            action(
                "MEL_E_SOLAR_SNARE_CENTER",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, center, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "ROOT", duration_ms=1500),
                ),
            )
        ]
        for index in range(1, 5):
            at_ms = self._E_AT_MS + index * 125
            if at_ms > context.duration_ms:
                break
            events.append(
                action(
                    f"MEL_E_SOLAR_SNARE_AREA_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(damage(context.opponent_entity, tick, DamageType.MAGIC),),
                )
            )
        return tuple(events)

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks and consume nine stored passive missiles once.

        :param context: Snapshot supplying level, AD, AP, speed, and duration.
        :return: First enhanced attack followed by ordinary basic attacks.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        level_fraction = Decimal(context.snapshot.level - 1) / Decimal(17)
        missile = (
            Decimal(8)
            + Decimal(22) * level_fraction
            + Decimal("0.04") * context.snapshot.ability_power
        )
        base = self._sequence_base(context) + 500
        events: list[ActionEvent] = []
        for index, at_ms in enumerate(
            range(self._FIRST_ATTACK_AT_MS, context.duration_ms + 1, interval), start=1
        ):
            outputs = [
                damage(
                    context.opponent_entity,
                    context.snapshot.attack_damage,
                    DamageType.PHYSICAL,
                )
            ]
            if index == 1:
                outputs.append(
                    damage(context.opponent_entity, Decimal(9) * missile, DamageType.MAGIC)
                )
            events.append(
                action(
                    f"MEL_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
        return tuple(events)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose W1's locked forty-percent decaying movement boost.

        :param context: Role-bound Mel encounter context.
        :return: Initial W movement-speed multiplier.
        """
        return Decimal("1.40")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return zero because Mel has no displacement ability.

        :param context: Role-bound Mel encounter context.
        :return: Zero dash distance.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the selected spell fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Mel-scoped blocker, or ``None`` for represented channels.
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
            return f"MEL_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build W, E, Q, R, and passive-enhanced attacks.

        :param context: Role-bound Mel and opponent snapshots.
        :return: Deterministic level-13 action schedule.
        """
        ap = context.snapshot.ability_power
        base = self._sequence_base(context)
        shield = Decimal(80) + Decimal("0.70") * ap
        r_damage = (
            Decimal(200) + Decimal("0.30") * ap + Decimal(15) * (Decimal(7) + Decimal("0.04") * ap)
        )
        fixed = (
            action(
                "MEL_W_REBUTTAL",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(context.self_entity, shield, duration_ms=750),
                    movement_speed(
                        context.self_entity,
                        Decimal("0.40") * context.snapshot.move_speed,
                        duration_ms=750,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "MEL_R_GOLDEN_ECLIPSE_FIFTEEN_STACKS",
                at_ms=self._R_AT_MS,
                sequence=base + 300,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, r_damage, DamageType.MAGIC),),
            ),
        )
        events = (
            *fixed,
            *self._e_events(context),
            *self._q_events(context),
            *self._attack_events(context),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"MEL_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "mel_q5_e5_w1_r2_fifteen_stack_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "MEL_LEVEL13_Q5_E5_W1_R2_ORDER_LOCKED_UNVERIFIED",
                "MEL_E_CENTER_AND_ALL_FOUR_AREA_TICKS_HIT_ASSUMED",
                "MEL_Q_ALL_TEN_EXPLOSIONS_HIT_ASSUMED",
                "MEL_R_FIFTEEN_OVERWHELM_STACKS_FROM_E_AND_Q_ASSUMED",
                "MEL_PASSIVE_FIRST_ATTACK_CONSUMES_NINE_STORED_MISSILES_ASSUMED",
                "MEL_PASSIVE_EXECUTE_THRESHOLD_NOT_CAUSALLY_MODELED",
                "MEL_W_PROJECTILE_REFLECTION_REQUIRES_PROJECTILE_METADATA",
                "MEL_W_DECAYING_MOVE_SPEED_APPROXIMATED_AS_FLAT_WINDOW",
                "MEL_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose E root and area slow without inventing universal W immunity.

        :param context: Role-bound Mel and opponent snapshots.
        :return: Movement-control windows plus reflection blockers.
        """
        return ReactionPlan(
            "mel_e_root_area_slow_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "mel_e_solar_snare_root",
                    self._E_AT_MS,
                    min(self._E_AT_MS + 1500, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "MEL_E_SOLAR_SNARE_CENTER",
                    True,
                    ControlType.ROOT,
                ),
                CastBlockWindow(
                    "mel_e_solar_snare_slow",
                    self._E_AT_MS,
                    min(self._E_AT_MS + 750, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "MEL_E_SOLAR_SNARE_CENTER",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=(
                "MEL_E_AREA_SLOW_RESIDENCE_750MS_ASSUMED",
                "MEL_MOVEMENT_SLOW_MAGNITUDE_NOT_INTEGRATED_IN_TIMELINE",
                "MEL_W_PROJECTILE_REFLECTION_REQUIRES_PROJECTILE_METADATA",
                "MEL_W_DOES_NOT_GRANT_GENERIC_DAMAGE_IMMUNITY",
            ),
        )
