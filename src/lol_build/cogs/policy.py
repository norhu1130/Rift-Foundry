"""Mechanic-keyed champion policy extraction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from lol_build.core.timeline import ActionChannel
from lol_build.items.candidates import ResourceType


@dataclass(frozen=True)
class ChampionPolicy:
    """Capture resource, range, objective, and exception policy for one champion."""

    resource: ResourceType
    range_class: str
    primary_metric: str
    mechanics: tuple[str, ...]
    rotation_rules: tuple[str, ...]
    relevant_action_channels: tuple[ActionChannel, ...]


def policy_from_profile(profile: Mapping[str, Any]) -> ChampionPolicy:
    """Build evaluation policy from mechanics; identity fields are metadata only.

    :param profile: Mechanic-keyed champion profile document.
    :return: Evaluation policy derived only from mechanic and rotation fields.
    """

    rules = tuple(profile["rotation"]["rules"])
    channels: list[ActionChannel] = []
    if any("BASIC_ATTACK" in rule or "ATTACK_RESET" in rule for rule in rules):
        channels.append(ActionChannel.BASIC_ATTACK)
    if any(rule in {"W_ON_COOLDOWN_ATTACK_RESET", "E_CAST_ONCE"} for rule in rules):
        channels.append(ActionChannel.ABILITY)
    return ChampionPolicy(
        ResourceType(profile["resource"]),
        profile["range_class"],
        profile["primary_metric"],
        tuple(profile["mechanics"]),
        rules,
        tuple(channels),
    )
