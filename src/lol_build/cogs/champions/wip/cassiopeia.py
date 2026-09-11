"""Cassiopeia combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class CassiopeiaCog(ChampionCog):
    """Model Cassiopeia's E5/Q5/W1/R2 level-13 duel fixture.

    The deterministic policy begins with one unpoisoned Twin Fang, then uses
    Noxious Blast and a one-second Miasma contact assumption to exercise the
    poison-dependent Twin Fang branch. Petrifying Gaze assumes the target is
    facing Cassiopeia; geometry, facing, mana, and persistent-zone occupancy
    remain explicit verification blockers rather than hidden inputs.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Cassiopeia.json",
        "data/raw/16.17.1/communitydragon/champions/69.json",
        "data/raw/16.17.1/communitydragon/champions/cassiopeia.bin.json",
    )

    @staticmethod
    def _cooldown_ms(base_seconds: str, ability_haste: Decimal) -> int:
        """Apply ability haste to one locked base cooldown.

        :param base_seconds: Decimal base cooldown expressed in seconds.
        :param ability_haste: Aggregated non-negative ability haste.
        :return: Positive nearest-even cooldown in milliseconds.
        """
        seconds = Decimal(base_seconds) * Decimal(100) / (Decimal(100) + ability_haste)
        return max(
            1,
            int((seconds * Decimal(1000)).to_integral_value(ROUND_HALF_EVEN)),
        )

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Q5's champion-hit movement bonus for the approach metric.

        :param context: Role-bound snapshots for the encounter.
        :return: Rank-five Noxious Blast movement multiplier.
        """
        return Decimal("1.50")

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject boots and item channels absent from the fixed fixture.

        Cassiopeia cannot buy boots. Mana cannot constrain the current action
        schedule. AP, haste, movement, chassis, penetration, AD, attack speed,
        life steal, omnivamp, and heal and shield power remain represented.

        :param item: Normalized candidate from the locked item catalog.
        :return: Cassiopeia-scoped blocker, or ``None`` when represented.
        """
        groups = item.get("groups")
        if isinstance(groups, dict) and groups.get("purchase_limit") == "boots":
            return f"CASSIOPEIA_BOOTS_FORBIDDEN:{item['id']}"
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"CASSIOPEIA_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks so attack-speed value remains observable.

        :param context: Role-bound snapshots supplying damage and attack cadence.
        :return: Chronological physical attacks susceptible to blind.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 500
        events: list[ActionEvent] = []
        at_ms = 600
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"CASSIOPEIA_BASIC_ATTACK_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=base + len(events),
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
            at_ms += interval_ms
        return tuple(events)

    def _twin_fang_event(
        self,
        context: ParticipantContext,
        *,
        at_ms: int,
        sequence: int,
        poisoned: bool,
    ) -> ActionEvent:
        """Build one Twin Fang with its poison-dependent damage and healing.

        :param context: Cassiopeia and opponent combat snapshots.
        :param at_ms: Fixed cast-resolution timestamp.
        :param sequence: Stable equal-time ordering key.
        :param poisoned: Whether deterministic poison windows cover the cast.
        :return: One normal or poison-enhanced Twin Fang event.
        """
        ap = context.snapshot.ability_power
        amount = Decimal(100) + Decimal("0.10") * ap
        outputs = []
        suffix = "UNPOISONED"
        if poisoned:
            amount += Decimal(120) + Decimal("0.55") * ap
            outputs.append(healing(context.self_entity, Decimal("0.16") * ap))
            suffix = "POISONED"
        outputs.insert(0, damage(context.opponent_entity, amount, DamageType.MAGIC))
        return action(
            f"CASSIOPEIA_E_TWIN_FANG_{at_ms}_{suffix}",
            at_ms=at_ms,
            sequence=sequence,
            source=context.self_entity,
            channel=ActionChannel.ABILITY,
            outputs=tuple(outputs),
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build a deterministic E5/Q5/W1/R2 single-target sequence.

        Q poison is treated as a three-second state beginning at its fixed hit
        timestamp. Miasma assumes one second of target occupancy. Twin Fang's
        poison branch is selected from those frozen windows.

        :param context: Role-bound Cassiopeia and opponent snapshots.
        :return: Damage, healing, poison, control, attacks, and blockers.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        r_damage = Decimal(250) + Decimal("0.50") * ap
        q_damage = Decimal(215) + Decimal("0.65") * ap
        w_damage = Decimal(20) + Decimal("0.10") * ap
        spell_events: list[ActionEvent] = [
            action(
                "CASSIOPEIA_R_PETRIFYING_GAZE_FACING_STUN",
                at_ms=200,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.MAGIC),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=2000),
                ),
            ),
            self._twin_fang_event(
                context,
                at_ms=400,
                sequence=base + 1,
                poisoned=False,
            ),
            action(
                "CASSIOPEIA_Q_NOXIOUS_BLAST_1",
                at_ms=800,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, q_damage, DamageType.MAGIC),
                    StatusOutput(context.opponent_entity, "CASSIOPEIA_POISON_Q", 3000),
                    StatusOutput(context.self_entity, "CASSIOPEIA_Q_MOVE_SPEED", 3000),
                ),
            ),
            action(
                "CASSIOPEIA_W_MIASMA_ONE_SECOND_CONTACT",
                at_ms=3900,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, w_damage, DamageType.MAGIC),
                    StatusOutput(context.opponent_entity, "CASSIOPEIA_POISON_W", 1000),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=1000,
                        magnitude=Decimal("0.40"),
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "GROUNDED",
                        duration_ms=1000,
                    ),
                ),
            ),
        ]
        q_cooldown = self._cooldown_ms("3.5", context.snapshot.ability_haste)
        q_number = 2
        q_at_ms = 800 + q_cooldown
        while q_at_ms <= context.duration_ms:
            spell_events.append(
                action(
                    f"CASSIOPEIA_Q_NOXIOUS_BLAST_{q_number}",
                    at_ms=q_at_ms,
                    sequence=base + 3 + q_number,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, q_damage, DamageType.MAGIC),
                        StatusOutput(context.opponent_entity, "CASSIOPEIA_POISON_Q", 3000),
                        StatusOutput(context.self_entity, "CASSIOPEIA_Q_MOVE_SPEED", 3000),
                    ),
                )
            )
            q_number += 1
            q_at_ms += q_cooldown
        q_windows = tuple(
            (event.at_ms, event.at_ms + 3000)
            for event in spell_events
            if event.id.startswith("CASSIOPEIA_Q_NOXIOUS_BLAST_")
        )
        poison_windows = (*q_windows, (3900, 4900))
        e_cooldown = self._cooldown_ms("0.75", context.snapshot.ability_haste)
        e_at_ms = 1200
        e_number = 1
        while e_at_ms <= context.duration_ms:
            poisoned = any(start <= e_at_ms < end for start, end in poison_windows)
            spell_events.append(
                self._twin_fang_event(
                    context,
                    at_ms=e_at_ms,
                    sequence=base + 100 + e_number,
                    poisoned=poisoned,
                )
            )
            e_number += 1
            e_at_ms += e_cooldown
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"CASSIOPEIA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "cassiopeia_e5_q5_w1_r2_level13_poison_v1",
            tuple(
                sorted(
                    (*spell_events, *self._basic_attacks(context)),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "CASSIOPEIA_LEVEL13_E5_Q5_W1_R2_POLICY_UNVERIFIED",
                "CASSIOPEIA_CAST_PROJECTILE_AND_POISON_TICK_TIMING_UNVERIFIED",
                "CASSIOPEIA_Q_DAMAGE_TICKS_AGGREGATED_AT_HIT",
                "CASSIOPEIA_Q_HIT_FOR_MOVE_SPEED_ASSUMED",
                "CASSIOPEIA_W_ONE_SECOND_ZONE_OCCUPANCY_ASSUMED",
                "CASSIOPEIA_W_GROUNDED_DASH_CHANNEL_NOT_REPRESENTABLE",
                "CASSIOPEIA_R_TARGET_FACING_ASSUMED",
                "CASSIOPEIA_MANA_BUDGET_NOT_MODELED",
                "CASSIOPEIA_PASSIVE_LEVEL_MOVE_SPEED_NOT_IN_SNAPSHOT",
                "CASSIOPEIA_MULTI_TARGET_EFFECTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose facing-R stun and the representable portion of Miasma CC.

        The W slow blocks the abstract movement channel. Grounded is retained
        in the action output, but it cannot selectively disable dashes because
        the shared channel model does not distinguish walking from mobility
        spells.

        :param context: Role-bound snapshots identifying Cassiopeia's opponent.
        :return: Source-linked stun and slow windows with honest blockers.
        """
        return ReactionPlan(
            "cassiopeia_r_facing_stun_w_slow_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "cassiopeia_r_facing_stun",
                    200,
                    min(2200, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "CASSIOPEIA_R_PETRIFYING_GAZE_FACING_STUN",
                    True,
                    ControlType.STUN,
                ),
                CastBlockWindow(
                    "cassiopeia_w_miasma_slow",
                    3900,
                    min(4900, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "CASSIOPEIA_W_MIASMA_ONE_SECOND_CONTACT",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=(
                "CASSIOPEIA_R_TARGET_FACING_ASSUMED",
                "CASSIOPEIA_R_AWAY_FACING_SLOW_BRANCH_NOT_SELECTED",
                "CASSIOPEIA_W_ONE_SECOND_ZONE_OCCUPANCY_ASSUMED",
                "CASSIOPEIA_W_GROUNDED_DASH_CHANNEL_NOT_REPRESENTABLE",
                "CASSIOPEIA_CONTROL_HIT_TIMING_UNVERIFIED",
            ),
        )
