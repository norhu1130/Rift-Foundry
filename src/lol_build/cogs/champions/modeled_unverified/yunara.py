"""Yunara combat Cog backed by locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    ChampionCog,
    CogMaturity,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class YunaraCog(ChampionCog):
    """Model Yunara's Q5/W5/E1/R2 level-thirteen transcendent fixture.

    Transcend One's Self opens the fight, turning Arc of Judgment into Arc of
    Ruin: a laser dealing ``Calc_RW_Damage`` with a slow, on a cooldown cut by
    ``RW_CDR``. Cultivation of Spirit's passive adds its rank-five on-hit
    magic damage to every attack, and after four champion hits fill its
    resource the active adds its on-hit damage again for ``Buff_Duration``.
    Critical strikes and the active's attack speed and spread are excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Yunara.json",
        "data/raw/16.17.1/communitydragon/champions/804.json",
        "data/raw/16.17.1/communitydragon/champions/yunara.bin.json",
    )

    _LASER_FIRST_MS = 300
    _LASER_COOLDOWN_MS = 2000
    _LASER_SLOW_MS = 1000
    _FIRST_ATTACK_MS = 200
    _HITS_FOR_ACTIVE = 4
    _ACTIVE_MS = 5000

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Yunara's transcendent laser and cultivation-empowered attacks.

        :param context: Role-bound Yunara and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        ap = snapshot.ability_power
        laser = Decimal(320) + Decimal("1.2") * snapshot.bonus_attack_damage + Decimal("0.75") * ap
        on_hit = Decimal(25) + Decimal("0.2") * ap
        events: list[ActionEvent] = []
        for index, at_ms in enumerate(
            range(self._LASER_FIRST_MS, context.duration_ms + 1, self._LASER_COOLDOWN_MS)
        ):
            events.append(
                action(
                    f"YUNARA_RW_ARC_OF_RUIN_{index + 1}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(context.opponent_entity, laser, DamageType.MAGIC),
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=self._LASER_SLOW_MS,
                            magnitude=Decimal("0.99"),
                        ),
                    ),
                )
            )
        interval = self._attack_interval_ms(snapshot.attack_speed)
        attack_times = tuple(range(self._FIRST_ATTACK_MS, context.duration_ms + 1, interval))
        active_from = (
            attack_times[self._HITS_FOR_ACTIVE - 1]
            if len(attack_times) >= self._HITS_FOR_ACTIVE
            else None
        )
        for index, at_ms in enumerate(attack_times):
            outputs = [
                damage(context.opponent_entity, snapshot.attack_damage, DamageType.PHYSICAL),
                damage(context.opponent_entity, on_hit, DamageType.MAGIC),
            ]
            if active_from is not None and active_from < at_ms <= active_from + self._ACTIVE_MS:
                outputs.append(damage(context.opponent_entity, on_hit, DamageType.MAGIC))
            events.append(
                action(
                    f"YUNARA_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 700 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=tuple(outputs),
                )
            )
        level_blockers = (
            () if snapshot.level == 13 else (f"YUNARA_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "yunara_q5_w5_e1_r2_transcendent_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "YUNARA_LEVEL13_Q5_W5_E1_R2_POLICY_UNVERIFIED",
                "YUNARA_W_DAMAGE_TYPE_ASSUMED_MAGIC",
                "YUNARA_Q_ACTIVE_ATTACK_SPEED_AND_SPREAD_NOT_MODELED",
                "YUNARA_PASSIVE_CRITICAL_MAGIC_DAMAGE_NOT_MODELED",
                "YUNARA_E_GHOSTED_DASH_NOT_MODELED",
                "YUNARA_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Report that Yunara's rotation applies no hard control.

        :param context: Role-bound Yunara and opponent snapshots.
        :return: Empty reaction plan carrying only evidence blockers.
        """
        return ReactionPlan(
            "yunara_no_hard_control_reaction_v1",
            blockers=(*self.verification_blockers(),),
        )
