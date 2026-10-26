"""Official WOFOST seeds retain their upstream identities through real sowing."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from fairy.apps.farm_world import FarmWorldApp, TractorApp, WeatherApp
from fairy.apps.farm_world.crop_profiles import (
    OFFICIAL_WOFOST_SEED_VARIETIES,
    official_seed_backend_error,
    seed_crop_type,
)
from fairy.apps.farm_world.models import InventoryState, SeedType as AppSeedType
from fairy.physics.canopy_biomass_engine import (
    DEFAULT_SEED_GROWTH_PARAMS,
    SeedType as CanopySeedType,
)
from fairy.physics.phenology_engine import (
    DEFAULT_SEED_TYPE_PARAMS,
    SeedType as PhenologySeedType,
)
from fairy.time_manager import SimulationTimeManager


SEEDS = tuple(OFFICIAL_WOFOST_SEED_VARIETIES)
START = datetime(2019, 4, 28, 7, tzinfo=timezone.utc).timestamp()


def equipment(seed, *, native=True, cultivar_map=None, simulate_preloaded=False):
    if native:
        pytest.importorskip("pcse")
    farm = FarmWorldApp(num_ridges=1)
    weather = WeatherApp()
    clock = SimulationTimeManager()
    clock.reset(START)
    tractor = TractorApp(farm, weather)
    for app in (farm, weather, tractor):
        app.register_time_manager(clock)
    farm.attach_weather_app(weather)
    farm._ridges[0].soil_vwc = .26
    farm._ridges[0].soil_temp_c = 18.
    farm._inventory.seed_stock[seed] = 20000
    weather.set_weather("2019-04-28", 20., 55., 2., 0., 20./.0864)
    if native:
        farm.configure_crop_backend("wofost",
            cultivar_map=dict(OFFICIAL_WOFOST_SEED_VARIETIES) if cultivar_map is None else cultivar_map,
            require_explicit_cultivar_parameters=True,
            reference_density_plants_m2=40., external_biotic_coupling=False)
    # Explicit prepared seedbed fixture; the sowing and inventory transfer
    # themselves use the real registered tractor tools below.
    tractor._completed_prep_ops = ["level", "base_fertilize", "form_ridges"]
    before_load = deepcopy((clock.time(), tractor.get_state(), farm.get_state()))
    loaded = tractor.load_seeds(seed, 20000)
    if simulate_preloaded:
        # A fixed-farm loading point now rejects incompatible biology early.
        # Independently test the planting boundary against a preloaded device,
        # as could arrive from an old equipment snapshot or a shared depot.
        assert "error" in loaded
        assert (clock.time(), tractor.get_state(), farm.get_state()) == before_load
        tractor.seed_type, tractor._seed_hopper = seed, 20000
        farm._inventory.seed_stock[seed] -= 20000
    else:
        assert loaded["status"] == "ok"
    return farm, weather, tractor, clock


@pytest.mark.parametrize("seed", SEEDS)
def test_official_identifiers_have_only_neutral_compatibility_initializers(seed):
    assert AppSeedType(seed).value == PhenologySeedType(seed).value == CanopySeedType(seed).value == seed
    assert seed_crop_type(seed) == "soybean"
    phenology = DEFAULT_SEED_TYPE_PARAMS[PhenologySeedType(seed)]
    canopy = DEFAULT_SEED_GROWTH_PARAMS[CanopySeedType(seed)]
    assert phenology == DEFAULT_SEED_TYPE_PARAMS[PhenologySeedType.STANDARD]
    assert canopy == DEFAULT_SEED_GROWTH_PARAMS[CanopySeedType.STANDARD]
    assert phenology is not DEFAULT_SEED_TYPE_PARAMS[PhenologySeedType.STANDARD]
    assert canopy is not DEFAULT_SEED_GROWTH_PARAMS[CanopySeedType.STANDARD]
    assert seed not in InventoryState.default().seed_stock


@pytest.mark.parametrize("seed", SEEDS)
def test_real_sowing_keeps_all_78_official_parameters_without_legacy_daily_growth(seed, monkeypatch):
    import yaml
    from fairy.physics.wofost_backend import _DATA

    farm, weather, tractor, clock = equipment(seed)
    # Exactly 40 realized plants/m2, so TDWI needs no density or stand scaling.
    spacing = 100. * farm.crop_profile.rows_per_ridge / (40. * farm.ridge_width_m)
    receipt = tractor.plant_seeds(0, 0, 4., spacing)
    assert receipt["status"] == "ok" and receipt["planted_ridges"] == [0]
    assert receipt["seeds_used"] / farm.ridge_area_m2 == 40.
    assert farm.physics.phenology.states[0].seed_type.value == seed

    def reject_proxy(*args, **kwargs):
        pytest.fail("Native official seed growth must not call the legacy daily growth models")

    monkeypatch.setattr(farm.physics.phenology, "update_day", reject_proxy)
    monkeypatch.setattr(farm.physics.canopy, "update_day", reject_proxy)
    clock.add_offset(86400)
    weather.set_weather("2019-04-29", 20., 55., 2., 0., 20./.0864)
    farm.advance_physics_time()
    run = farm.physics.crop_backend.snapshot()["ridges"]["0"]
    specification = run["specification"]
    variety = OFFICIAL_WOFOST_SEED_VARIETIES[seed]
    raw = yaml.safe_load((_DATA / "soybean.yaml").read_text())["CropParameters"]["Varieties"][variety]
    expected = {name: value[0] for name, value in raw.items() if name != "Metadata"}
    assert len(expected) == len(specification["crop_parameters"]) == 78
    assert specification["crop_parameters"] == expected
    assert specification["seed_type"] == seed
    assert specification["variety"] == variety
    assert specification["cultivar_mapping"] == "explicit"
    assert specification["density_plants_m2"] == 40.
    assert specification["initial_stand_fraction"] == 1.
    assert "cultivar_profile" not in specification
    assert farm.physics.crop_backend.config.parameter_overrides == {}


@pytest.mark.parametrize("seed", SEEDS)
def test_legacy_planter_rejects_official_seed_before_resource_or_clock_changes(seed):
    farm, _, tractor, clock = equipment(seed, native=False, simulate_preloaded=True)
    before = deepcopy((clock.time(), tractor.get_state(), farm.get_state()))
    receipt = tractor.plant_seeds(0, 0, 4., 100./22.)
    assert "native WOFOST backend" in receipt["error"]
    assert (clock.time(), tractor.get_state(), farm.get_state()) == before
    assert farm._physics is None


def test_native_planter_rejects_wrong_official_cultivar_mapping_before_sowing():
    farm, _, tractor, clock = equipment("SOYBEAN_902", cultivar_map={"SOYBEAN_902": "Soybean_901"},
                                      simulate_preloaded=True)
    before = deepcopy((clock.time(), tractor.get_state(), farm.get_state()))
    receipt = tractor.plant_seeds(0, 0, 4., 100./22.)
    assert "Soybean_902" in receipt["error"]
    assert (clock.time(), tractor.get_state(), farm.get_state()) == before
    assert farm.physics.crop_backend.snapshot()["ridges"] == {}


def test_legacy_official_seed_rejection_does_not_initialize_physics():
    assert "native WOFOST" in official_seed_backend_error("SOYBEAN_901", None)
    assert official_seed_backend_error("STANDARD", None) is None


@pytest.mark.parametrize("method,args", [
    ("_operate_plant_seeds", {"depth_cm": 4., "seed_spacing_cm": 100./22.}),
    ("_operate_replant_seeds", {"depth_cm": 4., "spacing_cm": 100./22.}),
])
def test_shared_tractor_internal_preflight_also_rejects_legacy_official_seeds(method, args):
    from types import SimpleNamespace
    from fairy.apps.farm_world.tractor_operations import TractorOperations

    tractor = object.__new__(TractorOperations)
    tractor.seed_type = "SOYBEAN_901"
    tractor._tractor_validate_ridge_window = lambda *args, **kwargs: None
    farm = SimpleNamespace(world=SimpleNamespace(_physics=None))
    receipt = getattr(tractor, method)(farm, 0, 0, **args)
    assert "native WOFOST backend" in receipt["error"]
    assert farm.world._physics is None
