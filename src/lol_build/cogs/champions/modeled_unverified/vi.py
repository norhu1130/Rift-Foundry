"""Vi combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.core.timeline import ActionChannel, ActionEvent


class ViCog(ChampionCog):
    """Model Vi's Q5/E5/W1/R2 level-thirteen duel fixture.

    Denting Blows procs on the third attack against the same target, Relentless
    Force empowers the attack it precedes, Vault Breaker dashes in for its
    minimum-charge damage, and Cease and Desist locks the primary target down.
    Vault Breaker's full-charge value, Relentless Force's second charge, and
    Cease and Desist's secondary-target collision are excluded rather than
    guessed: each depends on a hold duration or positioning this fixture does
    not vary.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Vi.json",
        "data/raw/16.17.1/communitydragon/champions/254.json",
        "data/raw/16.17.1/communitydragon/champions/vi.bin.json",
    )

    _E_AT_MS = 0
    _Q_AT_MS = 700
    _R_AT_MS = 1600
    _R_TRAVEL_DELAY_MS = 700
    _R_STUN_MS = 1300

    def _w_bonus(self, context: ParticipantContext) -> Decimal:
        """Compute Denting Blows's every-third-attack max-health bonus.

        :param context: Role-bound Vi and opponent snapshots.
        :return: Flat physical damage equal to the locked percent of the
            opponent's known max health at this snapshot.
        """
        percent = Decimal("0.04") + Decimal("0.00035") * context.snapshot.bonus_attack_damage
        return percent * context.opponent_snapshot.max_hp

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill the duel with basic attacks, applying E and W's on-hit bonuses.

        :param context: Role-bound Vi and opponent combat snapshots.
        :return: Basic-attack events, the first carrying Relentless Force and
            every third carrying Denting Blows.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 500
        e_bonus = Decimal(90) + Decimal("1.1") * context.snapshot.bonus_attack_damage
        w_bonus = self._w_bonus(context)
        events: list[ActionEvent] = []
        at_ms = 200
        index = 0
        while at_ms <= context.duration_ms:
            outputs = [
                damage(context.opponent_entity, context.snapshot.attack_damage, DamageType.PHYSICAL)
            ]
            if index == 0:
                outputs.append(damage(context.opponent_entity, e_bonus, DamageType.PHYSICAL))
            if index % 3 == 2:
                outputs.append(damage(context.opponent_entity, w_bonus, DamageType.PHYSICAL))
            events.append(
                action(
                    f"VI_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
            index += 1
            at_ms += interval
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Vi's empowered-attack, dash, stack, and stun rotation.

        :param context: Role-bound Vi and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        q_damage = Decimal(120) + Decimal("0.6") * context.snapshot.bonus_attack_damage
        r_damage = Decimal(250) + Decimal("0.9") * context.snapshot.bonus_attack_damage
        fixed = [
            action(
                "VI_Q_VAULT_BREAKER",
                at_ms=self._Q_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.PHYSICAL),),
            ),
            action(
                "VI_R_CEASE_AND_DESIST",
                at_ms=self._R_AT_MS + self._R_TRAVEL_DELAY_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, r_damage, DamageType.PHYSICAL),
                    crowd_control(context.opponent_entity, "AIRBORNE", duration_ms=self._R_STUN_MS),
                ),
            ),
        ]
        events = (*fixed, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"VI_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "vi_q5_e5_w1_r2_empowered_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "VI_Q_FULL_CHARGE_DAMAGE_AND_KNOCKBACK_NOT_MODELED",
                "VI_E_SECOND_CHARGE_NOT_MODELED",
                "VI_R_SECONDARY_TARGET_COLLISION_NOT_MODELED",
                "VI_PASSIVE_BLAST_SHIELD_NOT_MODELED",
                "VI_RESOURCE_COSTS_NOT_EVALUATED",
                "VI_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the Cease and Desist knock-up as this Cog's control window.

        :param context: Role-bound Vi and opponent snapshots.
        :return: Deterministic control windows caused by Vi's rotation.
        """
        start_ms = self._R_AT_MS + self._R_TRAVEL_DELAY_MS
        return ReactionPlan(
            "vi_r_stun_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "vi_r_cease_and_desist_knockup",
                    start_ms,
                    min(start_ms + self._R_STUN_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "VI_R_CEASE_AND_DESIST",
                    False,
                    ControlType.AIRBORNE,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Vault Breaker's minimum dash as a closing-distance benchmark.

        :param context: Concrete participant context.
        :return: Dash distance in game units.
        """
        return Decimal(250)
