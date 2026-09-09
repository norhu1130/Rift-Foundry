"""Pantheon combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class PantheonCog(ChampionCog):
    """Model Pantheon's Q5/W5/E1/R2 level-thirteen duel fixture.

    Mortal Will empowers every third ability or attack, so the rotation spends
    its stacks rather than assuming a permanent buff: W opens with its stun and
    consumes the opening stack, Q follows as the tap cast that refunds most of
    its cooldown, and E holds the shield for its locked duration. The ultimate
    is left out of an eight-second duel because its locked cooldown is one
    hundred fifty seconds at rank two and its cast is a channelled leap.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Pantheon.json",
        "data/raw/16.17.1/communitydragon/champions/80.json",
        "data/raw/16.17.1/communitydragon/champions/pantheon.bin.json",
    )

    #: Mortal Will empowers the third ability or attack; the opening rotation
    #: reaches that count on the W cast.
    _MORTAL_WILL_STACKS = 3

    _W_AT_MS = 0
    _W_STUN_MS = 1000
    _Q_AT_MS = 700
    _E_AT_MS = 1400
    #: Aegis Assault holds for its locked ShieldDuration of 1.5 seconds and
    #: strikes at its locked AttacksPerSecond of four.
    _E_DURATION_MS = 1500
    _E_STRIKE_COUNT = 6
    _Q_SECOND_AT_MS = 3600

    @staticmethod
    def _haste_cooldown_ms(base_ms: int, ability_haste: Decimal) -> int:
        """Apply ability haste to one locked base cooldown.

        :param base_ms: Locked cooldown in milliseconds before haste.
        :param ability_haste: Non-negative ability haste from items.
        :return: Rounded cooldown in milliseconds.
        """
        haste = max(Decimal(0), ability_haste)
        return int(
            (Decimal(base_ms) * Decimal(100) / (Decimal(100) + haste)).to_integral_value(
                ROUND_CEILING
            )
        )

    def _q_damage(self, context: ParticipantContext) -> Decimal:
        """Compute the rank-five Comet Spear tap damage.

        :param context: Snapshot supplying bonus attack damage.
        :return: Raw physical damage before mitigation.
        """
        return Decimal(160) + Decimal("1.15") * context.snapshot.bonus_attack_damage

    def _w_damage(self, context: ParticipantContext) -> Decimal:
        """Compute the rank-five Shield Vault damage.

        :param context: Snapshot supplying total attack damage.
        :return: Raw physical damage before mitigation.
        """
        return Decimal(25) + context.snapshot.attack_damage

    def _e_strike_damage(self, context: ParticipantContext) -> Decimal:
        """Split rank-one Aegis Assault damage across its locked strike count.

        :param context: Snapshot supplying bonus attack damage.
        :return: Raw physical damage for one strike.
        """
        total = Decimal(5) + Decimal("1.5") * context.snapshot.bonus_attack_damage
        return total / Decimal(self._E_STRIKE_COUNT)

    def _e_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule the held Aegis Assault strikes and its shield.

        :param context: Role-bound Pantheon and opponent snapshots.
        :return: Shield grant followed by evenly spaced strikes.
        """
        base = self._sequence_base(context) + 300
        strike = self._e_strike_damage(context)
        interval = self._E_DURATION_MS // self._E_STRIKE_COUNT
        # ByCharLevelBreakpoints(40 at level 1, +5/level, +10 from level 9,
        # +20 from level 15) evaluates to 125 at level thirteen under the
        # inclusive breakpoint convention; see _level_breakpoint_value.
        shield_base = self._level_breakpoint_value(
            Decimal(40), Decimal(5), ((9, Decimal(10)), (15, Decimal(20))), 13
        )
        shield_amount = shield_base + Decimal("1.5") * context.snapshot.bonus_attack_damage
        events: list[ActionEvent] = [
            action(
                "PANTHEON_E_AEGIS_ASSAULT_SHIELD",
                at_ms=self._E_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(context.self_entity, shield_amount, duration_ms=self._E_DURATION_MS),
                ),
                requires_living_opponent=False,
            )
        ]
        for index in range(1, self._E_STRIKE_COUNT + 1):
            at_ms = self._E_AT_MS + interval * index
            if at_ms > context.duration_ms:
                break
            events.append(
                action(
                    f"PANTHEON_E_AEGIS_ASSAULT_STRIKE_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, strike, DamageType.PHYSICAL),),
                )
            )
        return tuple(events)

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time outside the fixed casts and E channel with basic attacks.

        Aegis Assault's own strikes already cover the E channel, so this only
        adds attacks before it opens and after it ends.

        :param context: Role-bound Pantheon and opponent combat snapshots.
        :return: Ordinary basic-attack damage events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 500
        channel_end = self._E_AT_MS + self._E_DURATION_MS
        events: list[ActionEvent] = []
        at_ms = 200
        index = 0
        while at_ms <= context.duration_ms:
            if not (self._E_AT_MS <= at_ms < channel_end):
                events.append(
                    action(
                        f"PANTHEON_BASIC_ATTACK_{index}",
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
                )
                index += 1
            at_ms += interval
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Pantheon's stun-open, spear, and shield-hold rotation.

        :param context: Role-bound Pantheon and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        q_damage = self._q_damage(context)
        fixed = [
            action(
                "PANTHEON_W_SHIELD_VAULT",
                at_ms=self._W_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, self._w_damage(context), DamageType.PHYSICAL),
                    crowd_control(
                        context.opponent_entity, "STUN", duration_ms=self._W_STUN_MS
                    ),
                    StatusOutput(context.self_entity, "PANTHEON_MORTAL_WILL_SPENT", 4000),
                ),
            ),
            action(
                "PANTHEON_Q_COMET_SPEAR_TAP_1",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.PHYSICAL),),
            ),
        ]
        # A tap cast refunds 60% of its locked eight-second rank-five cooldown.
        recast_ms = self._Q_AT_MS + self._haste_cooldown_ms(
            int(Decimal(8000) * (Decimal(1) - Decimal("0.60"))),
            context.snapshot.ability_haste,
        )
        if recast_ms <= context.duration_ms:
            fixed.append(
                action(
                    "PANTHEON_Q_COMET_SPEAR_TAP_2",
                    at_ms=max(recast_ms, self._Q_SECOND_AT_MS),
                    sequence=base + 2,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, q_damage, DamageType.PHYSICAL),),
                )
            )
        events = (*fixed, *self._e_events(context), *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"PANTHEON_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "pantheon_q5_w5_e1_r2_stun_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "PANTHEON_MORTAL_WILL_STACK_TIMING_ASSUMED",
                "PANTHEON_E_SHIELD_LEVEL_CURVE_CONVENTION_ASSUMED",
                "PANTHEON_Q_HOLD_CAST_AND_EXECUTE_BONUS_NOT_MODELED",
                "PANTHEON_E_DIRECTIONAL_BLOCK_NOT_MODELED",
                "PANTHEON_E_SELF_SLOW_AND_RECAST_NOT_MODELED",
                "PANTHEON_R_EXCLUDED_COOLDOWN_EXCEEDS_ENCOUNTER",
                "PANTHEON_RESOURCE_COSTS_NOT_EVALUATED",
                "PANTHEON_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the Shield Vault stun as this Cog's hostile control window.

        :param context: Role-bound Pantheon and opponent snapshots.
        :return: Deterministic control windows caused by Pantheon's rotation.
        """
        return ReactionPlan(
            "pantheon_w_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "pantheon_w_shield_vault_stun",
                    self._W_AT_MS,
                    min(self._W_AT_MS + self._W_STUN_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "PANTHEON_W_SHIELD_VAULT",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(
                *self.verification_blockers(),
                "PANTHEON_E_INCOMING_DAMAGE_BLOCK_NOT_MODELED",
            ),
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Shield Vault's locked cast range as its closing distance.

        :param context: Concrete participant context.
        :return: Dash distance in game units.
        """
        return Decimal(600)
