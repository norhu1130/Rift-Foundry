"""Focused regressions for the locked Amumu champion Cog."""

from decimal import Decimal
from pathlib import Path

from lol_build.application.matchup import MatchupEngine, MatchupRequest
from lol_build.cogs import CogMaturity, ParticipantContext
from lol_build.cogs.base import DUEL_CAPABILITIES, CogCapability
from lol_build.cogs.registry import create_default_registry
from lol_build.core.combat import DamageType
from lol_build.core.timeline import ActionChannel, EntityId, StatusOutput

ROOT = Path(__file__).resolve().parents[1]


def _context(
    *,
    amumu_is_actor: bool = True,
    item_stats: dict[str, Decimal] | None = None,
    opponent_health: Decimal = Decimal(0),
) -> ParticipantContext:
    """Build a level-13 Amumu-versus-Teemo direct-Cog context.

    :param amumu_is_actor: Place Amumu on the actor side when true.
    :param item_stats: Optional permanent item modifiers applied to Amumu.
    :param opponent_health: Additional maximum health applied to Teemo.
    :return: Role-bound deterministic benchmark context.
    """
    registry = create_default_registry(ROOT)
    amumu = registry.require_cog("Amumu")
    teemo = registry.require_cog("Teemo")
    return ParticipantContext(
        EntityId.ACTOR if amumu_is_actor else EntityId.TARGET,
        EntityId.TARGET if amumu_is_actor else EntityId.ACTOR,
        amumu.snapshot(level=13, item_stats=item_stats),
        teemo.snapshot(level=13, item_stats={"HP": opponent_health}),
        8000,
        3000,
    )


def _event(plan: object, event_id: str):
    """Resolve one event by its stable Amumu identifier.

    :param plan: Action plan exposing an ``events`` tuple.
    :param event_id: Exact event identifier to locate.
    :return: Matching action event.
    """
    return next(event for event in plan.events if event.id == event_id)


def _events_with_prefix(plan: object, prefix: str):
    """Collect action events sharing an Amumu identifier prefix.

    :param plan: Action plan exposing an ``events`` tuple.
    :param prefix: Event identifier prefix to select.
    :return: Matching events in their plan order.
    """
    return tuple(event for event in plan.events if event.id.startswith(prefix))


def test_amumu_declares_modeled_capabilities_and_locked_evidence() -> None:
    """Distinguish Amumu from a scaffold and retain all source forms."""
    amumu = create_default_registry(ROOT).require_cog("Amumu")

    assert amumu.maturity is CogMaturity.MODELED_UNVERIFIED
    assert amumu.capabilities == DUEL_CAPABILITIES | {CogCapability.MULTI_TARGET}
    assert amumu.verification_blockers() == ("COG_MODEL_UNVERIFIED:Amumu",)
    assert amumu.evidence_refs == (
        "data/raw/16.17.1/en_US/champion/Amumu.json",
        "data/raw/16.17.1/communitydragon/champions/32.json",
        "data/raw/16.17.1/communitydragon/champions/amumu.bin.json",
    )
    assert all((ROOT / reference).is_file() for reference in amumu.evidence_refs)


def test_amumu_rotation_is_deterministic_and_uses_locked_formulas() -> None:
    """Anchor E5/Q5/W1/R2 and Cursed Touch outputs to locked values."""
    amumu = create_default_registry(ROOT).require_cog("Amumu")
    context = _context(item_stats={"AP": Decimal(100)}, opponent_health=Decimal(500))

    first = amumu.build_action_plan(context)
    repeated = amumu.build_action_plan(context)
    q1 = _event(first, "AMUMU_Q_BANDAGE_TOSS_1")
    q2 = _event(first, "AMUMU_Q_BANDAGE_TOSS_2")
    ultimate = _event(first, "AMUMU_R_CURSE_OF_THE_SAD_MUMMY")
    tantrum = _event(first, "AMUMU_E_TANTRUM_1")
    despair = _event(first, "AMUMU_W_DESPAIR_TICK_1")
    q_amount = Decimal(255)
    r_amount = Decimal(380)
    e_amount = Decimal(235)
    w_amount = Decimal(5) + Decimal("0.0075") * context.opponent_snapshot.max_hp

    assert first == repeated
    assert first.model_id == "amumu_e5_q5_w1_r2_level13_locked_v1"
    assert q1.outputs[0].amount == q_amount
    assert q1.outputs[0].damage_type is DamageType.MAGIC
    assert isinstance(q1.outputs[1], StatusOutput)
    assert [output.amount for output in q2.outputs[:2]] == [q_amount, Decimal("25.50")]
    assert isinstance(ultimate.outputs[0], StatusOutput)
    assert [output.amount for output in ultimate.outputs[1:3]] == [
        r_amount,
        Decimal(38),
    ]
    assert [output.amount for output in tantrum.outputs] == [e_amount, Decimal("23.50")]
    assert [output.amount for output in despair.outputs] == [w_amount, w_amount / 10]
    assert "AMUMU_E_INCOMING_HIT_COOLDOWN_REFUND_NOT_MODELED" in first.blockers
    assert "AMUMU_W_TOGGLE_MANA_AND_DEACTIVATION_NOT_MODELED" in first.blockers


def test_amumu_ap_attack_speed_haste_and_defenses_reach_their_channels() -> None:
    """Prove offensive cadence, cooldown, and defensive snapshots stay live."""
    amumu = create_default_registry(ROOT).require_cog("Amumu")
    baseline_context = _context()
    baseline = amumu.build_action_plan(baseline_context)
    powered = amumu.build_action_plan(_context(item_stats={"AP": Decimal(100)}))
    faster = amumu.build_action_plan(_context(item_stats={"ATTACK_SPEED": Decimal("0.50")}))
    hasted = amumu.build_action_plan(_context(item_stats={"ABILITY_HASTE": Decimal(100)}))
    defended = amumu.snapshot(
        level=13,
        item_stats={"ARMOR": Decimal(50), "MAGIC_RESISTANCE": Decimal(40)},
    )

    assert (
        _event(powered, "AMUMU_E_TANTRUM_1").outputs[0].amount
        - _event(baseline, "AMUMU_E_TANTRUM_1").outputs[0].amount
        == 50
    )
    assert len(_events_with_prefix(faster, "AMUMU_BASIC_ATTACK_")) > len(
        _events_with_prefix(baseline, "AMUMU_BASIC_ATTACK_")
    )
    assert [event.at_ms for event in _events_with_prefix(hasted, "AMUMU_E_TANTRUM_")] == [
        1700,
        4200,
        6700,
    ]
    assert defended.armor == baseline_context.snapshot.armor + 50
    assert defended.magic_resistance == baseline_context.snapshot.magic_resistance + 40


def test_amumu_reaction_models_two_bandages_and_ultimate_stun() -> None:
    """Expose three tenacity-reducible stuns without role assumptions."""
    amumu = create_default_registry(ROOT).require_cog("Amumu")
    reaction = amumu.build_reaction_plan(_context())

    assert [window.id for window in reaction.cast_block_windows] == [
        "amumu_q1_stun",
        "amumu_r_stun",
        "amumu_q2_stun",
    ]
    assert [window.end_ms - window.start_ms for window in reaction.cast_block_windows] == [
        1000,
        1500,
        1000,
    ]
    assert all(window.control_type.value == "STUN" for window in reaction.cast_block_windows)
    assert all(window.tenacity_reducible for window in reaction.cast_block_windows)
    assert all(
        window.blocked_channels
        == (
            ActionChannel.BASIC_ATTACK,
            ActionChannel.ABILITY,
            ActionChannel.MOVEMENT,
            ActionChannel.ITEM_ACTIVE,
        )
        for window in reaction.cast_block_windows
    )
    assert amumu.engagement_dash_distance(_context()) == 1100


def test_amumu_role_reversal_preserves_models_and_recipients() -> None:
    """Keep Amumu's action and reaction behavior participant-neutral."""
    engine = MatchupEngine(ROOT)
    as_actor = engine.evaluate(MatchupRequest("Amumu", "Garen"))
    as_opponent = engine.evaluate(MatchupRequest("Garen", "Amumu"))

    assert as_actor.actor_action_model == as_opponent.opponent_action_model
    assert as_actor.actor_reaction_model == as_opponent.opponent_reaction_model
    actor_q = next(
        entry
        for entry in as_actor.timeline.log
        if entry.event_id == "AMUMU_Q_BANDAGE_TOSS_1" and entry.operation == "DAMAGE"
    )
    opponent_q = next(
        entry
        for entry in as_opponent.timeline.log
        if entry.event_id == "AMUMU_Q_BANDAGE_TOSS_1" and entry.operation == "DAMAGE"
    )
    assert actor_q.recipient is EntityId.TARGET
    assert opponent_q.recipient is EntityId.ACTOR


def test_teemo_blind_cancels_amumu_attacks_but_not_abilities() -> None:
    """Keep Amumu's spell damage independent from the blinded attack channel."""
    result = MatchupEngine(ROOT).evaluate(MatchupRequest("Teemo", "Amumu"))

    assert any(
        entry.event_id.startswith("AMUMU_BASIC_ATTACK_CURSED_TOUCH_")
        and entry.action_channel is ActionChannel.BASIC_ATTACK
        and entry.status == "CANCELLED"
        for entry in result.timeline.log
    )
    for event_id in (
        "AMUMU_Q_BANDAGE_TOSS_1",
        "AMUMU_R_CURSE_OF_THE_SAD_MUMMY",
        "AMUMU_E_TANTRUM_1",
        "AMUMU_W_DESPAIR_TICK_1",
    ):
        assert any(
            entry.event_id == event_id and entry.operation == "DAMAGE" and entry.status == "APPLIED"
            for entry in result.timeline.log
        )


def test_amumu_item_policy_accepts_live_stats_and_rejects_model_gaps() -> None:
    """Allow represented stats while blocking resource and sustain gaps."""
    amumu = create_default_registry(ROOT).require_cog("Amumu")

    assert (
        amumu.item_candidate_blocker(
            {
                "id": 1,
                "stats": {
                    "AP": {},
                    "AD": {},
                    "ATTACK_SPEED": {},
                    "ABILITY_HASTE": {},
                    "HP": {},
                    "ARMOR": {},
                    "MAGIC_RESISTANCE": {},
                },
            }
        )
        is None
    )
    assert (
        amumu.item_candidate_blocker(
            {"id": 2, "stats": {"HEAL_SHIELD_POWER": {}, "MANA": {}, "OMNIVAMP": {}}}
        )
        == "AMUMU_ITEM_STAT_NOT_MODELED:2:MANA"
    )
