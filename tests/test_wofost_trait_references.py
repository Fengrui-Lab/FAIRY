"""Published trait identity and engineered native responses must stay distinguishable."""
import json
from pathlib import Path

import pytest
import yaml

from fairy.apps.farm_world.crop_profiles import get_seed_trait_reference, seed_crop_type
from fairy.apps.farm_world.models import SeedType as AppSeed
from fairy.physics.canopy_biomass_engine import DEFAULT_SEED_GROWTH_PARAMS, SeedType as CanopySeed
from fairy.physics.phenology_engine import DEFAULT_SEED_TYPE_PARAMS, SeedType
from fairy.physics.wofost_profiles import REFERENCE_CULTIVAR_PROFILES, load_cultivar_profile


DATA = Path(__file__).parents[1] / "fairy/physics/data/wofost"


@pytest.mark.parametrize("seed,profile_id", REFERENCE_CULTIVAR_PROFILES.items())
def test_reference_identity_is_usable_without_claiming_native_calibration(seed, profile_id):
    profile = load_cultivar_profile(profile_id)
    assert AppSeed(seed).value == SeedType(seed).value == CanopySeed(seed).value
    assert seed_crop_type(seed) == "soybean"
    assert profile.supported_seed_types == (seed,)
    assert profile.provenance()["validation_status"] == "unvalidated"
    assert profile.trait_reference["mapping_status"] == "engineering_assumption"
    assert profile.trait_reference["evidence_source_ids"]
    info = get_seed_trait_reference(seed)
    assert info["profile_id"] == profile_id
    assert info["profile_sha256"] == profile.sha256
    # Legacy numerical defaults have no fabricated cultivar-specific GDD/RUE fit.
    assert DEFAULT_SEED_TYPE_PARAMS[SeedType(seed)] == DEFAULT_SEED_TYPE_PARAMS[SeedType.STANDARD]
    assert DEFAULT_SEED_GROWTH_PARAMS[CanopySeed(seed)] == DEFAULT_SEED_GROWTH_PARAMS[CanopySeed.STANDARD]


def test_full_native_profiles_change_only_the_declared_trait_from_the_pinned_base():
    document = yaml.safe_load((DATA / "soybean.yaml").read_text())
    baseline = {key: value[0] for key, value in document["CropParameters"]["Varieties"]["Soybean_901"].items()
                if key != "Metadata"}
    assert len(baseline) == 78
    for seed, profile_id in REFERENCE_CULTIVAR_PROFILES.items():
        profile = load_cultivar_profile(profile_id)
        native = profile.parameter_overrides
        assert native.keys() == baseline.keys()
        expected = "TMNFTB" if seed in ("SUINONG42", "KENDOU40") else "DEPNR"
        assert {key for key in native if native[key] != baseline[key]} <= {expected}
        assert native["TSUM1"] == baseline["TSUM1"]
        assert native["TSUM2"] == baseline["TSUM2"]


def test_cold_reference_is_bounded_and_separates_observation_from_assumed_assimilation():
    tolerant = load_cultivar_profile(REFERENCE_CULTIVAR_PROFILES["SUINONG42"])
    sensitive = load_cultivar_profile(REFERENCE_CULTIVAR_PROFILES["KENDOU40"])
    raw = json.loads((DATA / "observations/soybean_cold_contrasts_wang2023_v1.json").read_text())
    for profile, observed in zip((tolerant, sensitive), raw["records"]):
        assert profile.minimum_temperature_factor(4) == pytest.approx(0.2 + 0.6 * observed["table4_D"])
        assert profile.minimum_temperature_factor(-20) == 0
        assert profile.minimum_temperature_factor(12) == 1
        assert profile.minimum_temperature_factor(40) == 1
        for temperature in range(-10, 25):
            assert 0 <= profile.minimum_temperature_factor(temperature) <= 1
    assert tolerant.minimum_temperature_factor(4) > sensitive.minimum_temperature_factor(4)
    assert raw["method"]["treatment_hours"] == 72
    assert raw["use_for_fit"] is False
    assert "not a measured assimilation factor" in raw["caveats"][0]
    for value in (float("nan"), float("inf"), -float("inf")):
        with pytest.raises(ValueError, match="finite"):
            tolerant.minimum_temperature_factor(value)


def test_drought_reference_uses_native_groups_and_preserves_source_ambiguity():
    tolerant = load_cultivar_profile(REFERENCE_CULTIVAR_PROFILES["HEINONG44"])
    sensitive = load_cultivar_profile(REFERENCE_CULTIVAR_PROFILES["HEINONG65"])
    assert tolerant.parameter_overrides["DEPNR"] == 5
    assert sensitive.parameter_overrides["DEPNR"] == 2
    raw = json.loads((DATA / "observations/soybean_drought_contrasts_wang2022_v1.json").read_text())
    assert raw["table_header_observations"]["reported_soil_moisture_pct"][3:5] == [20.8, 20.1]
    assert "Narrative swaps" in raw["table_header_observations"]["method_narrative_conflict"]
    assert raw["use_for_fit"] is False
    assert "not estimated from the paper" in sensitive.trait_reference["native_response"]["mapping"]


def test_reference_metadata_is_copied_and_does_not_select_a_backend():
    profile_id = REFERENCE_CULTIVAR_PROFILES["SUINONG42"]
    profile = load_cultivar_profile(profile_id)
    preview = profile.trait_reference
    preview["classification"] = "invented"
    assert profile.trait_reference["classification"] == "tolerant"
    assert get_seed_trait_reference("STANDARD") is None
    with pytest.raises(ValueError, match="Unknown seed_type"):
        get_seed_trait_reference("UNKNOWN")


def test_one_native_backend_resolves_each_reference_seed_to_its_own_profile(monkeypatch):
    from fairy.physics import wofost_backend as module

    monkeypatch.setattr(module, "_load_runtime", lambda: {"yaml": yaml})
    backend = module.WofostBackend(module.WofostConfig(
        cultivar_profiles=REFERENCE_CULTIVAR_PROFILES,
        require_explicit_cultivar_parameters=True,
    ))
    for seed, profile_id in REFERENCE_CULTIVAR_PROFILES.items():
        assert backend._profile_for_seed(seed).profile_id == profile_id
        actual = backend._crop_parameters(backend._variety_for_seed(seed), seed)
        assert actual == load_cultivar_profile(profile_id).parameter_overrides
    with pytest.raises(ValueError, match="requires explicit cultivar parameters"):
        backend._crop_parameters("Soybean_901", "HEIHE43")
    with pytest.raises(ValueError, match="does not support seed"):
        module.WofostBackend(module.WofostConfig(cultivar_profiles={
            "HEINONG44": REFERENCE_CULTIVAR_PROFILES["HEINONG65"],
        }))


def test_material_serialization_does_not_refill_small_withdrawals():
    from fairy.apps.farm_world.models import InventoryState

    inventory = InventoryState.default()
    for name in ("pesticide_liters", "fertilizer_kg", "fuel_liters"):
        setattr(inventory, name, 5.0 - 0.000001)
    restored = InventoryState.from_dict(inventory.to_dict())
    for name in ("pesticide_liters", "fertilizer_kg", "fuel_liters"):
        assert getattr(restored, name) == 4.999999


def test_native_reference_pairs_have_equal_controls_and_real_stress_response():
    pytest.importorskip("pcse")
    from scripts.audit_wofost_soybean_traits import audit

    result = audit()
    runs = {(row["seed_type"], row["forcing"]): row for row in result["runs"]}
    assert runs["HEINONG44", "drought"]["final_native_TWSO_kg_ha"] > runs[
        "HEINONG65", "drought"]["final_native_TWSO_kg_ha"]
    assert result["validation_status"] == "controlled_model_check_not_field_validation"
