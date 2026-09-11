"""Tenacity stacks multiplicatively within a group and additively across groups."""

from decimal import Decimal

from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    Combatant,
    EntityId,
    StatModifierOutput,
    StatusOutput,
    simulate_timeline,
)


def _stun_end_ms(item_tenacity: str, ability_tenacity: str) -> str:
    """Stun a champion holding item and ability tenacity and read the stun's end.

    :param item_tenacity: Static item tenacity on the champion.
    :param ability_tenacity: Tenacity granted by a champion ability.
    :return: The logged stun detail naming its adjusted end time.
    """
    actor = Combatant(
        EntityId.ACTOR,
        max_hp=Decimal(1000),
        current_hp=Decimal(1000),
        armor=Decimal(0),
        magic_resistance=Decimal(0),
        tenacity=Decimal(item_tenacity),
    )
    target = Combatant(
        EntityId.TARGET,
        max_hp=Decimal(1000),
        current_hp=Decimal(1000),
        armor=Decimal(0),
        magic_resistance=Decimal(0),
    )
    events = (
        ActionEvent(
            "ability_tenacity",
            0,
            1,
            EntityId.ACTOR,
            ActionChannel.ABILITY,
            (
                StatModifierOutput(
                    EntityId.ACTOR, "TENACITY_PERCENT", Decimal(ability_tenacity), None
                ),
            ),
        ),
        ActionEvent(
            "stun",
            100,
            2,
            EntityId.TARGET,
            ActionChannel.ABILITY,
            (StatusOutput(EntityId.ACTOR, "CC_STUN", 1000),),
        ),
    )
    result = simulate_timeline(
        duration_ms=2000, horizon_ms=2000, actor=actor, target=target, events=events
    )
    return next(entry.detail for entry in result.log if entry.event_id == "stun")


def test_item_and_ability_tenacity_groups_add() -> None:
    """30% item plus 30% ability tenacity is 60%, so a 1 s stun lasts 400 ms."""
    assert _stun_end_ms("0.30", "0.30").startswith("CC_STUN:500")


def test_a_single_group_is_unchanged() -> None:
    """With only item tenacity the stun shortens by exactly that fraction."""
    assert _stun_end_ms("0.30", "0").startswith("CC_STUN:800")
