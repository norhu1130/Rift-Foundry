"""Tests for explicit Cog maturity and reusable mechanic primitives."""

from decimal import Decimal

import pytest

from lol_build.cogs.base import (
    ChampionCog,
    CogCapability,
    CogMaturity,
    ParticipantContext,
)
from lol_build.cogs.mechanics import (
    action,
    crowd_control,
    damage,
    healing,
    movement_speed,
    shielding,
)
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, EntityId


def _document() -> dict[str, object]:
    """Build the smallest Data Dragon champion document used by contract tests.

    :return: Champion summary containing all snapshot fallback stats.
    """
    return {
        "key": "1",
        "id": "TestChampion",
        "name": "Test Champion",
        "stats": {
            "hp": 600,
            "hpperlevel": 100,
            "attackdamage": 60,
            "attackdamageperlevel": 3,
            "attackspeed": 0.65,
            "attackspeedperlevel": 2,
            "armor": 30,
            "armorperlevel": 4,
            "spellblock": 30,
            "spellblockperlevel": 2,
            "movespeed": 340,
            "attackrange": 175,
        },
    }


def test_generic_cog_explicitly_reports_scaffolded_capabilities() -> None:
    """Keep a registered fallback distinct from a modeled recommendation Cog."""
    cog = ChampionCog(_document())

    assert cog.metadata.maturity is CogMaturity.SCAFFOLDED
    assert cog.metadata.capabilities == frozenset({CogCapability.BASIC_ATTACK})
    assert cog.has_capability(CogCapability.BASIC_ATTACK)
    assert not cog.has_capability(CogCapability.RECOMMENDATION)
    assert cog.verification_blockers() == ("COG_SCAFFOLDED:TestChampion",)
    assert not hasattr(cog, "recommendation_model_id")


def test_modeled_cog_can_declare_capabilities_without_inheriting_false_ones() -> None:
    """Allow champion modules to opt into only behavior they actually model."""

    class ModeledCog(ChampionCog):
        """Represent a test-only ability and reaction model."""

        maturity = CogMaturity.MODELED_UNVERIFIED
        capabilities = frozenset(
            {
                CogCapability.BASIC_ATTACK,
                CogCapability.ABILITY_ROTATION,
                CogCapability.REACTION_MODEL,
            }
        )

    cog = ModeledCog(_document())

    assert cog.has_capability(CogCapability.ABILITY_ROTATION)
    assert not cog.has_capability(CogCapability.RECOMMENDATION)
    assert cog.verification_blockers() == ("COG_MODEL_UNVERIFIED:TestChampion",)


def test_snapshot_preserves_ability_haste_for_champion_rotation_models() -> None:
    """Expose item ability haste without inventing champion cooldown schedules.

    :return: None.
    """
    snapshot = ChampionCog(_document()).snapshot(
        level=13,
        item_stats={"ABILITY_HASTE": Decimal(35)},
    )

    assert snapshot.ability_haste == 35


def test_base_cog_owns_shared_sequence_and_attack_interval_policies() -> None:
    """Give ordinary champion Cogs deterministic defaults without duplication.

    :return: None.
    """
    cog = ChampionCog(_document())
    snapshot = cog.snapshot(level=13)
    actor_context = ParticipantContext(
        EntityId.ACTOR,
        EntityId.TARGET,
        snapshot,
        snapshot,
        8000,
        8000,
    )
    target_context = ParticipantContext(
        EntityId.TARGET,
        EntityId.ACTOR,
        snapshot,
        snapshot,
        8000,
        8000,
    )

    assert cog._sequence_base(actor_context) == 0
    assert cog._sequence_base(target_context) == 10_000
    assert cog._attack_interval_ms(Decimal("0.5")) == 2000
    with pytest.raises(ValueError, match="attack_speed"):
        cog._attack_interval_ms(Decimal(0))


def test_mechanic_primitives_build_timeline_native_outputs() -> None:
    """Compose damage, recovery, mobility, and control in one shared action."""
    outputs = (
        damage(EntityId.TARGET, Decimal(125), DamageType.PHYSICAL),
        healing(EntityId.ACTOR, Decimal(40)),
        shielding(EntityId.ACTOR, Decimal(80), duration_ms=2000),
        movement_speed(EntityId.ACTOR, Decimal(25), duration_ms=1500),
        crowd_control(EntityId.TARGET, "slow", duration_ms=1000, magnitude=Decimal("0.3")),
    )

    event = action(
        "TEST_COMPOSITE",
        at_ms=500,
        sequence=2,
        source=EntityId.ACTOR,
        channel=ActionChannel.ABILITY,
        outputs=outputs,
    )

    assert event.outputs == outputs
    assert event.outputs[3].stat == "MOVE_SPEED_FLAT"
    assert event.outputs[4].status == "CC_SLOW"


@pytest.mark.parametrize(
    ("factory", "message"),
    (
        (lambda: damage(EntityId.TARGET, Decimal(-1), DamageType.TRUE), "damage amount"),
        (lambda: healing(EntityId.ACTOR, Decimal(-1)), "healing amount"),
        (lambda: shielding(EntityId.ACTOR, Decimal(1), duration_ms=0), "shield duration"),
        (lambda: crowd_control(EntityId.TARGET, "", duration_ms=100), "control_type"),
    ),
)
def test_mechanic_primitives_reject_invalid_contracts(factory: object, message: str) -> None:
    """Fail at Cog construction time instead of corrupting a combat timeline.

    :param factory: Zero-argument callable constructing an invalid primitive.
    :param message: Error fragment identifying the rejected field.
    :return: None.
    """
    assert callable(factory)
    with pytest.raises(ValueError, match=message):
        factory()
