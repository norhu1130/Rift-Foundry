from decimal import Decimal

from lol_build.items.progression import (
    movement_speed,
    simulate_engagement,
    simulate_heartsteel_progression,
    simulate_lane_sustain,
    warmog_heart_ready,
)


def test_heartsteel_bought_earlier_accumulates_more_health() -> None:
    first = simulate_heartsteel_progression(
        purchase_ms=600_000,
        evaluation_ms=1_800_000,
        first_proc_delay_ms=30_000,
        proc_interval_ms=60_000,
        base_max_health_at_purchase=Decimal(3000),
        target_armor=Decimal(100),
    )
    third = simulate_heartsteel_progression(
        purchase_ms=1_440_000,
        evaluation_ms=1_800_000,
        first_proc_delay_ms=30_000,
        proc_interval_ms=60_000,
        base_max_health_at_purchase=Decimal(3000),
        target_armor=Decimal(100),
    )

    assert first.proc_count == 20
    assert third.proc_count == 6
    assert first.bonus_health > third.bonus_health


def test_warmog_is_dormant_until_bonus_health_threshold() -> None:
    assert warmog_heart_ready(Decimal(1999)) is False
    assert warmog_heart_ready(Decimal(2000)) is True


def test_ready_warmog_changes_lane_recovery_but_not_maximum_health() -> None:
    dormant = simulate_lane_sustain(
        max_health=Decimal(4000),
        starting_health_fraction=Decimal("0.5"),
        duration_ms=30_000,
        base_health_regen_per_second=Decimal(4),
        base_health_regen_bonus=Decimal(1),
        total_attack_damage=Decimal(150),
        lifesteal=Decimal(0),
        minion_attacks=6,
        warmog_ready=False,
    )
    ready = simulate_lane_sustain(
        max_health=Decimal(4000),
        starting_health_fraction=Decimal("0.5"),
        duration_ms=30_000,
        base_health_regen_per_second=Decimal(4),
        base_health_regen_bonus=Decimal(1),
        total_attack_damage=Decimal(150),
        lifesteal=Decimal(0),
        minion_attacks=6,
        warmog_ready=True,
    )

    assert dormant.ending_health == Decimal(2240)
    assert ready.ending_health == Decimal(4000)


def test_engagement_reports_failure_and_reached_contact() -> None:
    failed = simulate_engagement(
        initial_center_distance=Decimal(400),
        actor_attack_range=Decimal(175),
        actor_move_speed=Decimal(340),
        target_move_speed=Decimal(340),
        window_ms=3000,
    )
    reached = simulate_engagement(
        initial_center_distance=Decimal(400),
        actor_attack_range=Decimal(175),
        actor_move_speed=Decimal(390),
        target_move_speed=Decimal(300),
        window_ms=3000,
    )

    assert failed.contact_reached is False
    assert failed.combat_uptime_fraction == 0
    assert reached.contact_reached is True
    assert reached.contact_time_ms == Decimal(2500)
    assert movement_speed(Decimal(500)) == Decimal(480)


def test_dash_reduces_distance_before_pursuit() -> None:
    result = simulate_engagement(
        initial_center_distance=Decimal(400),
        actor_attack_range=Decimal(175),
        actor_move_speed=Decimal(340),
        target_move_speed=Decimal(340),
        window_ms=3000,
        actor_dash_distance=Decimal(275),
    )

    assert result.contact_reached is True
    assert result.contact_time_ms == 0
