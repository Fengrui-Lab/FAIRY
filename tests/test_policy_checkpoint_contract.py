"""Frozen native prefixes cannot overwrite a different declared scenario environment."""

from copy import deepcopy

import pytest

from fairy.scenarios.management_extensions.L4.scenario_maize_soybean_policy_choice import (
    ScenarioMaizeSoybeanPolicyChoice,
)


@pytest.mark.parametrize("change", ["field", "soil", "storage", "harvest"])
def test_initial_checkpoint_rejects_different_declared_environment_without_restoring(
    change,
):
    class Changed(ScenarioMaizeSoybeanPolicyChoice):
        field = deepcopy(ScenarioMaizeSoybeanPolicyChoice.field)
        backend_options = deepcopy(ScenarioMaizeSoybeanPolicyChoice.backend_options)

    if change == "field":
        Changed.field["ridge_count"] = 8
    elif change == "soil":
        Changed.backend_options["initial_available_n_kg_ha"] = 51.0
    elif change == "storage":
        Changed.safe_moisture_pct = 13.0
    else:
        Changed.maximum_harvest_moisture_pct = 24.0
    scene = Changed(calibrating=True)
    scene.init_and_populate_apps()
    from fairy.controllers.engine import Engine

    Engine(None, scene)
    before = scene.verification_state()
    with pytest.raises(ValueError, match="declared initial"):
        scene._load_initial_checkpoint()
    assert scene.verification_state() == before


def test_default_checkpoint_loads_actual_native_crop_without_capturing_tools():
    from fairy.types import EventRegisterer

    with EventRegisterer.capture_mode() as events:
        scene = ScenarioMaizeSoybeanPolicyChoice(calibrating=True)
        scene.setup()
    assert events == []
    farm = scene.cycle.farm
    assert farm.num_ridges == 16
    assert len(farm.physics.crop_backend._runs) == 16
    assert farm._inventory.warehouse_grain_kg == 0
    assert all(
        r.planted and not r.harvested and r.growth_stage == "REPRODUCTIVE"
        for r in farm._ridges
    )
    assert scene.start_time == 1721802900.0


def test_usd_binding_preserves_original_cny_source_manifest_and_native_payload():
    import hashlib
    import json
    from pathlib import Path

    asset = json.loads(
        (
            Path(__file__).parents[1]
            / "fairy/scenarios/management_extensions/data/checkpoints/maize_2024_growing_policy_takeover.json"
        ).read_text()
    )
    historical = asset["manifest"]["source_manifest"]
    binding = asset["manifest"]["usd_economic_binding"]
    assert historical["input_signature"]["prices"]["currency"] == "CNY"
    assert binding["input_signature"]["prices"]["currency"] == "USD"
    assert (
        asset["payload"]["source_input_fingerprint"]
        == historical["input_fingerprint"]
        == binding["source_input_fingerprint"]
    )
    canonical = json.dumps(
        asset["payload"], sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    assert (
        hashlib.sha256(canonical).hexdigest()
        == ScenarioMaizeSoybeanPolicyChoice.checkpoint_payload_sha256
    )


def test_different_usd_prices_cannot_use_the_checkpoint_binding():
    class DifferentPrices(ScenarioMaizeSoybeanPolicyChoice):
        prices = deepcopy(ScenarioMaizeSoybeanPolicyChoice.prices)

    DifferentPrices.prices["fuel_per_liter"] += 0.01
    scene = DifferentPrices(calibrating=True)
    scene.init_and_populate_apps()
    with pytest.raises(ValueError, match="declared initial"):
        scene._load_initial_checkpoint()
