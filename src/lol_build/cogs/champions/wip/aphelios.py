"""Aphelios combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class ApheliosCog(ChampionCog):
    """Model one level-13 Gravitum-main Aphelios duel fixture.

    Aphelios cannot have a meaningful weapon-agnostic rotation. This fixture
    therefore fixes Gravitum as the main hand, Calibrum as the unused off hand,
    sufficient Gravitum ammunition, and six AD plus six attack-speed passive
    ranks. Moonlight Vigil supplies the first Gravitum mark, Binding Eclipse
    consumes it, and subsequent attacks exercise Gravitum's normal slow.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Aphelios.json",
        "data/raw/16.17.1/communitydragon/champions/523.json",
        "data/raw/16.17.1/communitydragon/champions/aphelios.bin.json",
    )

    _PASSIVE_AD = Decimal(24)
    _PASSIVE_ATTACK_SPEED = Decimal("0.54")
    _ATTACK_SPEED_RATIO = Decimal("0.658")
    _CRITICAL_DAMAGE_MULTIPLIER = Decimal(2)

    @classmethod
    def _total_ad(cls, context: ParticipantContext) -> Decimal:
        """Include the fixture's six passive AD ranks in total attack damage.

        :param context: Role-bound Aphelios combat context.
        :return: Total attack damage used by attacks in the fixed fixture.
        """
        return context.snapshot.attack_damage + cls._PASSIVE_AD

    @classmethod
    def _bonus_ad(cls, context: ParticipantContext) -> Decimal:
        """Include the fixture's six passive AD ranks in bonus attack damage.

        :param context: Role-bound Aphelios combat context.
        :return: Bonus attack damage consumed by Q and R formulas.
        """
        return context.snapshot.bonus_attack_damage + cls._PASSIVE_AD

    @classmethod
    def _attack_speed(cls, context: ParticipantContext) -> Decimal:
        """Apply six passive attack-speed ranks through the locked AS ratio.

        :param context: Role-bound Aphelios combat context.
        :return: Attacks per second for the fixed passive allocation.
        """
        return context.snapshot.attack_speed + cls._ATTACK_SPEED_RATIO * cls._PASSIVE_ATTACK_SPEED

    @classmethod
    def _expected_critical_multiplier(cls, context: ParticipantContext) -> Decimal:
        """Convert random critical strikes to deterministic expected damage.

        :param context: Snapshot containing item critical-strike chance.
        :return: Expected multiplier for an ordinary weapon attack.
        """
        return Decimal(1) + context.snapshot.critical_strike_chance * (
            cls._CRITICAL_DAMAGE_MULTIPLIER - Decimal(1)
        )

    @classmethod
    def _gravitum_attack(
        cls,
        context: ParticipantContext,
        *,
        event_id: str,
        at_ms: int,
        sequence: int,
        slow: Decimal = Decimal("0.30"),
    ) -> ActionEvent:
        """Create one blind-susceptible Gravitum attack and its slow.

        :param context: Role-bound Aphelios and opponent snapshots.
        :param event_id: Stable champion-scoped event identifier.
        :param at_ms: Attack timestamp within the benchmark.
        :param sequence: Stable ordering key for equal timestamps.
        :param slow: Slow magnitude applied by this Gravitum attack.
        :return: Atomic basic-attack event with damage and crowd control.
        """
        return action(
            event_id,
            at_ms=at_ms,
            sequence=sequence,
            source=context.self_entity,
            channel=ActionChannel.BASIC_ATTACK,
            outputs=(
                damage(
                    context.opponent_entity,
                    cls._total_ad(context) * cls._expected_critical_multiplier(context),
                    DamageType.PHYSICAL,
                ),
                crowd_control(
                    context.opponent_entity,
                    "SLOW",
                    duration_ms=2500,
                    magnitude=slow,
                ),
            ),
        )

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the fixed Gravitum timeline.

        AD, AP, attack speed, critical chance, penetration, defenses, movement,
        and tenacity reach the modeled formula or shared combat engine. The
        schedule does not spend mana, reschedule spells with haste, or convert
        dealt damage into item sustain.

        :param item: Normalized candidate from the locked item catalog.
        :return: Aphelios-scoped blocker or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"APHELIOS_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Keep self speed neutral while Gravitum controls the opponent.

        The fixed weapon has no self-mobility. Its slows and root appear on the
        timeline, while their effect on approach distance is kept as a blocker.

        :param context: Role-bound snapshots for the current encounter.
        :return: Neutral pursuit-speed multiplier.
        """
        return Decimal(1)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build R2, its Gravitum attack, Q, and sustained Gravitum attacks.

        The R follow-up supplies a deterministic mark before Q. R initial damage
        uses the locked 30-percent critical-effect modifier, whereas weapon
        attacks use expected ordinary critical damage. No weapon is depleted or
        swapped during the eight-second fixture.

        :param context: Role-bound snapshots for Aphelios and his opponent.
        :return: Chronological Gravitum-main schedule with honest boundaries.
        """
        base = self._sequence_base(context)
        events: list[ActionEvent] = []
        if context.duration_ms >= 100:
            r_critical_multiplier = Decimal(1) + Decimal("0.30") * (
                context.snapshot.critical_strike_chance
                * (self._CRITICAL_DAMAGE_MULTIPLIER - Decimal(1))
            )
            events.append(
                action(
                    "APHELIOS_R_MOONLIGHT_VIGIL",
                    at_ms=100,
                    sequence=base + 1,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            (
                                Decimal(175)
                                + Decimal("0.20") * self._bonus_ad(context)
                                + context.snapshot.ability_power
                            )
                            * r_critical_multiplier,
                            DamageType.PHYSICAL,
                        ),
                    ),
                )
            )
        if context.duration_ms >= 350:
            events.append(
                self._gravitum_attack(
                    context,
                    event_id="APHELIOS_R_GRAVITUM_FOLLOWUP_ATTACK",
                    at_ms=350,
                    sequence=base + 2,
                    slow=Decimal("0.99"),
                )
            )
        if context.duration_ms >= 700:
            events.append(
                action(
                    "APHELIOS_Q_BINDING_ECLIPSE",
                    at_ms=700,
                    sequence=base + 3,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal(140)
                            + Decimal("0.50") * self._bonus_ad(context)
                            + Decimal("0.70") * context.snapshot.ability_power,
                            DamageType.PHYSICAL,
                        ),
                        crowd_control(
                            context.opponent_entity,
                            "ROOT",
                            duration_ms=1000,
                        ),
                    ),
                )
            )

        interval_ms = self._attack_interval_ms(self._attack_speed(context))
        at_ms = 1800
        attack_index = 1
        while at_ms <= context.duration_ms:
            events.append(
                self._gravitum_attack(
                    context,
                    event_id=f"APHELIOS_GRAVITUM_ATTACK_{attack_index}",
                    at_ms=at_ms,
                    sequence=base + 100 + attack_index,
                )
            )
            attack_index += 1
            at_ms += interval_ms

        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"APHELIOS_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "aphelios_gravitum_calibrum_l13_locked_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "APHELIOS_LEVEL13_PASSIVE_6AD_6AS_1LETHALITY_POLICY_UNVERIFIED",
                "APHELIOS_PASSIVE_LETHALITY_RANK_NOT_INTEGRATED",
                "APHELIOS_GRAVITUM_MAIN_CALIBRUM_OFFHAND_ASSUMED",
                "APHELIOS_WEAPON_AMMUNITION_AND_QUEUE_NOT_MODELED",
                "APHELIOS_WEAPON_SWAP_AND_OFFHAND_COMBINATIONS_NOT_MODELED",
                "APHELIOS_CALIBRUM_SEVERUM_INFERNUM_CRESCENDUM_ACTIONS_NOT_MODELED",
                "APHELIOS_R_PROJECTILE_HIT_AND_TRAVEL_UNVERIFIED",
                "APHELIOS_R_FOLLOWUP_ATTACK_TIMING_AND_CRIT_UNVERIFIED",
                "APHELIOS_Q_REQUIRES_RESOLVED_GRAVITUM_MARK_NOT_CAUSALLY_GATED",
                "APHELIOS_Q_HIT_AND_CAST_TIMING_UNVERIFIED",
                "APHELIOS_GRAVITUM_SLOW_APPROACH_EFFECT_NOT_INTEGRATED",
                "APHELIOS_SEVERUM_NATIVE_SUSTAIN_OUTSIDE_FIXED_FIXTURE",
                "APHELIOS_MANA_AND_WEAPON_AMMO_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Binding Eclipse's reducible movement-block interval.

        Gravitum slows remain status outputs because the shared engine does not
        yet translate opponent slow magnitude into approach distance.

        :param context: Role-bound snapshots for Aphelios and his opponent.
        :return: Q root window linked to its source action event.
        """
        windows = (
            (
                CastBlockWindow(
                    "aphelios_q_gravitum_root",
                    700,
                    min(1700, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "APHELIOS_Q_BINDING_ECLIPSE",
                    True,
                    ControlType.ROOT,
                ),
            )
            if context.duration_ms > 700
            else ()
        )
        return ReactionPlan(
            "aphelios_gravitum_q_root_reaction_v1",
            cast_block_windows=windows,
            blockers=(
                "APHELIOS_Q_REQUIRES_RESOLVED_GRAVITUM_MARK_NOT_CAUSALLY_GATED",
                "APHELIOS_GRAVITUM_SLOW_APPROACH_EFFECT_NOT_INTEGRATED",
            ),
        )
