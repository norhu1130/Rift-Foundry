"""Lucian combat Cog backed by locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    ChampionCog,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, damage, movement_speed
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class LucianCog(ChampionCog):
    """Model Lucian's Q5/E5/W1/R2 spell-weaving fixture.

    E, W, and Q each arm one Lightslinger pair. Six champion-hit passive shots
    reduce the rank-five E cooldown enough for a second dash. The Culling is
    represented as separate evenly spaced bullets so later shots can be
    cancelled by control instead of hiding the channel in one aggregate hit.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Lucian.json",
        "data/raw/16.17.1/communitydragon/champions/236.json",
        "data/raw/16.17.1/communitydragon/champions/lucian.bin.json",
    )

    _SPELLS = ((0, "E"), (1000, "W"), (1800, "Q"))
    _R_START_MS = 2500
    _R_DURATION_MS = 3000
    _SECOND_E_AT_MS = 6000

    @staticmethod
    def _passive_second_shot_ratio(level: int) -> Decimal:
        """Resolve Lightslinger's level-breakpoint second-shot ratio.

        :param level: Current champion level.
        :return: Total-AD fraction dealt by the second shot.
        """
        ratio = Decimal("0.50")
        if level >= 7:
            ratio += Decimal("0.05")
        if level >= 13:
            ratio += Decimal("0.05")
        return ratio

    def _lightslinger_event(
        self, context: ParticipantContext, *, at_ms: int, label: str, sequence: int
    ) -> ActionEvent:
        """Build one two-shot Lightslinger attack event.

        :param context: Role-bound snapshots identifying AD and recipients.
        :param at_ms: Timestamp of the passive attack.
        :param label: Stable identifier segment for the arming spell.
        :param sequence: Deterministic ordering key.
        :return: Basic attack with full first and reduced second shot.
        """
        total_ad = context.snapshot.attack_damage
        return action(
            f"LUCIAN_PASSIVE_LIGHTSLINGER_AFTER_{label}",
            at_ms=at_ms,
            sequence=sequence,
            source=context.self_entity,
            channel=ActionChannel.BASIC_ATTACK,
            outputs=(
                damage(context.opponent_entity, total_ad, DamageType.PHYSICAL),
                damage(
                    context.opponent_entity,
                    total_ad * self._passive_second_shot_ratio(context.snapshot.level),
                    DamageType.PHYSICAL,
                ),
            ),
        )

    @staticmethod
    def _culling_shot_count(critical_chance: Decimal) -> int:
        """Calculate Culling bullets using locked crit chance scaling.

        The snapshot does not expose critical-damage modifiers, so the locked
        base 175% multiplier supplies the 0.75 bonus term.

        :param critical_chance: Fractional critical-strike chance.
        :return: Floored positive bullet count.
        """
        scaled = Decimal(22) * (Decimal(1) + Decimal("0.75") * critical_chance)
        return max(1, int(scaled.to_integral_value(rounding=ROUND_FLOOR)))

    def _culling_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule individually cancellable Culling bullets.

        :param context: Snapshot supplying AD, AP, crit, roles, and duration.
        :return: Evenly spaced R2 bullet events within the three-second channel.
        """
        count = self._culling_shot_count(context.snapshot.critical_strike_chance)
        bullet = (
            Decimal(30)
            + Decimal("0.25") * context.snapshot.attack_damage
            + Decimal("0.15") * context.snapshot.ability_power
        )
        base = self._sequence_base(context) + 200
        events: list[ActionEvent] = []
        for index in range(count):
            at_ms = self._R_START_MS + index * self._R_DURATION_MS // count
            if at_ms > context.duration_ms:
                break
            events.append(
                action(
                    f"LUCIAN_R_THE_CULLING_BULLET_{index + 1}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, bullet, DamageType.PHYSICAL),),
                )
            )
        return tuple(events)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Convert W1's marked-target 60 flat speed into a multiplier.

        :param context: Snapshot supplying Lucian's current movement speed.
        :return: Movement multiplier while Ardent Blaze's proc is active.
        """
        return (context.snapshot.move_speed + Decimal(60)) / context.snapshot.move_speed

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Relentless Pursuit's maximum locked dash distance.

        :param context: Role-bound Lucian encounter context.
        :return: Dash distance in game units.
        """
        return Decimal(425)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item stats absent from Lucian's selected fixture.

        :param item: Normalized candidate from the locked catalog.
        :return: Lucian-scoped blocker, or ``None`` for represented stats.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "HEAL_SHIELD_POWER",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"LUCIAN_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build spell weaving, passive pairs, Culling, and refunded E.

        :param context: Role-bound Lucian and opponent snapshots.
        :return: Deterministic level-13 action schedule.
        """
        ap = context.snapshot.ability_power
        bonus_ad = context.snapshot.bonus_attack_damage
        base = self._sequence_base(context)
        events: list[ActionEvent] = [
            action(
                "LUCIAN_E_RELENTLESS_PURSUIT_1",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "LUCIAN_E_DASH", 315),),
                requires_living_opponent=False,
            ),
            action(
                "LUCIAN_W_ARDENT_BLAZE",
                at_ms=1000,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(75) + Decimal("0.90") * ap,
                        DamageType.MAGIC,
                    ),
                    movement_speed(context.self_entity, Decimal(60), duration_ms=1000),
                ),
            ),
            action(
                "LUCIAN_Q_PIERCING_LIGHT",
                at_ms=1800,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, Decimal(220) + bonus_ad, DamageType.PHYSICAL),
                ),
            ),
            action(
                "LUCIAN_E_RELENTLESS_PURSUIT_2_REFUNDED",
                at_ms=self._SECOND_E_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "LUCIAN_E_DASH", 315),),
                requires_living_opponent=False,
            ),
        ]
        for index, (at_ms, label) in enumerate(self._SPELLS):
            events.append(
                self._lightslinger_event(
                    context,
                    at_ms=at_ms + 250,
                    label=label,
                    sequence=base + 20 + index,
                )
            )
        events.append(
            self._lightslinger_event(
                context,
                at_ms=self._SECOND_E_AT_MS + 250,
                label="E2",
                sequence=base + 24,
            )
        )
        events.extend(self._culling_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"LUCIAN_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "lucian_q5_e5_w1_r2_spell_weave_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "LUCIAN_LEVEL13_Q5_E5_W1_R2_ORDER_LOCKED_UNVERIFIED",
                "LUCIAN_LIGHTSLINGER_PAIR_TIMING_SYNTHETIC",
                "LUCIAN_E2_ASSUMES_ALL_SIX_PASSIVE_SHOTS_HIT_CHAMPION",
                "LUCIAN_R_ALL_BULLETS_HIT_TARGET_ASSUMED",
                "LUCIAN_R_BASE_CRITICAL_DAMAGE_MULTIPLIER_ASSUMED_1_75",
                "LUCIAN_VIGILANCE_ALLY_BUFF_ON_HIT_NOT_MODELED",
                "LUCIAN_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Return an explicit empty reaction because Lucian applies no CC.

        :param context: Role-bound Lucian and opponent snapshots.
        :return: Empty reaction plan with a Culling-channel blocker.
        """
        return ReactionPlan(
            "lucian_no_hostile_control_v1",
            blockers=("LUCIAN_R_CHANNEL_SELF_MOVEMENT_RESTRICTIONS_NOT_MODELED",),
        )
