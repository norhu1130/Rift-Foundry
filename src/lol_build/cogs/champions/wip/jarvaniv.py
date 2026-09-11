"""Jarvan IV combat Cog backed by the locked 16.17.1 sources."""

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
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    CurrentHealthDamageOutput,
    ResistanceReductionOutput,
    StatusOutput,
)


class JarvanIVCog(ChampionCog):
    """Model Jarvan IV's Q5/W1/E5/R2 level-13 duel fixture.

    The fixture lands Demacian Standard before Dragon Strike, so the first and
    cooldown-ready second Q pull Jarvan to the still-active flag and knock up
    the opponent. Cataclysm then lands on that opponent, Golden Aegis hits one
    enemy champion, and Jarvan attacks inside his E aura. Flag placement,
    collision, arena terrain, and all effects on allied champions remain
    blockers rather than invented geometry or extra participants.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/JarvanIV.json",
        "data/raw/16.17.1/communitydragon/champions/59.json",
        "data/raw/16.17.1/communitydragon/champions/jarvaniv.bin.json",
    )

    _ATTACK_SPEED_RATIO = Decimal("0.658")
    _E5_PASSIVE_ATTACK_SPEED = Decimal("0.30")
    _E5_AURA_ATTACK_SPEED = Decimal("0.30")
    _E_AURA_END_MS = 8100
    _Q5_COOLDOWN_MS = 6000
    _Q5_ARMOR_REDUCTION = Decimal("0.26")
    _PASSIVE_CURRENT_HEALTH_RATIO = Decimal("0.08")
    _PASSIVE_CAP = Decimal(400)
    _PASSIVE_COOLDOWN_MS = 4000

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Cataclysm's locked target-cast range for approach scoring.

        The longer E-Q displacement is conditional on flag placement and path
        collision, so it remains a blocker in the action plan.

        :param context: Role-bound Jarvan IV encounter context.
        :return: Rank-two Cataclysm cast range in game units.
        """
        return Decimal(650)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Jarvan IV's fixed duel policy.

        AD, AP, attack speed, health, defenses, penetration, movement speed,
        and tenacity reach a modeled snapshot or event. Haste cannot change the
        locked schedule, and resource, critical, and sustain channels are not
        represented.

        :param item: Normalized candidate from the locked item catalog.
        :return: Jarvan-IV-scoped blocker, or ``None`` for represented stats.
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
            return f"JARVANIV_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Q5 hits while the opening rank-five flag remains active.

        :param context: Role-bound snapshots supplying bonus AD and duration.
        :return: Q damage, armor reduction, and E-Q airborne effects.
        """
        raw_damage = Decimal(240) + Decimal("1.45") * context.snapshot.bonus_attack_damage
        base = self._sequence_base(context) + 10
        events: list[ActionEvent] = []
        at_ms = 350
        while at_ms <= min(context.duration_ms, self._E_AURA_END_MS):
            index = len(events) + 1
            events.append(
                action(
                    f"JARVANIV_Q_DRAGON_STRIKE_EQ_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, raw_damage, DamageType.PHYSICAL),
                        ResistanceReductionOutput(
                            context.opponent_entity,
                            "ARMOR",
                            self._Q5_ARMOR_REDUCTION,
                            1,
                            3000,
                            f"JARVANIV_Q_ARMOR_REDUCTION_{context.self_entity.value}",
                        ),
                        crowd_control(
                            context.opponent_entity,
                            "AIRBORNE",
                            duration_ms=750,
                        ),
                    ),
                )
            )
            at_ms += self._Q5_COOLDOWN_MS
        return tuple(events)

    def _attack_speed(self, context: ParticipantContext, *, at_ms: int) -> Decimal:
        """Resolve E5's permanent and active attack-speed contributions.

        :param context: Jarvan IV snapshot supplying item-adjusted attack speed.
        :param at_ms: Prospective attack time used for active-aura expiry.
        :return: Attacks per second for the relevant cadence segment.
        """
        bonus = self._E5_PASSIVE_ATTACK_SPEED
        if at_ms <= self._E_AURA_END_MS:
            bonus += self._E5_AURA_ATTACK_SPEED
        return context.snapshot.attack_speed + self._ATTACK_SPEED_RATIO * bonus

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks and level-13 Martial Cadence procs.

        The passive has a four-second per-target cooldown at level 13. Its
        documented 400-damage cap is represented; the 20-damage monster floor
        is irrelevant to this champion-only fixture and is retained as a model
        scope blocker.

        :param context: Role-bound snapshots supplying attack damage and speed.
        :return: Chronological blind-susceptible basic-attack events.
        """
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 1700
        last_passive_ms: int | None = None
        while at_ms <= context.duration_ms:
            passive_ready = (
                last_passive_ms is None or at_ms - last_passive_ms >= self._PASSIVE_COOLDOWN_MS
            )
            outputs = []
            if passive_ready:
                outputs.append(
                    CurrentHealthDamageOutput(
                        context.opponent_entity,
                        self._PASSIVE_CURRENT_HEALTH_RATIO,
                        DamageType.PHYSICAL,
                        self._PASSIVE_CAP,
                    )
                )
                last_passive_ms = at_ms
            outputs.append(
                damage(
                    context.opponent_entity,
                    context.snapshot.attack_damage,
                    DamageType.PHYSICAL,
                )
            )
            events.append(
                action(
                    f"JARVANIV_BASIC_ATTACK_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
            at_ms += self._attack_interval_ms(self._attack_speed(context, at_ms=at_ms))
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked E5-Q5-R2-W1 level-13 engage and attack sequence.

        :param context: Role-bound Jarvan IV and opponent combat snapshots.
        :return: Deterministic spells, armor shred, shield, attacks, and blockers.
        """
        base = self._sequence_base(context)
        bonus_ad = context.snapshot.bonus_attack_damage
        ap = context.snapshot.ability_power
        fixed_events = (
            action(
                "JARVANIV_E_DEMACIAN_STANDARD",
                at_ms=100,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(240) + Decimal("0.80") * ap,
                        DamageType.MAGIC,
                    ),
                    StatusOutput(context.self_entity, "JARVANIV_E_AURA", 8000),
                ),
            ),
            action(
                "JARVANIV_R_CATACLYSM",
                at_ms=1200,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(325) + Decimal("1.80") * bonus_ad,
                        DamageType.PHYSICAL,
                    ),
                    StatusOutput(context.opponent_entity, "JARVANIV_R_ARENA", 3500),
                ),
            ),
            action(
                "JARVANIV_W_GOLDEN_AEGIS_ONE_CHAMPION",
                at_ms=1400,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(
                        context.self_entity,
                        Decimal(60)
                        + Decimal("0.70") * bonus_ad
                        + Decimal("0.013") * context.snapshot.max_hp,
                        duration_ms=4000,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=2000,
                        magnitude=Decimal("0.15"),
                    ),
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"JARVANIV_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        events = (*fixed_events, *self._q_events(context), *self._basic_attacks(context))
        return ActionPlan(
            "jarvaniv_q5_w1_e5_r2_level13_eq_cataclysm_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "JARVANIV_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "JARVANIV_ROTATION_TIMING_UNVERIFIED",
                "JARVANIV_EQ_FLAG_PLACEMENT_PATH_AND_COLLISION_NOT_MODELED",
                "JARVANIV_EQ_DASH_DISTANCE_NOT_USED_FOR_ENGAGEMENT",
                "JARVANIV_E_ALLY_ATTACK_SPEED_AURA_NOT_MODELED",
                "JARVANIV_R_TERRAIN_GEOMETRY_AND_ESCAPE_NOT_MODELED",
                "JARVANIV_R_TERRAIN_ALLY_INTERACTIONS_NOT_MODELED",
                "JARVANIV_W_ADDITIONAL_CHAMPION_HITS_NOT_MODELED",
                "JARVANIV_PASSIVE_MONSTER_MINIMUM_NOT_APPLICABLE",
                "JARVANIV_RESOURCE_COSTS_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose E-Q knockups and Golden Aegis's movement slow.

        Cataclysm does not immobilize a target inside its arena, so its terrain
        is deliberately a blocker instead of a full movement cast block.

        :param context: Role-bound Jarvan IV encounter context.
        :return: Source-linked airborne and slow windows with terrain blockers.
        """
        q_windows = tuple(
            CastBlockWindow(
                f"jarvaniv_eq_airborne_{index}",
                event.at_ms,
                min(event.at_ms + 750, context.duration_ms),
                (
                    ActionChannel.BASIC_ATTACK,
                    ActionChannel.ABILITY,
                    ActionChannel.MOVEMENT,
                ),
                event.id,
                False,
                ControlType.AIRBORNE,
            )
            for index, event in enumerate(self._q_events(context), start=1)
            if event.at_ms < context.duration_ms
        )
        slow_end_ms = min(3400, context.duration_ms)
        slow_windows = (
            (
                CastBlockWindow(
                    "jarvaniv_w_slow",
                    1400,
                    slow_end_ms,
                    (ActionChannel.MOVEMENT,),
                    "JARVANIV_W_GOLDEN_AEGIS_ONE_CHAMPION",
                    False,
                    ControlType.SLOW,
                ),
            )
            if slow_end_ms > 1400
            else ()
        )
        return ReactionPlan(
            "jarvaniv_eq_w1_r2_reaction_v1",
            cast_block_windows=(*q_windows, *slow_windows),
            blockers=(
                "JARVANIV_EQ_HIT_AND_KNOCKUP_TIMING_UNVERIFIED",
                "JARVANIV_W_SLOW_RESISTANCE_NOT_MODELED",
                "JARVANIV_R_TERRAIN_BOUNDARY_REACTION_NOT_MODELED",
                "JARVANIV_R_ALLY_TERRAIN_REACTION_NOT_MODELED",
            ),
        )
