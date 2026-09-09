import json
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from lol_build.core.combat import DamageType
from lol_build.core.expression import EvaluationContext
from lol_build.items.effects import (
    ItemEffectContext,
    ResolutionStatus,
    initial_effect_state,
    resolution_to_action_event,
    resolution_to_action_events,
    resolve_item_effect,
)

ROOT = Path(__file__).resolve().parents[1]


def _document(item_id: int = 6631) -> dict:
    return json.loads(
        (ROOT / f"data/curated/item_effects/{item_id}.json").read_text(encoding="utf-8")
    )


def _program(program_id: str, item_id: int = 6631) -> dict:
    return next(value for value in _document(item_id)["programs"] if value["id"] == program_id)


def _context(at_ms: int, champions_hit: int = 1, range_class: str = "MELEE"):
    return ItemEffectContext(
        at_ms,
        EvaluationContext(
            13,
            13,
            {("SELF", "TOTAL", "AD"): Decimal(200)},
        ),
        range_class,
        champions_hit,
    )


def test_all_item_effect_documents_are_valid() -> None:
    expression_schema = json.loads(
        (ROOT / "schemas/numeric-expression.schema.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (ROOT / "schemas/item-effect-program.schema.json").read_text(encoding="utf-8")
    )
    registry = Registry().with_resource(
        "https://local.lol-build.example/schemas/numeric-expression.schema.json",
        Resource.from_contents(expression_schema),
    )

    validator = Draft202012Validator(schema, registry=registry)
    for path in sorted((ROOT / "data/curated/item_effects").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert list(validator.iter_errors(document)) == []


def test_every_stateful_item_program_obeys_generic_runtime_boundaries() -> None:
    """Exercise every curated trigger through accumulation, duration, and cooldown edges."""
    for path in sorted((ROOT / "data/curated/item_effects").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for program in document["programs"]:
            stat_keys: set[tuple[str, str, str]] = set()
            multipliers: dict[str, Decimal] = {}
            for operation in program["operations"]:
                stack = [operation["value_expression"]]
                while stack:
                    expression = stack.pop()
                    if expression["type"] == "STAT":
                        stat_keys.add(
                            (
                                expression["entity"],
                                expression["basis"],
                                expression["stat"],
                            )
                        )
                    elif expression["type"] == "ADD":
                        stack.extend(expression["terms"])
                    elif expression["type"] == "MULTIPLY":
                        stack.extend(expression["factors"])
                if multiplier := operation.get("context_multiplier"):
                    multipliers[multiplier] = Decimal(1)

            flags = frozenset(
                [program["required_context_flag"]] if program.get("required_context_flag") else []
            )

            def context(
                at_ms: int,
                *,
                stat_keys: set[tuple[str, str, str]] = stat_keys,
                multipliers: dict[str, Decimal] = multipliers,
                flags: frozenset[str] = flags,
            ) -> ItemEffectContext:
                return ItemEffectContext(
                    at_ms,
                    EvaluationContext(
                        13,
                        13,
                        {key: Decimal(100) for key in stat_keys},
                    ),
                    "MELEE",
                    dynamic_multipliers=multipliers,
                    flags=flags,
                )

            state = initial_effect_state()
            resolution = None
            for _ in range(program.get("proc_every", 1)):
                resolution = resolve_item_effect(program, state, context(1000))
                state = resolution.state
            assert resolution is not None
            assert resolution.status is ResolutionStatus.APPLIED
            assert len(resolution.operations) == len(program["operations"])

            for operation, resolved in zip(
                program["operations"], resolution.operations, strict=True
            ):
                expected_duration = operation.get("range_durations_ms", {}).get(
                    "MELEE", operation.get("duration_ms")
                )
                assert resolved.end_ms == (
                    resolved.start_ms + expected_duration if expected_duration is not None else None
                )

            cooldown_ms = program.get("cooldown_ms", 0)
            if cooldown_ms:
                blocked = resolve_item_effect(
                    program, resolution.state, context(1000 + cooldown_ms - 1)
                )
                assert blocked.status is ResolutionStatus.COOLDOWN
                ready = resolve_item_effect(program, resolution.state, context(1000 + cooldown_ms))
                if program.get("proc_every", 1) == 1:
                    assert ready.status is ResolutionStatus.APPLIED


def test_grievous_wounds_programs_apply_40_percent_for_three_seconds() -> None:
    cases = (
        (3033, "mortal_reminder_grievous_wounds", "PHYSICAL_DAMAGE_TO_CHAMPION"),
        (3123, "executioners_calling_grievous_wounds", "PHYSICAL_DAMAGE_TO_CHAMPION"),
        (3165, "morellonomicon_grievous_wounds", "MAGIC_DAMAGE_TO_CHAMPION"),
        (3916, "oblivion_orb_grievous_wounds", "MAGIC_DAMAGE_TO_CHAMPION"),
        (6609, "chempunk_chainsword_hackshorn", "PHYSICAL_DAMAGE_TO_CHAMPION"),
    )
    for item_id, program_id, trigger in cases:
        program = _program(program_id, item_id)
        resolution = resolve_item_effect(program, initial_effect_state(), _context(100))

        assert program["trigger"] == trigger
        assert resolution.operations[0].amount == Decimal("0.40")
        assert resolution.operations[0].status_or_stat == "HEALING_REDUCTION"
        assert resolution.operations[0].end_ms == 3100


def test_on_hit_items_resolve_fixed_and_ap_scaled_damage() -> None:
    evaluation = EvaluationContext(
        13,
        13,
        {
            ("SELF", "BASE", "AD"): Decimal(120),
            ("SELF", "TOTAL", "AP"): Decimal(200),
        },
    )
    context = ItemEffectContext(0, evaluation, "MELEE")
    expected = (
        (1043, "recurve_bow_sting", Decimal(15), DamageType.PHYSICAL),
        (3091, "wits_end_fray", Decimal(45), DamageType.MAGIC),
        (3115, "nashors_tooth_icathian_bite", Decimal(45), DamageType.MAGIC),
    )
    for item_id, program_id, amount, damage_type in expected:
        resolution = resolve_item_effect(
            _program(program_id, item_id), initial_effect_state(), context
        )

        assert resolution.operations[0].amount == amount
        assert resolution.operations[0].damage_type is damage_type


def test_spellblade_items_require_priming_and_use_locked_patch_coefficients() -> None:
    evaluation = EvaluationContext(
        13,
        13,
        {
            ("SELF", "BASE", "AD"): Decimal(120),
            ("SELF", "TOTAL", "AP"): Decimal(200),
        },
    )
    absent = ItemEffectContext(0, evaluation, "MELEE")
    primed = ItemEffectContext(0, evaluation, "MELEE", flags=frozenset({"SPELLBLADE_READY"}))
    expected = (
        (3057, "sheen_spellblade", Decimal(120), DamageType.PHYSICAL),
        (3100, "lich_bane_spellblade", Decimal(180), DamageType.MAGIC),
        (3078, "trinity_force_spellblade", Decimal(240), DamageType.PHYSICAL),
    )
    for item_id, program_id, amount, damage_type in expected:
        program = _program(program_id, item_id)
        blocked = resolve_item_effect(program, initial_effect_state(), absent)
        resolution = resolve_item_effect(program, initial_effect_state(), primed)

        assert blocked.status is ResolutionStatus.CONDITION_NOT_MET
        assert resolution.operations[0].amount == amount
        assert resolution.operations[0].damage_type is damage_type
        assert resolution.state.cooldown_ready_at_ms[program_id] == 1500

    quicken = resolve_item_effect(
        _program("trinity_force_quicken", 3078), initial_effect_state(), absent
    )
    assert quicken.operations[0].amount == Decimal(20)
    assert quicken.operations[0].end_ms == 2000


def test_stridebreaker_active_resolves_damage_slow_speed_and_cooldown() -> None:
    program = _program("stridebreaker_breaking_shockwave")
    first = resolve_item_effect(program, initial_effect_state(), _context(100, 2))

    assert first.status is ResolutionStatus.APPLIED
    assert [operation.amount for operation in first.operations] == [
        Decimal(160),
        Decimal("0.35"),
        Decimal("0.70"),
    ]
    assert first.operations[1].end_ms == 3100
    assert first.operations[2].decay == "LINEAR"
    assert first.state.cooldown_ready_at_ms[program["id"]] == 15100

    blocked = resolve_item_effect(program, first.state, _context(15099))
    ready = resolve_item_effect(program, first.state, _context(15100))
    assert blocked.status is ResolutionStatus.COOLDOWN
    assert ready.status is ResolutionStatus.APPLIED


def test_stridebreaker_active_damage_compiles_to_timeline_event() -> None:
    resolution = resolve_item_effect(
        _program("stridebreaker_breaking_shockwave"),
        initial_effect_state(),
        _context(100),
    )
    event = resolution_to_action_event(resolution, sequence=7)

    assert event is not None
    assert event.at_ms == 100
    assert len(event.outputs) == 3
    assert event.outputs[0].amount == Decimal(160)


def test_stridebreaker_cleave_excludes_primary_and_applies_ranged_modifier() -> None:
    resolution = resolve_item_effect(
        _program("stridebreaker_cleave"),
        initial_effect_state(),
        _context(200, range_class="RANGED"),
    )

    assert resolution.operations[0].amount == Decimal(40)
    assert resolution.operations[0].excludes_primary_target is True
    assert resolution_to_action_event(resolution, sequence=1) is None


def test_phantom_dancer_grants_persistent_ghosted_status() -> None:
    resolution = resolve_item_effect(
        _program("phantom_dancer_spectral_waltz", 3046),
        initial_effect_state(),
        _context(0),
    )

    operation = resolution.operations[0]
    assert operation.status_or_stat == "GHOSTED"
    assert operation.amount == Decimal(1)
    assert operation.end_ms is None


def test_dead_mans_plate_scales_momentum_and_discharges_on_hit() -> None:
    context = ItemEffectContext(
        4000,
        EvaluationContext(
            13,
            13,
            {
                ("SELF", "TOTAL", "AD"): Decimal(200),
                ("SELF", "BASE", "AD"): Decimal(120),
            },
        ),
        "MELEE",
        dynamic_multipliers={"MOMENTUM_FRACTION": Decimal("0.5")},
    )
    momentum = resolve_item_effect(
        _program("dead_mans_plate_shipwrecker_momentum", 3742),
        initial_effect_state(),
        context,
    )
    hit = resolve_item_effect(
        _program("dead_mans_plate_shipwrecker_hit", 3742),
        momentum.state,
        context,
    )

    assert momentum.operations[0].amount == Decimal(10)
    assert hit.operations[0].amount == Decimal(80)
    assert resolution_to_action_event(hit, sequence=2) is not None


def test_sterak_lifeline_requires_threshold_and_tracks_decay_cooldown() -> None:
    program = _program("sterak_lifeline", 3053)
    evaluation = EvaluationContext(
        13,
        13,
        {
            ("SELF", "BONUS", "HP"): Decimal(1000),
            ("SELF", "TOTAL", "AD"): Decimal(200),
        },
    )
    absent = resolve_item_effect(
        program,
        initial_effect_state(),
        ItemEffectContext(1000, evaluation, "MELEE"),
    )
    applied = resolve_item_effect(
        program,
        initial_effect_state(),
        ItemEffectContext(
            1000,
            evaluation,
            "MELEE",
            flags=frozenset({"SELF_HP_WOULD_FALL_BELOW_30_PERCENT"}),
        ),
    )

    assert absent.status is ResolutionStatus.CONDITION_NOT_MET
    assert applied.operations[0].amount == Decimal(600)
    assert applied.operations[0].end_ms == 5500
    assert applied.operations[0].decay_starts_at_ms == 1750
    assert applied.state.cooldown_ready_at_ms[program["id"]] == 91000


def test_black_cleaver_stacks_refresh_and_expire() -> None:
    program = _program("black_cleaver_carve", 3071)
    state = initial_effect_state()
    for at_ms in (0, 100, 200):
        result = resolve_item_effect(program, state, _context(at_ms))
        state = result.state

    assert result.operations[0].amount == Decimal("0.18")
    assert state.stacks[program["id"]] == 3
    expired = resolve_item_effect(program, state, _context(6200))
    assert expired.operations[0].amount == Decimal("0.06")


def test_bork_third_attack_proc_and_current_health_damage() -> None:
    mist_context = ItemEffectContext(
        0,
        EvaluationContext(
            13,
            13,
            {
                ("SELF", "TOTAL", "AD"): Decimal(200),
                ("TARGET", "CURRENT", "HP"): Decimal(2000),
            },
        ),
        "MELEE",
    )
    mist = resolve_item_effect(
        _program("blade_ruined_king_mists_edge", 3153),
        initial_effect_state(),
        mist_context,
    )
    assert mist.operations[0].amount == Decimal(180)

    claw = _program("blade_ruined_king_clawing_shadows", 3153)
    first = resolve_item_effect(claw, initial_effect_state(), _context(0))
    second = resolve_item_effect(claw, first.state, _context(1000))
    third = resolve_item_effect(claw, second.state, _context(2000))
    fourth = resolve_item_effect(claw, third.state, _context(3000))
    assert first.status is ResolutionStatus.ACCUMULATING
    assert second.status is ResolutionStatus.ACCUMULATING
    assert third.status is ResolutionStatus.APPLIED
    assert third.operations[0].amount == Decimal("0.30")
    assert fourth.status is ResolutionStatus.COOLDOWN


def test_hydra_family_active_ratios_and_cooldowns() -> None:
    for item_id, program_id, expected in (
        (3077, "tiamat_crescent", Decimal(150)),
        (6698, "profane_hydra_heretical_cleave", Decimal(160)),
    ):
        program = _program(program_id, item_id)
        resolution = resolve_item_effect(program, initial_effect_state(), _context(0))
        assert resolution.operations[0].amount == expected
        assert resolution.state.cooldown_ready_at_ms[program_id] == 10000


def test_ravenous_and_titanic_hydra_use_distinct_ad_and_hp_scaling() -> None:
    evaluation = EvaluationContext(
        13,
        13,
        {
            ("SELF", "TOTAL", "AD"): Decimal(200),
            ("SELF", "MAX", "HP"): Decimal(3000),
        },
    )
    melee = ItemEffectContext(0, evaluation, "MELEE")
    ranged = ItemEffectContext(0, evaluation, "RANGED")

    ravenous_passive = resolve_item_effect(
        _program("ravenous_hydra_cleave", 3074), initial_effect_state(), melee
    )
    ravenous_active = resolve_item_effect(
        _program("ravenous_hydra_ravenous_crescent", 3074),
        initial_effect_state(),
        melee,
    )
    titanic_passive = resolve_item_effect(
        _program("titanic_hydra_cleave_primary", 3748),
        initial_effect_state(),
        ranged,
    )
    titanic_active = resolve_item_effect(
        _program("titanic_hydra_titanic_crescent", 3748),
        initial_effect_state(),
        melee,
    )

    assert ravenous_passive.operations[0].amount == Decimal(80)
    assert ravenous_active.operations[0].amount == Decimal(160)
    assert titanic_passive.operations[0].amount == Decimal(15)
    assert titanic_passive.operations[1].amount == Decimal(45)
    assert titanic_active.operations[0].amount == Decimal(120)
    assert titanic_active.operations[1].amount == Decimal(270)


def test_thorns_reflects_damage_and_applies_grievous_wounds_to_attacker() -> None:
    evaluation = EvaluationContext(
        13,
        13,
        {("SELF", "BONUS", "ARMOR"): Decimal(100)},
    )
    context = ItemEffectContext(500, evaluation, "MELEE")
    thornmail = resolve_item_effect(
        _program("thornmail_thorns", 3075), initial_effect_state(), context
    )
    bramble = resolve_item_effect(
        _program("bramble_vest_thorns", 3076), initial_effect_state(), context
    )

    assert thornmail.operations[0].amount == Decimal(30)
    assert thornmail.operations[0].damage_type is DamageType.MAGIC
    assert thornmail.operations[1].amount == Decimal("0.40")
    assert thornmail.operations[1].end_ms == 3500
    assert bramble.operations[0].amount == Decimal(10)


def test_locked_mode_variant_actives_keep_their_own_numbers() -> None:
    evaluation = EvaluationContext(
        13,
        13,
        {
            ("SELF", "TOTAL", "AP"): Decimal(200),
            ("SELF", "BONUS", "AD"): Decimal(100),
            ("SELF", "BONUS", "HP"): Decimal(1000),
            ("SELF", "TOTAL", "HEAL_SHIELD_POWER"): Decimal(0),
            ("TARGET", "MAX", "HP"): Decimal(3000),
        },
    )
    context = ItemEffectContext(0, evaluation, "MELEE")

    shurelya = resolve_item_effect(
        _program("shurelyas_variant_inspiring_speech", 322065),
        initial_effect_state(),
        context,
    )
    locket = resolve_item_effect(
        _program("locket_variant_devotion", 323190), initial_effect_state(), context
    )
    gunblade = resolve_item_effect(
        _program("gunblade_variant_lightning_bolt", 663146),
        initial_effect_state(),
        context,
    )
    stoneplate = resolve_item_effect(
        _program("gargoyle_stoneplate_unbreakable", 663193),
        initial_effect_state(),
        context,
    )
    redemption = resolve_item_effect(
        _program("redemption_variant_intervention", 323107),
        initial_effect_state(),
        context,
    )
    mikael = resolve_item_effect(
        _program("mikaels_variant_purify", 323222),
        initial_effect_state(),
        context,
    )

    assert shurelya.operations[0].amount == Decimal("0.30")
    assert shurelya.operations[0].end_ms == 4000
    assert locket.operations[0].amount == Decimal(325)
    assert gunblade.operations[0].amount == Decimal("320.0588235294117647058823529")
    assert gunblade.operations[1].amount == Decimal("0.40")
    assert gunblade.operations[1].end_ms == 2000
    assert stoneplate.operations[0].amount == Decimal(1100)
    assert stoneplate.operations[1].amount == Decimal("0.25")
    assert redemption.operations[0].start_ms == 2500
    assert redemption.operations[1].amount == Decimal(300)
    assert mikael.operations[0].kind == "REMOVE_STATUS"
    assert mikael.operations[1].amount == Decimal("205.8823529411764705882352941")


def test_persistent_modifier_items_expose_locked_patch_adjustments() -> None:
    expected = (
        (
            3065,
            "spirit_visage_boundless_vitality",
            (Decimal("0.25"), Decimal("0.25")),
            ("HEALING_RECEIVED_INCREASE_PERCENT", "SHIELD_RECEIVED_INCREASE_PERCENT"),
        ),
        (
            3089,
            "rabadons_deathcap_magical_opus",
            (Decimal("0.30"),),
            ("TOTAL_AP_INCREASE_PERCENT",),
        ),
        (
            3110,
            "frozen_heart_winters_caress",
            (Decimal("0.20"),),
            ("ATTACK_SPEED_REDUCTION_PERCENT",),
        ),
        (
            3047,
            "plated_steelcaps_plating",
            (Decimal("0.90"),),
            ("BASIC_ATTACK_DAMAGE_MULTIPLIER",),
        ),
        (
            3009,
            "boots_swiftness_fleetfooted",
            (Decimal("0.25"),),
            ("SLOW_RESISTANCE_PERCENT",),
        ),
        (
            3158,
            "ionian_boots_ionian_insight",
            (Decimal(10),),
            ("SUMMONER_SPELL_HASTE",),
        ),
    )
    for item_id, program_id, amounts, stats in expected:
        resolution = resolve_item_effect(
            _program(program_id, item_id), initial_effect_state(), _context(0)
        )

        assert tuple(operation.amount for operation in resolution.operations) == amounts
        assert tuple(operation.status_or_stat for operation in resolution.operations) == stats


def test_rylais_applies_30_percent_slow_for_one_second() -> None:
    resolution = resolve_item_effect(
        _program("rylais_crystal_scepter_rimefrost", 3116),
        initial_effect_state(),
        _context(250),
    )

    assert resolution.operations[0].amount == Decimal("0.30")
    assert resolution.operations[0].status_or_stat == "CC_SLOW"
    assert resolution.operations[0].end_ms == 1250


def test_damage_ramp_and_conditional_slow_programs_resolve_boundaries() -> None:
    guise = _program("haunting_guise_madness", 3147)
    state = initial_effect_state()
    amounts = []
    for at_ms in (1000, 2000, 3000, 4000):
        resolution = resolve_item_effect(guise, state, _context(at_ms))
        state = resolution.state
        amounts.append(resolution.operations[0].amount)
    assert amounts == [Decimal("0.02"), Decimal("0.04"), Decimal("0.06"), Decimal("0.06")]

    shojin = resolve_item_effect(
        _program("spear_shojin_focused_will", 3161),
        initial_effect_state(),
        _context(0, range_class="RANGED"),
    )
    assert shojin.operations[0].amount == Decimal("0.015")

    serylda_program = _program("seryldas_grudge_bitter_cold", 6694)
    blocked = resolve_item_effect(serylda_program, initial_effect_state(), _context(0))
    applied = resolve_item_effect(
        serylda_program,
        initial_effect_state(),
        ItemEffectContext(
            0,
            EvaluationContext(13, 13, {}),
            "MELEE",
            flags=frozenset({"TARGET_BELOW_50_PERCENT_HP"}),
        ),
    )
    assert blocked.status is ResolutionStatus.CONDITION_NOT_MET
    assert applied.operations[0].amount == Decimal("0.30")


def test_riftmaker_and_giant_slayer_use_context_without_inventing_target_health() -> None:
    evaluation = EvaluationContext(
        13,
        13,
        {("SELF", "BONUS", "HP"): Decimal(1000)},
    )
    rift = resolve_item_effect(
        _program("riftmaker_void_infusion", 4633),
        initial_effect_state(),
        ItemEffectContext(0, evaluation, "MELEE"),
    )
    ldr = resolve_item_effect(
        _program("lord_dominiks_regards_giant_slayer", 3036),
        initial_effect_state(),
        ItemEffectContext(
            0,
            evaluation,
            "MELEE",
            dynamic_multipliers={"TARGET_BONUS_HEALTH_FRACTION_OF_1500": Decimal("0.5")},
        ),
    )

    assert rift.operations[0].amount == Decimal(20)
    assert ldr.operations[0].amount == Decimal("0.075")


def test_phage_and_cosmic_drive_movement_effects_keep_separate_triggers() -> None:
    phage = resolve_item_effect(
        _program("phage_rage", 3044),
        initial_effect_state(),
        _context(0, range_class="RANGED"),
    )
    cosmic = resolve_item_effect(
        _program("cosmic_drive_spelldance", 4629),
        initial_effect_state(),
        _context(0),
    )

    assert phage.operations[0].amount == Decimal(10)
    assert phage.operations[0].end_ms == 2000
    assert cosmic.operations[0].amount == Decimal(20)
    assert cosmic.operations[0].end_ms == 4000


def test_burn_items_expand_to_six_half_second_ticks() -> None:
    evaluation = EvaluationContext(
        13,
        13,
        {
            ("SELF", "TOTAL", "AP"): Decimal(200),
            ("TARGET", "MAX", "HP"): Decimal(3000),
        },
    )
    context = ItemEffectContext(100, evaluation, "MELEE")
    cases = (
        (2508, "fated_ashes_inflame_champion", Decimal("2.5")),
        (2503, "blackfire_torch_baleful_blaze", Decimal(12)),
        (6653, "liandrys_torment_burn", Decimal(30)),
    )
    for item_id, program_id, tick_damage in cases:
        resolution = resolve_item_effect(
            _program(program_id, item_id), initial_effect_state(), context
        )
        events = resolution_to_action_events(resolution, sequence=0)

        assert [event.at_ms for event in events] == [600, 1100, 1600, 2100, 2600, 3100]
        assert all(event.outputs[0].amount == tick_damage for event in events)


def test_quicksilver_variants_remove_cc_and_mercurial_grants_speed() -> None:
    sash = resolve_item_effect(
        _program("quicksilver_sash_quicksilver", 3140),
        initial_effect_state(),
        _context(0),
    )
    scimitar = resolve_item_effect(
        _program("mercurial_scimitar_quicksilver", 3139),
        initial_effect_state(),
        _context(0),
    )

    assert sash.operations[0].kind == "REMOVE_STATUS"
    assert sash.operations[0].status_or_stat == "CROWD_CONTROL_EXCEPT_AIRBORNE"
    assert scimitar.operations[1].amount == Decimal("0.5")
    assert scimitar.operations[1].end_ms == 2000


def test_stasis_single_use_transform_and_locket_level_curve() -> None:
    seekers = resolve_item_effect(
        _program("seekers_armguard_time_stop", 2420),
        initial_effect_state(),
        _context(500),
    )
    zhonyas = resolve_item_effect(
        _program("zhonyas_hourglass_time_stop", 3157),
        initial_effect_state(),
        _context(500),
    )
    locket = resolve_item_effect(
        _program("locket_devotion", 3190),
        initial_effect_state(),
        _context(0),
    )

    assert seekers.operations[0].status_or_stat == "STASIS"
    assert seekers.operations[0].end_ms == 3000
    assert seekers.operations[1].amount == Decimal(2421)
    assert zhonyas.state.cooldown_ready_at_ms[zhonyas.program_id] == 120500
    assert locket.operations[0].amount == Decimal(325)
    event = resolution_to_action_event(locket, sequence=1)
    assert event is not None
    assert event.outputs[0].amount == Decimal(325)


def test_support_actives_resolve_delay_scaling_targets_and_cooldowns() -> None:
    evaluation = EvaluationContext(
        13,
        13,
        {
            ("SELF", "TOTAL", "HEAL_SHIELD_POWER"): Decimal("0.10"),
            ("TARGET", "MAX", "HP"): Decimal(2000),
        },
    )
    redemption = resolve_item_effect(
        _program("redemption_intervention", 3107),
        initial_effect_state(),
        ItemEffectContext(100, evaluation, "MELEE"),
    )
    shurelya = resolve_item_effect(
        _program("shurelyas_inspiring_speech", 2065),
        initial_effect_state(),
        ItemEffectContext(100, evaluation, "MELEE"),
    )

    expected_heal = Decimal("291.1764705882352941176470588") * Decimal("1.10")
    assert redemption.operations[0].amount == expected_heal
    assert redemption.operations[0].start_ms == 2600
    assert redemption.operations[1].amount == Decimal(200)
    redemption_event = resolution_to_action_event(redemption, sequence=1)
    assert redemption_event is not None
    assert redemption_event.at_ms == 2600
    assert shurelya.operations[0].amount == Decimal("0.30")
    assert shurelya.operations[0].end_ms == 4100


def test_mikael_excludes_suppression_and_scales_heal_power() -> None:
    evaluation = EvaluationContext(
        13,
        13,
        {("SELF", "TOTAL", "HEAL_SHIELD_POWER"): Decimal("0.12")},
    )
    result = resolve_item_effect(
        _program("mikaels_blessing_purify", 3222),
        initial_effect_state(),
        ItemEffectContext(0, evaluation, "MELEE"),
    )

    expected = Decimal("205.8823529411764705882352941") * Decimal("1.12")
    assert result.operations[0].status_or_stat == ("CROWD_CONTROL_EXCEPT_AIRBORNE_AND_SUPPRESSION")
    assert result.operations[1].amount == expected


def test_youmuus_range_split_and_out_of_combat_condition() -> None:
    haunt = _program("youmuus_haunt", 3142)
    absent = resolve_item_effect(haunt, initial_effect_state(), _context(0))
    present = resolve_item_effect(
        haunt,
        initial_effect_state(),
        ItemEffectContext(
            0,
            EvaluationContext(13, 13, {("SELF", "TOTAL", "AD"): Decimal(200)}),
            "RANGED",
            flags=frozenset({"OUT_OF_COMBAT"}),
        ),
    )
    active = resolve_item_effect(
        _program("youmuus_wraith_step", 3142),
        initial_effect_state(),
        _context(100, range_class="RANGED"),
    )

    assert absent.status is ResolutionStatus.CONDITION_NOT_MET
    assert present.operations[0].amount == Decimal(10)
    assert active.operations[0].amount == Decimal(15)
    assert active.operations[0].end_ms == 4100
    assert active.operations[1].status_or_stat == "GHOSTED"


def test_randuins_rocketbelt_and_gunblade_active_values() -> None:
    ap_context = ItemEffectContext(
        0,
        EvaluationContext(13, 13, {("SELF", "TOTAL", "AP"): Decimal(200)}),
        "MELEE",
    )
    randuins = resolve_item_effect(
        _program("randuins_humility", 3143), initial_effect_state(), _context(0)
    )
    rocketbelt = resolve_item_effect(
        _program("rocketbelt_supersonic", 3152), initial_effect_state(), ap_context
    )
    gunblade = resolve_item_effect(
        _program("gunblade_lightning_bolt", 3146), initial_effect_state(), ap_context
    )

    assert randuins.operations[0].amount == Decimal("0.70")
    assert randuins.operations[0].end_ms == 2000
    assert rocketbelt.operations[0].kind == "DASH"
    assert rocketbelt.operations[0].amount == Decimal(275)
    assert rocketbelt.operations[1].amount == Decimal(120)
    assert gunblade.operations[0].amount == Decimal("290.0588235294117647058823529")
    assert gunblade.operations[1].amount == Decimal("0.25")


def test_lifeline_family_keeps_damage_type_and_range_differences() -> None:
    evaluation = EvaluationContext(
        13,
        13,
        {
            ("SELF", "BONUS", "AD"): Decimal(100),
            ("SELF", "TOTAL", "AD"): Decimal(200),
        },
    )
    magic_flag = frozenset({"MAGIC_DAMAGE_WOULD_LOWER_SELF_BELOW_30_PERCENT"})
    maw = resolve_item_effect(
        _program("maw_lifeline", 3156),
        initial_effect_state(),
        ItemEffectContext(0, evaluation, "RANGED", flags=magic_flag),
    )
    hexdrinker = resolve_item_effect(
        _program("hexdrinker_lifeline", 3155),
        initial_effect_state(),
        ItemEffectContext(0, evaluation, "MELEE", flags=magic_flag),
    )
    shieldbow = resolve_item_effect(
        _program("immortal_shieldbow_lifeline", 6673),
        initial_effect_state(),
        ItemEffectContext(
            0,
            evaluation,
            "RANGED",
            flags=frozenset({"SELF_HP_WOULD_FALL_BELOW_30_PERCENT"}),
        ),
    )

    assert maw.operations[0].amount == Decimal("262.50")
    assert maw.operations[0].absorbs_damage_types == (DamageType.MAGIC,)
    assert maw.operations[1].status_or_stat == "OMNIVAMP_UNTIL_COMBAT_END"
    assert hexdrinker.operations[0].amount == Decimal(230)
    assert shieldbow.operations[0].amount == Decimal(440)
    assert shieldbow.operations[0].absorbs_damage_types == ()


def test_guardian_angel_and_bloodthirster_state_values() -> None:
    ga_context = ItemEffectContext(
        100,
        EvaluationContext(
            13,
            13,
            {
                ("SELF", "BASE", "HP"): Decimal(2000),
                ("SELF", "MAX", "MANA"): Decimal(1000),
            },
        ),
        "MELEE",
    )
    guardian = resolve_item_effect(
        _program("guardian_angel_rebirth", 3026), initial_effect_state(), ga_context
    )
    bloodthirster = resolve_item_effect(
        _program("bloodthirster_ichorshield", 3072),
        initial_effect_state(),
        ItemEffectContext(
            0,
            EvaluationContext(13, 13, {("SELF", "TOTAL", "AD"): Decimal(200)}),
            "MELEE",
            dynamic_multipliers={"OVERHEAL_FRACTION_OF_CAP": Decimal("0.5")},
        ),
    )

    assert guardian.operations[0].status_or_stat == "STASIS"
    assert guardian.operations[1].kind == "REVIVE"
    assert guardian.operations[1].amount == Decimal(1000)
    assert guardian.operations[1].start_ms == 4100
    assert guardian.operations[2].amount == Decimal(1000)
    assert bloodthirster.operations[0].amount == Decimal(120)
    assert bloodthirster.operations[0].decay_starts_at_ms == 25000
