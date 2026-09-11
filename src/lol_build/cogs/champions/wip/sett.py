"""Sett combat Cog for the locked level-13 duel benchmark."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

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


class SettCog(ChampionCog):
    """Model Sett's alternating punches and Q5/W5/E1/R2 duel sequence.

    The locked sources expose each formula but the shared timeline cannot feed
    accumulated incoming damage into a later action. Haymaker therefore uses a
    deterministic maximum-Grit fixture and advertises that assumption. In the
    two-combatant benchmark Facebreaker has enemies on only one side, so it
    slows rather than fabricating the conditional stun.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Sett.json",
        "data/raw/16.17.1/communitydragon/champions/875.json",
        "data/raw/16.17.1/communitydragon/champions/sett.bin.json",
    )

    @staticmethod
    def _right_punch_bonus(level: int, bonus_attack_damage: Decimal) -> Decimal:
        """Calculate Pit Grit's level-scaled right-punch bonus damage.

        :param level: Champion level selecting the locked five-per-level curve.
        :param bonus_attack_damage: Item-sourced attack damage in the snapshot.
        :return: Raw physical bonus applied only to a right punch.
        """
        return Decimal(5 * level) + Decimal("0.55") * bonus_attack_damage

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Knuckle Down's movement bonus toward enemy champions.

        :param context: Role-bound combat snapshots for the encounter.
        :return: Pursuit movement-speed multiplier during the rank-five Q buff.
        """
        return Decimal("1.30")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Show Stopper's target acquisition range for approach modeling.

        :param context: Role-bound combat snapshots for the encounter.
        :return: Locked rank-independent R cast range in game units.
        """
        return Decimal(400)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels that the fixed Sett policy cannot evaluate.

        Health, attack damage, attack speed, defenses, penetration, movement,
        and tenacity flow through the shared snapshot or Sett formulas. Fixed
        cast times cannot value haste, while critical strikes and healing
        attribution are outside this action model.

        :param item: Normalized item candidate from the locked catalog.
        :return: Champion-scoped blocker for unsupported stats, otherwise ``None``.
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
            return f"SETT_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _punch_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule Q-enhanced punches followed by alternating passive punches.

        The right punch uses the locked 1.5 attack-speed modifier for its gap
        after a left punch. Q contributes bonus max-health damage to exactly the
        first two punches and preserves Pit Grit's left/right alternation.

        :param context: Role-bound combat snapshots used for cadence and damage.
        :return: Deterministic basic-attack events through the duel duration.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        right_gap_ms = max(
            1,
            int((Decimal(interval_ms) / Decimal("1.5")).to_integral_value(ROUND_HALF_EVEN)),
        )
        q_bonus = Decimal(50) + context.opponent_snapshot.max_hp * (
            Decimal("0.01") + Decimal("0.00025") * context.snapshot.attack_damage
        )
        right_bonus = self._right_punch_bonus(
            context.snapshot.level,
            context.snapshot.bonus_attack_damage,
        )
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 1200
        punch_index = 0
        while at_ms <= context.duration_ms:
            is_right = punch_index % 2 == 1
            q_empowered = punch_index < 2
            outputs = [
                damage(
                    context.opponent_entity,
                    context.snapshot.attack_damage,
                    DamageType.PHYSICAL,
                )
            ]
            if is_right:
                outputs.append(
                    damage(
                        context.opponent_entity,
                        right_bonus,
                        DamageType.PHYSICAL,
                    )
                )
            if q_empowered:
                outputs.append(
                    damage(
                        context.opponent_entity,
                        q_bonus,
                        DamageType.PHYSICAL,
                    )
                )
            label = "RIGHT" if is_right else "LEFT"
            prefix = "Q" if q_empowered else "PASSIVE"
            events.append(
                action(
                    f"SETT_{prefix}_{label}_PUNCH_{punch_index + 1}",
                    at_ms=at_ms,
                    sequence=base + punch_index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
            punch_index += 1
            at_ms += right_gap_ms if not is_right else interval_ms
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked Q5/W5/E1/R2 level-13 action sequence.

        W consumes an explicit maximum-Grit fixture equal to half of maximum
        health. Its shield and center-line true damage share one atomic event,
        so cancelling the cast removes both effects. R includes the grabbed
        opponent's bonus-health term and E deliberately emits only its duel slow.

        :param context: Role-bound snapshots for Sett and the opponent.
        :return: Damage, shield, and control events with audit blockers.
        """
        base = self._sequence_base(context)
        max_grit = Decimal("0.50") * context.snapshot.max_hp
        w_damage = Decimal(160) + max_grit * (
            Decimal("0.25") + Decimal("0.0025") * context.snapshot.bonus_attack_damage
        )
        e_damage = Decimal(50) + Decimal("0.60") * context.snapshot.attack_damage
        r_damage = (
            Decimal(300)
            + Decimal("1.20") * context.snapshot.bonus_attack_damage
            + Decimal("0.50") * context.opponent_snapshot.bonus_health
        )
        fixed_events = (
            action(
                "SETT_R_SHOW_STOPPER",
                at_ms=300,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.PHYSICAL),
                    crowd_control(
                        context.opponent_entity,
                        "SUPPRESSION",
                        duration_ms=1500,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=1000,
                        magnitude=Decimal("0.99"),
                    ),
                ),
            ),
            action(
                "SETT_E_FACEBREAKER_ONE_SIDE",
                at_ms=950,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.PHYSICAL),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=500,
                        magnitude=Decimal("0.70"),
                    ),
                ),
            ),
            action(
                "SETT_W_HAYMAKER_MAX_GRIT_CENTER",
                at_ms=4000,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(
                        context.self_entity,
                        max_grit,
                        duration_ms=3000,
                        decay_delay_ms=750,
                    ),
                    damage(context.opponent_entity, w_damage, DamageType.TRUE),
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"SETT_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "sett_q5_w5_e1_r2_level13_synthetic_v1",
            tuple(
                sorted(
                    (*fixed_events, *self._punch_events(context)),
                    key=lambda event: (event.at_ms, event.sequence),
                )
            ),
            (
                *level_blockers,
                "SETT_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "SETT_ROTATION_TIMING_UNVERIFIED",
                "SETT_RIGHT_PUNCH_CADENCE_INTERPRETATION_UNVERIFIED",
                "SETT_W_DYNAMIC_GRIT_ACCUMULATION_NOT_MODELED",
                "SETT_W_MAX_GRIT_AND_CENTER_HIT_ASSUMED",
                "SETT_E_TWO_SIDED_STUN_CONDITION_UNMET_DUEL",
                "SETT_R_ENGAGEMENT_GEOMETRY_UNVERIFIED",
                "SETT_RESOURCE_DECAY_NOT_EVALUATED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose R suppression and one-sided E slow as causal reactions.

        :param context: Role-bound snapshots for the current Sett participant.
        :return: Source-linked control windows without an invented E stun.
        """
        return ReactionPlan(
            "sett_r_suppression_e_slow_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "sett_r_suppression",
                    300,
                    min(1800, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                        ActionChannel.ITEM_ACTIVE,
                    ),
                    "SETT_R_SHOW_STOPPER",
                    False,
                    ControlType.SUPPRESSION,
                ),
                CastBlockWindow(
                    "sett_e_one_side_slow",
                    950,
                    min(1450, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "SETT_E_FACEBREAKER_ONE_SIDE",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=(
                "SETT_R_SUPPRESSION_AND_IMPACT_TIMING_UNVERIFIED",
                "SETT_E_SECOND_ENEMY_GEOMETRY_OUT_OF_SCOPE",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Decline to invent passive regeneration without a missing-health trace.

        :param context: Role-bound snapshot for the lane participant.
        :param duration_ms: Lane observation window in milliseconds.
        :param no_damage_delay_ms: Delay before out-of-combat recovery begins.
        :return: Zero recovery and the precise missing-state blocker.
        """
        return Decimal(0), ("SETT_PASSIVE_MISSING_HEALTH_REGEN_NOT_MODELED",)
