"""Ashe combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class AsheCog(ChampionCog):
    """Model Ashe's W5/Q4/E1/R2 level-13 single-target duel rotation."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Ashe.json",
        "data/raw/16.17.1/communitydragon/champions/22.json",
        "data/raw/16.17.1/communitydragon/champions/ashe.bin.json",
    )

    @staticmethod
    def _frost_slow(context: ParticipantContext) -> Decimal:
        """Interpolate Frost Shot's locked level-scaled slow magnitude.

        :param context: Role-bound Ashe combat context containing her level.
        :return: Normal slow fraction at the modeled champion level.
        """
        level_offset = Decimal(context.snapshot.level - 1)
        return Decimal("0.20") + Decimal("0.10") * level_offset / Decimal(17)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject stat channels that the fixed Ashe timeline cannot value.

        Attack damage and attack speed affect modeled attacks, while ability
        power affects Enchanted Crystal Arrow. Critical chance changes Frost Shot
        damage, but the locked data's internal stat identifiers are not yet mapped
        to the shared snapshot contract. Resource-aware cooldowns and attributed
        sustain are also outside this fixed schedule.

        :param item: Normalized item candidate from the locked item catalog.
        :return: Ashe-scoped blocker, or ``None`` for represented stat channels.
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
            return f"ASHE_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Keep pursuit speed unchanged because Ashe has no self-mobility spell.

        Her 600-unit attack range remains available through the shared snapshot.
        Volley and Enchanted Crystal Arrow can initiate control at longer range,
        but the current engagement contract has no ranged-spell reach channel.

        :param context: Role-bound combat snapshots for the encounter.
        :return: Neutral movement-speed multiplier.
        """
        return Decimal(1)

    def _attack_event(
        self,
        context: ParticipantContext,
        *,
        event_id: str,
        at_ms: int,
        sequence: int,
        damage_ratio: Decimal = Decimal(1),
    ) -> ActionEvent:
        """Create one Frost Shot attack with physical damage and normal slow.

        :param context: Role-bound snapshots for Ashe and her opponent.
        :param event_id: Stable champion-scoped event identifier.
        :param at_ms: Attack timestamp within the benchmark.
        :param sequence: Stable ordering key for equal timestamps.
        :param damage_ratio: Total-attack-damage ratio resolved by the attack.
        :return: Basic-attack event consumed by the shared timeline.
        """
        return action(
            event_id,
            at_ms=at_ms,
            sequence=sequence,
            source=context.self_entity,
            channel=ActionChannel.BASIC_ATTACK,
            outputs=(
                damage(
                    context.opponent_entity,
                    damage_ratio * context.snapshot.attack_damage,
                    DamageType.PHYSICAL,
                ),
                crowd_control(
                    context.opponent_entity,
                    "SLOW",
                    duration_ms=2000,
                    magnitude=self._frost_slow(context),
                ),
            ),
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build W, attacks, Q flurries, and a minimum-duration R hit.

        Four scheduled attacks unlock Q in this deterministic fixture. The shared
        engine cannot make Focus depend on whether those attacks resolved, so
        cancellation-sensitive Focus remains a blocker. R uses its locked
        one-second minimum stun because encounter distance is not an input.

        :param context: Role-bound snapshots for Ashe and her opponent.
        :return: Deterministic level-13 action schedule with evidence blockers.
        """
        base = self._sequence_base(context)
        slow = self._frost_slow(context)
        events: list[ActionEvent] = []
        for index, at_ms in enumerate(range(100, context.duration_ms + 1, 4000), start=1):
            events.append(
                action(
                    f"ASHE_W_VOLLEY_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal(200) + context.snapshot.attack_damage,
                            DamageType.PHYSICAL,
                        ),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=2000,
                            magnitude=slow,
                        ),
                    ),
                )
            )

        base_interval = self._attack_interval_ms(context.snapshot.attack_speed)
        regular_times = tuple(
            400 + index * base_interval
            for index in range(4)
            if 400 + index * base_interval <= context.duration_ms
        )
        for index, at_ms in enumerate(regular_times, start=1):
            events.append(
                self._attack_event(
                    context,
                    event_id=f"ASHE_FROST_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 100 + index,
                )
            )

        if len(regular_times) == 4:
            q_at_ms = regular_times[-1] + 250
            if q_at_ms <= context.duration_ms:
                events.append(
                    action(
                        "ASHE_Q_RANGERS_FOCUS",
                        at_ms=q_at_ms,
                        sequence=base + 200,
                        source=context.self_entity,
                        channel=ActionChannel.ABILITY,
                        outputs=(StatusOutput(context.self_entity, "ASHE_Q_ACTIVE", 6000),),
                        requires_living_opponent=False,
                    )
                )
                q_attack_speed = min(
                    Decimal("2.5"),
                    context.snapshot.attack_speed + Decimal("0.658") * Decimal("0.50"),
                )
                q_interval = self._attack_interval_ms(q_attack_speed)
                q_attack_ms = q_at_ms + 1
                q_index = 1
                while q_attack_ms <= context.duration_ms:
                    events.append(
                        self._attack_event(
                            context,
                            event_id=f"ASHE_Q_FLURRY_ATTACK_{q_index}",
                            at_ms=q_attack_ms,
                            sequence=base + 200 + q_index,
                            damage_ratio=Decimal("1.25"),
                        )
                    )
                    q_index += 1
                    q_attack_ms += q_interval

        if context.duration_ms >= 3400:
            events.append(
                action(
                    "ASHE_R_ENCHANTED_CRYSTAL_ARROW",
                    at_ms=3400,
                    sequence=base + 300,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal(400) + Decimal("1.20") * context.snapshot.ability_power,
                            DamageType.MAGIC,
                        ),
                        crowd_control(
                            context.opponent_entity,
                            "STUN",
                            duration_ms=1000,
                        ),
                    ),
                )
            )

        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"ASHE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "ashe_w5_q4_e1_r2_level13_locked_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "ASHE_LEVEL13_W5_Q4_E1_R2_POLICY_UNVERIFIED",
                "ASHE_ROTATION_AND_PROJECTILE_HIT_TIMING_UNVERIFIED",
                "ASHE_Q_FOCUS_STACK_RESOLUTION_NOT_CAUSALLY_MODELED",
                "ASHE_Q_ATTACK_RESET_TIMING_UNVERIFIED",
                "ASHE_FROST_SHOT_CRIT_DAMAGE_BONUS_NOT_MODELED",
                "ASHE_FROST_SHOT_SLOW_MOVEMENT_EFFECT_NOT_INTEGRATED",
                "ASHE_R_DISTANCE_BASED_STUN_NOT_MODELED_MINIMUM_USED",
                "ASHE_R_PROJECTILE_COLLISION_NOT_MODELED",
                "ASHE_RANGED_SPELL_REACH_NOT_CONNECTED_TO_ENGAGEMENT_MODEL",
                "ASHE_E_HAWKSHOT_NONCOMBAT_VISION_EXCLUDED",
                "ASHE_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Enchanted Crystal Arrow's minimum reducible stun window.

        :param context: Role-bound snapshots for Ashe and her opponent.
        :return: Causally linked one-second action block and honest blockers.
        """
        windows = (
            (
                CastBlockWindow(
                    "ashe_r_minimum_stun",
                    3400,
                    min(4400, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY),
                    "ASHE_R_ENCHANTED_CRYSTAL_ARROW",
                    True,
                    ControlType.STUN,
                ),
            )
            if context.duration_ms > 3400
            else ()
        )
        return ReactionPlan(
            "ashe_r_minimum_stun_reaction_v1",
            cast_block_windows=windows,
            blockers=(
                "ASHE_R_DISTANCE_BASED_STUN_NOT_MODELED_MINIMUM_USED",
                "ASHE_FROST_SHOT_SLOW_MOVEMENT_EFFECT_NOT_INTEGRATED",
            ),
        )
