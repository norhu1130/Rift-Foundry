"""Verified-fact-gated crowd-control adjustment for combat timelines."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from typing import Any

from lol_build.core.timeline import ActionChannel, ActionEvent, EntityId


class CcAdjustmentError(ValueError):
    """Raised when CC adjustment inputs are internally inconsistent."""


class CcAdjustmentStatus(StrEnum):
    """State whether crowd-control effects were calculated or remain unknown."""

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


class ResponseKind(StrEnum):
    """Classify cleanse, QSS, immunity, and duration-reduction responses."""

    CLEANSE = "CLEANSE"
    QSS = "QSS"


@dataclass(frozen=True)
class CrowdControlApplication:
    """Describe one scheduled crowd control application."""

    id: str
    mechanic_id: str
    at_ms: int
    sequence: int
    base_duration_ms: int
    affected: EntityId


@dataclass(frozen=True)
class ResponseActivation:
    """Describe one scheduled response activation."""

    id: str
    kind: ResponseKind
    at_ms: int
    sequence: int
    target: EntityId


@dataclass(frozen=True)
class DurationMultiplierWindow:
    """A pre-resolved duration multiplier; this module does not stack tenacity."""

    id: str
    start_ms: int
    end_ms: int
    target: EntityId
    multiplier: Decimal


@dataclass(frozen=True)
class ImmunityWindow:
    """Describe the timing and effect of one immunity window."""

    id: str
    start_ms: int
    end_ms: int
    target: EntityId


@dataclass(frozen=True)
class CrowdControlInterval:
    """Describe the timing and effect of one crowd control interval."""

    application_id: str
    mechanic_id: str
    affected: EntityId
    start_ms: int
    end_ms: int
    blocked_channels: tuple[ActionChannel, ...]
    ended_by: str | None


@dataclass(frozen=True)
class CcAdjustmentResult:
    """Report adjusted actions, applied intervals, uptime, or an evidence blocker."""

    status: CcAdjustmentStatus
    adjusted_events: tuple[ActionEvent, ...] | None
    intervals: tuple[CrowdControlInterval, ...] | None
    channel_uptime: Mapping[ActionChannel, Decimal] | None
    reason: str | None


def _validate_time(value: int, *, name: str, duration_ms: int, allow_end: bool = True) -> None:
    """Require an integer timestamp inside the modeled encounter.

    :param value: Millisecond timestamp or duration to validate.
    :param name: Diagnostic field name included in validation errors.
    :param duration_ms: Total modeled duration in milliseconds.
    :param allow_end: Whether an interval ending exactly at the scenario boundary is valid.
    :return: None.
    """

    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int")
    upper_ok = value <= duration_ms if allow_end else value < duration_ms
    if value < 0 or not upper_ok:
        raise CcAdjustmentError(f"{name} is outside the timeline")


def _verified_value(fact: Mapping[str, Any], key: str) -> bool:
    """Read a mechanic value only when its evidence is verified.

    :param fact: Mechanic fact whose evidence status is being resolved.
    :param key: Interaction name under the mechanic's ``interactions`` mapping.
    :return: Verified boolean interaction value.
    """

    interaction = fact.get("interactions", {}).get(key)
    if not isinstance(interaction, Mapping):
        raise CcAdjustmentError(f"missing interaction {key!r}")
    if interaction.get("status") != "VERIFIED" or not isinstance(interaction.get("value"), bool):
        raise CcAdjustmentError(f"interaction {key!r} is not verified")
    return interaction["value"]


def _unknown(reason: str) -> CcAdjustmentResult:
    """Build an unknown crowd-control result with one blocker.

    :param reason: Blocker explanation recorded when a value cannot be verified.
    :return: Non-numeric result that preserves the unresolved evidence reason.
    """

    return CcAdjustmentResult(CcAdjustmentStatus.UNKNOWN, None, None, None, reason)


def _union_duration(intervals: list[tuple[int, int]]) -> int:
    """Measure the union of possibly overlapping time intervals.

    :param intervals: Time intervals whose overlapping duration must be unioned.
    :return: Total milliseconds covered by at least one interval.
    """

    if not intervals:
        return 0
    total = 0
    current_start, current_end = sorted(intervals)[0]
    for start, end in sorted(intervals)[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
        else:
            total += current_end - current_start
            current_start, current_end = start, end
    return total + current_end - current_start


def adjust_for_crowd_control(
    *,
    duration_ms: int,
    events: tuple[ActionEvent, ...],
    applications: tuple[CrowdControlApplication, ...],
    mechanic_facts: Mapping[str, Mapping[str, Any]],
    responses: tuple[ResponseActivation, ...] = (),
    duration_windows: tuple[DurationMultiplierWindow, ...] = (),
    immunity_windows: tuple[ImmunityWindow, ...] = (),
    uptime_entity: EntityId = EntityId.ACTOR,
) -> CcAdjustmentResult:
    """Cancel actions blocked by verified CC intervals and report channel uptime.

    Unknown mechanic facts return an explicit unknown result with no adjusted
    events or numeric uptime. Duration multipliers must already be resolved by a
    separately verified stacking rule.

    :param duration_ms: Total modeled duration in milliseconds.
    :param events: Chronological combat events consumed by the simulation.
    :param applications: Scheduled crowd-control effects applied during the scenario.
    :param mechanic_facts: Verified and unverified mechanic records required by the scenario.
    :param responses: Cleanse, immunity, or tenacity responses available to the participant.
    :param duration_windows: Verified base-duration records keyed by CC identifier.
    :param immunity_windows: Intervals during which matching crowd control cannot apply.
    :param uptime_entity: Participant whose actionable uptime is being measured.
    :return: Adjusted events, applied CC intervals, and per-channel actionable uptime.
    """

    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int):
        raise TypeError("duration_ms must be int")
    if duration_ms <= 0:
        raise CcAdjustmentError("duration_ms must be positive")

    for application in applications:
        _validate_time(
            application.at_ms,
            name=f"application {application.id}.at_ms",
            duration_ms=duration_ms,
            allow_end=False,
        )
        if application.base_duration_ms <= 0:
            raise CcAdjustmentError("CC base duration must be positive")
        fact = mechanic_facts.get(application.mechanic_id)
        if fact is None:
            return _unknown(f"missing mechanic fact {application.mechanic_id!r}")
        if fact.get("verification", {}).get("status") != "VERIFIED":
            return _unknown(f"mechanic fact {application.mechanic_id!r} is not VERIFIED")

    for response in responses:
        _validate_time(
            response.at_ms,
            name=f"response {response.id}.at_ms",
            duration_ms=duration_ms,
        )
    for window in duration_windows:
        _validate_time(
            window.start_ms,
            name=f"window {window.id}.start_ms",
            duration_ms=duration_ms,
        )
        _validate_time(window.end_ms, name=f"window {window.id}.end_ms", duration_ms=duration_ms)
        if window.end_ms <= window.start_ms:
            raise CcAdjustmentError("duration window end must be after start")
        if not window.multiplier.is_finite() or not Decimal(0) < window.multiplier <= Decimal(1):
            raise CcAdjustmentError("duration multiplier must be within (0, 1]")
    for window in immunity_windows:
        _validate_time(
            window.start_ms,
            name=f"immunity {window.id}.start_ms",
            duration_ms=duration_ms,
        )
        _validate_time(window.end_ms, name=f"immunity {window.id}.end_ms", duration_ms=duration_ms)
        if window.end_ms <= window.start_ms:
            raise CcAdjustmentError("immunity window end must be after start")

    intervals: list[CrowdControlInterval] = []
    for application in sorted(applications, key=lambda item: (item.at_ms, item.sequence)):
        fact = mechanic_facts[application.mechanic_id]
        try:
            immunity_resistible = _verified_value(fact, "immunity_resistible")
            tenacity_reducible = _verified_value(fact, "tenacity_reducible")
            cleanse_removable = _verified_value(fact, "cleanse_removable")
            qss_removable = _verified_value(fact, "qss_removable")
        except CcAdjustmentError as error:
            return _unknown(str(error))

        immune = any(
            window.target is application.affected
            and window.start_ms <= application.at_ms < window.end_ms
            for window in immunity_windows
        )
        if immune and immunity_resistible:
            continue

        active_multipliers = [
            window
            for window in duration_windows
            if window.target is application.affected
            and window.start_ms <= application.at_ms < window.end_ms
        ]
        if len(active_multipliers) > 1:
            raise CcAdjustmentError(
                "overlapping duration multipliers require an upstream verified stacking rule"
            )
        multiplier = (
            active_multipliers[0].multiplier
            if tenacity_reducible and active_multipliers
            else Decimal(1)
        )
        effective_duration = int(
            (Decimal(application.base_duration_ms) * multiplier).to_integral_value()
        )
        end_ms = min(duration_ms, application.at_ms + effective_duration)
        ended_by: str | None = None

        for response in sorted(responses, key=lambda item: (item.at_ms, item.sequence)):
            if response.target is not application.affected:
                continue
            if (response.at_ms, response.sequence) <= (application.at_ms, application.sequence):
                continue
            if response.at_ms >= end_ms:
                continue
            removable = (
                cleanse_removable if response.kind is ResponseKind.CLEANSE else qss_removable
            )
            if removable:
                end_ms = response.at_ms
                ended_by = response.id
                break

        try:
            blocked_channels = tuple(ActionChannel(value) for value in fact["blocked_channels"])
        except (KeyError, TypeError, ValueError) as error:
            raise CcAdjustmentError("invalid blocked_channels in mechanic fact") from error
        intervals.append(
            CrowdControlInterval(
                application.id,
                application.mechanic_id,
                application.affected,
                application.at_ms,
                end_ms,
                blocked_channels,
                ended_by,
            )
        )

    adjusted_events: list[ActionEvent] = []
    for event in events:
        blockers = [
            interval
            for interval in intervals
            if interval.affected is event.source
            and interval.start_ms <= event.at_ms < interval.end_ms
            and event.channel in interval.blocked_channels
        ]
        if blockers and not event.cancelled:
            ids = ",".join(interval.application_id for interval in blockers)
            adjusted_events.append(
                replace(event, cancelled=True, cancellation_reason=f"CC_BLOCKED:{ids}")
            )
        else:
            adjusted_events.append(event)

    uptime: dict[ActionChannel, Decimal] = {}
    for channel in ActionChannel:
        blocked = _union_duration(
            [
                (interval.start_ms, interval.end_ms)
                for interval in intervals
                if interval.affected is uptime_entity and channel in interval.blocked_channels
            ]
        )
        uptime[channel] = Decimal(duration_ms - blocked) / Decimal(duration_ms)

    return CcAdjustmentResult(
        CcAdjustmentStatus.KNOWN,
        tuple(adjusted_events),
        tuple(intervals),
        uptime,
        None,
    )
