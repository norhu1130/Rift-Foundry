"""Cast-blocking control stops new casts, not spells already in flight."""

from decimal import Decimal

from lol_build.application.matchup import _apply_cast_blocks
from lol_build.cogs import CastBlockWindow
from lol_build.cogs.mechanics import action, damage
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, EntityId

SILENCE = CastBlockWindow("silence", 500, 1500, (ActionChannel.ABILITY,))


def _schedule(throw_at_ms: int) -> tuple:
    """Build a boomerang throw and its return 800 ms later.

    :param throw_at_ms: When the throw is cast.
    :return: The throw and its continuation, in order.
    """
    throw = action(
        "THROW",
        at_ms=throw_at_ms,
        sequence=1,
        source=EntityId.ACTOR,
        channel=ActionChannel.ABILITY,
        outputs=(damage(EntityId.TARGET, Decimal(100), DamageType.PHYSICAL),),
    )
    returning = action(
        "RETURN",
        at_ms=throw_at_ms + 800,
        sequence=2,
        source=EntityId.ACTOR,
        channel=ActionChannel.ABILITY,
        outputs=(damage(EntityId.TARGET, Decimal(100), DamageType.PHYSICAL),),
        origin_event_id="THROW",
    )
    return (throw, returning)


def test_a_continuation_inside_the_window_resolves_when_its_cast_did() -> None:
    """A blade thrown before the silence still returns during it."""
    throw, returning = _apply_cast_blocks(_schedule(throw_at_ms=200), (SILENCE,))

    assert not throw.cancelled
    assert returning.at_ms == 1000
    assert not returning.cancelled


def test_a_continuation_is_cancelled_with_its_cast() -> None:
    """A throw the silence prevents never returns, even after the window ends."""
    throw, returning = _apply_cast_blocks(_schedule(throw_at_ms=600), (SILENCE,))

    assert throw.cancelled
    assert throw.cancellation_reason == "OPPONENT_CAST_BLOCK:silence"
    assert returning.at_ms == 1400
    assert returning.cancelled
    assert returning.cancellation_reason == "ORIGIN_CAST_CANCELLED:THROW"


def test_an_unmarked_event_keeps_the_original_window_rule() -> None:
    """Events without an origin are judged by the window alone, as before."""
    throw, returning = _schedule(throw_at_ms=200)
    unmarked = action(
        "LATE_CAST",
        at_ms=1000,
        sequence=3,
        source=EntityId.ACTOR,
        channel=ActionChannel.ABILITY,
        outputs=(damage(EntityId.TARGET, Decimal(100), DamageType.PHYSICAL),),
    )

    _, _, late = _apply_cast_blocks((throw, returning, unmarked), (SILENCE,))

    assert late.cancelled
    assert late.cancellation_reason == "OPPONENT_CAST_BLOCK:silence"
