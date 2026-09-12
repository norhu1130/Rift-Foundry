"""Sylas combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, missing_health_healing
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class SylasCog(ChampionCog):
    """Model Sylas's R2/Q5/W5/E1 level-thirteen duel fixture.

    Abscond dashes in and Abduct pulls Sylas to the opponent for its rank-one
    ``PullDamage`` and knock-up. Chain Lash lands its lash and slow, then its
    ``DetonationDelay`` explosion. Kingslayer deals its rank-five damage and
    heals for ``MinHealing`` (``Healing`` plus ``HealMinAPRatio`` of ability
    power plus ``HealMinHPRatio`` of bonus health), amplified toward
    ``MaxHealingPercentAmp`` as Sylas loses health. After each spell,
    Petricite Burst empowers the next attack with its locked ``PassiveDamage``.
    Hijack steals the opponent's ultimate, which no fixed fixture can know.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Sylas.json",
        "data/raw/16.17.1/communitydragon/champions/517.json",
        "data/raw/16.17.1/communitydragon/champions/sylas.bin.json",
    )

    _E2_AT_MS = 300
    _E2_KNOCKUP_MS = 500
    _Q_AT_MS = 900
    _Q_DETONATION_DELAY_MS = 600
    _Q_SLOW_MS = 1500
    _W_AT_MS = 1800
    _PASSIVE_DELAY_MS = 250
    _BASIC_ATTACKS_FROM_MS = 2400

    def _petricite_attack(
        self, context: ParticipantContext, *, index: int, at_ms: int
    ) -> ActionEvent:
        """Create one Petricite Burst-empowered basic attack.

        :param context: Role-bound Sylas and opponent snapshots.
        :param index: One-based empowered-attack index.
        :param at_ms: Timestamp of the attack.
        :return: Basic attack carrying the passive's magic damage.
        """
        passive = (
            Decimal("1.3") * context.snapshot.attack_damage
            + Decimal("0.3") * context.snapshot.ability_power
        )
        return action(
            f"SYLAS_PASSIVE_PETRICITE_BURST_{index}",
            at_ms=at_ms,
            sequence=self._sequence_base(context) + 50 + index,
            source=context.self_entity,
            channel=ActionChannel.BASIC_ATTACK,
            outputs=(
                damage(
                    context.opponent_entity, context.snapshot.attack_damage, DamageType.PHYSICAL
                ),
                damage(context.opponent_entity, passive, DamageType.MAGIC),
            ),
        )

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Sylas's abduct, chain-lash, and kingslayer rotation.

        :param context: Role-bound Sylas and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        ap = context.snapshot.ability_power
        w_heal = (
            self.rank_value("SylasW", "Healing", context, Decimal(100))
            + Decimal("0.3") * ap
            + Decimal("0.05") * context.snapshot.bonus_health
        )
        fixed = [
            action(
                "SYLAS_E2_ABDUCT",
                at_ms=self._E2_AT_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("SylasE2", "BaseDamage", context, Decimal(50))
                        + Decimal("0.8") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity, "AIRBORNE", duration_ms=self._E2_KNOCKUP_MS
                    ),
                ),
            ),
            action(
                "SYLAS_Q_CHAIN_LASH",
                at_ms=self._Q_AT_MS,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("SylasQ", "BaseDamage", context, Decimal(120))
                        + Decimal("0.4") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=self._Q_SLOW_MS,
                        magnitude=self.rank_value("SylasQ", "SlowAmount", context, Decimal("0.35")),
                    ),
                ),
            ),
            action(
                "SYLAS_Q_CHAIN_LASH_EXPLOSION",
                origin_event_id="SYLAS_Q_CHAIN_LASH",
                at_ms=self._Q_AT_MS + self._Q_DETONATION_DELAY_MS,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("SylasQ", "ExplosionBaseDamage", context, Decimal(280))
                        + Decimal("0.8") * ap,
                        DamageType.MAGIC,
                    ),
                ),
            ),
            action(
                "SYLAS_W_KINGSLAYER",
                at_ms=self._W_AT_MS,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        self.rank_value("SylasW", "Damage", context, Decimal(215))
                        + Decimal("0.6") * ap,
                        DamageType.MAGIC,
                    ),
                    # Up to double healing, read linearly down to 40% health.
                    missing_health_healing(
                        context.self_entity,
                        min(Decimal(1), w_heal / (Decimal("0.6") * context.snapshot.max_hp)),
                        base_amount=w_heal,
                    ),
                ),
            ),
        ]
        petricite = tuple(
            self._petricite_attack(context, index=index, at_ms=spell_ms + self._PASSIVE_DELAY_MS)
            for index, spell_ms in enumerate(
                (self._E2_AT_MS, self._Q_AT_MS, self._W_AT_MS), start=1
            )
        )
        events = (*fixed, *petricite, *self._basic_attack_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"SYLAS_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "sylas_r2_q5_w5_e1_abduct_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "SYLAS_LEVEL13_R2_Q5_W5_E1_POLICY_UNVERIFIED",
                "SYLAS_R_HIJACK_DEPENDS_ON_OPPONENT_ULTIMATE",
                "SYLAS_W_HEAL_AMPLIFICATION_READ_AS_LINEAR_TO_FORTY_PERCENT",
                "SYLAS_W_LOW_HEALTH_DAMAGE_AMPLIFICATION_NOT_MODELED",
                "SYLAS_PASSIVE_ATTACK_SPEED_AND_AREA_DAMAGE_NOT_MODELED",
                "SYLAS_RESOURCE_COSTS_NOT_EVALUATED",
                "SYLAS_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill time after the spell rotation with ordinary basic attacks.

        :param context: Role-bound Sylas and opponent combat snapshots.
        :return: Ordinary basic-attack damage events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 700
        events: list[ActionEvent] = []
        at_ms = self._BASIC_ATTACKS_FROM_MS
        index = 0
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"SYLAS_BASIC_ATTACK_{index}",
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

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the Abduct knock-up as this Cog's hostile control window.

        :param context: Role-bound Sylas and opponent snapshots.
        :return: Deterministic control windows caused by Sylas's rotation.
        """
        return ReactionPlan(
            "sylas_e2_knockup_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "sylas_e2_abduct_knockup",
                    self._E2_AT_MS,
                    min(self._E2_AT_MS + self._E2_KNOCKUP_MS, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                    ),
                    "SYLAS_E2_ABDUCT",
                    False,
                    ControlType.AIRBORNE,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
