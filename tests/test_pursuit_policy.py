"""Pursuit and item-active assumptions must be explicit and bounded."""

from decimal import Decimal
from pathlib import Path

import pytest

from lol_build.application.cog_preview import (
    PURSUIT_TARGET_POLICIES,
    _fleeing_move_speed,
    _stage_noncombat_metrics,
)
from lol_build.application.item_combat import (
    ACTIVE_DUTY_POLICIES,
    _active_duty_factor,
    item_engagement_modifiers,
)
from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import ParticipantContext
from lol_build.core.timeline import EntityId

ROOT = Path(__file__).resolve().parents[1]
MELEE = Decimal(175)
RANGED = Decimal(550)
SPEED = Decimal(340)


def test_reach_decides_whether_a_target_retreats() -> None:
    """Let an opponent kite only when its reach rewards kiting."""
    assert _fleeing_move_speed(MELEE, RANGED, SPEED, "range_aware") == SPEED
    # A target that does not outrange the actor has to close to fight, so it
    # advances instead of waiting (a negative retreat speed).
    assert _fleeing_move_speed(MELEE, MELEE, SPEED, "range_aware") == -SPEED
    assert _fleeing_move_speed(RANGED, MELEE, SPEED, "range_aware") == -SPEED


def test_the_other_pursuit_policies_stay_available_and_unambiguous() -> None:
    """Keep both fixed readings selectable for comparison."""
    assert _fleeing_move_speed(MELEE, MELEE, SPEED, "always_flees") == SPEED
    assert _fleeing_move_speed(MELEE, RANGED, SPEED, "stands_ground") == 0
    assert set(PURSUIT_TARGET_POLICIES) == {"range_aware", "always_flees", "stands_ground"}
    with pytest.raises(ValueError):
        _fleeing_move_speed(MELEE, MELEE, SPEED, "sprint")


def test_a_short_active_on_a_long_cooldown_is_not_credited_in_full() -> None:
    """Scale an active by how long it lasts rather than treating it as permanent."""
    program = {"cooldown_ms": 90_000}
    operation = {"duration_ms": 2_000}

    assert _active_duty_factor(program, operation, 3_000, "always_ready") == 1
    # Saved for this engagement: two seconds of a three-second window.
    assert _active_duty_factor(program, operation, 3_000, "per_engagement") == (
        Decimal(2_000) / Decimal(3_000)
    )
    # Uncorrelated with the engagement: two seconds of every ninety.
    assert _active_duty_factor(program, operation, 3_000, "uncorrelated") == (
        Decimal(2_000) / Decimal(90_000)
    )
    # An effect with no stated duration is permanent and keeps its full value.
    assert _active_duty_factor(program, {}, 3_000, "uncorrelated") == 1
    assert set(ACTIVE_DUTY_POLICIES) == {"uncorrelated", "per_engagement", "always_ready"}


def test_active_scaling_is_reported_rather_than_applied_silently() -> None:
    """Attach a blocker whenever an active's value is reduced."""
    engine = MatchupEngine(ROOT)
    cog = engine.registry.require_cog("Darius")
    snapshot = cog.snapshot(level=13)
    context = ParticipantContext(EntityId.ACTOR, EntityId.TARGET, snapshot, snapshot, 8000, 3000)
    items = tuple(engine._items[item_id] for item_id in (6631, 3742, 3139))

    scaled = item_engagement_modifiers(
        items, context, actives_available=True, active_duty_policy="per_engagement"
    )
    full = item_engagement_modifiers(
        items, context, actives_available=True, active_duty_policy="always_ready"
    )

    assert scaled.move_speed_percent < full.move_speed_percent
    assert any(value.startswith("ITEM_ACTIVE_DUTY_SCALED") for value in scaled.blockers)
    assert not [value for value in full.blockers if value.startswith("ITEM_ACTIVE_DUTY_SCALED")]
    with pytest.raises(ValueError):
        item_engagement_modifiers(
            items, context, actives_available=True, active_duty_policy="sprint"
        )


def test_a_melee_mirror_reaches_contact_without_movement_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop the engagement metric from measuring movement items alone.

    Against an equally fast melee opponent that always flees, a build with no
    movement source never makes contact, so its damage scores zero however
    strong it is. Reach-aware pursuit lets the fight happen. Yorick is used
    because his Cog credits no gap-closer, dash, or pursuit slow — a champion
    with one (Darius's Apprehend) reaches contact even against a fleeing target.
    """
    engine = MatchupEngine(ROOT)
    # Hold Yorick's kit neutral so only movement items could reach contact.
    yorick = type(engine.registry.require_cog("Yorick"))
    monkeypatch.setattr(yorick, "engagement_target_slow_fraction", lambda self, ctx: Decimal(0))
    tank = (3143, 3083, 3742)

    def uptime(policy: str) -> Decimal:
        """Measure engagement uptime for the tank build under one policy.

        :param policy: Pursuit target policy to apply.
        :return: Combat uptime fraction.
        """
        request = MatchupRequest(
            "Yorick",
            "Garen",
            opponent_item_ids=(3071, 3053, 6333),
            pursuit_target_policy=policy,
        )
        stage = _stage_noncombat_metrics(
            engine,
            request,
            tank,
            request.opponent_item_ids[:3],
            Decimal(0),
            3,
            "per_engagement",
            policy,
        )
        assert any(value.startswith("PURSUIT_TARGET_POLICY_ASSUMED") for value in stage["blockers"])
        return stage["uptime"]

    assert uptime("always_flees") == 0
    assert uptime("range_aware") > 0


def test_a_ranged_opponent_still_kites_a_melee_actor() -> None:
    """Keep kiting real where reach actually supports it."""
    engine = MatchupEngine(ROOT)
    request = MatchupRequest(
        "Darius",
        "Vayne",
        opponent_item_ids=(3153, 3006, 3072),
        pursuit_target_policy="range_aware",
    )
    build = (6631, 3742, 6333)

    kited = _stage_noncombat_metrics(
        engine,
        request,
        build,
        request.opponent_item_ids[:3],
        Decimal(0),
        3,
        "per_engagement",
        "range_aware",
    )
    fleeing = _stage_noncombat_metrics(
        engine,
        request,
        build,
        request.opponent_item_ids[:3],
        Decimal(0),
        3,
        "per_engagement",
        "always_flees",
    )

    assert kited["uptime"] == fleeing["uptime"]
