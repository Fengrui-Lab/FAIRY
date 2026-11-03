"""Episode-local planning and money tools; existing farm classes stay unchanged."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from fairy.apps.app import App
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.shared_tractor_app import SharedTractorApp
from fairy.physics.weather_engine import WeatherGenerator, default_harbin_soybean_config
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered

SEEDS = {"soybean": "SOYBEAN_901", "maize": "MAIZE_201"}
VARIETIES = {"soybean": "Soybean_901", "maize": "Grain_maize_201"}
OPTIONS = {
    "soybean": {
        "seed_type": SEEDS["soybean"],
        "depth_cm": 4.0,
        "spacing_cm": 20 / 3,
        "rows_per_ridge": 2,
        "required_seeds": 514560,
    },
    "maize": {
        "seed_type": SEEDS["maize"],
        "depth_cm": 5.0,
        "spacing_cm": 20.0,
        "rows_per_ridge": 1,
        "required_seeds": 85760,
    },
}


def crop_options(farm):
    """Exact seed demand at the existing full-season geometry and target density."""
    options = deepcopy(OPTIONS)
    for crop, opt in options.items():
        opt["spacing_cm"] = (
            100
            * opt["rows_per_ridge"]
            / (farm.ridge_width_m * (40.0 if crop == "soybean" else 20 / 3))
        )
        per_ridge = round(
            farm.field_length_m * opt["rows_per_ridge"] * 100 / opt["spacing_cm"]
        )
        opt["required_seeds"] = per_ridge * farm.num_ridges
    return options


SCN_SOURCE = "https://extension.umn.edu/agriculture/crop-production/soybean/soybean-cyst-nematode-management-guide"
WEATHER_EXTENSION_DIR = Path(__file__).with_name("data") / "thionville_december2019_v1"


@dataclass
class EpisodeState:
    season_id: str = "2019"
    season_history: list = field(default_factory=list)
    soil_report: dict = field(default_factory=dict)
    selection: dict | None = None
    budget_initial_minor: int = 10000
    orders: dict = field(default_factory=dict)
    rain_free_october: bool = False

    @property
    def spent(self):
        return sum(order["total_minor"] for order in self.orders.values())

    @property
    def remaining(self):
        return self.budget_initial_minor - self.spent


def configure_weather(farm):
    """Family-local forcing, including weather before the crop is selected."""
    farm._sim_date = "2019-05-01"
    farm.set_season_phase("full_season")
    data = (
        Path(__file__).resolve().parents[2]
        / "physics/data/wofost/research/thionville_nasa2019_v1"
    )
    manifest = json.loads((data / "manifest.json").read_text())
    path = data / manifest["weather_path"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["weather_sha256"]:
        raise ValueError("Pinned weather checksum mismatch")
    extension_manifest = json.loads(
        (WEATHER_EXTENSION_DIR / "manifest.json").read_text()
    )
    extension_path = WEATHER_EXTENSION_DIR / extension_manifest["weather_path"]
    extension_bytes = extension_path.read_bytes()
    if (
        hashlib.sha256(extension_bytes).hexdigest()
        != extension_manifest["weather_sha256"]
        or extension_manifest["base_weather_sha256"] != manifest["weather_sha256"]
    ):
        raise ValueError("Pinned extension weather checksum mismatch")
    weather_rows = json.loads(path.read_text())["daily"]
    extension_rows = json.loads(extension_bytes)["daily"]
    # This overlay is opt-in for this family. Never overwrite the old bundle
    # or mutate the shared generator defaults used by other scenarios.
    if any(row["date"] <= weather_rows[-1]["date"] for row in extension_rows):
        raise ValueError("Extension weather must not replace base-period days")
    generator = WeatherGenerator(default_harbin_soybean_config(), seed=0)
    from datetime import date

    for row in weather_rows + extension_rows:
        generator.set_day_override(
            date.fromisoformat(row["date"]),
            air_temp_mean_c=(row["tmin_c"] + row["tmax_c"]) / 2,
            air_temp_min_c=row["tmin_c"],
            air_temp_max_c=row["tmax_c"],
            rain_mm=(
                0.0
                if farm.episode.rain_free_october and row["date"].startswith("2019-10-")
                else row["rain_mm"]
            ),
            wind_ms=row["wind_2m_m_s"],
            solar_rad_mj_m2=row["shortwave_mj_m2_day"],
            relative_humidity_pct=row["relative_humidity_pct"],
        )
    physics = farm.physics
    physics.weather_generator = generator
    physics.latitude_deg = 49.4
    physics.scenario_metadata = {
        "daily_settlement": "completed_calendar_day",
        "reference_id": "thionville",
        "weather_sha256": manifest["weather_sha256"],
        "weather_extension_sha256": extension_manifest["weather_sha256"],
        "weather_operations_end": "2019-12-31",
        "weather_forecast_buffer_end": "2020-01-07",
        "scn_dynamics": False,
        "field_trial_validation": False,
    }
    if farm.episode.rain_free_october:
        physics.scenario_metadata["weather_override"] = {
            "start_date": "2019-10-01",
            "end_date": "2019-10-31",
            "rain_mm": 0.0,
            "source": "synthetic scenario override; other NASA weather fields unchanged",
        }
    return manifest


def configure_native(farm):
    """Pinned weather and explicit regional soil/crop assumptions."""
    crop = farm.crop_type
    manifest = configure_weather(farm)
    physics = farm.physics
    physics.soil.params = replace(
        physics.soil.params,
        root_depth_m=1.2,
        wilting_point_vwc=0.10,
        field_capacity_vwc=0.30,
        saturation_vwc=0.45,
        max_infiltration_mm_day=50.0,
        rainfall_capture_efficiency=1.0,
    )
    physics.biotic.params = replace(physics.biotic.params, recruitment_fraction=0.0)
    physics.biotic.set_pressure(
        list(range(farm.num_ridges)),
        weed_pressure=0.0,
        insect_pressure=0.0,
        disease_pressure=0.0,
    )
    farm.configure_crop_backend(
        "wofost",
        crop_name=crop,
        variety_name=VARIETIES[crop],
        cultivar_map={SEEDS[crop]: VARIETIES[crop]},
        require_explicit_cultivar_parameters=True,
        latitude_deg=49.4,
        longitude_deg=6.2,
        elevation_m=manifest["location"]["elevation_m"],
        reference_density_plants_m2=40.0 if crop == "soybean" else 20 / 3,
        initial_available_n_kg_ha=50.0 if crop == "soybean" else 30.0,
        base_soil_n_kg_ha=50.0,
        soil_n_mineralization_fraction=0.025 if crop == "soybean" else 0.002,
        fertilizer_n_fraction=0.46,
        fertilizer_n_recovery=0.7,
        external_biotic_coupling=False,
    )
    if crop == "soybean":
        physics.yield_recovery.params.grain_moisture_mode = "soybean_equilibrium"
    farm.configure_management_regime(
        irrigation_quota_mm_total=180.0,
        fertilizer_quota_kg=600 * farm.field_area_m2 / 10000,
    )
    farm.configure_postharvest_market(
        market_moisture_pct=13.0 if crop == "soybean" else 14.0,
        max_storage_moisture_pct=13.5 if crop == "soybean" else 14.0,
    )
    physics.observation_model.rng.seed(0)


class PlanningFarm(FarmWorldApp):
    """Unselected, bare land becomes a crop exactly once before field work."""

    def __init__(
        self,
        *,
        selected_crop=None,
        episode=None,
        num_ridges=64,
        field_length_m=268.0,
        ridge_width_m=0.75,
        management_objective=None,
    ):
        self.episode = episode or EpisodeState()
        self._management_objective = deepcopy(management_objective)
        super().__init__(
            name="Field",
            farm_id="field",
            num_ridges=num_ridges,
            field_length_m=field_length_m,
            ridge_width_m=ridge_width_m,
            rows_per_ridge=1,
            crop_type=selected_crop or "maize",
            required_field_preparation_ops=("level", "form_ridges"),
        )
        for ridge in self._ridges:
            ridge.soil_vwc, ridge.soil_temp_c = 0.26, 20.0
        for soil in self.physics.soil.states.values():
            soil.top_temp_c, soil.root_temp_c = 20.0, 20.0
        if selected_crop:
            self._set_configuration(
                farm_id="field",
                num_ridges=num_ridges,
                field_length_m=field_length_m,
                ridge_width_m=ridge_width_m,
                crop_type=selected_crop,
                rows_per_ridge=OPTIONS[selected_crop]["rows_per_ridge"],
            )
            self.episode.selection = {"crop_id": selected_crop, "source": "scenario"}
            configure_native(self)
        else:
            configure_weather(self)

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_crop_capabilities(self) -> dict:
        """Read chosen crop capabilities and management objective, or both uncommitted candidates."""
        if not self.episode.selection:
            return {
                "farm_id": self.farm_id,
                "crop_selected": False,
                "candidates": crop_options(self),
            }
        result = super().get_crop_capabilities()
        if self._management_objective is not None:
            result["management_objective"] = deepcopy(self._management_objective)
        return result

    def validate_seed_for_crop(self, seed_type):
        if not self.episode.selection:
            return "Select this season's crop before planting"
        return super().validate_seed_for_crop(seed_type)

    def get_state(self):
        state = super().get_state()
        for raw, ridge in zip(state["ridges"], self._ridges):
            raw["seed_spacing_cm"] = ridge.seed_spacing_cm
        return {**state, "management_extension": asdict(self.episode)}

    def load_state(self, state_dict):
        episode = EpisodeState(**deepcopy(state_dict["management_extension"]))
        if episode.remaining < 0:
            raise ValueError("Invalid budget checkpoint")
        super().load_state(state_dict)
        self.episode = episode

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_farm_overview(self) -> dict:
        """Read field state and season/finance records; crop is null until selected."""
        result = super().get_farm_overview()
        if not self.episode.selection:
            result.update(crop_type=None, crop_profile=None)
        result["management_extension"] = asdict(self.episode)
        result["budget_remaining_minor"] = self.episode.remaining
        return result


class PlanningTractor(SharedTractorApp):
    def _target_error(self, farm_id):
        if not self.farm_environment.get_farm(farm_id).world.episode.selection:
            return {"error": "Select crop before field operations", "farm_id": farm_id}
        return super()._target_error(farm_id)


class SeasonPlanning(App):
    def __init__(self, farm, *, prices=None):
        super().__init__("SeasonPlanning")
        self.farm = farm
        self.prices = deepcopy(prices or {})

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_season_context(self, farm_id: str) -> dict:
        """Read season history, SCN report, crop rule and fixed USD prices.

        Args:
            farm_id: Declared farm ID, normally field; see farm overview.

        Returns:
            dict: Historical records, soil eggs/100cc, rotation rule and USD prices
            per kg, seed, L fuel or m3 water as named; includes FX/source.
            Budget *_minor fields are integer US cents (100/USD). Unknown farm
            returns error.
        """
        if farm_id != self.farm.farm_id:
            return {"error": "Unknown farm"}
        return {
            **asdict(self.farm.episode),
            "prices": deepcopy(self.prices),
            "currency": "USD",
            "rule": {
                "threshold_eggs_per_100cc": 10000,
                "hosts": ["soybean"],
                "nonhosts": ["maize"],
                "source": SCN_SOURCE,
                "scn_population_simulated": False,
            },
        }

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_crop_options(self, farm_id: str) -> dict:
        """Read both candidate crops, native seeds, density, depth and exact seed demand."""
        if farm_id != self.farm.farm_id:
            return {"error": "Unknown farm"}
        return crop_options(self.farm)

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def select_crop(
        self, farm_id: str, crop_id: str, cultivar_id: str, report_id: str
    ) -> dict:
        """Commit one crop before any field work; agronomic suitability is evaluated separately."""
        farm = self.farm
        if (
            farm_id != farm.farm_id
            or crop_id not in OPTIONS
            or cultivar_id != SEEDS.get(crop_id)
        ):
            return {"error": "Invalid farm/crop/cultivar"}
        if report_id != farm.episode.soil_report.get("report_id"):
            return {"error": "Unknown soil report"}
        if (
            farm.episode.selection
            or any(r.planted for r in farm._ridges)
            or farm.completed_prep_ops
        ):
            return {"error": "Crop choice is locked"}
        # Prepare independently, then commit: invalid native configuration cannot
        # partially change the land, clock, warehouse, or bound sensor references.
        candidate = PlanningFarm(
            selected_crop=crop_id,
            episode=deepcopy(farm.episode),
            num_ridges=farm.num_ridges,
            field_length_m=farm.field_length_m,
            ridge_width_m=farm.ridge_width_m,
            management_objective=farm._management_objective,
        )
        candidate._ridges = deepcopy(farm._ridges)
        if farm._physics is not None:
            candidate.physics.soil.states = deepcopy(farm.physics.soil.states)
        preserved = {
            k: farm.__dict__[k]
            for k in (
                "farm_environment",
                "time_manager",
                "_weather_app",
                "simulation_timezone",
                "add_event_callbacks",
                "schedule_event_callbacks",
            )
        }
        candidate.__dict__.update(preserved)
        candidate._legacy_inventory = None
        candidate.episode.selection = {
            "crop_id": crop_id,
            "cultivar_id": cultivar_id,
            "report_id": report_id,
            "timestamp": self.time_manager.time(),
        }
        farm.__dict__.update(candidate.__dict__)
        farm.is_state_modified = True
        self.is_state_modified = True
        return deepcopy(farm.episode.selection)


class SeedMarket(App):
    def __init__(
        self,
        farm,
        warehouse,
        offers,
        cost_reader=None,
        *,
        prices=None,
        production_budget_minor=None,
    ):
        super().__init__("SeedMarket")
        self.farm, self.warehouse, self.offers = farm, warehouse, deepcopy(offers)
        self.cost_reader = cost_reader
        self.prices = deepcopy(prices or {})
        self.production_budget_minor = (
            production_budget_minor
            if production_budget_minor is not None
            else farm.episode.budget_initial_minor
        )

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_budget(self) -> dict:
        """Read seed-purchase cash and the separate production-cost limit.

        Returns:
            dict: USD prices and *_minor amounts in integer US cents (100/USD).
            initial/spent/remaining_minor describe seed-purchase cash;
            production_budget_minor caps seed payments plus consumed fertilizer,
            fuel, water and actual drying. accounted_production_cost_minor is current
            cost; production_budget_remaining_minor is the remaining cost allowance.
        """
        s = self.farm.episode
        accounted = self.cost_reader() if self.cost_reader else s.spent
        return {
            "initial_minor": s.budget_initial_minor,
            "spent_minor": s.spent,
            "remaining_minor": s.remaining,
            "currency": "USD",
            "minor_units_per_usd": 100,
            "prices": deepcopy(self.prices),
            "production_budget_minor": self.production_budget_minor,
            "accounted_production_cost_minor": accounted,
            "production_budget_remaining_minor": self.production_budget_minor
            - accounted,
        }

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def list_offers(self, seed_type: str) -> dict:
        """List identical-quality, immediately delivered fixed seed lots and itemized total prices."""
        return {
            "currency": "USD",
            "minor_units_per_usd": 100,
            "offers": [
                {
                    **deepcopy(o),
                    "available_lots": int(
                        not any(
                            order["offer_id"] == o["offer_id"]
                            for order in self.farm.episode.orders.values()
                        )
                    ),
                }
                for o in self.offers.values()
                if o["seed_type"] == seed_type
            ],
        }

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def purchase_seed(self, offer_id: str, quantity: int, order_id: str) -> dict:
        """Purchase one indivisible offered lot; debit and warehouse credit are atomic and idempotent."""
        s = self.farm.episode
        if not isinstance(order_id, str) or not order_id.strip():
            return {"error": "Order ID required"}
        if order_id in s.orders:
            old = s.orders[order_id]
            if (old["offer_id"], old["quantity"]) != (offer_id, quantity):
                return {"error": "Order ID already used for different arguments"}
            return deepcopy(old)
        offer = self.offers.get(offer_id)
        if not offer or type(quantity) is not int or quantity != offer["quantity"]:
            return {"error": "Invalid offer or lot quantity"}
        if any(o["offer_id"] == offer_id for o in s.orders.values()):
            return {"error": "Offer stock exhausted"}
        total = offer["seed_minor"] - offer["discount_minor"] + offer["delivery_minor"]
        if total > s.remaining:
            return {"error": "Insufficient budget"}
        receipt = {
            **deepcopy(offer),
            "currency": "USD",
            "minor_units_per_usd": 100,
            "order_id": order_id,
            "total_minor": total,
            "timestamp": self.time_manager.time(),
        }
        seed = offer["seed_type"]
        self.warehouse.stock.seed_stock[seed] += quantity
        s.orders[order_id] = receipt
        self.is_state_modified = self.warehouse.is_state_modified = (
            self.farm.is_state_modified
        ) = True
        return deepcopy(receipt)

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_purchase_records(self) -> dict:
        """Read the actual purchase receipts, including seed identity, quantity and all fees."""
        return deepcopy(self.farm.episode.orders)
