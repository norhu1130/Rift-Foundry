"""Ezreal combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class EzrealCog(ChampionCog):
    """Model Ezreal's Q5/E5/W1/R2 level-13 single-target fixture.

    The fixture assumes every projectile reaches the selected champion. Mystic
    Shot therefore refunds 1.5 seconds from represented cooldown clocks, and an
    attached Essence Flux mark is detonated by the next modeled damaging spell.
    Rising Spell Force changes the basic-attack clock after successful spell
    hits while keeping projectile accuracy explicit as an unverified boundary.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Ezreal.json",
        "data/raw/16.17.1/communitydragon/champions/81.json",
        "data/raw/16.17.1/communitydragon/champions/ezreal.bin.json",
    )

    _R_HIT_MS = 1100
    _W_FIRST_MS = 1200
    _E_HIT_MS = 1500
    _Q_FIRST_MS = 1900
    _Q_REFUND_MS = 1500
    _PASSIVE_STACK_DURATION_MS = 6000
    _PASSIVE_AS_PER_STACK = Decimal("0.10")
    _ATTACK_SPEED_RATIO = Decimal("0.625")

    @staticmethod
    def _haste_cooldown_ms(base_ms: int, ability_haste: Decimal) -> int:
        """Apply the standard ability-haste transform to a base cooldown.

        :param base_ms: Rank-specific cooldown in milliseconds.
        :param ability_haste: Non-negative haste from the combat snapshot.
        :return: Cooldown rounded deterministically to the nearest millisecond.
        :raises ValueError: If the cooldown or haste input is negative.
        """
        if base_ms < 0 or ability_haste < 0:
            raise ValueError("cooldown inputs cannot be negative")
        return int(
            (Decimal(base_ms) * Decimal(100) / (Decimal(100) + ability_haste)).to_integral_value(
                ROUND_HALF_EVEN
            )
        )

    @classmethod
    def _q_hit_times(cls, context: ParticipantContext) -> tuple[int, ...]:
        """Schedule assumed Q hits after applying Q's own cooldown refund.

        :param context: Ezreal snapshot supplying haste and encounter duration.
        :return: Ordered Mystic Shot hit timestamps inside the fixture.
        """
        recast_ms = max(
            1,
            cls._haste_cooldown_ms(4500, context.snapshot.ability_haste) - cls._Q_REFUND_MS,
        )
        return tuple(range(cls._Q_FIRST_MS, context.duration_ms + 1, recast_ms))

    @classmethod
    def _refunded_recast_times(
        cls,
        context: ParticipantContext,
        *,
        first_cast_ms: int,
        base_cooldown_ms: int,
        q_times: tuple[int, ...],
    ) -> tuple[int, ...]:
        """Resolve represented recasts after chronological Q refunds.

        Refunds cannot move the ready time into the past. If one makes W ready
        or E ready at the current Q hit, a small deterministic delay reserves
        cast order. Each recast starts a fresh haste-adjusted cooldown clock.

        :param context: Ezreal snapshot supplying haste and fixture duration.
        :param first_cast_ms: Timestamp of the fixture's initial ability cast.
        :param base_cooldown_ms: Rank-specific cooldown before ability haste.
        :param q_times: Ordered Q hit timestamps that refund W cooldown.
        :return: Ordered recast timestamps inside the encounter duration.
        """
        cooldown_ms = cls._haste_cooldown_ms(base_cooldown_ms, context.snapshot.ability_haste)
        ready_ms = first_cast_ms + cooldown_ms
        recasts: list[int] = []
        for q_at_ms in q_times:
            while ready_ms < q_at_ms and ready_ms <= context.duration_ms:
                recasts.append(ready_ms)
                ready_ms += cooldown_ms
            ready_ms = max(q_at_ms, ready_ms - cls._Q_REFUND_MS)
            if ready_ms == q_at_ms:
                ready_ms += 100
        while ready_ms <= context.duration_ms:
            recasts.append(ready_ms)
            ready_ms += cooldown_ms
        return tuple(recasts)

    @staticmethod
    def _passive_marker(context: ParticipantContext) -> StatusOutput:
        """Create one transparent Rising Spell Force stack marker.

        :param context: Role-bound Ezreal context receiving the passive stack.
        :return: Six-second self status corresponding to one successful spell hit.
        """
        return StatusOutput(
            context.self_entity,
            "EZREAL_RISING_SPELL_FORCE_STACK",
            EzrealCog._PASSIVE_STACK_DURATION_MS,
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Arcane Shift's locked 475-unit blink range.

        :param context: Role-bound encounter context.
        :return: Maximum represented displacement in game units.
        """
        return Decimal(475)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Ezreal's fixed event policy.

        AD, AP, attack speed, and ability haste alter represented outputs. Mana
        expenditure, critical rolls, and healing conversion remain deliberately
        unavailable rather than being assigned invented value.

        :param item: Normalized candidate from the locked item catalog.
        :return: Ezreal-scoped blocker for unsupported stats, otherwise ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"EZREAL_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _spell_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build R, W, E, and cooldown-refunded Q spell events.

        :param context: Ezreal snapshot supplying AD, AP, haste, and role IDs.
        :return: Deterministic spell-hit events with causal W detonations.
        """
        base = self._sequence_base(context)
        bonus_ad = context.snapshot.bonus_attack_damage
        ap = context.snapshot.ability_power
        marker = self._passive_marker(context)
        q_times = self._q_hit_times(context)
        w_times = (
            (self._W_FIRST_MS,)
            + self._refunded_recast_times(
                context,
                first_cast_ms=self._W_FIRST_MS,
                base_cooldown_ms=8000,
                q_times=q_times,
            )
            if context.duration_ms >= self._W_FIRST_MS
            else ()
        )
        e_times = (
            (self._E_HIT_MS,)
            + self._refunded_recast_times(
                context,
                first_cast_ms=self._E_HIT_MS,
                base_cooldown_ms=14000,
                q_times=q_times,
            )
            if context.duration_ms >= self._E_HIT_MS
            else ()
        )
        schedule = [
            *(((self._R_HIT_MS, 0, "R", 1),) if context.duration_ms >= self._R_HIT_MS else ()),
            *((at_ms, 1, "W", index) for index, at_ms in enumerate(w_times, 1)),
            *((at_ms, 2, "E", index) for index, at_ms in enumerate(e_times, 1)),
            *((at_ms, 3, "Q", index) for index, at_ms in enumerate(q_times, 1)),
        ]
        events: list[ActionEvent] = []
        mark_live = False
        for at_ms, order, spell, index in sorted(schedule):
            if spell == "W":
                mark_live = True
                events.append(
                    action(
                        f"EZREAL_W_ESSENCE_FLUX_{index}",
                        at_ms=at_ms,
                        sequence=base + at_ms * 10 + order,
                        source=context.self_entity,
                        channel=ActionChannel.ABILITY,
                        outputs=(marker,),
                    )
                )
                continue
            outputs = []
            if spell == "R":
                outputs.append(
                    damage(
                        context.opponent_entity,
                        self.rank_value("EzrealR", "BaseDamage", context, Decimal(550))
                        + bonus_ad
                        + Decimal("1.10") * ap,
                        DamageType.MAGIC,
                    )
                )
                event_id = "EZREAL_R_TRUESHOT_BARRAGE"
            elif spell == "E":
                outputs.extend(
                    (
                        damage(
                            context.opponent_entity,
                            self.rank_value("EzrealE", "BaseDamage", context, Decimal(280))
                            + Decimal("0.60") * bonus_ad
                            + Decimal("0.75") * ap,
                            DamageType.MAGIC,
                        ),
                        StatusOutput(context.self_entity, "EZREAL_E_BLINK_475", 1),
                    )
                )
                event_id = f"EZREAL_E_ARCANE_SHIFT_{index}"
            else:
                outputs.append(
                    damage(
                        context.opponent_entity,
                        self.rank_value("EzrealQ", "BaseDamage", context, Decimal(120))
                        + Decimal("1.30") * context.snapshot.attack_damage
                        + Decimal("0.40") * ap,
                        DamageType.PHYSICAL,
                    )
                )
                event_id = f"EZREAL_Q_MYSTIC_SHOT_{index}"
            if mark_live:
                outputs.append(
                    damage(
                        context.opponent_entity,
                        self.rank_value("EzrealW", "BaseDamage", context, Decimal(80))
                        + bonus_ad
                        + Decimal("0.90") * ap,
                        DamageType.MAGIC,
                    )
                )
                mark_live = False
            outputs.append(marker)
            events.append(
                action(
                    event_id,
                    at_ms=at_ms,
                    sequence=base + at_ms * 10 + order,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=tuple(outputs),
                )
            )
        return tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id)))

    def _basic_attacks(
        self,
        context: ParticipantContext,
        spell_events: tuple[ActionEvent, ...],
    ) -> tuple[ActionEvent, ...]:
        """Schedule attacks using the passive stacks active at each attack.

        :param context: Ezreal snapshot supplying AD and item attack speed.
        :param spell_events: Successful spell hits that build and refresh stacks.
        :return: Blind-susceptible attacks with passive-adjusted cadence.
        """
        hit_times = tuple(event.at_ms for event in spell_events)
        base = self._sequence_base(context) + 500
        events: list[ActionEvent] = []
        at_ms = 2200
        while at_ms <= context.duration_ms:
            prior_hits = tuple(hit for hit in hit_times if hit <= at_ms)
            if prior_hits and at_ms - prior_hits[-1] <= self._PASSIVE_STACK_DURATION_MS:
                chain_start = 0
                for index in range(len(prior_hits) - 1, 0, -1):
                    if prior_hits[index] - prior_hits[index - 1] > self._PASSIVE_STACK_DURATION_MS:
                        chain_start = index
                        break
                stacks = min(5, len(prior_hits) - chain_start)
            else:
                stacks = 0
            attack_speed = context.snapshot.attack_speed + (
                self._ATTACK_SPEED_RATIO * self._PASSIVE_AS_PER_STACK * stacks
            )
            events.append(
                action(
                    f"EZREAL_BASIC_ATTACK_{len(events) + 1}",
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
            at_ms += self._attack_interval_ms(attack_speed)
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked level-13 spell and passive-adjusted attack rotation.

        :param context: Role-bound snapshots for Ezreal and his opponent.
        :return: Chronological combat schedule with explicit evidence blockers.
        """
        spells = self._spell_events(context)
        events = tuple(
            sorted(
                (*spells, *self._basic_attacks(context, spells)),
                key=lambda event: (event.at_ms, event.sequence, event.id),
            )
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"EZREAL_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "ezreal_q5_e5_w1_r2_level13_locked_v1",
            events,
            (
                *level_blockers,
                "EZREAL_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "EZREAL_ROTATION_AND_CAST_TIMING_UNVERIFIED",
                "EZREAL_SKILLSHOT_HITS_AND_RANGE_CONTINUITY_ASSUMED",
                "EZREAL_Q_ON_HIT_ITEM_EFFECTS_NOT_CAUSALLY_MODELED",
                "EZREAL_Q_COOLDOWN_REFUND_REQUIRES_ASSUMED_HIT",
                "EZREAL_W_MARK_TARGET_AND_DETONATION_ASSUMED",
                "EZREAL_E_TARGET_SELECTION_AND_POSITION_NOT_CAUSALLY_MODELED",
                "EZREAL_R_CHANNEL_INTERRUPTION_NOT_CAUSALLY_MODELED",
                "EZREAL_R_PRIOR_UNIT_HIT_DAMAGE_REDUCTION_NOT_MODELED",
                "EZREAL_PASSIVE_STACK_EXPIRY_PRECOMPUTED_FROM_ASSUMED_HITS",
                "EZREAL_MANA_COSTS_AND_W_REFUND_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Return neutral defense while preserving Ezreal's positional limits.

        Arcane Shift is represented as offensive displacement, not an oracle that
        automatically avoids hostile projectiles or crowd control.

        :param context: Role-bound snapshots for Ezreal and his opponent.
        :return: Neutral reaction model with targeting and timing blockers.
        """
        return ReactionPlan(
            "ezreal_arcane_shift_reaction_unresolved_v1",
            blockers=(
                "EZREAL_E_REACTIVE_BLINK_TRIGGER_NOT_MODELED",
                "EZREAL_E_PROJECTILE_DODGE_AND_TARGET_SELECTION_NOT_MODELED",
            ),
        )
