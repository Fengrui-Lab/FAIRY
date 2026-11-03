"""Native rotation must preserve official coefficients and the environmental contract."""

from copy import deepcopy
from dataclasses import asdict

import pytest

from fairy.scenarios.management_extensions.engines.crop_rotation_wofost import (
    CropRotationBackend,
)

MAIZE = {
    "crop_name": "maize",
    "variety_name": "Grain_maize_201",
    "reference_density_plants_m2": 20 / 3,
    "external_biotic_coupling": False,
}
SOYBEAN = {
    "crop_name": "soybean",
    "variety_name": "Soybean_901",
    "reference_density_plants_m2": 40,
    "external_biotic_coupling": False,
}


def test_manual_trait_is_rejected_on_initialization_and_same_config_activation():
    with pytest.raises(ValueError, match="unmodified official"):
        CropRotationBackend({**SOYBEAN, "parameter_overrides": {"*": {"DEPNR": 1.0}}})
    backend = CropRotationBackend(SOYBEAN)
    backend.config.parameter_overrides = {"*": {"DEPNR": 1.0}}
    with pytest.raises(ValueError, match="unmodified official"):
        backend._activate_configuration(asdict(backend.config))


@pytest.mark.parametrize(
    "field,value",
    [
        ("initial_available_n_kg_ha", 90.0),
        ("base_soil_n_kg_ha", 90.0),
        ("soil_n_mineralization_fraction", 0.5),
        ("fertilizer_n_fraction", 0.9),
        ("irrigation_efficiency", 0.5),
        ("soil_overrides", {"SMFCF": 0.5}),
        ("site_overrides", {"WAV": 90.0}),
    ],
)
def test_switching_crop_does_not_change_soil_or_input_accounting(field, value):
    backend = CropRotationBackend(MAIZE)
    with pytest.raises(ValueError, match="cannot change soil/site/accounting"):
        backend._activate_configuration({**SOYBEAN, field: value})
    assert asdict(backend.config)["crop_name"] == "maize"
    assert backend._next_seasons == {}


def test_checkpoint_cannot_reintroduce_a_manual_trait():
    backend = CropRotationBackend(SOYBEAN)
    saved = backend.export_state()
    tampered = deepcopy(saved)
    tampered["config"]["parameter_overrides"] = {"*": {"DEPNR": 1.0}}
    with pytest.raises(ValueError, match="unmodified official"):
        CropRotationBackend.from_state(tampered)
