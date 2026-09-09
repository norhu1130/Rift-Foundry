"""Role-symmetric matchup dispatch through champion Cogs."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any

from lol_build.application.progress import ProgressCallback, report_progress
from lol_build.application.threat import (
    ThreatParticipant,
    allocate_threat,
    policy_blockers,
)
from lol_build.cogs import (
    AttackCadenceModifierWindow,
    CastBlockWindow,
    ChampionCog,
    ChampionCogRegistry,
    ControlImmunityWindow,
    ControlType,
    OpponentView,
    ParticipantContext,
    create_default_registry,
)
from lol_build.cogs.base import CogCapability
from lol_build.core.canonical import dumps
from lol_build.core.expression import EvaluationContext, evaluate
from lol_build.core.timeline import (
    ALLY_ENTITIES,
    OPPONENT_ENTITIES,
    ActionChannel,
    ActionEvent,
    Combatant,
    EntityId,
    StatusOutput,
    TimelineResult,
    simulate_timeline,
)
from lol_build.items.catalog import load_complete_item_pool
from lol_build.items.progression import simulate_engagement


@dataclass(frozen=True)
class ParticipantSpec:
    """Describe one champion joining an encounter beside the actor or opponent.

    :param champion: Champion alias or numeric identifier for this participant.
    :param item_ids: Ordered completed items owned by this participant.
    :param bonus_health: Progression health not present in static item data.
    """

    champion: str | int
    item_ids: tuple[int, ...] = ()
    bonus_health: Decimal = Decimal(0)


OpponentSpec = ParticipantSpec
AllySpec = ParticipantSpec


@dataclass(frozen=True)
class MatchupRequest:
    """Describe one role-oriented but mechanically symmetric matchup.

    :param actor: Champion alias or numeric identifier receiving the recommendation.
    :param opponent: Champion alias or numeric identifier on the other side.
    :param level: Shared deterministic benchmark level.
    :param duration_ms: Total simulated encounter duration in milliseconds.
    :param horizon_ms: Early-damage measurement horizon in milliseconds.
    :param actor_item_ids: Ordered completed items owned by the actor.
    :param opponent_item_ids: Ordered completed items owned by the opponent.
    :param actor_bonus_health: Progression health not present in static item data.
    :param opponent_bonus_health: Opponent progression health from stack mechanics.
    :param additional_opponents: Further opponents fighting alongside ``opponent``.
    :param allies: Champions fighting alongside the actor, bound to ``ALLY_2`` onward.
    :param team_arrival_distance: Center-to-center separation each further
        opponent must close before it can act on the actor.
    :param team_arrival_spends_dash: Whether an arriving opponent spends its
        gap-closer walking into the encounter instead of keeping it for combat.
    :param active_duty_policy: How a short item active bound to a long cooldown
        is credited to the pursuit benchmark. Defaults to ``uncorrelated``
        (credit scaled by ``duration / cooldown``, i.e. how much of the time
        the active is actually up) rather than ``per_engagement`` (credit
        scaled only by how much of the pursuit window the active's duration
        covers, ignoring its cooldown entirely) — the latter let a long-
        cooldown item's incidental movement grant compete as if it were
        always available, which measurably won item slots on its side effect
        alone (P1-070; see ``TASKS.md``).
    :param pursuit_target_policy: Whether the pursued opponent retreats.
    """

    actor: str | int
    opponent: str | int
    level: int = 13
    duration_ms: int = 8000
    horizon_ms: int = 3000
    actor_item_ids: tuple[int, ...] = ()
    opponent_item_ids: tuple[int, ...] = ()
    actor_bonus_health: Decimal = Decimal(0)
    opponent_bonus_health: Decimal = Decimal(0)
    additional_opponents: tuple[ParticipantSpec, ...] = ()
    allies: tuple[ParticipantSpec, ...] = ()
    team_arrival_distance: Decimal = Decimal(650)
    team_arrival_spends_dash: bool = False
    active_duty_policy: str = "uncorrelated"
    pursuit_target_policy: str = "range_aware"

    @property
    def opponent_specs(self) -> tuple[ParticipantSpec, ...]:
        """List every opponent, primary first, in canonical entity order.

        :return: Opponent specifications covering the whole opposing side.
        """
        primary = ParticipantSpec(
            self.opponent, self.opponent_item_ids, self.opponent_bonus_health
        )
        return (primary, *self.additional_opponents)

    @property
    def ally_specs(self) -> tuple[ParticipantSpec, ...]:
        """List the actor's side, actor first, in canonical entity order.

        :return: Participant specifications covering the actor's whole side.
        """
        primary = ParticipantSpec(
            self.actor, self.actor_item_ids, self.actor_bonus_health
        )
        return (primary, *self.allies)


@dataclass(frozen=True)
class ResolvedMatchup:
    """Expose the concrete Cogs selected for a matchup request."""

    actor_cog: str
    actor_champion_id: int
    opponent_cog: str
    opponent_champion_id: int
    same_cog_contract: bool
    specialized_recommendation_available: bool


@dataclass(frozen=True)
class MatchupEvaluation:
    """Contain a deterministic two-sided combat simulation and its evidence blockers."""

    request: MatchupRequest
    resolved: ResolvedMatchup
    actor_action_model: str
    actor_reaction_model: str
    opponent_action_model: str
    opponent_reaction_model: str
    actor_hp_lost: Decimal
    opponent_hp_lost: Decimal
    timeline: TimelineResult
    blockers: tuple[str, ...]
    opponents_hp_lost: Mapping[EntityId, Decimal] = field(default_factory=dict)

    @property
    def opposing_side_hp_lost(self) -> Decimal:
        """Sum the health removed from every opponent in the encounter.

        :return: Combined health loss across the opposing side.
        """
        return sum(self.opponents_hp_lost.values(), Decimal(0))


@dataclass(frozen=True)
class MatchupRecommendation:
    """Wrap the actor-owned recommendation together with dispatch metadata."""

    resolved: ResolvedMatchup
    recommendation: Any | None
    blockers: tuple[str, ...]


def _delay_until_contact(
    events: tuple[ActionEvent, ...],
    contact_ms: int | None,
) -> tuple[ActionEvent, ...]:
    """Cancel actions taken before a participant has closed to contact.

    :param events: Immutable action schedule for one arriving participant.
    :param contact_ms: Millisecond at which contact is reached, or ``None`` when
        the participant never reaches the actor inside the encounter.
    :return: Schedule whose premature actions carry a causal cancellation.
    """
    if contact_ms == 0:
        return events
    reason = (
        "NOT_IN_CONTACT_WITHIN_ENCOUNTER"
        if contact_ms is None
        else f"NOT_YET_IN_CONTACT:{contact_ms}"
    )
    return tuple(
        replace(event, cancelled=True, cancellation_reason=reason)
        if not event.cancelled and (contact_ms is None or event.at_ms < contact_ms)
        else event
        for event in events
    )


def _threat_participant(view: OpponentView, cog: ChampionCog) -> ThreatParticipant:
    """Describe one participant for the position-and-role targeting policy.

    :param view: Participant entity bound to its resolved snapshot.
    :param cog: Champion Cog carrying the locked role tags.
    :return: Participant description consumed by the threat policy.
    """
    return ThreatParticipant(
        view.entity,
        view.snapshot.attack_range,
        tuple(cog.document.get("tags", ())),
    )


def _opponent_combatant(view: OpponentView) -> Combatant:
    """Build the timeline combatant for one opposing participant.

    :param view: Opponent entity bound to its resolved snapshot.
    :return: Combatant seeded at full health with the snapshot's defenses.
    """
    snapshot = view.snapshot
    return Combatant(
        view.entity,
        snapshot.max_hp,
        snapshot.max_hp,
        snapshot.armor,
        snapshot.magic_resistance,
        percent_armor_penetration=snapshot.percent_armor_penetration,
        flat_armor_penetration=snapshot.flat_armor_penetration,
        percent_magic_penetration=snapshot.percent_magic_penetration,
        flat_magic_penetration=snapshot.flat_magic_penetration,
        tenacity=snapshot.tenacity,
    )


def _apply_cast_blocks(
    events: tuple[ActionEvent, ...],
    windows: tuple[CastBlockWindow, ...],
) -> tuple[ActionEvent, ...]:
    """Mark actions that occur inside an opponent control window.

    :param events: Original immutable action schedule.
    :param windows: Active control windows emitted by the opponent Cog.
    :return: A new schedule whose blocked actions carry causal cancellation details.
    """
    return tuple(
        replace(
            event,
            cancelled=True,
            cancellation_reason=f"OPPONENT_CAST_BLOCK:{window.id}",
        )
        if (
            window := next(
                (
                    value
                    for value in windows
                    if value.start_ms <= event.at_ms < value.end_ms
                    and event.channel in value.blocked_channels
                ),
                None,
            )
        )
        is not None
        and not event.cancelled
        else event
        for event in events
    )


def _active_cast_windows(
    windows: tuple[CastBlockWindow, ...],
    source_events: tuple[ActionEvent, ...],
    recipient_tenacity: Decimal,
    recipient_immunities: tuple[ControlImmunityWindow, ...] = (),
) -> tuple[CastBlockWindow, ...]:
    """Filter causally absent CC and shorten duration-reducible windows.

    :param windows: Reaction windows declared by a champion Cog.
    :param source_events: Current fixed-point schedule of the CC source.
    :param recipient_tenacity: Permanent item tenacity of the controlled participant.
    :param recipient_immunities: Active discrete immunity windows owned by the recipient.
    :return: Active windows adjusted for source cancellation and tenacity.
    """
    cancelled = {event.id for event in source_events if event.cancelled}
    bounded_tenacity = min(Decimal("0.99"), max(Decimal(0), recipient_tenacity))
    return tuple(
        replace(
            window,
            end_ms=window.start_ms
            + max(
                1,
                int(Decimal(window.end_ms - window.start_ms) * (Decimal(1) - bounded_tenacity)),
            ),
        )
        if window.tenacity_reducible
        else window
        for window in windows
        if window.source_event_id is None or window.source_event_id not in cancelled
        if not any(
            immunity.start_ms <= window.start_ms < immunity.end_ms
            and immunity.blocks(window.control_type)
            for immunity in recipient_immunities
        )
    )


def _active_control_immunities(
    windows: tuple[ControlImmunityWindow, ...],
    source_events: tuple[ActionEvent, ...],
) -> tuple[ControlImmunityWindow, ...]:
    """Discard immunity windows whose enabling cast was causally cancelled.

    :param windows: Immunity intervals declared by the recipient Cog.
    :param source_events: Current fixed-point schedule of the immunity owner.
    :return: Immunity intervals backed by an active source event.
    """
    cancelled = {event.id for event in source_events if event.cancelled}
    return tuple(
        window
        for window in windows
        if window.source_event_id is None or window.source_event_id not in cancelled
    )


def _active_attack_cadence_windows(
    windows: tuple[AttackCadenceModifierWindow, ...],
    source_events: tuple[ActionEvent, ...],
) -> tuple[AttackCadenceModifierWindow, ...]:
    """Discard cadence modifiers whose source action did not resolve.

    :param windows: Cadence modifiers declared by the opposing reaction plan.
    :param source_events: Current fixed-point schedule of the modifier source.
    :return: Causally active cadence modifiers in deterministic order.
    :raises ValueError: If an active window has invalid timing or multiplier data.
    """
    cancelled = {event.id for event in source_events if event.cancelled}
    active = tuple(
        window
        for window in windows
        if window.source_event_id is None or window.source_event_id not in cancelled
    )
    for window in active:
        if window.start_ms < 0 or window.end_ms <= window.start_ms:
            raise ValueError(f"invalid attack cadence window: {window.id}")
        if not window.multiplier.is_finite() or window.multiplier <= 0:
            raise ValueError(f"attack cadence multiplier must be positive: {window.id}")
    return tuple(sorted(active, key=lambda window: (window.start_ms, window.end_ms, window.id)))


def _cadence_adjusted_timestamp(
    original_ms: int,
    windows: tuple[AttackCadenceModifierWindow, ...],
) -> int:
    """Map constant-clock attack progress onto a piecewise modified clock.

    :param original_ms: Timestamp generated from the participant's base cadence.
    :param windows: Active real-time cadence modifier windows.
    :return: Earliest real timestamp at which the original attack progress is met.
    """
    if not windows or original_ms <= 0:
        return original_ms
    boundaries = sorted(
        {point for window in windows for point in (window.start_ms, window.end_ms)}
    )
    actual_cursor = 0
    progress = Decimal(0)
    required = Decimal(original_ms)
    for boundary in boundaries:
        multiplier = Decimal(1)
        for window in windows:
            if window.start_ms <= actual_cursor < window.end_ms:
                multiplier *= window.multiplier
        available = Decimal(boundary - actual_cursor) * multiplier
        if required <= progress + available:
            elapsed = ((required - progress) / multiplier).to_integral_value(
                rounding=ROUND_CEILING
            )
            return actual_cursor + int(elapsed)
        progress += available
        actual_cursor = boundary
    return actual_cursor + int(
        (required - progress).to_integral_value(rounding=ROUND_CEILING)
    )


def _apply_attack_cadence(
    events: tuple[ActionEvent, ...],
    windows: tuple[AttackCadenceModifierWindow, ...],
    *,
    duration_ms: int,
) -> tuple[ActionEvent, ...]:
    """Reschedule basic attacks while leaving every other action channel intact.

    A temporary reduction slows attack-clock progress only inside its real-time
    window. Once the window expires, progress resumes at the original rate; the
    delay accumulated during the debuff remains instead of becoming an estimated
    damage multiplier.

    :param events: Original immutable champion action schedule.
    :param windows: Active cadence modifiers applied by the opponent.
    :param duration_ms: Inclusive boundary used to discard attacks delayed past combat.
    :return: Chronologically ordered schedule with adjusted basic-attack timestamps.
    """
    adjusted = (
        replace(event, at_ms=_cadence_adjusted_timestamp(event.at_ms, windows))
        if event.channel is ActionChannel.BASIC_ATTACK
        else event
        for event in events
    )
    return tuple(
        sorted(
            (event for event in adjusted if event.at_ms <= duration_ms),
            key=lambda event: (event.at_ms, event.sequence),
        )
    )


def _control_type_from_status(status: str) -> ControlType | None:
    """Normalize a timeline status into the shared control taxonomy.

    :param status: Raw status identifier emitted by a champion or item effect.
    :return: Recognized control type, ``UNSPECIFIED`` for another ``CC_`` status,
        or ``None`` for a non-control status.
    """
    normalized = status.strip().upper()
    if normalized.startswith("CC_"):
        normalized = normalized.removeprefix("CC_")
        try:
            return ControlType(normalized)
        except ValueError:
            return ControlType.UNSPECIFIED
    try:
        return ControlType(normalized)
    except ValueError:
        return None


def _strip_immune_control_outputs(
    events: tuple[ActionEvent, ...],
    immunities: tuple[ControlImmunityWindow, ...],
) -> tuple[ActionEvent, ...]:
    """Remove immune control outputs while preserving sibling damage outputs.

    :param events: Champion and item events ready for final timeline replay.
    :param immunities: Causally active control-immunity intervals for both roles.
    :return: Events with rejected status outputs removed and empty events omitted.
    """
    adjusted: list[ActionEvent] = []
    for event in events:
        outputs = tuple(
            output
            for output in event.outputs
            if not (
                isinstance(output, StatusOutput)
                and (control_type := _control_type_from_status(output.status)) is not None
                and any(
                    immunity.recipient is output.recipient
                    and immunity.start_ms <= event.at_ms < immunity.end_ms
                    and immunity.blocks(control_type)
                    for immunity in immunities
                )
            )
        )
        if outputs:
            adjusted.append(replace(event, outputs=outputs))
    return tuple(adjusted)


class MatchupEngine:
    """Coordinate champion Cogs, locked item data, and the shared timeline.

    :param root: Project root containing the patch-locked data tree.
    :param registry: Optional preconfigured Cog registry used for dependency injection.
    """

    def __init__(self, root: Path, registry: ChampionCogRegistry | None = None) -> None:
        """Load the deterministic item catalog and attach curated effect programs.

        :param root: Project root containing ``data/raw`` and ``data/curated``.
        :param registry: Optional registry override for tests or extensions.
        :return: None.
        """
        self.root = root.resolve()
        self.registry = registry or create_default_registry(self.root)
        self._items: dict[int, dict[str, Any]] = {}
        for source in load_complete_item_pool(self.root):
            item = dict(source)
            effect_path = self.root / "data/curated/item_effects" / f"{item['id']}.json"
            item["__effect_programs"] = (
                json.loads(effect_path.read_text(encoding="utf-8"))["programs"]
                if effect_path.exists()
                else []
            )
            labels = {program.get("source_label") for program in item["__effect_programs"]}
            if "PASSIVE:Spellblade" in labels:
                item["groups"]["shared_cooldown"] = "SPELLBLADE"
            if "PASSIVE:Lifeline" in labels:
                item["groups"]["shared_cooldown"] = "LIFELINE"
            if "PASSIVE:Cleave" in labels:
                item["groups"]["same_passive"] = "HYDRA_CLEAVE"
            self._items[item["id"]] = item

    @property
    def complete_items(self) -> tuple[dict[str, Any], ...]:
        """Return complete candidate items in stable numeric-ID order.

        :return: Immutable tuple of item documents.
        """
        return tuple(self._items[item_id] for item_id in sorted(self._items))

    def resolve(self, request: MatchupRequest) -> ResolvedMatchup:
        """Resolve both champion aliases without assigning permanent combat roles.

        :param request: Matchup whose participants should be resolved.
        :return: Cog identities and structural recommendation availability.
        :raises KeyError: If either champion alias is unknown.
        """
        actor = self.registry.require_cog(request.actor)
        opponent = self.registry.require_cog(request.opponent)
        specialized = actor.has_capability(CogCapability.RECOMMENDATION)
        return ResolvedMatchup(
            actor.qualified_name,
            actor.champion_id,
            opponent.qualified_name,
            opponent.champion_id,
            isinstance(actor, ChampionCog) and isinstance(opponent, ChampionCog),
            specialized,
        )

    def _item_stats(
        self,
        item_ids: tuple[int, ...],
        level: int,
        cog: ChampionCog,
        bonus_health: Decimal = Decimal(0),
    ) -> dict[str, Decimal]:
        """Aggregate static and unconditional item stats for one participant.

        :param item_ids: Ordered item identifiers owned by the participant.
        :param level: Champion level used by level-dependent expressions.
        :param cog: Champion Cog providing base stats.
        :param bonus_health: External health accumulated by progression mechanics.
        :return: Normalized stat map consumed by :meth:`ChampionCog.snapshot`.
        :raises ValueError: If an item is absent from the locked complete-item pool.
        """
        result: dict[str, Decimal] = {}
        base = cog.snapshot(level=level)
        champion_stats = cog.document["stats"]
        detail = cog.detail_root or {}
        growth = cog.growth_multiplier(level)

        def champion_value(detail_key: str, fallback_key: str) -> Decimal:
            """Resolve one detailed stat with its summary fallback.

            :param detail_key: CommunityDragon stat key.
            :param fallback_key: Data Dragon summary key.
            :return: Resolved decimal stat value.
            """
            raw = detail.get(detail_key)
            if isinstance(raw, dict) and "baseValue" in raw:
                return Decimal(str(raw["baseValue"]))
            return Decimal(str(champion_stats[fallback_key]))

        base_mana = (
            champion_value("baseMPModifiable", "mp")
            + champion_value("mpPerLevelModifiable", "mpperlevel") * growth
        )
        for item_id in item_ids:
            try:
                item = self._items[item_id]
            except KeyError as error:
                raise ValueError(f"unknown or non-complete item: {item_id}") from error
            for stat, expression in item["stats"].items():
                value = evaluate(expression, EvaluationContext(level, level, {}))
                if stat in {
                    "PERCENT_ARMOR_PENETRATION",
                    "PERCENT_MAGIC_PENETRATION",
                    "TENACITY",
                }:
                    result[stat] = Decimal(1) - (Decimal(1) - result.get(stat, Decimal(0))) * (
                        Decimal(1) - value
                    )
                else:
                    result[stat] = result.get(stat, Decimal(0)) + value
        context = EvaluationContext(
            level,
            level,
            {
                ("SELF", "BASE", "AD"): base.attack_damage,
                ("SELF", "BONUS", "AD"): result.get("AD", Decimal(0)),
                ("SELF", "TOTAL", "AD"): base.attack_damage + result.get("AD", Decimal(0)),
                ("SELF", "BONUS", "HP"): result.get("HP", Decimal(0)),
                ("SELF", "BONUS", "MANA"): result.get("MANA", Decimal(0)),
                ("SELF", "MAX", "MANA"): base_mana + result.get("MANA", Decimal(0)),
                ("SELF", "TOTAL", "ARMOR"): base.armor + result.get("ARMOR", Decimal(0)),
                ("SELF", "TOTAL", "MAGIC_RESISTANCE"): base.magic_resistance
                + result.get("MAGIC_RESISTANCE", Decimal(0)),
                ("SELF", "TOTAL", "MOVE_SPEED"): base.move_speed
                + result.get("MOVE_SPEED_FLAT", Decimal(0)),
                ("SELF", "TOTAL", "HEAL_SHIELD_POWER"): result.get("HEAL_SHIELD_POWER", Decimal(0)),
            },
        )
        static_grants = {
            "BONUS_AD": "AD",
            "ATTACK_DAMAGE_FLAT": "AD",
            "AD_FLAT": "AD",
            "HP_FLAT": "HP",
            "ABILITY_HASTE": "ABILITY_HASTE",
            "ABILITY_HASTE_FROM_BONUS_AD": "ABILITY_HASTE",
            "AP_FLAT": "AP",
            "MAGIC_RESISTANCE_FLAT": "MAGIC_RESISTANCE",
        }
        health_multiplier = Decimal(1)
        ap_multiplier = Decimal(1)
        for item_id in item_ids:
            for program in self._items[item_id]["__effect_programs"]:
                if program["trigger"] != "ALWAYS":
                    continue
                for operation in program["operations"]:
                    if operation.get("status_or_stat") == "ITEM_HEALTH_INCREASE_PERCENT":
                        health_multiplier *= Decimal(1) + evaluate(
                            operation["value_expression"], context
                        )
                    if operation.get("status_or_stat") == "TOTAL_AP_INCREASE_PERCENT":
                        ap_multiplier *= Decimal(1) + evaluate(
                            operation["value_expression"], context
                        )
                    target = static_grants.get(operation.get("status_or_stat"))
                    if operation["kind"] == "GRANT_STAT" and target is not None:
                        result[target] = result.get(target, Decimal(0)) + evaluate(
                            operation["value_expression"], context
                        )
        result["HP"] = (result.get("HP", Decimal(0)) + bonus_health) * health_multiplier
        result["AP"] = result.get("AP", Decimal(0)) * ap_multiplier
        return result

    def _enemy_item_stat_modifiers(self, item_ids: tuple[int, ...]) -> dict[str, Decimal]:
        """Compile opponent auras that alter precomputed champion schedules.

        :param item_ids: Items owned by the opposing participant.
        :return: Snapshot modifiers applied before action plans are generated.
        """
        attack_speed_multiplier = Decimal(1)
        for item_id in item_ids:
            for program in self._items[item_id]["__effect_programs"]:
                if program["trigger"] != "ALWAYS":
                    continue
                for operation in program["operations"]:
                    if (
                        operation["kind"] == "GRANT_STAT"
                        and operation["target"] in {"TARGET", "NEARBY_ENEMIES"}
                        and operation.get("status_or_stat") == "ATTACK_SPEED_REDUCTION_PERCENT"
                    ):
                        amount = evaluate(
                            operation["value_expression"], EvaluationContext(13, 13, {})
                        )
                        attack_speed_multiplier *= Decimal(1) - amount
        return {"ATTACK_SPEED_MULTIPLIER": attack_speed_multiplier}

    @staticmethod
    def _arrival_ms(
        view: OpponentView,
        cog: ChampionCog,
        context: ParticipantContext,
        *,
        distance: Decimal,
        duration_ms: int,
        spends_dash: bool,
    ) -> int | None:
        """Time one opponent's approach to the actor with the pursuit benchmark.

        The primary opponent is the matchup the caller asked about and is
        already engaged, so only the opponents arriving behind it pay this cost.
        A ranged opponent whose attack range already spans ``distance`` reaches
        contact immediately.

        :param view: Arriving opponent bound to its resolved snapshot.
        :param cog: Champion Cog supplying kit pursuit modifiers.
        :param context: Participant context for that Cog.
        :param distance: Center-to-center separation to close.
        :param duration_ms: Encounter duration bounding the approach.
        :param spends_dash: Whether the gap-closer is spent on the approach.
        :return: Contact millisecond, or ``None`` if contact is never reached.
        """
        engagement = simulate_engagement(
            initial_center_distance=distance,
            actor_attack_range=view.snapshot.attack_range,
            actor_move_speed=view.snapshot.move_speed,
            target_move_speed=Decimal(0),
            window_ms=duration_ms,
            actor_speed_multiplier=cog.engagement_speed_multiplier(context),
            actor_dash_distance=(
                cog.engagement_dash_distance(context) if spends_dash else Decimal(0)
            ),
        )
        if engagement.contact_time_ms is None:
            return None
        return int(engagement.contact_time_ms.to_integral_value(rounding=ROUND_CEILING))

    @staticmethod
    def _focus_target(
        opposing_side: tuple[OpponentView, ...],
    ) -> tuple[EntityId, Any]:
        """Choose the opponent the actor aims at for single-target actions.

        The locked patch data records no threat, aggro, or positioning model, so
        the actor keeps aiming at the opponent the caller named first. Callers
        that supply more than one opponent receive
        ``FOCUS_TARGET_POLICY_UNVERIFIED`` to mark that choice as an assumption.

        :param opposing_side: Opponents in canonical entity order.
        :return: Entity and snapshot of the aimed-at opponent.
        """
        primary = opposing_side[0]
        return primary.entity, primary.snapshot

    def evaluate(self, request: MatchupRequest) -> MatchupEvaluation:
        """Simulate both participants, their reactions, and their item effects.

        :param request: Fully specified deterministic matchup request.
        :return: Timeline result plus every unresolved evidence blocker.
        :raises ValueError: If the duration, horizon, or an item identifier is invalid.
        """
        if request.duration_ms <= 0:
            raise ValueError("duration_ms must be positive")
        if not 0 < request.horizon_ms <= request.duration_ms:
            raise ValueError("horizon_ms must be within the encounter duration")
        specs = request.opponent_specs
        if len(specs) > len(OPPONENT_ENTITIES):
            raise ValueError("an encounter supports at most five opponents")
        actor_cog = self.registry.require_cog(request.actor)
        opponent_cogs = [self.registry.require_cog(spec.champion) for spec in specs]
        opposing_item_ids = tuple(
            item_id for spec in specs for item_id in spec.item_ids
        )
        actor_item_stats = self._item_stats(
            request.actor_item_ids, request.level, actor_cog, request.actor_bonus_health
        )
        actor_item_stats.update(self._enemy_item_stat_modifiers(opposing_item_ids))
        actor_snapshot = actor_cog.snapshot(
            level=request.level,
            item_stats=actor_item_stats,
        )
        opponent_snapshots = []
        for spec, cog in zip(specs, opponent_cogs, strict=True):
            item_stats = self._item_stats(
                spec.item_ids, request.level, cog, spec.bonus_health
            )
            item_stats.update(self._enemy_item_stat_modifiers(request.actor_item_ids))
            opponent_snapshots.append(
                cog.snapshot(level=request.level, item_stats=item_stats)
            )
        opponent_entities = OPPONENT_ENTITIES[: len(specs)]
        opponent_snapshot = opponent_snapshots[0]
        opposing_side = tuple(
            OpponentView(entity, snapshot)
            for entity, snapshot in zip(opponent_entities, opponent_snapshots, strict=True)
        )
        ally_specs = request.allies
        if len(ally_specs) > len(ALLY_ENTITIES) - 1:
            raise ValueError("a side supports at most five participants")
        ally_cogs = [self.registry.require_cog(spec.champion) for spec in ally_specs]
        ally_snapshots = []
        for spec, cog in zip(ally_specs, ally_cogs, strict=True):
            item_stats = self._item_stats(spec.item_ids, request.level, cog, spec.bonus_health)
            item_stats.update(self._enemy_item_stat_modifiers(opposing_item_ids))
            ally_snapshots.append(cog.snapshot(level=request.level, item_stats=item_stats))
        ally_side = tuple(
            OpponentView(entity, snapshot)
            for entity, snapshot in zip(
                ALLY_ENTITIES[1 : 1 + len(ally_specs)], ally_snapshots, strict=True
            )
        )
        actor_side = (OpponentView(EntityId.ACTOR, actor_snapshot), *ally_side)
        focus_entity, focus_snapshot = self._focus_target(opposing_side)
        actor_threats = tuple(
            _threat_participant(view, cog)
            for view, cog in zip(actor_side, (actor_cog, *ally_cogs), strict=True)
        )
        opponent_threats = tuple(
            _threat_participant(view, cog)
            for view, cog in zip(opposing_side, opponent_cogs, strict=True)
        )
        snapshot_by_entity = {
            view.entity: view.snapshot for view in (*actor_side, *opposing_side)
        }
        opponent_targets = allocate_threat(opponent_threats, actor_threats)
        # The caller named this matchup, so its primary opponent stays on the
        # actor. Left to the policy a durable actor is the least valuable target
        # and would go unattacked, which would silence the survivability signal
        # the defensive branches rank on.
        opponent_targets[opposing_side[0].entity] = EntityId.ACTOR
        ally_targets = allocate_threat(actor_threats[1:], opponent_threats)
        actor_context = ParticipantContext(
            EntityId.ACTOR,
            focus_entity,
            actor_snapshot,
            focus_snapshot,
            request.duration_ms,
            request.horizon_ms,
            opponents=opposing_side,
        )
        opponent_contexts = [
            ParticipantContext(
                view.entity,
                opponent_targets[view.entity],
                view.snapshot,
                snapshot_by_entity[opponent_targets[view.entity]],
                request.duration_ms,
                request.horizon_ms,
                opponents=actor_side,
            )
            for view in opposing_side
        ]
        ally_contexts = [
            ParticipantContext(
                view.entity,
                ally_targets[view.entity],
                view.snapshot,
                snapshot_by_entity[ally_targets[view.entity]],
                request.duration_ms,
                request.horizon_ms,
                opponents=opposing_side,
            )
            for view in ally_side
        ]
        actor_actions = actor_cog.build_action_plan(actor_context)
        actor_reactions = actor_cog.build_reaction_plan(actor_context)
        ally_action_plans = [
            cog.build_action_plan(context)
            for cog, context in zip(ally_cogs, ally_contexts, strict=True)
        ]
        ally_reaction_plans = [
            cog.build_reaction_plan(context)
            for cog, context in zip(ally_cogs, ally_contexts, strict=True)
        ]
        opponent_action_plans = [
            cog.build_action_plan(context)
            for cog, context in zip(opponent_cogs, opponent_contexts, strict=True)
        ]
        opponent_reaction_plans = [
            cog.build_reaction_plan(context)
            for cog, context in zip(opponent_cogs, opponent_contexts, strict=True)
        ]
        opponent_actions = opponent_action_plans[0]
        opponent_reactions = opponent_reaction_plans[0]

        arrival_by_entity: dict[EntityId, int | None] = {opposing_side[0].entity: 0}
        for view, cog, context in zip(
            opposing_side[1:], opponent_cogs[1:], opponent_contexts[1:], strict=True
        ):
            arrival_by_entity[view.entity] = self._arrival_ms(
                view,
                cog,
                context,
                distance=request.team_arrival_distance,
                duration_ms=request.duration_ms,
                spends_dash=request.team_arrival_spends_dash,
            )
        for view, cog, context in zip(ally_side, ally_cogs, ally_contexts, strict=True):
            arrival_by_entity[view.entity] = self._arrival_ms(
                view,
                cog,
                context,
                distance=request.team_arrival_distance,
                duration_ms=request.duration_ms,
                spends_dash=request.team_arrival_spends_dash,
            )
        actor_events = actor_actions.events
        ally_event_lists = [
            _delay_until_contact(plan.events, arrival_by_entity[view.entity])
            for view, plan in zip(ally_side, ally_action_plans, strict=True)
        ]
        opponent_event_lists = [
            _delay_until_contact(plan.events, arrival_by_entity[view.entity])
            for view, plan in zip(opposing_side, opponent_action_plans, strict=True)
        ]
        converged = False
        for _ in range(6):
            actor_immunities = _active_control_immunities(
                actor_reactions.control_immunity_windows,
                actor_events,
            )
            incoming_cadence: tuple[AttackCadenceModifierWindow, ...] = ()
            incoming_blocks: tuple[CastBlockWindow, ...] = ()
            for view, plan, events in zip(
                opposing_side, opponent_reaction_plans, opponent_event_lists, strict=True
            ):
                if opponent_targets[view.entity] is not EntityId.ACTOR:
                    continue
                incoming_cadence += _active_attack_cadence_windows(
                    plan.attack_cadence_windows, events
                )
                incoming_blocks += _active_cast_windows(
                    plan.cast_block_windows,
                    events,
                    actor_snapshot.tenacity,
                    actor_immunities,
                )
            next_allies = []
            for view, plan, reactions, events in zip(
                ally_side, ally_action_plans, ally_reaction_plans, ally_event_lists, strict=True
            ):
                immunities = _active_control_immunities(
                    reactions.control_immunity_windows, events
                )
                ally_blocks: tuple[CastBlockWindow, ...] = ()
                ally_cadence: tuple[AttackCadenceModifierWindow, ...] = ()
                for enemy, enemy_plan, enemy_events in zip(
                    opposing_side, opponent_reaction_plans, opponent_event_lists, strict=True
                ):
                    if opponent_targets[enemy.entity] is not view.entity:
                        continue
                    ally_cadence += _active_attack_cadence_windows(
                        enemy_plan.attack_cadence_windows, enemy_events
                    )
                    ally_blocks += _active_cast_windows(
                        enemy_plan.cast_block_windows,
                        enemy_events,
                        view.snapshot.tenacity,
                        immunities,
                    )
                next_allies.append(
                    _apply_cast_blocks(
                        _apply_attack_cadence(
                            _delay_until_contact(
                                plan.events, arrival_by_entity[view.entity]
                            ),
                            ally_cadence,
                            duration_ms=request.duration_ms,
                        ),
                        ally_blocks,
                    )
                )
            next_actor = _apply_cast_blocks(
                _apply_attack_cadence(
                    actor_actions.events,
                    incoming_cadence,
                    duration_ms=request.duration_ms,
                ),
                incoming_blocks,
            )
            outgoing_by_target: dict[EntityId, list[tuple[Any, tuple[ActionEvent, ...]]]] = {}
            outgoing_by_target.setdefault(focus_entity, []).append(
                (actor_reactions, actor_events)
            )
            for ally, plan, events in zip(
                ally_side, ally_reaction_plans, ally_event_lists, strict=True
            ):
                outgoing_by_target.setdefault(ally_targets[ally.entity], []).append(
                    (plan, events)
                )
            next_opponents = []
            for view, plan, reactions, events in zip(
                opposing_side,
                opponent_action_plans,
                opponent_reaction_plans,
                opponent_event_lists,
                strict=True,
            ):
                immunities = _active_control_immunities(
                    reactions.control_immunity_windows, events
                )
                aimed_at_view = outgoing_by_target.get(view.entity, [])
                next_opponents.append(
                    _apply_cast_blocks(
                        _apply_attack_cadence(
                            _delay_until_contact(
                                plan.events, arrival_by_entity[view.entity]
                            ),
                            tuple(
                                window
                                for source_plan, source_events in aimed_at_view
                                for window in _active_attack_cadence_windows(
                                    source_plan.attack_cadence_windows, source_events
                                )
                            ),
                            duration_ms=request.duration_ms,
                        ),
                        tuple(
                            window
                            for source_plan, source_events in aimed_at_view
                            for window in _active_cast_windows(
                                source_plan.cast_block_windows,
                                source_events,
                                view.snapshot.tenacity,
                                immunities,
                            )
                        ),
                    )
                )
            if (
                next_actor == actor_events
                and next_opponents == opponent_event_lists
                and next_allies == ally_event_lists
            ):
                converged = True
                break
            actor_events = next_actor
            opponent_event_lists = next_opponents
            ally_event_lists = next_allies

        from lol_build.application.item_combat import compile_item_combat_events

        incoming_events: tuple[ActionEvent, ...] = ()
        for events in opponent_event_lists:
            incoming_events += events
        ally_item_results = [
            compile_item_combat_events(
                tuple(self._items[item_id] for item_id in spec.item_ids),
                events,
                context,
                incoming_events,
            )
            for spec, events, context in zip(
                ally_specs, ally_event_lists, ally_contexts, strict=True
            )
        ]
        actor_item_result = compile_item_combat_events(
            tuple(self._items[item_id] for item_id in request.actor_item_ids),
            actor_events,
            actor_context,
            incoming_events,
        )
        opponent_item_results = [
            compile_item_combat_events(
                tuple(self._items[item_id] for item_id in spec.item_ids),
                events,
                context,
                actor_events,
            )
            for spec, events, context in zip(
                specs, opponent_event_lists, opponent_contexts, strict=True
            )
        ]
        active_immunities = _active_control_immunities(
            actor_reactions.control_immunity_windows,
            actor_events,
        )
        for plan, events in zip(
            (*opponent_reaction_plans, *ally_reaction_plans),
            (*opponent_event_lists, *ally_event_lists),
            strict=True,
        ):
            active_immunities += _active_control_immunities(
                plan.control_immunity_windows, events
            )
        allied_events: tuple[ActionEvent, ...] = ()
        for view, plan, result, events in zip(
            ally_side, ally_reaction_plans, ally_item_results, ally_event_lists, strict=True
        ):
            arrival = arrival_by_entity[view.entity]
            allied_events += (
                events
                + _delay_until_contact(result.events, arrival)
                + _delay_until_contact(plan.events, arrival)
            )
        opposing_events: tuple[ActionEvent, ...] = ()
        for view, plan, result, events in zip(
            opposing_side,
            opponent_reaction_plans,
            opponent_item_results,
            opponent_event_lists,
            strict=True,
        ):
            arrival = arrival_by_entity[view.entity]
            opposing_events += (
                events
                + _delay_until_contact(result.events, arrival)
                + _delay_until_contact(plan.events, arrival)
            )
        combat_events = _strip_immune_control_outputs(
            actor_events
            + actor_item_result.events
            + actor_reactions.events
            + allied_events
            + opposing_events,
            active_immunities,
        )
        timeline = simulate_timeline(
            duration_ms=request.duration_ms,
            horizon_ms=request.horizon_ms,
            actor=Combatant(
                EntityId.ACTOR,
                actor_snapshot.max_hp,
                actor_snapshot.max_hp,
                actor_snapshot.armor,
                actor_snapshot.magic_resistance,
                percent_armor_penetration=actor_snapshot.percent_armor_penetration,
                flat_armor_penetration=actor_snapshot.flat_armor_penetration,
                percent_magic_penetration=actor_snapshot.percent_magic_penetration,
                flat_magic_penetration=actor_snapshot.flat_magic_penetration,
                tenacity=actor_snapshot.tenacity,
            ),
            target=_opponent_combatant(opposing_side[0]),
            additional_allies=tuple(_opponent_combatant(view) for view in ally_side),
            additional_targets=tuple(
                _opponent_combatant(view) for view in opposing_side[1:]
            ),
            events=tuple(
                sorted(combat_events, key=lambda event: (event.at_ms, event.sequence))
            ),
            damage_modifier_windows=(
                actor_reactions.damage_windows
                + tuple(
                    window
                    for plan in (*opponent_reaction_plans, *ally_reaction_plans)
                    for window in plan.damage_windows
                )
            ),
        )
        blockers = {
            *actor_actions.blockers,
            *actor_reactions.blockers,
            *actor_item_result.blockers,
        }
        for plan in (
            *opponent_action_plans,
            *opponent_reaction_plans,
            *opponent_item_results,
            *ally_action_plans,
            *ally_reaction_plans,
            *ally_item_results,
        ):
            blockers.update(plan.blockers)
        if ally_side:
            blockers.add("ALLY_CONTRIBUTION_EXCLUDED_FROM_BUILD_RANKING")
        blockers.update(
            policy_blockers(multi_participant=bool(ally_side or opposing_side[1:]))
        )
        if ally_side or opposing_side[1:]:
            blockers.add("PRIMARY_OPPONENT_PINNED_TO_ACTOR")
        if not converged:
            blockers.add("CAST_BLOCK_DEPENDENCY_DID_NOT_CONVERGE")
        if len(opposing_side) > 1:
            blockers.add("FOCUS_TARGET_POLICY_UNVERIFIED")
            if any(
                cog.has_capability(CogCapability.MULTI_TARGET)
                for cog in (actor_cog, *opponent_cogs, *ally_cogs)
            ):
                # Area reach is approximated from attack range, the only
                # positional fact the patch data records. How many champions a
                # given cast actually catches depends on the formation at that
                # moment, which the encounter does not model.
                blockers.add("AREA_ABILITY_REACH_APPROXIMATED_BY_LINE")
            blockers.add(
                f"TEAM_ARRIVAL_DISTANCE_ASSUMED:{request.team_arrival_distance}"
            )
            blockers.add(
                "TEAM_ARRIVAL_DASH_SPENT_ASSUMED"
                if request.team_arrival_spends_dash
                else "TEAM_ARRIVAL_DASH_RESERVED_ASSUMED"
            )
            if any(value is None for value in arrival_by_entity.values()):
                blockers.add("OPPONENT_NEVER_REACHES_CONTACT")
            if not any(cog.has_capability(CogCapability.MULTI_TARGET) for cog in (actor_cog,)):
                blockers.add(f"MULTI_TARGET_UNCURATED:{actor_cog.champion_key}")
        return MatchupEvaluation(
            request,
            self.resolve(request),
            actor_actions.model_id,
            actor_reactions.model_id,
            opponent_actions.model_id,
            opponent_reactions.model_id,
            actor_snapshot.max_hp - timeline.actor_at_end.current_hp,
            opponent_snapshot.max_hp - timeline.target_at_end.current_hp,
            timeline,
            tuple(sorted(blockers)),
            opponents_hp_lost={
                view.entity: view.snapshot.max_hp
                - timeline.targets_at_end[view.entity].current_hp
                for view in opposing_side
            },
        )

    def recommend(
        self,
        request: MatchupRequest,
        *,
        progress: ProgressCallback | None = None,
        workers: int | None = None,
    ) -> MatchupRecommendation:
        """Rank the actor's build paths using its Cog-declared behavior.

        Every actor runs through the same bounded generic search; no champion
        or matchup pair receives bespoke dispatch logic here. Champion-specific
        behavior belongs entirely in that champion's own Cog.

        :param request: Matchup and opponent build used to rank actor item paths.
        :param progress: Optional callback receiving live calculation milestones.
        :param workers: Worker processes the generic search may use.
        :return: Recommendation wrapper with release blockers.
        """
        actor_cog = self.registry.require_cog(request.actor)
        self.registry.require_cog(request.opponent)
        if not actor_cog.has_capability(CogCapability.RECOMMENDATION):
            report_progress(progress, "6/7 등록된 추천 모델 확인 완료")
            return MatchupRecommendation(
                self.resolve(request),
                None,
                (f"RECOMMENDATION_MODEL_UNCURATED:{actor_cog.champion_key}",),
            )
        from lol_build.application.cog_preview import generic_cog_build_preview

        recommendation = generic_cog_build_preview(
            self, request, progress=progress, workers=workers
        )
        return MatchupRecommendation(
            self.resolve(request),
            recommendation,
            tuple(recommendation.blockers),
        )


def main() -> None:
    """Run the matchup evaluation or recommendation command-line interface.

    :return: None.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("actor")
    parser.add_argument("opponent")
    parser.add_argument("--actor-items", nargs="*", type=int, default=())
    parser.add_argument("--opponent-items", nargs="*", type=int, default=())
    parser.add_argument("--recommend", action="store_true")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    engine = MatchupEngine(args.root)
    request = MatchupRequest(
        args.actor,
        args.opponent,
        actor_item_ids=tuple(args.actor_items),
        opponent_item_ids=tuple(args.opponent_items),
    )
    result = engine.recommend(request) if args.recommend else engine.evaluate(request)
    print(dumps(asdict(result)))


if __name__ == "__main__":
    main()
