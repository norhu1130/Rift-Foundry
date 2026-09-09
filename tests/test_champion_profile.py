import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator

from lol_build.cogs.policy import policy_from_profile
from lol_build.core.timeline import ActionChannel

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/champion-profile.schema.json"
PROFILE_PATH = ROOT / "data/curated/champions/24.json"


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text())
    return Draft202012Validator(schema)


def test_jax_profile_matches_schema_and_all_ability_sources_are_locked() -> None:
    profile = json.loads(PROFILE_PATH.read_text())
    assert list(_validator().iter_errors(profile)) == []
    assert all(ability["source_refs"] for ability in profile["abilities"])
    for ability in profile["abilities"]:
        for source in ability["source_refs"]:
            assert (ROOT / source["locked_path"]).is_file()


def test_profile_does_not_expose_conflicted_spell_resource_costs() -> None:
    profile = json.loads(PROFILE_PATH.read_text())
    assert all("resource_cost_by_rank" not in ability for ability in profile["abilities"])
    assert "patch 26.12" in profile["verification"]["notes"]


def test_curated_damage_and_cooldown_rank_arrays_match_locked_bin() -> None:
    profile = json.loads(PROFILE_PATH.read_text())
    raw = json.loads((ROOT / "data/raw/16.17.1/communitydragon/champions/jax.bin.json").read_text())
    abilities = {ability["id"]: ability for ability in profile["abilities"]}
    cases = {
        "Q_DAMAGE": ("JaxQAbility/JaxQ", "Damage", 5, True),
        "W_DAMAGE": ("JaxWAbility/JaxW", "Damage", 5, True),
        "E_DAMAGE": ("JaxEAbility/JaxE", "BaseDamage", 5, True),
        "R_PASSIVE_DAMAGE": ("JaxRAbility/JaxR", "PassiveBaseDamage", 3, False),
        "R_ACTIVE_DAMAGE": ("JaxRAbility/JaxR", "SwingDamageBase", 3, True),
    }
    for ability_id, (path_suffix, data_name, ranks, compare_cooldown) in cases.items():
        spell = raw[f"Characters/Jax/Spells/{path_suffix}"]["mSpell"]
        data = next(entry for entry in spell["DataValues"] if entry["name"] == data_name)
        expected_damage = [
            str(Decimal(str(value)).normalize()) for value in data["values"][1 : ranks + 1]
        ]
        actual_damage = [
            str(Decimal(value).normalize())
            for value in abilities[ability_id]["base_damage_by_rank"]
        ]
        assert actual_damage == expected_damage
        if compare_cooldown:
            expected_cooldown = [
                str(Decimal(str(value)).normalize())
                for value in spell["cooldownTime"][1 : ranks + 1]
            ]
            actual_cooldown = [
                str(Decimal(value).normalize())
                for value in abilities[ability_id]["cooldown_seconds_by_rank"]
            ]
            assert actual_cooldown == expected_cooldown


def test_policy_is_derived_from_mechanics_not_champion_name_or_id() -> None:
    profile = json.loads(PROFILE_PATH.read_text())
    renamed = deepcopy(profile)
    renamed["champion_id"] = 999
    renamed["display_name"] = "Identity Must Not Be A Rule Key"
    renamed["id"] = "champion_profile_identity_free_v1"

    assert policy_from_profile(profile) == policy_from_profile(renamed)


def test_jax_rotation_keeps_attack_and_ability_channels_separate() -> None:
    profile = json.loads(PROFILE_PATH.read_text())
    policy = policy_from_profile(profile)

    assert policy.relevant_action_channels == (
        ActionChannel.BASIC_ATTACK,
        ActionChannel.ABILITY,
    )
    assert "BASIC_ATTACK_CONTINUOUS_FROM_ATTACK_SPEED" in policy.rotation_rules
    assert "W_ON_COOLDOWN_ATTACK_RESET" in policy.rotation_rules
