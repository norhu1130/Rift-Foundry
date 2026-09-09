"""Deterministic target selection for encounters with more than two participants.

Real target selection is a player decision. The locked patch data records where
a champion stands (its attack range) and what it is built to do (its role tags),
but nothing about who a given player would actually attack. This module turns
the two recorded facts into one reviewable, deterministic policy and names the
assumptions it makes, so a caller can tell a data-backed result from a modeled
one.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from lol_build.cogs.base import MELEE_RANGE_CEILING as _MELEE_RANGE_CEILING
from lol_build.core.timeline import EntityId

POLICY_ID = "position_role_v1"

#: Attack range at or below which a champion fights from the front line, shared
#: with the Cog layer so targeting and area reach never disagree about lines.
MELEE_RANGE_CEILING = _MELEE_RANGE_CEILING

#: Kill priority by role tag, lowest value first. A champion with several tags
#: takes the highest priority any of its tags confers.
_ROLE_PRIORITY: dict[str, int] = {
    "Marksman": 0,
    "Mage": 1,
    "Assassin": 2,
    "Support": 3,
    "Fighter": 4,
    "Tank": 5,
}

_UNTAGGED_PRIORITY = max(_ROLE_PRIORITY.values()) + 1


@dataclass(frozen=True)
class ThreatParticipant:
    """Describe one participant for the purposes of target selection.

    :param entity: Timeline identity of this participant.
    :param attack_range: Attack range used to place it on a line.
    :param role_tags: Locked role tags for this champion.
    """

    entity: EntityId
    attack_range: Decimal
    role_tags: tuple[str, ...]

    @property
    def is_melee(self) -> bool:
        """Report whether this participant fights from the front line.

        :return: ``True`` when its attack range is within the melee ceiling.
        """
        return self.attack_range <= MELEE_RANGE_CEILING

    @property
    def role_priority(self) -> int:
        """Rank this participant as a target by its most valuable role tag.

        :return: Kill-priority rank, lower being attacked sooner.
        """
        return min(
            (_ROLE_PRIORITY[tag] for tag in self.role_tags if tag in _ROLE_PRIORITY),
            default=_UNTAGGED_PRIORITY,
        )


def reachable_targets(
    attacker: ThreatParticipant,
    defenders: tuple[ThreatParticipant, ...],
) -> tuple[ThreatParticipant, ...]:
    """List the defenders an attacker can engage from its own line.

    A melee attacker is held to the defending front line while one exists; it
    reaches the back line only once no front line remains. A ranged attacker is
    treated as able to engage anyone, which ignores terrain and spacing.

    :param attacker: Participant choosing a target.
    :param defenders: Living participants on the opposing side.
    :return: Engageable defenders in canonical order.
    """
    if not attacker.is_melee:
        return defenders
    front = tuple(defender for defender in defenders if defender.is_melee)
    return front or defenders


def choose_target(
    attacker: ThreatParticipant,
    defenders: tuple[ThreatParticipant, ...],
) -> EntityId | None:
    """Choose one defender for an attacker under the position-and-role policy.

    :param attacker: Participant choosing a target.
    :param defenders: Participants on the opposing side, in canonical order.
    :return: Chosen defender entity, or ``None`` when the side is empty.
    """
    candidates = reachable_targets(attacker, defenders)
    if not candidates:
        return None
    ordered = sorted(
        enumerate(candidates),
        key=lambda pair: (pair[1].role_priority, pair[0]),
    )
    return ordered[0][1].entity


def allocate_threat(
    attackers: tuple[ThreatParticipant, ...],
    defenders: tuple[ThreatParticipant, ...],
) -> dict[EntityId, EntityId]:
    """Assign every attacker a target on the defending side.

    :param attackers: Participants choosing targets, in canonical order.
    :param defenders: Participants being chosen from, in canonical order.
    :return: Mapping from attacker entity to its chosen defender entity.
    """
    allocation: dict[EntityId, EntityId] = {}
    for attacker in attackers:
        chosen = choose_target(attacker, defenders)
        if chosen is not None:
            allocation[attacker.entity] = chosen
    return allocation


def policy_blockers(*, multi_participant: bool) -> tuple[str, ...]:
    """Name the assumptions this policy introduces for an encounter.

    :param multi_participant: Whether either side holds more than one champion.
    :return: Blockers to attach to the evaluation, empty for a duel.
    """
    if not multi_participant:
        return ()
    return (
        f"THREAT_ALLOCATION_POLICY_ASSUMED:{POLICY_ID}",
        f"MELEE_RANGE_CEILING_ASSUMED:{MELEE_RANGE_CEILING}",
        "TARGET_SELECTION_SKILL_NOT_MODELED",
    )
