import json
from decimal import Decimal
from pathlib import Path

from lol_build.core.combat import DamageType
from lol_build.core.expression import EvaluationContext
from lol_build.core.timeline import (
    ActionChannel,
    ActionEvent,
    Combatant,
    CurrentHealthDamageOutput,
    DamageOutput,
    EntityId,
    HealOutput,
    ResistanceReductionOutput,
    ShieldOutput,
    StatusOutput,
    simulate_timeline,
)
from lol_build.items.effects import (
    ItemEffectContext,
    initial_effect_state,
    resolution_to_action_event,
    resolution_to_action_events,
    resolve_item_effect,
)

ROOT = Path(__file__).resolve().parents[1]


def _combatant(entity: EntityId, hp: str, armor: str = "0") -> Combatant:
    return Combatant(entity, Decimal(hp), Decimal(hp), Decimal(armor), Decimal(0))


def test_current_health_damage_uses_hp_at_event_execution_time() -> None:
    events = (
        ActionEvent(
            "hit",
            0,
            0,
            EntityId.ACTOR,
            ActionChannel.BASIC_ATTACK,
            (
                DamageOutput(EntityId.TARGET, Decimal(100), DamageType.TRUE),
                CurrentHealthDamageOutput(EntityId.TARGET, Decimal("0.10"), DamageType.TRUE),
            ),
        ),
    )
    result = simulate_timeline(
        duration_ms=1000,
        horizon_ms=1000,
        actor=_combatant(EntityId.ACTOR, "1000"),
        target=_combatant(EntityId.TARGET, "1000"),
        events=events,
    )

    assert result.target_at_end.current_hp == Decimal(810)


def test_grievous_wounds_reduces_healing_and_expires_at_exact_boundary() -> None:
    program = _item_program(3033, "mortal_reminder_grievous_wounds")
    resolution = resolve_item_effect(
        program,
        initial_effect_state(),
        ItemEffectContext(0, EvaluationContext(13, 13, {}), "MELEE"),
    )
    wound_event = resolution_to_action_event(resolution, sequence=0)
    assert wound_event is not None
    events = (
        wound_event,
        ActionEvent(
            "heal-before-expiry",
            2999,
            1,
            EntityId.TARGET,
            ActionChannel.ABILITY,
            (HealOutput(EntityId.TARGET, Decimal(100)),),
            requires_living_opponent=False,
        ),
        ActionEvent(
            "heal-at-expiry",
            3000,
            2,
            EntityId.TARGET,
            ActionChannel.ABILITY,
            (HealOutput(EntityId.TARGET, Decimal(100)),),
            requires_living_opponent=False,
        ),
    )
    target = Combatant(
        EntityId.TARGET,
        Decimal(1000),
        Decimal(800),
        Decimal(0),
        Decimal(0),
    )
    result = simulate_timeline(
        duration_ms=3000,
        horizon_ms=3000,
        actor=_combatant(EntityId.ACTOR, "1000"),
        target=target,
        events=events,
    )
    heal_logs = [entry for entry in result.log if entry.operation == "HEAL"]

    assert heal_logs[0].hp_delta == Decimal(60)
    assert heal_logs[0].detail == "healing_reduction:0.40"
    assert heal_logs[1].hp_delta == Decimal(100)
    assert result.target_at_end.current_hp == Decimal(960)


def test_thornmail_event_damages_and_wounds_the_basic_attacker() -> None:
    program = _item_program(3075, "thornmail_thorns")
    resolution = resolve_item_effect(
        program,
        initial_effect_state(),
        ItemEffectContext(
            0,
            EvaluationContext(13, 13, {("SELF", "BONUS", "ARMOR"): Decimal(100)}),
            "MELEE",
        ),
    )
    thorns_event = resolution_to_action_event(resolution, sequence=0)
    assert thorns_event is not None
    heal_event = ActionEvent(
        "attacker-heal",
        100,
        1,
        EntityId.TARGET,
        ActionChannel.ABILITY,
        (HealOutput(EntityId.TARGET, Decimal(100)),),
        requires_living_opponent=False,
    )
    result = simulate_timeline(
        duration_ms=1000,
        horizon_ms=1000,
        actor=_combatant(EntityId.ACTOR, "1000"),
        target=Combatant(
            EntityId.TARGET,
            Decimal(1000),
            Decimal(900),
            Decimal(0),
            Decimal(0),
        ),
        events=(thorns_event, heal_event),
    )

    assert result.target_at_end.current_hp == Decimal(930)
    assert result.target_at_end.statuses == ("HEALING_REDUCTION",)


def test_persistent_item_modifiers_change_timeline_outputs() -> None:
    spirit_resolution = resolve_item_effect(
        _item_program(3065, "spirit_visage_boundless_vitality"),
        initial_effect_state(),
        ItemEffectContext(0, EvaluationContext(13, 13, {}), "MELEE"),
    )
    steelcaps_resolution = resolve_item_effect(
        _item_program(3047, "plated_steelcaps_plating"),
        initial_effect_state(),
        ItemEffectContext(0, EvaluationContext(13, 13, {}), "MELEE"),
    )
    spirit_event = resolution_to_action_event(spirit_resolution, sequence=0)
    steelcaps_event = resolution_to_action_event(steelcaps_resolution, sequence=1)
    assert spirit_event is not None
    assert steelcaps_event is not None
    events = (
        spirit_event,
        steelcaps_event,
        ActionEvent(
            "heal-and-shield",
            100,
            2,
            EntityId.ACTOR,
            ActionChannel.ABILITY,
            (
                HealOutput(EntityId.ACTOR, Decimal(100)),
                ShieldOutput(EntityId.ACTOR, Decimal(100)),
            ),
            requires_living_opponent=False,
        ),
        ActionEvent(
            "incoming-attack",
            200,
            3,
            EntityId.TARGET,
            ActionChannel.BASIC_ATTACK,
            (DamageOutput(EntityId.ACTOR, Decimal(100), DamageType.TRUE),),
        ),
    )
    actor = Combatant(
        EntityId.ACTOR,
        Decimal(1000),
        Decimal(500),
        Decimal(0),
        Decimal(0),
    )
    result = simulate_timeline(
        duration_ms=1000,
        horizon_ms=1000,
        actor=actor,
        target=_combatant(EntityId.TARGET, "1000"),
        events=events,
    )

    heal_log = next(entry for entry in result.log if entry.operation == "HEAL")
    damage_log = next(entry for entry in result.log if entry.operation == "DAMAGE")
    assert heal_log.hp_delta == Decimal(125)
    assert damage_log.raw_amount == Decimal(90)
    assert damage_log.shield_absorbed == Decimal(90)
    assert result.actor_at_end.current_hp == Decimal(625)
    assert result.actor_at_end.shield == Decimal(35)


def test_swiftness_boots_reduce_slow_magnitude_in_audit_log() -> None:
    boots = resolve_item_effect(
        _item_program(3009, "boots_swiftness_fleetfooted"),
        initial_effect_state(),
        ItemEffectContext(0, EvaluationContext(13, 13, {}), "MELEE"),
    )
    slow = resolve_item_effect(
        _item_program(3116, "rylais_crystal_scepter_rimefrost"),
        initial_effect_state(),
        ItemEffectContext(100, EvaluationContext(13, 13, {}), "MELEE"),
    )
    boots_event = resolution_to_action_event(boots, sequence=0, source=EntityId.TARGET)
    slow_event = resolution_to_action_event(slow, sequence=1)
    assert boots_event is not None
    assert slow_event is not None
    result = simulate_timeline(
        duration_ms=1000,
        horizon_ms=1000,
        actor=_combatant(EntityId.ACTOR, "1000"),
        target=_combatant(EntityId.TARGET, "1000"),
        events=(boots_event, slow_event),
    )

    status_log = next(entry for entry in result.log if entry.operation == "STATUS")
    assert status_log.detail == "CC_SLOW:1100:magnitude=0.2250"


def test_spell_shield_blocks_every_output_of_one_ability_then_is_consumed() -> None:
    resolution = resolve_item_effect(
        _item_program(3102, "banshees_veil_annul"),
        initial_effect_state(),
        ItemEffectContext(0, EvaluationContext(13, 13, {}), "MELEE"),
    )
    shield_event = resolution_to_action_event(resolution, sequence=0)
    assert shield_event is not None
    events = (
        shield_event,
        ActionEvent(
            "blocked-spell",
            100,
            1,
            EntityId.TARGET,
            ActionChannel.ABILITY,
            (
                DamageOutput(EntityId.ACTOR, Decimal(100), DamageType.TRUE),
                StatusOutput(EntityId.ACTOR, "CC_SILENCE", 1000),
            ),
        ),
        ActionEvent(
            "next-spell",
            200,
            2,
            EntityId.TARGET,
            ActionChannel.ABILITY,
            (DamageOutput(EntityId.ACTOR, Decimal(100), DamageType.TRUE),),
        ),
    )
    result = simulate_timeline(
        duration_ms=1000,
        horizon_ms=1000,
        actor=_combatant(EntityId.ACTOR, "1000"),
        target=_combatant(EntityId.TARGET, "1000"),
        events=events,
    )

    blocked = [entry for entry in result.log if entry.status == "BLOCKED_SPELL_SHIELD"]
    assert len(blocked) == 2
    assert result.actor_at_end.current_hp == Decimal(900)
    assert result.actor_at_end.statuses == ()


def test_collector_execute_uses_health_threshold_as_discrete_event() -> None:
    resolution = resolve_item_effect(
        _item_program(6676, "collector_death"),
        initial_effect_state(),
        ItemEffectContext(0, EvaluationContext(13, 13, {}), "MELEE"),
    )
    execute_event = resolution_to_action_event(resolution, sequence=0)
    assert execute_event is not None
    target = Combatant(
        EntityId.TARGET,
        Decimal(1000),
        Decimal(50),
        Decimal(0),
        Decimal(0),
    )
    result = simulate_timeline(
        duration_ms=100,
        horizon_ms=100,
        actor=_combatant(EntityId.ACTOR, "1000"),
        target=target,
        events=(execute_event,),
    )

    assert result.target_at_end.dead is True
    assert result.target_at_end.current_hp == 0
    assert result.log[-1].operation == "EXECUTE"


def test_armor_reduction_affects_later_damage_and_expires_at_boundary() -> None:
    reduction = ResistanceReductionOutput(
        EntityId.TARGET,
        "ARMOR",
        Decimal("0.10"),
        5,
        1000,
        "carve",
    )
    events = (
        ActionEvent(
            "first",
            0,
            0,
            EntityId.ACTOR,
            ActionChannel.ABILITY,
            (DamageOutput(EntityId.TARGET, Decimal(100), DamageType.PHYSICAL), reduction),
        ),
        ActionEvent(
            "second",
            999,
            1,
            EntityId.ACTOR,
            ActionChannel.ABILITY,
            (DamageOutput(EntityId.TARGET, Decimal(100), DamageType.PHYSICAL),),
        ),
        ActionEvent(
            "third",
            1000,
            2,
            EntityId.ACTOR,
            ActionChannel.ABILITY,
            (DamageOutput(EntityId.TARGET, Decimal(100), DamageType.PHYSICAL),),
        ),
    )
    result = simulate_timeline(
        duration_ms=1000,
        horizon_ms=1000,
        actor=_combatant(EntityId.ACTOR, "1000"),
        target=_combatant(EntityId.TARGET, "1000", "100"),
        events=events,
    )
    damages = [entry for entry in result.log if entry.operation == "DAMAGE"]

    assert damages[0].post_mitigation_amount == Decimal(50)
    assert damages[1].post_mitigation_amount > Decimal(50)
    assert damages[2].post_mitigation_amount == Decimal(50)


def _item_program(item_id: int, program_id: str) -> dict:
    document = json.loads((ROOT / f"data/curated/item_effects/{item_id}.json").read_text())
    return next(program for program in document["programs"] if program["id"] == program_id)


def _active_event(item_id: int, program_id: str, at_ms: int, sequence: int):
    program = _item_program(item_id, program_id)
    resolution = resolve_item_effect(
        program,
        initial_effect_state(),
        ItemEffectContext(at_ms, EvaluationContext(13, 13, {}), "MELEE"),
    )
    event = resolution_to_action_event(resolution, sequence=sequence)
    assert event is not None
    return event


def test_stasis_blocks_incoming_damage_and_ends_at_exact_boundary() -> None:
    events = (
        _active_event(3157, "zhonyas_hourglass_time_stop", 0, 0),
        ActionEvent(
            "blocked",
            100,
            1,
            EntityId.TARGET,
            ActionChannel.ABILITY,
            (DamageOutput(EntityId.ACTOR, Decimal(100), DamageType.TRUE),),
        ),
        ActionEvent(
            "applied",
            2500,
            2,
            EntityId.TARGET,
            ActionChannel.ABILITY,
            (DamageOutput(EntityId.ACTOR, Decimal(100), DamageType.TRUE),),
        ),
    )
    result = simulate_timeline(
        duration_ms=3000,
        horizon_ms=3000,
        actor=_combatant(EntityId.ACTOR, "1000"),
        target=_combatant(EntityId.TARGET, "1000"),
        events=events,
    )

    damage_logs = [entry for entry in result.log if entry.operation == "DAMAGE"]
    assert damage_logs[0].status == "IMMUNE_STASIS"
    assert damage_logs[1].status == "APPLIED"
    assert result.actor_at_end.current_hp == Decimal(900)


def test_quicksilver_removes_cc_but_preserves_airborne() -> None:
    event = _active_event(3140, "quicksilver_sash_quicksilver", 0, 0)
    actor = Combatant(
        EntityId.ACTOR,
        Decimal(1000),
        Decimal(1000),
        Decimal(0),
        Decimal(0),
        statuses=(("CC_SILENCE", 5000), ("CC_AIRBORNE", 5000)),
    )
    result = simulate_timeline(
        duration_ms=1000,
        horizon_ms=1000,
        actor=actor,
        target=_combatant(EntityId.TARGET, "1000"),
        events=(event,),
    )

    assert result.actor_at_end.statuses == ("CC_AIRBORNE",)


def test_typed_shield_absorbs_only_matching_damage_and_expires() -> None:
    events = (
        ActionEvent(
            "magic-shield",
            0,
            0,
            EntityId.ACTOR,
            ActionChannel.ITEM_ACTIVE,
            (
                ShieldOutput(
                    EntityId.ACTOR,
                    Decimal(100),
                    duration_ms=1000,
                    damage_types=(DamageType.MAGIC,),
                ),
            ),
            requires_living_opponent=False,
        ),
        ActionEvent(
            "physical",
            100,
            1,
            EntityId.TARGET,
            ActionChannel.BASIC_ATTACK,
            (DamageOutput(EntityId.ACTOR, Decimal(100), DamageType.PHYSICAL),),
        ),
        ActionEvent(
            "magic",
            200,
            2,
            EntityId.TARGET,
            ActionChannel.ABILITY,
            (DamageOutput(EntityId.ACTOR, Decimal(100), DamageType.MAGIC),),
        ),
    )
    result = simulate_timeline(
        duration_ms=1200,
        horizon_ms=1200,
        actor=_combatant(EntityId.ACTOR, "1000"),
        target=_combatant(EntityId.TARGET, "1000"),
        events=events,
    )
    physical, magic = [entry for entry in result.log if entry.operation == "DAMAGE"]

    assert physical.shield_absorbed == Decimal(0)
    assert magic.shield_absorbed == Decimal(100)
    assert result.actor_at_end.current_hp == Decimal(900)
    assert result.actor_at_end.shield == Decimal(0)


def test_decaying_shield_uses_event_time_remaining_amount() -> None:
    events = (
        ActionEvent(
            "decay",
            0,
            0,
            EntityId.ACTOR,
            ActionChannel.ITEM_ACTIVE,
            (ShieldOutput(EntityId.ACTOR, Decimal(100), 1000, (), 500),),
            requires_living_opponent=False,
        ),
        ActionEvent(
            "hit",
            750,
            1,
            EntityId.TARGET,
            ActionChannel.ABILITY,
            (DamageOutput(EntityId.ACTOR, Decimal(60), DamageType.TRUE),),
        ),
    )
    result = simulate_timeline(
        duration_ms=750,
        horizon_ms=750,
        actor=_combatant(EntityId.ACTOR, "1000"),
        target=_combatant(EntityId.TARGET, "1000"),
        events=events,
    )
    damage = next(entry for entry in result.log if entry.operation == "DAMAGE")

    assert damage.shield_absorbed == Decimal(50)
    assert result.actor_at_end.current_hp == Decimal(990)


def test_guardian_angel_resolution_revives_dead_source_after_four_seconds() -> None:
    program = _item_program(3026, "guardian_angel_rebirth")
    resolution = resolve_item_effect(
        program,
        initial_effect_state(),
        ItemEffectContext(
            0,
            EvaluationContext(
                13,
                13,
                {
                    ("SELF", "BASE", "HP"): Decimal(2000),
                    ("SELF", "MAX", "MANA"): Decimal(1000),
                },
            ),
            "MELEE",
        ),
    )
    compiled = resolution_to_action_events(resolution, sequence=0)
    revive_event = compiled[1]
    result = simulate_timeline(
        duration_ms=4000,
        horizon_ms=4000,
        actor=Combatant(
            EntityId.ACTOR,
            Decimal(2500),
            Decimal(0),
            Decimal(0),
            Decimal(0),
        ),
        target=_combatant(EntityId.TARGET, "1000"),
        events=(revive_event,),
    )

    assert [event.at_ms for event in compiled] == [0, 4000]
    assert revive_event.requires_source_alive is False
    assert result.actor_at_end.current_hp == Decimal(1000)
    assert result.actor_at_end.dead is False
