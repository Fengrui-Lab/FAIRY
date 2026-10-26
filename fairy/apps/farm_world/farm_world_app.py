"""
FarmWorldApp — central ridge-state store.

All other apps write ridge data via @env_tool methods.
The agent reads via @app_tool methods.

Legacy default layout: 268 m × 71 m, 64 ridges, ridge width 1.1 m. [PDF-p1]
"""

from __future__ import annotations

import logging
import json
import math
from dataclasses import asdict, replace
from zoneinfo import ZoneInfo
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from fairy.apps.app import App
from fairy.apps.farm_world.crop_profiles import get_crop_profile, seed_crop_type
from fairy.apps.farm_world.field_geometry import FieldGeometry
from fairy.apps.farm_world.legacy_calendar import LegacySoybeanCalendar
from fairy.crops.catalog import get_crop_definition
from fairy.apps.farm_world.models import (
    GrowthStage,
    InventoryState,
    ManagementRegimeState,
    PostHarvestMarketPreset,
    RidgeState,
    SeasonPhase,
    SeedType,
)
from fairy.tool_utils import OperationType, app_tool, data_tool
from fairy.types import event_registered
from fairy.utils.type_utils import type_check

if TYPE_CHECKING:
    from fairy.apps.farm_world.farm_action_record import FarmActionRecord
    from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
    from fairy.apps.farm_world.weather_app import WeatherApp

logger = logging.getLogger(__name__)

# Number of ridges in the farm [PDF-p1]
DEFAULT_NUM_RIDGES = 64

# Farm physical dimensions [PDF-p1]
FIELD_LENGTH_M = 268.0  # ridge length (y-axis)
FIELD_WIDTH_M = 71.0  # total field width (x-axis)
DEFAULT_RIDGE_WIDTH_M = 1.1  # single ridge width
DEFAULT_REQUIRED_FIELD_PREPARATION_OPS = ("level", "base_fertilize", "form_ridges")
ROWS_PER_RIDGE = 2  # two soybean rows per ridge [PDF-p6]
ROW_SPACING_M = 0.4  # spacing between the two planted rows within a ridge [PDF-p1]

# Grain yield per ridge (kg) — midpoint of 200-290 kg range [PDF-p11]
GRAIN_KG_PER_RIDGE = 245.0

# Pesticide consumed per ridge per spray pass (L) [设计, based on 300-800L / 5-10 ridges]
PESTICIDE_L_PER_RIDGE = 8.0

# --------------------------------------------------------------------------
# Post-spray pest/disease pressure trajectory [设计, based on PDF-p9 "药效
# 并非即时显现，而是随病虫害种群数量减少而逐步显现"]
#
#   Phase 1 (0 - 2d): continued worsening — residual pests still feeding,
#                     eggs hatching; pressure rises linearly to base + 0.10.
#   Phase 2 (2 - 4d): plateau — kill-rate ≈ birth-rate, pressure held at
#                     base + 0.10.
#   Phase 3 (>= 4d):  recovery — net population decay at 0.18 / day down to 0.
# --------------------------------------------------------------------------
_SPRAY_WORSEN_DAYS = 2.0
_SPRAY_PLATEAU_DAYS = 4.0
_SPRAY_WORSEN_RATE = 0.05  # per day, during worsening phase
_SPRAY_PLATEAU_BUMP = 0.10  # height of the plateau above base
_SPRAY_DECAY_RATE = 0.18  # per day, during recovery phase
_SECONDS_PER_DAY = 86400.0


def _effective_pressure(base: float, last_spray_t: float | None, now_t: float) -> float:
    """Three-phase post-spray trajectory (worsen → plateau → recover)."""
    if last_spray_t is None:
        return max(0.0, min(1.0, base))
    days = max(0.0, (now_t - last_spray_t) / _SECONDS_PER_DAY)
    if days < _SPRAY_WORSEN_DAYS:
        value = base + _SPRAY_WORSEN_RATE * days
    elif days < _SPRAY_PLATEAU_DAYS:
        value = base + _SPRAY_PLATEAU_BUMP
    else:
        value = (
            base
            + _SPRAY_PLATEAU_BUMP
            - _SPRAY_DECAY_RATE * (days - _SPRAY_PLATEAU_DAYS)
        )
    return max(0.0, min(1.0, value))


# Growth stage progression: days_since_planted thresholds [设计, based on PDF-p6 stage descriptions]
# Maps (seed_type, days) → growth_stage
_STAGE_THRESHOLDS: list[tuple[int, str]] = [
    (0, GrowthStage.VE.value),
    (10, GrowthStage.V1.value),
    (20, GrowthStage.V2.value),
    (30, GrowthStage.V3.value),
    (40, GrowthStage.V4.value),
    (50, GrowthStage.V5.value),
    (60, GrowthStage.V6.value),
    (70, GrowthStage.R1.value),
    (80, GrowthStage.R2.value),
    (90, GrowthStage.R3.value),
    (100, GrowthStage.R4.value),
    (105, GrowthStage.R5.value),
    (110, GrowthStage.R6.value),
    (115, GrowthStage.R7.value),
    (120, GrowthStage.R8.value),
]


def _stage_for_days(days: int) -> str:
    """Return the growth stage string for a given days_since_planted value."""
    stage = GrowthStage.VE.value
    for threshold, s in _STAGE_THRESHOLDS:
        if days >= threshold:
            stage = s
    return stage


def _grain_moisture_for_stage(stage: str, days_in_r6_plus: int) -> float:
    """
    Estimate grain moisture % based on growth stage.
    Grain moisture starts ~35% at R6 and drops ~1.5%/day toward 13-15%. [PDF-p10]
    """
    pre_r6 = {
        GrowthStage.BARE.value,
        GrowthStage.VE.value,
        GrowthStage.V1.value,
        GrowthStage.V2.value,
        GrowthStage.V3.value,
        GrowthStage.V4.value,
        GrowthStage.V5.value,
        GrowthStage.V6.value,
        GrowthStage.R1.value,
        GrowthStage.R2.value,
        GrowthStage.R3.value,
        GrowthStage.R4.value,
        GrowthStage.R5.value,
    }
    if stage in pre_r6:
        return 0.0
    # R6 onward: start at 35%, drop ~1.5%/day, floor at 13%
    moisture = max(13.0, 35.0 - days_in_r6_plus * 1.5)
    return round(moisture, 2)


def validate_required_field_preparation_ops(operations) -> tuple[str, ...]:
    """Validate this field's explicit preparation contract.

    Leveling and ridge formation remain mandatory. A scenario may omit base
    fertilizer when its soil/crop management does not call for that operation.
    The legacy three-operation requirement remains the default.
    """
    if not isinstance(operations, (tuple, list)) or any(not isinstance(op, str) for op in operations):
        raise ValueError("required_field_preparation_ops must be an ordered list or tuple of operation names")
    value = tuple(operations)
    if (not {"level", "form_ridges"}.issubset(value)
            or value != tuple(op for op in DEFAULT_REQUIRED_FIELD_PREPARATION_OPS if op in value)):
        raise ValueError("required_field_preparation_ops must contain level and form_ridges in order, with optional base_fertilize between them")
    return value


def plants_per_ridge_from_spacing(
    seed_spacing_cm: float, rows_per_ridge: int = ROWS_PER_RIDGE
) -> int:
    """
    Convert in-row seed spacing to the realized plant count for one ridge.

    The default retains two soybean rows; other crops configure their row count.
    """
    return int(round(FIELD_LENGTH_M * rows_per_ridge * 100.0 / float(seed_spacing_cm)))


class FarmWorldApp(App):
    """
    Central ridge-state store for the Farm-World simulation.

    Maintains configured ridge geometry, crop identity, and farm inventory.
    Other device apps write ridge data via env_tool calls.
    The agent reads via app_tool calls.
    """

    def __init__(
        self, farm_id: str = "default", name: str | None = None, *,
        num_ridges: int = DEFAULT_NUM_RIDGES, field_length_m: float = FIELD_LENGTH_M,
        ridge_width_m: float | None = None, crop_type: str = "soybean",
        crop_id: str | None = None, cultivar_id: str | None = None,
        rows_per_ridge: int | None = None, field_width_m: float | None = None,
        required_field_preparation_ops: tuple[str, ...] = DEFAULT_REQUIRED_FIELD_PREPARATION_OPS,
    ) -> None:
        super().__init__(name=name or "FarmWorldApp")
        self.farm_environment = None
        self.simulation_timezone = timezone.utc
        self._set_configuration(farm_id=farm_id, num_ridges=num_ridges,
                                field_length_m=field_length_m,
                                ridge_width_m=ridge_width_m, crop_type=crop_type,
                                crop_id=crop_id, cultivar_id=cultivar_id,
                                rows_per_ridge=rows_per_ridge, field_width_m=field_width_m)
        self._ridges: list[RidgeState] = [
            RidgeState.default(i) for i in range(self.num_ridges)
        ]
        self._inventory: InventoryState = InventoryState.default()
        self._management_regime: ManagementRegimeState = ManagementRegimeState()
        self._postharvest_market: PostHarvestMarketPreset = self._default_postharvest_market()
        self.validate_tool_arguments = True
        if self._explicit_crop_id is not None:
            # Explicit modern scenarios own all initial supplies.
            self._inventory = InventoryState({}, 0.0, 0.0, 0.0, 0.0)
        self._planting_windows: list[dict[str, Any]] = []
        self._sim_date: str = "2026-04-25"
        self._season_phase: str = SeasonPhase.PREP.value
        self._pending_irrigation: dict[int, list[dict[str, float]]] = {}
        self._pending_bin_grain_ridge_ids: list[int] = []
        self._field_preparation_ops: list[str] = []
        self._required_field_preparation_ops = validate_required_field_preparation_ops(required_field_preparation_ops)
        self._pending_bin_grain_moistures_pct: list[float] = []
        self._trailer_grain_ridge_ids: list[int] = []
        self._trailer_grain_moistures_pct: list[float] = []
        # Physics state is created lazily on first physics-aware activity.
        # Until then, FarmPhysicsState.engines_active stays False and the
        # legacy in-tool helpers (_effective_pressure, _stage_for_days,
        # _grain_moisture_for_stage, _refresh_ridge_dynamics) remain in charge.
        self._physics: FarmPhysicsState | None = None
        # Forwarded by FieldOpsApp/TractorApp/DroneApp/RobotApp __init__
        # so the orchestrator can read daily weather without env discovery.
        self._weather_app: WeatherApp | None = None

    @property
    def shared_warehouse(self):
        """The scene's stock ledger, when explicitly configured by the scenario."""
        return self.farm_environment.warehouse if self.farm_environment is not None else None


    @property
    def _inventory(self) -> InventoryState:
        """Compatibility state for old single-farm scenarios only."""
        if self.shared_warehouse is not None:
            raise RuntimeError("Shared supplies belong to Warehouse.stock, not to a farm")
        return self._legacy_inventory


    @_inventory.setter
    def _inventory(self, value: InventoryState) -> None:
        if self.shared_warehouse is not None:
            raise RuntimeError("Configure common stock on Warehouse, not on a farm")
        self._legacy_inventory = value


    def simulation_date(self, timestamp: float | None = None) -> date:
        """Return a business date using this farm's explicitly bound timezone."""
        timestamp = self.time_manager.time() if timestamp is None else timestamp
        return datetime.fromtimestamp(timestamp, tz=self.simulation_timezone).date()


    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_management_status(self) -> dict[str, Any]:
        """Read this farm's water quota and actual field management usage.

        Returns:
            farm_id, common warehouse reference and local management limits
            and usage. Fertilizer usage counts application to this field;
            loading a machine from Warehouse does not consume field quota.
        """
        if self.farm_environment is not None:
            self.farm_environment.before_tool()
        return {"farm_id": self.farm_id,
                "warehouse_id": self.shared_warehouse.warehouse_id if self.shared_warehouse else None,
                "management_regime": self._management_regime.to_dict()}


    def check_fertilizer_use(self, kg: float) -> str | None:
        """Check a target field's actual application allowance, not stock ownership."""
        from math import isfinite

        if not isfinite(kg) or kg <= 0:
            return "Fertilizer application must be finite and positive"
        regime = self._management_regime
        if (regime.fertilizer_quota_kg is not None
                and regime.fertilizer_used_kg + kg > regime.fertilizer_quota_kg + 1e-9):
            return "Target farm fertilizer application quota exceeded"
        return None


    def record_fertilizer_use(self, kg: float) -> None:
        """Record fertilizer actually applied to this field after a successful operation."""
        self._management_regime.fertilizer_used_kg += float(kg)
        self.is_state_modified = True


    @property
    def required_field_preparation_ops(self) -> tuple[str, ...]:
        """Scenario configuration; actual completed work is tracked separately."""
        return self._required_field_preparation_ops

    @property
    def completed_prep_ops(self) -> list[str]:
        return self._field_preparation_ops

    @completed_prep_ops.setter
    def completed_prep_ops(self, values: list[str]) -> None:
        self._field_preparation_ops = list(values)

    @property
    def crop_name(self) -> str:
        """Native upland compatibility name for the declared field crop."""
        return self.crop_type

    @crop_name.setter
    def crop_name(self, value: str) -> None:
        # Crop identity is independent of field geometry and resource ownership.
        self.crop_profile = get_crop_profile(value)
        self.crop_type = value
        if hasattr(self, "_explicit_crop_id"):
            self._legacy_calendar = (LegacySoybeanCalendar()
                                     if self._explicit_crop_id is None and value == "soybean" else None)

    @property
    def native_crop_profile(self):
        physics = getattr(self, "_physics", None)
        backend = getattr(physics, "crop_backend", None)
        if backend is None:
            return None
        from fairy.physics.crop_profiles import get_crop_profile as get_native_profile
        return get_native_profile(backend.config.crop_name)

    @property
    def is_native_maize(self) -> bool:
        profile = self.native_crop_profile
        return profile is not None and profile.crop_name == "maize"

    @property
    def rows_per_ridge(self) -> int:
        if self._rows_per_ridge_override is not None:
            return self._rows_per_ridge_override
        profile = self.native_crop_profile
        if profile is not None:
            return profile.rows_per_ridge
        return (get_crop_definition(self._explicit_crop_id, self._cultivar_id).default_rows_per_ridge
                if self._explicit_crop_id is not None else self.crop_profile.rows_per_ridge)

    @property
    def default_harvest_moisture_limit_pct(self) -> float:
        profile = self.native_crop_profile
        return (profile.max_harvest_moisture_frac * 100.0 if profile is not None
                else self.crop_definition.harvest_rules.max_moisture_pct)

    @property
    def crop_id(self) -> str:
        return self.crop_type

    @property
    def cultivar_id(self) -> str | None:
        return self.crop_definition.cultivar_id

    @property
    def crop_definition(self):
        override = getattr(self, "_crop_definition_override", None)
        if override is not None:
            definition = override
        elif self._explicit_crop_id is not None:
            definition = get_crop_definition(self._explicit_crop_id, self._cultivar_id)
        else:
            seed = ("MAIZE_201" if self.is_native_maize else
                    self.crop_profile.seed_type if self.crop_type != "soybean" else self._cultivar_id)
            definition = get_crop_definition(self.crop_type, seed)
        # Scenario preparation remains an explicit field-level contract.
        if hasattr(self, "_required_field_preparation_ops"):
            definition = replace(definition, planting_rules=replace(
                definition.planting_rules, required_preparation=self.required_field_preparation_ops,
            ))
        return definition

    @crop_definition.setter
    def crop_definition(self, definition) -> None:
        """Apply scenario-authored operational rules without changing crop identity."""
        if self._explicit_crop_id is not None:
            base = get_crop_definition(self._explicit_crop_id, self._cultivar_id)
        else:
            seed = "MAIZE_201" if self.is_native_maize else self.crop_profile.seed_type if self.crop_type != "soybean" else self._cultivar_id
            base = get_crop_definition(self.crop_type, seed)
        self._validate_definition_override(definition, base)
        self._crop_definition_override = definition

    @staticmethod
    def _validate_definition_override(definition, base) -> None:
        from fairy.crops.catalog import CropDefinition
        if not isinstance(definition, CropDefinition):
            raise TypeError("Crop rules must be a typed CropDefinition")
        if (definition.crop_id != base.crop_id or definition.cultivar_id != base.cultivar_id
                or not set(definition.seed_types) <= set(base.seed_types)
                or definition.default_rows_per_ridge != base.default_rows_per_ridge
                or definition.default_ridge_width_m != base.default_ridge_width_m):
            raise ValueError("Crop rule override cannot change species, cultivar or default geometry")

    def _definition_override_state(self):
        definition = getattr(self, "_crop_definition_override", None)
        return None if definition is None else json.loads(json.dumps(asdict(definition), allow_nan=False))

    @staticmethod
    def _definition_override_from_state(value):
        if value is None:
            return None
        from fairy.crops.catalog import CropDefinition
        from fairy.crops.rules import ScalarRange, PlantingRules, HarvestRules
        def planting(row):
            if row is None:
                return None
            data = dict(row)
            for name in ("depth_cm", "soil_vwc", "soil_temperature_c", "density_plants_m2"):
                data[name] = ScalarRange(**data[name]) if data.get(name) is not None else None
            for name in ("required_preparation", "supported_replant_modes"):
                data[name] = tuple(data[name])
            data["soil_temperature_by_seed"] = tuple((seed, ScalarRange(**rule)) for seed, rule in data["soil_temperature_by_seed"])
            return PlantingRules(**data)
        data = dict(value)
        data["seed_types"] = tuple(data["seed_types"])
        data["planting_rules"] = planting(data["planting_rules"])
        data["replanting_rules"] = planting(data.get("replanting_rules"))
        harvest = dict(data["harvest_rules"])
        harvest["stage_codes"] = tuple(harvest["stage_codes"])
        data["harvest_rules"] = HarvestRules(**harvest)
        return CropDefinition(**data)

    def get_tools(self):
        tools = super().get_tools()
        if self.shared_warehouse is not None:
            return [tool for tool in tools if tool.name not in {
                "get_inventory", "dry_grain", "store_grain"}]
        return [tool for tool in tools if tool.name != "get_management_status"]


    def _set_configuration(self, *, farm_id: str, num_ridges: int,
                           field_length_m: float, ridge_width_m: float | None,
                           crop_type: str, crop_id: str | None = None,
                           cultivar_id: str | None = None,
                           rows_per_ridge: int | None = None,
                           field_width_m: float | None = None) -> None:
        if not isinstance(farm_id, str) or not farm_id.strip():
            raise ValueError("farm_id must be a nonempty string")
        if crop_id is not None:
            definition = get_crop_definition(crop_id, cultivar_id)
            if crop_type != "soybean" and crop_type != crop_id:
                raise ValueError("crop_type and explicit crop_id must identify the same species")
            crop_type = crop_id
        else:
            definition = get_crop_definition(crop_type, cultivar_id if cultivar_id is not None else
                                             get_crop_profile(crop_type).seed_type if crop_type != "soybean" else None)
        profile = get_crop_profile(crop_type)
        width = (definition.default_ridge_width_m if crop_id is not None
                 else DEFAULT_RIDGE_WIDTH_M) if ridge_width_m is None else ridge_width_m
        rows = definition.default_rows_per_ridge if rows_per_ridge is None else rows_per_ridge
        geometry = FieldGeometry(num_ridges=num_ridges, length_m=field_length_m,
                                 ridge_width_m=width, rows_per_ridge=rows,
                                 boundary_width_m=field_width_m)
        self._explicit_crop_id, self._cultivar_id = crop_id, cultivar_id
        self._crop_definition_override = None
        self._rows_per_ridge_override = rows_per_ridge
        self._field_boundary_width_m = field_width_m
        self._legacy_calendar = LegacySoybeanCalendar() if crop_id is None and crop_type == "soybean" else None
        self.crop_profile, self.crop_type = profile, crop_type
        self.variety_name = None
        self.farm_id, self.num_ridges = farm_id, geometry.num_ridges
        self.field_length_m, self.ridge_width_m = geometry.length_m, geometry.ridge_width_m

    @property
    def field_geometry(self) -> FieldGeometry:
        geometry = FieldGeometry(num_ridges=self.num_ridges, length_m=self.field_length_m,
                                 ridge_width_m=self.ridge_width_m, rows_per_ridge=self.rows_per_ridge,
                                 boundary_width_m=self._field_boundary_width_m)
        previous = getattr(self, "_field_geometry_cache", None)
        if previous != geometry:
            self._field_geometry_cache = geometry
        return self._field_geometry_cache

    @property
    def field_width_m(self) -> float:
        return self.field_geometry.working_width_m

    @property
    def ridge_area_m2(self) -> float:
        return self.field_length_m * self.ridge_width_m

    @property
    def field_area_m2(self) -> float:
        return self.ridge_area_m2 * self.num_ridges

    @property
    def grain_kg_per_ridge(self) -> float:
        return self.crop_profile.yield_kg_m2 * self.ridge_area_m2

    def plants_per_ridge_from_spacing(self, seed_spacing_cm: float) -> int:
        spacing = float(seed_spacing_cm)
        if not math.isfinite(spacing) or spacing <= 0:
            raise ValueError("seed_spacing_cm must be finite and positive")
        return int(round(self.field_length_m * self.rows_per_ridge * 100.0 / spacing))

    def configuration(self) -> dict[str, Any]:
        result = {"farm_id": self.farm_id, "num_ridges": self.num_ridges,
                  "field_length_m": self.field_length_m, "ridge_width_m": self.ridge_width_m,
                  "crop_type": self.crop_type}
        if self._explicit_crop_id is not None or self._cultivar_id is not None:
            result.update(crop_id=self._explicit_crop_id, cultivar_id=self._cultivar_id)
        if self._rows_per_ridge_override is not None:
            result["rows_per_ridge"] = self._rows_per_ridge_override
        if self._field_boundary_width_m is not None:
            result["field_width_m"] = self._field_boundary_width_m
        return result

    def _default_postharvest_market(self) -> PostHarvestMarketPreset:
        market = PostHarvestMarketPreset()
        market.max_storage_moisture_pct = self.crop_definition.storage_moisture_pct
        if self._explicit_crop_id is not None:
            market.market_moisture_pct = self.crop_definition.market_moisture_pct
            market.name = f"grain_{self.crop_type}"
            market.require_safe_moisture = True
        return market

    def _model_assumptions(self) -> list[str]:
        if self._physics is not None and self._physics.crop_backend is not None:
            return list(self._physics.crop_backend.snapshot().get("assumptions", []))
        if self._explicit_crop_id is not None:
            return ["registered crop dynamics; simulated cultivar parameters are not field calibrated"]
        return list(self.crop_profile.model_assumptions)

    def public_crop_profile(self) -> dict[str, Any]:
        """Project effective operation rules without presenting a proxy growth calendar."""
        result = self.crop_profile.to_dict()
        native = self.native_crop_profile
        if native is None and self._explicit_crop_id is None:
            return result
        definition = self.crop_definition
        planting, harvest = definition.planting_rules, definition.harvest_rules
        # Native and registered crop dynamics own their phenology, biomass and
        # drydown; the old calendar preset is only an internal compatibility view.
        for key in ("stage_thresholds", "grain_fill_day", "grain_moisture_start_pct",
                    "grain_drydown_pct_per_day", "yield_kg_m2", "harvest_moisture_min_pct",
                    "emergence_stage", "planting_depth_cm", "seed_spacing_cm"):
            result.pop(key, None)
        result.update(
            crop_type=self.crop_type, rows_per_ridge=self.rows_per_ridge,
            planting_depth_range_cm=[planting.depth_cm.minimum, planting.depth_cm.maximum],
            planting_vwc_range=[planting.soil_vwc.minimum, planting.soil_vwc.maximum],
            planting_min_temp_c=planting.soil_temperature_c.minimum,
            mature_stage=harvest.stage_codes[0],
            harvest_moisture_max_pct=harvest.max_moisture_pct,
            storage_moisture_max_pct=self._postharvest_market.max_storage_moisture_pct,
            model_assumptions=self._model_assumptions(),
        )
        if self._explicit_crop_id is not None:
            result.pop("seed_spacing_range_cm", None)
        if definition.cultivar_id is not None:
            result["seed_type"] = definition.cultivar_id
        else:
            result.pop("seed_type", None)
            result["seed_types"] = list(definition.seed_types)
        if native is not None:
            result["native_variety_name"] = self.variety_name
            result["cultivar_map"] = dict(self._physics.crop_backend.config.cultivar_map)
        return result

    # ------------------------------------------------------------------
    # App interface
    # ------------------------------------------------------------------

    def get_state(self) -> dict[str, Any]:
        self._apply_due_irrigation()
        state = {
            "app_name": self.name,
            "farm_config": self.configuration(),
            **self.configuration(),
            "field_width_m": self.field_width_m,
            "field_area_m2": self.field_area_m2,
            "sim_date": self._sim_date,
            "season_phase": self._season_phase,
            "field_preparation_ops": list(self._field_preparation_ops),
            "completed_prep_ops": list(self._field_preparation_ops),
            "required_field_preparation_ops": list(self.required_field_preparation_ops),
            "model_assumptions": self._model_assumptions(),
            **self._crop_metadata(),
            **({"crop_backend": self._physics.crop_backend.snapshot()["provenance"]}
               if self._physics is not None and self._physics.crop_backend is not None
               else {}),
            "ridges": [r.to_dict() for r in self._ridges],
            "inventory": self._inventory.to_dict() if self.shared_warehouse is None else {"warehouse_id": self.shared_warehouse.warehouse_id},
            "management_regime": self._management_regime.to_dict(),
            "postharvest_market": self._postharvest_market.to_dict(),
            "planting_windows": [dict(window) for window in self._planting_windows],
            "pending_irrigation": {
                str(ridge_id): [dict(item) for item in entries]
                for ridge_id, entries in self._pending_irrigation.items()
            },
            "pending_bin_grain_ridge_ids": list(self._pending_bin_grain_ridge_ids),
            "pending_bin_grain_moistures_pct": list(
                self._pending_bin_grain_moistures_pct
            ),
            "trailer_grain_ridge_ids": list(self._trailer_grain_ridge_ids),
            "trailer_grain_moistures_pct": list(self._trailer_grain_moistures_pct),
        }

        if self.shared_warehouse is not None:
            for key in ("inventory", "pending_bin_grain_ridge_ids", "pending_bin_grain_moistures_pct",
                        "trailer_grain_ridge_ids", "trailer_grain_moistures_pct"):
                state.pop(key, None)
            state["warehouse_id"] = self.shared_warehouse.warehouse_id
            state["resource_schema_version"] = 2
        from fairy.apps.farm_world.crop_snapshot import snapshot_physics
        state["crop_configuration"] = self._crop_configuration()
        state["crop_definition_override"] = self._definition_override_state()
        state["physics_state"] = snapshot_physics(self._physics)
        state["simulation_timezone"] = str(self.simulation_timezone)
        state["weather_state"] = self._weather_app.get_state() if self._weather_app is not None else None
        return state

    def load_state(self, state_dict: dict[str, Any]) -> None:
        """Restore a flat operational view only when no native history is needed.

        Native model history is intentionally absent from get_state(). Use the
        complete physics checkpoint codec to restore native crops and queues.
        """
        incoming_backend = state_dict.get("crop_backend") or {}
        current_native = (
            self._physics is not None
            and self._physics.crop_backend_name == "wofost"
        )
        native_snapshot = state_dict.get("physics_state") or {}
        complete_native = (native_snapshot.get("crop_backend_name") == "wofost"
                           and bool(native_snapshot.get("crop_backend_state")))
        if (current_native or incoming_backend.get("backend") == "wofost") and not complete_native:
            raise ValueError(
                "A flat farm state is not a native physics checkpoint; use "
                "restore_farm_checkpoint_state with full physics checkpoint history"
            )
        saved_crop = state_dict.get("crop_configuration")
        saved_explicit = ((saved_crop or {}).get("explicit_crop_id")
                          if "explicit_crop_id" in (saved_crop or {}) else
                          None if (saved_crop or {}).get("legacy_calendar", True) else (saved_crop or {}).get("crop_id"))
        if self._explicit_crop_id is not None or saved_explicit is not None:
            current = self._crop_configuration()
            if saved_crop is None or any(current.get(key) != value for key, value in saved_crop.items()
                                         if key != "operation_rules"):
                raise ValueError("Snapshot crop, cultivar or geometry does not match this physical farm")
        self._load_field_state(state_dict)

    def _load_field_state(self, state_dict: dict[str, Any]) -> None:
        """Parse and validate a complete field replacement before committing it."""
        required = validate_required_field_preparation_ops(state_dict.get(
            "required_field_preparation_ops", DEFAULT_REQUIRED_FIELD_PREPARATION_OPS))
        if self.shared_warehouse is not None:
            if (state_dict.get("warehouse_id") != self.shared_warehouse.warehouse_id
                    or state_dict.get("resource_schema_version") != 2
                    or any(key in state_dict for key in ("inventory", "pending_bin_grain_ridge_ids", "pending_bin_grain_moistures_pct", "trailer_grain_ridge_ids", "trailer_grain_moistures_pct"))
                    or state_dict.get("farm_config") != self.configuration()
                    or required != self.required_field_preparation_ops):
                raise ValueError("Shared field snapshot must match its complete farm/warehouse configuration and exclude legacy grain/stock")
        elif "warehouse_id" in state_dict:
            raise ValueError("Cannot restore shared field state into a legacy farm")
        config = state_dict.get("farm_config", {**self.configuration(), "num_ridges": len(state_dict["ridges"])})
        for key, value in config.items():
            if key in state_dict and state_dict[key] != value:
                raise ValueError(f"Snapshot {key} does not match its farm configuration")
        restored_ridges = [RidgeState.from_dict(row) for row in state_dict["ridges"]]
        if (len(restored_ridges) != config["num_ridges"]
                or [row.ridge_id for row in restored_ridges] != list(range(config["num_ridges"]))):
            raise ValueError("Ridge IDs must be contiguous and match farm configuration")
        override = (self._definition_override_from_state(state_dict.get("crop_definition_override"))
                    if "crop_definition_override" in state_dict else getattr(self, "_crop_definition_override", None))
        if override is not None:
            selected = config.get("crop_id")
            native = (state_dict.get("physics_state") or {}).get("crop_backend_name") == "wofost"
            seed = (config.get("cultivar_id") if selected is not None else
                    "MAIZE_201" if native and config["crop_type"] == "maize" else
                    get_crop_profile(config["crop_type"]).seed_type if config["crop_type"] != "soybean" else None)
            self._validate_definition_override(override, get_crop_definition(selected or config["crop_type"], seed))
        inventory = InventoryState.from_dict(state_dict["inventory"]) if self.shared_warehouse is None else None
        regime = ManagementRegimeState.from_dict(state_dict.get("management_regime", {}))
        market = PostHarvestMarketPreset.from_dict(state_dict.get("postharvest_market", self._default_postharvest_market().to_dict()))
        windows = [dict(window) for window in state_dict.get("planting_windows", [])]
        pending = {int(rid): [dict(item) for item in entries]
                   for rid, entries in state_dict.get("pending_irrigation", {}).items()}
        preparation = list(state_dict.get("field_preparation_ops", state_dict.get("completed_prep_ops", [])))
        if "completed_prep_ops" in state_dict and list(state_dict["completed_prep_ops"]) != preparation:
            raise ValueError("Snapshot preparation aliases disagree")
        buffers = {name: list(state_dict.get(name, [])) for name in (
            "pending_bin_grain_ridge_ids", "pending_bin_grain_moistures_pct",
            "trailer_grain_ridge_ids", "trailer_grain_moistures_pct")}
        sim_date, phase = state_dict["sim_date"], state_dict["season_phase"]
        date.fromisoformat(sim_date)
        saved_timezone = state_dict.get("simulation_timezone")
        zone = ZoneInfo(saved_timezone) if saved_timezone is not None else self.simulation_timezone
        if self.farm_environment is not None and zone != self.farm_environment.simulation_timezone:
            raise ValueError("A bound farm snapshot cannot change the scene timezone")
        saved_weather = state_dict.get("weather_state")
        if saved_weather is not None:
            if self._weather_app is None:
                raise ValueError("Attach the weather station before loading a complete farm snapshot")
            from fairy.apps.farm_world.weather_app import WeatherApp
            weather_check = WeatherApp()
            weather_check.load_state(saved_weather)
        from fairy.apps.farm_world.crop_snapshot import restore_physics
        restored_physics = restore_physics(
            state_dict.get("physics_state"), config["num_ridges"], config.get("crop_id"),
            crop_type=config["crop_type"], field_length_m=config["field_length_m"],
            ridge_width_m=config["ridge_width_m"],
        )
        if (config.get("crop_id") is not None and restored_physics is None
                and not state_dict.get("crop_backend") and any(row.planted for row in restored_ridges)):
            raise ValueError("A growing physical crop requires its complete physics snapshot")
        restored_variety = state_dict.get("variety_name")
        if restored_physics is not None and restored_physics.crop_backend is not None:
            native_config = restored_physics.crop_backend.config
            if ("variety_name" in state_dict and restored_variety != native_config.variety_name):
                raise ValueError("Snapshot cultivar metadata disagrees with its native model history")
            restored_variety = native_config.variety_name
        changed = config != self.configuration()
        # _set_configuration validates all geometry/identity before assigning it.
        self._set_configuration(**config)
        self._crop_definition_override = override
        self.simulation_timezone, self.variety_name = zone, restored_variety
        self._sim_date, self._season_phase = sim_date, phase
        self._field_preparation_ops, self._required_field_preparation_ops = preparation, required
        self._ridges = restored_ridges
        if inventory is not None:
            self._inventory = inventory
        self._management_regime, self._postharvest_market = regime, market
        self._planting_windows, self._pending_irrigation = windows, pending
        for name, values in buffers.items():
            setattr(self, "_" + name, values)
        if changed or "physics_state" in state_dict:
            self._physics = restored_physics
        if saved_weather is not None:
            self._weather_app.load_state(saved_weather)
        if self.farm_environment is not None:
            self.farm_environment._daily_weather.clear()

    def reset(self) -> None:
        backend_options = (
            self._physics.crop_backend.snapshot()["config"]
            if self._physics is not None and self._physics.crop_backend is not None
            else None
        )
        super().reset()
        self._ridges = [RidgeState.default(i) for i in range(self.num_ridges)]
        if self.shared_warehouse is None:
            self._inventory = InventoryState.default()
        self._management_regime = ManagementRegimeState()
        self._postharvest_market = self._default_postharvest_market()
        self._planting_windows = []
        self._sim_date = (self.simulation_date().isoformat() if self.farm_environment is not None else "2026-04-25")
        self._season_phase = SeasonPhase.PREP.value
        self._field_preparation_ops = []
        # Reset completed work while preserving the declared field contract.
        self._pending_irrigation = {}
        self._pending_bin_grain_ridge_ids = []
        self._pending_bin_grain_moistures_pct = []
        self._trailer_grain_ridge_ids = []
        self._trailer_grain_moistures_pct = []
        self._physics = None
        if self._explicit_crop_id is not None and self.shared_warehouse is None:
            self._inventory = InventoryState({}, 0.0, 0.0, 0.0, 0.0)
        if backend_options is not None:
            self.configure_crop_backend("wofost", **backend_options)

    # ------------------------------------------------------------------
    # Agent tools (@app_tool) — read-only
    # ------------------------------------------------------------------

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_farm_overview(self) -> dict[str, Any]:
        """
        Return a concise farm summary: current date, season phase, inventory,
        required_field_preparation_ops and actual completed preparation,
        and a per-ridge overview (key fields only, not full detail).

        season_phase indicates the current stage of the agricultural calendar:
          "prep"     — pre-planting field preparation
          "planting" — active sowing window
          "growing"  — crop vegetative and reproductive growth
          "harvest"  — grain maturity and harvesting

        Use get_ridge_state() or get_ridge_range_state() for full ridge detail.
        """
        self.advance_physics_time()
        overview = []
        for r in self._ridges:
            self._refresh_ridge_dynamics(r)
            overview.append(
                {
                    "ridge_id": r.ridge_id,
                    "planted": r.planted,
                    "harvested": r.harvested,
                    "growth_stage": r.growth_stage,
                    "grain_moisture_pct": round(r.grain_moisture_pct, 1),
                }
            )
        return {
            **self.configuration(),
            "field_width_m": self.field_width_m,
            "field_area_m2": self.field_area_m2,
            "crop_profile": self.public_crop_profile(),
            "required_field_preparation_ops": list(self.required_field_preparation_ops),
            "completed_field_preparation_ops": list(self.completed_prep_ops),
            **self._crop_metadata(),
            "sim_date": self._sim_date,
            "season_phase": self._season_phase,
            "inventory": self._inventory.to_dict() if self.shared_warehouse is None else {"warehouse_id": self.shared_warehouse.warehouse_id},
            "ridges_overview": overview,
            "model_assumptions": self._model_assumptions(),
        }

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_ridge_state(self, ridge_id: int) -> dict[str, Any]:
        """
        Return an operational state lookup for one ridge.

        Includes planting status, seed type, growth stage, days since planting,
        grain moisture, yield-potential proxy, and days since pesticide application.

        Under WOFOST, nutrient_index is mapped from the juvenile exponential
        leaf-area growth factor RFRGRL. It is not a general nitrogen-sufficiency
        measurement; a low value at flowering alone does not justify fertilizing.

        Args:
            ridge_id: Ridge identifier within the configured farm.
        """
        if not 0 <= ridge_id < self.num_ridges:
            return {
                "error": f"ridge_id must be 0-{self.num_ridges - 1}, got {ridge_id}"
            }
        self.advance_physics_time()
        return self._agent_ridge_dict(self._ridges[ridge_id])

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_ridge_range_state(self, start: int, end: int) -> dict[str, Any]:
        """
        Return the full state of ridges from start to end (inclusive).

        Includes planting status, seed type, growth stage, days since planting,
        grain moisture, yield-potential proxy, and days since pesticide application.

        Args:
            start: First ridge ID
            end:   Last ridge ID , must be >= start.
        """
        if not 0 <= start <= end < self.num_ridges:
            return {
                "error": f"Invalid range [{start}, {end}]. Must be within 0-{self.num_ridges - 1}."
            }
        self.advance_physics_time()
        ridges = [self._ridges[i] for i in range(start, end + 1)]
        return {
            "ridges": [self._agent_ridge_dict(ridge) for ridge in ridges],
        }

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_inventory(self) -> dict[str, Any]:
        """Return legacy single-farm stock and local management/storage requirements."""
        if self.shared_warehouse is not None:
            return {"error": "Read common stock through Warehouse.get_inventory and field limits through get_management_status",
                    "warehouse_id": self.shared_warehouse.warehouse_id}
        return {
            **self._inventory.to_dict(),
            **self._crop_metadata(),
            "management_regime": self._management_regime.to_dict(),
            "postharvest_market": self._postharvest_market.to_dict(),
        }

    def configure_management_regime(
        self,
        *,
        regime: str = "conventional",
        max_insecticide_applications: int | None = None,
        max_fungicide_applications: int | None = None,
        active_ingredient_cap_kg: float | None = None,
        irrigation_quota_mm_total: float | None = None,
        fertilizer_quota_kg: float | None = None,
        max_machine_passes: int | None = None,
        max_mechanical_weed_ridges: int | None = None,
    ) -> None:
        """Configure optional season-level resource constraints."""
        self._management_regime = ManagementRegimeState(
            regime=regime,
            max_insecticide_applications=max_insecticide_applications,
            max_fungicide_applications=max_fungicide_applications,
            active_ingredient_cap_kg=active_ingredient_cap_kg,
            irrigation_quota_mm_total=irrigation_quota_mm_total,
            fertilizer_quota_kg=fertilizer_quota_kg,
            max_machine_passes=max_machine_passes,
            max_mechanical_weed_ridges=max_mechanical_weed_ridges,
        )
        self.is_state_modified = True

    def configure_planting_windows(
        self, windows: list[dict[str, Any]] | tuple[dict[str, Any], ...]
    ) -> dict[str, Any]:
        """Configure inclusive planting date windows by ridge range.

        ``latest_date`` is optional, preserving existing earliest-only rules.
        """
        normalized: list[dict[str, Any]] = []
        for raw in windows:
            start = int(raw["start"])
            end = int(raw["end"])
            if not 0 <= start <= end < self.num_ridges:
                raise ValueError(
                    f"Invalid planting window ridge range [{start}, {end}]"
                )
            earliest_date = str(raw["earliest_date"])
            earliest_day = date.fromisoformat(earliest_date)
            latest_date = raw.get("latest_date")
            if latest_date is not None:
                latest_date = str(latest_date)
                if date.fromisoformat(latest_date) < earliest_day:
                    raise ValueError("latest_date must be on or after earliest_date")
            normalized.append(
                {
                    "label": str(raw.get("label", f"ridges_{start}_{end}")),
                    "start": start,
                    "end": end,
                    "seed_type": raw.get("seed_type"),
                    "earliest_date": earliest_date,
                    **({"latest_date": latest_date} if latest_date is not None else {}),
                }
            )
        self._planting_windows = normalized
        self.is_state_modified = True
        return {
            "status": "ok",
            "planting_windows": [dict(window) for window in self._planting_windows],
        }

    def check_planting_window(
        self, ridge_ids: list[int], seed_type: str | None = None
    ) -> str | None:
        """Return an error string if scenario planting-window rules block sowing."""
        if not self._planting_windows:
            return None
        today = datetime.fromtimestamp(
            float(self.time_manager.time()), tz=timezone(timedelta(hours=8))
        ).date()
        today_iso = today.isoformat()
        for ridge_id in ridge_ids:
            matches = [
                window
                for window in self._planting_windows
                if int(window["start"]) <= ridge_id <= int(window["end"])
                and (
                    not window.get("seed_type")
                    or seed_type is None
                    or str(window["seed_type"]) == str(seed_type)
                )
            ]
            for window in matches:
                earliest = str(window["earliest_date"])
                if today_iso < earliest:
                    return (
                        "Planting window not open for "
                        f"{window['label']} ridges {window['start']}-{window['end']}: "
                        f"earliest_date={earliest}, today={today_iso}"
                    )
                latest = window.get("latest_date")
                if latest is not None and today_iso > str(latest):
                    return (
                        "Planting window has closed for "
                        f"{window['label']} ridges {window['start']}-{window['end']}: "
                        f"latest_date={latest}, today={today_iso}"
                    )
        return None

    def configure_postharvest_market(
        self,
        *,
        name: str = "commodity",
        market_moisture_pct: float = 13.0,
        max_storage_moisture_pct: float = 13.5,
        drying_capacity_kg_per_day: float | None = None,
        storage_capacity_kg: float | None = None,
        quality_discount_wet: float = 0.0,
        quality_discount_damage: float = 0.0,
        grade: str = "commodity",
    ) -> None:
        """Configure optional post-harvest quality/capacity constraints."""
        self._postharvest_market = PostHarvestMarketPreset(
            name=name,
            market_moisture_pct=market_moisture_pct,
            max_storage_moisture_pct=max_storage_moisture_pct,
            drying_capacity_kg_per_day=drying_capacity_kg_per_day,
            storage_capacity_kg=storage_capacity_kg,
            quality_discount_wet=quality_discount_wet,
            quality_discount_damage=quality_discount_damage,
            grade=grade,
        )
        self.is_state_modified = True

    # ------------------------------------------------------------------
    # Environment tools (@env_tool) — called by scenario events / device apps
    # ------------------------------------------------------------------

    def trigger_pest_outbreak(
        self, ridge_ids: list[int], severity: float
    ) -> dict[str, Any]:
        """
        Trigger a localised pest outbreak on the specified ridges. [PDF-p7]

        Args:
            ridge_ids: List of ridge IDs affected.
            severity:  Pest pressure level to set (0.0-1.0).
        """
        for rid in ridge_ids:
            if 0 <= rid < self.num_ridges:
                r = self._ridges[rid]
                r.pest_pressure_base = max(r.pest_pressure_base, float(severity))
                r.last_spray_sim_time = None
                self._refresh_ridge_dynamics(r)
        self.is_state_modified = True
        return {"status": "ok", "affected_ridges": ridge_ids}

    def trigger_rainfall(self, mm: float) -> dict[str, Any]:
        """
        Apply an immediate rainfall event, updating soil VWC for all ridges. [PDF-p6]

        Args:
            mm: Rainfall amount in millimetres.
        """
        for r in self._ridges:
            r.soil_vwc = min(0.45, r.soil_vwc + mm / 100.0)
        self.is_state_modified = True
        return {"status": "ok", "rainfall_mm": mm}

    def set_ridge_planted(
        self,
        ridge_id: int,
        seed_type: str,
        seed_spacing_cm: float | None = None,
        seeds_planted: int | None = None,
    ) -> dict[str, Any]:
        """
        Mark a ridge as planted. Called by TractorApp after plant_seeds completes.

        Args:
            ridge_id:         Ridge ID (within the configured farm).
            seed_type:        SeedType value string.
            seed_spacing_cm:  In-row spacing in centimetres.
            seeds_planted:    Realized plant count for the ridge.
        """
        if not 0 <= ridge_id < self.num_ridges:
            return {"error": f"Invalid ridge_id {ridge_id}"}
        seed_error = self.validate_seed_for_crop(seed_type)
        if seed_error:
            raise ValueError(seed_error)
        if self._explicit_crop_id is not None:
            raise ValueError("Explicit physical crops must be planted through their device lifecycle")
        r = self._ridges[ridge_id]
        r.planted = True
        r.harvested = False
        r.seed_type = seed_type
        r.seed_spacing_cm = seed_spacing_cm
        r.seeds_planted = seeds_planted or 0
        r.planted_at_sim_time = float(self.time_manager.time())
        r.days_since_planted = 0
        r.growth_stage = ("PLANTED_PRE_EMERGENCE" if self.is_native_maize
                          else self.crop_profile.emergence_stage)
        r.grain_moisture_pct = 0.0
        self.is_state_modified = True
        return {
            "status": "ok",
            "ridge_id": ridge_id,
            "seed_type": seed_type,
            "seed_spacing_cm": seed_spacing_cm,
            "seeds_planted": r.seeds_planted,
        }

    def set_ridge_harvested(self, ridge_id: int) -> dict[str, Any]:
        """
        Mark a ridge as harvested. Called by TractorApp after harvest completes.
        Grain goes into the combine grain bin (tractor-side); it is only moved
        into warehouse inventory when `tractor.unload_grain()` is called. [PDF-p11]

        Args:
            ridge_id: Ridge ID (within the configured farm).
        """
        if not 0 <= ridge_id < self.num_ridges:
            return {"error": f"Invalid ridge_id {ridge_id}"}
        r = self._ridges[ridge_id]
        # Yield scales with yield_potential [设计]
        grain = round(self.grain_kg_per_ridge * r.yield_potential, 2)
        r.planted = False
        r.harvested = True
        r.seed_type = None
        r.seed_spacing_cm = None
        r.seeds_planted = 0
        r.growth_stage = GrowthStage.BARE.value
        r.days_since_planted = 0
        r.grain_moisture_pct = 0.0
        r.ndvi = -1.0
        r.canopy_temp_c = -1.0
        r.planted_at_sim_time = None
        self.is_state_modified = True
        return {"status": "ok", "ridge_id": ridge_id, "grain_kg_added": grain}

    def update_ridge_ndvi(self, ridge_id: int, ndvi: float) -> dict[str, Any]:
        """
        Update NDVI observation for a ridge. Called by DroneApp after survey. [PDF-p7]

        Args:
            ridge_id: Ridge ID (within the configured farm).
            ndvi:     NDVI value (0.0-1.0).
        """
        if not 0 <= ridge_id < self.num_ridges:
            return {"error": f"Invalid ridge_id {ridge_id}"}
        self._ridges[ridge_id].ndvi = round(float(ndvi), 4)
        self.is_state_modified = True
        return {"status": "ok"}

    def update_ridge_canopy_temp(self, ridge_id: int, temp_c: float) -> dict[str, Any]:
        """
        Update canopy temperature observation for a ridge.
        Called by DroneApp after thermal inspection. [PDF-p7]

        Args:
            ridge_id: Ridge ID (within the configured farm).
            temp_c:   Canopy temperature in °C.
        """
        if not 0 <= ridge_id < self.num_ridges:
            return {"error": f"Invalid ridge_id {ridge_id}"}
        self._ridges[ridge_id].canopy_temp_c = round(float(temp_c), 2)
        self.is_state_modified = True
        return {"status": "ok"}

    def update_ridge_pesticide(self, ridge_id: int) -> dict[str, Any]:
        """
        Record that pesticide was applied to a ridge. Called by TractorApp /
        FieldOpsApp after a spray completes. Pest/disease pressure then follows
        a worsen → plateau → recover trajectory driven by simulation time. [PDF-p9]

        Args:
            ridge_id: Ridge ID (within the configured farm).
        """
        if not 0 <= ridge_id < self.num_ridges:
            return {"error": f"Invalid ridge_id {ridge_id}"}
        r = self._ridges[ridge_id]
        now_t = float(self.time_manager.time())
        # Carry current observed pressure forward as the new baseline so the
        # post-spray curve starts from where the agent last saw it (no jump).
        r.pest_pressure_base = _effective_pressure(
            r.pest_pressure_base, r.last_spray_sim_time, now_t
        )
        r.disease_pressure_base = _effective_pressure(
            r.disease_pressure_base, r.last_spray_sim_time, now_t
        )
        r.last_spray_sim_time = now_t
        self._refresh_ridge_dynamics(r)
        self.is_state_modified = True
        return {"status": "ok"}

    def set_irrigation_pending(
        self, ridge_id: int, add_vwc: float, effect_ready_at: float | None = None
    ) -> dict[str, Any]:
        """
        Queue or apply irrigation effect for a ridge (called by FieldOpsApp).

        Args:
            ridge_id: Ridge ID (within the configured farm).
            add_vwc:  Volumetric water content increment from the irrigation duration.
            effect_ready_at:
                Absolute simulation timestamp when the effect should become visible.
                If omitted or already due, the moisture change is applied immediately.
        """
        if not 0 <= ridge_id < self.num_ridges:
            return {"error": f"Invalid ridge_id {ridge_id}"}
        now_t = float(self.time_manager.time())
        if effect_ready_at is not None and effect_ready_at > now_t:
            pending = self._pending_irrigation.setdefault(ridge_id, [])
            pending.append(
                {
                    "add_vwc": float(add_vwc),
                    "effect_ready_at": float(effect_ready_at),
                }
            )
            pending.sort(key=lambda item: item["effect_ready_at"])
            self.is_state_modified = True
            return {
                "status": "pending",
                "ridge_id": ridge_id,
                "effect_ready_at": float(effect_ready_at),
            }

        self._apply_irrigation_effect(ridge_id, float(add_vwc))
        self.is_state_modified = True
        return {"status": "ok"}

    def set_season_phase(self, phase: str) -> dict[str, Any]:
        """
        Update the high-level season phase label. [设计]

        Args:
            phase: SeasonPhase value string ("prep"/"planting"/"growing"/"harvest").
        """
        self._season_phase = phase
        self.is_state_modified = True
        return {"status": "ok", "season_phase": phase}

    # ------------------------------------------------------------------
    # Physics integration (FarmPhysicsState + orchestrator)
    # ------------------------------------------------------------------

    def attach_weather_app(self, weather_app: WeatherApp) -> None:
        """Forward a WeatherApp reference for the physics orchestrator.

        Idempotent. The first call wins; later calls update the reference if
        a different WeatherApp is provided. Called by other apps' __init__.
        """
        self._weather_app = weather_app

    def attach_system_app(self, system_app) -> None:
        """Bind a SystemApp <-> FarmWorldApp reference so SystemApp.advance_time
        can fire the physics orchestrator after a time jump. Called by scenarios
        in init_and_populate_apps after both apps are constructed.
        """
        try:
            system_app.attach_farm_world_app(self)
        except AttributeError:
            pass  # Older SystemApp without the hook — silent no-op.

    @property
    def physics(self) -> FarmPhysicsState:
        """Lazily-constructed physics state container.

        First access activates the physics path: from now on, tools that
        record actions or queue management events will route through engine
        updates instead of mutating ridge fields directly.
        """
        if self._physics is None:
            from fairy.apps.farm_world.farm_physics_state import (
                FarmPhysicsState,
            )

            self._physics = FarmPhysicsState(num_ridges=self.num_ridges, crop_type=self.crop_type,
                                             crop_id=self._explicit_crop_id,
                                             field_length_m=self.field_length_m,
                                             ridge_width_m=self.ridge_width_m)
            if self._explicit_crop_id is not None:
                self._physics.engines_active = True
        return self._physics

    @property
    def physics_active(self) -> bool:
        """True iff physics has been activated by a profile or queued action.

        Used by legacy helpers (_effective_pressure, _refresh_ridge_dynamics)
        to gate themselves out when physics is in charge. When False, the
        old behaviour is preserved verbatim for backward compatibility.
        """
        return self._physics is not None and self._physics.engines_active

    def _crop_metadata(self) -> dict[str, Any]:
        """Keep historical soybean snapshots unchanged; identify other crops explicitly."""
        if self.crop_name == "soybean":
            return {}
        return {
            "crop_name": self.crop_name,
            "variety_name": self.variety_name,
            "rows_per_ridge": self.rows_per_ridge,
            "ridge_width_m": self.ridge_width_m,
            "grain_mass_basis": "market_moisture",
            "market_moisture_pct": self._postharvest_market.market_moisture_pct,
        }

    def validate_seed_for_crop(self, seed_type: str | None) -> str | None:
        """Resolve seed/crop/backend admission before resource consumption."""
        from fairy.apps.farm_world.crop_profiles import official_seed_backend_error

        if seed_type is None:
            return "Load compatible seeds before planting"
        backend = self._physics.crop_backend if self._physics is not None else None
        if backend is not None and backend.config.crop_name != self.crop_name:
            return "Crop identity does not match the native backend; restore a complete farm checkpoint"
        if self.is_native_maize:
            return None if seed_type == "MAIZE_201" else "The native maize crop requires MAIZE_201 seeds"
        if self._explicit_crop_id is not None and seed_type not in self.crop_definition.seed_types:
            return f"Seed {seed_type} is not permitted by the selected crop/cultivar rules"
        if seed_type == "MAIZE_201":
            return "MAIZE_201 seeds require crop_name='maize' with the WOFOST backend"
        if seed_type not in self.crop_definition.seed_types:
            return f"Seed {seed_type!r} is not supported by this farm's crop rules"
        if seed_crop_type(seed_type) != self.crop_type:
            return f"Seed {seed_type} does not match farm crop {self.crop_type}"
        return official_seed_backend_error(seed_type, self._physics)

    def validate_biotic_management(self) -> str | None:
        """Reject management for a native crop without an adapted biotic model."""
        if self.is_native_maize:
            return "Native WOFOST maize does not simulate weeds, pests or diseases; biotic treatment is not supported"
        return None

    def is_ridge_mature(self, ridge_id: int) -> bool:
        """Native maturity is authoritative; legacy crops retain their own stage."""
        if self._physics is not None and self._physics.crop_backend is not None:
            return self._physics.phenology.states[ridge_id].maturity_date is not None
        stages = {stage.upper() for stage in self.crop_definition.harvest_rules.stage_codes}
        return str(self._ridges[ridge_id].growth_stage).upper() in stages

    def configure_crop_backend(
        self, backend: str = "legacy", **options: Any
    ) -> dict[str, Any]:
        """Select the crop backend before planting or advancing the season.

        This is scenario configuration, rather than an agent-visible tool.
        Switching a live crop would mix state from different models; resume
        WOFOST crops through the full farm checkpoint API instead.
        """
        if backend not in {"legacy", "wofost"}:
            raise ValueError("crop backend must be 'legacy' or 'wofost'")
        if backend == "wofost" and self._explicit_crop_id == "maize":
            raise ValueError("The explicit early maize model cannot switch to native WOFOST; create a fresh compatible farm")
        if backend == "legacy" and self.is_native_maize:
            raise ValueError("Native maize requires the WOFOST crop backend; create a fresh legacy farm")
        if backend == "legacy" and options:
            raise ValueError("WOFOST options require the 'wofost' crop backend")
        physics = self.physics
        config = None
        if backend == "wofost":
            from fairy.physics.wofost_backend import WofostConfig

            config = WofostConfig(**{"latitude_deg": physics.latitude_deg,
                                      "crop_name": self.crop_type, **options})
        if config is not None and self._explicit_crop_id not in (None, config.crop_name):
            raise ValueError("An explicit crop identity cannot be changed by backend selection")
        current = physics.crop_backend
        if current is not None and config is not None and current.config.crop_name != config.crop_name:
            raise ValueError("Changing crop identity requires a fresh farm or complete farm checkpoint")
        if physics.crop_backend_name == backend and (
            current is None or current.config == config
        ):
            return {"status": "unchanged", "crop_backend": backend}
        if physics.action_log or any(
            state.emerged or state.accumulated_gdd > 0.0
            for state in physics.phenology.states.values()
        ):
            raise ValueError(
                "Choose the crop backend before planting/advancing the season. "
                "A mid-season WOFOST start requires a WOFOST checkpoint."
            )
        if backend == "wofost":
            from fairy.physics.wofost_backend import WofostBackend

            current = WofostBackend(config)
            from fairy.physics.crop_profiles import get_crop_profile as get_native_profile

            native_profile = get_native_profile(config.crop_name)
            self.crop_name = config.crop_name
            self.variety_name = config.variety_name
            # Keep the explicitly configured field geometry and warehouse stock.
            # Backend selection changes biology, not acreage or material ownership.
            physics.crop_type = self.crop_type
            physics.crop_profile = self.crop_profile
            current.bind_physics(physics)
            if config.crop_name == "maize":
                # Native maize does not borrow the soybean biotic model.
                for state in physics.biotic.states.values():
                    state.weed_pressure = state.insect_pressure = state.disease_pressure = 0.0
                for ridge in self._ridges:
                    ridge.pest_pressure = ridge.pest_pressure_base = 0.0
                    ridge.disease_pressure = ridge.disease_pressure_base = 0.0
                self._postharvest_market.market_moisture_pct = native_profile.market_moisture_frac * 100
                self._postharvest_market.max_storage_moisture_pct = native_profile.max_storage_moisture_frac * 100
                self._postharvest_market.require_safe_moisture = True
        else:
            current = None
        physics.crop_backend = current
        physics.crop_backend_name = backend
        physics.yield_recovery.params.biological_yield_is_dry_matter = backend == "wofost"
        physics.engines_active = True
        return {
            "status": "ok",
            "crop_backend": backend,
            "details": current.snapshot() if current is not None else None,
        }

    def configure_physics_profile(
        self,
        profile_name: str,
        location: str | None = None,
        scenario_type: str | None = None,
        latitude_deg: float | None = None,
        random_seed: int | None = None,
        seed_growth_overrides: dict[str, dict[str, float]] | None = None,
        **scenario_metadata: Any,
    ) -> dict[str, Any]:
        """Activate physics with scenario-specific configuration.

        Called from scenario `_configure_physics_layers` methods. Idempotent:
        repeat calls update the labels but do not reset engine state. Extra
        keyword arguments (e.g. ``seed_type``) are stored as scenario
        metadata for later inspection without forcing the signature to
        evolve every time a mirror scenario adds a new hint.
        """
        physics = self.physics
        physics.profile_name = profile_name
        if location is not None:
            physics.location = location
        if scenario_type is not None:
            physics.scenario_type = scenario_type
        if latitude_deg is not None:
            physics.latitude_deg = float(latitude_deg)
        if random_seed is not None:
            physics.random_seed = int(random_seed)
        if scenario_metadata:
            # Merge into a freeform metadata bag (created lazily on first use).
            existing = getattr(physics, "scenario_metadata", None)
            if existing is None:
                physics.scenario_metadata = {}  # type: ignore[attr-defined]
                existing = physics.scenario_metadata  # type: ignore[attr-defined]
            existing.update(scenario_metadata)
        if seed_growth_overrides:
            self._apply_seed_growth_overrides(physics, seed_growth_overrides)
        # If a registered round-4 PhysicsProfile matches this name, wire its
        # WeatherGenerator + biotic-outbreak schedule into the physics state.
        # Round-3 episodes pass freeform names that don't match the registry —
        # those proceed with the static weather.set_weather pattern.
        from fairy.physics.profiles import get_profile

        registered = get_profile(profile_name)
        if registered is not None:
            from fairy.physics import WeatherGenerator

            physics.weather_generator = WeatherGenerator(
                config=registered.to_weather_generator_config(),
                seed=registered.rng_seed,
            )
            physics.latitude_deg = registered.latitude_deg
            physics.random_seed = registered.rng_seed
            # Stash profile metadata so the orchestrator can apply weather
            # events and biotic outbreaks during the daily tick.
            physics.profile = registered  # type: ignore[attr-defined]
        physics.engines_active = True
        if physics.crop_backend is not None:
            physics.crop_backend.bind_physics(physics)
        return {
            "status": "ok",
            "profile_name": profile_name,
            "location": physics.location,
            "scenario_type": physics.scenario_type,
            "profile_registered": registered is not None,
        }

    def _apply_seed_growth_overrides(
        self,
        physics: FarmPhysicsState,
        overrides: dict[str, dict[str, float]],
    ) -> None:
        """Apply scenario-local canopy growth overrides for named seed types."""
        from dataclasses import replace

        from fairy.physics.canopy_biomass_engine import (
            SeedType as CanopySeedType,
        )

        for seed_name, raw_updates in overrides.items():
            try:
                seed_type = CanopySeedType(str(seed_name))
            except ValueError:
                seed_type = CanopySeedType[str(seed_name)]

            current = physics.canopy.seed_params.get(seed_type)
            if current is None:
                raise ValueError(f"No canopy growth parameters for seed {seed_name!r}")

            valid_fields = set(current.__dataclass_fields__)
            updates: dict[str, float] = {}
            for key, value in raw_updates.items():
                if key not in valid_fields:
                    raise ValueError(
                        f"Unknown seed growth parameter {key!r} for seed {seed_name!r}"
                    )
                updates[key] = float(value)
            physics.canopy.seed_params[seed_type] = replace(current, **updates)

    def record_action(self, action: FarmActionRecord) -> None:
        """Append a structured FarmActionRecord to the physics audit log."""
        self.physics.record_action(action)
        self.is_state_modified = True

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def commit_daily_physics(self) -> dict[str, Any]:
        """
        Force a full daily physics tick at the current simulation time.

        Use this when you've taken several actions and want to advance the
        world by exactly one day so their delayed effects (canopy growth,
        biotic pressure decay, soil dry-down) become visible. Most agents
        should prefer ``SystemApp.advance_time(days=N)`` to advance multiple
        days; this is the single-day version with explicit "commit" semantics.
        """
        if not self.physics_active:
            return {"status": "noop", "reason": "physics_inactive"}
        # Advance the clock by one day, then run the orchestrator.
        self.time_manager.add_offset(86400)
        result = self.advance_physics_time()
        return {"status": "ok", "tick_result": result}

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply_fertigation(
        self,
        start_ridge: int,
        end_ridge: int,
        nutrient_amount: float,
        water_mm: float,
    ) -> dict[str, Any]:
        """
        Apply nutrient and carrier water to a ridge range.

        The nutrient amount is normalized (1.0 = a typical strong dose).
        ``water_mm`` is the per-ridge carrier-water depth; it consumes the
        irrigation quota and enters the soil water balance.

        Args:
            start_ridge:     First ridge (within the configured farm).
            end_ridge:       Last ridge (within the configured farm, inclusive, >= start_ridge).
            nutrient_amount: Normalized nutrient input (>0); typical 0.5-1.5.
            water_mm:        Carrier-water metadata in millimetres (>=0).
        """
        if not 0 <= start_ridge <= end_ridge < self.num_ridges:
            return {"error": f"Invalid ridge range [{start_ridge}, {end_ridge}]"}
        if float(nutrient_amount) <= 0:
            return {"error": "nutrient_amount must be > 0"}
        if float(water_mm) < 0:
            return {"error": "water_mm must be >= 0"}

        ridge_ids = list(range(start_ridge, end_ridge + 1))
        ridge_count = len(ridge_ids)
        nutrient_amount_f = float(nutrient_amount)
        water_mm_f = float(water_mm)
        # Keep the same calibration as TractorApp._register_fertilizer_with_physics:
        # 30 kg/ridge maps to a normalized nutrient amount of 1.0.
        fertilizer_kg_used = round(nutrient_amount_f * 30.0 * ridge_count, 4)
        field_equivalent_irrigation_mm = (
            water_mm_f * ridge_count / max(1, self.num_ridges)
        )

        if water_mm_f > 0:
            quota_error = self.check_irrigation_quota(field_equivalent_irrigation_mm)
            if quota_error:
                return {"error": quota_error}
        if fertilizer_kg_used > 0 and not self.consume_fertilizer(fertilizer_kg_used):
            return {
                "error": (
                    "insufficient fertilizer or fertilizer quota exceeded: "
                    f"need {fertilizer_kg_used:.2f} kg"
                )
            }

        if self.physics_active:
            from fairy.apps.farm_world.farm_action_record import (
                FarmActionRecord,
            )
            from fairy.physics import ManagementAction, ManagementActionType

            for ridge_id in ridge_ids:
                self.physics.queue_management_action(
                    ridge_id,
                    ManagementAction(
                        action_type=ManagementActionType.FERTIGATION,
                        amount=water_mm_f,
                        quality=1.0,
                        metadata={
                            "nutrient_amount": nutrient_amount_f,
                            "water_mm": water_mm_f,
                            "fertilizer_kg_per_ridge": fertilizer_kg_used
                            / max(1, ridge_count),
                        },
                    ),
                )
            import uuid as _uuid

            self.record_action(
                FarmActionRecord(
                    action_id=str(_uuid.uuid4())[:8],
                    timestamp=float(self.time_manager.time()),
                    actor_app=self.name,
                    action_type="fertigation",
                    ridge_ids=ridge_ids,
                    parameters={
                        "nutrient_amount": nutrient_amount_f,
                        "carrier_water_mm": water_mm_f,
                        "fertilizer_kg_used": fertilizer_kg_used,
                        "field_equivalent_irrigation_mm": round(
                            field_equivalent_irrigation_mm, 4
                        ),
                    },
                    direct_effect_summary={
                        "nutrient_input_registered": True,
                        "water_input_registered": water_mm_f > 0,
                        "soil_water_input_registered": water_mm_f > 0,
                    },
                )
            )
            self.advance_physics_time()

        if water_mm_f > 0:
            regime_status = self.record_irrigation_use(field_equivalent_irrigation_mm)
        else:
            regime_status = self._management_regime.to_dict()
        self.is_state_modified = True
        return {
            "status": "ok",
            "fertigated_ridges": ridge_ids,
            "nutrient_amount": nutrient_amount_f,
            "carrier_water_mm": water_mm_f,
            "fertilizer_kg_used": fertilizer_kg_used,
            "field_equivalent_irrigation_mm": round(
                field_equivalent_irrigation_mm, 4
            ),
            "management_regime": regime_status,
        }

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def dry_grain(self, target_moisture_pct: float = 13.0) -> dict[str, Any]:
        """
        Dry harvested grain in storage to a target moisture percentage.

        Used post-harvest when grain came in above the safe storage moisture
        window (usually 13-14%). The drying step advances the yield-recovery
        state's grain_moisture_frac for harvested ridges, and flips the
        inventory's `grain_dried` flag so subsequent `store_grain()` knows
        the grain is safe for long-term storage.

        Args:
            target_moisture_pct: Target storage moisture, typically 13.0.
                                 Must be in [11, 16].
        """
        if self.shared_warehouse is not None:
            return {"error": "Dry an explicit batch through Warehouse.dry_grain(batch_id)"}
        if not 11.0 <= float(target_moisture_pct) <= 16.0:
            return {"error": "target_moisture_pct must be in [11, 16]"}
        market = self._postharvest_market
        if float(target_moisture_pct) > market.max_storage_moisture_pct:
            return {
                "error": (
                    "target_moisture_pct exceeds storage limit: "
                    f"{float(target_moisture_pct):.1f}% > {market.max_storage_moisture_pct:.1f}%"
                )
            }
        if (
            market.drying_capacity_kg_per_day is not None
            and self._inventory.harvest_grain_kg
            > market.drying_capacity_kg_per_day + 1e-9
        ):
            return {
                "error": (
                    "drying capacity exceeded: "
                    f"{self._inventory.harvest_grain_kg:.2f} kg pending, "
                    f"capacity {market.drying_capacity_kg_per_day:.2f} kg/day"
                )
            }
        storage_moisture = self._trailer_grain_moisture_pct()
        if (
            storage_moisture is not None
            and storage_moisture <= market.max_storage_moisture_pct + 1e-9
        ):
            self.is_state_modified = True
            return {
                "status": "ok",
                "drying_skipped": True,
                "reason": "current_batch_already_safe_for_storage",
                "storage_grain_moisture_pct": round(storage_moisture, 3),
                "max_storage_moisture_pct": round(market.max_storage_moisture_pct, 3),
                "trailer_grain_kg": round(self._inventory.harvest_grain_kg, 2),
                "batch_ridge_ids": list(self._trailer_grain_ridge_ids),
                "postharvest_market": market.to_dict(),
            }
        target_frac = float(target_moisture_pct) / 100.0
        affected = 0
        if self.physics_active:
            for ridge_id in self._trailer_grain_ridge_ids:
                state = self.physics.yield_recovery.states.get(ridge_id)
                if state is not None and state.harvested:
                    state.grain_moisture_frac = target_frac
                    state.drying_required = False
                    affected += 1
        self._trailer_grain_moistures_pct = [float(target_moisture_pct)]
        self._inventory.grain_dried = True
        self.is_state_modified = True
        return {
            "status": "ok",
            "target_moisture_pct": float(target_moisture_pct),
            "ridges_dried": affected,
            "batch_ridge_ids": list(self._trailer_grain_ridge_ids),
            "trailer_grain_kg": round(self._inventory.harvest_grain_kg, 2),
            "postharvest_market": market.to_dict(),
        }

    def _trailer_grain_moisture_pct(self) -> float | None:
        if not self._trailer_grain_moistures_pct:
            return None
        return max(float(value) for value in self._trailer_grain_moistures_pct)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def store_grain(self) -> dict[str, Any]:
        """
        Finalise harvested grain into long-term warehouse storage.

        Moves the trailer's `harvest_grain_kg` into the warehouse's
        `warehouse_grain_kg` and zeroes the trailer. Records an action for
        the workflow validator + FOS gate matchers so the post-harvest
        sequence (harvest → dry → store) is observable end-to-end. A strict
        facility rejects unknown or unsafe moisture; the historical permissive
        single-farm facility admits it with a warning.
        """
        if self.shared_warehouse is not None:
            return {"error": "Store an explicit batch through Warehouse.store_grain(batch_id)"}
        moved_kg = round(self._inventory.harvest_grain_kg, 2)
        market = self._postharvest_market
        if market.require_safe_moisture and moved_kg > 0:
            moisture = self._trailer_grain_moisture_pct()
            if moisture is None or moisture > market.max_storage_moisture_pct + 1e-9:
                return {"error": "Batch must have known, safe storage moisture before admission",
                        "storage_grain_moisture_pct": moisture,
                        "max_storage_moisture_pct": market.max_storage_moisture_pct}
        if (
            market.storage_capacity_kg is not None
            and self._inventory.warehouse_grain_kg + moved_kg
            > market.storage_capacity_kg + 1e-9
        ):
            return {
                "error": (
                    "storage capacity exceeded: "
                    f"need {moved_kg:.2f} kg, remaining "
                    f"{market.storage_capacity_kg - self._inventory.warehouse_grain_kg:.2f} kg"
                )
            }
        self._inventory.warehouse_grain_kg = round(
            self._inventory.warehouse_grain_kg + moved_kg, 2
        )
        self._inventory.harvest_grain_kg = 0.0
        warning = None
        storage_moisture = self._trailer_grain_moisture_pct()
        grain_safe_without_drying = (
            storage_moisture is not None
            and storage_moisture <= market.max_storage_moisture_pct + 1e-9
        )
        grain_was_dried_before_store = self._inventory.grain_dried
        if grain_safe_without_drying:
            self._inventory.grain_dried = True
        if (
            not self._inventory.grain_dried
            and not grain_safe_without_drying
            and moved_kg > 0
        ):
            warning = "grain stored without drying — long-term spoilage risk"

        if self.physics_active:
            import uuid as _uuid

            from fairy.apps.farm_world.farm_action_record import (
                FarmActionRecord,
            )

            self.record_action(
                FarmActionRecord(
                    action_id=str(_uuid.uuid4())[:8],
                    timestamp=float(self.time_manager.time()),
                    actor_app=self.name,
                    action_type="store_grain",
                    ridge_ids=[],
                    parameters={},
                    direct_effect_summary={
                        "warehouse_grain_kg": self._inventory.warehouse_grain_kg,
                        "moved_kg": moved_kg,
                        "batch_ridge_ids": list(self._trailer_grain_ridge_ids),
                    },
                )
            )
        batch_ridge_ids = list(self._trailer_grain_ridge_ids)
        self._trailer_grain_ridge_ids = []
        self._trailer_grain_moistures_pct = []
        self.is_state_modified = True
        return {
            "status": "ok",
            "moved_kg": moved_kg,
            "batch_ridge_ids": batch_ridge_ids,
            "warehouse_grain_kg": self._inventory.warehouse_grain_kg,
            "trailer_grain_kg": self._inventory.harvest_grain_kg,
            "storage_grain_moisture_pct": (
                round(storage_moisture, 3) if storage_moisture is not None else None
            ),
            "max_storage_moisture_pct": round(market.max_storage_moisture_pct, 3),
            "stored_without_drying": bool(
                grain_safe_without_drying
                and not grain_was_dried_before_store
                and moved_kg > 0
            ),
            "postharvest_market": market.to_dict(),
            **({"warning": warning} if warning else {}),
        }

    def advance_physics_time(
        self, target_sim_time: float | None = None
    ) -> dict[str, Any]:
        """Run physics forward to the current simulation clock.

        Idempotent: if no time has elapsed since the last call, this is a
        no-op. Day-boundary crossings trigger one daily tick per crossed
        day; sub-daily intervals trigger a partial soil update if any
        irrigation is pending. The orchestrator owns the actual engine call
        sequence.

        Returns a small status dict for tracing.
        """
        if self._physics is None or not self._physics.engines_active:
            return {"status": "skipped", "reason": "physics_inactive"}
        from fairy.apps.farm_world.physics_orchestrator import (
            advance_physics_time as _advance,
        )

        current_time = (
            float(target_sim_time)
            if target_sim_time is not None
            else float(self.time_manager.time())
        )
        self._sim_date = datetime.fromtimestamp(current_time, tz=self.simulation_timezone).strftime(
            "%Y-%m-%d"
        )
        if self.farm_environment is not None and not self.farm_environment._syncing:
            self.farm_environment.sync(current_time)
            return {"status": "synchronized", "last_physics_sim_time": current_time}
        result = _advance(self, current_time,
                          weather_inputs_provider=(self.farm_environment.weather_inputs
                                                   if self.farm_environment is not None else None))
        self._refresh_auto_season_phase()
        return result

    def _advance_physics_time_local(self, target_sim_time: float):
        return self.advance_physics_time(target_sim_time)

    def _refresh_auto_season_phase(self, *, field_prepared: bool = False) -> None:
        """Derive the calendar label for opt-in seasons from actual crop state.

        Legacy scenarios author the phase explicitly, so automatic transitions
        are enabled only by ``configure_physics_profile(auto_season_phase=True)``.
        A farm enters harvest when its first ridge matures; the label remains
        harvest while its grain is being dried and stored after the field clears.
        """
        physics = self._physics
        if physics is None or not getattr(physics, "scenario_metadata", {}).get(
            "auto_season_phase", False
        ):
            return
        mature_stage = self.crop_profile.mature_stage.upper()
        if any(r.harvested or (r.planted and r.growth_stage.upper() == mature_stage)
               for r in self._ridges):
            self._season_phase = SeasonPhase.HARVEST.value
        elif any(state.emerged for state in physics.phenology.states.values()):
            self._season_phase = SeasonPhase.GROWING.value
        elif any(r.planted for r in self._ridges) or field_prepared:
            self._season_phase = SeasonPhase.PLANTING.value

    def sync_initial_physics_state(
        self,
        target_sim_time: float | None = None,
    ) -> dict[str, Any]:
        """Seed engine state from current ridge state without advancing days.

        This is the explicit "copy scenario initial conditions into physics"
        operation. It sets the physics start timestamp and mirrors ridge-level
        setup into the soil/phenology/canopy/management/yield engines. If
        physics is already initialized, it does not advance time.
        """
        if self._physics is None or not self._physics.engines_active:
            return {"status": "skipped", "reason": "physics_inactive"}
        if self._physics.last_physics_sim_time is not None:
            return {
                "status": "already_initialized",
                "day_ticks_run": 0,
                "last_physics_sim_time": self._physics.last_physics_sim_time,
            }
        current_time = (
            float(target_sim_time)
            if target_sim_time is not None
            else float(self.time_manager.time())
        )
        return self.advance_physics_time(current_time)

    def prepare_for_time_advance(
        self, current_sim_time: float | None = None
    ) -> dict[str, Any]:
        """FarmWorld hook called before an external clock jump.

        ``SystemApp`` is framework-level time plumbing; the FARM-specific
        decision about whether physics needs an initial seed belongs here.
        """
        return self.sync_initial_physics_state(current_sim_time)

    # Fields hidden from agent — observable only via SensorApp / DroneApp /
    # RobotApp (or ground-truth driver fields never exposed at all)
    _OBSERVATION_FIELDS = {
        "soil_vwc",
        "soil_temp_c",
        "ndvi",
        "canopy_temp_c",
        "pest_pressure",
        "disease_pressure",
        "pest_pressure_base",
        "disease_pressure_base",
        "last_spray_sim_time",
        "planted_at_sim_time",
    }

    def _agent_ridge_dict(self, ridge: RidgeState) -> dict[str, Any]:
        """Return ridge dict with observation fields stripped for agent tools."""
        self._refresh_ridge_dynamics(ridge)
        return {
            "farm_id": self.farm_id,
            "crop_type": self.crop_type,
            "crop_id": self.crop_id,
            "cultivar_id": self.cultivar_id,
            **{k: v for k, v in ridge.to_dict().items()
               if k not in self._OBSERVATION_FIELDS},
        }

    # ------------------------------------------------------------------
    # Internal helpers (used by device apps directly, not via tool system)
    # ------------------------------------------------------------------

    def _refresh_ridge_dynamics(self, ridge: RidgeState) -> None:
        """
        Derive all time-driven ridge fields from stored timestamps and the
        current simulation clock. Called from every read path; no caller ever
        has to "tick" a day.

        Pest / disease pressure    ← _effective_pressure(base, last_spray, now)
        pesticide_applied_days_ago ← floor((now - last_spray) / 86400)
        days_since_planted         ← floor((now - planted_at) / 86400)
        growth_stage               ← _stage_for_days(days_since_planted)
        grain_moisture_pct         ← _grain_moisture_for_stage(stage, days_in_r6_plus)

        Scenarios that bypass `set_ridge_planted` and manually set
        `days_since_planted` / `growth_stage` leave `planted_at_sim_time` as
        None, and the growth fields are not overwritten here.
        """
        now_t = float(self.time_manager.time())
        self._apply_due_irrigation_for_ridge(ridge.ridge_id, now_t)

        # Pest / disease (three-phase curve after spray)
        ridge.pest_pressure = _effective_pressure(
            ridge.pest_pressure_base, ridge.last_spray_sim_time, now_t
        )
        ridge.disease_pressure = _effective_pressure(
            ridge.disease_pressure_base, ridge.last_spray_sim_time, now_t
        )
        if ridge.last_spray_sim_time is None:
            ridge.pesticide_applied_days_ago = -1
        else:
            elapsed = max(0.0, now_t - ridge.last_spray_sim_time)
            ridge.pesticide_applied_days_ago = int(elapsed // _SECONDS_PER_DAY)

        # Growth progression (only when a real `set_ridge_planted` happened).
        # Once physics engines are active, the orchestrator owns stage and
        # moisture; legacy timestamp refresh must not overwrite its shadow.
        if (
            not self.physics_active
            and ridge.planted
            and ridge.planted_at_sim_time is not None
        ):
            elapsed_s = max(0.0, now_t - ridge.planted_at_sim_time)
            days = int(elapsed_s // _SECONDS_PER_DAY)
            ridge.days_since_planted = days
            ridge.growth_stage = self.crop_profile.stage_for_days(days)
            ridge.grain_moisture_pct = self.crop_profile.grain_moisture_for_days(days)

    def get_ridge(self, ridge_id: int) -> RidgeState:
        """Direct access for device apps that hold a reference to this app."""
        r = self._ridges[ridge_id]
        self._refresh_ridge_dynamics(r)
        return r

    def set_ridges(self, ridges: list[RidgeState]) -> None:
        """Replace the ridge list (called by TractorApp.form_ridges)."""
        self._ridges = ridges
        self.is_state_modified = True

    def get_avg_vwc(self) -> float:
        """Return average soil VWC across all ridges (used by WeatherApp)."""
        self._apply_due_irrigation()
        return round(sum(r.soil_vwc for r in self._ridges) / self.num_ridges, 4)

    def get_pending_irrigation_for_ridges(
        self, ridge_ids: list[int]
    ) -> list[dict[str, Any]]:
        """Return pending irrigation sessions overlapping the requested ridges."""
        self._apply_due_irrigation()
        results = []
        seen_keys: set[tuple[int, float, float]] = set()
        for ridge_id in ridge_ids:
            for item in self._pending_irrigation.get(ridge_id, []):
                key = (
                    ridge_id,
                    float(item["effect_ready_at"]),
                    float(item["add_vwc"]),
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                results.append(
                    {
                        "ridge_id": ridge_id,
                        "effect_ready_at": float(item["effect_ready_at"]),
                        "add_vwc": float(item["add_vwc"]),
                    }
                )
        results.sort(key=lambda item: (item["effect_ready_at"], item["ridge_id"]))
        return results

    def consume_seeds(self, seed_type: str, count: int) -> bool:
        """Deduct seeds from warehouse. Returns False if insufficient."""
        if self.shared_warehouse is not None:
            return self.shared_warehouse.consume_seeds(seed_type, count)
        current = self._inventory.seed_stock.get(seed_type, 0)
        if current < count:
            return False
        self._inventory.seed_stock[seed_type] = current - count
        self.is_state_modified = True
        return True

    def consume_pesticide(self, liters: float) -> bool:
        """Deduct pesticide from warehouse. Returns False if insufficient."""
        if type(liters) not in (int, float) or not math.isfinite(liters) or liters <= 0:
            return False
        if self.shared_warehouse is not None:
            return self.shared_warehouse.consume_pesticide(liters)
        if self._inventory.pesticide_liters < liters:
            return False
        self._inventory.pesticide_liters -= liters
        self.is_state_modified = True
        return True

    def check_chemical_application(
        self, chemical_type: str, liters: float
    ) -> str | None:
        """Return an error string if a chemical application would violate regime caps."""
        regime = self._management_regime
        chemical_type = str(chemical_type)
        application_day_already_counted = self._chemical_application_day_counted(
            chemical_type
        )
        if regime.regime in {"organic", "low_input_organic"} and chemical_type in {
            "herbicide",
            "insecticide",
            "fungicide",
        }:
            return f"{chemical_type} is not allowed under {regime.regime} management"
        if chemical_type == "insecticide" and not application_day_already_counted:
            cap = regime.max_insecticide_applications
            if cap is not None and regime.insecticide_applications_used + 1 > cap:
                return f"insecticide application cap exceeded: {regime.insecticide_applications_used}/{cap} already used"
        elif chemical_type == "fungicide" and not application_day_already_counted:
            cap = regime.max_fungicide_applications
            if cap is not None and regime.fungicide_applications_used + 1 > cap:
                return f"fungicide application cap exceeded: {regime.fungicide_applications_used}/{cap} already used"
        active_ingredient_kg = float(liters) * 0.001
        if (
            regime.active_ingredient_cap_kg is not None
            and regime.active_ingredient_used_kg + active_ingredient_kg
            > regime.active_ingredient_cap_kg + 1e-9
        ):
            return (
                "active ingredient cap exceeded: "
                f"need {active_ingredient_kg:.4f} kg, remaining "
                f"{regime.active_ingredient_cap_kg - regime.active_ingredient_used_kg:.4f} kg"
            )
        return None

    def record_chemical_application(
        self, chemical_type: str, liters: float
    ) -> dict[str, Any]:
        """Update season-level chemical-use counters after a successful application."""
        regime = self._management_regime
        application_day = self.get_state()["sim_date"]
        if (
            chemical_type == "insecticide"
            and regime.last_insecticide_application_day != application_day
        ):
            regime.insecticide_applications_used += 1
            regime.last_insecticide_application_day = application_day
        elif (
            chemical_type == "fungicide"
            and regime.last_fungicide_application_day != application_day
        ):
            regime.fungicide_applications_used += 1
            regime.last_fungicide_application_day = application_day
        regime.active_ingredient_used_kg = round(
            regime.active_ingredient_used_kg + float(liters) * 0.001,
            6,
        )
        self.is_state_modified = True
        return regime.to_dict()

    def _chemical_application_day_counted(self, chemical_type: str) -> bool:
        regime = self._management_regime
        application_day = self.get_state()["sim_date"]
        if chemical_type == "insecticide":
            return regime.last_insecticide_application_day == application_day
        if chemical_type == "fungicide":
            return regime.last_fungicide_application_day == application_day
        return False

    def check_machine_pass(self, passes: int = 1) -> str | None:
        """Return an error string if a machinery pass would violate regime caps."""
        regime = self._management_regime
        if (
            regime.max_machine_passes is not None
            and regime.machine_passes_used + int(passes) > regime.max_machine_passes
        ):
            return (
                "machine pass cap exceeded: "
                f"{regime.machine_passes_used}/{regime.max_machine_passes} already used"
            )
        return None

    def record_machine_pass(self, passes: int = 1) -> dict[str, Any]:
        """Update season-level machinery pass counters after a successful operation."""
        self._management_regime.machine_passes_used += int(passes)
        self.is_state_modified = True
        return self._management_regime.to_dict()

    def check_mechanical_weed_ridge_cap(self, ridge_count: int) -> str | None:
        """Return an error if mechanical weeding would exceed the ridge-area cap."""
        regime = self._management_regime
        if (
            regime.max_mechanical_weed_ridges is not None
            and regime.mechanical_weed_ridges_treated + int(ridge_count)
            > regime.max_mechanical_weed_ridges
        ):
            return (
                "mechanical weed ridge cap exceeded: "
                f"{regime.mechanical_weed_ridges_treated}/"
                f"{regime.max_mechanical_weed_ridges} already treated"
            )
        return None

    def record_mechanical_weed_ridges(self, ridge_count: int) -> dict[str, Any]:
        """Update season-level mechanical weed-control area after success."""
        self._management_regime.mechanical_weed_ridges_treated += int(ridge_count)
        self.is_state_modified = True
        return self._management_regime.to_dict()

    def check_irrigation_quota(self, water_mm_field_equivalent: float) -> str | None:
        regime = self._management_regime
        if (
            regime.irrigation_quota_mm_total is not None
            and regime.irrigation_used_mm_total + float(water_mm_field_equivalent)
            > regime.irrigation_quota_mm_total + 1e-9
        ):
            return (
                "irrigation quota exceeded: "
                f"need {float(water_mm_field_equivalent):.3f} field-mm, remaining "
                f"{regime.irrigation_quota_mm_total - regime.irrigation_used_mm_total:.3f} field-mm"
            )
        return None

    def record_irrigation_use(self, water_mm_field_equivalent: float) -> dict[str, Any]:
        # Keep accounting precision between operations. Rounding every entry
        # accumulates errors larger than check_irrigation_quota's tolerance,
        # rejecting a split application that fits the same total allowance.
        self._management_regime.irrigation_used_mm_total += float(water_mm_field_equivalent)
        self.is_state_modified = True
        return self._management_regime.to_dict()

    def consume_fertilizer(self, kg: float) -> bool:
        """Deduct fertilizer from warehouse. Returns False if insufficient."""
        if type(kg) not in (int, float) or not math.isfinite(kg) or kg <= 0:
            return False
        if self.shared_warehouse is not None:
            if self.check_fertilizer_use(kg) is not None or not self.shared_warehouse.consume_fertilizer(kg):
                return False
            self.record_fertilizer_use(kg)
            return True
        if (
            self._management_regime.fertilizer_quota_kg is not None
            and self._management_regime.fertilizer_used_kg + float(kg)
            > self._management_regime.fertilizer_quota_kg + 1e-9
        ):
            return False
        if self._inventory.fertilizer_kg < kg:
            return False
        self._inventory.fertilizer_kg -= kg
        self.record_fertilizer_use(kg)
        self.is_state_modified = True
        return True

    def withdraw_fertilizer(self, kg: float) -> bool:
        """Move stock to a machine without charging a field application quota."""
        if type(kg) not in (int, float) or not math.isfinite(kg) or kg <= 0:
            return False
        if self.shared_warehouse is not None:
            return self.shared_warehouse.consume_fertilizer(kg)
        if self._inventory.fertilizer_kg < kg:
            return False
        self._inventory.fertilizer_kg -= kg
        self.is_state_modified = True
        return True

    def consume_fuel(self, liters: float) -> bool:
        """Deduct fuel from warehouse. Returns False if insufficient."""
        if type(liters) not in (int, float) or not math.isfinite(liters) or liters <= 0:
            return False
        if self.shared_warehouse is not None:
            return self.shared_warehouse.consume_fuel(liters)
        if self._inventory.fuel_liters < liters:
            return False
        self._inventory.fuel_liters -= liters
        self.is_state_modified = True
        return True

    def add_grain_to_inventory(self, kg: float) -> None:
        """Deposit grain into warehouse inventory (called by tractor.unload_grain)."""
        self._inventory.harvest_grain_kg = round(
            self._inventory.harvest_grain_kg + float(kg), 2
        )
        if kg > 0:
            self._inventory.grain_dried = False
        self._trailer_grain_ridge_ids.extend(self._pending_bin_grain_ridge_ids)
        self._trailer_grain_moistures_pct.extend(self._pending_bin_grain_moistures_pct)
        self._pending_bin_grain_ridge_ids = []
        self._pending_bin_grain_moistures_pct = []
        self.is_state_modified = True

    def record_grain_bin_moisture(self, ridge_ids: list[int]) -> None:
        """Record moisture for the just-harvested combine-bin batch."""
        moistures: list[float] = []
        recorded_ridge_ids: list[int] = []
        for ridge_id in ridge_ids:
            if not 0 <= ridge_id < self.num_ridges:
                continue
            moisture = self._ridge_harvest_moisture_pct(ridge_id)
            if moisture is not None:
                recorded_ridge_ids.append(ridge_id)
                moistures.append(moisture)
        self._pending_bin_grain_ridge_ids.extend(recorded_ridge_ids)
        self._pending_bin_grain_moistures_pct.extend(moistures)
        self.is_state_modified = True

    def _ridge_harvest_moisture_pct(self, ridge_id: int) -> float | None:
        if self.physics_active:
            state = self.physics.yield_recovery.states.get(ridge_id)
            if state is not None and state.grain_moisture_frac is not None:
                return float(state.grain_moisture_frac) * 100.0
        ridge = self._ridges[ridge_id]
        self._refresh_ridge_dynamics(ridge)
        if ridge.grain_moisture_pct > 0.0:
            return float(ridge.grain_moisture_pct)
        return None

    def _apply_irrigation_effect(self, ridge_id: int, add_vwc: float) -> None:
        ridge = self._ridges[ridge_id]
        ridge.soil_vwc = min(0.45, ridge.soil_vwc + add_vwc)

    def _apply_due_irrigation(self) -> None:
        now_t = float(self.time_manager.time())
        for ridge_id in list(self._pending_irrigation):
            self._apply_due_irrigation_for_ridge(ridge_id, now_t)

    def _apply_due_irrigation_for_ridge(self, ridge_id: int, now_t: float) -> None:
        pending = self._pending_irrigation.get(ridge_id)
        if not pending:
            return

        remaining = []
        applied = False
        for item in pending:
            if float(item["effect_ready_at"]) <= now_t:
                self._apply_irrigation_effect(ridge_id, float(item["add_vwc"]))
                applied = True
            else:
                remaining.append(item)

        if remaining:
            self._pending_irrigation[ridge_id] = remaining
        else:
            del self._pending_irrigation[ridge_id]

        if applied:
            self.is_state_modified = True

    def planting_establishment(self, ridge_id: int) -> float:
        """Initial sowing quality, distinct from the current living stand."""
        if self._legacy_calendar is not None:
            return self._legacy_calendar.planting_establishment(self._ridges[ridge_id])
        return 1.0

    def crop_capabilities(self) -> dict[str, Any]:
        """Publish the actual operation rules and their units for this field."""
        definition = self.crop_definition
        return json.loads(json.dumps({
            "crop_id": self.crop_id, "cultivar_id": self.cultivar_id,
            "allowed_seed_types": list(definition.seed_types),
            "geometry": self.field_geometry.to_dict(),
            "planting": asdict(definition.planting_rules),
            "replanting": asdict(definition.replanting_rules or definition.planting_rules),
            "harvest": asdict(definition.harvest_rules),
            "postharvest": self._postharvest_market.to_dict(),
            "nutrition": {
                "nutrient_index": "dimensionless availability proxy, not a soil N/P/K measurement",
                "fertilizer_kg": "fertilizer product mass; elemental composition is unspecified",
                "scope": ("native PCSE CNB nitrogen balance; nutrient_index remains a derived proxy"
                          if self.native_crop_profile is not None else
                          "no explicit N/P/K mass balance or mechanistic nitrogen fixation"),
                "biotic_status": "not_simulated" if self.is_native_maize else "external_pressure_model",
            },
            "model_scope": "reduced simulation; cultivar parameters are not field-calibrated",
        }, allow_nan=False))

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_crop_capabilities(self) -> dict[str, Any]:
        """Read this field's crop, permitted seed, geometry and operation rules.

        Rules include seed-specific temperature limits, planting depth, VWC,
        supported replant modes, mature stages and required implements. They
        are the same typed rules used by tools and execution. Crop needs do
        not imply that a device owns the required implement. Nutrition metadata
        distinguishes the availability proxy from measured N/P/K and fertilizer
        product mass from elemental nutrient mass.
        """
        return self.crop_capabilities()

    def record_planting_metadata(
        self, ridge_id: int, seed_type: str, spacing_cm: float, seed_count: int,
    ) -> None:
        """Record the completed operation; living state is projected by physics."""
        ridge = self._ridges[ridge_id]
        ridge.seed_type = seed_type
        ridge.seed_spacing_cm = spacing_cm
        ridge.seeds_planted = seed_count
        ridge.planted_at_sim_time = float(self.time_manager.time())
        self.is_state_modified = True

    def _crop_configuration(self) -> dict[str, Any]:
        return {"schema_version": 2, "crop_id": self.crop_id, "explicit_crop_id": self._explicit_crop_id,
                "cultivar_id": self.cultivar_id, "geometry": self.field_geometry.to_dict(),
                "timezone": str(self.simulation_timezone), "legacy_calendar": self._legacy_calendar is not None}
