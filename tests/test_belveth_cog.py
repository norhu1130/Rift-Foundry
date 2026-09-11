"""Focused regressions for the locked Bel'Veth champion Cog."""

import json
from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import _apply_cast_blocks
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES
from lol_build.cogs.champions.wip.belveth import BelvethCog
from lol_build.cogs.champions.wip.teemo import TeemoCog
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, EntityId, HealOutput

ROOT = Path(__file__).resolve().parents[1]


def _locked_cog_documents(champion_key: str) -> tuple[dict, dict | None]:
    """Load one champion summary and detailed stat root without the manifest.

    This keeps focused tests isolated while other parallel workers are creating
    modules that the root-owned manifest may already reference.

    :param champion_key: Exact Data Dragon champion identifier.
    :return: Summary document and optional CommunityDragon character root.
    """
    catalog = json.loads(
        (ROOT / "data/raw/16.17.1/en_US/champion.json").read_text(encoding="utf-8")
    )["data"]
    document = catalog[champion_key]
    detail_document = json.loads(
        (
            ROOT
            / "data/raw/16.17.1/communitydragon/champions"
            / f"{champion_key.casefold()}.bin.json"
        ).read_text(encoding="utf-8")
    )
    expected_root = f"Characters/{champion_key}/CharacterRecords/Root".casefold()
    detail_root = next(
        (value for key, value in detail_document.items() if key.casefold() == expected_root),
        None,
    )
    return document, detail_root


def _belveth() -> BelvethCog:
    """Construct Bel'Veth independently of manifest integration.

    :return: Bel'Veth Cog backed by the locked registry documents.
    """
    document, detail_root = _locked_cog_documents("Belveth")
    return BelvethCog(document, detail_root)


def _context(
    *,
    belveth_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
) -> ParticipantContext:
    """Build a level-13 Bel'Veth-versus-Teemo direct-Cog context.

    :param belveth_is_actor: Place Bel'Veth on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Bel'Veth.
    :return: Role-bound deterministic benchmark context.
    """
    belveth = _belveth()
    teemo_document, teemo_detail = _locked_cog_documents("Teemo")
    teemo = TeemoCog(teemo_document, teemo_detail)
    return ParticipantContext(
        EntityId.ACTOR if belveth_is_actor else EntityId.TARGET,
        EntityId.TARGET if belveth_is_actor else EntityId.ACTOR,
        belveth.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Bel'Veth identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def test_belveth_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Bel'Veth from a scaffold and retain all source forms."""
    belveth = _belveth()

    assert belveth.maturity is CogMaturity.MODELED_UNVERIFIED
    assert belveth.capabilities == DUEL_CAPABILITIES
    assert belveth.verification_blockers() == ("COG_MODEL_UNVERIFIED:Belveth",)
    assert all((ROOT / reference).is_file() for reference in belveth.evidence_refs)


def test_belveth_rotation_is_deterministic_and_anchors_locked_formulas() -> None:
    """Anchor Q5, W1, E5, R2, fixed form, and sustain values."""
    belveth = _belveth()
    context = _context(item_stats={"AD": Decimal(100)})

    first = belveth.build_action_plan(context)
    repeated = belveth.build_action_plan(context)
    fixture = _event(first, "BELVETH_TRUE_FORM_FIXTURE")
    q = _event(first, "BELVETH_Q_VOID_SURGE_INITIAL_DIRECTION")
    w = _event(first, "BELVETH_W_ABOVE_AND_BELOW_1")
    e = _event(first, "BELVETH_E_ROYAL_MAELSTROM_STRIKE_1")
    second_attack = _event(first, "BELVETH_BASIC_ATTACK_2")

    assert first == repeated
    assert first.model_id == "belveth_q5_w1_e5_r2_level13_true_form_v1"
    assert fixture.outputs[1].magnitude == Decimal(20)
    assert q.outputs[0].amount == Decimal(20) + Decimal("1.05") * context.snapshot.attack_damage
    assert w.outputs[0].amount == Decimal(230)
    assert e.outputs[0].amount == Decimal(18) + Decimal("0.12") * context.snapshot.attack_damage
    assert isinstance(e.outputs[1], HealOutput)
    assert second_attack.outputs[1].damage_type is DamageType.TRUE
    assert second_attack.outputs[1].amount == Decimal(13)
    assert "BELVETH_R_CORAL_ACTIVE_AND_CURRENT_HP_EXECUTE_NOT_MODELED" in first.blockers
    assert "BELVETH_Q_DIRECTIONAL_COOLDOWNS_NOT_MODELED" in first.blockers


def test_belveth_ad_as_haste_and_hp_change_represented_channels() -> None:
    """Prove offensive cadence, spell frequency, and durability sensitivity."""
    belveth = _belveth()
    baseline_context = _context()
    baseline = belveth.build_action_plan(baseline_context)
    more_ad = belveth.build_action_plan(_context(item_stats={"AD": Decimal(80)}))
    more_speed = belveth.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.80")}))
    more_haste = belveth.build_action_plan(_context(item_stats={"ABILITY_HASTE": Decimal(100)}))
    more_health_context = _context(item_stats={"HP": Decimal(500)})

    assert (
        _event(more_ad, "BELVETH_Q_VOID_SURGE_INITIAL_DIRECTION").outputs[0].amount
        > _event(baseline, "BELVETH_Q_VOID_SURGE_INITIAL_DIRECTION").outputs[0].amount
    )
    baseline_attacks = [
        event for event in baseline.events if event.channel is ActionChannel.BASIC_ATTACK
    ]
    faster_attacks = [
        event for event in more_speed.events if event.channel is ActionChannel.BASIC_ATTACK
    ]
    baseline_e = [event for event in baseline.events if "MAELSTROM_STRIKE" in event.id]
    faster_e = [event for event in more_speed.events if "MAELSTROM_STRIKE" in event.id]
    haste_w = [event for event in more_haste.events if "W_ABOVE_AND_BELOW" in event.id]
    assert len(faster_attacks) > len(baseline_attacks)
    assert len(faster_e) > len(baseline_e)
    assert len(haste_w) == 2
    assert more_health_context.snapshot.max_hp == baseline_context.snapshot.max_hp + Decimal(500)


def test_belveth_reaction_exposes_w_control_and_e_damage_reduction() -> None:
    """Represent W displacement separately from E's defensive channel."""
    reaction = _belveth().build_reaction_plan(_context())

    airborne, slow = reaction.cast_block_windows
    reduction = reaction.damage_windows[0]
    assert airborne.control_type.name == "AIRBORNE"
    assert airborne.tenacity_reducible is False
    assert set(airborne.blocked_channels) == {
        ActionChannel.BASIC_ATTACK,
        ActionChannel.ABILITY,
        ActionChannel.MOVEMENT,
        ActionChannel.ITEM_ACTIVE,
    }
    assert slow.control_type.name == "SLOW"
    assert slow.tenacity_reducible is True
    assert reduction.multiplier == Decimal("0.40")
    assert reduction.recipient is EntityId.ACTOR


def test_belveth_role_reversal_keeps_sources_and_recipients_symmetric() -> None:
    """Bind every outgoing event to Bel'Veth's actual participant side."""
    belveth = _belveth()
    actor_plan = belveth.build_action_plan(_context(belveth_is_actor=True))
    target_plan = belveth.build_action_plan(_context(belveth_is_actor=False))

    actor_q = _event(actor_plan, "BELVETH_Q_VOID_SURGE_INITIAL_DIRECTION")
    target_q = _event(target_plan, "BELVETH_Q_VOID_SURGE_INITIAL_DIRECTION")
    assert actor_q.source is EntityId.ACTOR
    assert target_q.source is EntityId.TARGET
    assert actor_q.outputs[0].recipient is EntityId.TARGET
    assert target_q.outputs[0].recipient is EntityId.ACTOR
    assert actor_q.sequence != target_q.sequence


def test_teemo_blind_cancels_belveth_attacks_but_not_ability_events() -> None:
    """Apply Teemo's blind to attacks without suppressing Q, W, or E."""
    belveth = _belveth()
    context = _context(belveth_is_actor=False)
    teemo_document, teemo_detail = _locked_cog_documents("Teemo")
    teemo = TeemoCog(teemo_document, teemo_detail)
    teemo_context = ParticipantContext(
        EntityId.ACTOR,
        EntityId.TARGET,
        teemo.snapshot(level=13),
        context.snapshot,
        8000,
        3000,
    )
    blocked = _apply_cast_blocks(
        belveth.build_action_plan(context).events,
        teemo.build_reaction_plan(teemo_context).cast_block_windows,
    )

    assert any(event.channel is ActionChannel.BASIC_ATTACK and event.cancelled for event in blocked)
    blocked_plan = type("Plan", (), {"events": blocked})()
    assert not _event(blocked_plan, "BELVETH_Q_VOID_SURGE_INITIAL_DIRECTION").cancelled
    assert not _event(blocked_plan, "BELVETH_E_ROYAL_MAELSTROM_STRIKE_1").cancelled


def test_belveth_item_policy_accepts_only_represented_stat_channels() -> None:
    """Allow cadence and durability while rejecting unmodeled sustain stats."""
    belveth = _belveth()

    assert (
        belveth.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AD": {},
                    "ATTACK_SPEED": {},
                    "ABILITY_HASTE": {},
                    "HP": {},
                    "ARMOR": {},
                },
            }
        )
        is None
    )
    assert (
        belveth.item_candidate_blocker(
            {"id": 2, "stats": {"AP": {}, "CRITICAL_STRIKE_CHANCE": {}, "LIFESTEAL": {}}}
        )
        == "BELVETH_ITEM_STAT_NOT_MODELED:2:AP,CRITICAL_STRIKE_CHANCE,LIFESTEAL"
    )
