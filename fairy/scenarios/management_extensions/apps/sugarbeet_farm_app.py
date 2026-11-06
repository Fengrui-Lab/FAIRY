"""Reuse the wheat block world, native telemetry and shared clock, not its crop rules."""

from dataclasses import replace
from types import SimpleNamespace
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.apps.farm_world.field_geometry import FieldGeometry
from fairy.crops.catalog import CropDefinition
from fairy.crops.rules import PlantingRules, HarvestRules, ScalarRange
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered
from .winter_wheat_farm_app import (
    WinterWheatFarm,
    WheatFieldPhysics,
    PROFILE,
    DEFINITION,
)
from ..engines.sugarbeet_wofost import SugarBeetBackend


def crop_definition(c):
    if c.crop == "winter_wheat":
        return replace(DEFINITION, cultivar_id=c.seed, seed_types=(c.seed,))
    return CropDefinition(
        crop_id="sugarbeet",
        cultivar_id=c.seed,
        seed_types=(c.seed,),
        planting_rules=PlantingRules(
            depth_cm=ScalarRange(2, 3),
            soil_vwc=ScalarRange(0.10, 0.40),
            soil_temperature_c=ScalarRange(5, 30),
            required_implement="seeder",
            required_preparation=("level",),
            supported_replant_modes=(),
        ),
        # The cereal harvest path is NOT exposed for beet. A zero threshold makes
        # accidental use fail closed; harvest_roots checks its own contract.
        harvest_rules=HarvestRules(
            ("ROOT_BULKING",), 0, required_implement="beet_harvester"
        ),
        market_moisture_pct=12.5,
        storage_moisture_pct=12.5,
        default_ridge_width_m=6.25,
        default_rows_per_ridge=1,
    )


def operational_profile(c):
    return replace(
        PROFILE,
        crop_type=c.crop,
        seed_type=c.seed,
        planting_depth_cm=c.sowing_depth_cm,
        planting_depth_range_cm=(2, 3) if c.crop == "sugarbeet" else (2, 5),
        planting_min_temp_c=5 if c.crop == "sugarbeet" else 0,
    )


class ArableFieldPhysics(WheatFieldPhysics):
    def __init__(self, world):
        super().__init__(world)
        self.crop_id = self.crop_type = world.current_cycle.crop
        self.crop_profile = operational_profile(world.current_cycle)
        self.config = SimpleNamespace(
            crop_name=world.current_cycle.crop,
            cultivar_map={c.seed: c.cultivar for c in world.bundle.cycles},
        )
        self.crop_backend_name = "wofost_sugarbeet_rotation"

    def validate_planting(self, event):
        c = self.world.current_cycle
        c.check_sowing(event.planting_date)
        if event.seed_type != c.seed:
            raise ValueError(f"Load {c.seed}")
        for i in event.ridge_ids:
            self.world.backends[i].preflight("sow")

    def snapshot(self):
        return {
            "provenance": self.world.crop_backend_provenance(),
            "assumptions": [
                "Official European cultivars; China transfer is not field validation",
                "Native water/N soil continues during fallow; no crop/soil reset",
                "No modelled frost survival, bolting, pests, salinity, P/K or density response",
                "No residue-derived N credit; CNB is not an organic-matter rotation model",
                "Beet fresh mass/sucrose are external quality assumptions, not WOFOST predictions",
                "Historical 7-day weather is a perfect-forecast benchmark, not an operational forecast",
            ],
        }


class SugarBeetFarm(WinterWheatFarm):
    physics_class = ArableFieldPhysics

    def __init__(self, bundle, resources):
        self.bundle, self.resources = bundle, resources
        self.current_cycle_index = 0
        self.rotation_history = []
        FarmWorldApp.__init__(
            self,
            farm_id="arable",
            name="ArableField",
            crop_type=self.current_cycle.crop,
            crop_id=self.current_cycle.crop,
            cultivar_id=self.current_cycle.seed,
            num_ridges=resources.block_count,
            field_length_m=resources.block_length_m,
            ridge_width_m=resources.block_width_m,
            rows_per_ridge=1,
        )
        self.backends = [self.make_block_backend(i) for i in range(self.num_ridges)]
        self.mission_context = {}
        self.management_objective = {}
        self._required_field_preparation_ops = ("level",)
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

    def make_block_backend(self, block_id):
        return SugarBeetBackend(self.block_inputs(block_id))

    @property
    def current_cycle(self):
        return self.bundle.cycles[self.current_cycle_index]

    def _set_configuration(
        self, *, farm_id, num_ridges, field_length_m, ridge_width_m, crop_type, **kwargs
    ):
        g = FieldGeometry(
            num_ridges=num_ridges,
            length_m=field_length_m,
            ridge_width_m=ridge_width_m,
            rows_per_ridge=1,
        )
        self._explicit_crop_id = self.current_cycle.crop
        self._cultivar_id = self.current_cycle.seed
        self._crop_definition_override = None
        self._rows_per_ridge_override = 1
        self._field_boundary_width_m = None
        self._legacy_calendar = None
        self.crop_profile = operational_profile(self.current_cycle)
        self.crop_type = self.current_cycle.crop
        self.variety_name = self.current_cycle.cultivar
        self.farm_id, self.num_ridges = farm_id, g.num_ridges
        self.field_length_m, self.ridge_width_m = g.length_m, g.ridge_width_m

    @property
    def crop_definition(self):
        return crop_definition(self.current_cycle)

    def seed_inventory(self):
        return {
            c.seed: round(c.seed_count_ha * self.resources.area_ha)
            for c in self.bundle.cycles
        }

    def validate_seed_for_crop(self, seed_type):
        return (
            None
            if seed_type == self.current_cycle.seed
            else f"Load {self.current_cycle.seed}"
        )

    def plants_per_ridge_from_spacing(self, spacing_cm):
        return round(self.current_cycle.seed_count_ha * self.ridge_area_m2 / 10000)

    def check_planting_window(self, ridge_ids, seed_type):
        try:
            self.current_cycle.check_sowing(self.simulation_date())
        except ValueError as e:
            return str(e)
        return self.validate_seed_for_crop(seed_type)

    def is_ridge_mature(self, ridge_id):
        if self.current_cycle.crop == "sugarbeet":
            return False  # Root harvest has its own explicit machinery/quality path.
        return self.backends[ridge_id].maturity is not None

    def crop_backend_provenance(self):
        return dict(
            backend="wofost",
            model="Wofost81_NWLP_CWB_CNB",
            crop=self.current_cycle.crop,
            variety=self.current_cycle.cultivar,
            input_fingerprint=self.bundle.identity,
            management_unit="flat_block",
            block_count=self.num_ridges,
            pcse_version=self.backends[0].version,
            field_calibrated=False,
            continuous_soil=True,
            residue_n_credit=False,
            block_input_fingerprints=[backend.bundle.identity for backend in self.backends],
        )

    def get_tools(self):
        from fairy.apps.app import App

        return [
            t
            for t in App.get_tools(self)
            if t.name in {"get_field_info", "inspect_blocks", "begin_next_cycle"}
        ]

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_field_info(self) -> dict:
        """Read current crop, block geometry, agronomic windows and reference assumptions.
        Returns:
            dict: Dates, seed counts, N limits, soil water references, management
            history and objective. Soil references use m3/m3 and rootable depth cm.
            Current water estimates come from inspect_blocks and Sensor.
        """
        self.advance_physics_time()
        cycles = [cycle.to_dict() for cycle in self.bundle.cycles]
        for cycle in cycles:
            if cycle["crop"] == "winter_wheat":
                cycle["minimum_dry_yield_kg_ha"] = max(
                    cycle["minimum_dry_yield_kg_ha"],
                    self.management_objective.get("minimum_wheat_dry_kg_ha", 0.0),
                )
        return dict(
            farm_id=self.farm_id,
            crop=self.current_cycle.crop,
            cycle=dict(cycles[self.current_cycle_index]),
            cycles=cycles,
            date=self.simulation_date().isoformat(),
            weather_today=dict(
                rain_mm=self.bundle.weather[self.simulation_date()].rain_mm,
                air_temperature_proxy_c=self.bundle.weather[
                    self.simulation_date()
                ].tmean_c,
            ),
            area_ha=self.resources.area_ha,
            seed_type=self.current_cycle.seed,
            seeds_per_block=self.plants_per_ridge_from_spacing(1),
            blocks=[
                dict(
                    block_id=i,
                    area_m2=self.ridge_area_m2,
                    soil_water_reference={
                        "wilting_point_vwc": backend.bundle.manifest["native_soil_parameters"]["SMW"],
                        "field_capacity_vwc": backend.bundle.manifest["native_soil_parameters"]["SMFCF"],
                        "saturation_vwc": backend.bundle.manifest["native_soil_parameters"]["SM0"],
                        "rootable_depth_cm": backend.bundle.manifest["native_soil_parameters"]["RDMSOL"],
                        "status": backend.bundle.manifest.get("soil_status", "benchmark assumptions without local field calibration"),
                    },
                )
                for i, backend in enumerate(self.backends)
            ],
            mission_context=self.mission_context,
            management_objective=self.management_objective,
            model_scope=self._physics.snapshot()["assumptions"],
            soil_temperature="air_temperature_proxy_not_5cm_sensor",
            reference_row_spacing_cm=50
            if self.current_cycle.crop == "sugarbeet"
            else 20,
            row_spacing_response="geometry_only_not_native_yield_response",
            fertilizer_n_fraction=self.resources.fertilizer_n_fraction,
            storage_moisture_pct=self.resources.storage_moisture_pct,
            completed_preparation=list(self.completed_prep_ops),
        )

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def inspect_blocks(self, start_block: int, end_block: int) -> dict:
        """Read current block telemetry; dry storage mass is not fresh root or sugar.
        Args:
            start_block: First block, inclusive.
            end_block: Last block, inclusive.
        Returns:
            dict: Native-model estimates and crop-specific stage labels.
        """
        result = super().inspect_blocks(start_block, end_block)
        if "error" not in result:
            result["units"]["TWSO"] = "kg storage-organ dry matter/ha"
            result["crop"] = self.current_cycle.crop
            result["telemetry_kind"] = "native_estimates_not_laboratory_observations"
            if self.current_cycle.crop == "sugarbeet":
                for b in result["blocks"]:
                    b.pop("maturity_date", None)
            for block in result["blocks"]:
                backend = self.backends[block["block_id"]]
                soil = backend.bundle.manifest["native_soil_parameters"]
                block["relative_available_water"] = max(0.0, min(1.0,
                    (block["SM"] - soil["SMW"]) / (soil["SMFCF"] - soil["SMW"])))
                block["applied_n_kg_ha"] = backend.n_by_cycle[self.current_cycle.cycle_id]
                block["irrigation_mm_this_cycle"] = sum(
                    receipt["amount"] for receipt in backend.receipts.values()
                    if receipt["kind"] == "irrigate" and receipt["cycle_id"] == self.current_cycle.cycle_id
                )
                block["sowing_date"] = backend.sowing_day.isoformat() if backend.sowing_day else None
            result["units"].update(
                relative_available_water="fraction of field-capacity minus wilting-point storage, clipped to [0,1]",
                applied_n_kg_ha="kg pure N/ha in the current crop cycle",
                irrigation_mm_this_cycle="gross mm in the current crop cycle",
            )
        return result

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def begin_next_cycle(self) -> dict:
        """Start the next crop's operational cycle on the SAME land and soil.
        Returns:
            dict: New cycle and preserved native soil states, or an unmet precondition.
            Requires previous harvest stored, unloaded machine, fallow elapsed.
        """
        self.advance_physics_time()
        if self.current_cycle_index + 1 >= len(self.bundle.cycles):
            return {"error": "No next crop"}
        env = self.farm_environment
        tractor = getattr(self, "rotation_tractor", None)
        if tractor is None or tractor._grain_bin_kg > 1e-8 or tractor._seed_hopper > 0:
            return {
                "error": "Unload grain and return remaining seed before crop switch"
            }
        batches = list(env.warehouse.grain_batches.values())
        if self.current_cycle.crop == "winter_wheat" and (
            not batches or any(b.status != "stored" for b in batches)
        ):
            return {"error": "All wheat batches must be stored before switching"}
        upcoming = self.bundle.cycles[self.current_cycle_index + 1]
        if not upcoming.prepare_open <= self.simulation_date() <= upcoming.sowing_close:
            return {
                "error": "Fallow period not completed or next sowing window expired"
            }
        if any(
            b.cycle.cycle_id not in b.harvests or b.pending or b.model.crop is not None
            for b in self.backends
        ):
            return {"error": "Every block's previous crop must be closed"}
        previous = self.current_cycle.to_dict()
        for b in self.backends:
            b.begin_next_cycle()
        self.current_cycle_index += 1
        self._explicit_crop_id = self.crop_type = self.current_cycle.crop
        self._cultivar_id = self.current_cycle.seed
        self.variety_name = self.current_cycle.cultivar
        self.crop_profile = operational_profile(self.current_cycle)
        self._physics.crop_id = self._physics.crop_type = self.current_cycle.crop
        self._physics.crop_profile = self.crop_profile
        self._physics.config.crop_name = self.current_cycle.crop
        # Only crop-specific operational flags are cleared. Native soil, clocks,
        # management quotas, consumable stocks and warehouse batches survive.
        for r in self._ridges:
            r.planted = r.harvested = False
            r.seed_type = r.seed_spacing_cm = r.planted_at_sim_time = None
            r.seeds_planted = r.days_since_planted = 0
            r.grain_moisture_pct = 0.0
            r.growth_stage = "BARE"
        self._field_preparation_ops = []
        # Do NOT reset management quotas, machine resources, warehouse or accounts.
        self.rotation_history.append(previous)
        self._sync_blocks()
        return {
            "status": "ok",
            "cycle": self.current_cycle.to_dict(),
            "continuous_soil": True,
        }

    def _sync_blocks(self):
        super()._sync_blocks()
        if self.current_cycle.crop == "sugarbeet":
            for i, r in enumerate(self._ridges):
                r.grain_moisture_pct = 0.0
                state = self._physics.yield_recovery.states[i]
                state.grain_moisture_frac = 0.0
                state.recovered_yield_g_m2_at_market_moisture = 0.0

    def get_state(self):
        state = super().get_state()
        state.update(
            schema="fairy.sugarbeet.blocks.v1",
            current_cycle_index=self.current_cycle_index,
            rotation_history=list(self.rotation_history),
        )
        return state

    def load_state(self, state):
        if state.get("schema") != "fairy.sugarbeet.blocks.v1":
            raise ValueError("Wrong farm checkpoint schema")
        idx = state["current_cycle_index"]
        if type(idx) is not int or not 0 <= idx < len(self.bundle.cycles):
            raise ValueError("Invalid cycle index")
        self.current_cycle_index = idx
        self._explicit_crop_id = self.crop_type = self.current_cycle.crop
        self._cultivar_id = self.current_cycle.seed
        self.variety_name = self.current_cycle.cultivar
        self.crop_profile = operational_profile(self.current_cycle)
        self._physics.crop_id = self._physics.crop_type = self.current_cycle.crop
        self._physics.crop_profile = self.crop_profile
        self._physics.config.crop_name = self.current_cycle.crop
        self.rotation_history = state["rotation_history"]
        super().load_state({**state, "schema": "fairy.wheat.blocks.v1"})
        if any(b.cycle_index != idx for b in self.backends):
            raise ValueError("Mixed-cycle checkpoint")

    @property
    def accounting_crop_ids(self):
        return tuple(c.crop for c in self.bundle.cycles)
