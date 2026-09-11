"""Lulu combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import (
    action,
    crowd_control,
    damage,
    maximum_health,
    shielding,
)
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class LuluCog(ChampionCog):
    """Model Lulu's Q1/W5/E5/R2 self-buff duel fixture.

    Whimsy and Help, Pix! are deliberately self-targeted; their enemy variants
    are not granted at the same time. Wild Growth also targets Lulu, providing
    temporary maximum health while knocking up and slowing the nearby opponent.
    Pix accompanies each modeled basic attack with three separate bolts.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Lulu.json",
        "data/raw/16.17.1/communitydragon/champions/117.json",
        "data/raw/16.17.1/communitydragon/champions/lulu.bin.json",
    )

    _ATTACK_SPEED_RATIO = Decimal("0.625")
    _W_END_MS = 4000
    _R_AT_MS = 500

    @staticmethod
    def _pix_bolt(context: ParticipantContext) -> Decimal:
        """Calculate one of Pix's three attack bolts at the current level.

        :param context: Snapshot supplying Lulu's level and ability power.
        :return: Raw magic damage for one Pix bolt.
        """
        base = Decimal(5) + Decimal(34) * Decimal(context.snapshot.level - 1) / Decimal(17)
        return base + Decimal("0.05") * context.snapshot.ability_power

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule self-Whimsy attacks followed by normal-speed attacks.

        :param context: Snapshot supplying attack stats and encounter duration.
        :return: Basic attacks with three independently represented Pix bolts.
        """
        fast_interval = self._attack_interval_ms(
            context.snapshot.attack_speed + self._ATTACK_SPEED_RATIO * Decimal("0.30")
        )
        normal_interval = self._attack_interval_ms(context.snapshot.attack_speed)
        times: list[int] = []
        at_ms = 1200
        while at_ms < min(self._W_END_MS, context.duration_ms + 1):
            times.append(at_ms)
            at_ms += fast_interval
        at_ms = max(at_ms, self._W_END_MS)
        while at_ms <= context.duration_ms:
            times.append(at_ms)
            at_ms += normal_interval
        bolt = self._pix_bolt(context)
        base = self._sequence_base(context) + 200
        return tuple(
            action(
                f"LULU_BASIC_ATTACK_WITH_PIX_{index}",
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
                    damage(context.opponent_entity, bolt, DamageType.MAGIC),
                    damage(context.opponent_entity, bolt, DamageType.MAGIC),
                    damage(context.opponent_entity, bolt, DamageType.MAGIC),
                ),
            )
            for index, at_ms in enumerate(times, start=1)
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose self-Whimsy's AP-scaled movement multiplier.

        :param context: Snapshot supplying Lulu's ability power.
        :return: Movement multiplier during rank-five Whimsy.
        """
        return Decimal("1.25") + Decimal("0.0005") * context.snapshot.ability_power

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Return zero because Lulu has no displacement ability.

        :param context: Role-bound Lulu encounter context.
        :return: Zero dash distance.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats not represented in the self-buff fixture.

        :param item: Normalized candidate from the locked catalog.
        :return: Lulu-scoped blocker, or ``None`` for represented stats.
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
            return f"LULU_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build self-targeted W/E/R, double-hit Q, and Pix attacks.

        :param context: Role-bound Lulu and opponent snapshots.
        :return: Deterministic level-13 support-duel schedule.
        """
        ap = context.snapshot.ability_power
        base = self._sequence_base(context)
        q_damage = (Decimal(60) + Decimal("0.50") * ap) * Decimal("1.50")
        fixed = (
            action(
                "LULU_W_WHIMSY_SELF",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(context.self_entity, "LULU_W_MOVE_SPEED", 4000),
                    StatusOutput(context.self_entity, "LULU_W_ATTACK_SPEED_30_PERCENT", 4000),
                ),
                requires_living_opponent=False,
            ),
            action(
                "LULU_E_HELP_PIX_SELF",
                at_ms=100,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(
                        context.self_entity,
                        Decimal(230) + Decimal("0.50") * ap,
                        duration_ms=2500,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "LULU_R_WILD_GROWTH_SELF",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    maximum_health(
                        context.self_entity,
                        Decimal(425) + Decimal("0.55") * ap,
                        duration_ms=7000,
                    ),
                    crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=1000),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=7000,
                        magnitude=Decimal("0.45"),
                    ),
                ),
            ),
            action(
                "LULU_Q_GLITTERLANCE_DOUBLE_HIT",
                at_ms=900,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=2000,
                        magnitude=Decimal("0.80"),
                    ),
                ),
            ),
        )
        events = (*fixed, *self._attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"LULU_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "lulu_q1_w5_e5_r2_self_buff_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "LULU_LEVEL13_E5_W5_Q1_R2_ORDER_LOCKED_UNVERIFIED",
                "LULU_W_AND_E_SELF_TARGET_VARIANTS_SELECTED",
                "LULU_W_POLYMORPH_AND_E_ENEMY_DAMAGE_NOT_COMBINED_WITH_SELF_VARIANTS",
                "LULU_Q_BOTH_BOLTS_HIT_SAME_TARGET_ASSUMED",
                "LULU_PIX_PROJECTILE_BLOCKING_AND_TARGET_DISTANCE_NOT_MODELED",
                "LULU_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Wild Growth displacement/aura and Glitterlance slow.

        :param context: Role-bound Lulu and opponent snapshots.
        :return: Airborne and movement-only slow windows.
        """
        return ReactionPlan(
            "lulu_q1_r2_self_cast_control_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "lulu_r_knockup",
                    self._R_AT_MS,
                    min(self._R_AT_MS + 1000, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "LULU_R_WILD_GROWTH_SELF",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "lulu_r_aura_slow",
                    self._R_AT_MS,
                    min(self._R_AT_MS + 7000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "LULU_R_WILD_GROWTH_SELF",
                    True,
                    ControlType.SLOW,
                ),
                CastBlockWindow(
                    "lulu_q_glitterlance_slow",
                    900,
                    min(2900, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "LULU_Q_GLITTERLANCE_DOUBLE_HIT",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=("LULU_R_AURA_RANGE_UPTIME_ASSUMED_FULL",),
        )
