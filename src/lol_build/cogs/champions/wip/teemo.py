"""Teemo combat Cog backed by the locked 16.17.1 champion snapshot."""

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
from lol_build.core.timeline import ActionChannel


class TeemoCog(ChampionCog):
    """Model Teemo's rank-five Q and E for the level-13 duel benchmark.

    The locked recommended skill order supports the E5/Q5/W1/R2 allocation.
    Mushroom placement and passive stealth preparation depend on pre-combat
    state absent from the benchmark, so neither is fabricated here.
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
        "data/raw/16.17.1/en_US/champion/Teemo.json",
        "data/raw/16.17.1/communitydragon/champions/17.json",
        "data/raw/16.17.1/communitydragon/champions/teemo.bin.json",
    )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Return rank-one Move Quick's active pursuit multiplier.

        :param context: Role-bound combat snapshots for the encounter.
        :return: Movement multiplier during the modeled three-second approach.
        """
        return Decimal("1.24")

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats whose effect is absent from this fixed rotation.

        Mana and ability haste do not alter the fixed spell schedule, critical
        strikes are not sampled, and life steal is not resolved by basic
        ``DamageOutput`` events. Defensive, AP, AD, and attack-speed stats remain
        eligible because the shared snapshot or this Cog consumes them.

        :param item: Normalized locked item candidate.
        :return: Champion-scoped blocker code, or ``None`` when representable.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"TEEMO_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build a deterministic Q5 and E5 sustained-attack sequence.

        Toxic Shot impact damage is emitted with every basic attack. Its
        non-stacking poison is emitted once per second after the first hit while
        attacks continuously refresh the four-second duration. The exact server
        tick phase remains an explicit verification blocker.

        :param context: Role-bound combat snapshots for the encounter.
        :return: Teemo action schedule and unresolved evidence blockers.
        """
        sequence = self._sequence_base(context)
        ap = context.snapshot.ability_power
        bonus_ad = context.snapshot.bonus_attack_damage
        q_damage = Decimal(260) + Decimal("0.70") * ap
        e_impact = Decimal(65) + Decimal("0.30") * ap + Decimal("0.05") * bonus_ad
        e_tick = Decimal(30) + Decimal("0.10") * ap + Decimal("0.025") * bonus_ad
        events = [
            action(
                "TEEMO_Q_BLINDING_DART",
                at_ms=100,
                sequence=sequence,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q_damage, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "BLIND", duration_ms=3000),
                ),
            )
        ]
        sequence += 1
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        for index, at_ms in enumerate(range(400, context.duration_ms + 1, interval_ms), start=1):
            events.append(
                action(
                    f"TEEMO_E_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=sequence,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            context.snapshot.attack_damage,
                            DamageType.PHYSICAL,
                        ),
                        damage(context.opponent_entity, e_impact, DamageType.MAGIC),
                    ),
                )
            )
            sequence += 1
        for index, at_ms in enumerate(range(1400, context.duration_ms + 1, 1000), start=1):
            events.append(
                action(
                    f"TEEMO_E_POISON_TICK_{index}",
                    at_ms=at_ms,
                    sequence=sequence,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(damage(context.opponent_entity, e_tick, DamageType.MAGIC),),
                )
            )
            sequence += 1
        return ActionPlan(
            "teemo_q5_e5_level13_locked_values_v1",
            tuple(events),
            (
                "TEEMO_Q_HIT_TIMING_UNVERIFIED",
                "TEEMO_E_POISON_REFRESH_PHASE_UNVERIFIED",
                "TEEMO_PASSIVE_AMBUSH_NOT_MODELED",
                "TEEMO_R_TRAP_STATE_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Q blind as a causal, tenacity-reducible attack block.

        :param context: Role-bound combat snapshots for the encounter.
        :return: Blind window linked to the corresponding Q hit event.
        """
        return ReactionPlan(
            "teemo_q5_blind_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "teemo_q_blind",
                    100,
                    min(3100, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK,),
                    "TEEMO_Q_BLINDING_DART",
                    True,
                ),
            ),
            blockers=(
                "TEEMO_Q_HIT_TIMING_UNVERIFIED",
                "TEEMO_BLIND_TENACITY_RUNTIME_UNVERIFIED",
            ),
        )
