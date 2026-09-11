"""Brand combat Cog backed by the locked 16.17.1 champion sources."""

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


class BrandCog(ChampionCog):
    """Model Brand's W5/Q5/E1/R2 level-13 single-target rotation.

    The fixed E-Q-W-R policy deliberately opens with E so Q receives its
    Ablaze stun and W receives its twenty-five-percent damage amplification.
    W supplies the third Blaze stack, and the resulting detonation resolves two
    seconds later. Only R's guaranteed first hit is counted: additional bounces
    require nearby-unit geometry that the duel scenario does not describe.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Brand.json",
        "data/raw/16.17.1/communitydragon/champions/63.json",
        "data/raw/16.17.1/communitydragon/champions/brand.bin.json",
    )

    @staticmethod
    def _explosion_ratio(level: int, ability_power: Decimal) -> Decimal:
        """Resolve Blaze's champion maximum-health explosion ratio.

        The locked calculation interpolates from six to twelve percent over
        champion levels one through eighteen, then adds two percentage points
        per one hundred ability power.

        :param level: Brand's champion level in the supported one-to-eighteen range.
        :param ability_power: Brand's aggregated ability power.
        :return: Fraction of the victim's maximum health dealt as magic damage.
        """
        bounded_level = min(18, max(1, level))
        level_percent = Decimal(6) + (Decimal(6) * Decimal(bounded_level - 1) / Decimal(17))
        return level_percent / Decimal(100) + Decimal("0.0002") * ability_power

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Brand's fixed event schedule.

        Ability haste cannot reschedule this one-cast-per-spell policy. Mana and
        combat healing are likewise not resolved, while AP, penetration, chassis
        stats, AD, and attack speed reach modeled snapshot or event channels.

        :param item: Normalized candidate from the locked item catalog.
        :return: Brand-scoped blocker for unsupported stats, otherwise ``None``.
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
            return f"BRAND_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks after the opening spell sequence.

        :param context: Role-bound snapshots supplying attack damage and cadence.
        :return: Deterministic physical basic attacks through the duel duration.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        sequence = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 1400
        index = 1
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"BRAND_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=sequence + index,
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
            index += 1
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Brand's fixed enhanced combo, Blaze ticks, and detonation.

        Blaze damage is represented as two synchronized one-second ticks after
        all three applications. This preserves stack scaling in the common event
        timeline without claiming an unverified server tick phase.

        :param context: Role-bound Brand and opponent combat snapshots.
        :return: Deterministic damage and status events with evidence blockers.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        opponent_hp = context.opponent_snapshot.max_hp
        e_damage = Decimal(55) + Decimal("0.60") * ap
        q_damage = Decimal(190) + Decimal("0.65") * ap
        w_damage = (Decimal(255) + Decimal("0.70") * ap) * Decimal("1.25")
        r_damage = Decimal(175) + Decimal("0.30") * ap
        blaze_tick = opponent_hp * Decimal("0.02") * Decimal(3) / Decimal(4)
        explosion = opponent_hp * self._explosion_ratio(context.snapshot.level, ap)
        spell_events = (
            action(
                "BRAND_E_CONFLAGRATION_APPLY_BLAZE_1",
                at_ms=100,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, e_damage, DamageType.MAGIC),),
            ),
            action(
                "BRAND_Q_SEAR_ABLAZE_STUN_APPLY_BLAZE_2",
                at_ms=400,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q_damage, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=1750),
                ),
            ),
            action(
                "BRAND_W_PILLAR_EMPOWERED_APPLY_BLAZE_3",
                at_ms=700,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, w_damage, DamageType.MAGIC),),
            ),
            action(
                "BRAND_R_PYROCLASM_INITIAL_ABLAZE_HIT",
                at_ms=1000,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=250,
                        magnitude=Decimal("0.45"),
                    ),
                ),
            ),
            action(
                "BRAND_PASSIVE_BLAZE_THREE_STACK_TICK_1",
                at_ms=1100,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(damage(context.opponent_entity, blaze_tick, DamageType.MAGIC),),
            ),
            action(
                "BRAND_PASSIVE_BLAZE_THREE_STACK_TICK_2",
                at_ms=2100,
                sequence=base + 5,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(damage(context.opponent_entity, blaze_tick, DamageType.MAGIC),),
            ),
            action(
                "BRAND_PASSIVE_BLAZE_THREE_STACK_EXPLOSION",
                at_ms=2700,
                sequence=base + 6,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(damage(context.opponent_entity, explosion, DamageType.MAGIC),),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"BRAND_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "brand_w5_q5_e1_r2_level13_three_stack_v1",
            tuple(
                sorted(
                    (*spell_events, *self._basic_attacks(context)),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "BRAND_LEVEL13_W5_Q5_E1_R2_POLICY_UNVERIFIED",
                "BRAND_E_Q_W_HIT_SEQUENCE_ASSUMED",
                "BRAND_CAST_AND_PROJECTILE_TIMING_UNVERIFIED",
                "BRAND_PASSIVE_TICK_PHASE_AND_REFRESH_UNVERIFIED",
                "BRAND_PASSIVE_POST_DETONATION_LOCKOUT_NOT_MODELED",
                "BRAND_R_REPEAT_BOUNCES_REQUIRE_UNIT_GEOMETRY",
                "BRAND_R_ONLY_GUARANTEED_INITIAL_HIT_MODELED",
                "BRAND_MULTI_TARGET_SPREAD_AND_EXPLOSION_NOT_MODELED",
                "BRAND_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose enhanced Q stun and Ablaze-enhanced R slow windows.

        :param context: Role-bound snapshots identifying Brand's opponent.
        :return: Source-linked, tenacity-reducible control windows.
        """
        return ReactionPlan(
            "brand_ablaze_control_level13_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "brand_q_ablaze_stun",
                    400,
                    min(2150, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY),
                    "BRAND_Q_SEAR_ABLAZE_STUN_APPLY_BLAZE_2",
                    True,
                    ControlType.STUN,
                ),
                CastBlockWindow(
                    "brand_r_ablaze_slow",
                    1000,
                    min(1250, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "BRAND_R_PYROCLASM_INITIAL_ABLAZE_HIT",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=(
                "BRAND_E_Q_W_HIT_SEQUENCE_ASSUMED",
                "BRAND_Q_STUN_TENACITY_RUNTIME_UNVERIFIED",
                "BRAND_R_SLOW_TENACITY_RUNTIME_UNVERIFIED",
            ),
        )
