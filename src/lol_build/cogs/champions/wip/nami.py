"""Nami combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class NamiCog(ChampionCog):
    """Model Nami's W5/E5/Q1/R2 self-buff duel fixture.

    E is placed on Nami and its three charges empower Q, W's hostile bounce,
    and R. W starts as a self-heal and then bounces once to the sole opponent.
    Q and R provide distinct immobilization windows, while multi-ally bounce
    routing remains outside a one-opponent scenario.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Nami.json",
        "data/raw/16.17.1/communitydragon/champions/267.json",
        "data/raw/16.17.1/communitydragon/champions/nami.bin.json",
    )

    _E_AT_MS = 0
    _Q_AT_MS = 100
    _W_SELF_AT_MS = 300
    _W_ENEMY_AT_MS = 500
    _R_AT_MS = 700

    @staticmethod
    def _e_damage(ap: Decimal) -> Decimal:
        """Calculate one rank-five Tidecaller's Blessing proc.

        :param ap: Ability power from Nami's current snapshot.
        :return: Raw bonus magic damage for one empowered hit.
        """
        return Decimal(80) + Decimal("0.20") * ap

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks after all three E charges are consumed.

        :param context: Snapshot supplying attack damage, speed, and duration.
        :return: Chronological basic attacks.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 300
        return tuple(
            action(
                f"NAMI_BASIC_ATTACK_{index}",
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
            for index, at_ms in enumerate(range(1200, context.duration_ms + 1, interval), start=1)
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Convert Surging Tides' flat self speed into a snapshot multiplier.

        :param context: Role-bound Nami encounter context.
        :return: Ratio after one ordinary passive movement proc.
        """
        bonus = Decimal(100) + Decimal("0.25") * context.snapshot.ability_power
        return (context.snapshot.move_speed + bonus) / context.snapshot.move_speed

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return zero because Nami has no displacement movement ability.

        :param context: Role-bound Nami encounter context.
        :return: Zero dash distance.
        """
        return Decimal(0)

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Avoid repeating W as free sustain without mana and cooldown state.

        :param context: Role-bound Nami encounter context.
        :param duration_ms: Requested lane observation duration.
        :param no_damage_delay_ms: Time since the last incoming damage event.
        :return: Zero extra health and a resource-state blocker.
        """
        return Decimal(0), ("NAMI_W_SELF_HEAL_REQUIRES_MANA_AND_COOLDOWN_STATE",)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the selected fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Nami-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "CRITICAL_STRIKE_CHANCE",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            return f"NAMI_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build self E, Q, self-to-enemy W, R, and follow-up attacks.

        :param context: Role-bound Nami and opponent snapshots.
        :return: Deterministic level-13 action schedule.
        """
        ap = context.snapshot.ability_power
        base = self._sequence_base(context)
        e_damage = self._e_damage(ap)
        bounce_scale = Decimal("0.80") + Decimal("0.0015") * ap
        fixed = (
            action(
                "NAMI_E_TIDECALLERS_BLESSING_SELF",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "NAMI_E_THREE_CHARGES", 6000),),
                requires_living_opponent=False,
            ),
            action(
                "NAMI_Q_AQUA_PRISON_E_PROC",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(90) + Decimal("0.50") * ap,
                        DamageType.MAGIC,
                    ),
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=1500),
                ),
            ),
            action(
                "NAMI_W_EBB_AND_FLOW_SELF_HEAL",
                at_ms=self._W_SELF_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(healing(context.self_entity, Decimal(155) + Decimal("0.40") * ap),),
                requires_living_opponent=False,
            ),
            action(
                "NAMI_W_EBB_AND_FLOW_ENEMY_BOUNCE_E_PROC",
                at_ms=self._W_ENEMY_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(
                    damage(
                        context.opponent_entity,
                        (Decimal(200) + Decimal("0.50") * ap) * bounce_scale,
                        DamageType.MAGIC,
                    ),
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                ),
            ),
            action(
                "NAMI_R_TIDAL_WAVE_E_PROC",
                at_ms=self._R_AT_MS,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(250) + Decimal("0.60") * ap,
                        DamageType.MAGIC,
                    ),
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=500),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=4000,
                        magnitude=Decimal("0.70"),
                    ),
                ),
            ),
        )
        events = (*fixed, *self._attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"NAMI_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "nami_w5_e5_q1_r2_self_buff_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "NAMI_LEVEL13_W5_E5_Q1_R2_ORDER_LOCKED_UNVERIFIED",
                "NAMI_E_SELF_CAST_AND_SPELL_PROC_BEHAVIOR_ASSUMED",
                "NAMI_W_SELF_FIRST_THEN_SINGLE_ENEMY_BOUNCE_ASSUMED",
                "NAMI_W_NO_THIRD_VALID_ALLY_TARGET_IN_DUEL",
                "NAMI_R_MAXIMUM_FOUR_SECOND_SLOW_DISTANCE_ASSUMED",
                "NAMI_Q_SUSPENSION_CLASSIFIED_AS_TENACITY_REDUCIBLE_STUN_UNVERIFIED",
                "NAMI_PASSIVE_MOVE_SPEED_DECAY_APPROXIMATED_BY_INITIAL_VALUE",
                "NAMI_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Q suspension and R knockup-plus-slow windows.

        :param context: Role-bound Nami and opponent snapshots.
        :return: Three hostile control windows with explicit reducibility.
        """
        all_active = (
            ActionChannel.BASIC_ATTACK,
            ActionChannel.ABILITY,
            ActionChannel.MOVEMENT,
        )
        return ReactionPlan(
            "nami_q_suspension_r_wave_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "nami_q_aqua_prison_suspension",
                    self._Q_AT_MS,
                    min(self._Q_AT_MS + 1500, context.duration_ms),
                    all_active,
                    "NAMI_Q_AQUA_PRISON_E_PROC",
                    True,
                    ControlType.STUN,
                ),
                CastBlockWindow(
                    "nami_r_tidal_wave_knockup",
                    self._R_AT_MS,
                    min(self._R_AT_MS + 500, context.duration_ms),
                    all_active,
                    "NAMI_R_TIDAL_WAVE_E_PROC",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "nami_r_tidal_wave_slow",
                    self._R_AT_MS + 500,
                    min(self._R_AT_MS + 4500, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "NAMI_R_TIDAL_WAVE_E_PROC",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=(
                "NAMI_Q_SUSPENSION_TENACITY_INTERACTION_UNVERIFIED",
                "NAMI_R_SLOW_DURATION_DEPENDS_ON_TRAVEL_DISTANCE",
            ),
        )
