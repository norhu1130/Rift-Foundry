"""Ryze combat Cog backed by locked 16.17.1 champion sources."""

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


class RyzeCog(ChampionCog):
    """Model Ryze's Q5/E5/W1/R2 level-thirteen combo fixture.

    Spell Flux marks the opponent for ``DebuffDuration`` on its rank-five
    cooldown, and every Spell Flux or Rune Prison resets Overload. Rune
    Prison roots a Fluxed target for ``CCDuration``. Realm Warp's passive
    makes each Overload that hits a Fluxed target heal Ryze for its rank-two
    ``OverloadHealPercent``, read as a share of Overload's damage. Bonus-mana
    scaling (no mana stat reaches the snapshot) and Flux's Overload damage
    amplification (two candidate sources in the locked data) are excluded.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Ryze.json",
        "data/raw/16.17.1/communitydragon/champions/13.json",
        "data/raw/16.17.1/communitydragon/champions/ryze.bin.json",
    )

    _E_CYCLE_MS = 2500
    _W_AT_MS = 500
    _W_ROOT_MS = 1500
    _Q_AFTER_RESET_MS = 250
    _FLUX_MS = 4000
    _ATTACKS_FROM_MS = 1100

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Ryze's flux, overload, and rune-prison combo cycle.

        :param context: Role-bound Ryze and opponent combat snapshots.
        :return: Deterministic level-thirteen schedule with honest blockers.
        """
        base = self._sequence_base(context)
        snapshot = context.snapshot
        ap = snapshot.ability_power
        q_damage = Decimal(135) + Decimal("0.55") * ap
        events: list[ActionEvent] = []
        resets: list[int] = []
        for index, at_ms in enumerate(range(0, context.duration_ms + 1, self._E_CYCLE_MS)):
            events.append(
                action(
                    f"RYZE_E_SPELL_FLUX_{index + 1}",
                    at_ms=at_ms,
                    sequence=base + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            Decimal(150) + Decimal("0.5") * ap,
                            DamageType.MAGIC,
                        ),
                    ),
                )
            )
            resets.append(at_ms)
        events.append(
            action(
                "RYZE_W_RUNE_PRISON",
                at_ms=self._W_AT_MS,
                sequence=base + 20,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity, Decimal(60) + Decimal("0.6") * ap, DamageType.MAGIC
                    ),
                    crowd_control(context.opponent_entity, "ROOT", duration_ms=self._W_ROOT_MS),
                ),
            )
        )
        resets.append(self._W_AT_MS)
        for index, reset_ms in enumerate(sorted(resets)):
            at_ms = reset_ms + self._Q_AFTER_RESET_MS
            if at_ms > context.duration_ms:
                continue
            fluxed = any(
                0 <= at_ms - flux < self._FLUX_MS for flux in resets if flux % self._E_CYCLE_MS == 0
            )
            events.append(
                action(
                    f"RYZE_Q_OVERLOAD_{index + 1}",
                    at_ms=at_ms,
                    sequence=base + 40 + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            q_damage,
                            DamageType.MAGIC,
                            source_heal_ratio=Decimal("0.25") if fluxed else Decimal(0),
                        ),
                    ),
                )
            )
        interval = self._attack_interval_ms(snapshot.attack_speed)
        for index, at_ms in enumerate(
            range(self._ATTACKS_FROM_MS, context.duration_ms + 1, interval)
        ):
            events.append(
                action(
                    f"RYZE_BASIC_ATTACK_{index}",
                    at_ms=at_ms,
                    sequence=base + 700 + index,
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity, snapshot.attack_damage, DamageType.PHYSICAL
                        ),
                    ),
                )
            )
        level_blockers = (
            () if snapshot.level == 13 else (f"RYZE_MODEL_LEVEL_UNSUPPORTED:{snapshot.level}",)
        )
        return ActionPlan(
            "ryze_q5_e5_w1_r2_flux_cycle_level13_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            blockers=(
                *level_blockers,
                *self.verification_blockers(),
                "RYZE_LEVEL13_Q5_E5_W1_R2_POLICY_UNVERIFIED",
                "RYZE_BONUS_MANA_SCALING_NOT_IN_SNAPSHOT",
                "RYZE_FLUX_OVERLOAD_AMPLIFICATION_SOURCE_AMBIGUOUS",
                "RYZE_R_OVERLOAD_HEAL_READ_AS_PERCENT_OF_DAMAGE",
                "RYZE_R_REALM_WARP_TELEPORT_NOT_MODELED",
                "RYZE_RESOURCE_COSTS_NOT_EVALUATED",
                "RYZE_ROTATION_AND_HIT_TIMING_UNVERIFIED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose the Fluxed Rune Prison root as a control window.

        :param context: Role-bound Ryze and opponent snapshots.
        :return: Deterministic control windows caused by Ryze's rotation.
        """
        return ReactionPlan(
            "ryze_w_root_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "ryze_w_rune_prison_root",
                    self._W_AT_MS,
                    min(self._W_AT_MS + self._W_ROOT_MS, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "RYZE_W_RUNE_PRISON",
                    True,
                    ControlType.ROOT,
                ),
            ),
            blockers=(*self.verification_blockers(),),
        )
