"""Area abilities must reach every opponent without changing duel results."""

from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest, ParticipantSpec
from lol_build.cogs.base import AREA_TARGETING_TYPES, CogCapability
from lol_build.cogs.manifest import CHAMPION_COG_BY_KEY
from lol_build.cogs.registry import create_default_registry

ROOT = Path(__file__).resolve().parents[1]
PROMOTED = ("Amumu", "Annie", "Karthus", "Leona")
#: Garen leads the opposing side, so Jax shares his front line while Ahri
#: stands behind it. An area effect must separate the two.
TEAM = (ParticipantSpec("Jax", (3078,)), ParticipantSpec("Ahri", (3020,)))


def test_area_slots_come_from_locked_targeting_types() -> None:
    """Read area membership from the patch data rather than from game knowledge."""
    registry = create_default_registry(ROOT)

    # Ambiguous point and line casts stay out: they may resolve on one champion.
    assert "Location" not in AREA_TARGETING_TYPES
    assert "Direction" not in AREA_TARGETING_TYPES
    assert registry.require_cog("Amumu").area_ability_slots() == frozenset({"W", "E", "R"})
    assert registry.require_cog("Garen").area_ability_slots() == frozenset({"E"})
    # Every champion resolves, so no Cog silently gets an empty classification
    # because its locked record could not be read.
    classified = sum(
        bool(registry.require_cog(key).area_ability_slots()) for key in CHAMPION_COG_BY_KEY
    )
    assert classified > 100


def test_only_promoted_cogs_claim_multi_target() -> None:
    """Keep the capability tied to Cogs that actually widen their outputs."""
    registry = create_default_registry(ROOT)
    claiming = sorted(
        key
        for key in CHAMPION_COG_BY_KEY
        if registry.require_cog(key).has_capability(CogCapability.MULTI_TARGET)
    )

    assert claiming == sorted(PROMOTED)


def test_a_promoted_cog_is_unchanged_in_a_duel() -> None:
    """Leave one-versus-one damage exactly where it was before the fan-out."""
    engine = MatchupEngine(ROOT)
    for name in PROMOTED:
        duel = engine.evaluate(
            MatchupRequest(name, "Garen", opponent_item_ids=(3071, 3053))
        )
        # A duel holds one opponent, so the area helper yields one output and
        # the whole opposing side's loss is the primary target's loss.
        assert len(duel.opponents_hp_lost) == 1
        assert duel.opposing_side_hp_lost == duel.opponent_hp_lost


def test_promoted_cogs_damage_opponents_beyond_the_primary_target() -> None:
    """Spread area damage across the opposing side once more of it is present."""
    engine = MatchupEngine(ROOT)
    for name in PROMOTED:
        team = engine.evaluate(
            MatchupRequest(
                name,
                "Garen",
                # Facing three opponents, an itemless actor can die before its
                # area abilities come up, which would prove nothing about reach.
                actor_item_ids=(3083, 3742, 3143),
                opponent_item_ids=(3071, 3053),
                additional_opponents=TEAM,
            )
        )
        losses = {entity.value: value for entity, value in team.opponents_hp_lost.items()}

        # Jax holds the same line as the primary target and is reached.
        assert losses["TARGET_2"] > 0, name
        # Ahri stands behind that line and is not.
        assert losses["TARGET_3"] == 0, name
        assert f"MULTI_TARGET_UNCURATED:{name}" not in team.blockers


def test_an_unpromoted_cog_still_reports_its_single_target_limit() -> None:
    """Keep the honest blocker for kits whose area effects are not modeled yet."""
    engine = MatchupEngine(ROOT)
    team = engine.evaluate(
        MatchupRequest(
            "Garen", "Darius", opponent_item_ids=(3071, 3053), additional_opponents=TEAM
        )
    )
    secondary = [
        value for entity, value in team.opponents_hp_lost.items() if entity.value != "TARGET"
    ]

    assert all(value == 0 for value in secondary)
    assert "MULTI_TARGET_UNCURATED:Garen" in team.blockers


def test_area_reach_is_bounded_by_line_rather_than_the_whole_side() -> None:
    """Cover the line an area effect lands on, not every opponent present."""
    from lol_build.cogs import OpponentView, ParticipantContext
    from lol_build.cogs.base import ChampionCog
    from lol_build.core.timeline import OPPONENT_ENTITIES, EntityId

    registry = create_default_registry(ROOT)
    names = ("Garen", "Ahri", "Vayne", "Leona", "Jax")
    side = tuple(
        OpponentView(entity, registry.require_cog(name).snapshot(level=13))
        for entity, name in zip(OPPONENT_ENTITIES, names, strict=True)
    )
    context = ParticipantContext(
        EntityId.ACTOR,
        EntityId.TARGET,
        registry.require_cog("Annie").snapshot(level=13),
        side[0].snapshot,
        8000,
        3000,
        opponents=side,
    )

    # Garen, Leona, and Jax hold the front line; Ahri and Vayne stand behind it.
    front = {EntityId.TARGET, EntityId.TARGET_4, EntityId.TARGET_5}
    assert set(ChampionCog.area_recipients(context, centered_on_self=True)) == front
    assert set(ChampionCog.area_recipients(context, centered_on_self=False)) == front


def test_area_reach_collapses_to_the_single_opponent_of_a_duel() -> None:
    """Keep a duel producing exactly the one output it produced before."""
    from lol_build.cogs import ParticipantContext
    from lol_build.cogs.base import ChampionCog
    from lol_build.core.timeline import EntityId

    registry = create_default_registry(ROOT)
    context = ParticipantContext(
        EntityId.ACTOR,
        EntityId.TARGET,
        registry.require_cog("Annie").snapshot(level=13),
        registry.require_cog("Ahri").snapshot(level=13),
        8000,
        3000,
    )

    # The lone opponent is ranged, so it shares no line with a melee caster and
    # would be missed by a line rule that ignored the aimed-at champion.
    assert ChampionCog.area_recipients(context, centered_on_self=True) == (EntityId.TARGET,)
    assert ChampionCog.area_recipients(context, centered_on_self=False) == (EntityId.TARGET,)
