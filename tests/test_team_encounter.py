"""Verify that a five-opponent encounter reaches every layer of the engine."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest, ParticipantSpec
from lol_build.application.web.service import WebService
from lol_build.core.timeline import EntityId

ROOT = Path(__file__).resolve().parents[1]

TEAM = (
    ParticipantSpec("Ahri", (3020, 6653, 3089)),
    ParticipantSpec("Vayne", (3153, 3006, 3072)),
    ParticipantSpec("Leona", (3068, 3143, 3047)),
    ParticipantSpec("Jax", (3078, 3053, 3047)),
)


def test_duel_evaluation_is_unchanged_by_the_multi_opponent_engine() -> None:
    """Keep the two-entity result identical now that five entities are possible."""
    engine = MatchupEngine(ROOT)
    duel = engine.evaluate(
        MatchupRequest("Darius", "Garen", opponent_item_ids=(3071, 3053, 6333))
    )

    assert set(duel.opponents_hp_lost) == {EntityId.TARGET}
    assert duel.opposing_side_hp_lost == duel.opponent_hp_lost
    assert duel.timeline.damage_to_all_targets_total == duel.timeline.damage_to_target_total
    assert "FOCUS_TARGET_POLICY_UNVERIFIED" not in duel.blockers


def test_team_evaluation_simulates_every_opponent_and_marks_its_assumptions() -> None:
    """Bind all five opponents and expose the assumptions that choice implies."""
    engine = MatchupEngine(ROOT)
    team = engine.evaluate(
        MatchupRequest(
            "Darius",
            "Garen",
            opponent_item_ids=(3071, 3053, 6333),
            additional_opponents=TEAM,
        )
    )

    assert set(team.opponents_hp_lost) == {
        EntityId.TARGET,
        EntityId.TARGET_2,
        EntityId.TARGET_3,
        EntityId.TARGET_4,
        EntityId.TARGET_5,
    }
    assert set(team.timeline.targets_at_end) == set(team.opponents_hp_lost)
    assert "FOCUS_TARGET_POLICY_UNVERIFIED" in team.blockers
    assert "THREAT_ALLOCATION_POLICY_ASSUMED:position_role_v1" in team.blockers
    assert "MULTI_TARGET_UNCURATED:Darius" in team.blockers
    # Five attackers must remove strictly more health than one.
    duel = engine.evaluate(
        MatchupRequest("Darius", "Garen", opponent_item_ids=(3071, 3053, 6333))
    )
    assert team.actor_hp_lost > duel.actor_hp_lost


def test_darius_recommendation_never_silently_drops_the_opposing_team() -> None:
    """Keep every named opponent visible in the team-encounter blockers.

    Every actor, Darius included, always runs through the same generic search,
    so a request naming a full opposing team must surface it rather than
    silently modeling one opponent only.
    """
    service = WebService(ROOT)
    document = service.recommend(
        {
            "actor": "Darius",
            "opponent": "Garen",
            "opponent_item_ids": [3071, 3053, 6333],
            "additional_opponents": [
                {"champion": spec.champion, "item_ids": list(spec.item_ids)} for spec in TEAM
            ],
        }
    )

    blockers = document["recommendation"]["blockers"]
    assert "FOCUS_TARGET_POLICY_UNVERIFIED" in blockers
    assert "THREAT_ALLOCATION_POLICY_ASSUMED:position_role_v1" in blockers
    assert "TEAM_ENCOUNTER_CHASSIS_METRICS_USE_PRIMARY_OPPONENT_ONLY" in blockers
    assert document["recommendation"]["release_eligible"] is False


def test_arriving_opponents_cannot_act_before_they_close_the_distance() -> None:
    """Hold each arriving opponent out of the fight until it reaches the actor."""
    engine = MatchupEngine(ROOT)
    request = MatchupRequest(
        "Darius",
        "Garen",
        opponent_item_ids=(3071, 3053, 6333),
        additional_opponents=TEAM,
    )
    team = engine.evaluate(request)

    gated = [
        entry
        for entry in team.timeline.log
        if entry.detail is not None and entry.detail.startswith("NOT_YET_IN_CONTACT")
    ]
    assert gated, "arriving opponents must have premature actions cancelled"
    assert "TEAM_ARRIVAL_DISTANCE_ASSUMED:650" in team.blockers
    assert "TEAM_ARRIVAL_DASH_RESERVED_ASSUMED" in team.blockers

    # The primary opponent is already engaged and is never held back.
    assert not [
        entry
        for entry in team.timeline.log
        if entry.detail is not None
        and entry.detail.startswith("NOT_YET_IN_CONTACT")
        and entry.event_id.startswith("GAREN")
    ]


def test_a_longer_approach_leaves_the_actor_more_time_to_deal_damage() -> None:
    """Make the approach distance change the encounter, not just its blockers."""
    engine = MatchupEngine(ROOT)
    near = engine.evaluate(
        MatchupRequest(
            "Darius",
            "Garen",
            opponent_item_ids=(3071, 3053, 6333),
            additional_opponents=TEAM,
        )
    )
    far = engine.evaluate(
        MatchupRequest(
            "Darius",
            "Garen",
            opponent_item_ids=(3071, 3053, 6333),
            additional_opponents=TEAM,
            team_arrival_distance=Decimal(2000),
        )
    )

    assert far.opposing_side_hp_lost > near.opposing_side_hp_lost


def test_spending_the_gap_closer_on_approach_is_an_explicit_choice() -> None:
    """Keep dash-assisted arrival opt-in and labelled, since it is an assumption."""
    engine = MatchupEngine(ROOT)
    reserved = engine.evaluate(
        MatchupRequest(
            "Darius",
            "Garen",
            opponent_item_ids=(3071, 3053, 6333),
            additional_opponents=TEAM,
        )
    )
    spent = engine.evaluate(
        MatchupRequest(
            "Darius",
            "Garen",
            opponent_item_ids=(3071, 3053, 6333),
            additional_opponents=TEAM,
            team_arrival_spends_dash=True,
        )
    )

    assert "TEAM_ARRIVAL_DASH_RESERVED_ASSUMED" in reserved.blockers
    assert "TEAM_ARRIVAL_DASH_SPENT_ASSUMED" in spent.blockers
    # Gap-closers erase the approach for this roster, so nothing is held back.
    assert not [
        entry
        for entry in spent.timeline.log
        if entry.detail is not None and entry.detail.startswith("NOT_YET_IN_CONTACT")
    ]


ALLIES = (
    ParticipantSpec("Lux", (6653, 3020, 3089)),
    ParticipantSpec("Jinx", (3031, 3006, 3072)),
    ParticipantSpec("Thresh", (3068, 3143, 3047)),
    ParticipantSpec("LeeSin", (6631, 3047, 3053)),
)


def test_five_versus_five_binds_both_sides_and_isolates_the_actor() -> None:
    """Fight ten participants while keeping the actor's own damage separable."""
    engine = MatchupEngine(ROOT)
    full = engine.evaluate(
        MatchupRequest(
            "Darius",
            "Garen",
            opponent_item_ids=(3071, 3053, 6333),
            additional_opponents=TEAM,
            allies=ALLIES,
        )
    )

    assert set(full.timeline.allies_at_end) == {
        EntityId.ACTOR,
        EntityId.ALLY_2,
        EntityId.ALLY_3,
        EntityId.ALLY_4,
        EntityId.ALLY_5,
    }
    assert len(full.timeline.targets_at_end) == 5
    # Allies add team damage without being credited to the actor's build.
    assert full.timeline.damage_to_all_targets_total > full.timeline.actor_damage_dealt
    assert "ALLY_CONTRIBUTION_EXCLUDED_FROM_BUILD_RANKING" in full.blockers


def test_ally_output_is_never_credited_to_the_actors_build() -> None:
    """Separate the side's output from the actor's, which is what ranks a build."""
    engine = MatchupEngine(ROOT)
    without = engine.evaluate(
        MatchupRequest(
            "Darius",
            "Garen",
            opponent_item_ids=(3071, 3053, 6333),
            additional_opponents=TEAM,
        )
    )
    with_allies = engine.evaluate(
        MatchupRequest(
            "Darius",
            "Garen",
            opponent_item_ids=(3071, 3053, 6333),
            additional_opponents=TEAM,
            allies=ALLIES,
        )
    )

    # Allies change the fight, so the actor's own output legitimately differs.
    # What must hold is that their damage is never folded into the actor's.
    assert with_allies.timeline.actor_damage_dealt < (
        with_allies.timeline.damage_to_all_targets_total
    )
    assert without.timeline.actor_damage_dealt == (
        without.timeline.damage_to_all_targets_total
    )
    assert with_allies.timeline.damage_to_all_targets_total > (
        without.timeline.damage_to_all_targets_total
    )


def test_a_duel_reports_no_allies_and_no_team_blockers() -> None:
    """Leave the one-versus-one contract untouched by the team machinery."""
    engine = MatchupEngine(ROOT)
    duel = engine.evaluate(
        MatchupRequest("Darius", "Garen", opponent_item_ids=(3071, 3053, 6333))
    )

    assert set(duel.timeline.allies_at_end) == {EntityId.ACTOR}
    assert "ALLY_CONTRIBUTION_EXCLUDED_FROM_BUILD_RANKING" not in duel.blockers
    assert duel.timeline.actor_damage_dealt > 0


def test_allies_absorb_attention_so_the_actor_survives_a_team_fight() -> None:
    """Spread incoming damage once the actor's side gives enemies other targets."""
    engine = MatchupEngine(ROOT)
    alone = engine.evaluate(
        MatchupRequest(
            "Darius",
            "Garen",
            opponent_item_ids=(3071, 3053, 6333),
            additional_opponents=TEAM,
        )
    )
    supported = engine.evaluate(
        MatchupRequest(
            "Darius",
            "Garen",
            opponent_item_ids=(3071, 3053, 6333),
            additional_opponents=TEAM,
            allies=ALLIES,
        )
    )

    # Facing five attackers alone, the actor is silenced into near-zero output.
    # With a side of its own, only the named matchup stays on it.
    assert supported.timeline.actor_damage_dealt > alone.timeline.actor_damage_dealt
    assert "PRIMARY_OPPONENT_PINNED_TO_ACTOR" in supported.blockers


def test_single_target_damage_to_the_actor_comes_only_from_the_pinned_opponent() -> None:
    """Route single-target damage by allocation, and say where area damage differs.

    A champion aimed elsewhere still reaches the actor through an area ability,
    which is why the promoted Cogs exist. What allocation must control is
    single-target damage: an opponent aimed at an ally may not attack the actor
    directly.
    """
    engine = MatchupEngine(ROOT)
    supported = engine.evaluate(
        MatchupRequest(
            "Darius",
            "Garen",
            opponent_item_ids=(3071, 3053, 6333),
            additional_opponents=TEAM,
            allies=ALLIES,
        )
    )

    sources = {
        entry.event_id.split("_")[0]
        for entry in supported.timeline.log
        if entry.recipient is EntityId.ACTOR
        and entry.hp_delta is not None
        and entry.hp_delta < 0
    }
    # Ahri, Vayne, and Jax are aimed at the actor's allies and model no area
    # ability, so none of their damage may land on the actor.
    assert not {"AHRI", "VAYNE", "JAX"} & sources

    # Leona is aimed at an ally too, but her promoted area abilities still reach
    # champions standing on the same line, which is approximated from attack
    # range rather than known. That approximation is declared, not hidden.
    assert "AREA_ABILITY_REACH_APPROXIMATED_BY_LINE" in supported.blockers
