"""Deterministic build-timing, sustain, and engagement calculations.

These calculations deliberately consume explicit scenario assumptions.  They do
not infer how often a player trades, recalls, or reaches a Heartsteel target.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class HeartsteelProgression:
    """Contain deterministic proc count and health gained after purchase."""

    proc_count: int
    bonus_health: Decimal


@dataclass(frozen=True)
class LaneSustainResult:
    """Contain recovery capacity over one explicit lane window."""

    recovered_health: Decimal
    ending_health: Decimal
    warmog_ready: bool


@dataclass(frozen=True)
class EngagementResult:
    """Contain straight-line pursuit distance, contact, and combat uptime."""

    distance_closed: Decimal
    contact_reached: bool
    contact_time_ms: Decimal | None
    combat_uptime_fraction: Decimal


def mitigated_physical_damage(raw_damage: Decimal, armor: Decimal) -> Decimal:
    """Apply the ordinary non-negative armor multiplier.

    :param raw_damage: Raw physical damage.
    :param armor: Target armor, clamped to zero in this progression helper.
    :return: Post-mitigation physical damage.
    """
    return raw_damage * Decimal(100) / (Decimal(100) + max(armor, Decimal(0)))


def simulate_heartsteel_progression(
    *,
    purchase_ms: int | None,
    evaluation_ms: int,
    first_proc_delay_ms: int,
    proc_interval_ms: int,
    base_max_health_at_purchase: Decimal,
    target_armor: Decimal,
    base_damage: Decimal = Decimal(70),
    max_health_ratio: Decimal = Decimal("0.06"),
    health_gain_ratio: Decimal = Decimal("0.10"),
) -> HeartsteelProgression:
    """Simulate explicit single-target proc opportunities through a snapshot.

    The opportunity cadence is a fixture assumption, while the proc formula is
    sourced from the locked item program.  Health gain uses post-mitigation
    damage because that is the current curated-but-unverified mechanic status.

    :param purchase_ms: Item completion time, or ``None`` when not purchased.
    :param evaluation_ms: Progression snapshot timestamp.
    :param first_proc_delay_ms: Delay from purchase to the first proc.
    :param proc_interval_ms: Assumed interval between later proc opportunities.
    :param base_max_health_at_purchase: Owner maximum health at completion.
    :param target_armor: Benchmark target armor.
    :param base_damage: Proc base damage.
    :param max_health_ratio: Owner-health damage coefficient.
    :param health_gain_ratio: Post-mitigation damage converted to permanent health.
    :return: Proc count and accumulated health.
    :raises ValueError: If ``proc_interval_ms`` is not positive.
    """
    if purchase_ms is None or evaluation_ms < purchase_ms + first_proc_delay_ms:
        return HeartsteelProgression(0, Decimal(0))
    if proc_interval_ms <= 0:
        raise ValueError("Heartsteel proc interval must be positive")
    count = 1 + (evaluation_ms - purchase_ms - first_proc_delay_ms) // proc_interval_ms
    gained = Decimal(0)
    for _ in range(count):
        raw = base_damage + max_health_ratio * (base_max_health_at_purchase + gained)
        gained += health_gain_ratio * mitigated_physical_damage(raw, target_armor)
    return HeartsteelProgression(count, gained)


def warmog_heart_ready(bonus_health: Decimal, threshold: Decimal = Decimal(2000)) -> bool:
    """Check the explicit Warmog's Heart bonus-health requirement.

    :param bonus_health: Current bonus health from items and progression.
    :param threshold: Required bonus-health threshold.
    :return: Whether the passive is available.
    """
    return bonus_health >= threshold


def simulate_lane_sustain(
    *,
    max_health: Decimal,
    starting_health_fraction: Decimal,
    duration_ms: int,
    base_health_regen_per_second: Decimal,
    base_health_regen_bonus: Decimal,
    total_attack_damage: Decimal,
    lifesteal: Decimal,
    minion_attacks: int,
    warmog_ready: bool,
    warmog_no_damage_delay_ms: int = 8000,
    warmog_heal_fraction_per_second: Decimal = Decimal("0.03"),
) -> LaneSustainResult:
    """Evaluate a no-champion-damage lane recovery window.

    Basic attacks are deterministic fixture opportunities.  No minion armor is
    assumed, making this a recovery-capacity metric rather than a lane replay.

    :param max_health: Champion maximum health.
    :param starting_health_fraction: Health fraction at window start.
    :param duration_ms: Recovery window duration.
    :param base_health_regen_per_second: Champion base regeneration rate.
    :param base_health_regen_bonus: Item multiplier applied to base regeneration.
    :param total_attack_damage: Damage used for deterministic minion attacks.
    :param lifesteal: Fraction of attack damage restored.
    :param minion_attacks: Number of assumed minion attacks.
    :param warmog_ready: Whether Warmog's conditional passive is available.
    :param warmog_no_damage_delay_ms: Delay before Warmog recovery begins.
    :param warmog_heal_fraction_per_second: Warmog maximum-health recovery rate.
    :return: Recovered and ending health plus passive readiness.
    """
    duration_seconds = Decimal(duration_ms) / Decimal(1000)
    starting = max_health * starting_health_fraction
    ordinary_regen = (
        base_health_regen_per_second * (Decimal(1) + base_health_regen_bonus) * duration_seconds
    )
    attack_healing = total_attack_damage * lifesteal * Decimal(minion_attacks)
    warmog_seconds = max(
        Decimal(0),
        Decimal(duration_ms - warmog_no_damage_delay_ms) / Decimal(1000),
    )
    warmog_healing = (
        max_health * warmog_heal_fraction_per_second * warmog_seconds
        if warmog_ready
        else Decimal(0)
    )
    recovered = min(max_health - starting, ordinary_regen + attack_healing + warmog_healing)
    return LaneSustainResult(recovered, starting + recovered, warmog_ready)


def movement_speed(raw_speed: Decimal) -> Decimal:
    """Apply League's positive movement-speed soft caps.

    :param raw_speed: Movement speed before positive soft caps.
    :return: Effective movement speed.
    """
    if raw_speed > Decimal(490):
        return raw_speed * Decimal("0.5") + Decimal(230)
    if raw_speed > Decimal(415):
        return raw_speed * Decimal("0.8") + Decimal(83)
    return raw_speed


def simulate_engagement(
    *,
    initial_center_distance: Decimal,
    actor_attack_range: Decimal,
    actor_move_speed: Decimal,
    target_move_speed: Decimal,
    window_ms: int,
    actor_speed_multiplier: Decimal = Decimal(1),
    target_slow_fraction: Decimal = Decimal(0),
    actor_dash_distance: Decimal = Decimal(0),
) -> EngagementResult:
    """Run a deterministic straight-line pursuit benchmark.

    :param initial_center_distance: Starting center-to-center separation.
    :param actor_attack_range: Range at which the actor reaches contact.
    :param actor_move_speed: Actor movement speed before kit multipliers.
    :param target_move_speed: Fleeing target movement speed.
    :param window_ms: Maximum pursuit duration.
    :param actor_speed_multiplier: Champion/item pursuit multiplier.
    :param target_slow_fraction: Slow applied to the target.
    :param actor_dash_distance: Immediate displacement toward the target.
    :return: Distance closed, contact time, and usable combat fraction.
    """
    required = max(Decimal(0), initial_center_distance - actor_attack_range - actor_dash_distance)
    actor = movement_speed(actor_move_speed * actor_speed_multiplier)
    target = movement_speed(target_move_speed * (Decimal(1) - target_slow_fraction))
    closing_per_second = max(Decimal(0), actor - target)
    window_seconds = Decimal(window_ms) / Decimal(1000)
    possible = closing_per_second * window_seconds
    closed = min(required, possible)
    reached = required == 0 or closing_per_second > 0 and possible >= required
    if required == 0:
        contact_ms: Decimal | None = Decimal(0)
    elif reached:
        contact_ms = required / closing_per_second * Decimal(1000)
    else:
        contact_ms = None
    uptime = (
        max(Decimal(0), Decimal(window_ms) - contact_ms) / Decimal(window_ms)
        if contact_ms is not None
        else Decimal(0)
    )
    return EngagementResult(closed, reached, contact_ms, uptime)
