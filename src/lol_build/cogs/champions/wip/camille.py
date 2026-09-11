"""Camille combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing
from lol_build.core.combat import (
    DamageType,
    ResistanceModifiers,
    apply_resistance,
    apply_resistance_pipeline,
)
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    CurrentHealthDamageOutput,
    StatusOutput,
)


class CamilleCog(ChampionCog):
    """Model Camille's Q5/W1/E5/R2 level-13 duel fixture.

    The fixture assumes Hookshot connects through usable terrain, Tactical
    Sweep hits its outer edge, and The Hextech Ultimatum retains its chosen
    target. Target selection, terrain, evasion, and Adaptive Defenses remain
    explicit blockers instead of inferred dynamic state.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Camille.json",
        "data/raw/16.17.1/communitydragon/champions/164.json",
        "data/raw/16.17.1/communitydragon/champions/camille.bin.json",
    )

    _ATTACK_SPEED_RATIO = Decimal("0.644")
    _E5_ATTACK_SPEED_BONUS = Decimal("0.60")
    _Q5_BONUS_RATIO = Decimal("0.40")
    _Q2_AMPLIFIER = Decimal(2)
    _Q2_TRUE_CONVERSION_L13 = Decimal("0.88")
    _R2_CURRENT_HP_RATIO = Decimal("0.06")
    _R2_END_MS = 3650

    @staticmethod
    def _post_mitigation_physical(
        context: ParticipantContext,
        raw_damage: Decimal,
    ) -> Decimal:
        """Resolve physical damage for Tactical Sweep's healing amount.

        :param context: Snapshots supplying armor and Camille penetration.
        :param raw_damage: Outer-edge bonus damage before mitigation.
        :return: Damage dealt before runtime defensive reactions.
        """
        resistance = apply_resistance_pipeline(
            context.opponent_snapshot.armor,
            ResistanceModifiers(
                percent_penetration=context.snapshot.percent_armor_penetration,
                flat_penetration=context.snapshot.flat_armor_penetration,
            ),
        ).effective_resistance
        return apply_resistance(
            raw_damage,
            DamageType.PHYSICAL,
            armor=resistance,
            magic_resistance=context.opponent_snapshot.magic_resistance,
        ).post_mitigation_damage

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose the enemy-directed second Hookshot dash range.

        :param context: Role-bound snapshots for the Hookshot fixture.
        :return: Locked long-dash range in game units.
        """
        return Decimal(800)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Camille's fixed action policy.

        :param item: Normalized candidate from the locked item catalog.
        :return: Camille-scoped blocker, or ``None`` for represented stats.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"CAMILLE_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _attack_outputs(
        self,
        context: ParticipantContext,
        *,
        at_ms: int,
        physical_amount: Decimal,
        true_amount: Decimal = Decimal(0),
    ) -> tuple:
        """Build one attack's damage outputs including active R damage.

        :param context: Role-bound snapshots identifying both recipients.
        :param at_ms: Attack timestamp used to determine R zone activity.
        :param physical_amount: Raw physical portion of the attack.
        :param true_amount: Raw true-damage portion of empowered Q2.
        :return: Atomic outputs for the basic-attack event.
        """
        outputs = []
        if physical_amount:
            outputs.append(damage(context.opponent_entity, physical_amount, DamageType.PHYSICAL))
        if true_amount:
            outputs.append(damage(context.opponent_entity, true_amount, DamageType.TRUE))
        if 400 <= at_ms <= self._R2_END_MS:
            outputs.append(
                CurrentHealthDamageOutput(
                    context.opponent_entity,
                    self._R2_CURRENT_HP_RATIO,
                    DamageType.MAGIC,
                )
            )
        return tuple(outputs)

    def _basic_attack_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule post-Q attacks across E-buffed and normal cadence segments.

        :param context: Role-bound snapshots supplying attack damage and speed.
        :return: Chronological basic attacks with R on-hit damage when active.
        """
        boosted_speed = (
            context.snapshot.attack_speed + self._ATTACK_SPEED_RATIO * self._E5_ATTACK_SPEED_BONUS
        )
        boosted_interval = self._attack_interval_ms(boosted_speed)
        normal_interval = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = 2200 + boosted_interval
        while at_ms <= context.duration_ms:
            events.append(
                action(
                    f"CAMILLE_BASIC_ATTACK_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=self._attack_outputs(
                        context,
                        at_ms=at_ms,
                        physical_amount=context.snapshot.attack_damage,
                    ),
                )
            )
            interval = boosted_interval if at_ms < 5100 else normal_interval
            at_ms += interval
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked Q5/W1/E5/R2 level-13 duel sequence.

        :param context: Role-bound Camille and opponent combat snapshots.
        :return: Deterministic entry, control, attacks, sustain, and blockers.
        """
        base = self._sequence_base(context)
        total_ad = context.snapshot.attack_damage
        bonus_ad = context.snapshot.bonus_attack_damage
        e_damage = Decimal(180) + Decimal("0.75") * bonus_ad
        w_base = Decimal(60) + Decimal("0.60") * bonus_ad
        w_outer = (
            Decimal("0.07") + Decimal("0.00025") * bonus_ad
        ) * context.opponent_snapshot.max_hp
        q1_total = total_ad * (Decimal(1) + self._Q5_BONUS_RATIO)
        q2_total = total_ad * (Decimal(1) + self._Q5_BONUS_RATIO * self._Q2_AMPLIFIER)
        q2_true = q2_total * self._Q2_TRUE_CONVERSION_L13
        fixed_events = (
            action(
                "CAMILLE_E_HOOKSHOT_CHAMPION_HIT",
                at_ms=200,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.PHYSICAL),
                    crowd_control(context.opponent_entity, "STUN", duration_ms=750),
                    StatusOutput(context.self_entity, "CAMILLE_E_ATTACK_SPEED", 5000),
                ),
            ),
            action(
                "CAMILLE_R_HEXTECH_ULTIMATUM",
                at_ms=400,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(StatusOutput(context.opponent_entity, "CAMILLE_R_CONFINED", 3250),),
            ),
            action(
                "CAMILLE_Q1_PRECISION_PROTOCOL_ATTACK",
                at_ms=650,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=self._attack_outputs(context, at_ms=650, physical_amount=q1_total),
            ),
            action(
                "CAMILLE_W_TACTICAL_SWEEP_OUTER",
                at_ms=1050,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(
                        context.opponent_entity,
                        w_base + w_outer,
                        DamageType.PHYSICAL,
                    ),
                    healing(
                        context.self_entity,
                        self._post_mitigation_physical(context, w_outer),
                    ),
                    crowd_control(
                        context.opponent_entity,
                        "SLOW",
                        duration_ms=2000,
                        magnitude=Decimal("0.80"),
                    ),
                ),
            ),
            action(
                "CAMILLE_Q2_PRECISION_PROTOCOL_EMPOWERED",
                at_ms=2200,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.BASIC_ATTACK,
                outputs=self._attack_outputs(
                    context,
                    at_ms=2200,
                    physical_amount=q2_total - q2_true,
                    true_amount=q2_true,
                ),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"CAMILLE_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "camille_q5_w1_e5_r2_level13_locked_v1",
            tuple(
                sorted(
                    (*fixed_events, *self._basic_attack_events(context)),
                    key=lambda event: (event.at_ms, event.sequence),
                )
            ),
            (
                *level_blockers,
                "CAMILLE_ROTATION_TIMING_UNVERIFIED",
                "CAMILLE_Q2_LEVEL_CONVERSION_CURVE_UNVERIFIED",
                "CAMILLE_PASSIVE_ADAPTIVE_DAMAGE_TYPE_NOT_MODELED",
                "CAMILLE_E_TERRAIN_AND_COLLISION_NOT_MODELED",
                "CAMILLE_R_UNTARGETABILITY_AND_EVASION_NOT_MODELED",
                "CAMILLE_R_BOUNDARY_ESCAPE_RULES_NOT_MODELED",
                "CAMILLE_R_CHANNEL_INTERRUPT_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Hookshot's tenacity-reducible stun to the opponent.

        :param context: Role-bound Camille encounter context.
        :return: Causally linked stun window plus unresolved R reactions.
        """
        return ReactionPlan(
            "camille_e5_r2_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "camille_e_stun",
                    200,
                    min(950, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY),
                    "CAMILLE_E_HOOKSHOT_CHAMPION_HIT",
                    True,
                    ControlType.STUN,
                ),
            ),
            blockers=(
                "CAMILLE_E_HIT_AND_STUN_TIMING_UNVERIFIED",
                "CAMILLE_R_UNTARGETABILITY_REACTION_NOT_MODELED",
                "CAMILLE_R_CHANNEL_INTERRUPT_NOT_MODELED",
            ),
        )
