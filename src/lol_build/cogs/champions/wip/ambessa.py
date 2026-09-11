"""Ambessa combat Cog backed by the locked 16.17.1 champion sources."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

from lol_build.cogs.base import (
    DUEL_CAPABILITIES,
    ActionPlan,
    CastBlockWindow,
    ChampionCog,
    CogMaturity,
    ControlImmunityWindow,
    ControlType,
    ParticipantContext,
    ReactionPlan,
)
from lol_build.cogs.mechanics import action, crowd_control, damage, shielding
from lol_build.core.combat import (
    DamageType,
    ResistanceModifiers,
    apply_resistance,
    apply_resistance_pipeline,
)
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class AmbessaCog(ChampionCog):
    """Model Ambessa's Q5/W1/E5/R2 level-13 single-target sequence.

    The fixture opens with Public Execution, uses every basic ability once,
    consumes each Drakehound's Step charge with an empowered attack, and lets
    haste create additional Q and E casts inside the eight-second benchmark.
    Q assumes its outer/first-target variants, W assumes champion damage was
    blocked during its brace, and E assumes a directed passive dash triggers
    its second strike. Geometry and the energy ledger remain explicit blockers.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Ambessa.json",
        "data/raw/16.17.1/communitydragon/champions/799.json",
        "data/raw/16.17.1/communitydragon/champions/ambessa.bin.json",
    )

    _PASSIVE_ATTACK_SPEED_BONUS = Decimal("0.50")
    _PASSIVE_DASH_DISTANCE = Decimal(350)
    _R2_ABILITY_HEAL_RATIO = Decimal("0.175")

    @staticmethod
    def _haste_adjusted_ms(base_ms: int, ability_haste: Decimal) -> int:
        """Apply non-negative ability haste to a locked base cooldown.

        :param base_ms: Rank-specific cooldown in milliseconds.
        :param ability_haste: Haste supplied by the participant snapshot.
        :return: Deterministically rounded cooldown with a one-ms floor.
        """
        haste = max(Decimal(0), ability_haste)
        adjusted = Decimal(base_ms) * Decimal(100) / (Decimal(100) + haste)
        return max(1, int(adjusted.to_integral_value(rounding=ROUND_CEILING)))

    @staticmethod
    def _passive_on_hit(context: ParticipantContext) -> Decimal:
        """Evaluate Drakehound's Step's level-scaled empowered-hit damage.

        :param context: Ambessa snapshot supplying level and bonus attack damage.
        :return: Raw physical on-hit damage for one consumed passive charge.
        """
        level_fraction = Decimal(context.snapshot.level - 1) / Decimal(17)
        return (
            Decimal(5)
            + Decimal(25) * level_fraction
            + Decimal("0.25") * context.snapshot.bonus_attack_damage
        )

    @staticmethod
    def _q1_damage(context: ParticipantContext) -> Decimal:
        """Evaluate Q5's outer-edge damage against the duel target.

        :param context: Snapshots supplying Ambessa bonus AD and target maximum health.
        :return: Raw physical damage for Cunning Sweep's outer edge.
        """
        bonus_ad = context.snapshot.bonus_attack_damage
        max_health_ratio = Decimal("0.06") + Decimal("0.0003") * bonus_ad
        return (
            Decimal(120)
            + Decimal("0.60") * bonus_ad
            + (max_health_ratio * context.opponent_snapshot.max_hp)
        )

    @staticmethod
    def _q2_damage(context: ParticipantContext) -> Decimal:
        """Evaluate Q5's first-target Sundering Slam damage.

        :param context: Snapshots supplying Ambessa bonus AD and target maximum health.
        :return: Raw physical damage for the empowered Q recast.
        """
        bonus_ad = context.snapshot.bonus_attack_damage
        max_health_ratio = Decimal("0.06") + Decimal("0.0004") * bonus_ad
        return (
            Decimal(150)
            + Decimal("0.90") * bonus_ad
            + (max_health_ratio * context.opponent_snapshot.max_hp)
        )

    @staticmethod
    def _w_shield(context: ParticipantContext) -> Decimal:
        """Interpolate Repudiation's level shield and add its bonus-AD ratio.

        :param context: Ambessa snapshot supplying level and bonus attack damage.
        :return: Raw shield strength before generic item amplification.
        """
        level_fraction = Decimal(context.snapshot.level - 1) / Decimal(17)
        return (
            Decimal(50)
            + Decimal(270) * level_fraction
            + (Decimal("1.50") * context.snapshot.bonus_attack_damage)
        )

    @staticmethod
    def _post_mitigation_physical(
        context: ParticipantContext,
        raw_damage: Decimal,
    ) -> Decimal:
        """Resolve modeled physical damage for R2's ability healing.

        This follows the shared snapshot penetration path. Ambessa's additional
        R passive armor penetration is separately blocked until the shared
        timeline can consume champion-native penetration modifiers.

        :param context: Snapshots supplying target armor and item penetration.
        :param raw_damage: Ability damage before resistance mitigation.
        :return: Post-mitigation damage used by the healing output.
        """
        armor = apply_resistance_pipeline(
            context.opponent_snapshot.armor,
            ResistanceModifiers(
                percent_penetration=context.snapshot.percent_armor_penetration,
                flat_penetration=context.snapshot.flat_armor_penetration,
            ),
        ).effective_resistance
        return apply_resistance(
            raw_damage,
            DamageType.PHYSICAL,
            armor=armor,
            magic_resistance=context.opponent_snapshot.magic_resistance,
        ).post_mitigation_damage

    def _ability_outputs(
        self,
        context: ParticipantContext,
        raw_damage: Decimal,
        *,
        extra_outputs: tuple = (),
    ) -> tuple:
        """Create one physical spell hit and its R2 passive healing.

        :param context: Role-bound snapshots identifying recipients and defenses.
        :param raw_damage: Total physical spell damage produced by the event.
        :param extra_outputs: Shield, status, or control outputs resolved atomically.
        :return: Damage, healing, and caller-provided outputs for one ability hit.
        """
        return (
            damage(
                context.opponent_entity,
                raw_damage,
                DamageType.PHYSICAL,
                source_heal_ratio=self._R2_ABILITY_HEAL_RATIO,
            ),
            StatusOutput(
                context.self_entity,
                "AMBESSA_PASSIVE_DASH_DISTANCE",
                300,
                self._PASSIVE_DASH_DISTANCE,
            ),
            StatusOutput(
                context.self_entity,
                "AMBESSA_PASSIVE_ATTACK_SPEED",
                1000,
                self._PASSIVE_ATTACK_SPEED_BONUS,
            ),
            *extra_outputs,
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Public Execution's locked acquisition range.

        :param context: Role-bound encounter snapshots.
        :return: R's target-search range in game units.
        """
        return Decimal(1250)

    def engagement_speed_multiplier(self, context: ParticipantContext) -> Decimal:
        """Avoid inventing movement speed absent from Ambessa's locked kit.

        :param context: Role-bound encounter snapshots.
        :return: Neutral movement-speed multiplier.
        """
        return Decimal(1)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels not consumed by Ambessa's fixed model.

        AD, attack speed, haste, health, defenses, penetration, movement, and
        tenacity reach a modeled formula or shared system. AP, crit, external
        sustain, and mana channels do not.

        :param item: Normalized candidate from the locked item catalog.
        :return: Ambessa-scoped blocker, or ``None`` for represented stats.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "AP",
            "CRITICAL_STRIKE_CHANCE",
            "MANA",
            "MANA_REGEN",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"AMBESSA_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _empowered_attack(
        self,
        context: ParticipantContext,
        *,
        event_id: str,
        at_ms: int,
        sequence: int,
    ) -> ActionEvent:
        """Consume one deterministic passive charge with an empowered attack.

        :param context: Role-bound snapshot supplying total and bonus AD.
        :param event_id: Stable identifier naming the enabling spell.
        :param at_ms: Timestamp after that spell's modeled dash.
        :param sequence: Collision-free timeline order key.
        :return: Blind-susceptible physical basic-attack event.
        """
        return action(
            event_id,
            at_ms=at_ms,
            sequence=sequence,
            source=context.self_entity,
            channel=ActionChannel.BASIC_ATTACK,
            outputs=(
                damage(
                    context.opponent_entity,
                    context.snapshot.attack_damage,
                    DamageType.PHYSICAL,
                ),
                damage(
                    context.opponent_entity,
                    self._passive_on_hit(context),
                    DamageType.PHYSICAL,
                ),
            ),
        )

    def _ordinary_attacks(
        self,
        context: ParticipantContext,
        *,
        occupied_times: frozenset[int],
    ) -> tuple[ActionEvent, ...]:
        """Schedule ordinary attacks after the opening empowered sequence.

        :param context: Snapshot supplying total AD and attack speed.
        :param occupied_times: Empowered-attack timestamps excluded from this stream.
        :return: Remaining blind-susceptible basic attacks through the duel.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        base = self._sequence_base(context) + 500
        events: list[ActionEvent] = []
        at_ms = 4600
        while at_ms <= context.duration_ms:
            if at_ms not in occupied_times:
                events.append(
                    action(
                        f"AMBESSA_BASIC_ATTACK_{len(events) + 1}",
                        at_ms=at_ms,
                        sequence=base + len(events),
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
            at_ms += interval_ms
        return tuple(events)

    def _repeat_events(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule haste-enabled second Q and E cycles inside the benchmark.

        :param context: Snapshot supplying ability haste and damage inputs.
        :return: Repeat spell events and their passive-charge attacks.
        """
        base = self._sequence_base(context) + 300
        events: list[ActionEvent] = []
        q1_ms = 1600 + self._haste_adjusted_ms(10_000, context.snapshot.ability_haste)
        if q1_ms <= context.duration_ms:
            q2_ms = q1_ms + 600
            events.append(
                action(
                    "AMBESSA_Q1_CUNNING_SWEEP_2",
                    at_ms=q1_ms,
                    sequence=base,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=self._ability_outputs(context, self._q1_damage(context)),
                )
            )
            attack_ms = q1_ms + 400
            if attack_ms <= context.duration_ms:
                events.append(
                    self._empowered_attack(
                        context,
                        event_id="AMBESSA_PASSIVE_ATTACK_AFTER_Q1_2",
                        at_ms=attack_ms,
                        sequence=base + 1,
                    )
                )
            if q2_ms <= context.duration_ms:
                events.append(
                    action(
                        "AMBESSA_Q2_SUNDERING_SLAM_2",
                        at_ms=q2_ms,
                        sequence=base + 2,
                        source=context.self_entity,
                        channel=ActionChannel.ABILITY,
                        outputs=self._ability_outputs(context, self._q2_damage(context)),
                    )
                )
                if q2_ms + 400 <= context.duration_ms:
                    events.append(
                        self._empowered_attack(
                            context,
                            event_id="AMBESSA_PASSIVE_ATTACK_AFTER_Q2_2",
                            at_ms=q2_ms + 400,
                            sequence=base + 3,
                        )
                    )

        e_ms = 3000 + self._haste_adjusted_ms(9000, context.snapshot.ability_haste)
        if e_ms <= context.duration_ms:
            e_single = Decimal(120) + Decimal("0.50") * context.snapshot.bonus_attack_damage
            events.append(
                action(
                    "AMBESSA_E_LACERATE_DOUBLE_2",
                    at_ms=e_ms,
                    sequence=base + 10,
                    source=context.self_entity,
                    channel=ActionChannel.ABILITY,
                    outputs=self._ability_outputs(
                        context,
                        Decimal(2) * e_single,
                        extra_outputs=(
                            crowd_control(
                                context.opponent_entity,
                                "SLOW",
                                duration_ms=1000,
                                magnitude=Decimal("0.99"),
                            ),
                        ),
                    ),
                )
            )
            if e_ms + 400 <= context.duration_ms:
                events.append(
                    self._empowered_attack(
                        context,
                        event_id="AMBESSA_PASSIVE_ATTACK_AFTER_E_2",
                        at_ms=e_ms + 400,
                        sequence=base + 11,
                    )
                )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build Ambessa's locked Q5/W1/E5/R2 level-13 duel sequence.

        :param context: Role-bound Ambessa and opponent snapshots.
        :return: Entry, spell, shield, control, empowered-hit, and sustain events.
        """
        base = self._sequence_base(context)
        bonus_ad = context.snapshot.bonus_attack_damage
        r_damage = Decimal(250) + Decimal("0.80") * bonus_ad
        w_low_damage = Decimal(50) + Decimal("0.50") * bonus_ad
        w_high_damage = Decimal("1.50") * w_low_damage
        e_single_damage = Decimal(120) + Decimal("0.50") * bonus_ad
        fixed_events = (
            action(
                "AMBESSA_R_PUBLIC_EXECUTION_CAST",
                at_ms=200,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    crowd_control(context.opponent_entity, "SUPPRESSION", duration_ms=750),
                    StatusOutput(context.self_entity, "AMBESSA_R_UNSTOPPABLE", 750),
                ),
            ),
            action(
                "AMBESSA_R_PUBLIC_EXECUTION_IMPACT",
                at_ms=950,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=self._ability_outputs(
                    context,
                    r_damage,
                    extra_outputs=(
                        crowd_control(context.opponent_entity, "STUN", duration_ms=400),
                    ),
                ),
            ),
            self._empowered_attack(
                context,
                event_id="AMBESSA_PASSIVE_ATTACK_AFTER_R",
                at_ms=1400,
                sequence=base + 2,
            ),
            action(
                "AMBESSA_Q1_CUNNING_SWEEP_1",
                at_ms=1600,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=self._ability_outputs(context, self._q1_damage(context)),
            ),
            self._empowered_attack(
                context,
                event_id="AMBESSA_PASSIVE_ATTACK_AFTER_Q1_1",
                at_ms=2000,
                sequence=base + 4,
            ),
            action(
                "AMBESSA_Q2_SUNDERING_SLAM_1",
                at_ms=2200,
                sequence=base + 5,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=self._ability_outputs(context, self._q2_damage(context)),
            ),
            self._empowered_attack(
                context,
                event_id="AMBESSA_PASSIVE_ATTACK_AFTER_Q2_1",
                at_ms=2600,
                sequence=base + 6,
            ),
            action(
                "AMBESSA_E_LACERATE_DOUBLE_1",
                at_ms=3000,
                sequence=base + 7,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=self._ability_outputs(
                    context,
                    Decimal(2) * e_single_damage,
                    extra_outputs=(
                        crowd_control(
                            context.opponent_entity,
                            "SLOW",
                            duration_ms=1000,
                            magnitude=Decimal("0.99"),
                        ),
                    ),
                ),
            ),
            self._empowered_attack(
                context,
                event_id="AMBESSA_PASSIVE_ATTACK_AFTER_E_1",
                at_ms=3400,
                sequence=base + 8,
            ),
            action(
                "AMBESSA_W_REPUDIATION_BRACED",
                at_ms=3800,
                sequence=base + 9,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=self._ability_outputs(
                    context,
                    w_high_damage,
                    extra_outputs=(
                        shielding(
                            context.self_entity,
                            self._w_shield(context),
                            duration_ms=1500,
                        ),
                    ),
                ),
            ),
            self._empowered_attack(
                context,
                event_id="AMBESSA_PASSIVE_ATTACK_AFTER_W",
                at_ms=4200,
                sequence=base + 10,
            ),
        )
        repeats = self._repeat_events(context)
        occupied = frozenset(
            event.at_ms
            for event in (*fixed_events, *repeats)
            if event.channel is ActionChannel.BASIC_ATTACK
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"AMBESSA_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        events = (
            *fixed_events,
            *repeats,
            *self._ordinary_attacks(context, occupied_times=occupied),
        )
        return ActionPlan(
            "ambessa_q5_w1_e5_r2_level13_locked_v1",
            tuple(sorted(events, key=lambda event: (event.at_ms, event.sequence))),
            (
                *level_blockers,
                "AMBESSA_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "AMBESSA_ROTATION_TIMING_UNVERIFIED",
                "AMBESSA_ENERGY_LEDGER_NOT_MODELED",
                "AMBESSA_PASSIVE_DASH_DIRECTION_AND_TERRAIN_NOT_MODELED",
                "AMBESSA_PASSIVE_DASH_DISTANCE_350_LOCKED_BUT_NOT_ACCUMULATED",
                "AMBESSA_Q_OUTER_EDGE_AND_FIRST_TARGET_ASSUMED",
                "AMBESSA_W_CHAMPION_DAMAGE_BLOCKED_ASSUMED",
                "AMBESSA_E_DASH_SECOND_STRIKE_ASSUMED",
                "AMBESSA_R_TARGET_SELECTION_AND_GEOMETRY_NOT_MODELED",
                "AMBESSA_R2_NATIVE_ARMOR_PENETRATION_NOT_APPLIED_BY_TIMELINE",
                "AMBESSA_MULTITARGET_OUTPUT_NOT_MODELED",
                "AMBESSA_COOLDOWN_AND_ATTACK_INTERLEAVING_ASSUMED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose R suppression, impact stun, unstoppable, and E slow.

        :param context: Role-bound snapshots for the Ambessa participant.
        :return: Source-linked control and immunity windows.
        """
        return ReactionPlan(
            "ambessa_r2_e5_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "ambessa_r_suppression",
                    200,
                    min(950, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                        ActionChannel.ITEM_ACTIVE,
                    ),
                    "AMBESSA_R_PUBLIC_EXECUTION_CAST",
                    False,
                    ControlType.SUPPRESSION,
                ),
                CastBlockWindow(
                    "ambessa_r_impact_stun",
                    950,
                    min(1350, context.duration_ms),
                    (
                        ActionChannel.BASIC_ATTACK,
                        ActionChannel.ABILITY,
                        ActionChannel.MOVEMENT,
                        ActionChannel.ITEM_ACTIVE,
                    ),
                    "AMBESSA_R_PUBLIC_EXECUTION_IMPACT",
                    True,
                    ControlType.STUN,
                ),
                CastBlockWindow(
                    "ambessa_e_slow",
                    3000,
                    min(4000, context.duration_ms),
                    (ActionChannel.MOVEMENT,),
                    "AMBESSA_E_LACERATE_DOUBLE_1",
                    True,
                    ControlType.SLOW,
                ),
            ),
            control_immunity_windows=(
                ControlImmunityWindow(
                    "ambessa_r_unstoppable",
                    200,
                    min(950, context.duration_ms),
                    context.self_entity,
                    (ControlType.ALL,),
                    "AMBESSA_R_PUBLIC_EXECUTION_CAST",
                ),
            ),
            blockers=(
                "AMBESSA_R_BLINK_AND_UNSTOPPABLE_TIMING_UNVERIFIED",
                "AMBESSA_E_DECAYING_SLOW_APPROXIMATED_AS_CONSTANT",
                "AMBESSA_REPEAT_E_REACTION_WINDOW_NOT_MODELED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Decline to turn combat-only R healing into free lane recovery.

        :param context: Role-bound Ambessa lane snapshot.
        :param duration_ms: Lane observation duration in milliseconds.
        :param no_damage_delay_ms: Required no-damage delay before recovery.
        :return: Zero native lane recovery and a combat-target dependency blocker.
        """
        return Decimal(0), ("AMBESSA_R_SUSTAIN_REQUIRES_ABILITY_DAMAGE_TARGET",)
