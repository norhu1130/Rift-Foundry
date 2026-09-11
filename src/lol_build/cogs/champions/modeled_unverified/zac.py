"""Zac combat Cog backed by locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing, health_cost
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class ZacCog(ChampionCog):
    """Model Zac's E5/W5/Q1/R2 level-thirteen engage fixture.

    Elastic Slingshot channels for its rank-five ``ChannelTime`` and lands for
    its damage and maximum knock-up. Unstable Matter deals flat damage plus a
    share of the target's maximum health, Stretching Strikes grabs and slams
    for two hits, and Let's Bounce! lands four bounces, each after the first at
    ``DamageReductionBounce``. Every ability pays its locked ``HPCost`` of
    current health, and every ability hit drops a Cell Division chunk that
    heals ``HealPercent`` of maximum health when reabsorbed. Revival through
    bloblets is excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Zac.json",
        "data/raw/16.17.1/communitydragon/champions/154.json",
        "data/raw/16.17.1/communitydragon/champions/zac.bin.json",
    )

    _E_LANDING_MS = 1300
    _E_KNOCKUP_MS = 1000
    _W_TIMES_MS = (1500, 6500)
    _Q_TIMES_MS = (2000, 2600)
    _R_BOUNCES_MS = (3200, 4200, 5200, 6200)
    _R_KNOCKUP_MS = 1000
    _CHUNK_PICKUP_DELAY_MS = 800

    def _chunk_heal(self, context: ParticipantContext) -> Decimal:
        """Evaluate one Cell Division chunk's heal.

        :param context: Role-bound Zac snapshot.
        :return: ``HealPercent`` (4% to 8% by level) of maximum health.
        """
        level = Decimal(context.snapshot.level - 1)
        return (Decimal("0.04") + Decimal("0.04") * level / Decimal(17)) * context.snapshot.max_hp

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Zac's slingshot, matter, strikes, and bounce rotation.

        :param context: Role-bound Zac and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        ap = snapshot.ability_power
        target_hp = context.opponent_snapshot.max_hp
        w_damage = Decimal(80) + (Decimal("0.08") + Decimal("0.0003") * ap) * target_hp
        q_damage = Decimal(60) + Decimal("0.3") * ap + Decimal("0.03") * snapshot.bonus_health
        r_first = Decimal(190) + Decimal("0.4") * ap
        hits: list[tuple[int, str, tuple]] = [
            (
                self._E_LANDING_MS,
                "ZAC_E_ELASTIC_SLINGSHOT",
                (
                    health_cost(context.self_entity, current_health_ratio=Decimal("0.04")),
                    damage(
                        context.opponent_entity,
                        Decimal(240) + Decimal("0.8") * ap,
                        DamageType.MAGIC,
                    ),
                    crowd_control(
                        context.opponent_entity, "AIRBORNE", duration_ms=self._E_KNOCKUP_MS
                    ),
                ),
            ),
            *(
                (
                    at_ms,
                    f"ZAC_W_UNSTABLE_MATTER_{index}",
                    (
                        health_cost(context.self_entity, current_health_ratio=Decimal("0.04")),
                        damage(context.opponent_entity, w_damage, DamageType.MAGIC),
                    ),
                )
                for index, at_ms in enumerate(self._W_TIMES_MS, start=1)
            ),
            *(
                (
                    at_ms,
                    f"ZAC_Q_STRETCHING_STRIKES_{index}",
                    (
                        *(
                            (
                                health_cost(
                                    context.self_entity, current_health_ratio=Decimal("0.08")
                                ),
                            )
                            if index == 1
                            else ()
                        ),
                        damage(context.opponent_entity, q_damage, DamageType.MAGIC),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=500,
                            magnitude=Decimal("0.40"),
                        ),
                    ),
                )
                for index, at_ms in enumerate(self._Q_TIMES_MS, start=1)
            ),
            *(
                (
                    at_ms,
                    f"ZAC_R_LETS_BOUNCE_{index}",
                    (
                        damage(
                            context.opponent_entity,
                            r_first if index == 1 else r_first * Decimal("0.5"),
                            DamageType.MAGIC,
                        ),
                        *(
                            (
                                crowd_control(
                                    context.opponent_entity,
                                    "AIRBORNE",
                                    duration_ms=self._R_KNOCKUP_MS,
                                ),
                            )
                            if index == 1
                            else (
                                crowd_control(
                                    context.opponent_entity,
                                    "SLOW",
                                    duration_ms=1000,
                                    magnitude=Decimal("0.20"),
                                ),
                            )
                        ),
                    ),
                )
                for index, at_ms in enumerate(self._R_BOUNCES_MS, start=1)
            ),
        ]
        events: list[ActionEvent] = []
        chunk = self._chunk_heal(context)
        for index, (at_ms, event_id, outputs) in enumerate(sorted(hits)):
            if at_ms > context.duration_ms:
                continue
            events.append(
                action(
                    event_id,
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=outputs,
                )
            )
            pickup_ms = at_ms + self._CHUNK_PICKUP_DELAY_MS
            if pickup_ms <= context.duration_ms:
                events.append(
                    action(
                        f"ZAC_PASSIVE_CHUNK_REABSORBED_{index + 1}",
                        at_ms=pickup_ms,
                        sequence=base + 100 + index,
                        source=context.self_entity,
                        channel=ActionChannel.PASSIVE,
                        outputs=(healing(context.self_entity, chunk),),
                        requires_living_opponent=False,
                    )
                )
        events.extend(self._basic_attack_events(context))
        level_blockers = (
            () if snapshot.level == 13 else (f"ZAC_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "zac_e5_w5_q1_r2_slingshot_open_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "ZAC_LEVEL13_E5_W5_Q1_R2_POLICY_UNVERIFIED",
                "ZAC_PASSIVE_EVERY_CHUNK_REABSORBED_ASSUMED",
                "ZAC_PASSIVE_BLOBLET_REVIVAL_NOT_MODELED",
                "ZAC_E_FULL_CHANNEL_MAXIMUM_KNOCKUP_ASSUMED",
                "ZAC_W_AP_PERCENT_HEALTH_SCALING_READ_AS_PER_100_AP",
                "ZAC_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Fill gaps between spells with ordinary basic attacks.

        :param context: Role-bound Zac and opponent combat snapshots.
        :return: Ordinary basic-attack damage events.
        """
        interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 700
        return tuple(
            action(
                f"ZAC_BASIC_ATTACK_{index}",
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
            for index, at_ms in enumerate(
                range(self._E_LANDING_MS + 400, context.duration_ms + 1, interval)
            )
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the slingshot and first-bounce knock-ups as control windows.

        :param context: Role-bound Zac and opponent snapshots.
        :return: Deterministic control windows caused by Zac's rotation.
        """
        channels = (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY, ActionChannel.MOVEMENT)
        return ReactionPlan(
            "zac_e_r_knockup_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "zac_e_elastic_slingshot_knockup",
                    self._E_LANDING_MS,
                    min(self._E_LANDING_MS + self._E_KNOCKUP_MS, context.duration_ms),
                    channels,
                    "ZAC_E_ELASTIC_SLINGSHOT",
                    False,
                    ControlType.AIRBORNE,
                ),
                CastBlockWindow(
                    "zac_r_first_bounce_knockup",
                    self._R_BOUNCES_MS[0],
                    min(self._R_BOUNCES_MS[0] + self._R_KNOCKUP_MS, context.duration_ms),
                    channels,
                    "ZAC_R_LETS_BOUNCE_1",
                    False,
                    ControlType.AIRBORNE,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
