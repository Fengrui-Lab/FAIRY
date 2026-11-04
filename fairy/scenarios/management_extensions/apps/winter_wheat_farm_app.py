"""Block-managed wheat on the existing FarmWorld/FarmEnvironment boundary.

A legacy ridge slot represents one flat management block here. It is not a
raised soybean ridge. Only wheat subclasses translate this private storage API.
"""

from dataclasses import asdict
from datetime import datetime, timedelta
from types import SimpleNamespace
import math

from fairy.apps.app import App
from fairy.apps.farm_world.sensor_app import SensorApp
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.field_geometry import FieldGeometry
from fairy.apps.farm_world.models import RidgeState, ManagementRegimeState
from fairy.apps.farm_world.crop_profiles import CropProfile
from fairy.crops.catalog import CropDefinition
from fairy.crops.rules import PlantingRules, HarvestRules, ScalarRange
from fairy.crops.runtime import CropObservationTraits, CropStatus
from fairy.physics import SoilEngine, ManagementEffectEngine
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered
from ..engines.winter_wheat_wofost import WinterWheatBackend
from ..engines.winter_wheat_inputs import json_safe
from .winter_wheat_accounts_app import SEED

DEFINITION = CropDefinition(
    crop_id="winter_wheat",
    cultivar_id=SEED,
    seed_types=(SEED,),
    planting_rules=PlantingRules(
        depth_cm=ScalarRange(2, 5),
        soil_vwc=ScalarRange(0.10, 0.40),
        soil_temperature_c=ScalarRange(0, 30),
        required_implement="seeder",
        required_preparation=("level",),
        supported_replant_modes=(),
    ),
    harvest_rules=HarvestRules(("MATURE",), 25, required_implement="harvester"),
    market_moisture_pct=12.5,
    storage_moisture_pct=12.5,
    default_ridge_width_m=6.25,
    default_rows_per_ridge=1,
)
# The base FarmWorld constructor requires this operational profile. Its legacy
# growth/yield calendar is unused: physics is always active and PCSE owns growth.
PROFILE = CropProfile(
    crop_type="winter_wheat",
    seed_type=SEED,
    planting_depth_cm=3,
    planting_depth_range_cm=(2, 5),
    seed_spacing_cm=1.25,
    seed_spacing_range_cm=(0, math.inf),
    rows_per_ridge=1,
    stage_thresholds=(),
    emergence_stage="SOWN_NOT_EMERGED",
    mature_stage="MATURE",
    harvest_moisture_min_pct=0,
    harvest_moisture_max_pct=25,
    yield_kg_m2=0,
    grain_fill_day=0,
    grain_moisture_start_pct=0,
    grain_drydown_pct_per_day=0,
    storage_moisture_max_pct=12.5,
    planting_min_temp_c=0,
    planting_vwc_range=(0.10, 0.40),
    irrigation_stop_vwc=0.45,
)


class WheatFieldPhysics:
    """Existing devices read these views; PCSE alone evolves crop and soil water/N."""

    observation_traits = CropObservationTraits(0.30, None, None)

    def __init__(self, world):
        n = world.num_ridges
        self.world = world
        self.num_ridges = n
        self.crop_id = self.crop_type = "winter_wheat"
        self.crop_profile = PROFILE
        self.field_length_m = world.field_length_m
        self.ridge_width_m = world.ridge_width_m
        self.latitude_deg = world.bundle.latitude
        self.last_physics_sim_time = None
        self.engines_active = True
        self.crop_backend_name = "wofost_winter_wheat"
        self.crop_backend = self
        self.config = SimpleNamespace(
            crop_name="winter_wheat", cultivar_map={SEED: world.bundle.cultivar}
        )
        self.soil = SoilEngine(num_ridges=n)
        self.management = ManagementEffectEngine(num_ridges=n)
        self.canopy = SimpleNamespace(
            states={
                i: SimpleNamespace(
                    initialized=False, ndvi_proxy=-1.0, yield_potential_g_m2=0.0
                )
                for i in range(n)
            }
        )
        self.yield_recovery = SimpleNamespace(
            states={
                i: SimpleNamespace(
                    biological_yield_g_m2=0.0, grain_moisture_frac=0.0, harvested=False
                )
                for i in range(n)
            },
            params=SimpleNamespace(
                biological_yield_is_dry_matter=True,
                market_moisture_frac=world.resources.storage_moisture_pct / 100,
            ),
        )
        self.crop = self
        self.action_log = []
        self.scenario_metadata = {
            "model": "native_winter_wheat",
            "field_trial_validation": False,
        }

    def validate_planting(self, event):
        self.world.bundle.season.check_sowing(event.planting_date)
        if event.seed_type != SEED:
            raise ValueError("This farm requires WINTER_WHEAT_104")
        if any(
            self.world.backends[i].sown
            or any(a["kind"] == "sow" for a in self.world.backends[i].pending)
            for i in event.ridge_ids
        ):
            raise ValueError("Block already sown")

    def project(self, ridge_id, management):
        b = self.world.backends[ridge_id]
        r = self.world._ridges[ridge_id]
        emerged = b.values.get("DOE") is not None
        return CropStatus(
            current_planted=r.planted,
            emerged=emerged,
            current_stand=1.0 if emerged and r.planted else 0.0,
            harvested=r.harvested,
            stage=r.growth_stage,
            days_since_planted=r.days_since_planted,
            grain_moisture_pct=r.grain_moisture_pct,
            yield_potential=0.0,
        )

    def native_soil_nitrogen(self, ids):
        result = {}
        for i in ids:
            b = self.world.backends[i]
            n = b.model.soil.nutrientbalance
            result[i] = dict(
                status="native",
                native_effective_day=b.next_day.isoformat(),
                nitrogen_state_effective_day=b.next_day.isoformat(),
                available_n_kg_ha=float(n.states.NAVAIL),
                reserve_n_kg_ha=float(n.states.NSOIL),
                release_reference_n_kg_ha=float(n.NSOILI),
            )
        return result

    def snapshot(self):
        return {
            "provenance": self.world.crop_backend_provenance(),
            "assumptions": [
                "Official European wheat reference; no Chinese field calibration",
                "Independent flat blocks; no lateral water/N exchange",
                "No winterkill, pests, density response or dynamic grain moisture",
            ],
        }


class WinterWheatFarm(FarmWorldApp):
    physics_class = WheatFieldPhysics

    def __init__(self, bundle, resources):
        self.bundle, self.resources = bundle, resources
        super().__init__(
            farm_id="wheat",
            name="WheatField",
            crop_type="winter_wheat",
            crop_id="winter_wheat",
            cultivar_id=SEED,
            num_ridges=resources.block_count,
            field_length_m=resources.block_length_m,
            ridge_width_m=resources.block_width_m,
            rows_per_ridge=1,
        )
        self.backends = [
            self.make_block_backend(block_id)
            for block_id in range(self.num_ridges)
        ]
        self._required_field_preparation_ops = ("level",)
        self.variety_name = bundle.cultivar
        self._sim_date = bundle.season.start.isoformat()
        self._physics = self.physics_class(self)
        self._postharvest_market.market_moisture_pct = resources.storage_moisture_pct
        self._postharvest_market.max_storage_moisture_pct = (
            resources.storage_moisture_pct
        )
        self.configure_management_regime(
            irrigation_quota_mm_total=resources.water_stock_m3
            / (resources.area_ha * 10),
            fertilizer_quota_kg=resources.fertilizer_stock_kg,
        )
        self._sync_blocks()

    def seed_inventory(self):
        return {SEED: round(self.resources.seed_stock_kg / self.resources.seed_mass_kg)}

    def make_block_backend(self, block_id):
        return WinterWheatBackend(self.block_inputs(block_id))

    def block_inputs(self, block_id):
        """Select this block's configured inputs before native initialization."""
        return self.bundle

    def _set_configuration(
        self, *, farm_id, num_ridges, field_length_m, ridge_width_m, crop_type, **kwargs
    ):
        if crop_type != "winter_wheat":
            raise ValueError("WinterWheatFarm only accepts winter_wheat")
        g = FieldGeometry(
            num_ridges=num_ridges,
            length_m=field_length_m,
            ridge_width_m=ridge_width_m,
            rows_per_ridge=1,
        )
        self._explicit_crop_id = "winter_wheat"
        self._cultivar_id = SEED
        self._crop_definition_override = None
        self._rows_per_ridge_override = 1
        self._field_boundary_width_m = None
        self._legacy_calendar = None
        self.crop_profile, self.crop_type = PROFILE, "winter_wheat"
        self.variety_name = None
        self.farm_id, self.num_ridges = farm_id, g.num_ridges
        self.field_length_m, self.ridge_width_m = g.length_m, g.ridge_width_m

    @property
    def crop_definition(self):
        return DEFINITION

    @property
    def native_crop_profile(self):
        return None  # Do not route wheat through soybean/maize profile selection.

    def validate_seed_for_crop(self, seed_type):
        return None if seed_type == SEED else "Load WINTER_WHEAT_104 before sowing"

    def plants_per_ridge_from_spacing(self, spacing_cm):
        return self.resources.seeds_per_block

    def record_action(self, action):
        self._physics.action_log.append(action)

    def check_planting_window(self, ridge_ids, seed_type):
        try:
            self.bundle.season.check_sowing(self.simulation_date())
        except ValueError as exc:
            return str(exc)
        return None

    def advance_physics_time(self, target_sim_time=None):
        target = float(
            target_sim_time if target_sim_time is not None else self.time_manager.time()
        )
        if self.farm_environment is not None and not self.farm_environment._syncing:
            return self.farm_environment.sync(target)
        old = self._physics.last_physics_sim_time
        if old is not None and target < old:
            raise ValueError("Cannot move wheat clock backwards")
        day = datetime.fromtimestamp(target, self.simulation_timezone).date()
        if day > self.bundle.season.deadline:
            raise ValueError("Winter-wheat season deadline exceeded")
        ticks = 0
        for backend in self.backends:
            while backend.next_day < day:
                backend.advance_day()
                ticks += 1
        self._sim_date = day.isoformat()
        self._physics.last_physics_sim_time = target
        self._sync_blocks()
        self._publish_weather(day)
        return {
            "status": "advanced",
            "block_day_ticks": ticks,
            "last_physics_sim_time": target,
        }

    def _publish_weather(self, day):
        if self._weather_app is None:
            return

        def row(d):
            w = self.bundle.weather[d]
            return dict(
                date=d.isoformat(),
                temp_c=w.tmean_c,
                humidity_pct=w.rh_pct,
                wind_speed_ms=w.wind_2m_m_s,
                rainfall_mm=w.rain_mm,
                solar_radiation=w.radiation_mj_m2 / 0.0864,
            )

        forecast = [
            row(day + timedelta(days=i))
            for i in range(1, 8)
            if day + timedelta(days=i) in self.bundle.weather.rows
        ]
        self._weather_app.set_weather(
            **row(day), forecast=forecast, avg_soil_vwc=self.get_avg_vwc()
        )

    def _sync_blocks(self):
        for i, b in enumerate(self.backends):
            r = self._ridges[i]
            v = b.values
            sm = v.get("SM")
            if sm is None:
                raise RuntimeError("Native wheat soil water is unavailable")
            r.soil_vwc = float(sm)
            # No soil thermal engine: this is explicitly an air-temperature proxy.
            r.soil_temp_c = self.bundle.weather[b.next_day].tmean_c
            r.planted = bool(
                (b.sown or any(a["kind"] == "sow" for a in b.pending))
                and not r.harvested
            )
            r.growth_stage = (
                "BARE"
                if r.harvested
                else "SOWN_NOT_EMERGED"
                if r.planted and not b.sown
                else b.snapshot()["stage"]
            )
            sowing = next(
                (
                    d["day"]
                    for d in b.journal
                    if any(a["kind"] == "sow" for a in d["actions"])
                ),
                None,
            )
            r.days_since_planted = (
                (b.next_day - datetime.fromisoformat(sowing).date()).days
                if sowing
                else 0
            )
            r.grain_moisture_pct = (
                self.resources.harvest_moisture_pct
                if b.maturity and not r.harvested
                else 0.0
            )
            soil = self._physics.soil.states[i]
            soil.root_vwc = soil.top_vwc = r.soil_vwc
            soil.root_temp_c = soil.top_temp_c = r.soil_temp_c
            canopy = self._physics.canopy.states[i]
            lai = v.get("LAI") or 0.0
            canopy.initialized = bool(v.get("DOE"))
            canopy.ndvi_proxy = 1 - math.exp(-0.6 * lai) if canopy.initialized else -1.0
            canopy.yield_potential_g_m2 = (v.get("TWSO") or 0) / 10
            yr = self._physics.yield_recovery.states[i]
            yr.biological_yield_g_m2 = canopy.yield_potential_g_m2
            yr.grain_moisture_frac = r.grain_moisture_pct / 100
            yr.harvested = r.harvested
            yr.machine_loss_fraction = 0.05 if r.harvested else 0.0
            yr.field_loss_fraction = yr.quality_discount_fraction = 0.0
            yr.recovered_yield_g_m2_at_market_moisture = (
                yr.biological_yield_g_m2
                * 0.95
                / (1 - self.resources.storage_moisture_pct / 100)
                if r.harvested
                else 0.0
            )

    def is_ridge_mature(self, ridge_id):
        return self.backends[ridge_id].maturity is not None

    def crop_backend_provenance(self):
        return {
            "backend": "wofost",
            "model": "Wofost81_NWLP_CWB_CNB",
            "crop": "winter_wheat",
            "variety": self.bundle.cultivar,
            "input_fingerprint": self.bundle.identity,
            "management_unit": "flat_block",
            "block_count": self.num_ridges,
            "pcse_version": self.backends[0].version,
            "field_calibrated": False,
        }

    def get_tools(self):
        return [
            t
            for t in super().get_tools()
            if t.name in {"get_field_info", "inspect_blocks"}
        ]

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_field_info(self) -> dict:
        """Query wheat layout and actual operation rules before field work.

        Returns:
            dict: Flat-block IDs/area (m2), official seed identity, seed kg/ha,
            sowing window, implements, pure-N fraction, moisture limits (%),
            model scope and deadline. No raised-ridge operation is required.
        """
        self.advance_physics_time()
        return dict(
            farm_id=self.farm_id,
            crop="winter_wheat",
            variety=self.bundle.cultivar,
            area_m2=self.field_area_m2,
            machinery_working_width_m={
                "seeder": 3.0,
                "fertilizer_spreader": 6.0,
                "harvester": 4.4,
            },
            machine_grain_recovery_fraction=0.95,
            blocks=[
                dict(block_id=i, area_m2=self.ridge_area_m2)
                for i in range(self.num_ridges)
            ],
            season=self.bundle.season.as_dict(),
            seed_type=SEED,
            seed_kg_ha=self.resources.seed_kg_ha,
            seed_mass_kg=self.resources.seed_mass_kg,
            planting_depth_cm=[2, 5],
            planting_vwc_range=[0.10, 0.40],
            planting_air_temperature_proxy_c=[0, 30],
            block_length_m=self.field_length_m,
            block_width_m=self.ridge_width_m,
            preparation="level flat field; no form_ridges",
            sowing_implement="seeder",
            harvest_implement="harvester",
            fertilizer="urea product kg per block; N fraction 0.46",
            harvest_moisture_pct=self.resources.harvest_moisture_pct,
            storage_moisture_pct=self.resources.storage_moisture_pct,
            model_scope=self._physics.snapshot()["assumptions"],
            soil_temperature="daily air-temperature proxy, not measured 5-cm soil temperature",
            reference_density_response="Fixed reference seed rate; density/yield response is not simulated",
            legacy_field_keys="Sensor ridge_start/end and Warehouse ridge_ids are block IDs in this wheat farm",
        )

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def inspect_blocks(self, start_block: int, end_block: int) -> dict:
        """Read each selected block's crop stage and native water/N telemetry.

        Args:
            start_block: First block ID, inclusive; see get_field_info.
            end_block: Last block ID, inclusive, at least start_block.

        Returns:
            dict: Per-block native DVS, LAI, dry biomass/grain kg/ha, SM m3/m3,
            NAVAIL kg N/ha, maturity and planted/harvested status. Model estimates
            are not lab samples. Inputs queued today settle the next calendar day.
        """
        self.advance_physics_time()
        if (
            type(start_block) is not int
            or type(end_block) is not int
            or not 0 <= start_block <= end_block < self.num_ridges
        ):
            return {"error": "Invalid block range"}
        readings = []
        for i in range(start_block, end_block + 1):
            native = self.backends[i]
            r = self._ridges[i]
            readings.append(
                dict(
                    block_id=i,
                    planted=r.planted,
                    harvested=r.harvested,
                    stage=r.growth_stage,
                    DVS=native.values.get("DVS"),
                    LAI=native.values.get("LAI"),
                    SM=native.values.get("SM"),
                    NAVAIL=native.values.get("NAVAIL"),
                    TAGP=native.values.get("TAGP"),
                    TWSO=native.values.get("TWSO"),
                    maturity_date=json_safe(native.values.get("DOM")),
                    pending_inputs=len(native.pending),
                )
            )
        return {
            "date": self._sim_date,
            "units": {
                "SM": "m3/m3",
                "NAVAIL": "kg N/ha",
                "TAGP": "kg dry matter/ha",
                "TWSO": "kg dry grain/ha",
            },
            "blocks": readings,
        }

    def get_state(self):
        return dict(
            schema="fairy.wheat.blocks.v1",
            resources=asdict(self.resources),
            input_fingerprint=self.bundle.identity,
            ridges=[
                {**r.to_dict(), "seed_spacing_cm": r.seed_spacing_cm}
                for r in self._ridges
            ],
            native=[b.export_state() for b in self.backends],
            last_time=self._physics.last_physics_sim_time,
            completed_preparation=list(self.completed_prep_ops),
            management_regime=self._management_regime.to_dict(),
            pending_bin_ids=list(self._pending_bin_grain_ridge_ids),
            pending_bin_moistures=list(self._pending_bin_grain_moistures_pct),
            sim_date=self._sim_date,
        )

    def load_state(self, state):
        if (
            state.get("schema") != "fairy.wheat.blocks.v1"
            or state["resources"] != asdict(self.resources)
            or state["input_fingerprint"] != self.bundle.identity
        ):
            raise ValueError("Wheat checkpoint configuration mismatch")
        ridges = [RidgeState.from_dict(r) for r in state["ridges"]]
        if (
            len(ridges) != self.num_ridges
            or [r.ridge_id for r in ridges] != list(range(self.num_ridges))
            or len(state["native"]) != self.num_ridges
        ):
            raise ValueError("Checkpoint must contain every block exactly once")
        backends = [
            type(backend).restore(backend.bundle, saved)
            for backend, saved in zip(self.backends, state["native"])
        ]
        self._ridges, self.backends = ridges, backends
        self._field_preparation_ops = list(state["completed_preparation"])
        self._management_regime = ManagementRegimeState(**state["management_regime"])
        self._pending_bin_grain_ridge_ids = list(state["pending_bin_ids"])
        self._pending_bin_grain_moistures_pct = list(state["pending_bin_moistures"])
        self._physics.last_physics_sim_time = state["last_time"]
        self._sim_date = state["sim_date"]
        self._sync_blocks()


class WinterWheatSensors(SensorApp):
    """Reuse fixed root-zone/canopy telemetry without fictitious 5-cm measurements."""

    def __init__(self, farm):
        super().__init__(farm, name="Sensor")

    def get_tools(self):
        tools = [
            t
            for t in App.get_tools(self)
            if t.name in {"read_root_zone_sensors", "read_canopy_sensors"}
        ]
        for tool in tools:
            tool.function_description = (tool.function_description or "").replace(
                "ridge", "block"
            )
        return tools
