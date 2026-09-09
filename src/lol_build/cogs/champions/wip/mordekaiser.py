"""Mordekaiser combat Cog for the locked level-13 duel benchmark."""

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
from lol_build.cogs.mechanics import action, crowd_control, damage, healing, shielding
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, ActionEvent, StatusOutput


class MordekaiserCog(ChampionCog):
    """Model Mordekaiser's Q5/W1/E5/R2 level-13 duel sequence.

    The fixed policy resolves Realm of Death before Mordekaiser's damaging
    rotation. The model can therefore precompute the offensive AP and attack
    damage gained from the locked ten-percent stat steal. The shared timeline
    cannot change maximum health, defenses, or isolation state dynamically, so
    those parts of the ultimate remain explicit blockers instead of estimates.

    Indestructible uses its locked five-percent minimum shield and rank-one
    heal conversion. Damage-driven shield-resource accumulation is deliberately
    excluded because the current event contract cannot consume a live resource.
    """

    maturity = CogMaturity.MODELED_UNVERIFIED
    capabilities = DUEL_CAPABILITIES
    evidence_refs = (
        "data/raw/16.17.1/en_US/champion/Mordekaiser.json",
        "data/raw/16.17.1/communitydragon/champions/82.json",
        "data/raw/16.17.1/communitydragon/champions/mordekaiser.bin.json",
    )

    _REALM_START_MS = 600
    _REALM_END_MS = 7600
    _PASSIVE_START_MS = 1500

    @staticmethod
    def _level_percent_health_ratio(level: int) -> Decimal:
        """Interpolate Darkness Rise's one-to-five-percent health ratio.

        CommunityDragon stores a linear level-one through level-eighteen curve.

        :param level: Champion level selecting the interpolation point.
        :return: Target maximum-health ratio dealt by one second of aura contact.
        """
        bounded_level = min(18, max(1, level))
        return Decimal("0.01") + (
            Decimal("0.04") * Decimal(bounded_level - 1) / Decimal(17)
        )

    @staticmethod
    def _q_level_bonus(level: int) -> Decimal:
        """Evaluate the locked post-level-ten Q breakpoint conservatively.

        :param level: Champion level used by the BIN breakpoint calculation.
        :return: Flat Q damage added at and after level ten.
        """
        return Decimal(max(0, level - 9) * 5)

    @staticmethod
    def _realm_stats(
        context: ParticipantContext,
    ) -> tuple[Decimal, Decimal]:
        """Return offensive stats during the modeled Realm of Death window.

        :param context: Role-bound snapshots for Mordekaiser and his target.
        :return: Effective total attack damage and ability power during the realm.
        """
        return (
            context.snapshot.attack_damage
            + Decimal("0.10") * context.opponent_snapshot.attack_damage,
            context.snapshot.ability_power
            + Decimal("0.10") * context.opponent_snapshot.ability_power,
        )

    def engagement_dash_distance(self, context: ParticipantContext) -> Decimal:
        """Expose Death's Grasp pull distance as closing displacement.

        :param context: Role-bound combat snapshots for the encounter.
        :return: Locked maximum pull distance in game units.
        """
        return Decimal(250)

    def item_candidate_blocker(self, item: dict[str, object]) -> str | None:
        """Reject item channels absent from the fixed Mordekaiser policy.

        Health, defenses, AP, AD, attack speed, penetration, movement, and
        tenacity reach the shared snapshot or modeled formulas. The fixed cast
        schedule cannot value haste, while resource and healing attribution
        require contracts that this Cog does not claim.

        :param item: Normalized item candidate from the locked catalog.
        :return: Champion-scoped blocker for unsupported stats, otherwise ``None``.
        """
        stats = item["stats"]
        assert isinstance(stats, dict)
        unsupported = {
            "ABILITY_HASTE",
            "CRITICAL_STRIKE_CHANCE",
            "HEAL_SHIELD_POWER",
            "LIFESTEAL",
            "MANA",
            "OMNIVAMP",
        } & stats.keys()
        if unsupported:
            names = ",".join(sorted(unsupported))
            return f"MORDEKAISER_ITEM_STAT_NOT_MODELED:{item['id']}:{names}"
        return None

    def _basic_attacks(self, context: ParticipantContext) -> tuple[ActionEvent, ...]:
        """Schedule attacks with Darkness Rise's locked AP on-hit damage.

        Attacks inside the seven-second realm use the precomputed ten-percent
        offensive stat steal; later attacks revert to Mordekaiser's base snapshot.

        :param context: Role-bound snapshots supplying cadence and damage stats.
        :return: Deterministic physical and magic attack events through the duel.
        """
        interval_ms = self._attack_interval_ms(context.snapshot.attack_speed)
        realm_ad, realm_ap = self._realm_stats(context)
        base = self._sequence_base(context) + 100
        events: list[ActionEvent] = []
        at_ms = self._PASSIVE_START_MS
        while at_ms <= context.duration_ms:
            in_realm = self._REALM_START_MS <= at_ms < self._REALM_END_MS
            attack_damage = realm_ad if in_realm else context.snapshot.attack_damage
            ability_power = realm_ap if in_realm else context.snapshot.ability_power
            events.append(
                action(
                    f"MORDEKAISER_BASIC_ATTACK_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.BASIC_ATTACK,
                    outputs=(
                        damage(
                            context.opponent_entity,
                            attack_damage,
                            DamageType.PHYSICAL,
                        ),
                        damage(
                            context.opponent_entity,
                            Decimal("0.40") * ability_power,
                            DamageType.MAGIC,
                        ),
                    ),
                )
            )
            at_ms += interval_ms
        return tuple(events)

    def _passive_aura_events(
        self, context: ParticipantContext
    ) -> tuple[ActionEvent, ...]:
        """Emit one-second Darkness Rise aura samples after the third stack.

        The fixed E, Q, attack opener supplies three stacks at 1500 ms. Aura
        samples begin one second later and remain on the passive channel so blind
        cannot incorrectly cancel an already active damage aura.

        :param context: Role-bound snapshots supplying AP and target maximum health.
        :return: Deterministic one-second aura damage events.
        """
        realm_ap = self._realm_stats(context)[1]
        target_ratio = self._level_percent_health_ratio(context.snapshot.level)
        base = self._sequence_base(context) + 300
        events: list[ActionEvent] = []
        for at_ms in range(
            self._PASSIVE_START_MS + 1000,
            context.duration_ms + 1,
            1000,
        ):
            ability_power = (
                realm_ap
                if self._REALM_START_MS <= at_ms < self._REALM_END_MS
                else context.snapshot.ability_power
            )
            amount = (
                Decimal(5)
                + Decimal("0.30") * ability_power
                + target_ratio * context.opponent_snapshot.max_hp
            )
            events.append(
                action(
                    f"MORDEKAISER_PASSIVE_AURA_TICK_{len(events) + 1}",
                    at_ms=at_ms,
                    sequence=base + len(events),
                    source=context.self_entity,
                    channel=ActionChannel.PASSIVE,
                    outputs=(
                        damage(context.opponent_entity, amount, DamageType.MAGIC),
                    ),
                )
            )
        return tuple(events)

    def build_action_plan(self, context: ParticipantContext) -> ActionPlan:
        """Build the locked P/Q5/W1/E5/R2 level-13 duel policy.

        Q assumes the isolated target produced by the synthetic realm policy.
        W activates only its guaranteed minimum shield and then converts that
        undamaged fixture into healing; dynamic resource gain is not fabricated.

        :param context: Role-bound Mordekaiser and opponent combat snapshots.
        :return: Damage, sustain, control, and realm events with audit blockers.
        """
        base = self._sequence_base(context)
        realm_ad, realm_ap = self._realm_stats(context)
        q_damage = Decimal("1.50") * (
            Decimal(220)
            + self._q_level_bonus(context.snapshot.level)
            + Decimal("1.20") * realm_ad
            + Decimal("0.70") * realm_ap
        )
        e_damage = Decimal(140) + Decimal("0.45") * realm_ap
        minimum_shield = Decimal("0.05") * context.snapshot.max_hp
        minimum_shield_heal = Decimal("0.35") * minimum_shield
        fixed_events = (
            action(
                "MORDEKAISER_R_REALM_OF_DEATH",
                at_ms=self._REALM_START_MS,
                sequence=base,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    StatusOutput(
                        context.opponent_entity,
                        "MORDEKAISER_DEATH_REALM",
                        7000,
                    ),
                ),
            ),
            action(
                "MORDEKAISER_E_DEATHS_GRASP",
                at_ms=850,
                sequence=base + 1,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    damage(context.opponent_entity, e_damage, DamageType.MAGIC),
                    crowd_control(
                        context.opponent_entity,
                        "AIRBORNE",
                        duration_ms=250,
                    ),
                ),
            ),
            action(
                "MORDEKAISER_Q_OBLITERATE_1",
                at_ms=1100,
                sequence=base + 2,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.MAGIC),),
            ),
            action(
                "MORDEKAISER_W_INDESTRUCTIBLE_SHIELD",
                at_ms=2000,
                sequence=base + 3,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(
                    shielding(
                        context.self_entity,
                        minimum_shield,
                        duration_ms=800,
                    ),
                ),
                requires_living_opponent=False,
            ),
            action(
                "MORDEKAISER_W_INDESTRUCTIBLE_HEAL",
                at_ms=2800,
                sequence=base + 4,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(healing(context.self_entity, minimum_shield_heal),),
                requires_living_opponent=False,
            ),
            action(
                "MORDEKAISER_Q_OBLITERATE_2",
                at_ms=5100,
                sequence=base + 5,
                source=context.self_entity,
                channel=ActionChannel.ABILITY,
                outputs=(damage(context.opponent_entity, q_damage, DamageType.MAGIC),),
            ),
        )
        level_blockers = (
            ()
            if context.snapshot.level == 13
            else (f"MORDEKAISER_MODEL_LEVEL_UNSUPPORTED:{context.snapshot.level}",)
        )
        return ActionPlan(
            "mordekaiser_p_q5_w1_e5_r2_level13_synthetic_v1",
            tuple(
                sorted(
                    (
                        *fixed_events,
                        *self._basic_attacks(context),
                        *self._passive_aura_events(context),
                    ),
                    key=lambda event: (event.at_ms, event.sequence),
                )
            ),
            (
                *level_blockers,
                "MORDEKAISER_LEVEL13_Q5_W1_E5_R2_POLICY_UNVERIFIED",
                "MORDEKAISER_CAST_AND_HIT_TIMING_UNVERIFIED",
                "MORDEKAISER_Q_LEVEL_BREAKPOINT_INTERPRETATION_UNVERIFIED",
                "MORDEKAISER_Q_ISOLATED_TARGET_ASSUMED",
                "MORDEKAISER_PASSIVE_AURA_TICK_PHASE_UNVERIFIED",
                "MORDEKAISER_PASSIVE_ACTIVATION_DEPENDENCY_NOT_EVALUATED",
                "MORDEKAISER_PASSIVE_PROXIMITY_CONTINUITY_ASSUMED",
                "MORDEKAISER_W_DYNAMIC_SHIELD_RESOURCE_NOT_MODELED",
                "MORDEKAISER_W_MINIMUM_SHIELD_UNDAMAGED_BEFORE_RECAST_ASSUMED",
                "MORDEKAISER_E_PULL_DURATION_UNVERIFIED",
                "MORDEKAISER_E_COOLDOWN_SOURCE_CONFLICT",
                "MORDEKAISER_E_PASSIVE_MAGIC_PENETRATION_NOT_APPLIED_TO_SNAPSHOT",
                "MORDEKAISER_R_ISOLATION_AND_MULTI_TARGET_STATE_NOT_MODELED",
                "MORDEKAISER_R_DYNAMIC_STAT_STEAL_DEFENSES_AND_HEALTH_NOT_MODELED",
                "MORDEKAISER_R_KILL_RETENTION_NOT_MODELED",
            ),
        )

    def build_reaction_plan(self, context: ParticipantContext) -> ReactionPlan:
        """Expose Death's Grasp displacement as a causal action block.

        E's passive magic penetration cannot be installed into the immutable
        snapshot from a reaction plan, so its omission remains a plan blocker.

        :param context: Role-bound snapshots identifying the displaced opponent.
        :return: Non-tenacity-reducible pull window linked to the E hit event.
        """
        return ReactionPlan(
            "mordekaiser_e_pull_reaction_v1",
            cast_block_windows=(
                CastBlockWindow(
                    "mordekaiser_e_pull",
                    850,
                    min(1100, context.duration_ms),
                    (ActionChannel.BASIC_ATTACK, ActionChannel.ABILITY),
                    "MORDEKAISER_E_DEATHS_GRASP",
                    False,
                    ControlType.AIRBORNE,
                ),
            ),
            blockers=(
                "MORDEKAISER_E_PULL_DURATION_UNVERIFIED",
                "MORDEKAISER_E_PASSIVE_MAGIC_PENETRATION_NOT_APPLIED_TO_SNAPSHOT",
                "MORDEKAISER_R_ISOLATION_AND_MULTI_TARGET_STATE_NOT_MODELED",
                "MORDEKAISER_R_DYNAMIC_STAT_STEAL_DEFENSES_AND_HEALTH_NOT_MODELED",
            ),
        )

    def lane_sustain_extra_health(
        self,
        context: ParticipantContext,
        *,
        duration_ms: int,
        no_damage_delay_ms: int,
    ) -> tuple[Decimal, tuple[str, ...]]:
        """Decline to invent lane healing from an unknown W resource history.

        :param context: Role-bound snapshot containing Mordekaiser's maximum health.
        :param duration_ms: Lane observation window in milliseconds.
        :param no_damage_delay_ms: Delay before out-of-combat recovery can begin.
        :return: Zero recovery and the dynamic-resource evidence blocker.
        """
        return Decimal(0), (
            "MORDEKAISER_LANE_W_DYNAMIC_SHIELD_RESOURCE_NOT_MODELED",
        )
