"""Shared deterministic runtime for declarative passive and active item effects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from lol_build.core.combat import DamageType
from lol_build.core.expression import EvaluationContext, evaluate
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    DamageOutput,
    EntityId,
    EventOutput,
    ExecuteOutput,
    HealOutput,
    RemoveStatusOutput,
    ReviveOutput,
    ShieldOutput,
    StatModifierOutput,
    StatusOutput,
)


class EffectRuntimeError(ValueError):
    """Raised when an item effect invocation violates its contract."""


class ResolutionStatus(StrEnum):
    """Describe why a triggered item program did or did not emit operations."""

    APPLIED = "APPLIED"
    COOLDOWN = "COOLDOWN"
    CONDITION_NOT_MET = "CONDITION_NOT_MET"
    ACCUMULATING = "ACCUMULATING"


@dataclass(frozen=True)
class ItemEffectContext:
    """Provide deterministic runtime inputs for one item trigger."""

    at_ms: int
    evaluation: EvaluationContext
    range_class: str
    champions_hit: int = 1
    dynamic_multipliers: Mapping[str, Decimal] | None = None
    flags: frozenset[str] = frozenset()


@dataclass(frozen=True)
class EffectRuntimeState:
    """Persist cooldown, stack, and trigger-count state between invocations."""

    cooldown_ready_at_ms: Mapping[str, int]
    stacks: Mapping[str, int]
    stack_expires_at_ms: Mapping[str, int]
    trigger_counts: Mapping[str, int]
    count_expires_at_ms: Mapping[str, int]


@dataclass(frozen=True)
class ResolvedOperation:
    """Represent one numeric item operation after expression evaluation."""

    kind: str
    target: str
    amount: Decimal
    damage_type: DamageType | None
    absorbs_damage_types: tuple[DamageType, ...]
    status_or_stat: str | None
    start_ms: int
    end_ms: int | None
    decay: str
    decay_starts_at_ms: int | None
    excludes_primary_target: bool
    repeat_interval_ms: int | None


@dataclass(frozen=True)
class EffectResolution:
    """Contain resolved operations, updated state, and an optional blocker."""

    status: ResolutionStatus
    program_id: str
    operations: tuple[ResolvedOperation, ...]
    state: EffectRuntimeState
    blocker: str | None


def initial_effect_state() -> EffectRuntimeState:
    """Create an empty immutable item-runtime state.

    :return: State with no cooldowns, stacks, or trigger counts.
    """
    return EffectRuntimeState({}, {}, {}, {}, {})


def _updated_state(
    *,
    cooldowns: Mapping[str, int],
    stacks: Mapping[str, int],
    stack_expirations: Mapping[str, int],
    counts: Mapping[str, int],
    count_expirations: Mapping[str, int],
) -> EffectRuntimeState:
    """Copy mutable working maps into an immutable runtime state.

    :param cooldowns: Program IDs mapped to their next eligible trigger timestamp.
    :param stacks: Program IDs mapped to their current stack count.
    :param stack_expirations: Program IDs mapped to stack-expiration timestamps.
    :param counts: Program IDs mapped to accumulated trigger counts.
    :param count_expirations: Program IDs mapped to trigger-count expiration timestamps.
    :return: Defensive copies of the working maps as the next immutable state.
    """

    return EffectRuntimeState(
        dict(cooldowns),
        dict(stacks),
        dict(stack_expirations),
        dict(counts),
        dict(count_expirations),
    )


def resolve_item_effect(
    program: Mapping[str, Any],
    state: EffectRuntimeState,
    context: ItemEffectContext,
) -> EffectResolution:
    """Resolve one already-triggered program and update its runtime state.

    :param program: Validated declarative effect program.
    :param state: State produced by the preceding invocation.
    :param context: Timestamp, stats, range class, and condition flags.
    :return: Resolution containing operations and updated state.
    :raises EffectRuntimeError: If the invocation contract is invalid.
    """
    if context.at_ms < 0:
        raise EffectRuntimeError("at_ms must be non-negative")
    if context.range_class not in {"MELEE", "RANGED"}:
        raise EffectRuntimeError("range_class must be MELEE or RANGED")
    if context.champions_hit < 0:
        raise EffectRuntimeError("champions_hit must be non-negative")
    program_id = program["id"]
    ready_at = state.cooldown_ready_at_ms.get(program_id, 0)
    if context.at_ms < ready_at:
        return EffectResolution(
            ResolutionStatus.COOLDOWN,
            program_id,
            (),
            state,
            f"ITEM_EFFECT_ON_COOLDOWN:{program_id}:{ready_at}",
        )

    required_flag = program.get("required_context_flag")
    if required_flag is not None and required_flag not in context.flags:
        return EffectResolution(
            ResolutionStatus.CONDITION_NOT_MET,
            program_id,
            (),
            state,
            f"ITEM_EFFECT_CONDITION_NOT_MET:{program_id}:{required_flag}",
        )

    cooldowns = dict(state.cooldown_ready_at_ms)
    stacks = dict(state.stacks)
    stack_expirations = dict(state.stack_expires_at_ms)
    counts = dict(state.trigger_counts)
    count_expirations = dict(state.count_expires_at_ms)
    if context.at_ms >= stack_expirations.get(program_id, context.at_ms + 1):
        stacks.pop(program_id, None)
        stack_expirations.pop(program_id, None)

    proc_every = program.get("proc_every")
    if proc_every is not None:
        if context.at_ms >= count_expirations.get(program_id, context.at_ms + 1):
            counts.pop(program_id, None)
            count_expirations.pop(program_id, None)
        count = counts.get(program_id, 0) + 1
        if count < proc_every:
            counts[program_id] = count
            counts_window = program.get("counting_window_ms")
            if counts_window is not None:
                count_expirations[program_id] = context.at_ms + counts_window
            return EffectResolution(
                ResolutionStatus.ACCUMULATING,
                program_id,
                (),
                _updated_state(
                    cooldowns=cooldowns,
                    stacks=stacks,
                    stack_expirations=stack_expirations,
                    counts=counts,
                    count_expirations=count_expirations,
                ),
                None,
            )
        counts.pop(program_id, None)
        count_expirations.pop(program_id, None)

    stacking = program.get("stacking")
    if stacking is not None:
        stacks[program_id] = min(
            stacking["max_stacks"],
            stacks.get(program_id, 0) + stacking["stacks_per_trigger"],
        )
        stack_expirations[program_id] = context.at_ms + stacking["duration_ms"]

    resolved: list[ResolvedOperation] = []
    for operation in program["operations"]:
        amount = evaluate(operation["value_expression"], context.evaluation)
        range_multipliers = operation.get("range_multipliers", {})
        amount *= Decimal(range_multipliers.get(context.range_class, "1"))
        if operation.get("multiply_by_targets_hit", False):
            amount *= context.champions_hit
        if operation.get("multiply_by_current_stacks", False):
            amount *= stacks.get(program_id, 0)
        multiplier_name = operation.get("context_multiplier")
        if multiplier_name is not None:
            multipliers = context.dynamic_multipliers or {}
            if multiplier_name not in multipliers:
                raise EffectRuntimeError(f"missing dynamic multiplier for {multiplier_name}")
            multiplier = multipliers[multiplier_name]
            if not multiplier.is_finite() or multiplier < 0:
                raise EffectRuntimeError(
                    f"dynamic multiplier {multiplier_name} must be non-negative"
                )
            amount *= multiplier
        range_durations = operation.get("range_durations_ms", {})
        duration = range_durations.get(context.range_class, operation.get("duration_ms"))
        operation_start = context.at_ms + operation.get("delay_ms", 0)
        decay = operation.get("decay", "NONE")
        damage_type = operation.get("damage_type")
        resolved.append(
            ResolvedOperation(
                operation["kind"],
                operation["target"],
                amount,
                DamageType(damage_type) if damage_type is not None else None,
                tuple(DamageType(value) for value in operation.get("absorbs_damage_types", ())),
                operation.get("status_or_stat"),
                operation_start,
                operation_start + duration if duration is not None else None,
                decay,
                operation_start + operation.get("decay_delay_ms", 0) if decay != "NONE" else None,
                operation.get("excludes_primary_target", False),
                operation.get("repeat_interval_ms"),
            )
        )
    cooldowns[program_id] = context.at_ms + program.get("cooldown_ms", 0)
    return EffectResolution(
        ResolutionStatus.APPLIED,
        program_id,
        tuple(resolved),
        _updated_state(
            cooldowns=cooldowns,
            stacks=stacks,
            stack_expirations=stack_expirations,
            counts=counts,
            count_expirations=count_expirations,
        ),
        None,
    )


def resolution_to_action_event(
    resolution: EffectResolution,
    *,
    sequence: int,
    source: EntityId = EntityId.ACTOR,
) -> ActionEvent | None:
    """Compile a single-time effect resolution into one combat event.

    :param resolution: Applied or skipped item effect resolution.
    :param sequence: Stable timeline tie-break sequence.
    :param source: Participant that owns the item.
    :return: One event, or ``None`` when no operation was applied.
    :raises EffectRuntimeError: If operations use multiple timestamps.
    """
    events = resolution_to_action_events(resolution, sequence=sequence, source=source)
    if len(events) > 1:
        raise EffectRuntimeError("resolution contains operations at different times")
    return events[0] if events else None


def resolution_to_action_events(
    resolution: EffectResolution,
    *,
    sequence: int,
    source: EntityId = EntityId.ACTOR,
) -> tuple[ActionEvent, ...]:
    """Compile a resolution into deterministic events grouped by execution time.

    :param resolution: Applied or skipped item effect resolution.
    :param sequence: First stable timeline tie-break sequence.
    :param source: Participant that owns the item.
    :return: Chronological item action events.
    :raises EffectRuntimeError: If an operation lacks required output metadata.
    """
    if resolution.status is not ResolutionStatus.APPLIED:
        return ()
    outputs_by_time: dict[int, list[EventOutput]] = {}
    for operation in resolution.operations:
        if operation.target == "NEARBY_ENEMIES" and operation.excludes_primary_target:
            continue
        self_targets = {"SELF", "ALLY_TARGET", "SELF_AND_NEARBY_ALLIES", "AREA_ALLIES"}
        recipient = (
            source
            if operation.target in self_targets
            else (EntityId.TARGET if source is EntityId.ACTOR else EntityId.ACTOR)
        )
        output: EventOutput | None = None
        if operation.kind == "DAMAGE":
            if operation.damage_type is None:
                raise EffectRuntimeError("damage operation requires damage_type")
            output = DamageOutput(recipient, operation.amount, operation.damage_type)
        elif operation.kind == "HEAL":
            output = HealOutput(recipient, operation.amount)
        elif operation.kind == "SHIELD":
            output = ShieldOutput(
                recipient,
                operation.amount,
                operation.end_ms - operation.start_ms if operation.end_ms is not None else None,
                operation.absorbs_damage_types,
                operation.decay_starts_at_ms - operation.start_ms
                if operation.decay_starts_at_ms is not None
                else None,
            )
        elif operation.kind == "APPLY_STATUS":
            if operation.status_or_stat is None or operation.end_ms is None:
                raise EffectRuntimeError("status operation requires status and duration")
            output = StatusOutput(
                recipient,
                operation.status_or_stat,
                operation.end_ms - operation.start_ms,
                operation.amount,
            )
        elif operation.kind == "REMOVE_STATUS":
            if operation.status_or_stat is None:
                raise EffectRuntimeError("remove-status operation requires group")
            output = RemoveStatusOutput(recipient, operation.status_or_stat)
        elif operation.kind == "REVIVE":
            output = ReviveOutput(recipient, operation.amount)
        elif operation.kind in {"GRANT_STAT", "DAMAGE_MODIFIER"}:
            if operation.status_or_stat is None:
                raise EffectRuntimeError("stat modifier operation requires a stat")
            output = StatModifierOutput(
                recipient,
                operation.status_or_stat,
                operation.amount,
                operation.end_ms - operation.start_ms if operation.end_ms is not None else None,
            )
        elif operation.kind == "EXECUTE":
            output = ExecuteOutput(recipient, operation.amount)
        if output is not None:
            if operation.repeat_interval_ms is None:
                execution_times = (operation.start_ms,)
            elif operation.end_ms is None:
                raise EffectRuntimeError("repeating operation requires duration")
            else:
                execution_times = tuple(
                    range(
                        operation.start_ms + operation.repeat_interval_ms,
                        operation.end_ms + 1,
                        operation.repeat_interval_ms,
                    )
                )
            for execution_time in execution_times:
                outputs_by_time.setdefault(execution_time, []).append(output)
    ordered_times = sorted(outputs_by_time)
    return tuple(
        ActionEvent(
            resolution.program_id
            if len(ordered_times) == 1
            else f"{resolution.program_id}:{at_ms}",
            at_ms,
            sequence + index,
            source,
            ActionChannel.ITEM_ACTIVE,
            tuple(outputs_by_time[at_ms]),
            requires_living_opponent=any(
                output.recipient is not source for output in outputs_by_time[at_ms]
            ),
            requires_source_alive=not any(
                isinstance(output, ReviveOutput) for output in outputs_by_time[at_ms]
            ),
        )
        for index, at_ms in enumerate(ordered_times)
    )
