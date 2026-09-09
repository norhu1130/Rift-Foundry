"""Annie combat Cog backed by the locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    CastBlockWindow,
    ChampionCog,
    CogCapability,
    CogMaturity,
    ControlType,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class AnnieCog(ChampionCog):
    """Model Annie's Q5/W5/E1/R2 level-13 single-target sequence.

    The deterministic policy assumes Pyromania is ready when combat begins.
    Summoning Tibbers consumes that stun; Q, W, E, and the second Q then rebuild
    four stacks, allowing the final W to stun again. Only Tibbers' initial cast
    damage is included because pet pursuit, attacks, and aura contact require a
    summon AI and positioning state that the duel benchmark does not expose.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES | {CogCapability.MULTI_TARGET}
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Annie.json",
        "data/raw/16.17.1/communitydragon/champions/1.json",
        "data/raw/16.17.1/communitydragon/champions/annie.bin.json",
    )

    @staticmethod
    def _pyromania_duration_ms(level: int) -> int:
        """Resolve Pyromania's locked level-breakpoint stun duration.

        :param level: Annie's current champion level.
        :return: Base stun duration in integer milliseconds.
        """
        if level >= 11:
            return 1750
        if level >= 6:
            return 1500
        return 1250

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Return Molten Shield's initial level-scaled movement multiplier.

        CommunityDragon defines a linear 20% at level one to 50% at level
        eighteen curve. Its decay is not representable by this scalar contract.

        :param context: Role-bound combat snapshots for the encounter.
        :return: Initial pursuit movement-speed multiplier after self-cast E.
        """
        level_offset = Decimal(context.snapshot.level - 1)
        bonus = Decimal("0.20") + Decimal("0.30") * level_offset / Decimal(17)
        return Decimal(1) + bonus

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats not consumed by Annie's fixed event schedule.

        :param item: Normalized locked item candidate.
        :return: Champion-scoped blocker, or ``None`` when fully consumed.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "OMNIVAMP",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"ANNIE_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ordinary ranged attacks around the fixed spell rotation.

        :param context: Role-bound snapshots supplying attack speed and damage.
        :return: Deterministic physical basic-attack events within the duel.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        for index, at_ms in enumerate(
            range(1200, context.duration_ms + 1, interval_ms), start=1
        ):
            events.append(
                action(
                    f"ANNIE_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
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
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Annie's deterministic burst, shield, and follow-up sequence.

        :param context: Role-bound Annie and opponent combat snapshots.
        :return: Locked spell and attack events with unresolved assumptions.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        stun_ms = self._pyromania_duration_ms(context.snapshot.level)
        q_damage = Decimal(260) + Decimal("0.80") * ap
        w_damage = Decimal(230) + Decimal("0.80") * ap
        e_shield = Decimal(60) + Decimal("0.40") * ap
        r_damage = Decimal(275) + Decimal("0.75") * ap
        events = (
            action(
                "ANNIE_R_SUMMON_TIBBERS",
                at_ms=200,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    *self.area_outputs(
                        context,
                        lambda entity: damage(entity, r_damage, DamageType.MAGIC),
                    ),
                    *self.area_outputs(
                        context,
                        lambda entity: crowd_control(entity, "STUN", duration_ms=stun_ms),
                    ),
                ),
            ),
            action(
                "ANNIE_Q_DISINTEGRATE_1",
                at_ms=400,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.MAGIC),),
            ),
            action(
                "ANNIE_W_INCINERATE_1",
                at_ms=650,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=self.area_outputs(
                    context, lambda entity: damage(entity, w_damage, DamageType.MAGIC)
                ),
            ),
            action(
                "ANNIE_E_MOLTEN_SHIELD",
                at_ms=900,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(shielding(context.self_entity, e_shield, duration_ms=3000),),
            ),
            action(
                "ANNIE_Q_DISINTEGRATE_2",
                at_ms=4400,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.MAGIC),),
            ),
            action(
                "ANNIE_W_INCINERATE_2_PYROMANIA",
                at_ms=7650,
                sequence=base + 5,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    *self.area_outputs(
                        context,
                        lambda entity: damage(entity, w_damage, DamageType.MAGIC),
                    ),
                    *self.area_outputs(
                        context,
                        lambda entity: crowd_control(entity, "STUN", duration_ms=stun_ms),
                    ),
                ),
            ),
            *self._basic_attacks(context),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"ANNIE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "annie_q5_w5_e1_r2_level13_synthetic_v1",
            events,
            (
                "ANNIE_PYROMANIA_READY_AT_COMBAT_START_ASSUMED",
                "ANNIE_TIBBERS_SUMMON_AI_NOT_MODELED",
                "ANNIE_TIBBERS_AURA_AND_ATTACKS_NOT_MODELED",
                "ANNIE_Q_DISINTEGRATE_SINGLE_TARGET_ASSUMED",
                "ANNIE_E_REFLECT_TRIGGER_NOT_MODELED",
                "ANNIE_E_MOVEMENT_SPEED_DECAY_NOT_MODELED",
                "ANNIE_R_PASSIVE_MAGIC_PENETRATION_NOT_MODELED",
                "ANNIE_CAST_AND_MISSILE_TIMING_UNVERIFIED",
                *level_blockers,
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Pyromania stuns as causal, tenacity-reducible cast blocks.

        Molten Shield's shield is emitted by the action plan. Its retaliation
        needs an incoming-hit trigger, so no unconditional damage is fabricated.

        :param context: Role-bound snapshots identifying the controlled target.
        :return: Two stun windows linked to their offensive source events.
        """
        stun_ms = self._pyromania_duration_ms(context.snapshot.level)
        blocked = (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY)
        return ReactionPlan(
            "annie_pyromania_level13_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "annie_r_pyromania_stun",
                    200,
                    min(200 + stun_ms, context.duration_ms),
                    blocked,
                    "ANNIE_R_SUMMON_TIBBERS",
                    True,
                    ControlType.STUN,
                ),
                CastBlockWindow(
                    "annie_w2_pyromania_stun",
                    7650,
                    min(7650 + stun_ms, context.duration_ms),
                    blocked,
                    "ANNIE_W_INCINERATE_2_PYROMANIA",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(
                "ANNIE_PYROMANIA_READY_AT_COMBAT_START_ASSUMED",
                "ANNIE_E_REFLECT_TRIGGER_NOT_MODELED",
                "ANNIE_PYROMANIA_TENACITY_RUNTIME_UNVERIFIED",
            ),
        )
