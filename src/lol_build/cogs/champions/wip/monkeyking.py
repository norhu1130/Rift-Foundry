"""Wukong combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    ResistanceReductionOutput,
    StatusOutput,
)


class MonkeyKingCog(ChampionCog):
    """Model Wukong's E5/W1/Q5/R2 double-Cyclone fixture.

    Nimbus Strike starts the engagement and its attack-speed steroid controls
    attacks outside Cyclone. Crushing Blow applies a timed armor reduction.
    Both ultimate casts emit eight physical ticks; the selected clone mirrors
    the first cast at W1's thirty-five-percent damage coefficient.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/MonkeyKing.json",
        "data/raw/16.17.1/communitydragon/champions/62.json",
        "data/raw/16.17.1/communitydragon/champions/monkeyking.bin.json",
    )

    _E_AT_MS = 0
    _W_AT_MS = 150
    _Q_AT_MS = 300
    _FIRST_R_AT_MS = 500
    _SECOND_Q_AT_MS = 2700
    _SECOND_R_AT_MS = 3000

    def _q_event(self, context: ParticipantContext, *, at_ms: int, index: int) -> ActionEvent:
        """Create an empowered attack and its three-second armor shred.

        :param context: Snapshot supplying AD and role identities.
        :param at_ms: Timestamp of the empowered attack.
        :param index: Stable cast ordinal used in identifiers and sequencing.
        :return: Crushing Blow attack event.
        """
        amount = (
            context.snapshot.attack_damage
            + Decimal(120)
            + Decimal("0.50") * context.snapshot.bonus_attack_damage
        )
        return action(
            f"MONKEY_KING_Q_CRUSHING_BLOW_{index}",
            at_ms=at_ms,
            sequence=self._sequence_base(context) + 20 + index,
            source=context.self_entity,
            channel=ActionChannel.BASIC_ATTACK,
            outputs=(
                damage(context.opponent_entity, amount, DamageType.PHYSICAL),
                ResistanceReductionOutput(
                    context.opponent_entity,
                    "ARMOR",
                    Decimal("0.30"),
                    1,
                    3000,
                    "MONKEY_KING_Q_ARMOR_SHRED",
                ),
            ),
        )

    def _cyclone_events(
        self,
        context: ParticipantContext,
        *,
        start_ms: int,
        cast_index: int,
        clone_multiplier: Decimal,
    ) -> tuple[ActionEvent, ...]:
        """Split one Cyclone cast into eight independently cancellable ticks.

        :param context: Snapshot supplying AD, target health, and roles.
        :param start_ms: Start of this two-second channel.
        :param cast_index: First or second cast ordinal.
        :param clone_multiplier: Additional mimicked-damage fraction.
        :return: Eight quarter-second Cyclone damage events.
        """
        total = (
            Decimal("2.75") * context.snapshot.attack_damage
            + Decimal("0.12") * context.opponent_snapshot.max_hp
        )
        tick = total * (Decimal(1) + clone_multiplier) / Decimal(8)
        base = self._sequence_base(context) + 200 + cast_index * 20
        return tuple(
            action(
                f"MONKEY_KING_R_CYCLONE_{cast_index}_TICK_{tick_index}",
                at_ms=start_ms + (tick_index - 1) * 250,
                sequence=base + tick_index,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, tick, DamageType.PHYSICAL),),
            )
            for tick_index in range(1, 9)
            if start_ms + (tick_index - 1) * 250 <= context.duration_ms
        )

    def _attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule E-accelerated attacks outside Q and ultimate timestamps.

        :param context: Snapshot supplying attack speed, AD, and duration.
        :return: Synthetic ordinary attack events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed * Decimal("1.60"))
        times = list(range(350, self._FIRST_R_AT_MS, interval))
        times.extend(range(5000, context.duration_ms + 1, interval))
        base = self._sequence_base(context) + 500
        return tuple(
            action(
                f"MONKEY_KING_BASIC_ATTACK_{index}",
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
            for index, at_ms in enumerate(times, start=1)
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Cyclone's locked twenty-percent movement steroid.

        :param context: Role-bound Wukong encounter context.
        :return: Cyclone movement-speed multiplier.
        """
        return Decimal("1.20")

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Combine targeted E range with W's directional dash clamp.

        :param context: Role-bound Wukong encounter context.
        :return: Selected E-plus-W closing distance in game units.
        """
        return Decimal(950)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the selected fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Wukong-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            return f"MONKEY_KING_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build E entry, clone creation, two Qs, two Rs, and attacks.

        :param context: Role-bound Wukong and opponent snapshots.
        :return: Deterministic level-13 action schedule.
        """
        base = self._sequence_base(context)
        fixed = (
            action(
                "MONKEY_KING_E_NIMBUS_STRIKE",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(240) + context.snapshot.ability_power,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "MONKEY_KING_W_WARRIOR_TRICKSTER",
                at_ms=self._W_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "MONKEY_KING_CLONE", 4000),),
                requires_living_opponent=False,
            ),
            self._q_event(context, at_ms=self._Q_AT_MS, index=1),
            self._q_event(context, at_ms=self._SECOND_Q_AT_MS, index=2),
        )
        events = (
            *fixed,
            *self._cyclone_events(
                context,
                start_ms=self._FIRST_R_AT_MS,
                cast_index=1,
                clone_multiplier=Decimal("0.35"),
            ),
            *self._cyclone_events(
                context,
                start_ms=self._SECOND_R_AT_MS,
                cast_index=2,
                clone_multiplier=Decimal(0),
            ),
            *self._attack_events(context),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"MONKEY_KING_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "monkey_king_q5_w1_e5_r2_double_cyclone_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "MONKEY_KING_LEVEL13_Q5_E5_W1_R2_ORDER_LOCKED_UNVERIFIED",
                "MONKEY_KING_W_CAST_AT_150MS_AND_CLONE_FIRST_R_ONLY_ASSUMED",
                "MONKEY_KING_W_CLONE_BASIC_ATTACK_AND_Q_MIMIC_NOT_MODELED",
                "MONKEY_KING_Q_SECOND_CAST_TIMING_AND_REFUNDS_SYNTHETIC",
                "MONKEY_KING_E_SINGLE_TARGET_ONLY",
                "MONKEY_KING_R_TARGET_REMAINS_IN_BOTH_FULL_SPINS_ASSUMED",
                "MONKEY_KING_PASSIVE_ARMOR_AND_REGEN_STACKS_NOT_MODELED",
                "MONKEY_KING_W_STEALTH_TARGET_SELECTION_EFFECT_NOT_MODELED",
                "MONKEY_KING_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose one non-reducible knockup for each Cyclone cast.

        :param context: Role-bound Wukong and opponent snapshots.
        :return: Two airborne cast-block windows.
        """
        channels = (
            ActionChannel.BASIC_ATTACK,
            ActionChannel.ABILITY,
            ActionChannel.MOVEMENT,
        )
        return ReactionPlan(
            "monkey_king_double_cyclone_knockup_reaction_v1",
            cast_block_windows=tuple(
                CastBlockWindow(
                    f"monkey_king_r_cyclone_{index}_knockup",
                    start_ms,
                    min(start_ms + 600, context.duration_ms),
                    channels,
                    f"MONKEY_KING_R_CYCLONE_{index}_TICK_1",
                    False,
                    ControlType.AIRBORNE,
                )
                for index, start_ms in enumerate(
                    (self._FIRST_R_AT_MS, self._SECOND_R_AT_MS), start=1
                )
            ),
            blockers=(
                "MONKEY_KING_R_ONE_KNOCKUP_PER_TARGET_PER_CAST",
                "MONKEY_KING_W_STEALTH_HAS_NO_GENERIC_DAMAGE_IMMUNITY",
            ),
        )
