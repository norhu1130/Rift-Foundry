"""Focused regressions for the locked Fizz champion Cog."""

import json
from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import _active_cast_windows, _apply_cast_blocks
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.champions.wip.fizz import FizzCog
from lol_build.cogs.champions.wip.teemo import TeemoCog
from lol_build.core.timeline import EntityId

ROOT = Path(__file__).resolve().parents[1]


def _fizz() -> FizzCog:
    """Construct Fizz independently of root-owned manifest integration.

    :return: Fizz Cog backed by the locked champion documents.
    """
    detail_document = json.loads(
        (ROOT / "data/raw/16.17.1/communitydragon/champions/fizz.bin.json").read_text(
            encoding="utf-8"
        )
    )
    detail_root = next(
        value
        for key, value in detail_document.items()
        if key.casefold() == "characters/fizz/characterrecords/root"
    )
    document = json.loads(
        (ROOT / "data/raw/16.17.1/en_US/champion/Fizz.json").read_text(encoding="utf-8")
    )["data"]["Fizz"]
    return FizzCog(document, detail_root)


def _teemo() -> TeemoCog:
    """Construct Teemo directly from locked documents for blind tests.

    :return: Teemo Cog independent from concurrent manifest integration.
    """
    detail_document = json.loads(
        (ROOT / "data/raw/16.17.1/communitydragon/champions/teemo.bin.json").read_text(
            encoding="utf-8"
        )
    )
    detail_root = next(
        value
        for key, value in detail_document.items()
        if key.casefold() == "characters/teemo/characterrecords/root"
    )
    document = json.loads(
        (ROOT / "data/raw/16.17.1/en_US/champion/Teemo.json").read_text(encoding="utf-8")
    )["data"]["Teemo"]
    return TeemoCog(document, detail_root)


def _context(
    *,
    fizz_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Fizz-versus-Teemo direct-Cog context.

    :param fizz_is_actor: Place Fizz on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Fizz.
    :return: Role-bound deterministic benchmark context.
    """
    fizz = _fizz()
    teemo = _teemo()
    return ParticipantContext(
        EntityId.ACTOR if fizz_is_actor else EntityId.TARGET,
        EntityId.TARGET if fizz_is_actor else EntityId.ACTOR,
        fizz.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Find one named event in a Fizz action plan.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Stable champion-scoped event identifier.
    :return: Matching immutable action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def _attacks(plan: object):
    """Collect ordinary post-reset attacks from one Fizz plan.

    :param plan: Fizz action plan exposing an ``events`` tuple.
    :return: Chronological ordinary basic-attack events.
    """
    return tuple(event for event in plan.events if event.id.startswith("FIZZ_BASIC_ATTACK_"))


def test_fizz_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Fizz from a scaffold and retain all three source forms."""
    fizz = _fizz()

    assert fizz.maturity is CogMaturity.MODELED_UNVERIFIED
    assert fizz.capabilities == DUEL_CAPABILITIES
    assert fizz.verification_blockers() == ("COG_MODEL_UNVERIFIED:Fizz",)
    assert fizz.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Fizz.json",
        "data/raw/16.17.1/communitydragon/champions/105.json",
        "data/raw/16.17.1/communitydragon/champions/fizz.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in fizz.evidence_refs)


def test_fizz_rotation_is_deterministic_and_anchors_locked_formulas() -> None:
    """Anchor maximum-range R, Q, E, W, and bleed values at 100 AP."""
    fizz = _fizz()
    context = _context(item_stats={"AP": Decimal(100)})

    first = fizz.build_action_plan(context)
    repeated = fizz.build_action_plan(context)
    shark = _event(first, "FIZZ_R_CHUM_THE_WATERS_LARGE_SHARK")
    q = _event(first, "FIZZ_Q_URCHIN_STRIKE_1")
    q_on_hit = _event(first, "FIZZ_Q_ON_HIT_1")
    landing = _event(first, "FIZZ_E_TRICKSTER_LANDING")
    reset = _event(first, "FIZZ_W_SEASTONE_RESET_ATTACK")
    bleed = _event(first, "FIZZ_W_SEASTONE_BLEED_TICK_1")

    assert first == repeated
    assert first.model_id == "fizz_e5_w5_q1_r2_level13_large_shark_v1"
    assert shark.outputs[0].amount == Decimal(540)
    assert shark.outputs[1].status == "CC_AIRBORNE"
    assert q.outputs[0].amount == Decimal(65)
    assert q_on_hit.outputs[0].amount == context.snapshot.attack_damage
    assert landing.outputs[0].amount == Decimal(375)
    assert landing.outputs[1].magnitude == Decimal("0.60")
    assert reset.outputs[1].amount == Decimal(195)
    assert bleed.outputs[0].amount == Decimal(115) / Decimal(6)
    assert "FIZZ_R_DISTANCE_TIER_AND_PROJECTILE_COLLISION_NOT_MODELED" in first.blockers
    assert "FIZZ_E_TERRAIN_AND_DASH_GEOMETRY_NOT_MODELED" in first.blockers


def test_fizz_ap_attack_speed_and_haste_change_represented_outputs() -> None:
    """Prove AP, attack speed, and haste affect distinct modeled channels."""
    fizz = _fizz()
    baseline = fizz.build_action_plan(_context())
    powered = fizz.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    faster = fizz.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))
    hasted = fizz.build_action_plan(_context(item_stats={"ABILITY_HASTE": Decimal(100)}))

    assert _event(powered, "FIZZ_E_TRICKSTER_LANDING").outputs[0].amount - _event(
        baseline, "FIZZ_E_TRICKSTER_LANDING"
    ).outputs[0].amount == Decimal(95)
    assert len(_attacks(faster)) > len(_attacks(baseline))
    assert _event(hasted, "FIZZ_Q_URCHIN_STRIKE_2").at_ms == 6150
    assert not any(event.id == "FIZZ_Q_URCHIN_STRIKE_2" for event in baseline.events)


def test_fizz_reaction_separates_untargetability_slow_and_knockup() -> None:
    """Expose E defense and control without hiding source-filter uncertainty."""
    fizz = _fizz()
    reaction = fizz.build_reaction_plan(_context())
    attached_slow, knockup, landing_slow = reaction.cast_block_windows

    assert reaction.damage_windows[0].start_ms == 2500
    assert reaction.damage_windows[0].end_ms == 3250
    assert reaction.damage_windows[0].multiplier == 0
    assert attached_slow.control_type.value == "SLOW"
    assert attached_slow.tenacity_reducible is True
    assert knockup.control_type.value == "AIRBORNE"
    assert knockup.tenacity_reducible is False
    assert landing_slow.control_type.value == "SLOW"
    assert "FIZZ_E_UNTARGETABLE_SOURCE_FILTERING_NOT_MODELED" in reaction.blockers


def test_fizz_role_reversal_keeps_sources_recipients_and_sequences_symmetric() -> None:
    """Bind all Fizz effects to the selected participant instead of actor role."""
    fizz = _fizz()
    actor_plan = fizz.build_action_plan(_context(fizz_is_actor=True))
    target_plan = fizz.build_action_plan(_context(fizz_is_actor=False))
    actor_q = _event(actor_plan, "FIZZ_Q_URCHIN_STRIKE_1")
    target_q = _event(target_plan, "FIZZ_Q_URCHIN_STRIKE_1")

    assert actor_q.source is EntityId.ACTOR
    assert target_q.source is EntityId.TARGET
    assert actor_q.outputs[0].recipient is EntityId.TARGET
    assert target_q.outputs[0].recipient is EntityId.ACTOR
    assert actor_q.sequence != target_q.sequence


def test_teemo_blind_cancels_fizz_on_hits_but_not_spell_damage() -> None:
    """Apply Teemo's real reaction window to Fizz's channel-separated plan."""
    fizz = _fizz()
    context = _context()
    fizz_plan = fizz.build_action_plan(context)
    teemo = _teemo()
    teemo_context = ParticipantContext(
        EntityId.TARGET,
        EntityId.ACTOR,
        context.opponent_snapshot,
        context.snapshot,
        context.duration_ms,
        context.horizon_ms,
    )
    teemo_actions = teemo.build_action_plan(teemo_context)
    teemo_reaction = teemo.build_reaction_plan(teemo_context)
    active_blind = _active_cast_windows(
        teemo_reaction.cast_block_windows,
        teemo_actions.events,
        context.snapshot.tenacity,
    )
    blocked = _apply_cast_blocks(fizz_plan.events, active_blind)

    assert next(event for event in blocked if event.id == "FIZZ_Q_ON_HIT_1").cancelled
    assert not next(event for event in blocked if event.id == "FIZZ_Q_URCHIN_STRIKE_1").cancelled
    assert not next(
        event for event in blocked if event.id == "FIZZ_R_CHUM_THE_WATERS_LARGE_SHARK"
    ).cancelled
    assert not next(event for event in blocked if event.id == "FIZZ_E_TRICKSTER_LANDING").cancelled


def test_fizz_item_policy_engagement_and_lane_sustain_are_explicit() -> None:
    """Accept represented stats while refusing unsupported resource valuation."""
    fizz = _fizz()
    context = _context()

    assert fizz.engagement_dash_distance(context) == Decimal(550)
    assert (
        fizz.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AP": {},
                    "AD": {},
                    "ATTACK_SPEED": {},
                    "ABILITY_HASTE": {},
                    "HP": {},
                },
            }
        )
        is None
    )
    assert (
        fizz.item_candidate_blocker({"id": 2, "stats": {"CRITICAL_STRIKE_CHANCE": {}, "MANA": {}}})
        == "FIZZ_ITEM_STAT_NOT_MODELED:2:CRITICAL_STRIKE_CHANCE,MANA"
    )
    assert fizz.lane_sustain_extra_health(
        context,
        duration_ms=30_000,
        no_damage_delay_ms=8_000,
    ) == (Decimal(0), ())
