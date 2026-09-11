"""Jinx combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    MissingHealthDamageOutput,
    StatusOutput,
)


class JinxCog(ChampionCog):
    """Model Jinx's Q5/W5/E1/R2 level-13 single-target fixture.

    One Fishbones attack precedes a fixed Pow-Pow three-stack ramp. Zap follows
    its haste-adjusted cooldown, one armed Chomper is assumed to trigger, and R
    receives full travel scaling. Get Excited remains inactive because the
    benchmark cannot promise a takedown.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Jinx.json",
        "data/raw/16.17.1/communitydragon/champions/222.json",
        "data/raw/16.17.1/communitydragon/champions/jinx.bin.json",
    )
    _AS_RATIO = Decimal("0.625")
    _MINIGUN_MAX_BONUS = Decimal("1.30")
    _E_TRIGGER_MS = 1300

    @staticmethod
    def _critical_multiplier(context: ParticipantContext) -> Decimal:
        """Return expected attack damage under the locked 2.0 crit modifier.

        :param context: Jinx snapshot containing critical-strike chance.
        :return: Deterministic expected-value attack multiplier.
        """
        return Decimal(1) + context.snapshot.critical_strike_chance

    @classmethod
    def _minigun_speed(cls, context: ParticipantContext, stacks: int) -> Decimal:
        """Calculate Pow-Pow speed at a deterministic stack count.

        :param context: Jinx snapshot supplying ordinary attack speed.
        :param stacks: Minigun stacks, clamped to zero through three.
        :return: Attacks per second after the rank-five ratio-scaled bonus.
        """
        stacks = min(3, max(0, stacks))
        bonus = cls._MINIGUN_MAX_BONUS * Decimal(stacks) / Decimal(3)
        return context.snapshot.attack_speed + cls._AS_RATIO * bonus

    @staticmethod
    def _cooldown_ms(base_ms: int, context: ParticipantContext) -> int:
        """Apply nonnegative ability haste to a base cooldown.

        :param base_ms: Locked base cooldown in milliseconds.
        :param context: Jinx snapshot containing ability haste.
        :return: Rounded haste-adjusted cooldown in milliseconds.
        """
        value = (
            Decimal(base_ms)
            * 100
            / (Decimal(100) + max(Decimal(0), context.snapshot.ability_haste))
        )
        return int(value.to_integral_value(rounding=ROUND_HALF_EVEN))

    def _weapon_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule the fixed Fishbones opener and Pow-Pow ramp.

        :param context: Role-bound snapshots used for damage and cadence.
        :return: Weapon state and basic-attack events in chronological order.
        """
        base = self._sequence_base(context) + 100
        critical = self._critical_multiplier(context)
        events = [
            action(
                "JINX_Q_FISHBONES_ACTIVE",
                at_ms=0,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.self_entity, "JINX_FISHBONES", 1200),),
                requires_living_opponent=False,
            )
        ]
        if context.duration_ms >= 300:
            events.append(
                action(
                    "JINX_Q_FISHBONES_ATTACK",
                    at_ms=300,
                    sequence=base + 1,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal("1.10") * context.snapshot.attack_damage * critical,
                            DamageType.PHYSICAL,
                        ),
                    ),
                )
            )
        if context.duration_ms >= 1200:
            events.append(
                action(
                    "JINX_Q_SWITCH_TO_POW_POW",
                    at_ms=1200,
                    sequence=base + 2,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(StatusOutput(context.self_entity, "JINX_POW_POW", 6800),),
                    requires_living_opponent=False,
                )
            )
        at_ms, stacks, index = 1450, 0, 1
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"JINX_Q_POW_POW_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 10 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            context.snapshot.attack_damage * critical,
                            DamageType.PHYSICAL,
                        ),
                    ),
                )
            )
            stacks = min(3, stacks + 1)
            at_ms += self._attack_interval_ms(self._minigun_speed(context, stacks))
            index += 1
        return tuple(events)

    def _zap_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule W5 casts on their haste-adjusted cooldown.

        :param context: Role-bound snapshot supplying total AD and haste.
        :return: Physical-damage and slow events for assumed hits.
        """
        base = self._sequence_base(context) + 500
        cooldown_ms = self._cooldown_ms(4000, context)
        raw_damage = Decimal(210) + Decimal("1.40") * context.snapshot.attack_damage
        events: list[ActionEvent] = []
        at_ms = 100
        while at_ms <= context.duration_ms:
            index = len(events) + 1
            events.append(
                action(
                    f"JINX_W_ZAP_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, raw_damage, DamageType.PHYSICAL),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=2000,
                            magnitude=Decimal("0.80"),
                        ),
                    ),
                )
            )
            at_ms += cooldown_ms
        return tuple(events)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Keep pursuit speed neutral without inventing a passive takedown.

        :param context: Role-bound Jinx encounter context.
        :return: Neutral multiplier while Get Excited remains inactive.
        """
        return Decimal(1)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the deterministic fixture.

        :param item: Normalized candidate from the locked item catalog.
        :return: Jinx-scoped blocker, or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "HEAL_SHIELD_POWER",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            return f"JINX_ITEM_STAT_NOT_MODELED:{item['id']}:{','.join(sorted(unsupported))}"
        return None

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked Q5/W5/E1/R2 level-13 duel sequence.

        :param context: Role-bound Jinx and opponent snapshots.
        :return: Deterministic weapon, spell, trap, and ultimate events.
        """
        base = self._sequence_base(context)
        events = [*self._weapon_events(context), *self._zap_events(context)]
        if context.duration_ms >= self._E_TRIGGER_MS:
            events.append(
                action(
                    "JINX_E_ASSUMED_CHOMPER_TRIGGER",
                    at_ms=self._E_TRIGGER_MS,
                    sequence=base + 700,
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal(90) + context.snapshot.ability_power,
                            DamageType.MAGIC,
                        ),
                        crowd_control(context.opponent_entity, "ROOT", duration_ms=1500),
                    ),
                )
            )
        if context.duration_ms >= 2000:
            events.append(
                action(
                    "JINX_R_FULL_TRAVEL_ROCKET",
                    at_ms=2000,
                    sequence=base + 800,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        MissingHealthDamageOutput(
                            context.opponent_entity,
                            Decimal(350) + Decimal("1.20") * context.snapshot.bonus_attack_damage,
                            Decimal("0.30"),
                            DamageType.PHYSICAL,
                        ),
                    ),
                )
            )
        levels = (
            ()
            if context.snapshot.level == 13
            else (f"JINX_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "jinx_q5_w5_e1_r2_weapon_swap_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *levels,
                "JINX_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "JINX_ROTATION_AND_ANIMATION_TIMING_UNVERIFIED",
                "JINX_Q_FISHBONES_SINGLE_TARGET_SPLASH_NOT_MODELED",
                "JINX_Q_WEAPON_SWITCH_AND_MINIGUN_STACK_TIMING_ASSUMED",
                "JINX_Q_ATTACK_SPEED_CAP_AND_STACK_EXPIRY_NOT_MODELED",
                "JINX_W_PROJECTILE_HIT_AND_CAST_TIME_ASSUMED",
                "JINX_E_CHOMPER_PLACEMENT_AND_TRIGGER_ASSUMED",
                "JINX_R_FULL_TRAVEL_SCALING_AND_PROJECTILE_HIT_ASSUMED",
                "JINX_R_SPLASH_TARGETS_NOT_MODELED",
                "JINX_PASSIVE_TAKEDOWN_AND_STRUCTURE_KILL_STATE_NOT_MODELED",
                "JINX_MANA_POOL_AND_COSTS_NOT_MODELED",
                "JINX_CRITICAL_ATTACKS_USE_EXPECTED_VALUE",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose W slow and the assumed Chomper root causally.

        :param context: Role-bound snapshots for Jinx and the opponent.
        :return: Movement-blocking windows tied to source events.
        """
        windows = [
            CastBlockWindow(
                f"{event.id.casefold()}_slow",
                event.at_ms,
                min(event.at_ms + 2000, context.duration_ms),
                (ActionChannel.MOVEMENT,),
                event.id,
                True,
                ControlType.SLOW,
            )
            for event in self._zap_events(context)
        ]
        if context.duration_ms > self._E_TRIGGER_MS:
            windows.append(
                CastBlockWindow(
                    "jinx_e_assumed_chomper_root",
                    self._E_TRIGGER_MS,
                    min(self._E_TRIGGER_MS + 1500, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "JINX_E_ASSUMED_CHOMPER_TRIGGER",
                    True,
                    ControlType.ROOT,
                )
            )
        return ReactionPlan(
            "jinx_w5_slow_e1_root_reaction_v1",
            cast_block_windows=tuple(windows),
            blockers=(
                "JINX_W_PROJECTILE_HIT_AND_CAST_TIME_ASSUMED",
                "JINX_E_CHOMPER_PLACEMENT_AND_TRIGGER_ASSUMED",
                "JINX_PASSIVE_TAKEDOWN_AND_STRUCTURE_KILL_STATE_NOT_MODELED",
            ),
        )
