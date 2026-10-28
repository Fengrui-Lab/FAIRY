"""
Shared tractor business operations with an explicit farm context.

All operations are synchronous: they complete immediately, advance the
simulation clock by the real-world duration of the task, and consume
resources from the tractor's own onboard tanks/hoppers.

Onboard capacity:
  Fuel tank:           100 L (full = 100%)
  Pesticide tank:      800 L max
  Fertilizer spreader: 500 kg max
  Seed hopper:          max 300000 plants

Resources must be loaded from the farm warehouse before use:
  load_seeds(), load_fertilizer(), refill_pesticide_tank(), refuel()
"""

from __future__ import annotations

import uuid
import math
from math import isfinite
from fairy.physics.biotic_pressure_engine import TreatmentType, chemical_dose_efficacy
from typing import Any, TYPE_CHECKING

from fairy.apps.farm_world.equipment import TractorEquipment
from fairy.apps.farm_world.operation_plans import PlantingPlan
from fairy.crops.rules import PlantingRules
from fairy.crops.runtime import PlantingEvent

from fairy.apps.farm_world.farm_world_app import (
    FIELD_LENGTH_M,
    FIELD_WIDTH_M,
    GRAIN_KG_PER_RIDGE,
    PESTICIDE_L_PER_RIDGE,
    FarmWorldApp,
    plants_per_ridge_from_spacing,
)
from fairy.apps.farm_world.crop_profiles import official_seed_backend_error
from fairy.apps.farm_world.models import (
    GrowthStage,
    RidgeState,
    SeedType,
)
from fairy.apps.farm_world.weather_app import WeatherApp, _MAX_VWC_TRAFFIC


def split_pass(
    start_ridge: int, end_ridge: int, max_width: int
) -> list[tuple[int, int]]:
    """Split an inclusive ridge range into passes of at most ``max_width``.

    Use in scenario oracles to pre-decompose ridge-window calls that would
    otherwise exceed a tool's per-pass limit (4 for replant_seeds/harvest/
    unload, 10 for spray_pesticide/apply_fungicide/incorporate_residue).

    Example::

        for s, e in split_pass(34, 46, 10):
            tractor.apply_fungicide(s, e, liters_per_ridge=5.0)
    """
    if max_width <= 0:
        raise ValueError("max_width must be positive")
    if end_ridge < start_ridge:
        return []
    passes: list[tuple[int, int]] = []
    s = start_ridge
    while s <= end_ridge:
        e = min(s + max_width - 1, end_ridge)
        passes.append((s, e))
        s = e + 1
    return passes


# Tractor working speeds (m/s) by operation type
_SPEED_TILL_MS = 3000 / 3600  # rotary tilling: 3 km/h
_SPEED_FERTILIZE_MS = 6000 / 3600  # broadcast spreader: 6 km/h
_SPEED_RIDGE_MS = 4000 / 3600  # ridge former: 4 km/h
_SPEED_PLANT_MS = 5000 / 3600  # planter: 5 km/h
_SPEED_SPRAY_MS = 6000 / 3600  # spray boom: 6 km/h
_SPEED_HARVEST_MS = 4000 / 3600  # combine: 4 km/h

# Working widths (m) for full-field ops
_WIDTH_FERTILIZE_M = 6.0  # broadcast spreader

# Levelling attachment working widths (m) [PDF-p4]
_ATTACH_WIDTH_M = {
    "grader": 3.0,  # 平地机
    "furrower": 1.1,  # 开沟机
    "harvester": 4.4,  # 收割机
    "sprayer": 11.0,  # 喷药机
    "cultivator": 3.0,  # 中耕除草机
}
ATTACHMENTS = list(_ATTACH_WIDTH_M.keys())

# Headland turn time per pass (s)
_HEADLAND_TURN_S = 30

# Fuel consumption (L) per full-field prep operation
_FUEL_PER_PREP_OP = 8.0
# Fuel consumption (L) per single ridge-pass (planting / spraying / fertilizing)
_FUEL_PER_PASS = 2.0

# Fertilizer consumed for base_fertilize (kg) [PDF-p4]
_BASE_FERTILIZE_KG = 200.0

# Onboard tank/hopper capacities
_FUEL_TANK_MAX_L = 100.0
_PESTICIDE_TANK_MAX_L = 800.0
_FERTILIZER_SPREADER_MAX_KG = 500.0
_SEED_HOPPER_MAX_PLANTS = 300000
# Combine harvester grain bin capacity (kg). [PDF-p11, 1.2–1.5 t range]
# Holds roughly 2 four-ridge passes before it must be unloaded.
_GRAIN_BIN_MAX_KG = 2000.0
# Time to transfer full grain bin to trailer/warehouse (s). [PDF-p11, 5–10 min]
_GRAIN_UNLOAD_DURATION_S = 480

# Prep steps that must be completed before planting
_FIELD_PREP_SEQUENCE = ["level", "base_fertilize", "form_ridges"]


def _full_field_duration(world: FarmWorldApp, working_width_m: float, speed_ms: float) -> int:
    """Duration in seconds for a full-field operation."""
    # Preserve the historical headland width for the original farm layout.
    width = FIELD_WIDTH_M if (world.num_ridges == 64 and world.ridge_width_m == 1.1
                              and world.field_length_m == FIELD_LENGTH_M) else world.field_width_m
    passes = width / working_width_m
    total_dist = passes * world.field_length_m
    turn_time = passes * _HEADLAND_TURN_S
    return int(total_dist / speed_ms + turn_time)


def _pass_duration(world: FarmWorldApp, speed_ms: float) -> int:
    """Duration in seconds for a single ridge-length pass plus headland turn."""
    return int(world.field_length_m / speed_ms) + _HEADLAND_TURN_S



def _prep_area_scale(world: FarmWorldApp) -> float:
    """Resource calibration refers to the original 64-ridge field area."""
    return world.field_area_m2 / (FIELD_LENGTH_M * 64 * 1.1)

def _fuel_per_prep_op(world: FarmWorldApp) -> float:
    return _FUEL_PER_PREP_OP * _prep_area_scale(world)

def _base_fertilize_kg(world: FarmWorldApp) -> float:
    return _BASE_FERTILIZE_KG * _prep_area_scale(world)

def _fuel_per_pass(world: FarmWorldApp) -> float:
    return _FUEL_PER_PASS * world.field_length_m / FIELD_LENGTH_M

def harvest_grain_upper_bound_kg(world: FarmWorldApp, ridge_ids: list[int]) -> float:
    """Bound a mature pass before spending resources, using its actual crop mass.

    Native TWSO is dry matter; conversion to market moisture can increase its
    mass. Omit all field and machine losses for a conservative bin bound.
    Compatibility mode retains the configured crop's area-based yield bound.
    """
    if not world.physics_active:
        return len(ridge_ids) * world.grain_kg_per_ridge
    physics = world.physics
    if physics.crop_id == "maize" and physics.crop_backend is None:
        # The independent early-maize runtime already exposes a conservative
        # market-moisture bound; its parameters are not YieldRecoveryParameters.
        return (len(ridge_ids) * world.ridge_area_m2
                * physics.crop.max_recoverable_yield_g_m2 / 1000.0)
    biological = sum(max(
        physics.yield_recovery.states[rid].biological_yield_g_m2,
        physics.canopy.states[rid].yield_potential_g_m2,
    ) for rid in ridge_ids)
    if physics.yield_recovery.params.biological_yield_is_dry_matter:
        biological /= 1.0 - physics.yield_recovery.params.market_moisture_frac
    return biological * world.ridge_area_m2 / 1000.0


if TYPE_CHECKING:
    from fairy.apps.farm_world.farm_environment import FarmContext


class TractorOperations:
    """Device state and agricultural operations; callers supply the target farm."""

    def _tractor_available_implements(self) -> list[str]:
        """Only the implements explicitly owned by this physical tractor."""
        return list(self.equipment.implements)

    def _tractor_pass_duration(self, farm: FarmContext, speed_ms: float) -> int:
        return int(farm.world.field_length_m / speed_ms) + _HEADLAND_TURN_S

    def _tractor_full_field_duration(self, farm: FarmContext, working_width_m: float, speed_ms: float) -> int:
        return _full_field_duration(farm.world, working_width_m, speed_ms)

    def _planting_error(
        self, farm: FarmContext, ridges: list[RidgeState], depth_cm: float,
        spacing_cm: float, *, rules: PlantingRules | None = None,
    ) -> str | None:
        """Check the same rules used by capability discovery and tool schemas."""
        crop = farm.world.crop_definition
        crop_error = farm.world.validate_seed_for_crop(self.seed_type)
        if crop_error:
            return crop_error
        rules = rules or crop.planting_rules
        missing = [op for op in rules.required_preparation if op not in farm.world.completed_prep_ops]
        if missing:
            return f"Field preparation incomplete (missing: {missing})"
        if self.seed_type not in crop.seed_types:
            return f"Load a seed type permitted on this field: {list(crop.seed_types)}"
        error = rules.validate_parameters(depth_cm, spacing_cm) or rules.validate_implement(self._attached_implement)
        if error:
            return error
        if farm.world._explicit_crop_id is None:
            low, high = farm.world.crop_profile.seed_spacing_range_cm
            if not low <= float(spacing_cm) <= high:
                return f"seed_spacing_cm outside the supported {farm.world.crop_type} range ({low:g}–{high:g} cm)"
        density = (farm.world.plants_per_ridge_from_spacing(spacing_cm)
                   / farm.world.field_geometry.ridge_area_m2)
        avg_vwc = sum(r.soil_vwc for r in ridges) / len(ridges)
        avg_temp = sum(r.soil_temp_c for r in ridges) / len(ridges)
        return (rules.validate_conditions(self.seed_type, avg_temp, avg_vwc, density)
                or (farm.world.check_planting_window([r.ridge_id for r in ridges], self.seed_type)
                    if rules.respect_scenario_window else None))

    def _initialize_tractor_state(self, equipment: TractorEquipment | None = None) -> None:
        """Initialize the one physical tractor; farm preparation lives on the farm."""
        self.equipment = equipment or getattr(self, "equipment", TractorEquipment())
        self.seed_type: str | None = None
        self._fuel_tank_l = _FUEL_TANK_MAX_L
        self._pesticide_tank_l = 0.0
        self._fungicide_tank_l = 0.0
        self._fertilizer_spreader_kg = 0.0
        self._seed_hopper = 0
        self._grain_bin_kg = 0.0
        self._operation_log: list[dict[str, Any]] = []
        self._attached_implement: str | None = None
        self.source_farm_id: str | None = None
        self.grain_origin_farm_id: str | None = None

    def _tractor_device_state(self) -> dict[str, Any]:
        """Serialize equipment state without copying any farm state into the device."""
        return {
            "app_name": self.name,
            "fuel_tank_l": self._fuel_tank_l,
            "pesticide_tank_l": self._pesticide_tank_l,
            "fungicide_tank_l": self._fungicide_tank_l,
            "fertilizer_spreader_kg": self._fertilizer_spreader_kg,
            "seed_type": self.seed_type,
            "seed_hopper": self._seed_hopper,
            "grain_bin_kg": self._grain_bin_kg,
            "grain_bin_max_kg": _GRAIN_BIN_MAX_KG,
            "attached_implement": self._attached_implement,
            "available_implements": self._tractor_available_implements(),
            "operation_log": [dict(entry) for entry in self._operation_log],
            "source_farm_id": self.source_farm_id,
            "grain_origin_farm_id": self.grain_origin_farm_id,
        }

    def _load_tractor_device_state(self, state: dict[str, Any]) -> None:
        self._fuel_tank_l = float(state.get("fuel_tank_l", _FUEL_TANK_MAX_L))
        self._pesticide_tank_l = float(state.get("pesticide_tank_l", 0.0))
        self._fungicide_tank_l = float(state.get("fungicide_tank_l", 0.0))
        self._fertilizer_spreader_kg = float(state.get("fertilizer_spreader_kg", 0.0))
        self.seed_type = state.get("seed_type")
        self._seed_hopper = int(state.get("seed_hopper", 0))
        self._grain_bin_kg = float(state.get("grain_bin_kg", 0.0))
        self._attached_implement = state.get("attached_implement")
        self._operation_log = [dict(entry) for entry in state.get("operation_log", [])]
        self.source_farm_id = state.get("source_farm_id")
        self.grain_origin_farm_id = state.get("grain_origin_farm_id")

    def _operate_attach_implement(self, implement: str) -> dict[str, Any]:
        """
        Mount an implement onto the tractor.

        Args:
            implement: Name of the implement to attach.
        """
        if implement not in self._tractor_available_implements():
            return {"error": f"Unknown implement '{implement}'"}
        if (
            self._attached_implement is not None
            and self._attached_implement != implement
        ):
            return {"error": f"Already have '{self._attached_implement}' attached."}
        self._attached_implement = implement
        self.is_state_modified = True
        return {"status": "ok", "attached_implement": implement}

    def _operate_detach_implement(self) -> dict[str, Any]:
        """
        Remove the currently mounted implement from the tractor.
        """
        if self._attached_implement is None:
            return {"error": "No implement is currently attached"}
        removed = self._attached_implement
        self._attached_implement = None
        self.is_state_modified = True
        return {"status": "ok", "detached": removed}

    def _operate_refuel(self, farm: FarmContext, liters: float) -> dict[str, Any]:
        """
        Transfer fuel from the farm warehouse to the tractor fuel tank.

        Args:
            liters: Amount to transfer .
        """
        liters = float(liters)
        if not isfinite(liters) or liters <= 0:
            return {"error": "liters must be positive"}
        space = _FUEL_TANK_MAX_L - self._fuel_tank_l
        if space <= 0:
            return {"msg": "Fuel tank is already full"}
        to_transfer = min(liters, space)
        if not farm.world.consume_fuel(to_transfer):
            return {"error": "Insufficient fuel in warehouse"}
        self._fuel_tank_l = self._fuel_tank_l + to_transfer
        self.is_state_modified = True
        return {"status": "ok", "fuel_tank_l": self._fuel_tank_l}

    def _operate_refill_pesticide_tank(
        self,
        farm: FarmContext,
        liters: float,
    ) -> dict[str, Any]:
        """
        Transfer pesticide from the farm warehouse to the tractor spray tank.

        Args:
            liters: Amount to transfer
        """
        liters = float(liters)
        if not isfinite(liters) or liters <= 0:
            return {"error": "liters must be positive"}
        space = _PESTICIDE_TANK_MAX_L - self._pesticide_tank_l
        if space <= 0:
            return {"msg": "Pesticide tank is already full"}
        to_transfer = min(liters, space)
        if not farm.world.consume_pesticide(to_transfer):
            return {"error": "Insufficient pesticide in warehouse"}
        self._pesticide_tank_l = self._pesticide_tank_l + to_transfer
        self.is_state_modified = True
        return {"status": "ok", "pesticide_tank_l": self._pesticide_tank_l}

    def _operate_load_fertilizer(self, farm: FarmContext, kg: float) -> dict[str, Any]:
        """
        Transfer fertilizer from the farm warehouse to the tractor spreader.
        Args:
            kg: Amount to transfer.
        """
        kg = float(kg)
        if not isfinite(kg) or kg <= 0:
            return {"error": "kg must be positive"}
        space = _FERTILIZER_SPREADER_MAX_KG - self._fertilizer_spreader_kg
        if space <= 0:
            return {"msg": "Fertilizer spreader is already full"}
        to_transfer = min(kg, space)
        if not farm.world.withdraw_fertilizer(to_transfer):
            return {"error": "Insufficient fertilizer in warehouse"}
        self._fertilizer_spreader_kg = self._fertilizer_spreader_kg + to_transfer
        self.is_state_modified = True
        return {
            "status": "ok",
            "fertilizer_spreader_kg": self._fertilizer_spreader_kg,
        }

    def _operate_load_seeds(
        self,
        farm: FarmContext,
        seed_type: str,
        count: int,
    ) -> dict[str, Any]:
        """
        Transfer seeds from the farm warehouse to the tractor seed hopper.
        Hopper holds up to 300000 plants per seed type; excess is rejected.

        Args:
            seed_type: One of STANDARD, EARLY_COLD, HIGH_DENSITY,
                    STRESS_TOLERANT, HEIHE43, HEIHE50, HEINONG60,
                    HEINONG84, HEIKE71.
            count:     Number of plants to load (must be positive).
        """
        crop_error = farm.world.validate_seed_for_crop(seed_type)
        if crop_error:
            return {"error": crop_error}
        allowed_seed_types = set(farm.world.crop_definition.seed_types)
        if seed_type not in allowed_seed_types:
            return {"error": f"Unknown seed_type '{seed_type}'"}
        if self._seed_hopper > 0 and self.seed_type != seed_type:
            return {"error": "Seed hopper contains another seed type; empty or return it first"}
        count = int(count)
        if count <= 0:
            return {"error": "count must be positive"}
        current = self._seed_hopper
        space = _SEED_HOPPER_MAX_PLANTS - current
        if space <= 0:
            return {"msg": f"Seed hopper already full for {seed_type}"}
        to_transfer = min(count, space)
        if not farm.world.consume_seeds(seed_type, to_transfer):
            return {
                "error": f"Insufficient {seed_type} seeds in warehouse: need {to_transfer}"
            }
        self.seed_type = seed_type
        self._seed_hopper = current + to_transfer
        self.is_state_modified = True
        return {
            "status": "ok",
            "seed_hopper": self._seed_hopper,
            "seed_type": seed_type,
        }

    def _operate_get_status(self) -> dict[str, Any]:
        """
        Return tractor resource levels, implement status, and available implements.
        """
        return {
            "source_farm_id": self.source_farm_id,
            "grain_origin_farm_id": self.grain_origin_farm_id,
            "fungicide_tank_l": self._fungicide_tank_l,
            "fuel_tank_l": self._fuel_tank_l,
            "fertilizer_spreader_kg": self._fertilizer_spreader_kg,
            "pesticide_tank_l": self._pesticide_tank_l,
            "seed_type": self.seed_type,
            "seed_hopper": self._seed_hopper,
            "grain_bin_kg": self._grain_bin_kg,
            "grain_bin_max_kg": _GRAIN_BIN_MAX_KG,
            "available_implements": self._tractor_available_implements(),
            "attached_implement": self._attached_implement,
        }

    def _tractor_balance_after_use(self, farm: FarmContext, balance: float, used: float) -> float:
        # Accounting retains precision; rounding is for public presentation only.
        return max(0.0, float(balance) - float(used))

    def _operate_level(self, farm: FarmContext) -> dict[str, Any]:
        """
        Level and till the full field surface using the attached implement.
        """
        if self._attached_implement is None:
            return {"error": "No implement attached."}
        if self._attached_implement != "grader":
            return {
                "error": f"Attached implement '{self._attached_implement}' is not suitable for levelling"
            }
        traffic_error = self._tractor_trafficability_error(farm, "tractor operation")
        if traffic_error:
            return {"error": traffic_error}
        if self._fuel_tank_l < _fuel_per_prep_op(farm.world):
            return {"error": f"Insufficient fuel: need {_fuel_per_prep_op(farm.world)} L"}

        implement = self._attached_implement
        width_m = _ATTACH_WIDTH_M[implement]
        duration = _full_field_duration(farm.world, width_m, _SPEED_TILL_MS)
        self._fuel_tank_l = self._fuel_tank_l - _fuel_per_prep_op(farm.world)
        farm.advance_time(duration)
        farm.world.completed_prep_ops.append("level")
        self._operation_log.append(
            {
                "farm_id": farm.farm_id,
                "op_id": str(uuid.uuid4())[:8],
                "operation": "level",
                "implement": implement,
                "working_width_m": width_m,
                "duration_s": duration,
            }
        )
        self.is_state_modified = True
        return {
            "status": "ok",
            "implement": implement,
            "working_width_m": width_m,
            "duration_minutes": round(duration / 60, 1),
            "fuel_tank_l": self._fuel_tank_l,
        }

    def _operate_base_fertilize(self, farm: FarmContext, total_kg: float | None = None) -> dict[str, Any]:
        """
        Apply base fertilizer across the full field using the tractor spreader.
        """

        amount_kg = _base_fertilize_kg(farm.world) if total_kg is None else float(total_kg)
        if not isfinite(amount_kg) or amount_kg <= 0:
            return {"error": "total_kg must be finite and positive"}
        quota_error = farm.world.check_fertilizer_use(amount_kg)
        if quota_error:
            return {"error": quota_error}
        if self._fertilizer_spreader_kg < amount_kg:
            return {
                "error": f"Insufficient fertilizer in spreader: need {amount_kg} kg, have {self._fertilizer_spreader_kg:.1f} kg"
            }
        if self._fuel_tank_l < _fuel_per_prep_op(farm.world):
            return {
                "error": f"Insufficient fuel: need {_fuel_per_prep_op(farm.world)} L, have {self._fuel_tank_l:.1f} L"
            }
        traffic_error = self._tractor_trafficability_error(farm, "tractor operation")
        if traffic_error:
            return {"error": traffic_error}

        self._fertilizer_spreader_kg = self._fertilizer_spreader_kg - amount_kg
        farm.world.record_fertilizer_use(amount_kg)
        self._fuel_tank_l = self._fuel_tank_l - _fuel_per_prep_op(farm.world)
        duration = _full_field_duration(farm.world, _WIDTH_FERTILIZE_M, _SPEED_FERTILIZE_MS)
        farm.advance_time(duration)
        farm.world.completed_prep_ops.append("base_fertilize")

        if farm.world.physics_active:
            # Pre-planting broadcast → BASE_FERTILIZER action across all
            # ridges; sets nutrient_index baseline used by canopy/biomass.
            self._tractor_register_base_fertilizer_with_physics(
                farm,
                ridge_ids=list(range(farm.world.num_ridges)),
                total_kg=amount_kg,
            )

        self._operation_log.append(
            {
                "farm_id": farm.farm_id,
                "op_id": str(uuid.uuid4())[:8],
                "operation": "base_fertilize",
                "fertilizer_used_kg": amount_kg,
                "duration_s": duration,
            }
        )
        self.is_state_modified = True
        return {
            "status": "ok",
            "fertilizer_used_kg": amount_kg,
            "duration_minutes": round(duration / 60, 1),
            "fuel_tank_l": self._fuel_tank_l,
        }

    def _operate_form_ridges(
        self,
        farm: FarmContext,
        ridge_width_m: float,
    ) -> dict[str, Any]:
        """
        Form ridge rows across the full field using a tractor-mounted ridge former.

        Args:
            ridge_width_m: Width of each ridge in metres.
        """
        # Ordinary preparation cannot terminate a living crop. Check both the
        # public bootstrap state and authoritative dynamics before any charge.
        live = any(r.planted for r in farm.world._ridges)
        if farm.world.physics_active:
            physics = farm.world.physics
            live = live or any(physics.crop.project(rid, state).current_planted
                               for rid, state in physics.management.states.items())
        if live:
            return {"error": "Cannot form ridges while a crop is planted; terminate the crop explicitly first"}
        if (self.equipment.ridging_implement is not None
                and self._attached_implement != self.equipment.ridging_implement):
            return {"error": f"Ridging requires attached implement '{self.equipment.ridging_implement}'"}
        if self._fuel_tank_l < _fuel_per_prep_op(farm.world):
            return {
                "error": f"Insufficient fuel: need {_fuel_per_prep_op(farm.world)} L, have {self._fuel_tank_l:.1f} L"
            }
        ridge_width_m = float(ridge_width_m)
        if not isfinite(ridge_width_m) or ridge_width_m <= 0.0:
            return {"error": "ridge_width_m must be positive"}
        if ridge_width_m != farm.world.field_geometry.ridge_width_m:
            return {"error": f"Field ridge width is configured as {farm.world.field_geometry.ridge_width_m:g} m"}
        # Each pass forms 4 ridges side by side
        ridges_per_pass = 4
        working_width_m = ridges_per_pass * ridge_width_m
        traffic_error = self._tractor_trafficability_error(farm, "tractor operation")
        if traffic_error:
            return {"error": traffic_error}

        duration = self._tractor_full_field_duration(farm, working_width_m, _SPEED_RIDGE_MS)
        self._fuel_tank_l = self._tractor_balance_after_use(
            farm, self._fuel_tank_l, _fuel_per_prep_op(farm.world)
        )
        farm.advance_time(duration)

        # Preserve pre-conditioned soil state (VWC, temp, pressure baselines).
        # FarmWorld has 64 fixed logical ridge IDs (0-63); ridge_width_m is an
        # operating setting, not permission to resize the indexed state/engine maps.
        farm.world.ridge_width_m = ridge_width_m
        for i, r in enumerate(farm.world._ridges):
            r.ridge_id = i
            r.seed_type = None
            r.seed_spacing_cm = None
            r.seeds_planted = 0
            r.days_since_planted = 0
            r.ndvi = -1.0
            r.canopy_temp_c = -1.0
            r.grain_moisture_pct = 0.0
            r.planted_at_sim_time = None
            r.pest_pressure = r.pest_pressure_base
            r.disease_pressure = r.disease_pressure_base

        farm.world.completed_prep_ops.append("form_ridges")
        farm.world._refresh_auto_season_phase(field_prepared=True)
        self._operation_log.append(
            {
                "farm_id": farm.farm_id,
                "op_id": str(uuid.uuid4())[:8],
                "operation": "form_ridges",
                "ridge_width_m": ridge_width_m,
                "num_ridges": farm.world.num_ridges,
                "duration_s": duration,
            }
        )
        self.is_state_modified = True
        return {
            "status": "ok",
            "ridge_width_m": ridge_width_m,
            "num_ridges": farm.world.num_ridges,
            "duration_minutes": round(duration / 60, 1),
            "fuel_tank_l": round(self._fuel_tank_l, 1),
        }

    def _operate_apply_fertilizer(
        self,
        farm: FarmContext,
        start_ridge: int,
        end_ridge: int,
        kg_per_ridge: float,
    ) -> dict[str, Any]:
        """
        Apply fertilizer across a contiguous block of ridges using the tractor spreader
        (up to 10 ridges per pass).

        Args:
            start_ridge:   First ridge to fertilize.
            end_ridge:     Last ridge to fertilize (max 10-ridge span).
            kg_per_ridge:  Fertilizer amount per ridge in kilograms (must be positive).
        """
        err = self._tractor_validate_ridge_window(farm, start_ridge, end_ridge, max_width=10)
        if err:
            return {"error": err}
        if not isfinite(float(kg_per_ridge)) or float(kg_per_ridge) <= 0:
            return {"error": "kg_per_ridge must be positive"}
        traffic_error = self._tractor_trafficability_error(farm, "tractor fertilizing")
        if traffic_error:
            return {"error": traffic_error}

        ridge_count = end_ridge - start_ridge + 1
        required_kg = ridge_count * float(kg_per_ridge)
        quota_error = farm.world.check_fertilizer_use(required_kg)
        if quota_error:
            return {"error": quota_error}
        # Relative-only tolerance accepts a last-pass subtraction tail, not missing stock.
        if not (self._fertilizer_spreader_kg >= required_kg
                or math.isclose(self._fertilizer_spreader_kg, required_kg, rel_tol=1e-12, abs_tol=0.0)):
            return {
                "error": f"Insufficient fertilizer in spreader: need {required_kg:.1f} kg, have {self._fertilizer_spreader_kg:.1f} kg"
            }
        if self._fuel_tank_l < _fuel_per_pass(farm.world):
            return {
                "error": f"Insufficient fuel: need {_fuel_per_pass(farm.world)} L, have {self._fuel_tank_l:.1f} L"
            }

        self._fertilizer_spreader_kg = max(0.0, self._fertilizer_spreader_kg - required_kg)
        farm.world.record_fertilizer_use(required_kg)
        self._fuel_tank_l = self._fuel_tank_l - _fuel_per_pass(farm.world)
        duration = _pass_duration(farm.world, _SPEED_FERTILIZE_MS)
        farm.advance_time(duration)

        if farm.world.physics_active:
            # Physics path: queue a FERTIGATION action; nutrient_index rises,
            # nutrient_stress eases, and canopy/biomass recovers over the
            # next several daily ticks. NDVI does NOT jump immediately
            # (integration guide §"It should not: immediately set NDVI to
            # normal, immediately reset yield potential").
            self._tractor_register_fertilizer_with_physics(
                farm,
                ridge_ids=list(range(start_ridge, end_ridge + 1)),
                kg_per_ridge=float(kg_per_ridge),
                method="targeted_spreader",
            )
        else:
            # Legacy path: direct yield_potential bump. Kept for backward
            # compatibility in compat-mode runs.
            for ridge_id in range(start_ridge, end_ridge + 1):
                ridge = farm.world.get_ridge(ridge_id)
                ridge.yield_potential = min(
                    1.0,
                    round(
                        ridge.yield_potential + min(0.15, float(kg_per_ridge) * 0.005),
                        3,
                    ),
                )
            farm.world.is_state_modified = True

        op_id = str(uuid.uuid4())[:8]
        self._operation_log.append(
            {
                "farm_id": farm.farm_id,
                "op_id": op_id,
                "operation": "apply_fertilizer",
                "ridge_ids": list(range(start_ridge, end_ridge + 1)),
                "fertilizer_used_kg": required_kg,
                "duration_s": duration,
            }
        )
        self.is_state_modified = True
        return {
            "status": "ok",
            "fertilized_ridges": list(range(start_ridge, end_ridge + 1)),
            "fertilizer_used_kg": required_kg,
        }

    def _prepare_planting_plan(
        self, farm: FarmContext, ridges: list[RidgeState], depth_cm: float,
        spacing_cm: float, *, replace_existing: bool = False,
    ) -> PlantingPlan:
        """Preflight the native crop, resources and future completion timestamp."""
        from fairy.apps.farm_world.crop_dynamics import create_crop_dynamics
        physics = farm.world._physics
        duration = self._tractor_pass_duration(farm, _SPEED_PLANT_MS)
        count = farm.world.plants_per_ridge_from_spacing(spacing_cm)
        event = PlantingEvent(
            ridge_ids=tuple(r.ridge_id for r in ridges),
            planting_date=farm.world.simulation_date(farm.world.time_manager.time() + duration),
            seed_type=self.seed_type, depth_cm=depth_cm,
            stand_fraction_by_ridge={r.ridge_id: farm.world.planting_establishment(r.ridge_id) for r in ridges},
            density_by_ridge={r.ridge_id: count / farm.world.field_geometry.ridge_area_m2 for r in ridges},
            latitude_deg=physics.latitude_deg if physics is not None else 45.7,
            replace_existing=replace_existing,
        )
        plan = PlantingPlan(event, spacing_cm, count, duration, _fuel_per_pass(farm.world))
        error = self._planting_resource_error(plan)
        if error:
            raise ValueError(error)
        # Validation must not install a bundle just because a caller tried a
        # rejected action. The real bundle is created only when work commits.
        crop = (physics.crop if physics is not None
                else create_crop_dynamics(farm.world._explicit_crop_id, farm.world.num_ridges,
                                          crop_type=farm.world.crop_type))
        crop.validate_planting(event)
        return plan

    def _planting_resource_error(self, plan: PlantingPlan) -> str | None:
        if self._seed_hopper < plan.total_seeds:
            return f"Insufficient {self.seed_type} seeds in hopper: need {plan.total_seeds}, have {self._seed_hopper}"
        if self._fuel_tank_l < plan.fuel_liters:
            return f"Insufficient fuel: need {plan.fuel_liters} L, have {self._fuel_tank_l:.1f} L"
        return None

    def _operate_plant_seeds(
        self, farm: FarmContext, start_ridge: int, end_ridge: int,
        depth_cm: float, seed_spacing_cm: float,
    ) -> dict[str, Any]:
        """Validate one complete planting plan, then execute it exactly once."""
        native_seed_error = official_seed_backend_error(self.seed_type, farm.world._physics)
        if native_seed_error:
            return {"error": native_seed_error}
        error = self._tractor_validate_ridge_window(
            farm, start_ridge, end_ridge, max_width=self.equipment.planting_max_ridges_per_pass,
        )
        if error:
            return {"error": error}
        ridges = [farm.world.get_ridge(r) for r in range(start_ridge, end_ridge + 1)]
        if any(r.planted for r in ridges):
            return {"error": "One or more ridges are already planted"}
        error = self._planting_error(farm, ridges, depth_cm, seed_spacing_cm)
        if error:
            return {"error": error}
        try:
            plan = self._prepare_planting_plan(farm, ridges, depth_cm, seed_spacing_cm)
        except ValueError as exc:
            return {"error": str(exc)}
        farm.advance_time(plan.duration_s)
        self._tractor_register_planting_with_physics(
            farm, ridges, depth_cm, seed_spacing_cm, event=plan.event,
        )
        self._seed_hopper -= plan.total_seeds
        self._fuel_tank_l = self._tractor_balance_after_use(farm, self._fuel_tank_l, plan.fuel_liters)
        for ridge in ridges:
            farm.world.record_planting_metadata(ridge.ridge_id, self.seed_type, seed_spacing_cm, plan.seeds_per_ridge)
        self._operation_log.append({
            "farm_id": farm.farm_id, "op_id": str(uuid.uuid4())[:8], "operation": "plant_seeds",
            "ridge_ids": list(plan.event.ridge_ids), "depth_cm": depth_cm,
            "seed_spacing_cm": seed_spacing_cm, "seeds_per_ridge": plan.seeds_per_ridge,
            "seeds_used": plan.total_seeds, "duration_s": plan.duration_s,
        })
        self.is_state_modified = True
        return {
            "status": "ok", "planted_ridges": list(plan.event.ridge_ids), "depth_cm": depth_cm,
            "seed_spacing_cm": seed_spacing_cm, "seeds_per_ridge": plan.seeds_per_ridge,
            "seeds_used": plan.total_seeds,
        }

    def _operate_apply_pesticide(
        self,
        farm: FarmContext,
        start_ridge: int,
        end_ridge: int,
    ) -> dict[str, Any]:
        """
        Apply insecticide pesticide across a contiguous block of ridges using the tractor
        spray boom (up to 10 ridges per pass).

        Args:
            start_ridge: First ridge to spray (0-63).
            end_ridge:   Last ridge to spray (0-63, max 10-ridge span).
        """
        biotic_error = farm.world.validate_biotic_management()
        if biotic_error:
            return {"error": biotic_error}
        err = self._tractor_validate_ridge_window(farm, start_ridge, end_ridge, max_width=10)
        if err:
            return {"error": err}
        if not farm.weather.is_sprayable:
            return {
                "error": "Weather conditions do not allow spraying (rain or wind above spray limit)"
            }
        traffic_error = self._tractor_trafficability_error(farm, "tractor spraying")
        if traffic_error:
            return {"error": traffic_error}

        ridge_count = end_ridge - start_ridge + 1
        required_liters = ridge_count * PESTICIDE_L_PER_RIDGE
        regime_error = farm.world.check_chemical_application(
            "insecticide", required_liters
        )
        if regime_error:
            return {"error": regime_error}
        if self._pesticide_tank_l < required_liters:
            return {
                "error": f"Insufficient pesticide in tank: need {required_liters:.1f} L, have {self._pesticide_tank_l:.1f} L"
            }
        if self._fuel_tank_l < _fuel_per_pass(farm.world):
            return {
                "error": f"Insufficient fuel: need {_fuel_per_pass(farm.world)} L, have {self._fuel_tank_l:.1f} L"
            }

        self._pesticide_tank_l = self._pesticide_tank_l - required_liters
        self._fuel_tank_l = self._fuel_tank_l - _fuel_per_pass(farm.world)
        duration = _pass_duration(farm.world, _SPEED_SPRAY_MS)
        farm.advance_time(duration)
        for ridge_id in range(start_ridge, end_ridge + 1):
            farm.world.update_ridge_pesticide(ridge_id)

        # Physics integration: route the spray through the biotic + management
        # engines. Tool name and signature unchanged so the oracle alphabet
        # stays stable. Maps to INSECTICIDE per round-1+2 scope; fungicide /
        # herbicide channels ship in round 3 with new tool surface.
        self._tractor_register_spray_with_physics(
            farm,
            ridge_ids=list(range(start_ridge, end_ridge + 1)),
            method="boom",
            efficacy_multiplier=1.0,
        )
        regime_status = farm.world.record_chemical_application(
            "insecticide", required_liters
        )

        op_id = str(uuid.uuid4())[:8]
        self._operation_log.append(
            {
                "farm_id": farm.farm_id,
                "op_id": op_id,
                "operation": "apply_pesticide",
                "ridge_ids": list(range(start_ridge, end_ridge + 1)),
                "pesticide_used_liters": required_liters,
                "duration_s": duration,
            }
        )
        self.is_state_modified = True
        return {
            "status": "ok",
            "sprayed_ridges": list(range(start_ridge, end_ridge + 1)),
            "pesticide_used_liters": required_liters,
            "management_regime": regime_status,
        }

    def _operate_load_pesticide(
        self,
        farm: FarmContext,
        liters: float,
    ) -> dict[str, Any]:
        """
        Round-3 / round-4 alias for ``refill_pesticide_tank``.

        Args:
            liters: Amount of pesticide (insecticide) to transfer from
                    warehouse to the tractor's onboard pesticide tank.
        """
        liters = float(liters)
        if not isfinite(liters) or liters <= 0:
            return {"error": "liters must be positive"}
        space = _PESTICIDE_TANK_MAX_L - self._pesticide_tank_l
        if space <= 0:
            return {"msg": "Pesticide tank is already full"}
        to_transfer = min(liters, space)
        if not farm.world.consume_pesticide(to_transfer):
            return {"error": "Insufficient pesticide in warehouse"}
        self._pesticide_tank_l = self._pesticide_tank_l + to_transfer
        self.is_state_modified = True
        return {"status": "ok", "pesticide_tank_l": self._pesticide_tank_l}

    def _operate_spray_pesticide(
        self,
        farm: FarmContext,
        start_ridge: int,
        end_ridge: int,
        liters_per_ridge: float = PESTICIDE_L_PER_RIDGE,
    ) -> dict[str, Any]:
        """
        Apply (insecticide) pesticide across a contiguous block of ridges using
        the tractor spray boom (up to 10 ridges per pass).

        Routes through ``BioticPressureEngine.apply_treatment(INSECTICIDE)``
        and opens the management residual window. Spray weather constraints
        apply (no rain, wind below the spray limit). Round-3 alias for ``apply_pesticide``
        with configurable per-ridge dose; default matches the legacy
        hardcoded 8.0 L/ridge so existing scenarios stay calibrated.

        Args:
            start_ridge:      First ridge (0-63).
            end_ridge:        Last ridge (max 10-ridge span).
            liters_per_ridge: Insecticide application rate (>0).
        """
        biotic_error = farm.world.validate_biotic_management()
        if biotic_error:
            return {"error": biotic_error}
        err = self._tractor_validate_ridge_window(farm, start_ridge, end_ridge, max_width=10)
        if err:
            return {"error": err}
        if not isfinite(float(liters_per_ridge)) or float(liters_per_ridge) <= 0:
            return {"error": "liters_per_ridge must be positive"}
        if not farm.weather.is_sprayable:
            return {
                "error": "Weather conditions do not allow spraying (rain or wind above spray limit)"
            }
        traffic_error = self._tractor_trafficability_error(farm, "tractor spraying")
        if traffic_error:
            return {"error": traffic_error}

        ridge_count = end_ridge - start_ridge + 1
        required_liters = ridge_count * float(liters_per_ridge)
        regime_error = farm.world.check_chemical_application(
            "insecticide", required_liters
        )
        if regime_error:
            return {"error": regime_error}
        # Relative-only tolerance accepts subtraction roundoff, never an empty tank.
        if not (self._pesticide_tank_l >= required_liters
                or math.isclose(self._pesticide_tank_l, required_liters, rel_tol=1e-12, abs_tol=0.0)):
            return {
                "error": f"Insufficient pesticide in tank: need {required_liters:.1f} L, have {self._pesticide_tank_l:.1f} L"
            }
        if self._fuel_tank_l < _fuel_per_pass(farm.world):
            return {
                "error": f"Insufficient fuel: need {_fuel_per_pass(farm.world)} L, have {self._fuel_tank_l:.1f} L"
            }

        self._pesticide_tank_l = max(0.0, self._pesticide_tank_l - required_liters)
        self._fuel_tank_l = self._fuel_tank_l - _fuel_per_pass(farm.world)
        duration = _pass_duration(farm.world, _SPEED_SPRAY_MS)
        farm.advance_time(duration)
        for ridge_id in range(start_ridge, end_ridge + 1):
            farm.world.update_ridge_pesticide(ridge_id)

        self._tractor_register_spray_with_physics(

            farm,
            ridge_ids=list(range(start_ridge, end_ridge + 1)),
            method="boom",
            efficacy_multiplier=chemical_dose_efficacy(TreatmentType.INSECTICIDE, float(liters_per_ridge)),
        )
        regime_status = farm.world.record_chemical_application(
            "insecticide", required_liters
        )

        op_id = str(uuid.uuid4())[:8]
        self._operation_log.append(
            {
                "farm_id": farm.farm_id,
                "op_id": op_id,
                "operation": "spray_pesticide",
                "ridge_ids": list(range(start_ridge, end_ridge + 1)),
                "pesticide_used_liters": required_liters,
                "duration_s": duration,
            }
        )
        self.is_state_modified = True
        return {
            "status": "ok",
            "sprayed_ridges": list(range(start_ridge, end_ridge + 1)),
            "pesticide_used_liters": required_liters,
            "management_regime": regime_status,
        }

    def _operate_load_fungicide(
        self,
        farm: FarmContext,
        liters: float,
    ) -> dict[str, Any]:
        """
        Transfer fungicide from the farm warehouse to the tractor's fungicide tank.

        Fungicide is a separate chemical class from insecticide; the agent must
        load fungicide explicitly before calling apply_fungicide. The warehouse
        pesticide pool is shared (`pesticide_liters`).

        Args:
            liters: Amount to transfer.
        """
        liters = float(liters)
        if not isfinite(liters) or liters <= 0:
            return {"error": "liters must be positive"}
        space = _PESTICIDE_TANK_MAX_L - self._fungicide_tank_l
        if space <= 0:
            return {"msg": "Fungicide tank is already full"}
        to_transfer = min(liters, space)
        if not farm.world.consume_pesticide(to_transfer):
            return {"error": "Insufficient chemical in warehouse"}
        self._fungicide_tank_l = self._fungicide_tank_l + to_transfer
        self.is_state_modified = True
        return {"status": "ok", "fungicide_tank_l": self._fungicide_tank_l}

    def _operate_apply_fungicide(
        self,
        farm: FarmContext,
        start_ridge: int,
        end_ridge: int,
        liters_per_ridge: float,
    ) -> dict[str, Any]:
        """
        Apply fungicide across a contiguous block of ridges using the tractor
        spray boom (up to 10 ridges per pass).

        Routes through `BioticPressureEngine.apply_treatment(FUNGICIDE)` and
        opens a management-residual window for disease pressure. Spray weather
        constraints apply (no rain, wind below the spray limit).

        Args:
            start_ridge:      First ridge to spray (0-63).
            end_ridge:        Last ridge to spray (0-63, max 10-ridge span).
            liters_per_ridge: Fungicide application rate (>0).
        """
        biotic_error = farm.world.validate_biotic_management()
        if biotic_error:
            return {"error": biotic_error}
        err = self._tractor_validate_ridge_window(farm, start_ridge, end_ridge, max_width=10)
        if err:
            return {"error": err}
        if not isfinite(float(liters_per_ridge)) or float(liters_per_ridge) <= 0:
            return {"error": "liters_per_ridge must be positive"}
        if not farm.weather.is_sprayable:
            return {
                "error": "Weather conditions do not allow spraying (rain or wind above spray limit)"
            }
        traffic_error = self._tractor_trafficability_error(farm, "tractor spraying")
        if traffic_error:
            return {"error": traffic_error}

        ridge_count = end_ridge - start_ridge + 1
        required_liters = ridge_count * float(liters_per_ridge)
        regime_error = farm.world.check_chemical_application(
            "fungicide", required_liters
        )
        if regime_error:
            return {"error": regime_error}
        # Relative-only tolerance accepts subtraction roundoff, never an empty tank.
        if not (self._fungicide_tank_l >= required_liters
                or math.isclose(self._fungicide_tank_l, required_liters, rel_tol=1e-12, abs_tol=0.0)):
            return {
                "error": f"Insufficient fungicide in tank: need {required_liters:.1f} L, have {self._fungicide_tank_l:.1f} L"
            }
        if self._fuel_tank_l < _fuel_per_pass(farm.world):
            return {
                "error": f"Insufficient fuel: need {_fuel_per_pass(farm.world)} L, have {self._fuel_tank_l:.1f} L"
            }

        self._fungicide_tank_l = max(0.0, self._fungicide_tank_l - required_liters)
        self._fuel_tank_l = self._fuel_tank_l - _fuel_per_pass(farm.world)
        duration = _pass_duration(farm.world, _SPEED_SPRAY_MS)
        farm.advance_time(duration)

        # Physics integration: queue FUNGICIDE treatment + management residual.
        if farm.world.physics_active:
            self._tractor_register_fungicide_with_physics(
                farm,
                ridge_ids=list(range(start_ridge, end_ridge + 1)),
                liters_per_ridge=float(liters_per_ridge),
            )
        regime_status = farm.world.record_chemical_application(
            "fungicide", required_liters
        )

        op_id = str(uuid.uuid4())[:8]
        self._operation_log.append(
            {
                "farm_id": farm.farm_id,
                "op_id": op_id,
                "operation": "apply_fungicide",
                "ridge_ids": list(range(start_ridge, end_ridge + 1)),
                "fungicide_used_liters": required_liters,
                "duration_s": duration,
            }
        )
        self.is_state_modified = True
        return {
            "status": "ok",
            "sprayed_ridges": list(range(start_ridge, end_ridge + 1)),
            "fungicide_used_liters": required_liters,
            "management_regime": regime_status,
        }

    def _operate_apply_herbicide(
        self,
        farm: FarmContext,
        start_ridge: int,
        end_ridge: int,
        liters_per_ridge: float,
    ) -> dict[str, Any]:
        """
        Apply chemical weed control across a contiguous block of ridges.

        This is the herbicide path: it requires sprayable weather, trafficable
        soil, tank chemical, fuel, and management-regime permission. It queues a
        HERBICIDE treatment, so weed pressure receives both same-day knockdown
        and the chemical residual window.

        Args:
            start_ridge:      First ridge to treat (0-63).
            end_ridge:        Last ridge to treat (0-63, max 10-ridge span).
            liters_per_ridge: Herbicide application rate (>0).
        """
        biotic_error = farm.world.validate_biotic_management()
        if biotic_error:
            return {"error": biotic_error}
        err = self._tractor_validate_ridge_window(farm, start_ridge, end_ridge, max_width=10)
        if err:
            return {"error": err}
        if not isfinite(float(liters_per_ridge)) or float(liters_per_ridge) <= 0:
            return {"error": "liters_per_ridge must be positive"}
        if not farm.weather.is_sprayable:
            return {
                "error": "Weather conditions do not allow spraying (rain or wind above spray limit)"
            }
        traffic_error = self._tractor_trafficability_error(farm, "tractor spraying")
        if traffic_error:
            return {"error": traffic_error}

        ridge_count = end_ridge - start_ridge + 1
        required_liters = ridge_count * float(liters_per_ridge)
        regime_error = farm.world.check_chemical_application(
            "herbicide", required_liters
        )
        if regime_error:
            return {"error": regime_error}
        # Relative-only tolerance accepts subtraction roundoff, never an empty tank.
        if not (self._pesticide_tank_l >= required_liters
                or math.isclose(self._pesticide_tank_l, required_liters, rel_tol=1e-12, abs_tol=0.0)):
            return {
                "error": f"Insufficient chemical in tank: need {required_liters:.1f} L, have {self._pesticide_tank_l:.1f} L"
            }
        if self._fuel_tank_l < _fuel_per_pass(farm.world):
            return {
                "error": f"Insufficient fuel: need {_fuel_per_pass(farm.world)} L, have {self._fuel_tank_l:.1f} L"
            }

        self._pesticide_tank_l = max(0.0, self._pesticide_tank_l - required_liters)
        self._fuel_tank_l = self._fuel_tank_l - _fuel_per_pass(farm.world)
        duration = _pass_duration(farm.world, _SPEED_SPRAY_MS)
        farm.advance_time(duration)
        self._tractor_register_weed_control_with_physics(
            farm,
            ridge_ids=list(range(start_ridge, end_ridge + 1)),
            action_type="herbicide",
            method="boom",
            efficacy_multiplier=chemical_dose_efficacy(TreatmentType.HERBICIDE, float(liters_per_ridge)),
        )
        regime_status = farm.world.record_chemical_application(
            "herbicide", required_liters
        )
        self._operation_log.append(
            {
                "farm_id": farm.farm_id,
                "op_id": str(uuid.uuid4())[:8],
                "operation": "apply_herbicide",
                "ridge_ids": list(range(start_ridge, end_ridge + 1)),
                "herbicide_used_liters": required_liters,
                "duration_s": duration,
            }
        )
        self.is_state_modified = True
        return {
            "status": "ok",
            "treated_ridges": list(range(start_ridge, end_ridge + 1)),
            "herbicide_used_liters": required_liters,
            "management_regime": regime_status,
        }

    def _operate_mechanical_weed_control(
        self,
        farm: FarmContext,
        start_ridge: int,
        end_ridge: int,
    ) -> dict[str, Any]:
        """
        Cultivate a contiguous ridge block for mechanical weed control.

        This is the non-chemical weed-control path for organic/low-chemical
        scenarios. It requires trafficable soil, fuel, and machine-pass budget.
        It queues a MECHANICAL_WEED treatment: strong same-day weed knockdown,
        no herbicide residual, and no pesticide application count.

        Args:
            start_ridge: First ridge to cultivate (0-63).
            end_ridge:   Last ridge to cultivate (0-63, max 10-ridge span).
        """
        biotic_error = farm.world.validate_biotic_management()
        if biotic_error:
            return {"error": biotic_error}
        err = self._tractor_validate_ridge_window(farm, start_ridge, end_ridge, max_width=10)
        if err:
            return {"error": err}
        traffic_error = self._tractor_trafficability_error(farm, "mechanical weed control")
        if traffic_error:
            return {"error": traffic_error}
        pass_error = farm.world.check_machine_pass(1)
        if pass_error:
            return {"error": pass_error}
        ridge_count = end_ridge - start_ridge + 1
        ridge_cap_error = farm.world.check_mechanical_weed_ridge_cap(
            ridge_count
        )
        if ridge_cap_error:
            return {"error": ridge_cap_error}
        if self._fuel_tank_l < _fuel_per_pass(farm.world):
            return {
                "error": f"Insufficient fuel: need {_fuel_per_pass(farm.world)} L, have {self._fuel_tank_l:.1f} L"
            }

        self._fuel_tank_l = self._fuel_tank_l - _fuel_per_pass(farm.world)
        duration = _pass_duration(farm.world, _SPEED_TILL_MS)
        farm.advance_time(duration)
        self._tractor_register_weed_control_with_physics(
            farm,
            ridge_ids=list(range(start_ridge, end_ridge + 1)),
            action_type="mechanical_weed_control",
            method="cultivator",
            efficacy_multiplier=1.0,
        )
        farm.world.record_machine_pass(1)
        regime_status = farm.world.record_mechanical_weed_ridges(ridge_count)
        self._operation_log.append(
            {
                "farm_id": farm.farm_id,
                "op_id": str(uuid.uuid4())[:8],
                "operation": "mechanical_weed_control",
                "ridge_ids": list(range(start_ridge, end_ridge + 1)),
                "duration_s": duration,
            }
        )
        self.is_state_modified = True
        return {
            "status": "ok",
            "treated_ridges": list(range(start_ridge, end_ridge + 1)),
            "management_regime": regime_status,
        }

    def _operate_replant_seeds(
        self, farm: FarmContext, start_ridge: int, end_ridge: int,
        depth_cm: float, spacing_cm: float, full_replant: bool = False,
    ) -> dict[str, Any]:
        """Replant through the crop lifecycle, preserving established gap fills."""
        native_seed_error = official_seed_backend_error(self.seed_type, farm.world._physics)
        if native_seed_error:
            return {"error": native_seed_error}
        from fairy.apps.farm_world.farm_action_record import FarmActionRecord
        from dataclasses import replace
        error = self._tractor_validate_ridge_window(
            farm, start_ridge, end_ridge, max_width=self.equipment.planting_max_ridges_per_pass,
        )
        if error:
            return {"error": error}
        backend = getattr(farm.world._physics, "crop_backend", None)
        if backend is not None:
            error = backend.check_replant(range(start_ridge, end_ridge + 1))
            if error:
                return {"error": error}
        ridges = [farm.world.get_ridge(r) for r in range(start_ridge, end_ridge + 1)]
        definition = farm.world.crop_definition
        error = self._planting_error(
            farm, ridges, depth_cm, spacing_cm,
            rules=definition.replanting_rules or definition.planting_rules,
        )
        if error:
            return {"error": error}
        try:
            plan = self._prepare_planting_plan(farm, ridges, depth_cm, spacing_cm, replace_existing=True)
            physics = farm.world.physics
            replant = physics.crop.prepare_replant(plan.event, physics.management.states, full_replant=full_replant)
        except ValueError as exc:
            return {"error": str(exc)}
        farm.advance_time(plan.duration_s)
        physics.crop.apply_replant(replant, physics.management.states)
        if replant.fresh_ridge_ids:
            fresh = [farm.world.get_ridge(r) for r in replant.fresh_ridge_ids]
            self._tractor_register_planting_with_physics(
                farm, fresh, depth_cm, spacing_cm,
                event=replace(replant.event, ridge_ids=replant.fresh_ridge_ids,
                              stand_fraction_by_ridge=replant.stand_after), already_planted=True,
            )
            for ridge in fresh:
                farm.world.record_planting_metadata(ridge.ridge_id, self.seed_type, spacing_cm, plan.seeds_per_ridge)
        self._seed_hopper -= plan.total_seeds
        self._fuel_tank_l = self._tractor_balance_after_use(farm, self._fuel_tank_l, plan.fuel_liters)
        stand_feedback = {
            "stand_fraction_before": {rid: round(value, 3) for rid, value in replant.stand_before.items()},
            "stand_fraction_after": {rid: round(value, 3) for rid, value in replant.stand_after.items()},
        }
        farm.world.record_action(FarmActionRecord(
            action_id=str(uuid.uuid4())[:8], timestamp=float(self.time_manager.time()), actor_app=self.name,
            action_type="replanting", ridge_ids=list(plan.event.ridge_ids),
            parameters={"seed_type": self.seed_type, "seed_depth_cm": depth_cm,
                        "spacing_cm": spacing_cm, "full_replant": full_replant},
            direct_effect_summary={"phenology_reset_ridges": list(replant.fresh_ridge_ids),
                                   **stand_feedback},
        ))
        farm.world.advance_physics_time()
        self._operation_log.append({
            "farm_id": farm.farm_id, "op_id": str(uuid.uuid4())[:8], "operation": "replant_seeds",
            "ridge_ids": list(plan.event.ridge_ids), "depth_cm": depth_cm, "seed_spacing_cm": spacing_cm,
            "seeds_used": plan.total_seeds, "duration_s": plan.duration_s,
            "full_replant": full_replant, "phenology_reset_ridge_ids": list(replant.fresh_ridge_ids),
            **stand_feedback,
        })
        self.is_state_modified = True
        return {"status": "ok", "replanted_ridges": list(plan.event.ridge_ids),
                "seeds_used": plan.total_seeds, "full_replant": full_replant,
                "phenology_reset_ridges": list(replant.fresh_ridge_ids), **stand_feedback}

    def _operate_incorporate_residue(
        self,
        farm: FarmContext,
        start_ridge: int,
        end_ridge: int,
    ) -> dict[str, Any]:
        """
        Tillage pass that incorporates harvested-crop residue back into the soil.

        Post-harvest agronomic step: returning organic matter to the soil
        rather than burning it. Logged action only — the reduced physics
        engine doesn't model soil organic carbon, but FOS gates verify the
        agent followed the right post-harvest sequence.

        Args:
            start_ridge: First ridge (0-63).
            end_ridge:   Last ridge (0-63, max 10-ridge span).
        """
        err = self._tractor_validate_ridge_window(farm, start_ridge, end_ridge, max_width=10)
        if err:
            return {"error": err}
        if self._fuel_tank_l < _fuel_per_pass(farm.world):
            return {"error": f"Insufficient fuel: need {_fuel_per_pass(farm.world)} L"}

        self._fuel_tank_l = self._fuel_tank_l - _fuel_per_pass(farm.world)
        duration = _pass_duration(farm.world, _SPEED_TILL_MS)
        farm.advance_time(duration)

        if farm.world.physics_active:
            self._tractor_register_residue_incorporation_with_physics(
                farm,
                ridge_ids=list(range(start_ridge, end_ridge + 1)),
            )

        op_id = str(uuid.uuid4())[:8]
        self._operation_log.append(
            {
                "farm_id": farm.farm_id,
                "op_id": op_id,
                "operation": "incorporate_residue",
                "ridge_ids": list(range(start_ridge, end_ridge + 1)),
                "duration_s": duration,
            }
        )
        self.is_state_modified = True
        return {
            "status": "ok",
            "ridge_ids": list(range(start_ridge, end_ridge + 1)),
        }

    def _operate_harvest(
        self,
        farm: FarmContext,
        start_ridge: int,
        end_ridge: int,
    ) -> dict[str, Any]:
        """
        Harvest a contiguous block of ridges (up to 4 per pass).

        Args:
            start_ridge: First ridge to harvest (0-63).
            end_ridge:   Last ridge to harvest (0-63, max 4-ridge span).
        """
        err = self._tractor_validate_ridge_window(farm, start_ridge, end_ridge, max_width=self.equipment.harvest_max_ridges_per_pass)
        if err:
            return {"error": err}
        if farm.weather.rainfall_mm > 0.0:
            return {"error": "Cannot harvest in rainy conditions"}
        traffic_error = self._tractor_trafficability_error(farm, "harvest")
        if traffic_error:
            return {"error": traffic_error}

        ridges = [
            farm.world.get_ridge(r) for r in range(start_ridge, end_ridge + 1)
        ]
        if any(not r.planted for r in ridges):
            return {"error": "All ridges must be planted before harvest"}
        rules = farm.world.crop_definition.harvest_rules
        error = rules.validate_implement(self._attached_implement)
        if error:
            return {"error": error}
        mature_stages = {stage.upper() for stage in rules.stage_codes}
        max_moisture = (self._harvest_moisture_limit_pct
                        if getattr(self, "_harvest_limit_configured", False)
                        else rules.max_moisture_pct)
        immature_ridges = [
            r.ridge_id
            for r in ridges
            if not farm.world.is_ridge_mature(r.ridge_id)
        ]
        if immature_ridges:
            return {
                "error": f"Ridges are not mature enough for harvest: {immature_ridges}"
            }
        bad_moisture = [r.ridge_id for r in ridges if r.grain_moisture_pct > max_moisture]
        if bad_moisture:
            return {
                "error": (
                    f"Grain moisture too high for harvest (>{max_moisture:g}%) on ridges "
                    f"{bad_moisture}"
                )
            }
        if self._fuel_tank_l < _fuel_per_pass(farm.world):
            return {
                "error": f"Insufficient fuel: need {_fuel_per_pass(farm.world)} L, have {self._fuel_tank_l:.1f} L"
            }

        worst_case_grain = harvest_grain_upper_bound_kg(
            farm.world, list(range(start_ridge, end_ridge + 1)))
        if self._grain_bin_kg + worst_case_grain > _GRAIN_BIN_MAX_KG:
            return {
                "error": (
                    f"Grain bin would overflow: {self._grain_bin_kg:.0f} + "
                    f"{worst_case_grain:.0f} kg > {_GRAIN_BIN_MAX_KG:.0f} kg. "
                    f"Call unload_grain first."
                )
            }

        ridge_ids = list(range(start_ridge, end_ridge + 1))
        self._fuel_tank_l = self._tractor_balance_after_use(
            farm, self._fuel_tank_l, _fuel_per_pass(farm.world)
        )
        duration = self._tractor_pass_duration(farm, _SPEED_HARVEST_MS)
        farm.advance_time(duration)
        if farm.world.physics_active:
            # A pass can cross the daily weather boundary. Its real time and
            # fuel were spent, but a newly wet crop must not enter the harvest
            # queue and raise after resources have already been charged.
            farm.world.advance_physics_time()
            end_moistures = {
                rid: farm.world.physics.yield_recovery.states[rid].grain_moisture_frac * 100.0
                for rid in ridge_ids
            }
            too_wet = [rid for rid, moisture in end_moistures.items()
                       if moisture > max_moisture]
            if too_wet or farm.weather.rainfall_mm > 0.0:
                reason = (f"Grain moisture exceeded {max_moisture:g}% during the pass on ridges {too_wet}"
                          if too_wet else "Rain started during the harvest pass")
                self._operation_log.append({
                    "farm_id": farm.farm_id, "op_id": str(uuid.uuid4())[:8],
                    "operation": "harvest", "ridge_ids": ridge_ids,
                    "status": "failed", "error": reason, "duration_s": duration,
                    "fuel_used_l": _fuel_per_pass(farm.world), "grain_kg_added": 0.0,
                })
                self.is_state_modified = True
                return {
                    "status": "failed", "error": reason, "harvested_ridges": [],
                    "grain_kg_added": 0.0, "duration_s": duration,
                    "fuel_used_l": _fuel_per_pass(farm.world),
                    "grain_bin_kg": round(self._grain_bin_kg, 1),
                    "grain_moisture_pct_by_ridge": {str(rid): moisture for rid, moisture in end_moistures.items()},
                }
        # Keep each legacy runtime combine's grain provenance on that asset;
        # independently owned machines must not consume each other's field buffer.
        shared_asset = getattr(self, "_shared_asset_state", None)
        if shared_asset is None:
            farm.world.record_grain_bin_moisture(ridge_ids)
            grain_moistures = []
        else:
            grain_moistures = [farm.world._ridge_harvest_moisture_pct(rid) for rid in ridge_ids]
        grain_added = 0.0

        if farm.world.physics_active:
            # Physics path: route through yield-recovery engine. Recovered
            # yield depends on grain moisture, machine quality, lodging,
            # and shattering — not a fixed kg per ridge.
            grain_added = self._tractor_register_harvest_with_physics(farm,
                ridge_ids=ridge_ids,
            )
        else:
            for r in ridges:
                result = farm.world.set_ridge_harvested(r.ridge_id)
                grain_added += float(result.get("grain_kg_added", 0.0))
            grain_added = round(grain_added, 2)
        self._grain_bin_kg = round(self._grain_bin_kg + grain_added, 2)
        if shared_asset is not None and grain_added > 0:
            moistures = [float(value) for value in grain_moistures if value is not None]
            shared_asset.grain_lots.append({
                "farm_id": farm.world.farm_id, "crop_type": farm.world.crop_type,
                "ridge_ids": list(ridge_ids), "grain_kg": round(grain_added, 2),
                "moisture_pct": max(moistures) if moistures else 0.0,
                "moistures_pct": moistures, "harvested_at": float(self.time_manager.time()),
            })

        op_id = str(uuid.uuid4())[:8]
        self._operation_log.append(
            {
                "farm_id": farm.farm_id,
                "op_id": op_id,
                "operation": "harvest",
                "ridge_ids": ridge_ids,
                "grain_kg_added": grain_added,
                "grain_bin_kg": round(self._grain_bin_kg, 1),
                "duration_s": duration,
            }
        )
        self.is_state_modified = True
        return {
            "status": "ok",
            "harvested_ridges": ridge_ids,
            "grain_kg_added": grain_added,
            "grain_bin_kg": round(self._grain_bin_kg, 1),
            "grain_bin_max_kg": _GRAIN_BIN_MAX_KG,
        }

    def _operate_unload_grain(self, farm: FarmContext) -> dict[str, Any]:
        """
        Unload the combine grain bin into the farm warehouse (trailer transfer).
        Takes about 8 minutes. Call this when the bin is full or after the
        final harvest pass to deposit grain into the warehouse inventory.
        """
        if self._grain_bin_kg <= 0.0:
            return {"error": "Grain bin is already empty"}
        unloaded = round(self._grain_bin_kg, 2)
        shared_asset = getattr(self, "_shared_asset_state", None)
        if shared_asset is not None:
            lots = shared_asset.grain_lots
            if (not lots or any(lot["farm_id"] != farm.world.farm_id for lot in lots)
                    or abs(sum(float(lot["grain_kg"]) for lot in lots) - unloaded) > 0.011):
                return {"error": "Grain lots must match this asset's bin and origin farm"}
        farm.advance_time(_GRAIN_UNLOAD_DURATION_S)
        if shared_asset is None:
            farm.world.add_grain_to_inventory(unloaded)
        else:
            farm = farm.world
            farm._inventory.harvest_grain_kg = round(farm._inventory.harvest_grain_kg + unloaded, 2)
            farm._inventory.grain_dried = False
            for lot in shared_asset.grain_lots:
                farm._trailer_grain_ridge_ids.extend(lot["ridge_ids"])
                farm._trailer_grain_moistures_pct.extend(lot.get("moistures_pct") or [lot["moisture_pct"]])
            shared_asset.grain_lots = []
            farm.is_state_modified = True
        self._grain_bin_kg = 0.0

        op_id = str(uuid.uuid4())[:8]
        self._operation_log.append(
            {
                "op_id": op_id,
                "operation": "unload_grain",
                "grain_kg_unloaded": unloaded,
                "duration_s": _GRAIN_UNLOAD_DURATION_S,
            }
        )
        self.is_state_modified = True
        return {
            "status": "ok",
            "grain_kg_unloaded": unloaded,
            "grain_bin_kg": 0.0,
            "duration_minutes": round(_GRAIN_UNLOAD_DURATION_S / 60, 1),
        }

    def _tractor_validate_ridge_window(
        self,
        farm: FarmContext,
        start_ridge: int,
        end_ridge: int,
        max_width: int,
    ) -> str | None:
        if not 0 <= start_ridge <= end_ridge < farm.world.num_ridges:
            return f"Invalid ridge range [{start_ridge}, {end_ridge}]"
        if end_ridge - start_ridge + 1 > max_width:
            return f"Range cannot exceed {max_width} ridges per pass"
        return None

    def _tractor_trafficability_error(
        self,
        farm: FarmContext,
        operation: str,
    ) -> str | None:
        if (
            farm.world.physics_active
            and farm.world.physics.last_physics_sim_time is not None
        ):
            farm.world.advance_physics_time()
        avg_vwc = farm.world.get_avg_vwc()
        if farm.environment is None:
            # Legacy single-farm weather reports that farm's soil moisture.
            # Shared weather holds regional inputs; trafficability stays local.
            farm.weather.set_avg_soil_vwc(avg_vwc)
        if avg_vwc > _MAX_VWC_TRAFFIC:
            return (
                f"Soil too wet for {operation} "
                f"(avg VWC {avg_vwc:.3f} > {_MAX_VWC_TRAFFIC:.2f})"
            )
        return None

    def _tractor_register_planting_with_physics(
        self,
        farm: FarmContext,
        ridges: list[RidgeState],
        seed_depth_cm: float,
        seed_spacing_cm: float,
        initial_stand_fraction_by_ridge: dict[int, float] | None = None,
        replace_existing: bool = False,
        *, event: PlantingEvent | None = None, already_planted: bool = False,
    ) -> None:
        from fairy.apps.farm_world.farm_action_record import FarmActionRecord
        from fairy.physics import ManagementAction, ManagementActionType

        physics = farm.world.physics
        ridge_ids = [r.ridge_id for r in ridges]
        seed_type_value = self.seed_type
        now_t = float(self.time_manager.time())
        stand_fractions = (dict(event.stand_fraction_by_ridge) if event is not None else {
            r.ridge_id: float((initial_stand_fraction_by_ridge or {}).get(r.ridge_id, 1.0))
            for r in ridges
        })
        initial_stand_fraction_by_ridge = stand_fractions
        if event is None:
            density = farm.world.plants_per_ridge_from_spacing(seed_spacing_cm) / farm.world.field_geometry.ridge_area_m2
            event = PlantingEvent(tuple(ridge_ids), farm.world.simulation_date(now_t), seed_type_value,
                                  seed_depth_cm, stand_fractions, {rid: density for rid in ridge_ids},
                                  physics.latitude_deg, replace_existing)
        if not already_planted:
            physics.crop.plant(event)
        for ridge_id in ridge_ids:
            ridge = farm.world.get_ridge(ridge_id)
            initial_stand_fraction = max(
                0.0,
                min(
                    1.0,
                    float(
                        (initial_stand_fraction_by_ridge or {}).get(
                            ridge_id,
                            ridge.stand_fraction,
                        )
                    ),
                ),
            )
            physics.queue_management_action(
                ridge_id,
                ManagementAction(
                    action_type=ManagementActionType.PLANTING,
                    amount=1.0,
                    quality=1.0,
                    metadata={
                        "seed_depth_cm": float(seed_depth_cm),
                        "spacing_cm": float(seed_spacing_cm),
                        "seed_type": seed_type_value,
                        "initial_stand_fraction": initial_stand_fraction,
                    },
                ),
            )

        farm.world.record_action(
            FarmActionRecord(
                action_id=str(uuid.uuid4())[:8],
                timestamp=now_t,
                actor_app=self.name,
                action_type="planting",
                ridge_ids=ridge_ids,
                parameters={
                    "seed_type": seed_type_value,
                    "seed_depth_cm": float(seed_depth_cm),
                    "spacing_cm": float(seed_spacing_cm),
                },
                direct_effect_summary={
                    "phenology_stage": "PLANTED_PRE_EMERGENCE",
                    "stand_fraction_initial": round(
                        min(
                            float(
                                (initial_stand_fraction_by_ridge or {}).get(
                                    ridge.ridge_id,
                                    ridge.stand_fraction,
                                )
                            )
                            for ridge in ridges
                        ),
                        3,
                    ),
                },
            )
        )
        farm.world.advance_physics_time()

    def _tractor_register_harvest_with_physics(
        self,
        farm: FarmContext,
        ridge_ids: list[int],
    ) -> float:
        """Run a yield-recovery harvest pass and return total kg recovered.

        Uses the YieldRecoveryEngine to compute recovered yield per ridge
        from biological yield potential, grain moisture, machine quality, and
        field/lodging losses. The legacy set_ridge_harvested write is also
        invoked so RidgeState's planted/grain_moisture flags reset. The
        returned grain quantity replaces the fixed GRAIN_KG_PER_RIDGE × yield_potential
        used in the legacy path.
        """
        from fairy.apps.farm_world.farm_action_record import FarmActionRecord
        from fairy.apps.farm_world.farm_world_app import (
            DEFAULT_RIDGE_WIDTH_M,
            FIELD_LENGTH_M,
        )
        from fairy.physics import HarvestAction

        physics = farm.world.physics
        for ridge_id in ridge_ids:
            physics.queue_harvest(
                ridge_id,
                HarvestAction(machine_quality=0.95, pass_completed=True),
            )

        # Submit the harvest queue even at an unchanged timestamp. The
        # orchestrator applies the historical harvest drying/loss update.
        farm.world.advance_physics_time()

        # Convert recovered yield from g/m² to kg per ridge: each ridge is
        # FIELD_LENGTH_M × DEFAULT_RIDGE_WIDTH_M m².
        ridge_area_m2 = farm.world.ridge_area_m2
        total_kg = 0.0
        for ridge_id in ridge_ids:
            state = physics.yield_recovery.states[ridge_id]
            if state.harvested:
                kg = (
                    state.recovered_yield_g_m2_at_market_moisture
                    * ridge_area_m2
                    / 1000.0
                )
                total_kg += kg
                # Mirror harvested state into RidgeState (yield, moisture,
                # planted, growth_stage all reset).
                farm.world.set_ridge_harvested(ridge_id)

        farm.world.record_action(
            FarmActionRecord(
                action_id=str(uuid.uuid4())[:8],
                timestamp=float(self.time_manager.time()),
                actor_app=self.name,
                action_type="harvest",
                ridge_ids=list(ridge_ids),
                parameters={"machine_quality": 0.95},
                direct_effect_summary={
                    "recovered_yield_kg": round(total_kg, 2),
                    "yield_engine_used": True,
                },
            )
        )
        return round(total_kg, 2)

    def _tractor_register_base_fertilizer_with_physics(
        self,
        farm: FarmContext,
        ridge_ids: list[int],
        total_kg: float,
    ) -> None:
        if not farm.world.physics_active:
            return

        from fairy.apps.farm_world.farm_action_record import FarmActionRecord
        from fairy.physics import ManagementAction, ManagementActionType

        physics = farm.world.physics
        per_ridge = float(total_kg) / max(1, len(ridge_ids))
        normalized = per_ridge / 30.0
        for ridge_id in ridge_ids:
            physics.queue_management_action(
                ridge_id,
                ManagementAction(
                    action_type=ManagementActionType.BASE_FERTILIZER,
                    amount=normalized,
                    quality=1.0,
                    metadata={"kg_per_ridge": per_ridge},
                ),
            )
        farm.world.record_action(
            FarmActionRecord(
                action_id=str(uuid.uuid4())[:8],
                timestamp=float(self.time_manager.time()),
                actor_app=self.name,
                action_type="base_fertilizer",
                ridge_ids=list(ridge_ids),
                parameters={"total_kg": float(total_kg)},
                direct_effect_summary={"nutrient_baseline_registered": True},
            )
        )
        farm.world.advance_physics_time()

    def _tractor_register_fertilizer_with_physics(
        self,
        farm: FarmContext,
        ridge_ids: list[int],
        kg_per_ridge: float,
        method: str,
    ) -> None:
        if not farm.world.physics_active:
            return

        from fairy.apps.farm_world.farm_action_record import FarmActionRecord
        from fairy.physics import (
            ManagementAction,
            ManagementActionType,
        )

        physics = farm.world.physics
        # Map kg/ridge to a normalized fertigation amount. The management
        # engine treats `amount` as a relative input; we calibrate so that a
        # typical 30 kg/ridge dose registers as a strong single-pass effect.
        normalized_amount = float(kg_per_ridge) / 30.0
        for ridge_id in ridge_ids:
            physics.queue_management_action(
                ridge_id,
                ManagementAction(
                    action_type=ManagementActionType.FERTIGATION,
                    amount=normalized_amount,
                    quality=1.0,
                    metadata={
                        "method": method,
                        "kg_per_ridge": float(kg_per_ridge),
                    },
                ),
            )

        farm.world.record_action(
            FarmActionRecord(
                action_id=str(uuid.uuid4())[:8],
                timestamp=float(self.time_manager.time()),
                actor_app=self.name,
                action_type="fertigation",
                ridge_ids=list(ridge_ids),
                parameters={
                    "kg_per_ridge": float(kg_per_ridge),
                    "method": method,
                },
                direct_effect_summary={
                    "nutrient_index_increase_registered": True,
                    "ndvi_recovery_deferred": True,
                },
            )
        )
        farm.world.advance_physics_time()

    def _tractor_register_fungicide_with_physics(
        self,
        farm: FarmContext,
        ridge_ids: list[int],
        liters_per_ridge: float,
    ) -> None:
        if not farm.world.physics_active:
            return
        from fairy.apps.farm_world.farm_action_record import FarmActionRecord
        from fairy.physics import (
            ManagementAction,
            ManagementActionType,
            TreatmentApplication,
            TreatmentType,
        )

        physics = farm.world.physics
        for ridge_id in ridge_ids:
            physics.queue_treatment(
                ridge_id,
                TreatmentApplication(
                    treatment_type=TreatmentType.FUNGICIDE,
                    efficacy_multiplier=chemical_dose_efficacy(TreatmentType.FUNGICIDE, float(liters_per_ridge)),
                ),
            )
            physics.queue_management_action(
                ridge_id,
                ManagementAction(
                    action_type=ManagementActionType.FUNGICIDE,
                    amount=float(liters_per_ridge),
                    quality=chemical_dose_efficacy(TreatmentType.FUNGICIDE, float(liters_per_ridge)),
                    metadata={"method": "boom"},
                ),
            )

        farm.world.record_action(
            FarmActionRecord(
                action_id=str(uuid.uuid4())[:8],
                timestamp=float(self.time_manager.time()),
                actor_app=self.name,
                action_type="fungicide",
                ridge_ids=list(ridge_ids),
                parameters={
                    "liters_per_ridge": float(liters_per_ridge),
                    "method": "boom",
                },
                direct_effect_summary={
                    "treatment_type": "FUNGICIDE",
                    "residual_window_opened": True,
                },
            )
        )
        farm.world.advance_physics_time()

    def _tractor_register_weed_control_with_physics(
        self,
        farm: FarmContext,
        ridge_ids: list[int],
        action_type: str,
        method: str,
        efficacy_multiplier: float,
    ) -> None:
        if not farm.world.physics_active:
            return
        from fairy.apps.farm_world.farm_action_record import FarmActionRecord
        from fairy.physics import (
            ManagementAction,
            ManagementActionType,
            TreatmentApplication,
            TreatmentType,
        )

        physics = farm.world.physics
        is_mechanical = action_type == "mechanical_weed_control"
        treatment_type = (
            TreatmentType.MECHANICAL_WEED if is_mechanical else TreatmentType.HERBICIDE
        )
        management_action_type = (
            ManagementActionType.MECHANICAL_WEED_CONTROL
            if is_mechanical
            else ManagementActionType.HERBICIDE
        )
        for ridge_id in ridge_ids:
            physics.queue_treatment(
                ridge_id,
                TreatmentApplication(
                    treatment_type=treatment_type,
                    efficacy_multiplier=float(efficacy_multiplier),
                ),
            )
            physics.queue_management_action(
                ridge_id,
                ManagementAction(
                    action_type=management_action_type,
                    amount=1.0,
                    quality=float(efficacy_multiplier),
                    metadata={"method": method, "action_type": action_type},
                ),
            )

        farm.world.record_action(
            FarmActionRecord(
                action_id=str(uuid.uuid4())[:8],
                timestamp=float(self.time_manager.time()),
                actor_app=self.name,
                action_type=action_type,
                ridge_ids=list(ridge_ids),
                parameters={
                    "method": method,
                    "efficacy_multiplier": float(efficacy_multiplier),
                },
                direct_effect_summary={
                    "treatment_type": treatment_type.value,
                    "weed_control_registered": True,
                    "residual_window_opened": action_type == "herbicide",
                },
            )
        )
        farm.world.advance_physics_time()

    def _tractor_register_residue_incorporation_with_physics(
        self,
        farm: FarmContext,
        ridge_ids: list[int],
    ) -> None:
        if not farm.world.physics_active:
            return
        from fairy.apps.farm_world.farm_action_record import FarmActionRecord
        from fairy.physics import ManagementAction, ManagementActionType

        physics = farm.world.physics
        for ridge_id in ridge_ids:
            physics.queue_management_action(
                ridge_id,
                ManagementAction(
                    action_type=ManagementActionType.INCORPORATE_RESIDUE,
                    amount=1.0,
                    quality=1.0,
                ),
            )
        farm.world.record_action(
            FarmActionRecord(
                action_id=str(uuid.uuid4())[:8],
                timestamp=float(self.time_manager.time()),
                actor_app=self.name,
                action_type="incorporate_residue",
                ridge_ids=list(ridge_ids),
                parameters={},
                direct_effect_summary={"residue_incorporated": True},
            )
        )
        farm.world.advance_physics_time()

    def _tractor_register_spray_with_physics(
        self,
        farm: FarmContext,
        ridge_ids: list[int],
        method: str,
        efficacy_multiplier: float = 1.0,
    ) -> None:
        if not farm.world.physics_active:
            return

        from fairy.apps.farm_world.farm_action_record import FarmActionRecord
        from fairy.physics import (
            ManagementAction,
            ManagementActionType,
            TreatmentApplication,
            TreatmentType,
        )

        physics = farm.world.physics
        for ridge_id in ridge_ids:
            physics.queue_treatment(
                ridge_id,
                TreatmentApplication(
                    treatment_type=TreatmentType.INSECTICIDE,
                    efficacy_multiplier=efficacy_multiplier,
                ),
            )
            # Management residual window is updated via INSECTICIDE action.
            physics.queue_management_action(
                ridge_id,
                ManagementAction(
                    action_type=ManagementActionType.INSECTICIDE,
                    amount=1.0,
                    quality=efficacy_multiplier,
                    metadata={"method": method},
                ),
            )

        farm.world.record_action(
            FarmActionRecord(
                action_id=str(uuid.uuid4())[:8],
                timestamp=float(self.time_manager.time()),
                actor_app=self.name,
                action_type="insecticide",
                ridge_ids=list(ridge_ids),
                parameters={
                    "method": method,
                    "efficacy_multiplier": efficacy_multiplier,
                },
                direct_effect_summary={
                    "treatment_type": "INSECTICIDE",
                    "residual_window_opened": True,
                },
            )
        )
        farm.world.advance_physics_time()
