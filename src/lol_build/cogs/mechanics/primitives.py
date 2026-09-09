"""Small constructors shared by deterministic champion action models."""

from __future__ import annotations

from decimal import Decimal

from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    DamageOutput,
    EntityId,
    EventOutput,
    HealOutput,
    HealthCostOutput,
    MaxHealthModifierOutput,
    ShieldOutput,
    StatModifierOutput,
    StatusOutput,
)


def action(
    event_id: str,
    *,
    at_ms: int,
    sequence: int,
    source: EntityId,
    channel: ActionChannel,
    outputs: tuple[EventOutput, ...],
    requires_living_opponent: bool = True,
) -> ActionEvent:
    """Assemble atomic mechanic outputs into one deterministic action.

    :param event_id: Champion-scoped identifier used in timeline evidence.
    :param at_ms: Timestamp relative to the beginning of the encounter.
    :param sequence: Stable ordering key for actions sharing a timestamp.
    :param source: Participant performing the action.
    :param channel: Action category used by control cancellation rules.
    :param outputs: Atomic effects resolved together at the timestamp.
    :param requires_living_opponent: Whether opponent death cancels the action.
    :return: Immutable event accepted by the shared timeline simulator.
    """
    if at_ms < 0:
        raise ValueError("action timestamp cannot be negative")
    if not event_id:
        raise ValueError("action event_id cannot be empty")
    if not outputs:
        raise ValueError("action must contain at least one output")
    return ActionEvent(
        event_id,
        at_ms,
        sequence,
        source,
        channel,
        outputs,
        requires_living_opponent=requires_living_opponent,
    )


def damage(
    recipient: EntityId,
    amount: Decimal,
    damage_type: DamageType,
    *,
    percent_resistance_penetration: Decimal = Decimal(0),
    flat_resistance_penetration: Decimal = Decimal(0),
) -> DamageOutput:
    """Create fixed raw damage without pre-applying target resistance.

    :param recipient: Participant receiving the damage.
    :param amount: Non-negative raw damage resolved by the timeline.
    :param damage_type: Resistance channel or true-damage classification.
    :param percent_resistance_penetration: Event-local resistance fraction ignored.
    :param flat_resistance_penetration: Event-local resistance amount ignored.
    :return: Atomic damage output for an action event.
    """
    if amount < 0:
        raise ValueError("damage amount cannot be negative")
    return DamageOutput(
        recipient,
        amount,
        damage_type,
        percent_resistance_penetration,
        flat_resistance_penetration,
    )


def healing(recipient: EntityId, amount: Decimal) -> HealOutput:
    """Create a health restoration output capped by recipient maximum health.

    :param recipient: Participant whose current health should increase.
    :param amount: Non-negative health restored before the maximum-health cap.
    :return: Atomic healing output for an action event.
    """
    if amount < 0:
        raise ValueError("healing amount cannot be negative")
    return HealOutput(recipient, amount)


def health_cost(
    recipient: EntityId,
    *,
    flat_amount: Decimal = Decimal(0),
    current_health_ratio: Decimal = Decimal(0),
    health_floor: Decimal = Decimal(1),
) -> HealthCostOutput:
    """Create a non-damage health payment with an optional health floor.

    :param recipient: Participant paying the ability health cost.
    :param flat_amount: Fixed health removed before applying the floor.
    :param current_health_ratio: Fraction of current health additionally spent.
    :param health_floor: Minimum health remaining after payment.
    :return: Atomic health-cost output for the shared timeline.
    """
    return HealthCostOutput(
        recipient,
        flat_amount=flat_amount,
        current_health_ratio=current_health_ratio,
        health_floor=health_floor,
    )


def maximum_health(
    recipient: EntityId,
    amount: Decimal,
    *,
    duration_ms: int,
) -> MaxHealthModifierOutput:
    """Create a temporary grant to both maximum and current health.

    :param recipient: Participant receiving the health increase.
    :param amount: Positive maximum and current health granted immediately.
    :param duration_ms: Positive lifetime before maximum health is removed.
    :return: Atomic temporary maximum-health output.
    """
    return MaxHealthModifierOutput(recipient, amount, duration_ms)


def shielding(
    recipient: EntityId,
    amount: Decimal,
    *,
    duration_ms: int | None = None,
    damage_types: tuple[DamageType, ...] = (),
    decay_delay_ms: int | None = None,
) -> ShieldOutput:
    """Create a permanent, timed, typed, or decaying shield output.

    :param recipient: Participant receiving the shield.
    :param amount: Non-negative initial shield strength.
    :param duration_ms: Optional lifetime before the shield expires.
    :param damage_types: Empty for universal shielding or accepted damage types.
    :param decay_delay_ms: Optional delay before linear shield decay begins.
    :return: Atomic shielding output for an action event.
    """
    if amount < 0:
        raise ValueError("shield amount cannot be negative")
    if duration_ms is not None and duration_ms <= 0:
        raise ValueError("shield duration_ms must be positive")
    if decay_delay_ms is not None and decay_delay_ms < 0:
        raise ValueError("shield decay_delay_ms cannot be negative")
    return ShieldOutput(recipient, amount, duration_ms, damage_types, decay_delay_ms)


def movement_speed(
    recipient: EntityId,
    amount: Decimal,
    *,
    duration_ms: int | None = None,
) -> StatModifierOutput:
    """Create a runtime flat movement-speed modifier.

    :param recipient: Participant whose movement speed changes.
    :param amount: Signed flat movement-speed delta.
    :param duration_ms: Optional lifetime of the modifier.
    :return: Atomic movement-speed modifier for an action event.
    """
    if duration_ms is not None and duration_ms <= 0:
        raise ValueError("movement duration_ms must be positive")
    return StatModifierOutput(recipient, "MOVE_SPEED_FLAT", amount, duration_ms)


def crowd_control(
    recipient: EntityId,
    control_type: str,
    *,
    duration_ms: int,
    magnitude: Decimal = Decimal(1),
) -> StatusOutput:
    """Create a timed crowd-control status without assuming reducibility.

    Reducibility and action cancellation belong to the owning Cog's reaction
    plan because silence, displacement, and channel interruption differ.

    :param recipient: Participant receiving the control status.
    :param control_type: Uppercase control name, with or without ``CC_``.
    :param duration_ms: Positive base duration before reaction-plan adjustment.
    :param magnitude: Optional strength such as a slow fraction.
    :return: Atomic status output for an action event.
    """
    normalized = control_type.strip().upper()
    if not normalized:
        raise ValueError("control_type cannot be empty")
    if duration_ms <= 0:
        raise ValueError("crowd-control duration_ms must be positive")
    if not normalized.startswith("CC_"):
        normalized = f"CC_{normalized}"
    return StatusOutput(recipient, normalized, duration_ms, magnitude)
