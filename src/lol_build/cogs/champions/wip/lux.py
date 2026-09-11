"""Lux combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class LuxCog(ChampionCog):
    """Model Lux's E5/Q5/W1/R2 level-13 single-target spell rotation.

    The fixed sequence consumes Q's Illumination mark with an attack, consumes
    E's mark with Final Spark, and consumes the mark refreshed by Final Spark
    with the next attack. This preserves the locked passive relationships while
    leaving conditional mark state and projectile geometry explicit blockers.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Lux.json",
        "data/raw/16.17.1/communitydragon/champions/99.json",
        "data/raw/16.17.1/communitydragon/champions/lux.bin.json",
    )

    @staticmethod
    def _illumination_damage(level: int, ability_power: Decimal) -> Decimal:
        """Calculate the locked Illumination damage at a champion level.

        CommunityDragon stores a by-character-level curve equal to twenty plus
        ten per champion level and an additional 35 percent AP ratio.

        :param level: Lux's champion level in the current combat snapshot.
        :param ability_power: Lux's ability power after item aggregation.
        :return: Raw magic damage dealt when an Illumination mark is consumed.
        """
        return Decimal(20 + 10 * level) + Decimal("0.35") * ability_power

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Lux's fixed rotation.

        AP, attack damage, attack speed, defenses, penetration, movement, and
        tenacity reach the shared snapshot or modeled events. Haste and resource
        stats cannot change the fixed spell policy. Plain attacks deal expected
        critical-strike damage, and heal and shield power amplifies the shield,
        both through the shared engine.

        :param item: Normalized candidate item from the locked item catalog.
        :return: Lux-scoped blocker for unsupported stats, otherwise ``None``.
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
            return f"LUX_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Build two marked attacks followed by ordinary ranged attacks.

        The first attack consumes Q's mark. The second consumes the mark that
        Final Spark refreshes after consuming E's mark. Later attacks carry no
        passive damage because no further damaging spell is available inside
        the eight-second level-13 fixture.

        :param context: Role-bound snapshots supplying Lux's AD, AP, and cadence.
        :return: Deterministic basic-attack events through the duel duration.
        """
        base = self._sequence_base(context) + 100
        illumination = self._illumination_damage(
            context.snapshot.level,
            context.snapshot.ability_power,
        )
        attacks = [
            action(
                "LUX_PASSIVE_ILLUMINATION_Q_ATTACK",
                at_ms=500,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity,
                        context.snapshot.attack_damage,
                        DamageType.PHYSICAL,
                    ),
                    damage(context.opponent_entity, illumination, DamageType.MAGIC),
                ),
            ),
            action(
                "LUX_PASSIVE_ILLUMINATION_R_ATTACK",
                at_ms=2400,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=(
                    damage(
                        context.opponent_entity,
                        context.snapshot.attack_damage,
                        DamageType.PHYSICAL,
                    ),
                    damage(context.opponent_entity, illumination, DamageType.MAGIC),
                ),
            ),
        ]
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        at_ms = 2400 + interval_ms
        index = 1
        while at_ms <= context.duration_ms:
            attacks.append(
                action(
                    f"LUX_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 1 + index,
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
        return tuple(attacks)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Q, E, R, W, Illumination, and follow-up attack events.

        Q and E are assumed to hit the single benchmark opponent. E is detonated
        after four hundred milliseconds. W grants Lux one outbound and one
        returning self shield. Shielding other allies needs trajectory and ally
        geometry not present in the two-combatant scenario.

        :param context: Role-bound Lux and opponent combat snapshots.
        :return: Locked spell outputs and explicit unresolved assumptions.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        illumination = self._illumination_damage(context.snapshot.level, ap)
        q_damage = Decimal(240) + Decimal("0.75") * ap
        e_damage = Decimal(265) + Decimal("0.80") * ap
        r_damage = Decimal(400) + Decimal("1.20") * ap
        w_shield = Decimal(40) + Decimal("0.40") * ap
        fixed_events = (
            action(
                "LUX_Q_LIGHT_BINDING",
                at_ms=100,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q_damage, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "ROOT", duration_ms=2000),
                ),
            ),
            action(
                "LUX_E_LUCENT_SINGULARITY_ZONE",
                at_ms=700,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=1400,
                        magnitude=Decimal("0.45"),
                    ),
                ),
            ),
            action(
                "LUX_E_LUCENT_SINGULARITY_DETONATE",
                at_ms=1100,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, e_damage, DamageType.MAGIC),),
            ),
            action(
                "LUX_R_FINAL_SPARK",
                at_ms=1800,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, illumination, DamageType.MAGIC),
                    damage(context.opponent_entity, r_damage, DamageType.MAGIC),
                ),
            ),
            action(
                "LUX_W_PRISMATIC_BARRIER_OUTBOUND_SELF",
                at_ms=2700,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(shielding(context.self_entity, w_shield, duration_ms=2500),),
                requires_living_opponent=False,
            ),
            action(
                "LUX_W_PRISMATIC_BARRIER_RETURN_SELF",
                origin_event_id="LUX_W_PRISMATIC_BARRIER_OUTBOUND_SELF",
                at_ms=3700,
                sequence=base + 5,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(shielding(context.self_entity, w_shield, duration_ms=2500),),
                requires_living_opponent=False,
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"LUX_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "lux_e5_q5_w1_r2_level13_locked_v1",
            tuple(
                sorted(
                    (*fixed_events, *self._attack_events(context)),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "LUX_LEVEL13_E5_Q5_W1_R2_POLICY_UNVERIFIED",
                "LUX_ROTATION_AND_SKILLSHOT_HIT_TIMING_UNVERIFIED",
                "LUX_ILLUMINATION_MARK_STATE_NOT_CAUSALLY_MODELED",
                "LUX_E_DETONATION_TIMING_UNVERIFIED",
                "LUX_E_MULTI_TARGET_AND_ZONE_POSITIONING_NOT_MODELED",
                "LUX_Q_SECOND_TARGET_NOT_MODELED",
                "LUX_R_MULTI_TARGET_NOT_MODELED",
                "LUX_W_RETURN_TIMING_UNVERIFIED",
                "LUX_W_ALLY_GEOMETRY_NOT_MODELED",
                "LUX_RANGED_SPELL_REACH_NOT_CONNECTED_TO_ENGAGEMENT_MODEL",
                "LUX_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Light Binding root and Lucent Singularity slow windows.

        Root blocks movement rather than attacks or ordinary spell casts. The E
        window covers four hundred milliseconds before deterministic detonation
        plus the locked one-second lingering slow after leaving the zone.

        :param context: Role-bound snapshots identifying Lux's opponent.
        :return: Source-linked, tenacity-reducible movement-control windows.
        """
        return ReactionPlan(
            "lux_q_root_e_slow_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "lux_q_light_binding_root",
                    100,
                    min(2100, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "LUX_Q_LIGHT_BINDING",
                    True,
                    ControlType.ROOT,
                ),
                CastBlockWindow(
                    "lux_e_lucent_singularity_slow",
                    700,
                    min(2100, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "LUX_E_LUCENT_SINGULARITY_ZONE",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=(
                "LUX_Q_PROJECTILE_HIT_TIMING_UNVERIFIED",
                "LUX_E_DETONATION_AND_LINGER_TIMING_UNVERIFIED",
                "LUX_MOVEMENT_SPEED_REDUCTION_NOT_INTEGRATED_IN_TIMELINE",
            ),
        )
