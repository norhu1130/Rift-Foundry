"""Every Cog's damage outputs carry a real damage type in the right position."""

from pathlib import Path

from lol_build.cogs import ParticipantContext, create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import (
    CurrentHealthDamageOutput,
    DamageOutput,
    EntityId,
    MissingHealthDamageOutput,
)

ROOT = Path(__file__).resolve().parents[1]


def test_every_cog_damage_output_names_a_damage_type() -> None:
    """Catch positional mix-ups before the recommendation reads plan outputs.

    The build search reads each opponent plan's damage outputs directly to
    weigh damage types, before any timeline validation runs, so a Cog that
    swaps positional fields (a ratio where the damage type belongs) crashes
    the search only against that champion.
    """
    registry = create_default_registry(ROOT)
    garen = registry.require_cog("Garen").snapshot(level=13)
    misplaced = []
    for cog in registry.walk_cogs():
        context = ParticipantContext(
            EntityId.ACTOR, EntityId.TARGET, cog.snapshot(level=13), garen, 8000, 3000
        )
        for event in cog.build_action_plan(context).events:
            for output in event.outputs:
                if isinstance(
                    output, (DamageOutput, CurrentHealthDamageOutput, MissingHealthDamageOutput)
                ) and not isinstance(output.damage_type, DamageType):
                    misplaced.append((cog.champion_key, event.id))

    assert misplaced == []
