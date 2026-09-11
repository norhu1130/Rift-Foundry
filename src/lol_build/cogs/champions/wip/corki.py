"""Corki combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent, StatModifierOutput, StatusOutput


class CorkiCog(ChampionCog):
    """Model Corki's Q5/W1/E5/R2 level-13 single-target fixture.

    The fixture exposes Rapid Reload's bonus true damage, a closing Valkyrie,
    all sixteen Gatling Gun damage ticks with four flat resistance-shred steps,
    and a preloaded three-missile Barrage sequence whose third shot is The Big
    One. Projectile contact, area occupancy, ammunition history, and recharge
    are assumptions rather than silently manufactured runtime state.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Corki.json",
        "data/raw/16.17.1/communitydragon/champions/42.json",
        "data/raw/16.17.1/communitydragon/champions/corki.bin.json",
    )
    _Q_FIRST_AT_MS = 900
    _W_AT_MS = 100
    _E_AT_MS = 500
    _E_TICKS = 16
    _E_TICK_INTERVAL_MS = 250
    _R_TIMES_MS = (300, 2300, 4300)

    @staticmethod
    def _cooldown_ms(base_seconds: Decimal, ability_haste: Decimal) -> int:
        """Convert a base cooldown through the standard ability-haste formula.

        :param base_seconds: Rank-specific base cooldown in seconds.
        :param ability_haste: Non-negative haste from Corki's snapshot.
        :return: Deterministically rounded cooldown in milliseconds.
        :raises ValueError: If either input is negative.
        """
        if base_seconds < 0 or ability_haste < 0:
            raise ValueError("cooldown inputs cannot be negative")
        return int(
            (base_seconds * Decimal(100_000) / (Decimal(100) + ability_haste)).to_integral_value(
                ROUND_HALF_EVEN
            )
        )

    @staticmethod
    def _critical_multiplier(context: ParticipantContext) -> Decimal:
        """Return deterministic expected damage for Corki's locked 2.0 crits.

        :param context: Snapshot carrying Corki's critical-strike chance.
        :return: Expected multiplier applied to attack and passive damage.
        """
        return Decimal(1) + context.snapshot.critical_strike_chance

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose the maximum locked normal-Valkyrie displacement.

        :param context: Role-bound Corki encounter context.
        :return: Six-hundred-unit maximum dash distance.
        """
        return Decimal(600)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Corki's fixed combat fixture.

        AD, AP, attack speed, critical chance, haste, penetration, movement,
        and chassis defenses reach modeled calculations. Resource expenditure
        and generic sustain are not inferred from the locked spell formulas.

        :param item: Normalized candidate from the locked item catalog.
        :return: Corki-scoped blocker for unsupported stats, otherwise ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "MANA_REGEN",
            "OMNIVAMP",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"CORKI_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks with Rapid Reload's locked bonus true damage.

        :param context: Snapshot supplying attack damage, speed, and crit chance.
        :return: Deterministic basic attacks susceptible to blind and disarm.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        multiplier = self._critical_multiplier(context)
        base = self._sequence_base(context) + 300
        events: list[ActionEvent] = []
        at_ms = 1200
        while at_ms <= context.duration_ms:
            attack_number = len(events) + 1
            events.append(
                action(
                    f"CORKI_RAPID_RELOAD_ATTACK_{attack_number}",
                    at_ms=at_ms,
                    sequence=base + attack_number,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            context.snapshot.attack_damage * multiplier,
                            DamageType.PHYSICAL,
                        ),
                        damage(
                            context.opponent_entity,
                            context.snapshot.attack_damage * Decimal("0.20") * multiplier,
                            DamageType.TRUE,
                        ),
                    ),
                )
            )
            at_ms += interval_ms
        return tuple(events)

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule rank-five Phosphorus Bomb and haste-enabled recasts.

        :param context: Snapshot supplying bonus AD, AP, haste, and entity roles.
        :return: Magic-damage and reveal events within the fixture duration.
        """
        cooldown_ms = self._cooldown_ms(Decimal(7), context.snapshot.ability_haste)
        raw_damage = (
            Decimal(240)
            + Decimal("1.25") * context.snapshot.bonus_attack_damage
            + context.snapshot.ability_power
        )
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = self._Q_FIRST_AT_MS
        while at_ms <= context.duration_ms:
            number = len(events) + 1
            events.append(
                action(
                    f"CORKI_Q_PHOSPHORUS_BOMB_{number}",
                    at_ms=at_ms,
                    sequence=base + number,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, raw_damage, DamageType.MAGIC),
                        StatusOutput(context.opponent_entity, "REVEALED", 6000),
                    ),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def _gatling_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Emit sixteen E ticks and four progressive flat-resistance shreds.

        Each shred modifier shares the locked two-second post-spray expiry by
        receiving the remaining spray time plus two seconds. This represents
        stack refresh without adding a champion-specific timeline primitive.

        :param context: Snapshot supplying bonus AD and participant roles.
        :return: Physical tick events with four five-point shred increments.
        """
        total_damage = Decimal(280) + Decimal("2.40") * context.snapshot.bonus_attack_damage
        per_tick = total_damage / Decimal(self._E_TICKS)
        base = self._sequence_base(context) + 200
        events: list[ActionEvent] = []
        shred_ticks = {0, 4, 8, 12}
        shared_expiry_ms = self._E_AT_MS + 4000 + 2000
        for index in range(self._E_TICKS):
            at_ms = self._E_AT_MS + index * self._E_TICK_INTERVAL_MS
            outputs = [damage(context.opponent_entity, per_tick, DamageType.PHYSICAL)]
            if index in shred_ticks:
                duration_ms = shared_expiry_ms - at_ms
                outputs.extend(
                    (
                        StatModifierOutput(
                            context.opponent_entity, "ARMOR", Decimal(-5), duration_ms
                        ),
                        StatModifierOutput(
                            context.opponent_entity,
                            "MAGIC_RESISTANCE",
                            Decimal(-5),
                            duration_ms,
                        ),
                    )
                )
            events.append(
                action(
                    f"CORKI_E_GATLING_GUN_TICK_{index + 1}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=tuple(outputs),
                )
            )
        return tuple(event for event in events if event.at_ms <= context.duration_ms)

    def _missile_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Create a fixed two-small-one-big rank-two missile sequence.

        :param context: Snapshot supplying bonus AD and participant roles.
        :return: Three assumed-hit physical missile events inside the duration.
        """
        raw_small = Decimal(170) + Decimal("0.85") * context.snapshot.bonus_attack_damage
        base = self._sequence_base(context) + 400
        events: list[ActionEvent] = []
        for index, at_ms in enumerate(self._R_TIMES_MS, start=1):
            if at_ms > context.duration_ms:
                continue
            big_one = index == 3
            events.append(
                action(
                    "CORKI_R_THE_BIG_ONE" if big_one else f"CORKI_R_MISSILE_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            raw_small * (Decimal(2) if big_one else Decimal(1)),
                            DamageType.PHYSICAL,
                        ),
                    ),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Corki's fixed dash, spell, missile, and attack schedule.

        :param context: Role-bound Corki and opponent snapshots.
        :return: Chronological level-13 combat plan with honest assumptions.
        """
        base = self._sequence_base(context)
        w_total = (
            Decimal(150)
            + Decimal(2) * context.snapshot.bonus_attack_damage
            + Decimal("1.50") * context.snapshot.ability_power
        )
        events = (
            action(
                "CORKI_W_VALKYRIE_FULL_TRAIL",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.MOVEMENT,
                outputs=(damage(context.opponent_entity, w_total, DamageType.MAGIC),),
            ),
            *self._q_events(context),
            *self._gatling_events(context),
            *self._missile_events(context),
            *self._attack_events(context),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"CORKI_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "corki_q5_w1_e5_r2_level13_preloaded_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "CORKI_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "CORKI_ROTATION_AND_ANIMATION_TIMING_UNVERIFIED",
                "CORKI_PROJECTILE_HITS_AND_TRAVEL_TIME_ASSUMED",
                "CORKI_W_DASH_DIRECTION_AND_FULL_TRAIL_OCCUPANCY_ASSUMED",
                "CORKI_E_CONE_FACING_AND_ALL_SIXTEEN_TICKS_ASSUMED",
                "CORKI_E_FLAT_SHRED_STACK_TIMING_UNVERIFIED",
                "CORKI_R_STARTS_WITH_THREE_PRELOADED_MISSILES",
                "CORKI_R_AMMO_RECHARGE_AND_ATTACK_REFUND_NOT_MODELED",
                "CORKI_R_AREA_AND_MULTI_TARGET_DAMAGE_NOT_MODELED",
                "CORKI_R_THIRD_SHOT_BIG_ONE_PHASE_ASSUMED",
                "CORKI_RAPID_RELOAD_CRITICAL_TRUE_DAMAGE_INTERACTION_UNVERIFIED",
                "CORKI_PACKAGE_NOT_PRESENT_IN_LOCKED_CLASSIC_SPELL_SET",
                "CORKI_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Return Corki's neutral reaction policy for the fixed fixture.

        Valkyrie is represented as an outgoing engagement action; the locked
        sources do not justify inventing an automatic defensive dash trigger.

        :param context: Role-bound Corki and opponent snapshots.
        :return: Neutral reactions with explicit positioning limitations.
        """
        return ReactionPlan(
            "corki_neutral_reaction_v1",
            blockers=(
                "CORKI_W_REACTIVE_ESCAPE_POLICY_NOT_MODELED",
                "CORKI_PROJECTILE_DODGE_BEHAVIOR_NOT_MODELED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Report that Corki's locked kit supplies no native lane healing.

        :param context: Role-bound Corki encounter context.
        :param duration_ms: Lane observation duration in milliseconds.
        :param no_damage_delay_ms: Delay before out-of-combat recovery may begin.
        :return: Zero extra health and no champion-native sustain blocker.
        """
        return Decimal(0), ()
