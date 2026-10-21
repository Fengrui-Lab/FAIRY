from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from fairy.physics import PlantingConfig, SeedType, SoilWeatherInput
from fairy.physics import wofost_profiles
from fairy.physics.wofost_backend import WofostBackend, WofostConfig
from fairy.physics.wofost_profiles import load_cultivar_profile


@pytest.fixture
def profile_file(tmp_path: Path, monkeypatch):
    profile_id = "test_heilongjiang_transfer_v1"
    document = {
        "schema_version": 1,
        "profile_id": profile_id,
        "profile_version": "1.0.0",
        "crop_name": "soybean",
        "supported_seed_types": ["HEINONG84"],
        "base_variety": "Soybean_901",
        "transfer_status": "literature_transfer",
        "validation_status": "unvalidated",
        "parameter_overrides": {"TSUM1": 700.0, "TSUM2": 1200.0},
        "sources": [{"title": "Test source, not a calibrated cultivar",
                     "url": "https://example.org/test-source"}],
        "caveats": ["A regional parameter transfer is not HEINONG84 calibration."],
    }
    path = tmp_path / f"{profile_id}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(wofost_profiles, "_PROFILE_DIRECTORY", tmp_path)
    return profile_id, path, document


def test_profile_carries_exact_version_scope_sources_and_copyable_values(profile_file):
    profile_id, _, document = profile_file
    profile = load_cultivar_profile(profile_id)

    assert profile.profile_version == "1.0.0"
    assert profile.applies_to("HEINONG84")
    assert not profile.applies_to("HEIHE43")
    assert not profile.applies_to("*")
    assert profile.provenance()["sources"] == document["sources"]
    assert profile.provenance()["validation_status"] == "unvalidated"
    assert len(profile.sha256) == 64
    changed = profile.parameter_overrides
    changed["TSUM1"] = 1.0
    assert profile.parameter_overrides["TSUM1"] == 700.0


@pytest.mark.parametrize("profile_id", ["missing", "../elsewhere", "/tmp/profile", "x.json", ""])
def test_unknown_or_unsafe_profile_is_not_silently_substituted(profile_file, profile_id):
    with pytest.raises(ValueError, match="profile"):
        load_cultivar_profile(profile_id)


@pytest.mark.parametrize(
    "change, message",
    [
        ({"schema_version": 2}, "schema_version"),
        ({"profile_id": "another"}, "file name"),
        ({"profile_version": ""}, "profile_version"),
        ({"supported_seed_types": ["*"]}, "supported_seed_types"),
        ({"supported_seed_types": ["HEINONG84", "HEINONG84"]}, "supported_seed_types"),
        ({"transfer_status": "calibrated"}, "literature_transfer"),
        ({"validation_status": "calibrated"}, "not local cultivar calibration"),
        ({"sources": []}, "sources"),
        ({"parameter_overrides": {}}, "parameter_overrides"),
    ],
)
def test_profile_rejects_ambiguous_scope_or_missing_provenance(profile_file, change, message):
    profile_id, path, document = profile_file
    document.update(change)
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_cultivar_profile(profile_id)


def test_profile_scope_and_explicit_override_precedence_without_optional_pcse(profile_file):
    profile_id, _, _ = profile_file
    backend = object.__new__(WofostBackend)
    backend.config = WofostConfig(
        cultivar_profile=profile_id,
        parameter_overrides={"*": {"TSUM1": 800.0}, "HEINONG84": {"TSUM1": 900.0}},
    )
    backend._cultivar_profile = load_cultivar_profile(profile_id)
    native = {"TSUMEM": [70.0], "TSUM1": [350.0], "TSUM2": [850.0],
              "TDWI": [10.0], "DVSEND": [2.0]}
    backend._varieties = {"Soybean_901": native}

    hn84 = backend._crop_parameters(backend._variety_for_seed("HEINONG84"), "HEINONG84")
    other = backend._crop_parameters(backend._variety_for_seed("HEIHE43"), "HEIHE43")

    assert hn84["TSUM1"] == 900.0  # Explicit cultivar > explicit '*' > profile.
    assert hn84["TSUM2"] == 1200.0
    assert other["TSUM1"] == 800.0
    assert other["TSUM2"] == 850.0  # HEIHE43 never inherits the HEINONG84 transfer.
    assert native["TSUM2"] == [850.0]


def test_profile_fails_on_unknown_native_parameters(profile_file):
    profile_id, path, document = profile_file
    document["parameter_overrides"]["NONEXISTENT_NATIVE_PARAMETER"] = 1.0
    path.write_text(json.dumps(document), encoding="utf-8")
    backend = object.__new__(WofostBackend)
    backend.config = WofostConfig(cultivar_profile=profile_id)
    backend._cultivar_profile = load_cultivar_profile(profile_id)
    backend._varieties = {"Soybean_901": {"TSUM1": [350.0]}}
    with pytest.raises(ValueError, match="NONEXISTENT_NATIVE_PARAMETER"):
        backend._crop_parameters("Soybean_901", "HEINONG84")


def test_invalid_profile_or_conflicting_base_fails_before_loading_pcse(profile_file, monkeypatch):
    def unexpected_runtime():
        pytest.fail("Invalid profile should fail before importing optional PCSE")

    monkeypatch.setattr("fairy.physics.wofost_backend._load_runtime", unexpected_runtime)
    with pytest.raises(ValueError, match="Unknown WOFOST cultivar profile"):
        WofostBackend({"cultivar_profile": "does_not_exist"})
    with pytest.raises(ValueError, match="conflicts"):
        WofostBackend({"cultivar_profile": profile_file[0],
                       "cultivar_map": {"HEINONG84": "Soybean_906"}})


@pytest.fixture
def native_backend():
    pytest.importorskip("pcse")
    return WofostBackend


def test_native_profile_changes_parameters_for_only_its_scope_and_replays_checkpoint(
    profile_file, native_backend,
):
    from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState

    profile_id, _, _ = profile_file
    backend = native_backend({"cultivar_profile": profile_id})
    physics = FarmPhysicsState(num_ridges=2)
    start = date(2026, 5, 5)
    for rid, seed in enumerate((SeedType.HEINONG84, SeedType.HEIHE43)):
        physics.phenology.plant_ridges([rid], PlantingConfig(planting_date=start, seed_type=seed))
        physics.management.states[rid].planted = True
        physics.management.states[rid].stand_fraction = 1.0
    for offset in range(2):
        day = start + timedelta(days=offset)
        backend.advance_day(
            physics=physics, day=day,
            weather=SoilWeatherInput(day=day, air_temp_mean_c=20.0, air_temp_min_c=14.0,
                                    air_temp_max_c=26.0, rain_mm=2.0,
                                    solar_rad_mj_m2=20.0, wind_ms=2.0),
            actions_by_ridge={}, density_by_ridge={0: 23.0, 1: 23.0},
            ridge_area_m2=294.8,
        )

    snapshot = backend.snapshot()
    hn84 = snapshot["ridges"]["0"]["specification"]
    other = snapshot["ridges"]["1"]["specification"]
    assert hn84["crop_parameters"]["TSUM1"] == 700.0
    assert other["crop_parameters"]["TSUM1"] == 350.0
    assert hn84["cultivar_mapping"] == "literature_transfer"
    assert hn84["calibration"] == "uncalibrated"
    assert hn84["cultivar_profile"]["validation_status"] == "unvalidated"
    assert "cultivar_profile" not in other
    restored = native_backend.from_state(json.loads(json.dumps(backend.export_state())))
    assert restored.snapshot() == snapshot


def test_profile_source_changes_invalidate_native_fingerprint_and_checkpoint(
    profile_file, native_backend,
):
    profile_id, path, document = profile_file
    backend = native_backend({"cultivar_profile": profile_id})
    previous = backend.snapshot()["provenance"]["config_fingerprint"]
    checkpoint = backend.export_state()
    document["sources"][0]["title"] = "Corrected research provenance"
    path.write_text(json.dumps(document), encoding="utf-8")
    changed = native_backend({"cultivar_profile": profile_id})

    assert changed.snapshot()["provenance"]["config_fingerprint"] != previous
    with pytest.raises(ValueError, match="checkpoint cultivar profile"):
        native_backend.from_state(checkpoint)


def test_checkpoint_without_profile_field_remains_compatible(native_backend):
    backend = native_backend()
    checkpoint = copy.deepcopy(backend.export_state())
    checkpoint.pop("cultivar_profile", None)
    checkpoint["config"].pop("cultivar_profile", None)
    restored = native_backend.from_state(checkpoint)
    assert restored.snapshot() == backend.snapshot()
