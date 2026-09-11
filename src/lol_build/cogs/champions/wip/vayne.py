"""Vayne combat Cog for the locked level-13 duel benchmark."""

from __future__ import annotations

from decimal import Decimal

from lol_build.cogs.base import (
    ActionPlan,
    ChampionCog,
    CogCapability,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class VayneCog(ChampionCog):
    """Model Vayne's Q5/W5/E1/R2 level-13 duel sequence.

    Final Hour is active for the complete eight-second benchmark. Tumble is
    scheduled as an empowered basic attack that resets the ordinary attack
    clock, and every third Silver Bolts application deals its locked rank-five
    maximum-health true damage. Terrain and target-visibility state are absent
    from the scenario, so Condemn's collision reward and Tumble invisibility do
    not receive fabricated value.
    """

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
        "data/raw/16.17.1/en_US/champion/Vayne.json",
        "data/raw/16.17.1/communitydragon/champions/67.json",
        "data/raw/16.17.1/communitydragon/champions/vayne.bin.json",
    )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Final Hour's empowered Night Hunter pursuit speed.

        The locked R2 profile changes Night Hunter's flat pursuit bonus from 30
        to 90. The engagement contract accepts a multiplier, so the conversion
        is made relative to the current snapshot movement speed.

        :param context: Role-bound Vayne combat context.
        :return: Movement multiplier while pursuing the opposing champion.
        """
        return (context.snapshot.move_speed + Decimal(90)) / context.snapshot.move_speed

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Tumble's locked dash distance for approach evaluation.

        :param context: Role-bound Vayne combat context.
        :return: Maximum Tumble displacement in game units.
        """
        return Decimal(300)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the deterministic Vayne model.

        Attack damage, attack speed, ability power, defenses, penetration,
        movement, life steal, and omnivamp feed represented calculations; the
        shared timeline resolves vamp from each damage output, and heal and
        shield power amplifies cast heals and shields; plain attacks deal
        expected critical-strike damage. Mana consumption and ability-haste
        rescheduling are intentionally not inferred by this fixed rotation.

        :param item: Normalized candidate item from the locked catalog.
        :return: Champion-scoped blocker, or ``None`` when represented.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "MANA",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"VAYNE_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _damage_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks and Condemn applications under Final Hour.

        Q5 has a two-second base cooldown, reduced by 40 percent during R2. A Q
        attack resets the ordinary attack clock. Silver Bolts stacks are assigned
        over the resulting ordered hit stream and proc on every third hit.

        :param context: Role-bound snapshots used for cadence and damage formulas.
        :return: Ordered damaging events including Q, W, and E outputs.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        tumble_cooldown_ms = 1200
        tumble_hit_lockout_ms = 300
        next_tumble_ms = 300
        next_ordinary_ms = 300 + interval_ms
        shapes: list[tuple[int, str]] = []
        while min(next_tumble_ms, next_ordinary_ms) <= context.duration_ms:
            if (
                next_tumble_ms <= next_ordinary_ms
                or next_tumble_ms - next_ordinary_ms < tumble_hit_lockout_ms
            ):
                at_ms = next_tumble_ms
                shapes.append((at_ms, "Q"))
                next_tumble_ms += tumble_cooldown_ms
                next_ordinary_ms = at_ms + interval_ms
            else:
                at_ms = next_ordinary_ms
                shapes.append((at_ms, "ATTACK"))
                next_ordinary_ms += interval_ms
        if context.duration_ms >= 7600:
            shapes.append((7600, "E"))
        shapes.sort(key=lambda shape: (shape[0], shape[1] == "E"))

        final_hour_ad = Decimal(50)
        combat_attack_damage = context.snapshot.attack_damage + final_hour_ad
        q_bonus = (
            Decimal("1.15") * combat_attack_damage
            + Decimal("0.50") * context.snapshot.ability_power
        )
        silver_bolts = max(
            Decimal(100),
            Decimal("0.10") * context.opponent_snapshot.max_hp,
        )
        condemn_damage = Decimal(50) + Decimal("0.50") * (
            context.snapshot.bonus_attack_damage + final_hour_ad
        )
        base = self._sequence_base(context)
        events: list[ActionEvent] = []
        for hit_number, (at_ms, hit_kind) in enumerate(shapes, start=1):
            outputs = []
            if hit_kind == "E":
                outputs.append(
                    damage(
                        context.opponent_entity,
                        condemn_damage,
                        DamageType.PHYSICAL,
                    )
                )
            else:
                outputs.append(
                    damage(
                        context.opponent_entity,
                        combat_attack_damage,
                        DamageType.PHYSICAL,
                    )
                )
                if hit_kind == "Q":
                    outputs.append(
                        damage(
                            context.opponent_entity,
                            q_bonus,
                            DamageType.PHYSICAL,
                        )
                    )
            if hit_number % 3 == 0:
                outputs.append(
                    damage(
                        context.opponent_entity,
                        silver_bolts,
                        DamageType.TRUE,
                    )
                )
            event_name = {
                "ATTACK": "BASIC_ATTACK",
                "E": "E_CONDEMN",
                "Q": "Q_TUMBLE_ATTACK",
            }[hit_kind]
            events.append(
                action(
                    f"VAYNE_{event_name}_{hit_number}",
                    at_ms=at_ms,
                    sequence=base + 100 + hit_number,
                    source=context.self_entity,
                    channel=(
                        ActionChannel.ABILITY if hit_kind == "E" else ActionChannel.BASIC_ATTACK
                    ),
                    outputs=tuple(outputs),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked Q5/W5/E1/R2 level-13 duel sequence.

        Condemn is fired late as non-terrain base damage so it does not pretend
        that the benchmark supplies a wall. Its knockback and any resulting
        reacquisition delay remain excluded because neither combat geometry nor
        pathing exists in the current scenario.

        :param context: Role-bound snapshots for Vayne and the opponent.
        :return: Deterministic attacks, Silver Bolts procs, and spell events.
        """
        base = self._sequence_base(context)
        final_hour = action(
            "VAYNE_R_FINAL_HOUR",
            at_ms=0,
            sequence=base,
            source=context.self_entity,
            channel=ActionChannel.ABILITY,
            outputs=(StatusOutput(context.self_entity, "VAYNE_FINAL_HOUR", 10_000),),
            requires_living_opponent=False,
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"VAYNE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "vayne_q5_w5_e1_r2_level13_locked_v1",
            tuple(
                sorted(
                    (final_hour, *self._damage_events(context)),
                    key=lambda event: (event.at_ms, event.sequence),
                )
            ),
            (
                *level_blockers,
                "VAYNE_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "VAYNE_ATTACK_AND_TUMBLE_TIMING_UNVERIFIED",
                "VAYNE_Q_DASH_DIRECTION_AND_HIT_DELAY_NOT_MODELED",
                "VAYNE_W_STACK_EXPIRY_AND_TARGET_SWITCHING_NOT_MODELED",
                "VAYNE_W_CANCELLED_HIT_STACK_RECOMPUTATION_NOT_MODELED",
                "VAYNE_NIGHT_HUNTER_PURSUIT_DIRECTION_ASSUMED",
                "VAYNE_E_KNOCKBACK_REACQUISITION_NOT_MODELED",
                "VAYNE_E_TERRAIN_COLLISION_DAMAGE_AND_STUN_NOT_MODELED",
                "VAYNE_R_TUMBLE_INVISIBILITY_TARGETING_NOT_MODELED",
                "VAYNE_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Return a neutral reaction plan for unresolved geometry and stealth.

        Condemn's wall stun is conditional on collision geometry and Final Hour's
        invisibility affects opponent targeting. Neither input exists in the
        benchmark, so no unconditional control window is emitted.

        :param context: Role-bound snapshots for Vayne and the opponent.
        :return: Neutral reaction behavior with explicit unresolved blockers.
        """
        return ReactionPlan(
            "vayne_geometry_and_stealth_unresolved_v1",
            blockers=(
                "VAYNE_E_TERRAIN_COLLISION_DAMAGE_AND_STUN_NOT_MODELED",
                "VAYNE_E_DISPLACEMENT_ACTION_BLOCK_NOT_MODELED",
                "VAYNE_R_TUMBLE_INVISIBILITY_TARGETING_NOT_MODELED",
            ),
        )
