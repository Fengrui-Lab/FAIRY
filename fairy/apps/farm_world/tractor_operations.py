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
from typing import Any, TYPE_CHECKING

from fairy.apps.farm_world.farm_world_app import (
    FIELD_LENGTH_M,
    FIELD_WIDTH_M,
    PESTICIDE_L_PER_RIDGE,
    FarmWorldApp,
)
from fairy.apps.farm_world.models import (
    GrowthStage,
    RidgeState,
    SeedType,
)
from fairy.apps.farm_world.weather_app import WeatherApp, _MAX_VWC_TRAFFIC
from fairy.apps.farm_world.crop_profiles import official_seed_backend_error
from fairy.physics.biotic_pressure_engine import TreatmentType, chemical_dose_efficacy


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

    def _initialize_tractor_state(self) -> None:
        """Initialize the one physical tractor; farm preparation lives on the farm."""
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
            "available_implements": list(ATTACHMENTS),
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
        if implement not in _ATTACH_WIDTH_M:
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
        if seed_type not in {m.value for m in SeedType}:
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
            "grain_bin_kg": round(self._grain_bin_kg, 1),
            "grain_bin_max_kg": _GRAIN_BIN_MAX_KG,
            "available_implements": ATTACHMENTS,
            "attached_implement": self._attached_implement,
        }

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

    def _operate_base_fertilize(self, farm: FarmContext) -> dict[str, Any]:
        """
        Apply base fertilizer across the full field using the tractor spreader.
        """

        quota_error = farm.world.check_fertilizer_use(_base_fertilize_kg(farm.world))
        if quota_error:
            return {"error": quota_error}
        if self._fertilizer_spreader_kg < _base_fertilize_kg(farm.world):
            return {
                "error": f"Insufficient fertilizer in spreader: need {_base_fertilize_kg(farm.world)} kg, have {self._fertilizer_spreader_kg:.1f} kg"
            }
        if self._fuel_tank_l < _fuel_per_prep_op(farm.world):
            return {
                "error": f"Insufficient fuel: need {_fuel_per_prep_op(farm.world)} L, have {self._fuel_tank_l:.1f} L"
            }
        traffic_error = self._tractor_trafficability_error(farm, "tractor operation")
        if traffic_error:
            return {"error": traffic_error}

        self._fertilizer_spreader_kg = self._fertilizer_spreader_kg - _base_fertilize_kg(farm.world)
        farm.world.record_fertilizer_use(_base_fertilize_kg(farm.world))
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
                total_kg=_base_fertilize_kg(farm.world),
            )

        self._operation_log.append(
            {
                "farm_id": farm.farm_id,
                "op_id": str(uuid.uuid4())[:8],
                "operation": "base_fertilize",
                "fertilizer_used_kg": _base_fertilize_kg(farm.world),
                "duration_s": duration,
            }
        )
        self.is_state_modified = True
        return {
            "status": "ok",
            "fertilizer_used_kg": _base_fertilize_kg(farm.world),
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
        if self._fuel_tank_l < _fuel_per_prep_op(farm.world):
            return {
                "error": f"Insufficient fuel: need {_fuel_per_prep_op(farm.world)} L, have {self._fuel_tank_l:.1f} L"
            }
        ridge_width_m = float(ridge_width_m)
        if ridge_width_m <= 0.0:
            return {"error": "ridge_width_m must be positive"}
        # Each pass forms 4 ridges side by side
        ridges_per_pass = 4
        working_width_m = ridges_per_pass * ridge_width_m
        traffic_error = self._tractor_trafficability_error(farm, "tractor operation")
        if traffic_error:
            return {"error": traffic_error}

        duration = _full_field_duration(farm.world, working_width_m, _SPEED_RIDGE_MS)
        self._fuel_tank_l = self._fuel_tank_l - _fuel_per_prep_op(farm.world)
        farm.advance_time(duration)

        # Preserve pre-conditioned soil state (VWC, temp, pressure baselines).
        # FarmWorld has 64 fixed logical ridge IDs (0-63); ridge_width_m is an
        # operating setting, not permission to resize the indexed state/engine maps.
        farm.world.ridge_width_m = ridge_width_m
        for i, r in enumerate(farm.world._ridges):
            r.ridge_id = i
            r.planted = False
            r.seed_type = None
            r.seed_spacing_cm = None
            r.seeds_planted = 0
            r.growth_stage = GrowthStage.BARE.value
            r.days_since_planted = 0
            r.ndvi = -1.0
            r.canopy_temp_c = -1.0
            r.grain_moisture_pct = 0.0
            r.planted_at_sim_time = None
            r.pest_pressure = r.pest_pressure_base
            r.disease_pressure = r.disease_pressure_base

        farm.world.completed_prep_ops.append("form_ridges")
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
            "fuel_tank_l": self._fuel_tank_l,
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

    def _operate_plant_seeds(
        self,
        farm: FarmContext,
        start_ridge: int,
        end_ridge: int,
        depth_cm: float,
        seed_spacing_cm: float,
    ) -> dict[str, Any]:
        """
        Sow seeds across a contiguous block of ridges (up to 4 per pass).

        Seed types:
          STANDARD
          EARLY_COLD
          HIGH_DENSITY
          STRESS_TOLERANT
          HEIHE43
          HEIHE50
          HEINONG60
          HEINONG84
          HEIKE71

        Args:
            start_ridge: First ridge to plant (0-63).
            end_ridge:   Last ridge to plant (0-63, max 4-ridge span).
            depth_cm:    Sowing depth in centimetres.
            seed_spacing_cm:
                In-row seed spacing in centimetres.
        """
        err = self._tractor_validate_ridge_window(farm, start_ridge, end_ridge, max_width=4)
        if err:
            return {"error": err}
        native_seed_error = official_seed_backend_error(self.seed_type, farm.world._physics)
        if native_seed_error:
            return {"error": native_seed_error}
        if not 3.0 <= float(depth_cm) <= 5.0:
            return {"error": "depth_cm must be within 3–5 cm"}
        if float(seed_spacing_cm) <= 0:
            return {"error": "seed_spacing_cm must be positive"}

        # Requirements and completed work both belong to the target field.
        required = farm.world.required_field_preparation_ops
        missing = [
            op for op in required if op not in farm.world.completed_prep_ops
        ]
        if missing:
            return {
                "error": (
                    "Field preparation incomplete: must finish "
                    + " -> ".join(required) + " before planting"
                    f" (missing: {missing})"
                )
            }

        ridges = [
            farm.world.get_ridge(r) for r in range(start_ridge, end_ridge + 1)
        ]
        if any(r.planted for r in ridges):
            return {"error": "One or more ridges are already planted"}

        window_error = farm.world.check_planting_window(
            [r.ridge_id for r in ridges], self.seed_type
        )
        if window_error:
            return {"error": window_error}

        avg_vwc = sum(r.soil_vwc for r in ridges) / len(ridges)
        avg_temp = sum(r.soil_temp_c for r in ridges) / len(ridges)
        if not 0.20 <= avg_vwc <= 0.35:
            return {
                "error": f"Soil VWC {avg_vwc:.3f} must be within 0.20–0.30 for planting"
            }
        if self.seed_type == SeedType.EARLY_COLD.value:
            if avg_temp < 8.0:
                return {
                    "error": f"Soil temperature {avg_temp:.1f}°C too low for EARLY_COLD (min 8°C)"
                }
        elif avg_temp <= 10.0:
            return {
                "error": f"Soil temperature {avg_temp:.1f}°C must exceed 10°C for planting"
            }

        seeds_per_ridge = farm.world.plants_per_ridge_from_spacing(seed_spacing_cm)
        seed_count = len(ridges) * seeds_per_ridge
        if self._seed_hopper < seed_count:
            return {
                "error": f"Insufficient {self.seed_type} seeds in hopper: need {seed_count}, have {self._seed_hopper}"
            }
        if self._fuel_tank_l < _fuel_per_pass(farm.world):
            return {
                "error": f"Insufficient fuel: need {_fuel_per_pass(farm.world)} L, have {self._fuel_tank_l:.1f} L"
            }

        self._seed_hopper = self._seed_hopper - seed_count
        self._fuel_tank_l = self._fuel_tank_l - _fuel_per_pass(farm.world)
        duration = _pass_duration(farm.world, _SPEED_PLANT_MS)
        farm.advance_time(duration)
        for r in ridges:
            farm.world.set_ridge_planted(
                r.ridge_id,
                self.seed_type,
                seed_spacing_cm=float(seed_spacing_cm),
                seeds_planted=seeds_per_ridge,
            )

        # Physics integration: register the planting action with engines.
        # This records the action, initialises phenology to PLANTED_PRE_EMERGENCE
        # (NOT VE — emergence comes later via accumulated GDD), and queues a
        # PLANTING management action so stand_fraction is set on next tick.
        # Compatibility shadow: legacy growth_stage=VE set above is overwritten
        # by the orchestrator's compat sync to "bare" until phenology emerges.
        self._tractor_register_planting_with_physics(
            farm,
            ridges=ridges,
            seed_depth_cm=float(depth_cm),
            seed_spacing_cm=float(seed_spacing_cm),
        )

        op_id = str(uuid.uuid4())[:8]
        self._operation_log.append(
            {
                "farm_id": farm.farm_id,
                "op_id": op_id,
                "operation": "plant_seeds",
                "ridge_ids": list(range(start_ridge, end_ridge + 1)),
                "depth_cm": float(depth_cm),
                "seed_spacing_cm": float(seed_spacing_cm),
                "seeds_per_ridge": seeds_per_ridge,
                "seeds_used": seed_count,
                "duration_s": duration,
            }
        )
        self.is_state_modified = True
        return {
            "status": "ok",
            "planted_ridges": list(range(start_ridge, end_ridge + 1)),
            "depth_cm": float(depth_cm),
            "seed_spacing_cm": float(seed_spacing_cm),
            "seeds_per_ridge": seeds_per_ridge,
            "seeds_used": seed_count,
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
        self,
        farm: FarmContext,
        start_ridge: int,
        end_ridge: int,
        depth_cm: float,
        spacing_cm: float,
        full_replant: bool = False,
    ) -> dict[str, Any]:
        """
        Replant a block of failed/poorly-emerged ridges.

        For ridges that have not emerged yet, this behaves like a fresh
        planting pass. For ridges that already have an established crop, the
        operation represents gap-filling within the row: it improves
        ``stand_fraction`` without resetting the whole ridge's phenology.
        Set ``full_replant=True`` only when inspection shows the ridge stand
        failed badly enough that the farm decision is to re-sow the ridge and
        accept a later maturity window.

        With WOFOST, any started native crop rejects both replacement and gap
        filling before consuming resources; a new native season is required.

        Args:
            start_ridge: First ridge (0-63).
            end_ridge:   Last ridge (0-63, max 4-ridge span).
            depth_cm:    Sowing depth (3-5 cm).
            spacing_cm:  In-row seed spacing (>0).
            full_replant: Whether this pass resets the ridge phenology.
        """
        seed_spacing_cm = float(spacing_cm)
        err = self._tractor_validate_ridge_window(farm, start_ridge, end_ridge, max_width=4)
        if err:
            return {"error": err}
        native_seed_error = official_seed_backend_error(self.seed_type, farm.world._physics)
        if native_seed_error:
            return {"error": native_seed_error}
        backend = getattr(farm.world._physics, "crop_backend", None)
        if backend is not None:
            error = backend.check_replant(range(start_ridge, end_ridge + 1))
            if error:
                return {"error": error}
        if not 3.0 <= float(depth_cm) <= 5.0:
            return {"error": "depth_cm must be within 3–5 cm"}
        if float(seed_spacing_cm) <= 0:
            return {"error": "seed_spacing_cm must be positive"}

        ridges = [
            farm.world.get_ridge(r) for r in range(start_ridge, end_ridge + 1)
        ]
        seeds_per_ridge = farm.world.plants_per_ridge_from_spacing(seed_spacing_cm)
        seed_count = len(ridges) * seeds_per_ridge
        if self._seed_hopper < seed_count:
            return {
                "error": f"Insufficient {self.seed_type} seeds in hopper: need {seed_count}"
            }
        if self._fuel_tank_l < _fuel_per_pass(farm.world):
            return {"error": f"Insufficient fuel: need {_fuel_per_pass(farm.world)} L"}

        self._seed_hopper -= seed_count
        self._fuel_tank_l = self._fuel_tank_l - _fuel_per_pass(farm.world)
        duration = _pass_duration(farm.world, _SPEED_PLANT_MS)
        farm.advance_time(duration)

        stand_fraction_before: dict[int, float] = {}
        stand_fraction_overrides: dict[int, float] = {}
        fresh_replant_ridges: list[RidgeState] = []

        if farm.world.physics_active:
            from fairy.physics import SoybeanStage

            for r in ridges:
                phen = farm.world.physics.phenology.states[r.ridge_id]
                current_stand = max(0.0, min(1.0, float(r.stand_fraction)))
                stand_fraction_before[r.ridge_id] = current_stand
                recovered_stand = min(0.92, current_stand + (1.0 - current_stand) * 0.6)
                stand_fraction_overrides[r.ridge_id] = max(
                    current_stand, recovered_stand
                )
                r.stand_fraction = stand_fraction_overrides[r.ridge_id]

                if full_replant or phen.stage in {
                    SoybeanStage.NOT_PLANTED,
                    SoybeanStage.PLANTED_PRE_EMERGENCE,
                }:
                    phen.stage = SoybeanStage.PLANTED_PRE_EMERGENCE
                    phen.emerged = False
                    phen.accumulated_gdd = 0.0
                    phen.effective_development_gdd = 0.0
                    phen.days_after_planting = 0
                    fresh_replant_ridges.append(r)
                else:
                    mgmt = farm.world.physics.management.states[r.ridge_id]
                    mgmt.planted = True
                    mgmt.stand_fraction = stand_fraction_overrides[r.ridge_id]
                    mgmt.planting_quality = max(
                        mgmt.planting_quality,
                        stand_fraction_overrides[r.ridge_id],
                    )
                    if "partial_replant_stand_recovery" not in mgmt.tags:
                        mgmt.tags.append("partial_replant_stand_recovery")

            if fresh_replant_ridges:
                self._tractor_register_planting_with_physics(
                    farm,
                    ridges=fresh_replant_ridges,
                    seed_depth_cm=float(depth_cm),
                    seed_spacing_cm=float(seed_spacing_cm),
                    initial_stand_fraction_by_ridge=stand_fraction_overrides,
                )
        else:
            for r in ridges:
                current_stand = max(0.0, min(1.0, float(r.stand_fraction)))
                stand_fraction_before[r.ridge_id] = current_stand
                recovered_stand = min(0.92, current_stand + (1.0 - current_stand) * 0.6)
                stand_fraction_overrides[r.ridge_id] = max(
                    current_stand, recovered_stand
                )
                r.stand_fraction = stand_fraction_overrides[r.ridge_id]

        if farm.world.physics_active:
            from fairy.apps.farm_world.farm_action_record import (
                FarmActionRecord,
            )

            farm.world.record_action(
                FarmActionRecord(
                    action_id=str(uuid.uuid4())[:8],
                    timestamp=float(self.time_manager.time()),
                    actor_app=self.name,
                    action_type="replanting",
                    ridge_ids=list(range(start_ridge, end_ridge + 1)),
                    parameters={
                        "seed_type": self.seed_type,
                        "seed_depth_cm": float(depth_cm),
                        "spacing_cm": float(seed_spacing_cm),
                        "full_replant": bool(full_replant),
                    },
                    direct_effect_summary={
                        "phenology_reset_ridges": [
                            ridge.ridge_id for ridge in fresh_replant_ridges
                        ],
                        "stand_fraction_before": {
                            ridge_id: round(value, 3)
                            for ridge_id, value in stand_fraction_before.items()
                        },
                        "stand_fraction_after": {
                            ridge_id: round(value, 3)
                            for ridge_id, value in stand_fraction_overrides.items()
                        },
                    },
                )
            )
        # Fresh replanting behaves like a new sowing pass. Gap filling only
        # improves stand; it must not reset the established crop's legacy
        # planting date, days_since_planted, or growth_stage.
        if farm.world.physics_active:
            legacy_fresh_ridges = fresh_replant_ridges
        else:
            legacy_fresh_ridges = [r for r in ridges if not r.planted]
        for r in legacy_fresh_ridges:
            farm.world.set_ridge_planted(
                r.ridge_id,
                self.seed_type,
                seed_spacing_cm=float(seed_spacing_cm),
                seeds_planted=seeds_per_ridge,
            )

        op_id = str(uuid.uuid4())[:8]
        self._operation_log.append(
            {
                "farm_id": farm.farm_id,
                "op_id": op_id,
                "operation": "replant_seeds",
                "ridge_ids": list(range(start_ridge, end_ridge + 1)),
                "depth_cm": float(depth_cm),
                "seed_spacing_cm": float(seed_spacing_cm),
                "full_replant": bool(full_replant),
                "seeds_used": seed_count,
                "phenology_reset_ridge_ids": [
                    ridge.ridge_id for ridge in fresh_replant_ridges
                ],
                "stand_fraction_before": {
                    ridge_id: round(value, 3)
                    for ridge_id, value in stand_fraction_before.items()
                },
                "stand_fraction_after": {
                    ridge_id: round(value, 3)
                    for ridge_id, value in stand_fraction_overrides.items()
                },
                "duration_s": duration,
            }
        )
        self.is_state_modified = True
        return {
            "status": "ok",
            "replanted_ridges": list(range(start_ridge, end_ridge + 1)),
            "full_replant": bool(full_replant),
            "seeds_used": seed_count,
            "phenology_reset_ridges": [
                ridge.ridge_id for ridge in fresh_replant_ridges
            ],
            "stand_fraction_before": {
                ridge_id: round(value, 3)
                for ridge_id, value in stand_fraction_before.items()
            },
            "stand_fraction_after": {
                ridge_id: round(value, 3)
                for ridge_id, value in stand_fraction_overrides.items()
            },
        }

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
        err = self._tractor_validate_ridge_window(farm, start_ridge, end_ridge, max_width=4)
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
        immature_ridges = [
            r.ridge_id
            for r in ridges
            if str(r.growth_stage).upper()
            not in {GrowthStage.R8.value.upper(), "R8_FULL_MATURITY"}
        ]
        if immature_ridges:
            return {
                "error": f"Ridges are not mature enough for harvest: {immature_ridges}"
            }
        bad_moisture = [r.ridge_id for r in ridges if r.grain_moisture_pct > 18.0]
        if bad_moisture:
            return {
                "error": (
                    "Grain moisture too high for harvest (>18%) on ridges "
                    f"{bad_moisture}"
                )
            }
        if self._fuel_tank_l < _fuel_per_pass(farm.world):
            return {
                "error": f"Insufficient fuel: need {_fuel_per_pass(farm.world)} L, have {self._fuel_tank_l:.1f} L"
            }

        # Native biological mass can exceed a compatibility yield assumption.
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
        self._fuel_tank_l = self._fuel_tank_l - _fuel_per_pass(farm.world)
        duration = _pass_duration(farm.world, _SPEED_HARVEST_MS)
        farm.advance_time(duration)
        # Sample the same end-of-pass moisture used by yield settlement.
        farm.world.record_grain_bin_moisture(ridge_ids)
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
        farm.advance_time(_GRAIN_UNLOAD_DURATION_S)
        farm.world.add_grain_to_inventory(unloaded)
        self._grain_bin_kg = 0.0

        op_id = str(uuid.uuid4())[:8]
        self._operation_log.append(
            {
                "farm_id": farm.farm_id,
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
    ) -> None:
        from fairy.apps.farm_world.farm_action_record import FarmActionRecord
        from fairy.physics import (
            ManagementAction,
            ManagementActionType,
            PlantingConfig,
        )
        from fairy.physics import (
            SeedType as PhysicsSeedType,
        )

        physics = farm.world.physics
        ridge_ids = [r.ridge_id for r in ridges]
        seed_type_value = self.seed_type or SeedType.STANDARD.value
        try:
            physics_seed_type = PhysicsSeedType(seed_type_value)
        except ValueError:
            physics_seed_type = PhysicsSeedType.STANDARD

        now_t = float(self.time_manager.time())
        today = farm.world.simulation_date(now_t)

        physics.phenology.plant_ridges(
            ridge_ids,
            PlantingConfig(
                planting_date=today,
                seed_type=physics_seed_type,
                seed_depth_cm=float(seed_depth_cm),
                planting_quality=1.0,
                latitude_deg=physics.latitude_deg,
            ),
        )
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
        from fairy.physics import HarvestAction

        physics = farm.world.physics
        for ridge_id in ridge_ids:
            physics.queue_harvest(
                ridge_id,
                HarvestAction(machine_quality=0.95, pass_completed=True),
            )

        # Submit the harvest queue even at an unchanged timestamp. The
        # orchestrator settles actions without running another drying day.
        farm.world.advance_physics_time()

        # Native yield is per square metre; target field geometry owns kg.
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
                    "treatment_type": "HERBICIDE",
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
