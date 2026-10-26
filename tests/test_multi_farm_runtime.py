from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

from fairy.agents.agent.toolset_builder import build_toolset
from fairy.apps.app import App
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.multi_farm import FarmFleet, FarmSite, farm_world_apps
from fairy.apps.system import SystemApp
from fairy.cli import _scenario_crop_backend_provenance
from fairy.controllers.engine import Engine
from fairy.scenarios.scenario import Scenario
from scripts.build_oracle_baselines import _require_single_farm_baseline


def _fleet() -> FarmFleet:
    return FarmFleet([
        FarmSite.create("north", "North", num_ridges=3, field_length_m=100),
        FarmSite.create("south", "South", num_ridges=5, field_length_m=200),
    ])


def test_fleet_namespaces_tools_and_owns_independent_resources():
    fleet = _fleet()
    north, south = fleet.sites
    _, schemas, tools = build_toolset(fleet.apps)
    assert len(schemas) == len(tools)
    assert "NorthTractor__plant_seeds" in tools
    assert "SouthTractor__plant_seeds" in tools
    assert "TractorApp__plant_seeds" not in tools
    assert north.farm.num_ridges == 3
    assert south.farm.num_ridges == 5
    assert north.farm._inventory is not south.farm._inventory
    assert north.weather._weather is not south.weather._weather
    north.farm._inventory.fuel_liters = 1.0
    north.weather._avg_soil_vwc = 0.45
    north.tractor._fuel_tank_l = 2.0
    assert south.farm._inventory.fuel_liters == 1000
    assert south.weather._avg_soil_vwc == 0.22
    assert south.tractor._fuel_tank_l == 100


def test_app_lookup_requires_explicit_name_for_multiple_farms():
    fleet = _fleet()
    scenario = Scenario(apps=fleet.apps)
    with pytest.raises(ValueError, match="Ambiguous app type"):
        scenario.get_typed_app(FarmWorldApp)
    assert scenario.get_typed_app(FarmWorldApp, "NorthFarm") is fleet.get("north").farm
    single = Scenario(apps=[fleet.get("north").farm])
    assert single.get_typed_app(FarmWorldApp) is fleet.get("north").farm


def test_duplicate_tools_and_farm_identifiers_fail_instead_of_overwriting():
    north = _fleet().get("north")
    with pytest.raises(ValueError, match="Duplicate tool name"):
        build_toolset([north.tractor, north.tractor])
    with pytest.raises(ValueError, match="Farm IDs must be unique"):
        FarmFleet([north, FarmSite.create("north", "Another")])
    with pytest.raises(ValueError, match="unique"):
        Engine(None, Scenario(apps=[north.farm, FarmWorldApp(farm_id="north", name="OtherFarm")]))


class _WrappedApp(App):
    """Exercise controller discovery without constructing an LLM agent."""

    def __init__(self, wrapped_app):
        super().__init__(name=wrapped_app.name)
        self.wrapped_app = wrapped_app

    def register_time_manager(self, time_manager):
        super().register_time_manager(time_manager)
        self.wrapped_app.register_time_manager(time_manager)


def test_device_time_passes_at_idle_farms_including_wrapped_apps():
    fleet = _fleet()
    system = SystemApp()
    scenario = Scenario(apps=[_WrappedApp(app) for app in fleet.apps] + [system], start_time=1_800_000_000)
    calls = {site.spec.farm_id: [] for site in fleet.sites}
    for site in fleet.sites:
        site.farm.prepare_for_time_advance = lambda timestamp, key=site.spec.farm_id: calls[key].append(("before", timestamp))
        site.farm.advance_physics_time = lambda timestamp=None, key=site.spec.farm_id: calls[key].append(("after", timestamp))
    engine = Engine(None, scenario)
    assert farm_world_apps(scenario.apps) == [site.farm for site in fleet.sites]
    initial = engine.time_manager.time()
    fleet.get("north").tractor.time_manager.add_offset(86400)
    for site in fleet.sites:
        events = calls[site.spec.farm_id]
        assert [event[0] for event in events] == ["before", "after"]
        assert events[0][1] == pytest.approx(initial, abs=0.1)
        assert events[1][1] == pytest.approx(initial + 86400, abs=0.1)
        assert site.farm.time_manager is engine.time_manager
    system.advance_time(days=1)
    assert engine.time_manager.time() == pytest.approx(initial + 2 * 86400, abs=0.1)
    assert all(len(events) >= 4 for events in calls.values())


def test_backend_configuration_applies_to_every_farm():
    fleet = _fleet()
    configured = []
    for site in fleet.sites:
        site.farm.configure_crop_backend = lambda backend, key=site.spec.farm_id, **kwargs: configured.append((key, backend, kwargs))

    class FleetScenario(Scenario):
        def init_and_populate_apps(self):
            self.apps = fleet.apps

    scenario = FleetScenario(crop_backend="wofost", crop_backend_options={"co2_ppm": 410})
    scenario.setup()
    assert configured == [("north", "wofost", {"co2_ppm": 410}), ("south", "wofost", {"co2_ppm": 410})]
    assert _scenario_crop_backend_provenance(scenario)["backend"] == "multi_farm"


def test_idle_crop_evolves_under_its_own_weather_when_other_farm_takes_time():
    fleet = _fleet()
    start = datetime(2026, 5, 12, tzinfo=timezone.utc).timestamp()
    engine = Engine(None, Scenario(apps=fleet.apps, start_time=start))
    for site, temp in zip(fleet.sites, (16.0, 27.0)):
        site.weather.set_weather("2026-05-12", temp, 55.0, 2.0, 0.0, 300.0)
        for ridge_id in range(site.farm.num_ridges):
            site.farm.set_ridge_planted(ridge_id, "STANDARD", 10.0)
        site.farm.physics.engines_active = True
    fleet.get("north").tractor.time_manager.add_offset(3 * 86400)
    north = fleet.get("north").farm.physics.phenology.states[0]
    south = fleet.get("south").farm.physics.phenology.states[0]
    assert north.days_after_planting >= 3
    assert south.days_after_planting >= 3
    assert south.accumulated_gdd > north.accumulated_gdd
    assert fleet.get("south").farm.physics.last_physics_sim_time == pytest.approx(engine.time_manager.time(), abs=0.1)


def test_outcome_accounts_for_each_farms_actual_ridge_area():
    fleet = _fleet()
    engine = Engine(None, Scenario(apps=fleet.apps))
    for site in fleet.sites:
        site.farm._physics = SimpleNamespace(engines_active=True, yield_recovery=SimpleNamespace(states={
            0: SimpleNamespace(biological_yield_g_m2=100, recovered_yield_g_m2_at_market_moisture=80, harvested=True),
        }))
    fleet.get("north").farm._inventory.warehouse_grain_kg = 10
    fleet.get("south").farm._inventory.warehouse_grain_kg = 25
    outcome = engine.outcome_summary()
    assert set(outcome["farms"]) == {"north", "south"}
    aggregate = outcome["aggregate"]
    assert aggregate["num_ridges"] == 8
    assert aggregate["field_area_m2"] == pytest.approx((3 * 100 + 5 * 200) * 1.1)
    assert aggregate["inventory"]["warehouse_grain_kg"] == 35
    assert aggregate["biological_yield_kg_total"] == 33
    assert aggregate["recovered_yield_kg_total"] == 26.4


def test_snapshot_outcome_reports_actual_grain_without_constructing_physics():
    fleet = _fleet()
    north, south = fleet.sites
    north.farm._inventory.warehouse_grain_kg = 735
    south.farm._inventory.warehouse_grain_kg = 675
    north.farm._inventory.harvest_grain_kg = 20
    south.tractor._grain_bin_kg = 30
    engine = Engine(None, Scenario(apps=fleet.apps))
    summary = engine.outcome_summary()
    assert summary["farms"]["north"]["recovered_grain_kg_total"] == 755
    assert summary["farms"]["south"]["recovered_grain_kg_total"] == 705
    assert summary["aggregate"]["recovered_grain_kg_total"] == 1460
    assert summary["aggregate"]["recovered_yield_kg_total"] is None
    assert summary["aggregate"]["biological_yield_kg_total"] is None
    assert summary["aggregate"]["grain_accounting_source"] == "warehouse_plus_trailer_plus_combine_bins"
    assert summary["aggregate"]["grain_mass_basis"] == "operational_inventory_kg"
    assert all(site.farm._physics is None for site in fleet.sites)
    assert all("yield_recovery" not in farm for farm in summary["farms"].values())


def test_multicrop_harvest_oracle_reports_recovered_mass_instead_of_zero_yield():
    from fairy.scenarios.farm_world_diverse.scenarios import ScenarioMultiCropHarvestStorage

    scenario = ScenarioMultiCropHarvestStorage()
    engine = Engine(None, scenario)
    engine.run_scenario_oracle(run_oracle=True)
    outcome = engine.outcome_summary()
    expected = sum(site.farm._inventory.warehouse_grain_kg for site in scenario.fleet.sites)
    assert expected > 0
    assert outcome["aggregate"]["recovered_grain_kg_total"] == pytest.approx(expected)
    assert outcome["aggregate"]["recovered_yield_kg_total"] is None
    assert all(site.farm._physics is None for site in scenario.fleet.sites)


def test_legacy_baseline_builder_explicitly_rejects_a_fleet():
    fleet = _fleet()
    scenario = Scenario(scenario_id="fleet", apps=fleet.apps)
    with pytest.raises(ValueError, match="no farm-qualified ridge IDs"):
        _require_single_farm_baseline(scenario)
    scenario.apps = [fleet.get("south").farm]
    assert _require_single_farm_baseline(scenario) is fleet.get("south").farm
