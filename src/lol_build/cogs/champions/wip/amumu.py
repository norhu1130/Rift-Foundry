"""Amumu combat Cog backed by the locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    CastBlockWindow,
    ChampionCog,
    CogCapability,
    CogMaturity,
    ControlType,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, EventOutput, StatusOutput


class AmumuCog(ChampionCog):
    """Model Amumu's E5/Q5/W1/R2 level-13 single-target sequence.

    The fixture spends both initially available Bandage Toss charges, enables
    Despair after the first engage, and keeps the target in aura range. Curse of
    the Sad Mummy establishes Cursed Touch before its own damage, allowing later
    magic damage to emit the locked ten-percent pre-mitigation bonus as true
    damage. Dynamic resources and geometry remain explicit blockers.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES | {CogCapability.MULTI_TARGET}
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Amumu.json",
        "data/raw/16.17.1/communitydragon/champions/32.json",
        "data/raw/16.17.1/communitydragon/champions/amumu.bin.json",
    )

    _Q_FIRST_AT_MS = 300
    _Q_SECOND_AT_MS = 3300
    _W_START_AT_MS = 1200
    _R_AT_MS = 1350
    _E_FIRST_AT_MS = 1700
    _ATTACK_FIRST_AT_MS = 1150

    @staticmethod
    def _haste_cooldown_ms(base_ms: int, ability_haste: Decimal) -> int:
        """Apply non-negative ability haste to one base cooldown.

        :param base_ms: Rank-specific cooldown before ability haste.
        :param ability_haste: Haste supplied by the participant snapshot.
        :return: Cooldown rounded upward to a deterministic millisecond.
        """
        haste = max(Decimal(0), ability_haste)
        return int(
            (Decimal(base_ms) * Decimal(100) / (Decimal(100) + haste)).to_integral_value(
                ROUND_CEILING
            )
        )

    @classmethod
    def _cursed_magic_outputs(
        cls,
        context: ParticipantContext,
        amount: Decimal,
    ) -> tuple[EventOutput, ...]:
        """Emit magic damage and Cursed Touch's pre-mitigation true damage.

        Despair, Tantrum, and Curse of the Sad Mummy all carry locked area
        targeting, so each opponent present takes the pair. A duel holds one
        opponent and therefore produces the original two outputs.

        :param context: Role-bound context identifying the affected opponents.
        :param amount: Raw magic damage before resistance mitigation.
        :return: Paired magic and ten-percent true-damage outputs per opponent.
        """
        return (
            *cls.area_outputs(
                context,
                lambda entity: damage(entity, amount, DamageType.MAGIC),
                centered_on_self=True,
            ),
            *cls.area_outputs(
                context,
                lambda entity: damage(entity, amount * Decimal("0.10"), DamageType.TRUE),
                centered_on_self=True,
            ),
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Bandage Toss's locked maximum cast range.

        :param context: Role-bound Amumu encounter context.
        :return: Maximum Q engage distance in game units.
        """
        return Decimal(1100)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Amumu's fixed duel model.

        :param item: Normalized candidate from the locked item catalog.
        :return: Amumu-scoped blocker, or ``None`` for represented channels.
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
            return f"AMUMU_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks that apply and refresh Cursed Touch.

        :param context: Role-bound snapshots supplying attack cadence and damage.
        :return: Chronological physical attacks with observable Curse statuses.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 200
        events: list[ActionEvent] = []
        at_ms = self._ATTACK_FIRST_AT_MS
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"AMUMU_BASIC_ATTACK_CURSED_TOUCH_{index}",
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
                        StatusOutput(context.opponent_entity, "AMUMU_CURSED_TOUCH", 3000),
                    ),
                )
            )
            at_ms += interval_ms
        return tuple(events)

    def _despair_ticks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule W1 half-second ticks while the target remains in aura range.

        :param context: Snapshots providing AP and opposing maximum health.
        :return: Cursed magic and true-damage tick events through the horizon.
        """
        ap = context.snapshot.ability_power
        health_ratio_per_tick = Decimal("0.005") + Decimal("0.000025") * ap
        amount = Decimal(5) + health_ratio_per_tick * context.opponent_snapshot.max_hp
        base = self._sequence_base(context) + 300
        events: list[ActionEvent] = []
        for index, at_ms in enumerate(
            range(self._W_START_AT_MS + 500, context.duration_ms + 1, 500),
            start=1,
        ):
            events.append(
                action(
                    f"AMUMU_W_DESPAIR_TICK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=self._cursed_magic_outputs(context, amount),
                )
            )
        return tuple(events)

    def _tantrum_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule E5 casts using haste but no speculative on-hit refunds.

        :param context: Snapshot carrying AP and ability haste.
        :return: One or more deterministic Tantrum damage events.
        """
        amount = Decimal(185) + Decimal("0.50") * context.snapshot.ability_power
        cooldown_ms = self._haste_cooldown_ms(5000, context.snapshot.ability_haste)
        base = self._sequence_base(context) + 400
        events: list[ActionEvent] = []
        at_ms = self._E_FIRST_AT_MS
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"AMUMU_E_TANTRUM_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=self._cursed_magic_outputs(context, amount),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Amumu's two-Q engage, aura, Tantrum, and ultimate plan.

        :param context: Role-bound Amumu and opponent combat snapshots.
        :return: Deterministic level-13 action schedule with honest blockers.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        q_amount = Decimal(170) + Decimal("0.85") * ap
        r_amount = Decimal(300) + Decimal("0.80") * ap
        fixed_events = (
            action(
                "AMUMU_Q_BANDAGE_TOSS_1",
                at_ms=self._Q_FIRST_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q_amount, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=1000),
                ),
            ),
            action(
                "AMUMU_W_DESPAIR_ENABLE",
                at_ms=self._W_START_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "AMUMU_W_DESPAIR_ACTIVE", 6800),),
                requires_living_opponent=False,
            ),
            action(
                "AMUMU_R_CURSE_OF_THE_SAD_MUMMY",
                at_ms=self._R_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    *self.area_outputs(
                        context,
                        lambda entity: StatusOutput(entity, "AMUMU_CURSED_TOUCH", 3000),
                        centered_on_self=True,
                    ),
                    *self._cursed_magic_outputs(context, r_amount),
                    *self.area_outputs(
                        context,
                        lambda entity: crowd_control(entity, "STUN", duration_ms=1500),
                        centered_on_self=True,
                    ),
                ),
            ),
            action(
                "AMUMU_Q_BANDAGE_TOSS_2",
                at_ms=self._Q_SECOND_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    *self._cursed_magic_outputs(context, q_amount),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=1000),
                ),
            ),
        )
        events = (
            *fixed_events,
            *self._basic_attacks(context),
            *self._despair_ticks(context),
            *self._tantrum_events(context),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"AMUMU_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "amumu_e5_q5_w1_r2_level13_locked_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "AMUMU_LEVEL13_E5_Q5_W1_R2_POLICY_UNVERIFIED",
                "AMUMU_ROTATION_AND_PROJECTILE_TIMING_UNVERIFIED",
                "AMUMU_Q_BOTH_INITIAL_AMMO_HITS_ASSUMED",
                "AMUMU_Q_AMMO_RECHARGE_AND_RESOURCE_COSTS_NOT_MODELED",
                "AMUMU_W_TOGGLE_MANA_AND_DEACTIVATION_NOT_MODELED",
                "AMUMU_W_HALF_SECOND_TICK_TIMING_UNVERIFIED",
                "AMUMU_W_TARGET_REMAINS_IN_AURA_ASSUMED",
                "AMUMU_E_INCOMING_HIT_COOLDOWN_REFUND_NOT_MODELED",
                "AMUMU_E_FLAT_PHYSICAL_DAMAGE_REDUCTION_NOT_MODELED",
                "AMUMU_CURSED_TOUCH_UPTIME_FIXED_AFTER_R_ASSUMED",
                "AMUMU_Q_BANDAGE_TOSS_SINGLE_TARGET_LANDING_ASSUMED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose both Q stuns and the ultimate stun as causal windows.

        :param context: Role-bound snapshots identifying Amumu's opponent.
        :return: Three tenacity-reducible all-action control intervals.
        """
        blocked = (
            ActionChannel.BASIC_ATTACK,
            ActionChannel.ABILITY,
            ActionChannel.MOVEMENT,
            ActionChannel.ITEM_ACTIVE,
        )
        return ReactionPlan(
            "amumu_q5_r2_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "amumu_q1_stun",
                    self._Q_FIRST_AT_MS,
                    min(self._Q_FIRST_AT_MS + 1000, context.duration_ms),
                    blocked,
                    "AMUMU_Q_BANDAGE_TOSS_1",
                    True,
                    ControlType.STUN,
                ),
                CastBlockWindow(
                    "amumu_r_stun",
                    self._R_AT_MS,
                    min(self._R_AT_MS + 1500, context.duration_ms),
                    blocked,
                    "AMUMU_R_CURSE_OF_THE_SAD_MUMMY",
                    True,
                    ControlType.STUN,
                ),
                CastBlockWindow(
                    "amumu_q2_stun",
                    self._Q_SECOND_AT_MS,
                    min(self._Q_SECOND_AT_MS + 1000, context.duration_ms),
                    blocked,
                    "AMUMU_Q_BANDAGE_TOSS_2",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(
                "AMUMU_Q_PROJECTILE_HIT_AND_DASH_GEOMETRY_NOT_MODELED",
                "AMUMU_Q_R_TENACITY_RUNTIME_UNVERIFIED",
                "AMUMU_MULTI_TARGET_CONTROL_NOT_MODELED",
                "AMUMU_E_FLAT_PHYSICAL_DAMAGE_REDUCTION_NOT_MODELED",
            ),
        )
