"""Hecarim combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing, movement_speed
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatModifierOutput, StatusOutput


class HecarimCog(ChampionCog):
    """Model Hecarim's Q5/W5/E1/R2 level-13 maximum-charge fixture.

    Devastating Charge and Onslaught of Shadows use their maximum travel
    variants. Rampage starts without stacks, then applies its three-stack
    damage and cooldown progression. Spirit of Dread emits eight half-second
    ticks and converts represented self damage into raw-damage leech while its
    four-second zone is active.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Hecarim.json",
        "data/raw/16.17.1/communitydragon/champions/120.json",
        "data/raw/16.17.1/communitydragon/champions/hecarim.bin.json",
    )

    _W_END_MS = 4000
    _E_END_MS = 4000
    _R_AT_MS = 100
    _E_ATTACK_MS = 900

    @staticmethod
    def _cooldown_ms(seconds: Decimal, ability_haste: Decimal) -> int:
        """Convert a post-stack cooldown through ability haste.

        :param seconds: Cooldown after Rampage's flat stack reduction.
        :param ability_haste: Non-negative haste supplied by the snapshot.
        :return: Deterministically rounded cooldown in milliseconds.
        :raises ValueError: If ability haste is negative.
        """
        if ability_haste < 0:
            raise ValueError("ability_haste must be non-negative")
        value = seconds * Decimal(100_000) / (Decimal(100) + ability_haste)
        return max(1, int(value.to_integral_value(ROUND_HALF_EVEN)))

    @staticmethod
    def _passive_coefficient(level: int) -> Decimal:
        """Resolve Warpath's locked level-breakpoint movement conversion.

        :param level: Champion level in the supported one-to-eighteen range.
        :return: Bonus-movement-speed fraction converted into attack damage.
        """
        coefficient = Decimal("0.12")
        for breakpoint in (3, 6, 9, 12, 15, 18):
            if level >= breakpoint:
                coefficient += Decimal("0.02")
        return coefficient

    def _passive_bonus_ad(
        self,
        context: ParticipantContext,
        *,
        devastating_charge: bool,
    ) -> Decimal:
        """Calculate Warpath AD from item and fixture movement bonuses.

        :param context: Snapshot supplying level and post-item movement speed.
        :param devastating_charge: Include E's maximum movement bonus when true.
        :return: Attack damage granted by represented bonus movement speed.
        """
        native_speed = self.snapshot(level=context.snapshot.level).move_speed
        bonus_speed = max(Decimal(0), context.snapshot.move_speed - native_speed)
        if devastating_charge:
            bonus_speed += Decimal("0.65") * context.snapshot.move_speed
        return self._passive_coefficient(context.snapshot.level) * bonus_speed

    def _bonus_ad(self, context: ParticipantContext, *, at_ms: int) -> Decimal:
        """Return item and Warpath bonus AD at one fixture timestamp.

        :param context: Snapshot supplying item AD and movement speed.
        :param at_ms: Timestamp used to determine whether E remains active.
        :return: Total represented bonus attack damage.
        """
        return context.snapshot.bonus_attack_damage + self._passive_bonus_ad(
            context,
            devastating_charge=at_ms < self._E_END_MS,
        )

    @staticmethod
    def _leeching_damage(
        context: ParticipantContext,
        amount: Decimal,
        damage_type: DamageType,
        *,
        active: bool,
    ) -> tuple:
        """Build damage and optional Spirit of Dread raw leech.

        :param context: Role bindings for damage and healing recipients.
        :param amount: Raw outgoing damage from the represented event.
        :param damage_type: Physical, magic, or true damage channel.
        :param active: Whether the W zone is active at the event timestamp.
        :return: Damage plus a twenty-five-percent self heal when active.
        """
        outputs = [damage(context.opponent_entity, amount, damage_type)]
        if active:
            outputs.append(healing(context.self_entity, Decimal("0.25") * amount))
        return tuple(outputs)

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Rampage with locked stack damage and cooldown changes.

        :param context: Snapshot supplying bonus AD, haste, duration, and roles.
        :return: Chronological Rampage events through the benchmark.
        """
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 500
        stacks = 0
        while at_ms <= context.duration_ms:
            bonus_ad = self._bonus_ad(context, at_ms=at_ms)
            base_damage = Decimal(180) + Decimal("0.90") * bonus_ad
            bonus_percent = Decimal(3) + Decimal("0.03") * bonus_ad
            amount = base_damage * (Decimal(1) + Decimal(stacks) * bonus_percent / Decimal(100))
            index = len(events) + 1
            events.append(
                action(
                    f"HECARIM_Q_RAMPAGE_{index}_STACKS_{stacks}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=self._leeching_damage(
                        context,
                        amount,
                        DamageType.PHYSICAL,
                        active=at_ms <= self._W_END_MS,
                    ),
                )
            )
            stacks = min(3, stacks + 1)
            cooldown = Decimal(4) - Decimal("0.75") * Decimal(stacks)
            at_ms += self._cooldown_ms(cooldown, context.snapshot.ability_haste)
        return tuple(events)

    def _w_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Spirit of Dread's defenses and eight damage ticks.

        :param context: Snapshot supplying AP, duration, and entity roles.
        :return: Passive resistance event followed by active-zone ticks.
        """
        base = self._sequence_base(context) + 200
        total_damage = Decimal(240) + Decimal("0.80") * context.snapshot.ability_power
        tick_damage = total_damage / Decimal(8)
        events: list[ActionEvent] = [
            action(
                "HECARIM_W_SPIRIT_OF_DREAD_START",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatModifierOutput(context.self_entity, "ARMOR", Decimal(25)),
                    StatModifierOutput(
                        context.self_entity,
                        "MAGIC_RESISTANCE",
                        Decimal(25),
                    ),
                    StatusOutput(context.self_entity, "HECARIM_W_ZONE", self._W_END_MS),
                ),
                requires_living_opponent=False,
            )
        ]
        for index, at_ms in enumerate(range(500, self._W_END_MS + 1, 500), start=1):
            if at_ms > context.duration_ms:
                break
            events.append(
                action(
                    f"HECARIM_W_SPIRIT_OF_DREAD_TICK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=self._leeching_damage(
                        context,
                        tick_damage,
                        DamageType.MAGIC,
                        active=True,
                    ),
                )
            )
        return tuple(events)

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks after the charged E attack.

        :param context: Snapshot supplying attack speed, damage, and duration.
        :return: Follow-up basic attacks with time-varying Warpath AD.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 400
        events: list[ActionEvent] = []
        for index, at_ms in enumerate(
            range(1800, context.duration_ms + 1, interval_ms),
            start=1,
        ):
            amount = context.snapshot.attack_damage + self._passive_bonus_ad(
                context,
                devastating_charge=at_ms < self._E_END_MS,
            )
            events.append(
                action(
                    f"HECARIM_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=self._leeching_damage(
                        context,
                        amount,
                        DamageType.PHYSICAL,
                        active=at_ms <= self._W_END_MS,
                    ),
                )
            )
        return tuple(events)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Devastating Charge's maximum movement multiplier.

        :param context: Role-bound Hecarim encounter context.
        :return: Maximum E movement multiplier.
        """
        return Decimal("1.65")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Onslaught of Shadows' locked maximum dash range.

        :param context: Role-bound Hecarim encounter context.
        :return: Maximum modeled ultimate dash distance.
        """
        return Decimal(1000)

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Avoid granting Spirit of Dread healing outside combat.

        :param context: Role-bound Hecarim encounter context.
        :param duration_ms: Requested lane observation duration.
        :param no_damage_delay_ms: Delay after taking damage.
        :return: Zero passive sustain and its combat-dependency blocker.
        """
        return Decimal(0), ("HECARIM_W_LANE_HEAL_REQUIRES_NEARBY_DAMAGE",)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Hecarim's deterministic fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Hecarim-scoped blocker, or ``None`` for represented channels.
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
            return f"HECARIM_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the maximum-charge E-R, W, Rampage, and attack fixture.

        :param context: Role-bound Hecarim and opponent snapshots.
        :return: Deterministic damage, healing, defense, and control events.
        """
        base = self._sequence_base(context)
        bonus_ad = self._bonus_ad(context, at_ms=self._E_ATTACK_MS)
        r_damage = Decimal(250) + context.snapshot.ability_power
        e_damage = (
            context.snapshot.attack_damage
            + self._passive_bonus_ad(context, devastating_charge=True)
            + Decimal(60)
            + bonus_ad
        )
        fixed = (
            action(
                "HECARIM_E_DEVASTATING_CHARGE_START",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.MOVEMENT,
                outputs=(
                    movement_speed(
                        context.self_entity,
                        Decimal("0.65") * context.snapshot.move_speed,
                        duration_ms=self._E_END_MS,
                    ),
                    StatusOutput(
                        context.self_entity,
                        "HECARIM_E_GHOSTED",
                        self._E_END_MS,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "HECARIM_R_ONSLAUGHT_MAX_RANGE",
                at_ms=self._R_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    *self._leeching_damage(
                        context,
                        r_damage,
                        DamageType.MAGIC,
                        active=True,
                    ),
                    crowd_control(context.opponent_entity, "FEAR", duration_ms=1500),
                ),
            ),
            action(
                "HECARIM_E_DEVASTATING_CHARGE_MAX_ATTACK",
                at_ms=self._E_ATTACK_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    *self._leeching_damage(
                        context,
                        e_damage,
                        DamageType.PHYSICAL,
                        active=True,
                    ),
                    crowd_control(context.opponent_entity, "KNOCKBACK", duration_ms=500),
                ),
            ),
        )
        events = (
            *fixed,
            *self._q_events(context),
            *self._w_events(context),
            *self._attack_events(context),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"HECARIM_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "hecarim_q5_w5_e1_r2_level13_max_charge_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "HECARIM_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "HECARIM_E_AND_R_MAX_TRAVEL_VARIANTS_ASSUMED",
                "HECARIM_Q_STACK_HIT_AND_REFRESH_ASSUMED",
                "HECARIM_W_LEECH_USES_RAW_INSTEAD_OF_POST_MITIGATION_DAMAGE",
                "HECARIM_W_ALLY_DAMAGE_LEECH_EXCLUDED",
                "HECARIM_W_RESISTANCE_PASSIVE_APPLICATION_TIMING_UNVERIFIED",
                "HECARIM_CAST_ATTACK_AND_TICK_TIMING_UNVERIFIED",
                "HECARIM_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose maximum R fear and E knockback control windows.

        :param context: Role-bound Hecarim and opponent snapshots.
        :return: Causally linked fear and displacement windows.
        """
        return ReactionPlan(
            "hecarim_e1_r2_max_charge_control_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "hecarim_r_max_range_fear",
                    self._R_AT_MS,
                    min(self._R_AT_MS + 1500, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "HECARIM_R_ONSLAUGHT_MAX_RANGE",
                    True,
                    ControlType.FEAR,
                ),
                CastBlockWindow(
                    "hecarim_e_max_charge_knockback",
                    self._E_ATTACK_MS,
                    min(self._E_ATTACK_MS + 500, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "HECARIM_E_DEVASTATING_CHARGE_MAX_ATTACK",
                    False,
                    ControlType.AIRBORNE,
                ),
            ),
            blockers=(
                "HECARIM_R_FEAR_DURATION_USES_MAX_RANGE_VARIANT",
                "HECARIM_E_KNOCKBACK_TRAVEL_GEOMETRY_NOT_MODELED",
                "HECARIM_W_LEECH_USES_RAW_INSTEAD_OF_POST_MITIGATION_DAMAGE",
            ),
        )
