"""Jhin combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    MissingHealthDamageOutput,
    StatusOutput,
)


class JhinCog(ChampionCog):
    """Model Jhin's Q5/W1/E5/R2 level-13 single-target four-shot fixture."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Jhin.json",
        "data/raw/16.17.1/communitydragon/champions/202.json",
        "data/raw/16.17.1/communitydragon/champions/jhin.bin.json",
    )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Report that Jhin has no displacement engage.

        :param context: Role-bound Jhin encounter context.
        :return: Zero game units.
        """
        return Decimal(0)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Keep pursuit speed neutral because the fixture has no fourth-shot crit state.

        :param context: Role-bound Jhin encounter context.
        :return: Neutral movement multiplier.
        """
        return Decimal(1)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject resource and sustain channels outside the fixed Jhin model.

        :param item: Normalized locked item candidate.
        :return: A champion-scoped blocker, or ``None`` for represented stats.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        return (
            f"JHIN_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
            if unsupported
            else None
        )

    def _attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule a deterministic four-shot magazine, including the fourth-shot execute.

        :param context: Snapshot supplying attack damage and critical chance.
        :return: Chronological physical attack events.
        """
        base = self._sequence_base(context) + 100
        ad = context.snapshot.attack_damage * (
            Decimal(1) + context.snapshot.critical_strike_chance * Decimal("0.25")
        )
        events = []
        for index, at_ms in enumerate((500, 1300, 2100, 2900), start=1):
            outputs = [damage(context.opponent_entity, ad, DamageType.PHYSICAL)]
            if index == 4:
                outputs.append(
                    MissingHealthDamageOutput(
                        context.opponent_entity, Decimal(0), Decimal("0.25"), DamageType.PHYSICAL
                    )
                )
                outputs.append(
                    StatusOutput(context.self_entity, "JHIN_FOURTH_SHOT_MOVEMENT_BONUS", 2000)
                )
            events.append(
                action(
                    f"JHIN_BASIC_ATTACK_SHOT_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
        return tuple(event for event in events if event.at_ms <= context.duration_ms)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Jhin's deterministic Q, trap, root, ultimate, and magazine schedule.

        :param context: Role-bound level-13 duel context.
        :return: Action plan with explicit projectile and bounce assumptions.
        """
        ap, ad, base = (
            context.snapshot.ability_power,
            context.snapshot.attack_damage,
            self._sequence_base(context),
        )
        events = [
            action(
                "JHIN_Q_DANCING_GRENADE_SINGLE_TARGET",
                at_ms=100,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(144) + Decimal("0.74") * ad + Decimal("0.60") * ap,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
            action(
                "JHIN_E_CAPTIVE_AUDIENCE_ASSUMED_TRIGGER",
                at_ms=900,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(260) + Decimal("1.20") * ad + Decimal("1.00") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity, "SLOW", duration_ms=2000, magnitude=Decimal("0.35")
                    ),
                ),
            ),
            action(
                "JHIN_W_DEADLY_FLOURISH_MARKED_HIT",
                at_ms=1700,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(70) + Decimal("0.50") * ad,
                        DamageType.PHYSICAL,
                    ),
                    crowd_control(context.opponent_entity, "ROOT", duration_ms=1250),
                ),
            ),
            action(
                "JHIN_R_CURTAIN_CALL_SHOT_1",
                at_ms=4300,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(128) + Decimal("0.25") * ad,
                        DamageType.PHYSICAL,
                    ),
                ),
            ),
        ]
        events.extend(self._attacks(context))
        return ActionPlan(
            "jhin_q5_w1_e5_r2_level13_four_shot_v1",
            tuple(
                sorted(
                    (event for event in events if event.at_ms <= context.duration_ms),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                (f"JHIN_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
                if context.snapshot.level != 13
                else ()
            )
            + (
                "JHIN_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "JHIN_Q_BOUNCE_KILL_AMPLIFICATION_NOT_MODELED",
                "JHIN_W_MARK_PREREQUISITE_ASSUMED",
                "JHIN_E_TRAP_PLACEMENT_AND_ARMING_ASSUMED",
                "JHIN_R_PROJECTILE_HIT_MISSING_HEALTH_SCALING_AND_EXTRA_SHOTS_NOT_MODELED",
                "JHIN_RELOAD_AND_CRITICAL_DAMAGE_STATE_NOT_MODELED",
                "JHIN_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the fixture's trap slow and marked Flourish root.

        :param context: Role-bound Jhin encounter context.
        :return: Source-linked control windows.
        """
        return ReactionPlan(
            "jhin_w1_e5_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "jhin_e_assumed_slow",
                    900,
                    min(2900, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "JHIN_E_CAPTIVE_AUDIENCE_ASSUMED_TRIGGER",
                    True,
                    ControlType.SLOW,
                ),
                CastBlockWindow(
                    "jhin_w_marked_root",
                    1700,
                    min(2950, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                        ActionChannel.ITEM_ACTIVE,
                    ),
                    "JHIN_W_DEADLY_FLOURISH_MARKED_HIT",
                    True,
                    ControlType.ROOT,
                ),
            ),
            blockers=(
                "JHIN_W_MARK_PREREQUISITE_ASSUMED",
                "JHIN_E_TRAP_PLACEMENT_AND_ARMING_ASSUMED",
            ),
        )
