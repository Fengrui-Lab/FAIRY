"""Paired management mechanisms in the ordinary official-reference world.

This is a model intervention experiment, not field validation of a dose or a
best-management recommendation. Every arm retains the complete official 901
crop parameters, Lille 2019 weather, soil, sowing and initial resources. Only
the declared management dose differs within each experiment. Low-N soil and
the rain-removal drought are explicit experimental conditions, not edits to
native crop coefficients. The once-only biotic events use the formal daily
scheduler; their subsequent treatment/yield coupling remains FAIRY empirical.

The policy below uses prespecified dates and registered tools only. Private
native states are collected *after* operations solely for assertions, never
to select an operation, date, dose or stop time. Harvest/storage are outside
these tests: TWSO is biological dry matter, not recovered market grain.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from functools import lru_cache
import hashlib
import json

import pytest
import yaml

pytest.importorskip("pcse")

from fairy.apps.farm_world import FarmWorldApp
from wofost_model_experiments import ModelExperimentEngine
from fairy.scenarios.wofost_events import (
    DroughtEvent, PressureEvent, install_scenario_events, scenario_events_snapshot,
)
from fairy.scenarios.wofost_farm import DATA, FarmDefinition, WofostReferenceScenario


SOWING, FINISH = date(2019, 4, 28), date(2019, 9, 30)
PRESSURE_DAY = date(2019, 6, 1)  # Pinned Lille record: no rain, wind 1.67 m/s.
WATER_DAYS = (date(2019, 6, 15), date(2019, 6, 30), date(2019, 7, 15), date(2019, 7, 30))
N_DAYS = (date(2019, 5, 25), date(2019, 6, 25))
DIAGNOSTIC_DAYS = (date(2019, 5, 24), date(2019, 6, 26), date(2019, 7, 15), date(2019, 8, 15))
CHEMICAL = {
    "weed": ("apply_herbicide", "refill_pesticide_tank", 8.),
    "insect": ("spray_pesticide", "refill_pesticide_tank", 8.),
    "disease": ("apply_fungicide", "load_fungicide", 3.8),
}


def _official_crop():
    manifest = json.loads((DATA / "manifest.json").read_text())
    raw = yaml.safe_load((DATA / manifest["crop_source"]["path"]).read_text())
    return {key: value[0] for key, value in raw["CropParameters"]["Varieties"]["Soybean_901"].items()
            if key != "Metadata"}


def _at_morning(session, day):
    session.advance_to("fixed_calendar_" + day.isoformat(),
        datetime.combine(day, time(7), session.timezone).timestamp())


def _prepare_and_sow(session, scene):
    call = session.call
    call("grader", "TractorApp__attach_implement", {"implement": "grader"})
    call("level", "TractorApp__level")
    call("detach_grader", "TractorApp__detach_implement")
    call("base_payload", "TractorApp__load_fertilizer", {"kg": scene.WORLD.base_fertilizer_kg})
    base = call("base_fertilizer", "TractorApp__base_fertilize", {"total_kg": scene.WORLD.base_fertilizer_kg})
    call("furrower", "TractorApp__attach_implement", {"implement": "furrower"})
    call("ridges", "TractorApp__form_ridges", {"ridge_width_m": scene.WORLD.ridge_width_m})
    call("detach_furrower", "TractorApp__detach_implement")
    count = 11792 * scene.WORLD.num_ridges  # 268 m x 1.1 m x 40 plants/m2.
    call("seed_payload", "TractorApp__load_seeds", {"seed_type": scene.WORLD.seed_type, "count": count})
    planted = call("actual_sowing", "TractorApp__plant_seeds", {
        "start_ridge": 0, "end_ridge": scene.WORLD.num_ridges-1,
        "depth_cm": 4., "seed_spacing_cm": 100 * 2 / (1.1 * 40),
    })
    assert planted["seeds_used"] == count
    return base


def _audit_native(scene):
    """Result-only read. No caller may use this to select management."""
    farm = scene.get_typed_app(FarmWorldApp)
    return {
        rid: {"pcse": deepcopy(run.pcse),
              "native_inputs": deepcopy(run.last_native_inputs),
              "pressure": asdict(farm.physics.biotic.states[rid])}
        for rid, run in farm.physics.crop_backend._runs.items()
    }


@lru_cache(maxsize=None)
def _trial(kind, fraction):
    """Run a fresh complete season at zero, half or reference management dose."""
    world = FarmDefinition("lille", "SOYBEAN_901", "Europe/Paris", SOWING, FINISH,
        num_ridges=4, initial_available_n_kg_ha=0. if kind == "nitrogen" else 50.,
        base_soil_n_kg_ha=0. if kind == "nitrogen" else 50.,
        # A nonzero real prep dose is required by the existing prep contract.
        # 0.1 kg on 0.11792 ha supplies only 0.3901 kg N/ha before recovery.
        base_fertilizer_kg=.1 if kind == "nitrogen" else 4.,
        irrigation_quota_mm=120., active_ingredient_cap_kg=.1)
    declarations = ([DroughtEvent("controlled_drought", "farm", date(2019, 6, 1), date(2019, 8, 15))]
        if kind == "water" else [PressureEvent("controlled_" + kind, "farm", 0, 3,
            PRESSURE_DAY, PRESSURE_DAY+timedelta(days=1), kind, .75, mode="set", repeat="once")]
        if kind in CHEMICAL else [])
    result = {"history": {}, "public_diagnostics": {}, "applied": [], "world": asdict(world)}

    class MechanismTrial(WofostReferenceScenario):
        WORLD = world
        DESCRIPTION = "Prespecified registered-tool management mechanism comparison"

        def build_events_flow(self):
            install_scenario_events(self, declarations)
            return []

        def run_experiment(self, session):
            result["base_receipt"] = _prepare_and_sow(session, self)
            farm = self.get_typed_app(FarmWorldApp)
            # All arms share original forcing after the same declared event.
            pins = [asdict(row) for _, row in sorted(farm.physics.weather_generator._day_overrides.items())]
            result["forcing_sha256"] = hashlib.sha256(json.dumps(pins, sort_keys=True, default=str).encode()).hexdigest()
            for offset in range((FINISH-SOWING).days):
                day = SOWING + timedelta(days=offset)
                if kind == "water" and day in WATER_DAYS and fraction:
                    receipt = session.call("prespecified_water", "FieldOpsApp__irrigate",
                        {"start": 0, "end": 3, "hours": 25. * fraction / 5.})
                    assert receipt["status"] == "irrigation_started"
                    result["applied"].append({"day": day, "receipt": receipt})
                if kind == "nitrogen" and day in N_DAYS and fraction:
                    kg = 3. * fraction
                    session.call("topdress_payload", "TractorApp__load_fertilizer", {"kg": 4 * kg})
                    receipt = session.call("prespecified_nitrogen", "TractorApp__apply_fertilizer",
                        {"start_ridge": 0, "end_ridge": 3, "kg_per_ridge": kg})
                    result["applied"].append({"day": day, "receipt": receipt})
                if kind in CHEMICAL and day == PRESSURE_DAY and fraction:
                    # Conditions are checked by the real spray tool, not waived
                    # by this experiment. June 1 is fixed independently of DVS.
                    method, load, reference = CHEMICAL[kind]
                    session.call("sprayer", "TractorApp__attach_implement", {"implement": "sprayer"})
                    session.call("chemical_payload", "TractorApp__" + load, {"liters": 4 * reference * fraction})
                    receipt = session.call("prespecified_" + kind, "TractorApp__" + method,
                        {"start_ridge": 0, "end_ridge": 3, "liters_per_ridge": reference * fraction})
                    result["applied"].append({"day": day, "receipt": receipt})
                    result["post_treatment"] = _audit_native(self)
                _at_morning(session, day + timedelta(days=1))
                result["history"][day] = _audit_native(self)
                if day in DIAGNOSTIC_DAYS:
                    result["public_diagnostics"][day] = session.call(
                        "public_nutrition_after_" + day.isoformat(),
                        "FarmWorldApp__get_ridge_range_state", {"start": 0, "end": 3})
            result["public_inventory"] = session.call("actual_final_inventory", "FarmWorldApp__get_inventory")

    scene = MechanismTrial()
    engine = ModelExperimentEngine(None, scene)
    workflow = engine.run_experiment()
    farm = scene.get_typed_app(FarmWorldApp)
    result["events"] = scenario_events_snapshot(farm)
    result["specifications"] = {rid: deepcopy(run.specification) for rid, run in farm.physics.crop_backend._runs.items()}
    result["final"] = _audit_native(scene)
    result["native_totals"] = {rid: {"irrigation_mm": run.cumulative_irrigation_mm,
        "fertilizer_kg": run.cumulative_fertilizer_kg, "n_kg_ha": run.cumulative_n_kg_ha,
        "journal": deepcopy(run.journal)} for rid, run in farm.physics.crop_backend._runs.items()}
    result["workflow"] = workflow
    result["final_time"] = engine.time_manager.time()
    return result


def _same_inputs(arms):
    assert len({arm["forcing_sha256"] for arm in arms}) == 1
    assert all(arm["world"] == arms[0]["world"] for arm in arms)
    assert len({arm["final_time"] for arm in arms}) == 1
    crop = _official_crop()
    assert len(crop) == 78
    for arm in arms:
        for rid, specification in arm["specifications"].items():
            assert specification["crop_parameters"] == crop
            assert specification["crop_parameters"]["TDWI"] == 120.
            assert specification["density_plants_m2"] == 40.
            assert specification["planting_date"] == SOWING.isoformat()
            for key in ("soil_parameters", "site_parameters", "crop_parameters"):
                assert specification[key] == arms[0]["specifications"][rid][key]
        assert len(arm["specifications"]) == 4
        assert all(not (step.content or {}).get("error") for step in arm["workflow"].dag.values())


def _twso(arm):
    return sum(row["pcse"]["TWSO"] for row in arm["final"].values()) / 4


def test_formal_drought_water_reaches_native_balance_and_protects_storage_organ():
    arms = [_trial("water", fraction) for fraction in (0., .5, 1.)]
    _same_inputs(arms)
    for arm, mm in zip(arms, (0., 50., 100.)):
        assert arm["public_inventory"]["management_regime"]["irrigation_used_mm_total"] == pytest.approx(mm)
        assert all(row["irrigation_mm"] == pytest.approx(mm) for row in arm["native_totals"].values())
        assert all(row["pcse"]["TOTIRR"] == pytest.approx(mm * .92 / 10) for row in arm["final"].values())
        assert arm["events"]["weather_changes"]
        assert all(row["rain_mm"] == 0 for row in arm["events"]["weather_changes"])
    assert _twso(arms[0]) < _twso(arms[1]) < _twso(arms[2])


def test_formal_low_n_topdress_uses_actual_product_n_budget_and_relaxes_native_deficiency():
    arms = [_trial("nitrogen", fraction) for fraction in (0., .5, 1.)]
    _same_inputs(arms)
    area = 268 * 1.1
    for arm, fraction in zip(arms, (0., .5, 1.)):
        total_product = .1 + 2 * 4 * 3. * fraction
        expected_n = total_product / 4 * .46 * 10000 / area
        assert sum(row["fertilizer_kg"] for row in arm["native_totals"].values()) == pytest.approx(total_product)
        assert all(row["n_kg_ha"] == pytest.approx(expected_n) for row in arm["native_totals"].values())
        assert arm["public_inventory"]["fertilizer_kg"] == pytest.approx(300. - total_product)
    # WOFOST 8.1's active N_Stress publishes RFRGRL/NSLLV, not the old NNI.
    # The official NFIX_FR=.8 remains unchanged: this fixture therefore has a
    # real but small N response, not a claim of severe N-limited yield loss.
    comparison_day = date(2019, 7, 15)
    control, supplied = (arm["history"][comparison_day] for arm in (arms[0], arms[2]))
    for rid in range(4):
        assert control[rid]["pcse"]["NAVAIL"] == 0.
        assert control[rid]["pcse"]["RFRGRL"] < .95
        assert supplied[rid]["pcse"]["RFRGRL"] > .99
        assert supplied[rid]["pcse"]["NuptakeTotal"] > control[rid]["pcse"]["NuptakeTotal"]
        assert arms[0]["specifications"][rid]["crop_parameters"]["NFIX_FR"] == .8
    public_control = arms[0]["public_diagnostics"][comparison_day]["ridges"]
    public_supplied = arms[2]["public_diagnostics"][comparison_day]["ridges"]
    assert all(row["nutrient_index"] < .8 for row in public_control)
    assert all(row["nutrient_index"] > .84 for row in public_supplied)
    assert _twso(arms[0]) < _twso(arms[1]) < _twso(arms[2])


@pytest.mark.parametrize("kind", ["weed", "insect", "disease"])
def test_formal_registered_dose_reduces_declared_pressure_and_protects_native_assimilation(kind):
    arms = [_trial(kind, fraction) for fraction in (0., .5, 1.)]
    _same_inputs(arms)
    pressure = kind + "_pressure"
    residual = {"weed": "herbicide", "insect": "insecticide", "disease": "fungicide"}[kind]
    for arm in arms:
        journal = arm["events"]["pressure_journal"]
        assert len(journal) == 1 and journal[0]["day"] == PRESSURE_DAY.isoformat()
    for arm, fraction in zip(arms[1:], (.5, 1.)):
        for row in arm["post_treatment"].values():
            assert row["pressure"][pressure] < .75
            assert row["pressure"][residual + "_residual_strength"] == pytest.approx(fraction)
        reference = CHEMICAL[kind][2]
        liters = 4 * reference * fraction
        assert arm["public_inventory"]["pesticide_liters"] == pytest.approx(500. - liters)
        assert arm["public_inventory"]["management_regime"]["active_ingredient_used_kg"] == pytest.approx(liters * .001)
    pgass = [arm["history"][PRESSURE_DAY][0]["pcse"]["PGASS"] for arm in arms]
    assert pgass[0] < pgass[1] < pgass[2]
    for arm in arms:
        daily = arm["history"][PRESSURE_DAY][0]
        assert daily["pcse"]["PGASS"] == pytest.approx(
            daily["pcse"]["PGASS_BEFORE_BIOTICS"] * daily["native_inputs"]["external_growth_factor"])
    assert _twso(arms[0]) < _twso(arms[1]) < _twso(arms[2])
