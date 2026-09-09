"""Role-symmetric adapter from item programs to a Cog combat timeline."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from lol_build.cogs.base import ParticipantContext
from lol_build.core.expression import EvaluationContext, ExpressionError, evaluate
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    DamageOutput,
    EntityId,
    opponent_sequence_offset,
)
from lol_build.items.effects import (
    EffectRuntimeError,
    ItemEffectContext,
    ResolutionStatus,
    initial_effect_state,
    resolution_to_action_events,
    resolve_item_effect,
)


def duplicate_group_blockers(items: tuple[Mapping[str, Any], ...]) -> tuple[str, ...]:
    """Flag an item portfolio whose ``same_passive``/``shared_cooldown`` groups repeat.

    Mirrors ``items/evaluation.py``'s ``_duplicate_group`` check: repeating
    one of these groups is legal to purchase (``docs/candidate-generation.md``
    — duplicate ``purchase_limit`` is the only hard purchase rejection), but
    this engine has no interaction handler that lets two items in the same
    group share a passive proc or a cooldown without double-counting either
    one. Rather than silently double-count, a caller must treat a non-empty
    result as "cannot be scored" for this portfolio.

    :param items: Full item documents owned at the point being evaluated.
    :return: One ``UNRESOLVED_SAME_PASSIVE:<group>`` or
        ``UNRESOLVED_SHARED_COOLDOWN:<group>`` blocker per repeated group,
        sorted for determinism; empty when no group repeats.
    """

    blockers: list[str] = []
    group_prefixes = (
        ("same_passive", "UNRESOLVED_SAME_PASSIVE"),
        ("shared_cooldown", "UNRESOLVED_SHARED_COOLDOWN"),
    )
    for key, prefix in group_prefixes:
        groups = [item["groups"][key] for item in items if item["groups"][key] is not None]
        repeated = sorted(group for group, count in Counter(groups).items() if count > 1)
        blockers.extend(f"{prefix}:{group}" for group in repeated)
    return tuple(blockers)


@dataclass(frozen=True)
class ItemCombatEvents:
    """Contain timeline events compiled from item programs and their blockers."""

    events: tuple[ActionEvent, ...]
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class ItemEngagementModifiers:
    """Contain item-derived movement inputs for the approach simulation."""

    move_speed_flat: Decimal = Decimal(0)
    move_speed_percent: Decimal = Decimal(0)
    target_slow_fraction: Decimal = Decimal(0)
    dash_distance: Decimal = Decimal(0)
    blockers: tuple[str, ...] = ()


_SUPPORTED_TRIGGERS = {
    "ITEM_ACTIVE_USED",
    "BASIC_ATTACK_HIT",
    "ABILITY_HIT",
    "ABILITY_DAMAGE_TO_CHAMPION",
    "ABILITY_DAMAGE_TO_UNIT",
    "ATTACK_OR_ABILITY_HIT",
    "DAMAGE_TO_CHAMPION",
    "DAMAGE_DEALT",
    "PHYSICAL_DAMAGE_TO_CHAMPION",
    "MAGIC_DAMAGE_TO_CHAMPION",
    "MAGIC_OR_TRUE_DAMAGE_TO_CHAMPION",
    "ULTIMATE_CAST",
    "CHAMPION_DAMAGE_RECEIVED",
    "PHYSICAL_DAMAGE_RECEIVED",
    "MAGIC_DAMAGE_RECEIVED",
    "BASIC_ATTACK_RECEIVED",
    "DAMAGE_TAKEN_OR_DEALT",
    "ALWAYS",
    "OUT_OF_COMBAT",
    "MOVEMENT_UPDATED",
}

_EXTERNALLY_MODELED_PROGRAM_IDS = {"warmogs_heart"}
_TriggerScheduleEntry = tuple[int, set[str], frozenset[str]]


def _evaluation_context(context: ParticipantContext) -> EvaluationContext:
    """Translate participant snapshots into expression-engine stat keys.

    :param context: Owner and target snapshot pair.
    :return: Immutable expression evaluation context.
    """
    own = context.snapshot
    target = context.opponent_snapshot
    return EvaluationContext(
        own.level,
        target.level,
        {
            ("SELF", "BASE", "AD"): own.attack_damage,
            ("SELF", "BONUS", "AD"): Decimal(0),
            ("SELF", "TOTAL", "AD"): own.attack_damage,
            ("SELF", "BONUS", "HP"): own.bonus_health,
            ("SELF", "MAX", "HP"): own.max_hp,
            ("SELF", "CURRENT", "HP"): own.max_hp,
            ("TARGET", "MAX", "HP"): target.max_hp,
            ("TARGET", "CURRENT", "HP"): target.max_hp,
            ("TARGET", "BONUS", "HP"): target.bonus_health,
        },
    )


#: How an item active's short, cooldown-bound effect is credited to a pursuit
#: benchmark that is much longer than the effect and much shorter than the
#: cooldown. Neither reading is recorded in patch data, so both are named.
ACTIVE_DUTY_POLICIES = ("uncorrelated", "per_engagement", "always_ready")


def _active_duty_factor(
    program: dict[str, Any],
    operation: dict[str, Any],
    window_ms: int,
    policy: str,
) -> Decimal:
    """Scale one active's contribution by how long it lasts and how often it is up.

    An active grants its bonus for ``duration_ms`` and then waits out
    ``cooldown_ms``. Crediting the full value to a pursuit benchmark treats a
    two-second effect on a ninety-second cooldown as if it were permanent.

    ``uncorrelated`` credits the share of wall-clock time the effect is up,
    which assumes nothing about when a player presses it. ``per_engagement``
    assumes the active is saved for this engagement and credits only the share
    of the window it covers. ``always_ready`` keeps the original behavior.

    :param program: Effect program declaring the cooldown.
    :param operation: Operation declaring the effect duration.
    :param window_ms: Length of the pursuit benchmark.
    :param policy: One of :data:`ACTIVE_DUTY_POLICIES`.
    :return: Multiplier in ``[0, 1]`` applied to the operation's value.
    """
    if policy == "always_ready":
        return Decimal(1)
    duration = operation.get("duration_ms")
    if not duration or duration <= 0:
        return Decimal(1)
    coverage = min(Decimal(1), Decimal(duration) / Decimal(window_ms))
    if policy == "per_engagement":
        return coverage
    cooldown = program.get("cooldown_ms") or 0
    if cooldown <= 0:
        return coverage
    return min(Decimal(1), Decimal(duration) / Decimal(cooldown))


def item_engagement_modifiers(
    items: tuple[dict[str, Any], ...],
    context: ParticipantContext,
    *,
    actives_available: bool,
    window_ms: int = 3000,
    active_duty_policy: str = "per_engagement",
) -> ItemEngagementModifiers:
    """Project declarative movement operations onto the pursuit benchmark.

    :param items: Item documents owned by the approaching participant.
    :param context: Owner and opponent snapshots.
    :param actives_available: Whether deterministic item actives may be used.
    :param window_ms: Length of the pursuit benchmark the values feed.
    :param active_duty_policy: How short, cooldown-bound actives are credited.
    :return: Aggregated movement, slow, dash, and blocker data.
    :raises ValueError: If the duty policy is not recognized.
    """
    if active_duty_policy not in ACTIVE_DUTY_POLICIES:
        raise ValueError(f"unknown active duty policy: {active_duty_policy}")
    flat = Decimal(0)
    percent = Decimal(0)
    slow = Decimal(0)
    dash = Decimal(0)
    blockers: set[str] = set()
    evaluation = _evaluation_context(context)
    for item in items:
        for program in item.get("__effect_programs", ()):
            trigger = program["trigger"]
            enabled = trigger in {"OUT_OF_COMBAT", "MOVEMENT_UPDATED"}
            enabled = enabled or (actives_available and trigger == "ITEM_ACTIVE_USED")
            if not enabled:
                continue
            is_active = trigger == "ITEM_ACTIVE_USED"
            for operation in program["operations"]:
                try:
                    value = evaluate(operation["value_expression"], evaluation)
                except (ExpressionError, KeyError) as error:
                    blockers.add(f"ITEM_ENGAGEMENT_CONTEXT_UNRESOLVED:{program['id']}:{error}")
                    continue
                multiplier = operation.get("context_multiplier")
                if multiplier == "MOMENTUM_FRACTION":
                    value *= Decimal(1)
                elif multiplier is not None:
                    blockers.add(
                        f"ITEM_ENGAGEMENT_MULTIPLIER_UNRESOLVED:{program['id']}:{multiplier}"
                    )
                    continue
                if is_active:
                    duty = _active_duty_factor(program, operation, window_ms, active_duty_policy)
                    if duty < 1:
                        blockers.add(
                            f"ITEM_ACTIVE_DUTY_SCALED:{program['id']}:{active_duty_policy}"
                        )
                    value *= duty
                stat = operation.get("status_or_stat")
                target = operation["target"]
                if operation["kind"] == "DASH" and target == "SELF":
                    dash += value
                elif stat == "MOVE_SPEED_FLAT" and target == "SELF":
                    flat += value
                elif stat == "MOVE_SPEED_PERCENT" and target == "SELF":
                    percent += value / Decimal(2) if operation.get("decay") == "LINEAR" else value
                elif stat == "CC_SLOW" and target == "TARGET":
                    slow = max(slow, value)
    return ItemEngagementModifiers(flat, percent, slow, dash, tuple(sorted(blockers)))


def _triggers(event: ActionEvent, opponent_entity: EntityId) -> set[str]:
    """Infer declarative outgoing triggers from a champion action.

    :param event: Champion action being inspected.
    :param opponent_entity: Expected recipient for hostile damage.
    :return: Trigger names activated by the action.
    """
    if event.cancelled:
        return set()
    damage = tuple(
        output
        for output in event.outputs
        if isinstance(output, DamageOutput) and output.recipient is opponent_entity
    )
    if not damage:
        return set()
    result = {"DAMAGE_TO_CHAMPION", "DAMAGE_DEALT", "ATTACK_OR_ABILITY_HIT"}
    if event.channel is ActionChannel.BASIC_ATTACK:
        result.add("BASIC_ATTACK_HIT")
    if event.channel is ActionChannel.ABILITY:
        result.update({"ABILITY_HIT", "ABILITY_DAMAGE_TO_CHAMPION", "ABILITY_DAMAGE_TO_UNIT"})
    if any(output.damage_type.value == "PHYSICAL" for output in damage):
        result.add("PHYSICAL_DAMAGE_TO_CHAMPION")
    if any(output.damage_type.value == "MAGIC" for output in damage):
        result.update({"MAGIC_DAMAGE_TO_CHAMPION", "MAGIC_OR_TRUE_DAMAGE_TO_CHAMPION"})
    if any(output.damage_type.value == "TRUE" for output in damage):
        result.add("MAGIC_OR_TRUE_DAMAGE_TO_CHAMPION")
    parts = event.id.split("_")
    if len(parts) > 1 and parts[1].startswith("R"):
        result.add("ULTIMATE_CAST")
    return result


def _build_trigger_schedule(
    champion_events: tuple[ActionEvent, ...],
    context: ParticipantContext,
    opponent_events: tuple[ActionEvent, ...],
) -> list[_TriggerScheduleEntry]:
    """Build a chronological trigger stream for one item owner.

    :param champion_events: Owner actions after champion-level cancellation.
    :param context: Role binding used to recognize hostile recipients.
    :param opponent_events: Opponent actions used by defensive item triggers.
    :return: Timestamped trigger sets with runtime context flags.
    """
    schedule: list[_TriggerScheduleEntry] = [
        (0, {"ALWAYS"}, frozenset()),
        (
            0,
            {"OUT_OF_COMBAT", "MOVEMENT_UPDATED"},
            frozenset({"OUT_OF_COMBAT", "NO_MAGIC_DAMAGE_FOR_15_SECONDS"}),
        ),
        (1000, {"ITEM_ACTIVE_USED"}, frozenset({"TARGET_IS_ENEMY_CHAMPION"})),
    ]
    first_attack = True
    spellblade_ready = False
    for event in sorted(champion_events, key=lambda value: (value.at_ms, value.sequence)):
        triggers = _triggers(event, context.opponent_entity)
        if not triggers:
            continue
        flags = {"TARGET_IS_ENEMY_CHAMPION"}
        champion_action = event.id.split("_")[1] if "_" in event.id else ""
        if event.channel is ActionChannel.ABILITY:
            spellblade_ready = True
        if champion_action in {"Q", "W"} and event.channel is ActionChannel.BASIC_ATTACK:
            spellblade_ready = True
        if "BASIC_ATTACK_HIT" in triggers and first_attack:
            flags.add("FIRST_ATTACK_AGAINST_THIS_CHAMPION")
            first_attack = False
        if "BASIC_ATTACK_HIT" in triggers and spellblade_ready:
            flags.add("SPELLBLADE_READY")
            spellblade_ready = False
        schedule.append((event.at_ms, triggers, frozenset(flags)))

    for event in sorted(opponent_events, key=lambda value: (value.at_ms, value.sequence)):
        if event.cancelled:
            continue
        incoming = tuple(
            output
            for output in event.outputs
            if isinstance(output, DamageOutput) and output.recipient is context.self_entity
        )
        if not incoming:
            continue
        triggers = {"CHAMPION_DAMAGE_RECEIVED", "DAMAGE_TAKEN_OR_DEALT"}
        if event.channel is ActionChannel.BASIC_ATTACK:
            triggers.add("BASIC_ATTACK_RECEIVED")
        if any(output.damage_type.value == "PHYSICAL" for output in incoming):
            triggers.add("PHYSICAL_DAMAGE_RECEIVED")
        if any(output.damage_type.value == "MAGIC" for output in incoming):
            triggers.add("MAGIC_DAMAGE_RECEIVED")
        schedule.append((event.at_ms, triggers, frozenset()))
    return schedule


def compile_item_combat_events(
    items: tuple[dict[str, Any], ...],
    champion_events: tuple[ActionEvent, ...],
    context: ParticipantContext,
    opponent_events: tuple[ActionEvent, ...] = (),
) -> ItemCombatEvents:
    """Compile supported active/on-hit programs for either participant role.

    Programs requiring unobservable combat state remain explicit blockers. Current-HP
    expressions use the encounter-start snapshot and are therefore also disclosed.

    :param items: Item documents owned by the participant.
    :param champion_events: Owner action schedule after CC cancellation.
    :param context: Role binding and participant snapshots.
    :param opponent_events: Opponent schedule used by defensive triggers.
    :return: Generated item events and all unresolved-context blockers.
    """
    programs = tuple(program for item in items for program in item.get("__effect_programs", ()))
    states = {program["id"]: initial_effect_state() for program in programs}
    events: list[ActionEvent] = []
    blockers: set[str] = set()
    schedule = _build_trigger_schedule(champion_events, context, opponent_events)

    sequence = (40_000 if context.self_entity is EntityId.ACTOR else 50_000) + (
        opponent_sequence_offset(context.self_entity)
    )
    evaluation = _evaluation_context(context)
    for program in programs:
        trigger = program["trigger"]
        if trigger in _SUPPORTED_TRIGGERS or program["id"] in _EXTERNALLY_MODELED_PROGRAM_IDS:
            continue
        blockers.add(f"ITEM_TRIGGER_NOT_CONNECTED:{program['id']}:{trigger}")
    for at_ms, triggers, flags in sorted(schedule, key=lambda value: value[0]):
        for program in programs:
            if program["trigger"] not in triggers:
                continue
            required = program.get("required_context_flag")
            if required is not None and required not in flags:
                blockers.add(f"ITEM_CONTEXT_UNAVAILABLE:{program['id']}:{required}")
                continue
            try:
                resolution = resolve_item_effect(
                    program,
                    states[program["id"]],
                    ItemEffectContext(
                        at_ms,
                        evaluation,
                        "MELEE",
                        dynamic_multipliers={"MOMENTUM_FRACTION": Decimal(1)},
                        flags=flags,
                    ),
                )
                states[program["id"]] = resolution.state
                if resolution.status is not ResolutionStatus.APPLIED:
                    continue
                generated = resolution_to_action_events(
                    resolution,
                    sequence=sequence,
                    source=context.self_entity,
                )
            except (EffectRuntimeError, ExpressionError, KeyError) as error:
                blockers.add(f"ITEM_EFFECT_CONTEXT_UNRESOLVED:{program['id']}:{error}")
                continue
            if any(
                operation.get("type") == "STAT" and operation.get("basis") == "CURRENT"
                for resolved in program["operations"]
                for operation in _walk_expression(resolved["value_expression"])
            ):
                blockers.add(f"ITEM_CURRENT_STATE_SNAPSHOT_APPROXIMATION:{program['id']}")
            bounded = tuple(event for event in generated if event.at_ms <= context.duration_ms)
            events.extend(bounded)
            sequence += len(bounded)
    return ItemCombatEvents(tuple(events), tuple(sorted(blockers)))


def _walk_expression(expression: dict[str, Any]):
    """Yield an expression tree in pre-order.

    :param expression: Root expression node.
    :return: Iterator over the root and all nested term or factor nodes.
    """
    yield expression
    for key in ("terms", "factors"):
        for child in expression.get(key, ()):
            yield from _walk_expression(child)
