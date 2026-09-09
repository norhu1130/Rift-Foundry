"""Diana combat Cog backed by the locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

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


class DianaCog(ChampionCog):
    """Model Diana's Q5/W5/E1/R2 level-13 single-target sequence.

    The fixture starts with Crescent Strike applying Moonlight, spends that mark
    on the first Lunar Rush, and represents the resulting reset with a second
    immediate Lunar Rush. Pale Cascade assumes all three orbiting spheres hit
    the duel target. Moonfall models its single-target pull and delayed damage;
    target count amplification remains outside the benchmark.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Diana.json",
        "data/raw/16.17.1/communitydragon/champions/131.json",
        "data/raw/16.17.1/communitydragon/champions/diana.bin.json",
    )

    _ATTACK_SPEED_RATIO = Decimal("0.6940000057220459")
    _Q_AT_MS = 100
    _W_AT_MS = 250
    _E_MARKED_AT_MS = 450
    _E_RESET_AT_MS = 700
    _W_CONTACT_AT_MS = 900
    _R_AT_MS = 1100
    _R_DAMAGE_AT_MS = 2100

    @staticmethod
    def _passive_cleave_base(level: int) -> Decimal:
        """Evaluate Moonsilver Blade's locked level-breakpoint base damage.

        :param level: Diana's current champion level.
        :return: Raw passive base damage before its AP ratio.
        """
        bounded = min(18, max(1, level))
        result = Decimal(20)
        for gained_level in range(2, bounded + 1):
            if gained_level >= 17:
                result += Decimal(25)
            elif gained_level >= 12:
                result += Decimal(15)
            elif gained_level >= 7:
                result += Decimal(10)
            else:
                result += Decimal(5)
        return result

    @staticmethod
    def _haste_cooldown_ms(base_ms: int, ability_haste: Decimal) -> int:
        """Apply ability haste to a locked base cooldown.

        :param base_ms: Rank-specific unmodified cooldown in milliseconds.
        :param ability_haste: Non-negative haste from the participant snapshot.
        :return: Cooldown rounded upward to a deterministic millisecond.
        """
        haste = max(Decimal(0), ability_haste)
        return int(
            (Decimal(base_ms) * Decimal(100) / (Decimal(100) + haste)).to_integral_value(
                ROUND_CEILING
            )
        )

    @staticmethod
    def _spell_empowered_attack_speed(level: int) -> Decimal:
        """Resolve the locked post-spell passive attack-speed ratio.

        :param level: Diana's current champion level.
        :return: Bonus attack-speed fraction after the three-times multiplier.
        """
        bounded = min(18, max(1, level))
        ordinary = Decimal("0.15") + Decimal("0.20") * Decimal(bounded - 1) / Decimal(17)
        return ordinary * Decimal(3)

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Lunar Rush's locked target dash range.

        :param context: Role-bound Diana encounter context.
        :return: Lunar Rush range in game units.
        """
        return Decimal(825)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Diana's fixed event model.

        :param item: Normalized candidate from the locked item catalog.
        :return: Diana-scoped blocker for unsupported stats, otherwise ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "MANA_REGEN",
            "OMNIVAMP",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"DIANA_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule empowered attacks and every-third-hit passive damage.

        :param context: Role-bound snapshots supplying cadence and damage stats.
        :return: Chronological physical attacks with periodic magic cleaves.
        """
        empowered_speed = context.snapshot.attack_speed + (
            self._ATTACK_SPEED_RATIO
            * self._spell_empowered_attack_speed(context.snapshot.level)
        )
        interval_ms = self._attack_interval_ms(empowered_speed)
        cleave = self._passive_cleave_base(context.snapshot.level) + (
            Decimal("0.50") * context.snapshot.ability_power
        )
        base = self._sequence_base(context) + 200
        events: list[ActionEvent] = []
        at_ms = 1300
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            outputs = [
                damage(
                    context.opponent_entity,
                    context.snapshot.attack_damage,
                    DamageType.PHYSICAL,
                )
            ]
            if index % 3 == 0:
                outputs.append(damage(context.opponent_entity, cleave, DamageType.MAGIC))
            events.append(
                action(
                    f"DIANA_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
            at_ms += interval_ms
        return tuple(events)

    def _q_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule every Q cast made legal by the eight-second horizon.

        :param context: Role-bound snapshot carrying AP and ability haste.
        :return: One or more deterministic Crescent Strike damage events.
        """
        cooldown_ms = self._haste_cooldown_ms(6000, context.snapshot.ability_haste)
        amount = Decimal(210) + Decimal("0.70") * context.snapshot.ability_power
        base = self._sequence_base(context)
        events: list[ActionEvent] = []
        at_ms = self._Q_AT_MS
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"DIANA_Q_CRESCENT_STRIKE_{index}",
                    at_ms=at_ms,
                    sequence=base + index - 1,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, amount, DamageType.MAGIC),),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Diana's locked Moonlight-reset single-target combat plan.

        :param context: Role-bound Diana and opponent combat snapshots.
        :return: Deterministic spells, shield applications, and passive attacks.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        e_damage = Decimal(50) + Decimal("0.60") * ap
        orb_damage = Decimal(68) + Decimal("0.18") * ap
        shield = (
            Decimal(105)
            + Decimal("0.30") * ap
            + Decimal("0.11") * context.snapshot.bonus_health
        )
        fixed_events = (
            action(
                "DIANA_W_PALE_CASCADE_SHIELD",
                at_ms=self._W_AT_MS,
                sequence=base + 20,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(shielding(context.self_entity, shield, duration_ms=5000),),
                requires_living_opponent=False,
            ),
            action(
                "DIANA_E_LUNAR_RUSH_MOONLIGHT",
                at_ms=self._E_MARKED_AT_MS,
                sequence=base + 21,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, e_damage, DamageType.MAGIC),),
            ),
            action(
                "DIANA_E_LUNAR_RUSH_RESET",
                at_ms=self._E_RESET_AT_MS,
                sequence=base + 22,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, e_damage, DamageType.MAGIC),),
            ),
            action(
                "DIANA_W_THREE_ORBS_AND_RESHIELD",
                at_ms=self._W_CONTACT_AT_MS,
                sequence=base + 23,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, orb_damage, DamageType.MAGIC),
                    damage(context.opponent_entity, orb_damage, DamageType.MAGIC),
                    damage(context.opponent_entity, orb_damage, DamageType.MAGIC),
                    shielding(context.self_entity, shield, duration_ms=5000),
                ),
            ),
            action(
                "DIANA_R_MOONFALL_PULL",
                at_ms=self._R_AT_MS,
                sequence=base + 24,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=250),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=2000,
                        magnitude=Decimal("0.50"),
                    ),
                ),
            ),
            action(
                "DIANA_R_MOONFALL_SINGLE_TARGET_DAMAGE",
                at_ms=self._R_DAMAGE_AT_MS,
                sequence=base + 25,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        Decimal(300) + Decimal("0.60") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"DIANA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "diana_q5_w5_e1_r2_level13_moonlight_reset_v1",
            tuple(
                sorted(
                    (*self._q_events(context), *fixed_events, *self._basic_attacks(context)),
                    key=lambda event: (event.at_ms, event.sequence, event.id),
                )
            ),
            (
                *level_blockers,
                "DIANA_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "DIANA_Q_MOONLIGHT_HIT_AND_DURATION_ASSUMED",
                "DIANA_E_FIRST_CAST_CONSUMES_MOONLIGHT_AND_RESETS_ASSUMED",
                "DIANA_W_ALL_THREE_ORBS_CONTACT_SINGLE_TARGET_ASSUMED",
                "DIANA_W_ORB_COLLISION_AND_RESHIELD_TIMING_UNVERIFIED",
                "DIANA_R_PULL_DURATION_UNVERIFIED",
                "DIANA_R_MULTI_TARGET_AMPLIFICATION_NOT_MODELED",
                "DIANA_POSITION_AND_COLLISION_NOT_MODELED",
                "DIANA_PASSIVE_STARTS_AT_ZERO_ATTACKS_ASSUMED",
                "DIANA_PASSIVE_ATTACK_SPEED_REFRESH_TIMING_SIMPLIFIED",
                "DIANA_CAST_AND_ATTACK_TIMING_UNVERIFIED",
                "DIANA_MANA_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Moonfall's pull and slow as causal control windows.

        :param context: Role-bound snapshots identifying Diana's opponent.
        :return: Pull and movement-control intervals linked to Moonfall.
        """
        return ReactionPlan(
            "diana_moonfall_single_target_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "diana_r_pull",
                    self._R_AT_MS,
                    min(self._R_AT_MS + 250, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "DIANA_R_MOONFALL_PULL",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "diana_r_slow",
                    self._R_AT_MS,
                    min(self._R_AT_MS + 2000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "DIANA_R_MOONFALL_PULL",
                    True,
                    ControlType.SLOW,
                ),
            ),
            blockers=(
                "DIANA_R_PULL_DURATION_UNVERIFIED",
                "DIANA_R_MULTI_TARGET_AMPLIFICATION_NOT_MODELED",
                "DIANA_POSITION_AND_COLLISION_NOT_MODELED",
            ),
        )
