"""Jax combat Cog for the locked level-13 duel benchmark."""

from __future__ import annotations

from decimal import Decimal

from lol_build.cogs.base import (
    ActionPlan,
    CastBlockWindow,
    ChampionCog,
    CogCapability,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class JaxCog(ChampionCog):
    """Model Jax's sustained attacks, Empower, Counter Strike, and R passive."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = frozenset(
        {
            CogCapability.BASIC_ATTACK,
            CogCapability.ABILITY_ROTATION,
            CogCapability.REACTION_MODEL,
            CogCapability.ENGAGEMENT,
            CogCapability.ITEM_POLICY,
            CogCapability.RECOMMENDATION,
        }
    )
    evidence_refs = (
        "data/curated/champions/24.json",
        "data/raw/16.17.1/en_US/champion/Jax.json",
        "data/raw/16.17.1/communitydragon/champions/24.json",
        "data/raw/16.17.1/communitydragon/champions/jax.bin.json",
    )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Leap Strike's locked cast range as approach displacement.

        :param context: Role-bound snapshots for the encounter being evaluated.
        :return: Maximum single-target Leap Strike distance in game units.
        """
        return Decimal(700)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats whose combat value is absent from this rotation.

        Defensive stats, attack speed, attack damage, ability power, penetration,
        movement, tenacity, health regeneration, and lane lifesteal are evaluated
        by the shared engine. Ability haste and mana need resource-aware spell
        scheduling, while critical strikes and omnivamp need output attribution.

        :param item: Normalized item candidate from the locked catalog.
        :return: A champion-scoped blocker for unsupported stats, otherwise ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "CRITICAL_STRIKE_CHANCE",
            "MANA",
            "OMNIVAMP",
        } & stats.keys()
        if unsupported:
            return f"JAX_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Create regular attacks and rank-five Empower attack resets.

        Empower attacks are inserted between the continuous attack-speed schedule
        and share its consecutive-hit counter for Grandmaster-at-Arms procs.

        :param context: Role-bound combat snapshots used for damage and cadence.
        :return: Chronologically ordered basic-attack events with stable IDs.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        attack_shapes: list[tuple[int, str, bool]] = []
        at_ms = 200
        regular_index = 0
        while at_ms <= context.duration_ms:
            attack_shapes.append((at_ms, f"JAX_GENERIC_ATTACK_{regular_index}", False))
            regular_index += 1
            at_ms += interval_ms

        empower_index = 1
        at_ms = 450
        while at_ms <= context.duration_ms:
            attack_shapes.append((at_ms, f"JAX_GENERIC_ATTACK_W_EMPOWER_{empower_index}", True))
            empower_index += 1
            at_ms += 3000

        events: list[ActionEvent] = []
        base = self._sequence_base(context)
        for consecutive_hit, (at_ms, event_id, empowered) in enumerate(
            sorted(attack_shapes), start=1
        ):
            outputs = [
                damage(
                    context.opponent_entity,
                    context.snapshot.attack_damage,
                    DamageType.PHYSICAL,
                )
            ]
            if empowered:
                outputs.append(
                    damage(
                        context.opponent_entity,
                        Decimal(190) + Decimal("0.60") * context.snapshot.ability_power,
                        DamageType.MAGIC,
                    )
                )
            if consecutive_hit % 3 == 0:
                outputs.append(
                    damage(
                        context.opponent_entity,
                        Decimal(130) + Decimal("0.60") * context.snapshot.ability_power,
                        DamageType.MAGIC,
                    )
                )
            if event_id.startswith("JAX_GENERIC_ATTACK_") and "_W_EMPOWER_" not in event_id:
                attack_index = int(event_id.rsplit("_", 1)[1])
                event_id = f"JAX_GENERIC_ATTACK_{base + attack_index}"
            events.append(
                action(
                    event_id,
                    at_ms=at_ms,
                    sequence=base + consecutive_hit,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked Q1/W5/E5/R2 level-13 duel sequence.

        Q contributes engagement distance rather than damage because this benchmark
        starts in attack range. R active remains excluded by the curated profile.

        :param context: Role-bound combat snapshots for Jax and the opponent.
        :return: Sustained attack and Counter Strike events with audit blockers.
        """
        base = self._sequence_base(context)
        e_stance = action(
            "JAX_E_DEFENSIVE_STANCE",
            at_ms=100,
            sequence=base + 100,
            source=context.self_entity,
            channel=ActionChannel.ABILITY,
            outputs=(StatusOutput(context.self_entity, "JAX_COUNTER_STRIKE", 2000),),
            requires_living_opponent=False,
        )
        e_damage = action(
            "JAX_E_COUNTER_STRIKE_DAMAGE",
            at_ms=2100,
            sequence=base + 101,
            source=context.self_entity,
            channel=ActionChannel.ABILITY,
            outputs=(
                damage(
                    context.opponent_entity,
                    Decimal(160)
                    + Decimal("0.70") * context.snapshot.ability_power
                    + Decimal("0.04") * context.opponent_snapshot.max_hp,
                    DamageType.MAGIC,
                ),
                crowd_control(context.opponent_entity, "STUN", duration_ms=1000),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"JAX_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "jax_q1_w5_e5_r2_level13_synthetic_v1",
            tuple(
                sorted(
                    (*self._attack_events(context), e_stance, e_damage),
                    key=lambda event: event.at_ms,
                )
            ),
            (
                *level_blockers,
                "JAX_LEVEL13_Q1_W5_E5_R2_POLICY_UNVERIFIED",
                "JAX_ROTATION_TIMING_UNVERIFIED",
                "JAX_RESOURCE_COSTS_EXCLUDED_SOURCE_CONFLICT",
                "JAX_Q_DAMAGE_EXCLUDED_IN_RANGE_BENCHMARK",
                "JAX_E_DODGE_DAMAGE_SCALING_NOT_EVALUATED",
                "JAX_R_ACTIVE_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Cancel attacks during Counter Strike and block actions after its stun.

        The shared damage-window contract cannot distinguish area abilities from
        single-target abilities, so Counter Strike's area-damage reduction remains
        an explicit verification blocker instead of being over-applied.

        :param context: Role-bound combat snapshots for the current participant.
        :return: Causally linked dodge and tenacity-reducible stun windows.
        """
        return ReactionPlan(
            "jax_e_counter_strike_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "jax_e_basic_attack_dodge",
                    100,
                    min(2100, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK,),
                    "JAX_E_DEFENSIVE_STANCE",
                ),
                CastBlockWindow(
                    "jax_e_stun",
                    2100,
                    min(3100, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY),
                    "JAX_E_COUNTER_STRIKE_DAMAGE",
                    True,
                ),
            ),
            blockers=(
                "JAX_E_CAST_AND_RECAST_TIMING_UNVERIFIED",
                "JAX_E_AOE_DAMAGE_REDUCTION_NOT_EVALUATED",
                "JAX_E_DEPENDENT_RECAST_CANCELLATION_NOT_EVALUATED",
            ),
        )
