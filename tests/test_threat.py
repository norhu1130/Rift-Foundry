"""Cover the position-and-role target selection policy."""

from decimal import Decimal

from lol_build.application.threat import (
    MELEE_RANGE_CEILING,
    ThreatParticipant,
    allocate_threat,
    choose_target,
    policy_blockers,
    reachable_targets,
)
from lol_build.core.timeline import EntityId


def participant(entity: EntityId, attack_range: int, *tags: str) -> ThreatParticipant:
    """Build one threat participant from plain values.

    :param entity: Timeline identity for this participant.
    :param attack_range: Attack range placing it on a line.
    :param tags: Locked role tags.
    :return: Participant description for the policy.
    """
    return ThreatParticipant(entity, Decimal(attack_range), tags)


def test_attack_range_places_a_champion_on_a_line() -> None:
    """Split front from back using the recorded attack range."""
    assert participant(EntityId.ACTOR, 175, "Fighter").is_melee
    assert participant(EntityId.ACTOR, int(MELEE_RANGE_CEILING), "Tank").is_melee
    assert not participant(EntityId.ACTOR, 550, "Marksman").is_melee


def test_role_priority_takes_the_most_valuable_tag() -> None:
    """Rank a multi-role champion by its highest-priority tag."""
    assassin_mage = participant(EntityId.TARGET, 550, "Mage", "Assassin")
    tank_support = participant(EntityId.TARGET, 125, "Tank", "Support")

    assert assassin_mage.role_priority < tank_support.role_priority
    # An unknown tag must not outrank a recognized one.
    assert participant(EntityId.TARGET, 550, "Unknown").role_priority > (tank_support.role_priority)


def test_a_melee_attacker_is_held_to_the_defending_front_line() -> None:
    """Keep melee attackers off the back line while a front line stands."""
    melee = participant(EntityId.ACTOR, 175, "Fighter")
    front = participant(EntityId.TARGET, 125, "Tank")
    back = participant(EntityId.TARGET_2, 550, "Marksman")

    assert reachable_targets(melee, (front, back)) == (front,)
    # The carry becomes reachable only once no front line remains.
    assert reachable_targets(melee, (back,)) == (back,)


def test_a_ranged_attacker_reaches_the_whole_opposing_side() -> None:
    """Let ranged attackers pick the highest-value target regardless of line."""
    ranged = participant(EntityId.ACTOR, 550, "Mage")
    front = participant(EntityId.TARGET, 125, "Tank")
    carry = participant(EntityId.TARGET_2, 550, "Marksman")

    assert reachable_targets(ranged, (front, carry)) == (front, carry)
    assert choose_target(ranged, (front, carry)) is EntityId.TARGET_2


def test_choosing_from_an_empty_side_yields_no_target() -> None:
    """Return no target rather than raising when a side is empty."""
    assert choose_target(participant(EntityId.ACTOR, 175, "Fighter"), ()) is None


def test_allocation_is_deterministic_and_covers_every_attacker() -> None:
    """Assign one target per attacker, breaking ties by canonical order."""
    attackers = (
        participant(EntityId.TARGET, 175, "Fighter"),
        participant(EntityId.TARGET_2, 550, "Mage"),
    )
    defenders = (
        participant(EntityId.ACTOR, 175, "Fighter", "Tank"),
        participant(EntityId.ALLY_2, 125, "Fighter"),
        participant(EntityId.ALLY_3, 550, "Marksman"),
    )

    allocation = allocate_threat(attackers, defenders)
    # The melee attacker cannot reach the carry and takes the first equal-rank
    # front liner; the ranged attacker takes the carry.
    assert allocation == {
        EntityId.TARGET: EntityId.ACTOR,
        EntityId.TARGET_2: EntityId.ALLY_3,
    }
    assert allocate_threat(attackers, defenders) == allocation


def test_a_duel_introduces_no_policy_assumptions() -> None:
    """Stay silent for two-participant encounters, which need no policy."""
    assert policy_blockers(multi_participant=False) == ()
    assumed = policy_blockers(multi_participant=True)
    assert "TARGET_SELECTION_SKILL_NOT_MODELED" in assumed
    assert any(value.startswith("THREAT_ALLOCATION_POLICY_ASSUMED") for value in assumed)
