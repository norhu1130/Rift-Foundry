"""Syndra combat Cog backed by the locked 16.17.1 champion sources."""

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


class SyndraCog(ChampionCog):
    """Model Syndra's Q5/E5/W1/R2 level-13 single-target rotation.

    The policy uses the sixty Splinters of Wrath guaranteed by level gains at
    level thirteen. Consequently Q has two charges and W adds upgraded true
    damage, while E's eighty-splinter slow and R's execute remain inactive. The
    fixed Q-E-W-Q-R sequence places two spheres before R, so R launches five
    spheres including the three orbiting Syndra.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Syndra.json",
        "data/raw/16.17.1/communitydragon/champions/134.json",
        "data/raw/16.17.1/communitydragon/champions/syndra.bin.json",
    )

    @staticmethod
    def _w_true_damage(magic_damage: Decimal, ability_power: Decimal) -> Decimal:
        """Calculate Force of Will's sixty-splinter bonus true damage.

        The locked calculation multiplies W's pre-mitigation spell damage by
        twelve percent plus two percentage points per one hundred ability power.

        :param magic_damage: Raw magic damage produced by the W throw formula.
        :param ability_power: Syndra's aggregated ability power.
        :return: Raw true damage added by the upgraded passive.
        """
        multiplier = Decimal("0.12") + Decimal("0.0002") * ability_power
        return magic_damage * multiplier

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Syndra's fixed event policy.

        Ability haste and mana cannot alter the fixed schedule, critical strikes
        are not sampled, and attack healing is not resolved by plain damage
        events. AP, penetration, chassis, movement, AD, and attack speed reach a
        shared snapshot or a modeled output.

        :param item: Normalized candidate from the locked item catalog.
        :return: Syndra-scoped blocker for unsupported stats, otherwise ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "CRITICAL_STRIKE_CHANCE",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"SYNDRA_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks without inventing spell-passive damage.

        :param context: Role-bound snapshots supplying attack damage and cadence.
        :return: Deterministic physical basic attacks through the duel duration.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        sequence = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 400
        index = 1
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"SYNDRA_BASIC_ATTACK_{index}",
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
        """Build the fixed five-sphere burst and one late Q recharge.

        Q's first charge creates the sphere pushed by E and subsequently thrown
        by W. The second charge creates another sphere before R. Rank-two R
        grants Q twenty intrinsic ability haste, allowing the first spent charge
        to return after 5.833 seconds and produce a third Q near six seconds.

        :param context: Role-bound Syndra and opponent combat snapshots.
        :return: Deterministic spell and attack events with unresolved assumptions.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        q_damage = Decimal(230) + Decimal("0.70") * ap
        w_magic_damage = Decimal(70) + Decimal("0.65") * ap
        e_damage = Decimal(200) + Decimal("0.60") * ap
        r_per_sphere = Decimal(120) + Decimal("0.20") * ap
        spell_events = (
            action(
                "SYNDRA_Q_DARK_SPHERE_1",
                at_ms=100,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.MAGIC),),
            ),
            action(
                "SYNDRA_E_SCATTER_THE_WEAK_SPHERE_STUN",
                at_ms=450,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=1250),
                ),
            ),
            action(
                "SYNDRA_W_FORCE_OF_WILL_THROW",
                at_ms=900,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, w_magic_damage, DamageType.MAGIC),
                    damage(
                        context.opponent_entity,
                        self._w_true_damage(w_magic_damage, ap),
                        DamageType.TRUE,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=1500,
                        magnitude=Decimal("0.25"),
                    ),
                ),
            ),
            action(
                "SYNDRA_Q_DARK_SPHERE_2",
                at_ms=1250,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.MAGIC),),
            ),
            action(
                "SYNDRA_R_UNLEASHED_POWER_FIVE_SPHERES",
                at_ms=1800,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(5) * r_per_sphere,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "SYNDRA_Q_DARK_SPHERE_3_RECHARGE",
                at_ms=6000,
                sequence=base + 5,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.MAGIC),),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"SYNDRA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "syndra_q5_e5_w1_r2_level13_five_sphere_v1",
            tuple(
                sorted(
                    (*spell_events, *self._basic_attacks(context)),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "SYNDRA_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "SYNDRA_LEVEL_DERIVED_SIXTY_SPLINTERS_ASSUMED",
                "SYNDRA_COMBAT_EARNED_SPLINTERS_NOT_MODELED",
                "SYNDRA_SPHERE_GEOMETRY_NOT_MODELED",
                "SYNDRA_W_SPHERE_PICKUP_AND_THROW_TIMING_UNVERIFIED",
                "SYNDRA_R_FIVE_SPHERE_PROXIMITY_ASSUMED",
                "SYNDRA_MULTI_TARGET_EFFECTS_NOT_MODELED",
                "SYNDRA_E_KNOCKBACK_NOT_MODELED",
                "SYNDRA_R_EXECUTE_THRESHOLD_NOT_MODELED",
                "SYNDRA_FULL_TRANSCENDENT_AP_BONUS_NOT_MODELED",
                "SYNDRA_CAST_AND_PROJECTILE_TIMING_UNVERIFIED",
                "SYNDRA_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the sphere stun and W slow as source-linked control windows.

        :param context: Role-bound snapshots identifying Syndra's opponent.
        :return: Tenacity-reducible stun and movement-slow intervals.
        """
        return ReactionPlan(
            "syndra_e_stun_w_slow_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "syndra_e_sphere_stun",
                    450,
                    min(1700, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY),
                    "SYNDRA_E_SCATTER_THE_WEAK_SPHERE_STUN",
                    True,
                    ControlType.STUN,
                ),
                CastBlockWindow(
                    "syndra_w_force_of_will_slow",
                    900,
                    min(2400, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "SYNDRA_W_FORCE_OF_WILL_THROW",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=(
                "SYNDRA_E_SPHERE_ALIGNMENT_ASSUMED",
                "SYNDRA_E_KNOCKBACK_NOT_MODELED",
                "SYNDRA_MOVEMENT_SLOW_NOT_INTEGRATED_IN_TIMELINE",
                "SYNDRA_CONTROL_HIT_TIMING_UNVERIFIED",
            ),
        )
