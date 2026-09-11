"""Ivern combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class IvernCog(ChampionCog):
    """Model Ivern's Q5/W1/E5/R2 level-13 two-participant fixture.

    Ivern creates brush, lands Rootcaller, shields himself with Triggerseed,
    and remains close enough for its explosion to hit. His attacks receive the
    locked Brushmaker bonus while the fixture keeps him in brush. Ally-only
    benefits and Daisy are omitted because the timeline has no allied or pet
    participant on which to represent them.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Ivern.json",
        "data/raw/16.17.1/communitydragon/champions/427.json",
        "data/raw/16.17.1/communitydragon/champions/ivern.bin.json",
    )

    _Q_AT_MS = 300
    _W_AT_MS = 100
    _E_AT_MS = 600
    _E_DETONATE_AT_MS = 2600
    _ATTACK_FIRST_AT_MS = 1000

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Report no movement-speed multiplier for Ivern's modeled engage.

        :param context: Role-bound Ivern encounter context.
        :return: Neutral movement-speed multiplier.
        """
        return Decimal(1)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Rootcaller's locked maximum recast engage distance.

        :param context: Role-bound Ivern encounter context.
        :return: Rootcaller cast range in game units.
        """
        return Decimal(1125)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats unused by Ivern's fixed duel schedule.

        AP affects every represented spell channel, and AD and attack speed
        affect ordinary attacks. Heal and shield power remains unsupported by
        champion snapshots even though Triggerseed emits a shield.

        :param item: Normalized candidate from the locked item catalog.
        :return: Ivern-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"IVERN_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Brushmaker-enhanced attacks for the fixed brush fixture.

        :param context: Role-bound snapshots supplying AP, AD, and attack cadence.
        :return: Chronological attacks with physical and W1 magic outputs.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        brush_damage = Decimal(20) + Decimal("0.20") * context.snapshot.ability_power
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = self._ATTACK_FIRST_AT_MS
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"IVERN_BASIC_ATTACK_BRUSHMAKER_{index}",
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
                        damage(
                            context.opponent_entity,
                            brush_damage,
                            DamageType.MAGIC,
                        ),
                    ),
                )
            )
            at_ms += interval_ms
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Ivern's fixed root, brush attacks, and self-shield sequence.

        Triggerseed's explosion is a separate event so its delayed damage and
        slow have a causal source. The fixture assumes its shielded caster stays
        beside the rooted opponent until detonation.

        :param context: Role-bound Ivern and opponent combat snapshots.
        :return: Deterministic level-13 action events with explicit omissions.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        q_damage = Decimal(260) + Decimal("0.70") * ap
        e_shield = Decimal(235) + Decimal("0.50") * ap
        e_damage = Decimal(150) + Decimal("0.80") * ap
        fixed_events = (
            action(
                "IVERN_W_BRUSHMAKER_CREATE",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "IVERN_W_IN_BRUSH", 7900),),
                requires_living_opponent=False,
            ),
            action(
                "IVERN_Q_ROOTCALLER",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q_damage, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "ROOT", duration_ms=2000),
                ),
            ),
            action(
                "IVERN_E_TRIGGERSEED_SELF",
                at_ms=self._E_AT_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(shielding(context.self_entity, e_shield, duration_ms=2000),),
                requires_living_opponent=False,
            ),
            action(
                "IVERN_E_TRIGGERSEED_DETONATE",
                at_ms=self._E_DETONATE_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.PASSIVE,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=2000,
                        magnitude=Decimal("0.60"),
                    ),
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"IVERN_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "ivern_q5_w1_e5_r2_level13_locked_v1",
            tuple(
                sorted(
                    (*fixed_events, *self._basic_attacks(context)),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "IVERN_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "IVERN_Q_HIT_AND_RECAST_ASSUMED",
                "IVERN_Q_ALLY_DASH_NOT_REPRESENTABLE_IN_TWO_COMBATANT_DUEL",
                "IVERN_W_REMAINS_IN_CREATED_BRUSH_FIXTURE",
                "IVERN_W_ALLY_ATTACK_BUFF_NOT_REPRESENTABLE_IN_TWO_COMBATANT_DUEL",
                "IVERN_E_SELF_TARGET_AND_ENEMY_HIT_FIXTURE",
                "IVERN_E_SECOND_SHIELD_ON_MISS_NOT_MODELED",
                "IVERN_E_ALLY_AND_DAISY_TARGETS_NOT_REPRESENTABLE",
                "IVERN_R_DAISY_PET_ENTITY_NOT_REPRESENTABLE",
                "IVERN_R_DAISY_ATTACKS_SHOCKWAVE_AND_KNOCKUP_NOT_MODELED",
                "IVERN_PASSIVE_JUNGLE_CAMPS_NOT_REPRESENTABLE_IN_CHAMPION_DUEL",
                "IVERN_CAST_MISSILE_AND_ATTACK_TIMING_UNVERIFIED",
                "IVERN_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Rootcaller's root and Triggerseed's delayed slow windows.

        :param context: Role-bound Ivern and opponent combat snapshots.
        :return: Causal movement-control windows for represented spell hits.
        """
        return ReactionPlan(
            "ivern_q5_e5_control_level13_locked_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "ivern_q_rootcaller_root",
                    self._Q_AT_MS,
                    min(self._Q_AT_MS + 2000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "IVERN_Q_ROOTCALLER",
                    True,
                    ControlType.ROOT,
                ),
                CastBlockWindow(
                    "ivern_e_triggerseed_slow",
                    self._E_DETONATE_AT_MS,
                    min(self._E_DETONATE_AT_MS + 2000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "IVERN_E_TRIGGERSEED_DETONATE",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=(
                "IVERN_Q_SKILLSHOT_HIT_ASSUMED",
                "IVERN_E_DETONATION_ENEMY_PROXIMITY_ASSUMED",
                "IVERN_R_DAISY_KNOCKUP_NOT_REPRESENTABLE_WITHOUT_PET_ENTITY",
            ),
        )
