"""Nilah combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, damage, movement_speed
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    DamageModifierWindow,
    DamageOutput,
    StatusOutput,
)


class NilahCog(ChampionCog):
    """Model Nilah's Q5/W1/E5/R2 level-13 close-range rotation.

    The fixture spends both Slipstream charges, lands Formless Blade, activates
    Jubilant Veil, and resolves Apotheosis before continuing Q-empowered basic
    attacks. Critical chance deterministically affects Q, attacks, and Nilah's
    spell-local armor penetration.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Nilah.json",
        "data/raw/16.17.1/communitydragon/champions/895.json",
        "data/raw/16.17.1/communitydragon/champions/nilah.bin.json",
    )

    _Q_AT_MS = 200
    _W_AT_MS = 300
    _R_AT_MS = 1000

    @staticmethod
    def _passive_armor_penetration(context: ParticipantContext) -> Decimal:
        """Calculate Formless Blade's armor penetration from critical chance.

        :param context: Nilah snapshot containing item critical-strike chance.
        :return: Event-local armor penetration fraction for physical outputs.
        """
        return Decimal("0.30") * context.snapshot.critical_strike_chance

    @staticmethod
    def _expected_critical_multiplier(context: ParticipantContext) -> Decimal:
        """Convert locked 2.0 critical strikes into deterministic expectation.

        :param context: Nilah snapshot containing critical-strike chance.
        :return: Expected multiplier for ordinary critical-capable attacks.
        """
        return Decimal(1) + context.snapshot.critical_strike_chance

    @staticmethod
    def _q_attack_speed_bonus(level: int) -> Decimal:
        """Interpolate the locked Q attack-speed bonus from level 1 to 18.

        :param level: Champion level in the inclusive range 1 through 18.
        :return: Fractional attack-speed bonus granted after Q hits.
        """
        bounded = min(18, max(1, level))
        return (Decimal(10) + Decimal(50) * Decimal(bounded - 1) / Decimal(17)) / Decimal(100)

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule post-ultimate attacks across Q-buffed and normal cadence.

        :param context: Role-bound Nilah encounter context.
        :return: Chronological expected-damage basic attacks.
        """
        penetration = self._passive_armor_penetration(context)
        amount = context.snapshot.attack_damage * self._expected_critical_multiplier(context)
        q_expires_at = self._Q_AT_MS + 4000
        at_ms = 2200
        sequence = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"NILAH_Q_EMPOWERED_BASIC_ATTACK_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=sequence + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            amount,
                            DamageType.PHYSICAL,
                            percent_resistance_penetration=penetration,
                        ),
                    ),
                )
            )
            attack_speed = context.snapshot.attack_speed
            if at_ms < q_expires_at:
                attack_speed *= Decimal(1) + self._q_attack_speed_bonus(context.snapshot.level)
            at_ms += self._attack_interval_ms(attack_speed)
        return tuple(events)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Jubilant Veil's rank-one pursuit-speed multiplier.

        :param context: Role-bound Nilah encounter context.
        :return: Fifteen-percent movement-speed multiplier.
        """
        return Decimal("1.15")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose one Slipstream target dash for engagement scoring.

        :param context: Role-bound Nilah encounter context.
        :return: Locked dash range in game units.
        """
        return Decimal(600)

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Avoid inventing Q lifesteal without champion-hit damage attribution.

        :param context: Role-bound Nilah lane context.
        :param duration_ms: Requested lane observation duration.
        :param no_damage_delay_ms: Time since the last incoming damage event.
        :return: Zero recovery and the state needed for a later model.
        """
        return Decimal(0), ("NILAH_Q_SUSTAIN_REQUIRES_CHAMPION_DAMAGE_AND_CURRENT_HEALTH",)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item value channels absent from Nilah's selected fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Nilah-scoped blocker, or ``None`` for represented channels.
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
        return (
            f"NILAH_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
            if unsupported
            else None
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build two dashes, Q, W, Apotheosis, and expected basic attacks.

        :param context: Role-bound level-13 Nilah encounter context.
        :return: Deterministic action plan with explicit unresolved mechanics.
        """
        ad = context.snapshot.attack_damage
        bonus_ad = context.snapshot.bonus_attack_damage
        crit = context.snapshot.critical_strike_chance
        penetration = self._passive_armor_penetration(context)
        base = self._sequence_base(context)

        def physical(amount: Decimal) -> DamageOutput:
            """Create Nilah physical damage with Q-passive penetration.

            :param amount: Raw physical damage before target mitigation.
            :return: Output carrying Nilah's critical-derived armor penetration.
            """
            return damage(
                context.opponent_entity,
                amount,
                DamageType.PHYSICAL,
                percent_resistance_penetration=penetration,
            )

        e_damage = Decimal(100) + Decimal("0.20") * bonus_ad
        q_damage = (Decimal(40) + ad) * (Decimal(1) + Decimal("0.70") * crit)
        r_tick = Decimal(25) + Decimal("0.10") * bonus_ad
        r_burst = Decimal(225) + bonus_ad
        fixed = (
            action(
                "NILAH_E_SLIPSTREAM_CHARGE_1",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.MOVEMENT,
                outputs=(physical(e_damage),),
            ),
            action(
                "NILAH_Q_FORMLESS_BLADE",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    physical(q_damage),
                    StatusOutput(context.self_entity, "NILAH_Q_ATTACK_BUFF", 4000),
                ),
            ),
            action(
                "NILAH_W_JUBILANT_VEIL",
                at_ms=self._W_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    movement_speed(
                        context.self_entity,
                        context.snapshot.move_speed * Decimal("0.15"),
                        duration_ms=2250,
                    ),
                    StatusOutput(context.self_entity, "NILAH_W_ATTACK_DODGE", 2250),
                ),
                requires_living_opponent=False,
            ),
            action(
                "NILAH_E_SLIPSTREAM_CHARGE_2",
                at_ms=800,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.MOVEMENT,
                outputs=(physical(e_damage),),
            ),
            *tuple(
                action(
                    f"NILAH_R_APOTHEOSIS_SPIN_{index + 1}",
                    at_ms=self._R_AT_MS + index * 200,
                    sequence=base + 4 + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(physical(r_tick),),
                )
                for index in range(4)
            ),
            action(
                "NILAH_R_APOTHEOSIS_BURST",
                at_ms=2000,
                sequence=base + 8,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(physical(r_burst),),
            ),
        )
        events = (*fixed, *self._attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"NILAH_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "nilah_q5_w1_e5_r2_two_charge_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "NILAH_LEVEL13_Q5_E5_W1_R2_ORDER_LOCKED_UNVERIFIED",
                "NILAH_E_TWO_CHARGES_ASSUMED_AVAILABLE_AT_ENCOUNTER_START",
                "NILAH_R_FOUR_TOOLTIP_TICKS_AND_FINAL_BURST_MAPPING_UNVERIFIED",
                "NILAH_R_POST_MITIGATION_HEAL_AND_OVERHEAL_SHIELD_NOT_MODELED",
                "NILAH_Q_ATTACK_HEAL_AND_OVERHEAL_SHIELD_NOT_MODELED",
                "NILAH_Q_CONE_HAS_ONE_CHAMPION_TARGET",
                "NILAH_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose W magic mitigation and the final Apotheosis displacement.

        :param context: Role-bound Nilah and opponent snapshots.
        :return: Defensive magic-damage and hostile pull windows.
        """
        return ReactionPlan(
            "nilah_w1_r2_reaction_v1",
            damage_windows=(
                DamageModifierWindow(
                    "nilah_w_magic_damage_reduction",
                    self._W_AT_MS,
                    min(self._W_AT_MS + 2250, context.duration_ms),
                    context.self_entity,
                    (DamageType.MAGIC,),
                    Decimal("0.75"),
                ),
            ),
            cast_block_windows=(
                CastBlockWindow(
                    "nilah_r_apotheosis_pull",
                    2000,
                    min(2500, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "NILAH_R_APOTHEOSIS_BURST",
                    False,
                    ControlType.AIRBORNE,
                ),
            ),
            blockers=(
                "NILAH_W_BASIC_ATTACK_DODGE_REQUIRES_CHANNEL_SCOPED_DAMAGE_IMMUNITY",
                "NILAH_R_PULL_DURATION_SYNTHETIC_UNVERIFIED",
                "NILAH_W_ALLY_SHARING_OUT_OF_DUEL_SCOPE",
            ),
        )
