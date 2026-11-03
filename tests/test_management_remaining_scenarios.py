"""Opt-in tools must preserve physical state, units and native reconstruction."""

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from fairy.apps.farm_world import FarmWorldApp, TractorApp
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.physics.biotic_pressure_engine import BioticPressureEngine, TreatmentType
from fairy.scenarios.management_extensions.apps.crop_protection_app import (
    CropProtection,
)
from fairy.scenarios.management_extensions.engines.soybean_cyst_nematode import (
    ScnParameters,
    SoybeanCystNematodeBackend,
)
from fairy.scenarios.management_extensions.L3.scenario_soybean_variety_high_water_price import (
    ScenarioSoybeanVarietyHighWaterPrice,
)
from fairy.scenarios.management_extensions.L4.scenario_two_year_soybean_cyst_rotation import (
    ScenarioTwoYearSoybeanCystRotation,
)
from fairy.time_manager import SimulationTimeManager


def test_official_variety_choice_preserves_soil_and_initial_fingerprint():
    scene = ScenarioSoybeanVarietyHighWaterPrice(calibrating=True)
    scene.setup()
    Engine(None, scene)
    fingerprint = scene.input_fingerprint()
    soils = deepcopy(scene.farms[0].physics.soil.states)
    options = scene.selection.get_options()["options"]
    assert (
        len({(r["parameters"]["TSUM1"], r["parameters"]["TSUM2"]) for r in options})
        == 3
    )
    assert len({r["parameters"]["DEPNR"] for r in options}) == 1
    assert len({r["parameters"]["CFET"] for r in options}) == 1
    scene.selection.select_variety("SOYBEAN_903")
    assert scene.farms[0].physics.crop_backend.config.variety_name == "Soybean_903"
    assert scene.farms[0].physics.soil.states == soils
    assert scene.input_fingerprint() == fingerprint
    before = scene.selection.get_state()
    with pytest.raises(ValueError, match="declared official seed"):
        scene.selection.select_variety("HEINONG58")
    assert scene.selection.get_state() == before
    scene.tractor.attach_implement(implement="grader")
    scene.tractor.level(farm_id="soybean")
    with pytest.raises(ValueError, match="locked"):
        scene.selection.select_variety("SOYBEAN_901")
    assert scene.selection.get_state() == before


def test_fungicide_uses_formulated_ml_and_disease_treatment_not_insecticide():
    catalog = json.loads(
        (
            Path(__file__).parents[1]
            / "fairy/scenarios/management_extensions/data/soybean_fungicide_products/catalog.json"
        ).read_text()
    )
    pending = []
    clock = SimulationTimeManager()
    clock.reset(datetime(2019, 7, 2, 7, tzinfo=timezone.utc).timestamp())
    farm = SimpleNamespace(
        num_ridges=4,
        field_area_m2=800.0,
        ridge_area_m2=200.0,
        crop_id="soybean",
        _ridges=[
            SimpleNamespace(planted=True, harvested=False, growth_stage="R1")
            for _ in range(4)
        ],
        advance_physics_time=lambda: None,
        simulation_date=lambda ts: datetime.fromtimestamp(ts, timezone.utc).date(),
        physics=SimpleNamespace(
            queue_treatment=lambda rid, t: pending.append((rid, t)),
            biotic=BioticPressureEngine(num_ridges=4),
        ),
        farm_environment=SimpleNamespace(advance_time=clock.add_offset),
    )
    app = CropProtection(
        farm, SimpleNamespace(is_sprayable=True), catalog, purchase_cash=100.0
    )
    app.register_time_manager(clock)
    p = app.products["tebustar_36l"]
    quantity = p["min_rate_per_ha"] * 0.08
    app.purchase("tebustar_36l", quantity, "purchase")
    result = app.apply("tebustar_36l", 0, 3, p["min_rate_per_ha"], "application")
    assert result["unit"] == "mL"
    assert result["product_quantity"] == pytest.approx(quantity)
    assert result["carrier_water_liters"] == 8.0
    assert all(t.treatment_type == TreatmentType.FUNGICIDE for _, t in pending)
    assert "mean_disease_pressure" in app.scout()
    assert "aphid_equivalent_per_plant" not in app.scout()["ridges"][0]
    assert app.harvest_restriction([0]) is not None
    before = app.get_state()
    app.apply("tebustar_36l", 0, 3, p["min_rate_per_ha"], "application")
    assert app.get_state() == before
    with pytest.raises(ValueError, match="seven days"):
        app.apply("tebustar_36l", 0, 3, p["min_rate_per_ha"], "duplicate-day")
    assert app.get_state() == before

    # Both fungicides are FRAC3: a brand change cannot reset the group count.
    app.purchase("tebustar_36l", quantity * 2, "two-more")
    for index in (2, 3):
        clock.add_offset(10 * 86400)
        app.apply("tebustar_36l", 0, 3, p["min_rate_per_ha"], f"application-{index}")
    clock.add_offset(10 * 86400)
    premium = app.products["proline_480sc"]
    app.purchase("proline_480sc", premium["min_rate_per_ha"] * 0.08, "premium")
    before = app.get_state()
    with pytest.raises(ValueError, match="consecutive"):
        app.apply("proline_480sc", 0, 3, premium["min_rate_per_ha"], "fourth-group3")
    assert app.get_state() == before


@pytest.mark.parametrize(
    "parameters",
    [
        {"initial_eggs_per_100cc": -1.0},
        {"host_multiplier_per_120_days": 0.5},
        {"nonhost_survival_per_120_days": 1.01},
        {"fallow_annual_survival": float("nan")},
    ],
)
def test_invalid_scn_assumptions_rejected(parameters):
    with pytest.raises(ValueError):
        ScnParameters(**parameters)


def test_zero_scn_population_can_be_restored_without_inventing_infestation():
    backend = SoybeanCystNematodeBackend(
        {"external_biotic_coupling": False},
        scn_parameters=ScnParameters(initial_eggs_per_100cc=0.0),
    )
    restored = SoybeanCystNematodeBackend.from_state(
        json.loads(json.dumps(backend.export_state()))
    )
    assert restored.scn_parameters.initial_eggs_per_100cc == 0.0
    assert restored.scn_population == {}


def test_scn_changes_native_assimilation_and_sorted_json_reconstruction():
    class OneRidge(ScenarioTwoYearSoybeanCystRotation):
        scenario_id = "test_one_ridge_scn"
        field: ClassVar[dict] = {
            **ScenarioTwoYearSoybeanCystRotation.field,
            "ridge_count": 1,
        }

    scene = OneRidge(calibrating=True)
    scene.setup()
    Engine(None, scene)
    tractor = scene.get_typed_app(TractorApp)
    farm = scene.get_typed_app(FarmWorldApp)
    tractor.attach_implement(implement="grader")
    tractor.level()
    tractor.detach_implement()
    tractor.attach_implement(implement="furrower")
    tractor.form_ridges(ridge_width_m=0.75)
    tractor.detach_implement()
    tractor.load_seeds(seed_type="SOYBEAN_901", count=8040)
    tractor.plant_seeds(
        start_ridge=0, end_ridge=0, depth_cm=4.0, seed_spacing_cm=100 * 2 / (0.75 * 40)
    )
    scene.get_typed_app(SystemApp).advance_time(days=40)
    backend = farm.physics.crop_backend
    state = json.loads(json.dumps(backend.export_state(), sort_keys=True))
    restored = SoybeanCystNematodeBackend.from_state(state)
    assert restored.export_state() == state
    assert restored.scn_population[0] > backend.scn_parameters.initial_eggs_per_100cc
    journal = state["runs"]["0"]["journal"]
    native = backend._runs[0].pcse
    assert native["PGASS"] > 0
    assert native["PGASS"] == pytest.approx(
        native["PGASS_BEFORE_BIOTICS"] * journal[-1]["scn"]["assimilation_factor"]
    )
    assert restored._runs[0].pcse == native
    altered = deepcopy(state)
    altered["runs"]["0"]["journal"][0]["scn"]["eggs_before_per_100cc"] += 1
    with pytest.raises(ValueError, match="SCN native journal mismatch"):
        SoybeanCystNematodeBackend.from_state(altered)


def test_pending_next_crop_checkpoint_keeps_new_configuration_after_old_journal():
    class OneRidge(ScenarioTwoYearSoybeanCystRotation):
        scenario_id = "test_pending_crop_scn"
        field: ClassVar[dict] = {
            **ScenarioTwoYearSoybeanCystRotation.field,
            "ridge_count": 1,
        }

    class OpenedNextCrop(Exception):
        pass

    scene = OneRidge(calibrating=True)
    scene.setup()
    engine = Engine(None, scene)

    def call(app, method, **args):
        result = getattr(app, method)(**args)
        if app is scene.cycle and method == "open_next_crop":
            raise OpenedNextCrop
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(result)
        return result

    with pytest.raises(OpenedNextCrop):
        scene.oracle_policy(
            scene,
            engine,
            call,
            allocations=[
                {"crop_id": "soybean", "fertilizer_kg": 0.0, "water_mm": 0.0},
                {"crop_id": "maize", "fertilizer_kg": 0.0, "water_mm": 0.0},
            ],
        )
    backend = scene.cycle.farm.physics.crop_backend
    assert (
        backend._runs[0].specification["rotation_configuration"]["crop_name"]
        == "soybean"
    )
    assert backend.config.crop_name == "maize"
    saved = json.loads(json.dumps(backend.export_state(), sort_keys=True))
    restored = SoybeanCystNematodeBackend.from_state(saved)
    assert restored.config.crop_name == "maize"
    assert json.loads(json.dumps(restored.export_state(), sort_keys=True)) == saved


def test_variety_native_evaluation_is_json_serializable_for_existing_cli():
    class OneRidge(ScenarioSoybeanVarietyHighWaterPrice):
        scenario_id = "test_variety_cli_dates"
        fields: ClassVar = (
            {**ScenarioSoybeanVarietyHighWaterPrice.fields[0], "ridge_count": 1},
        )

    scene = OneRidge(calibrating=True)
    scene.setup()
    Engine(None, scene)
    tractor = scene.tractor
    tractor.attach_implement(implement="grader")
    tractor.level(farm_id="soybean")
    tractor.detach_implement()
    tractor.attach_implement(implement="furrower")
    tractor.form_ridges(farm_id="soybean", ridge_width_m=1.1)
    tractor.detach_implement()
    tractor.attach_implement(implement="seeder")
    tractor.load_seeds(seed_type="SOYBEAN_901", count=11792)
    tractor.plant_seeds(
        farm_id="soybean",
        start_ridge=0,
        end_ridge=0,
        depth_cm=4.0,
        seed_spacing_cm=100 * 2 / (1.1 * 40),
    )
    scene.system.advance_time(days=40)
    result = scene.validate().to_dict()
    encoded = json.dumps(result)
    assert json.loads(encoded)["metadata"]["native_crop_water"][0]["DOE"] is not None
