"""Real management tools change native carbon growth, not only compatibility fields."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest

from fairy.apps.farm_world import FarmWorldApp, TractorApp, WeatherApp
from fairy.physics import PlantingConfig, SeedType
from fairy.time_manager import SimulationTimeManager


SOWING = date(2026, 5, 1)


def epoch(day):
    return datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp()


def forcing(weather, day, rain=5.0):
    weather.set_weather(day.isoformat(), 22, 55, 2, rain, 20 / 0.0864)


def native(world):
    return world.physics.crop_backend.snapshot()["ridges"]["0"]


def make_crop(*, coupling=True, water_limited=False):
    pytest.importorskip("pcse")
    world = FarmWorldApp()
    world.num_ridges = 1
    world._ridges = world._ridges[:1]
    weather = WeatherApp()
    tractor = TractorApp(world, weather)
    clock = SimulationTimeManager()
    clock.reset(epoch(SOWING))
    for app in (world, weather, tractor):
        app.register_time_manager(clock)
    world.configure_crop_backend(
        "wofost", external_biotic_coupling=coupling,
        initial_available_n_kg_ha=50.0 if water_limited else 200.0,
        soil_overrides={} if water_limited else {"SMFCF": 0.30},
    )
    world.physics.phenology.plant_ridges(
        [0], PlantingConfig(planting_date=SOWING, seed_type=SeedType.STANDARD),
    )
    world.physics.management.states[0].planted = True
    world.physics.management.states[0].stand_fraction = 1.0
    ridge = world._ridges[0]
    ridge.planted = True
    ridge.soil_vwc = 0.25 if water_limited else 0.30
    ridge.seed_type = "STANDARD"
    ridge.seeds_planted = round(40 * world.field_length_m * world.ridge_width_m)
    # Both arms have the same prescribed crop, sufficient water/N and 60 native
    # days. Otherwise severe water stress can consume all GASS in maintenance,
    # legitimately hiding any biomass gain despite a real PGASS response.
    for offset in range(61):
        day = SOWING + timedelta(days=offset)
        clock.reset(epoch(day))
        forcing(weather, day, rain=3.0 if water_limited else 5.0)
        world.advance_physics_time()
    return world, weather, tractor, clock, day


def treat(tractor, operation, dose):
    if operation == "manual":
        from fairy.apps.farm_world.field_ops_app import FieldOpsApp

        manual = FieldOpsApp(tractor._farm_world_app, tractor._weather_app)
        manual.register_time_manager(tractor.time_manager)
        return manual.apply_pesticide_manual(0, dose)
    if operation == "fungicide":
        assert tractor.load_fungicide(dose)["status"] == "ok"
        return tractor.apply_fungicide(0, 0, dose)
    if operation == "insecticide":
        assert tractor.load_pesticide(dose)["status"] == "ok"
        return tractor.spray_pesticide(0, 0, dose)
    if operation == "herbicide":
        assert tractor.load_pesticide(dose)["status"] == "ok"
        return tractor.apply_herbicide(0, 0, dose)
    assert tractor.attach_implement("cultivator")["status"] == "ok"
    return tractor.mechanical_weed_control(0, 0)


@pytest.mark.parametrize("operation,pressure,dose", [
    ("fungicide", "disease_pressure", 3.8),
    ("insecticide", "insect_pressure", 8.0),
    ("herbicide", "weed_pressure", 8.0),
    ("mechanical", "weed_pressure", None),
    ("manual", "insect_pressure", 3.0),
])
def test_real_treatment_changes_native_assimilation_biomass_and_storage_organ(
    operation, pressure, dose
):
    crops = [make_crop(), make_crop()]
    for world, weather, _, _, day in crops:
        # A declared local outbreak fixture is identical in the two arms.
        setattr(world.physics.biotic.states[0], pressure, 0.8)
        forcing(weather, day, rain=0)
    treated, _, tractor, clock, day = crops[1]
    before = deepcopy(native(treated))
    result = treat(tractor, operation, dose)
    assert result["status"] == "ok", result
    assert native(treated) == before  # No extra PCSE integration for a tool call.
    assert getattr(treated.physics.biotic.states[0], pressure) < 0.8
    crops[0][3].add_offset(clock.time() - crops[0][3].time())
    first_day = []
    for offset in range(1, 26):
        for world, weather, _, sim_clock, _ in crops:
            tomorrow = day + timedelta(days=offset)
            sim_clock.reset(epoch(tomorrow))
            forcing(weather, tomorrow)
            world.advance_physics_time()
        if offset == 1:
            first_day = [deepcopy(native(crop[0])) for crop in crops]
    control, managed = (native(crop[0]) for crop in crops)
    for record in first_day:
        rates = record["pcse"]
        factor = record["last_native_inputs"]["external_growth_factor"]
        assert rates["PGASS"] == pytest.approx(rates["PGASS_BEFORE_BIOTICS"] * factor)
        assert rates["GASS"] == pytest.approx(rates["PGASS"] * rates["RFTRA"])
        assert rates["ASRC"] == pytest.approx(rates["GASS"] - rates["MRES"])
    assert first_day[1]["pcse"]["PGASS"] > first_day[0]["pcse"]["PGASS"] > 0
    assert managed["pcse"]["TAGP"] > control["pcse"]["TAGP"] > 0
    assert managed["pcse"]["TWSO"] > control["pcse"]["TWSO"] > 0


def test_disabling_empirical_coupling_preserves_native_parity_after_real_treatment():
    crops = [make_crop(coupling=False), make_crop(coupling=False)]
    for world, weather, _, _, day in crops:
        world.physics.biotic.states[0].disease_pressure = 0.8
        forcing(weather, day, rain=0)
    assert treat(crops[1][2], "fungicide", 3.8)["status"] == "ok"
    for offset in range(1, 5):
        for world, weather, _, clock, day in crops:
            clock.reset(epoch(day + timedelta(days=offset)))
            forcing(weather, day + timedelta(days=offset))
            world.advance_physics_time()
    first, second = (native(crop[0]) for crop in crops)
    assert first["last_native_inputs"]["external_growth_factor"] == 1
    assert second["last_native_inputs"]["external_growth_factor"] == 1
    for key in ("DVS", "LAI", "TAGP", "TWSO", "SM", "NAVAIL", "PGASS", "GASS"):
        assert first["pcse"][key] == pytest.approx(second["pcse"][key])


def test_real_treatment_does_not_invent_growth_when_water_limits_all_assimilates():
    crops = [make_crop(water_limited=True), make_crop(water_limited=True)]
    for world, weather, _, _, day in crops:
        world.physics.biotic.states[0].disease_pressure = 0.8
        forcing(weather, day, rain=0)
    assert treat(crops[1][2], "fungicide", 3.8)["status"] == "ok"
    for world, weather, _, clock, day in crops:
        clock.reset(epoch(day + timedelta(days=1)))
        forcing(weather, day + timedelta(days=1), rain=3.0)
        world.advance_physics_time()
    first, second = (native(crop[0])["pcse"] for crop in crops)
    assert second["PGASS"] > first["PGASS"] > 0
    assert first["ASRC"] == second["ASRC"] == 0
    assert first["DMI"] == second["DMI"] == 0
    assert first["TAGP"] == second["TAGP"]
    assert first["TWSO"] == second["TWSO"]


def test_scouting_changes_observations_without_mutating_native_crop():
    from fairy.apps.farm_world.drone_app import DroneApp
    from fairy.apps.farm_world.robot_app import RobotApp

    world, weather, _, clock, day = make_crop()
    forcing(weather, day, rain=0)
    drone, robot = DroneApp(world, weather), RobotApp(world, weather)
    for device in (drone, robot):
        device.register_time_manager(clock)
    before = deepcopy(world.physics.crop_backend.export_state())
    assert drone.fly_survey(0, 0)["status"] == "ok"
    assert robot.inspect_crop_health(0, 0)["status"] == "ok"
    assert world.physics.crop_backend.export_state() == before


def test_real_half_dose_has_less_native_assimilation_recovery_than_reference_dose():
    crops = [make_crop(), make_crop(), make_crop()]
    for fraction, (world, weather, tractor, _, day) in zip((0, 0.5, 1), crops):
        world.physics.biotic.states[0].disease_pressure = 0.8
        forcing(weather, day, rain=0)
        if fraction:
            assert treat(tractor, "fungicide", 3.8 * fraction)["status"] == "ok"
            assert world.physics.biotic.states[0].fungicide_residual_strength == fraction
    for world, weather, _, clock, day in crops:
        clock.reset(epoch(day + timedelta(days=1)))
        forcing(weather, day + timedelta(days=1))
        world.advance_physics_time()
    pgass = [native(crop[0])["pcse"]["PGASS"] for crop in crops]
    assert pgass[0] < pgass[1] < pgass[2]


def test_legacy_rainfall_gain_is_rejected_before_creating_any_native_ridge():
    pytest.importorskip("pcse")
    from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
    from fairy.physics import SoilHydraulicModifier
    from fairy.physics.wofost_backend import WofostBackend

    physics = FarmPhysicsState(num_ridges=2)
    physics.soil.set_hydraulic_modifiers({
        1: SoilHydraulicModifier(rainfall_capture_efficiency=1.05),
    })
    backend = WofostBackend()
    with pytest.raises(ValueError, match="catchment/run-on"):
        backend.bind_physics(physics)
    assert not backend.has_started
    assert backend.export_state()["runs"] == {}


@pytest.mark.parametrize("fraction", [-0.01, 1.01, float("nan")])
def test_non_infiltrating_native_rain_fraction_is_validated_before_runtime(fraction):
    from fairy.physics.wofost_backend import WofostConfig

    with pytest.raises(ValueError, match="NOTINF"):
        WofostConfig(site_overrides={"NOTINF": fraction})


def test_assimilation_diagnostics_and_next_day_survive_native_checkpoint():
    from fairy.physics.wofost_backend import WofostBackend

    world, weather, tractor, clock, day = make_crop()
    world.physics.biotic.states[0].disease_pressure = 0.8
    forcing(weather, day, rain=0)
    assert treat(tractor, "fungicide", 1.9)["status"] == "ok"
    clock.reset(epoch(day + timedelta(days=1)))
    forcing(weather, day + timedelta(days=1))
    world.advance_physics_time()
    original = world.physics.crop_backend
    restored = WofostBackend.from_state(original.export_state())
    assert restored.snapshot() == original.snapshot()
    clone = deepcopy(world.physics)
    next_day = day + timedelta(days=2)
    from fairy.physics import SoilWeatherInput
    next_weather = SoilWeatherInput(next_day, 22, 16, 28, 3, 20, 2)
    for backend, physics in ((original, world.physics), (restored, clone)):
        backend.advance_day(physics, next_day, next_weather, ridge_area_m2=world.field_length_m * world.ridge_width_m)
    assert restored.snapshot() == original.snapshot()
