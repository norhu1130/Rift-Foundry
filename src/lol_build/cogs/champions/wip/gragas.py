"""Gragas combat Cog backed by the locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, DamageModifierWindow, StatusOutput


class GragasCog(ChampionCog):
    """Model Gragas's Q5/E5/W1/R2 level-13 charged-barrel fixture.

    The fixture deploys Barrel Roll at the start and detonates it after the
    locked two-second maximum-charge time. Drunken Rage then supplies its
    short damage-reduction window and one blind-susceptible empowered attack,
    while Body Slam and Explosive Cask expose role-neutral control. Terrain,
    displacement geometry, multiple targets, and exact passive availability
    remain explicit blockers instead of being inferred from tooltip prose.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Gragas.json",
        "data/raw/16.17.1/communitydragon/champions/79.json",
        "data/raw/16.17.1/communitydragon/champions/gragas.bin.json",
    )

    _Q_FIRST_CAST_MS = 0
    _Q_CHARGE_MS = 2000
    _W_CAST_MS = 100
    _W_COMPLETE_MS = 850
    _E_HIT_MS = 1500
    _W_ATTACK_MS = 2100
    _R_HIT_MS = 2400

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Body Slam's Data Dragon dash range for approach scoring.

        :param context: Role-bound Gragas encounter context.
        :return: Body Slam range in game units.
        """
        return Decimal(600)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats absent from Gragas's fixed event model.

        AP, AD, attack speed, haste, and health reach represented outputs.
        Resistances remain valid through the shared snapshot and EHP model.

        :param item: Normalized candidate from the locked item catalog.
        :return: Gragas-scoped blocker for unsupported stats, otherwise ``None``.
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
            return f"GRAGAS_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    @staticmethod
    def _q_cooldown_ms(ability_haste: Decimal) -> int:
        """Apply ability haste to Q5's locked six-second cooldown.

        :param ability_haste: Non-negative haste from Gragas's snapshot.
        :return: Cooldown rounded upward to a deterministic millisecond.
        """
        haste = max(Decimal(0), ability_haste)
        return int(
            (Decimal(6000) * Decimal(100) / (Decimal(100) + haste)).to_integral_value(ROUND_CEILING)
        )

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule maximally charged Q5 casts and detonations within the duel.

        Only the opening cast contains Happy Hour healing because the locked
        passive data does not by itself prove subsequent proc availability.

        :param context: Snapshot supplying AP, haste, health, duration, and roles.
        :return: Chronological barrel deployment and charged explosion events.
        """
        cooldown_ms = self._q_cooldown_ms(context.snapshot.ability_haste)
        charged_damage = (
            Decimal(240) + Decimal("0.80") * context.snapshot.ability_power
        ) * Decimal("1.50")
        passive_heal = Decimal("0.055") * context.snapshot.max_hp
        base = self._sequence_base(context)
        events: list[ActionEvent] = []
        cast_at_ms = self._Q_FIRST_CAST_MS
        while cast_at_ms <= context.duration_ms:
            index = len(events) // 2 + 1
            cast_outputs = [
                StatusOutput(context.self_entity, "GRAGAS_Q_BARREL_ACTIVE", self._Q_CHARGE_MS)
            ]
            if index == 1:
                cast_outputs.append(healing(context.self_entity, passive_heal))
            events.append(
                action(
                    f"GRAGAS_Q_BARREL_ROLL_CAST_{index}",
                    at_ms=cast_at_ms,
                    sequence=base + index * 2 - 2,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=tuple(cast_outputs),
                    requires_living_opponent=False,
                )
            )
            explosion_at_ms = cast_at_ms + self._Q_CHARGE_MS
            if explosion_at_ms <= context.duration_ms:
                events.append(
                    action(
                        f"GRAGAS_Q_BARREL_ROLL_MAX_CHARGE_{index}",
                        at_ms=explosion_at_ms,
                        sequence=base + index * 2 - 1,
                        source=context.self_entity,
                        channel=ActionChannel.ABILITY,
                        outputs=(
                            damage(context.opponent_entity, charged_damage, DamageType.MAGIC),
                            crowd_control(
                                context.opponent_entity,
                                "SLOW",
                                duration_ms=2000,
                                magnitude=Decimal("0.90"),
                            ),
                        ),
                    )
                )
            cast_at_ms += cooldown_ms
        return tuple(events)

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule the empowered W attack and later ordinary attacks.

        :param context: Snapshot supplying total AD, AP, attack speed, and target HP.
        :return: Blind-susceptible physical attacks with W magic damage on the first.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        empowered_magic = (
            Decimal(20)
            + Decimal("0.70") * context.snapshot.ability_power
            + Decimal("0.07") * context.opponent_snapshot.max_hp
        )
        base = self._sequence_base(context) + 200
        events = [
            action(
                "GRAGAS_W_DRUNKEN_RAGE_EMPOWERED_ATTACK",
                at_ms=self._W_ATTACK_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity,
                        context.snapshot.attack_damage,
                        DamageType.PHYSICAL,
                    ),
                    damage(context.opponent_entity, empowered_magic, DamageType.MAGIC),
                ),
            )
        ]
        at_ms = self._W_ATTACK_MS + interval_ms
        while at_ms <= context.duration_ms:
            index = len(events)
            events.append(
                action(
                    f"GRAGAS_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
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
        """Build Gragas's locked charged-Q single-target combat sequence.

        :param context: Role-bound Gragas and opponent combat snapshots.
        :return: Deterministic Q, W, E, R, passive-heal, and attack events.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        fixed_events = (
            action(
                "GRAGAS_W_DRUNKEN_RAGE_CAST",
                at_ms=self._W_CAST_MS,
                sequence=base + 100,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(
                        context.self_entity,
                        "GRAGAS_W_DRINKING",
                        self._W_COMPLETE_MS - self._W_CAST_MS,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "GRAGAS_W_DRUNKEN_RAGE_READY",
                at_ms=self._W_COMPLETE_MS,
                sequence=base + 101,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(StatusOutput(context.self_entity, "GRAGAS_W_EMPOWERED", 5000),),
                requires_living_opponent=False,
            ),
            action(
                "GRAGAS_E_BODY_SLAM",
                at_ms=self._E_HIT_MS,
                sequence=base + 102,
                source=context.self_entity,
                channel=ActionChannel.MOVEMENT,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(260) + Decimal("0.60") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=1000),
                ),
            ),
            action(
                "GRAGAS_R_EXPLOSIVE_CASK",
                at_ms=self._R_HIT_MS,
                sequence=base + 103,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(300) + Decimal("0.80") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=500),
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"GRAGAS_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "gragas_q5_e5_w1_r2_level13_max_charge_v1",
            tuple(
                sorted(
                    (*self._q_events(context), *fixed_events, *self._basic_attacks(context)),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "GRAGAS_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "GRAGAS_ROTATION_TIMING_UNVERIFIED",
                "GRAGAS_PASSIVE_COOLDOWN_EXACTNESS_AND_REPEAT_PROCS_NOT_MODELED",
                "GRAGAS_Q_MAX_CHARGE_HIT_ASSUMED",
                "GRAGAS_Q_CHARGE_SCALING_AND_EARLY_RECASTS_NOT_MODELED",
                "GRAGAS_Q_PROJECTILE_POSITION_AND_MULTI_TARGET_NOT_MODELED",
                "GRAGAS_W_CHANNEL_INTERRUPTION_NOT_MODELED",
                "GRAGAS_W_ATTACK_RESET_TIMING_UNVERIFIED",
                "GRAGAS_W_DAMAGE_REDUCTION_CAP_UNVERIFIED",
                "GRAGAS_E_COLLISION_TERRAIN_AND_MULTI_TARGET_NOT_MODELED",
                "GRAGAS_E_COOLDOWN_REFUND_NOT_MODELED",
                "GRAGAS_R_PROJECTILE_DISPLACEMENT_GEOMETRY_NOT_MODELED",
                "GRAGAS_R_MULTI_TARGET_NOT_MODELED",
                "GRAGAS_RESOURCE_COSTS_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose W mitigation and Q, E, and R control windows.

        :param context: Role-bound snapshots supplying AP, haste, duration, and roles.
        :return: Source-linked damage reduction, slow, stun, and knockback windows.
        """
        reduction = Decimal("0.10") + Decimal("0.0004") * context.snapshot.ability_power
        damage_multiplier = max(Decimal(0), Decimal(1) - reduction)
        q_windows: list[CastBlockWindow] = []
        cooldown_ms = self._q_cooldown_ms(context.snapshot.ability_haste)
        cast_at_ms = self._Q_FIRST_CAST_MS
        index = 1
        while cast_at_ms + self._Q_CHARGE_MS <= context.duration_ms:
            explosion_at_ms = cast_at_ms + self._Q_CHARGE_MS
            q_windows.append(
                CastBlockWindow(
                    f"gragas_q_max_charge_slow_{index}",
                    explosion_at_ms,
                    min(explosion_at_ms + 2000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    f"GRAGAS_Q_BARREL_ROLL_MAX_CHARGE_{index}",
                    True,
                    ControlType.SLOW,
                )
            )
            cast_at_ms += cooldown_ms
            index += 1
        return ReactionPlan(
            "gragas_q5_e5_w1_r2_reaction_v1",
            damage_windows=(
                DamageModifierWindow(
                    "gragas_w_damage_reduction",
                    self._W_COMPLETE_MS,
                    min(self._W_COMPLETE_MS + 2500, context.duration_ms),
                    context.self_entity,
                    (DamageType.PHYSICAL, DamageType.MAGIC),
                    damage_multiplier,
                ),
            ),
            cast_block_windows=(
                *q_windows,
                CastBlockWindow(
                    "gragas_e_stun",
                    self._E_HIT_MS,
                    min(self._E_HIT_MS + 1000, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                        ActionChannel.ITEM_ACTIVE,
                    ),
                    "GRAGAS_E_BODY_SLAM",
                    True,
                    ControlType.STUN,
                ),
                CastBlockWindow(
                    "gragas_r_knockback",
                    self._R_HIT_MS,
                    min(self._R_HIT_MS + 500, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                        ActionChannel.ITEM_ACTIVE,
                    ),
                    "GRAGAS_R_EXPLOSIVE_CASK",
                    False,
                    ControlType.AIRBORNE,
                ),
            ),
            blockers=(
                "GRAGAS_W_DAMAGE_REDUCTION_CAP_UNVERIFIED",
                "GRAGAS_Q_MAX_CHARGE_HIT_ASSUMED",
                "GRAGAS_E_STUN_TIMING_UNVERIFIED",
                "GRAGAS_R_KNOCKBACK_DURATION_AND_DIRECTION_UNVERIFIED",
                "GRAGAS_CONTROL_MULTI_TARGET_NOT_MODELED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Decline to extrapolate Happy Hour without a cast and cooldown trace.

        The duel plan still exposes one locked 5.5%-maximum-health proc. Lane
        sustain needs a spell schedule, mana state, missing-health trace, and a
        verified level-13 passive cooldown before repeat healing is defensible.

        :param context: Role-bound Gragas lane snapshot.
        :param duration_ms: Lane observation duration in milliseconds.
        :param no_damage_delay_ms: Required out-of-combat recovery delay.
        :return: Zero extrapolated recovery and exact unresolved-state blockers.
        """
        return Decimal(0), (
            "GRAGAS_LANE_SPELL_AND_MANA_SCHEDULE_NOT_MODELED",
            "GRAGAS_PASSIVE_COOLDOWN_EXACTNESS_UNVERIFIED",
            "GRAGAS_LANE_MISSING_HEALTH_TRACE_NOT_MODELED",
        )
