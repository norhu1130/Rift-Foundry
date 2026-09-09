"""Focused regression coverage for the locked Azir champion Cog."""

import json
from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import (
    ChampionCog,
    ChampionCogRegistry,
    CogMaturity,
    ControlType,
    ParticipantContext,
)
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.champions.modeled_unverified.garen import GarenCog
from lol_build.cogs.champions.wip.azir import AzirCog
from lol_build.cogs.champions.wip.teemo import TeemoCog
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, EntityId, ShieldOutput, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _locked_cog(
    cog_type: type[ChampionCog], champion_key: str, champion_id: int
) -> ChampionCog:
    """Construct one Cog directly from its two locked runtime documents.

    :param cog_type: Concrete champion Cog class to instantiate.
    :param champion_key: Data Dragon identifier and BIN path stem.
    :param champion_id: Numeric CommunityDragon profile identifier.
    :return: Cog backed by the locked summary and detailed stat root.
    """
    catalog = json.loads(
        (ROOT / "data/raw/16.17.1/en_US/champion.json").read_text(encoding="utf-8")
    )["data"]
    bin_document = json.loads(
        (
            ROOT
            / "data/raw/16.17.1/communitydragon/champions"
            / f"{champion_key.casefold()}.bin.json"
        ).read_text(encoding="utf-8")
    )
    expected_root = f"Characters/{champion_key}/CharacterRecords/Root".casefold()
    detail_root = next(
        value for key, value in bin_document.items() if key.casefold() == expected_root
    )
    assert (
        ROOT / f"data/raw/16.17.1/communitydragon/champions/{champion_id}.json"
    ).is_file()
    return cog_type(catalog[champion_key], detail_root)


def _azir() -> AzirCog:
    """Construct Azir independently of root-owned manifest integration.

    :return: Azir Cog backed by the locked registry documents.
    """
    result = _locked_cog(AzirCog, "Azir", 268)
    assert isinstance(result, AzirCog)
    return result


def _context(
    *,
    azir_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Azir-versus-Garen direct-Cog context.

    :param azir_is_actor: Place Azir on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Azir.
    :return: Role-bound context for deterministic Azir tests.
    """
    azir = _azir()
    garen = _locked_cog(GarenCog, "Garen", 86)
    return ParticipantContext(
        EntityId.ACTOR if azir_is_actor else EntityId.TARGET,
        EntityId.TARGET if azir_is_actor else EntityId.ACTOR,
        azir.snapshot(level=13, item_stats=item_stats),
        garen.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one action by its stable Azir identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching immutable action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def _engine() -> MatchupEngine:
    """Build a matchup engine with the in-progress Azir class injected.

    :return: Engine whose Azir registration does not depend on manifest edits.
    """
    registry = ChampionCogRegistry()
    registry.add_cog(_azir())
    registry.add_cog(_locked_cog(GarenCog, "Garen", 86))
    registry.add_cog(_locked_cog(TeemoCog, "Teemo", 17))
    return MatchupEngine(ROOT, registry=registry)


def test_azir_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Azir's modeled fixture from its generated scaffold."""
    azir = _azir()

    assert azir.maturity is CogMaturity.MODELED_UNVERIFIED
    assert azir.capabilities == DUEL_CAPABILITIES
    assert azir.verification_blockers() == ("COG_MODEL_UNVERIFIED:Azir",)
    assert len(azir.evidence_refs) == 3
    assert all((ROOT / reference).is_file() for reference in azir.evidence_refs)


def test_azir_rotation_uses_locked_q5_w5_e1_r2_values() -> None:
    """Anchor the single-soldier fixture's spell, shield, and attack values."""
    azir = _azir()
    context = _context(item_stats={"AP": Decimal(100)})
    plan = azir.build_action_plan(context)

    assert plan == azir.build_action_plan(context)
    assert plan.model_id == "azir_q5_w5_e1_r2_single_soldier_level13_locked_v1"
    q = _event(plan, "AZIR_Q_CONQUERING_SANDS_1")
    soldier = _event(plan, "AZIR_W_SOLDIER_ATTACK_1")
    shifting = _event(plan, "AZIR_E_SHIFTING_SANDS_COLLISION_FIXTURE")
    ultimate = _event(plan, "AZIR_R_EMPERORS_DIVIDE")

    assert q.outputs[0].amount == Decimal(210)
    assert q.outputs[0].damage_type is DamageType.MAGIC
    assert isinstance(q.outputs[1], StatusOutput)
    assert (q.outputs[1].status, q.outputs[1].duration_ms) == ("CC_SLOW", 1000)
    assert soldier.outputs[0].amount == Decimal(207)
    assert shifting.outputs[0].amount == Decimal(130)
    assert isinstance(shifting.outputs[1], ShieldOutput)
    assert shifting.outputs[1].amount == Decimal(130)
    assert shifting.outputs[1].recipient is EntityId.ACTOR
    assert ultimate.outputs[0].amount == Decimal(475)
    assert isinstance(ultimate.outputs[1], StatusOutput)
    assert ultimate.outputs[1].status == "CC_AIRBORNE"
    assert "AZIR_SINGLE_SOLDIER_COUNT_AND_POSITION_FIXTURE" in plan.blockers
    assert "AZIR_MULTI_TARGET_SOLDIER_PIERCE_NOT_MODELED" in plan.blockers
    assert "AZIR_PASSIVE_SUN_DISC_TURRET_NOT_MODELED" in plan.blockers


def test_azir_ap_attack_speed_and_haste_change_distinct_channels() -> None:
    """Prove AP, attack speed, and haste reach their represented calculations."""
    azir = _azir()
    baseline = azir.build_action_plan(_context())
    powered = azir.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    faster = azir.build_action_plan(
        _context(item_stats={"ATTACK_SPEED": Decimal("0.50")})
    )
    hasted = azir.build_action_plan(
        _context(item_stats={"ABILITY_HASTE": Decimal(100)})
    )

    assert (
        _event(powered, "AZIR_W_SOLDIER_ATTACK_1").outputs[0].amount
        - _event(baseline, "AZIR_W_SOLDIER_ATTACK_1").outputs[0].amount
        == Decimal(65)
    )
    assert len(
        [event for event in faster.events if event.id.startswith("AZIR_W_SOLDIER_ATTACK_")]
    ) > len(
        [event for event in baseline.events if event.id.startswith("AZIR_W_SOLDIER_ATTACK_")]
    )
    assert tuple(
        event.at_ms for event in baseline.events if event.id.startswith("AZIR_Q_CONQUERING_")
    ) == (200, 6200)
    assert tuple(
        event.at_ms for event in hasted.events if event.id.startswith("AZIR_Q_CONQUERING_")
    ) == (200, 3200, 6200)


def test_azir_engagement_item_policy_and_control_are_explicit() -> None:
    """Expose E approach, supported item channels, Q slow, and R knockback."""
    azir = _azir()
    context = _context()
    reaction = azir.build_reaction_plan(context)

    assert azir.engagement_dash_distance(context) == Decimal(1100)
    assert azir.item_candidate_blocker(
        {"id": 1, "stats": {"AP": {}, "ATTACK_SPEED": {}, "ABILITY_HASTE": {}}}
    ) is None
    assert azir.item_candidate_blocker(
        {"id": 2, "stats": {"AD": {}, "MANA": {}, "CRITICAL_STRIKE_CHANCE": {}}}
    ) == "AZIR_ITEM_STAT_NOT_MODELED:2:AD,CRITICAL_STRIKE_CHANCE,MANA"
    slow = reaction.cast_block_windows[0]
    knockback = next(
        window
        for window in reaction.cast_block_windows
        if window.control_type is ControlType.AIRBORNE
    )
    assert slow.control_type is ControlType.SLOW
    assert slow.tenacity_reducible is True
    assert slow.blocked_channels == (ActionChannel.MOVEMENT,)
    assert knockback.tenacity_reducible is False
    assert knockback.blocked_channels == (
        ActionChannel.BASIC_ATTACK,
        ActionChannel.ABILITY,
        ActionChannel.MOVEMENT,
    )


def test_azir_role_reversal_preserves_sources_recipients_and_models() -> None:
    """Keep Azir mechanics attached to the champion in either request role."""
    engine = _engine()
    as_actor = engine.evaluate(MatchupRequest("Azir", "Garen"))
    as_target = engine.evaluate(MatchupRequest("Garen", "Azir"))

    assert as_actor.actor_action_model == as_target.opponent_action_model
    assert as_actor.actor_reaction_model == as_target.opponent_reaction_model
    actor_q = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "AZIR_Q_CONQUERING_SANDS_1"
        and entry.operation == "DAMAGE"
    )
    target_q = next(
        entry
        for entry in as_target.timeline.log
        if entry.event_id == "AZIR_Q_CONQUERING_SANDS_1"
        and entry.operation == "DAMAGE"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert target_q.recipient is EntityId.ACTOR


def test_teemo_blind_cancels_soldiers_without_cancelling_azir_spells() -> None:
    """Treat soldier commands as blindable attacks while preserving spell casts."""
    result = _engine().evaluate(MatchupRequest("Azir", "Teemo"))

    assert any(
        entry.event_id.startswith("AZIR_W_SOLDIER_ATTACK_") and entry.status == "CANCELLED"
        for entry in result.timeline.log
    )
    assert any(
        entry.event_id.startswith("AZIR_W_SOLDIER_ATTACK_")
        and entry.status == "APPLIED"
        and entry.at_ms > 3100
        for entry in result.timeline.log
    )
    for event_id in (
        "AZIR_Q_CONQUERING_SANDS_1",
        "AZIR_E_SHIFTING_SANDS_COLLISION_FIXTURE",
        "AZIR_R_EMPERORS_DIVIDE",
    ):
        assert any(
            entry.event_id == event_id
            and entry.operation == "DAMAGE"
            and entry.status == "APPLIED"
            for entry in result.timeline.log
        )
