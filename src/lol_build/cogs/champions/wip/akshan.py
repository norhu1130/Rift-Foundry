"""Akshan combat Cog backed by the locked 16.17.1 champion sources."""

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
from lol_build.cogs.mechanics import action, damage, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent


class AkshanCog(ChampionCog):
    """Model Akshan's Q5/W1/E5/R2 level-13 single-target fixture."""

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Akshan.json",
        "data/raw/16.17.1/communitydragon/champions/166.json",
        "data/raw/16.17.1/communitydragon/champions/akshan.bin.json",
    )

    _CRITICAL_DAMAGE_MULTIPLIER = Decimal(2)
    _E_START_MS = 2000
    _E_END_MS = 3000
    _R_START_MS = 5000

    @classmethod
    def _expected_critical_multiplier(
        cls,
        context: ParticipantContext,
        effectiveness: Decimal = Decimal(1),
    ) -> Decimal:
        """Return a deterministic expected-value critical damage multiplier.

        :param context: Akshan context containing critical-strike chance.
        :param effectiveness: Fraction of normal critical bonus used by an effect.
        :return: Expected multiplier for the locked 2.0 critical damage value.
        """
        return Decimal(1) + (
            context.snapshot.critical_strike_chance
            * effectiveness
            * (cls._CRITICAL_DAMAGE_MULTIPLIER - Decimal(1))
        )

    @staticmethod
    def _passive_damage(context: ParticipantContext) -> Decimal:
        """Calculate Dirty Fighting's level-13 three-hit magic damage.

        :param context: Akshan context containing ability power.
        :return: Locked breakpoint damage plus its AP scaling.
        """
        return Decimal(80) + Decimal("0.60") * context.snapshot.ability_power

    def _passive_shield(self, context: ParticipantContext) -> Decimal:
        """Calculate Dirty Fighting's level-scaled champion shield.

        The BIN calculation scales 40 to 280 with Riot's champion-stat
        progression multiplier and adds 35 percent bonus attack damage.

        :param context: Akshan context containing level and bonus attack damage.
        :return: Shield amount emitted on the first passive proc.
        """
        progression = self.growth_multiplier(context.snapshot.level) / Decimal(17)
        base_shield = Decimal(40) + Decimal(240) * progression
        return base_shield + Decimal("0.35") * context.snapshot.bonus_attack_damage

    def _bonus_attack_speed(self, context: ParticipantContext) -> Decimal:
        """Recover item-sourced bonus attack speed from the combat snapshot.

        :param context: Akshan context after item aggregation.
        :return: Non-negative bonus attack-speed ratio consumed by Heroic Swing.
        """
        baseline = self.snapshot(level=context.snapshot.level).attack_speed
        detail = self.detail_root or {}
        raw_ratio = detail.get("attackSpeedRatioModifiable")
        if isinstance(raw_ratio, dict) and "baseValue" in raw_ratio:
            ratio = Decimal(str(raw_ratio["baseValue"]))
        else:
            ratio = Decimal(str(self.document["stats"]["attackspeed"]))
        if ratio <= 0:
            return Decimal(0)
        return max(Decimal(0), (context.snapshot.attack_speed - baseline) / ratio)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Expose Avengerang's champion-hit movement burst for approach scoring.

        :param context: Role-bound Akshan combat context.
        :return: Q movement speed divided by the standing movement speed.
        """
        q_haste = Decimal("0.20") + Decimal("0.0005") * context.snapshot.ability_power
        return Decimal(1) + q_haste

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Avoid inventing a terrain-independent Heroic Swing distance.

        :param context: Role-bound Akshan combat context.
        :return: Zero because the benchmark contains no grapple geometry.
        """
        return Decimal(0)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from Akshan's deterministic fixture.

        Damage stats, attack cadence, defenses, penetration, and movement feed
        represented paths. Resource spending, haste rescheduling, and item-based
        sustain or shield amplification are not yet causally modeled.

        :param item: Normalized candidate item from the locked catalog.
        :return: Akshan-specific blocker or ``None`` for represented channels.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "MANA_REGEN",
            "OMNIVAMP",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"AKSHAN_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _raw_hit_shapes(self, context: ParticipantContext) -> list[tuple[int, str]]:
        """Construct the fixed rotation's passive-eligible hit schedule.

        :param context: Role-bound snapshots used for attack cadence.
        :return: Timestamp and hit-kind pairs before damage-event construction.
        """
        shapes: list[tuple[int, str]] = [(200, "Q_OUT"), (600, "Q_RETURN")]
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        attack_ms = 900
        while attack_ms < min(context.duration_ms + 1, self._R_START_MS):
            if not self._E_START_MS <= attack_ms <= self._E_END_MS:
                shapes.append((attack_ms, "ATTACK"))
                second_ms = attack_ms + 100
                if second_ms <= context.duration_ms and not (
                    self._E_START_MS <= second_ms <= self._E_END_MS
                ):
                    shapes.append((second_ms, "SECOND_ATTACK"))
            attack_ms += interval_ms
        for index in range(5):
            at_ms = self._E_START_MS + index * 200
            if at_ms <= context.duration_ms:
                shapes.append((at_ms, "E_SHOT"))
        return sorted(shapes, key=lambda shape: (shape[0], shape[1]))

    def _eligible_hit_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Create Q, attack, E, and three-hit passive events.

        Each eligible hit advances one deterministic target-local passive stack.
        The first proc also emits the level-13 shield; its locked eight-second
        cooldown prevents another shield inside this fixture.

        :param context: Role-bound snapshots for damage and shield formulas.
        :return: Ordered events before Comeuppance is appended.
        """
        q_damage = Decimal(165) + Decimal("0.70") * context.snapshot.bonus_attack_damage
        attack_damage = context.snapshot.attack_damage * self._expected_critical_multiplier(
            context
        )
        second_attack_damage = Decimal("0.50") * attack_damage
        e_damage = (
            Decimal(40) + Decimal("0.25") * context.snapshot.bonus_attack_damage
        ) * (Decimal(1) + Decimal("0.30") * self._bonus_attack_speed(context))
        e_damage *= self._expected_critical_multiplier(context, Decimal("0.50"))

        base = self._sequence_base(context)
        events: list[ActionEvent] = []
        stack_count = 0
        shield_emitted = False
        for hit_number, (at_ms, hit_kind) in enumerate(
            self._raw_hit_shapes(context), start=1
        ):
            if at_ms > context.duration_ms:
                continue
            amount = {
                "Q_OUT": q_damage,
                "Q_RETURN": q_damage,
                "ATTACK": attack_damage,
                "SECOND_ATTACK": second_attack_damage,
                "E_SHOT": e_damage,
            }[hit_kind]
            outputs = [damage(context.opponent_entity, amount, DamageType.PHYSICAL)]
            stack_count += 1
            if stack_count == 3:
                outputs.append(
                    damage(
                        context.opponent_entity,
                        self._passive_damage(context),
                        DamageType.MAGIC,
                    )
                )
                if not shield_emitted:
                    outputs.append(
                        shielding(
                            context.self_entity,
                            self._passive_shield(context),
                            duration_ms=2000,
                        )
                    )
                    shield_emitted = True
                stack_count = 0
            channel = (
                ActionChannel.BASIC_ATTACK
                if hit_kind in {"ATTACK", "SECOND_ATTACK"}
                else ActionChannel.ABILITY
            )
            events.append(
                action(
                    f"AKSHAN_{hit_kind}_{hit_number}",
                    at_ms=at_ms,
                    sequence=base + 100 + hit_number,
                    source=context.self_entity,
                    channel=channel,
                    outputs=tuple(outputs),
                )
            )
        return tuple(events)

    def _ultimate_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Emit R2's six minimum-damage bullets after the fixed channel.

        :param context: Role-bound snapshots for R damage scaling.
        :return: Up to six physical-damage bullet events within the horizon.
        """
        bullet_damage = (
            Decimal(35) + Decimal("0.15") * context.snapshot.bonus_attack_damage
        ) * self._expected_critical_multiplier(context, Decimal("0.30"))
        base = self._sequence_base(context)
        events: list[ActionEvent] = []
        for index in range(6):
            at_ms = 7500 + index * 100
            if at_ms > context.duration_ms:
                break
            events.append(
                action(
                    f"AKSHAN_R_COMEUPPANCE_BULLET_{index + 1}",
                    at_ms=at_ms,
                    sequence=base + 500 + index,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=(damage(context.opponent_entity, bullet_damage, DamageType.PHYSICAL),),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Akshan's fixed level-13 single-target combat rotation.

        Q is assumed to hit on both legs. E contributes five shots from a
        reproducible one-second swing window. R contributes its six rank-two
        bullets at minimum missing-health amplification after a full channel.

        :param context: Role-bound snapshots for Akshan and his opponent.
        :return: Deterministic damage, passive proc, and shield schedule.
        """
        events = (*self._eligible_hit_events(context), *self._ultimate_events(context))
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"AKSHAN_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "akshan_q5_w1_e5_r2_level13_locked_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence, event.id))),
            (
                *level_blockers,
                "AKSHAN_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "AKSHAN_Q_OUTBOUND_AND_RETURN_HITS_ASSUMED",
                "AKSHAN_PASSIVE_TARGET_MARK_EXPIRY_AND_SWITCHING_NOT_MODELED",
                "AKSHAN_PASSIVE_SECOND_ATTACK_CANCEL_CHOICE_NOT_MODELED",
                "AKSHAN_PASSIVE_CANCELLED_HIT_STACK_RECOMPUTATION_NOT_MODELED",
                "AKSHAN_E_GRAPPLE_TERRAIN_AND_COLLISION_NOT_MODELED",
                "AKSHAN_E_SINGLE_TARGET_FIVE_SHOT_WINDOW_ASSUMED",
                "AKSHAN_E_ON_HIT_EFFECTS_NOT_MODELED",
                "AKSHAN_W_SCOUNDREL_MARK_GOLD_AND_REVIVAL_OUT_OF_MODEL",
                "AKSHAN_W_CAMOUFLAGE_TARGETING_NOT_MODELED",
                "AKSHAN_R_TARGET_MISSING_HEALTH_SCALING_NOT_MODELED",
                "AKSHAN_R_PROJECTILE_BLOCKERS_AND_CHANNEL_INTERRUPTION_NOT_MODELED",
                "AKSHAN_R_PASSIVE_MARK_INTERACTION_UNVERIFIED",
                "AKSHAN_RESOURCE_COSTS_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Keep unresolved camouflage, grapple, and channel reactions explicit.

        :param context: Role-bound Akshan combat context.
        :return: Neutral reaction plan with geometry and targeting blockers.
        """
        return ReactionPlan(
            "akshan_geometry_camouflage_channel_unresolved_v1",
            blockers=(
                "AKSHAN_W_CAMOUFLAGE_TARGETING_NOT_MODELED",
                "AKSHAN_E_GRAPPLE_TERRAIN_AND_COLLISION_NOT_MODELED",
                "AKSHAN_R_PROJECTILE_BLOCKERS_AND_CHANNEL_INTERRUPTION_NOT_MODELED",
            ),
        )
