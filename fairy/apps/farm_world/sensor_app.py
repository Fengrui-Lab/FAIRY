"""
SensorApp - fixed sensor infrastructure for Farm-World.

Manages soil probes (VWC + temperature) and canopy sensors (NDVI proxy).
The historical 64-ridge layout has six of each, at ridges
5/15/25/38/48/58. Other layouts partition their actual local ridge range.

Each sensor covers a contiguous range of ridges:
  S1/C1: ridge 0-10   (installed at ridge 5)
  S2/C2: ridge 11-21  (installed at ridge 15)
  S3/C3: ridge 22-32  (installed at ridge 25)
  S4/C4: ridge 33-43  (installed at ridge 38)
  S5/C5: ridge 44-53  (installed at ridge 48)
  S6/C6: ridge 54-63  (installed at ridge 58)

Agent-facing tools add small random noise to mimic sensor uncertainty. [设计]
Scenario events update cached readings via @env_tool methods.

Weather station data is NOT managed here — use WeatherApp.get_current_weather().
"""

from __future__ import annotations

import random
from typing import Any

from fairy.apps.app import App
from fairy.apps.farm_world.farm_world_app import FarmWorldApp
from fairy.tool_utils import OperationType, app_tool, data_tool
from fairy.types import event_registered
from fairy.utils.type_utils import type_check

# (sensor_id, installed_ridge, ridge_start, ridge_end)
_SENSOR_ZONES: list[tuple[str, int, int, int]] = [
    ("1", 5, 0, 10),
    ("2", 15, 11, 21),
    ("3", 25, 22, 32),
    ("4", 38, 33, 43),
    ("5", 48, 44, 53),
    ("6", 58, 54, 63),
]


class SensorApp(App):
    """Configured soil and canopy probes, each covering a local ridge zone."""

    def get_tools(self):
        tools = super().get_tools()
        if self._farm_world_app.farm_environment is not None:
            # These shared scenes install surface probes, not extra root probes.
            tools = [tool for tool in tools if tool.name != "read_root_zone_sensors"]
        return tools

    def __init__(self, farm_world_app: FarmWorldApp, name: str | None = None) -> None:
        super().__init__(name=name or "SensorApp")
        self._farm_world_app = farm_world_app
        self.bound_farm_id = farm_world_app.farm_id
        self._sensor_zones = self._zones_for_ridges(farm_world_app.num_ridges)
        self._soil_sensors = self._default_soil_sensors()
        self._canopy_sensors = self._default_canopy_sensors()

    # ------------------------------------------------------------------
    # App interface
    # ------------------------------------------------------------------

    def get_state(self) -> dict[str, Any]:
        version, internal, gaussian = self.rng.getstate()
        return {
            "app_name": self.name,
            "farm_id": self.bound_farm_id,
            "crop_id": self._farm_world_app.crop_type,
            "random_state": [version, list(internal), gaussian],
            "soil_sensors": [dict(s) for s in self._soil_sensors],
            "canopy_sensors": [dict(s) for s in self._canopy_sensors],
        }

    def load_state(self, state_dict: dict[str, Any]) -> None:
        if state_dict.get("farm_id", self.bound_farm_id) != self.bound_farm_id:
            raise ValueError("Sensor snapshot belongs to another farm")
        if state_dict.get("crop_id", self._farm_world_app.crop_type) != self._farm_world_app.crop_type:
            raise ValueError("Sensor snapshot belongs to another crop")
        saved_rng = state_dict.get("random_state")
        if saved_rng is not None:
            version, internal, gaussian = saved_rng
            restored_rng = (version, tuple(internal), gaussian)
            random.Random().setstate(restored_rng)
            self.rng.setstate(restored_rng)
        self._soil_sensors = [dict(s) for s in state_dict["soil_sensors"]]
        self._canopy_sensors = [dict(s) for s in state_dict["canopy_sensors"]]

    def reset(self) -> None:
        super().reset()
        self._sensor_zones = self._zones_for_ridges(self._farm_world_app.num_ridges)
        self._soil_sensors = self._default_soil_sensors()
        self._canopy_sensors = self._default_canopy_sensors()

    @staticmethod
    def _zones_for_ridges(num_ridges: int) -> list[tuple[str, int, int, int]]:
        """Cover every ridge exactly once, preserving the historical 64-ridge map."""
        if num_ridges == 64:
            return list(_SENSOR_ZONES)
        count = min(6, num_ridges)
        zones = []
        for index in range(count):
            start = index * num_ridges // count
            end = (index + 1) * num_ridges // count - 1
            zones.append((str(index + 1), (start + end) // 2, start, end))
        return zones

    # ------------------------------------------------------------------
    # Agent tools
    # ------------------------------------------------------------------

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def read_root_zone_sensors(self) -> dict[str, Any]:
        """Read simulated root-zone water telemetry for irrigation decisions.

        This is a separate modeled root-zone probe, not the existing 5 cm
        surface sensor. Values are zone averages with +/-0.005 VWC noise;
        use the local crop's irrigation threshold and check again after delivery.

        When WOFOST is active, soil_nitrogen also reports native CNB model
        telemetry for the same coverage zone: available and reserve nitrogen
        in kg N/ha, the completed native forcing day, and the latest nitrogen
        state day (which also includes scenario nitrogen interventions). These are modeled
        soil pools, not a physical nitrogen probe or a plant nitrogen-deficiency
        diagnosis. Existing nutrient_index is a separate juvenile growth proxy.
        Nitrogen values are unavailable until every covered ridge has a native
        state for the same completed day; missing values are never zero-filled.
        """
        self._sync_sensors()
        farm = self._farm_world_app
        if not farm.physics_active:
            return {"error": "Root-zone telemetry requires an active soil physics model"}
        farm.advance_physics_time()
        readings = []
        for sensor in self._soil_sensors:
            ids = range(sensor["ridge_start"], sensor["ridge_end"]+1)
            values = [farm.physics.soil.states[ridge_id].root_vwc for ridge_id in ids]
            reading = {"sensor_id": "R"+sensor["sensor_id"][1:],
                       "ridge_start": sensor["ridge_start"], "ridge_end": sensor["ridge_end"],
                       "root_vwc": round(max(0.0, min(1.0, sum(values)/len(values)+self.rng.uniform(-0.005, 0.005))), 4)}
            nitrogen_reader = getattr(farm.physics.crop_backend, "native_soil_nitrogen", None)
            if nitrogen_reader is not None:
                reading["soil_nitrogen"] = self._native_nitrogen_zone(nitrogen_reader(ids))
            readings.append(reading)
        return {"root_zone_sensors": readings, "source": "simulated_root_zone_probes",
                "measurement_noise_vwc": 0.005}

    @staticmethod
    def _native_nitrogen_zone(records: dict[int, dict[str, Any]]) -> dict[str, Any]:
        """Average complete native coverage without treating unstarted soil as zero."""
        native = [record for record in records.values() if record["status"] == "native"]
        days = {record["native_effective_day"] for record in native}
        if not native:
            status = "not_started"
        elif len(native) != len(records):
            status = "partial_native_coverage"
        elif len(days) != 1:
            status = "mixed_native_days"
        else:
            status = "native"
        reading = {"source": "PCSE_CNB_model_telemetry", "status": status,
                   "coverage_ridges": len(records), "initialized_ridges": len(native),
                   "native_effective_day": next(iter(days)) if status == "native" else None,
                   "nitrogen_state_effective_day": (max(record["nitrogen_state_effective_day"] for record in native)
                                                     if status == "native" else None)}
        for field in ("available_n_kg_ha", "reserve_n_kg_ha", "release_reference_n_kg_ha"):
            reading[field] = (round(sum(record[field] for record in native) / len(native), 4)
                              if status == "native" else None)
        return reading

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def read_soil_sensors(self) -> dict[str, Any]:
        """
        Return readings and actual coverage of this farm's soil probes.

        Each probe reports volumetric water content (vwc) and soil temperature
        (temp_c) at 5 cm depth. The reading represents the average condition
        of the ridges within the sensor's coverage zone.

        Probe count and coverage depend on the configured farm layout.
        Each result includes sensor_id, ridge_start and ridge_end; the
        environment directory supplies the global IDs for single-probe reads.
        """
        self._sync_sensors()
        readings = []
        for sensor in self._soil_sensors:
            reading = dict(sensor)
            reading["vwc"] = round(
                max(0.0, min(1.0, sensor["vwc"] + self.rng.uniform(-0.01, 0.01))),
                4,
            )
            reading["temp_c"] = round(sensor["temp_c"] + self.rng.uniform(-0.3, 0.3), 2)
            readings.append(reading)
        return {"farm_id": self.bound_farm_id, "soil_sensors": readings}

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def read_canopy_sensors(self) -> dict[str, Any]:
        """
        Return readings and actual coverage of this farm's canopy sensors.

        Each sensor reports an ndvi_proxy value (0.0-1.0). A value of -1
        means no valid reading yet (pre-emergence). The reading represents
        the average canopy condition within the sensor's coverage zone.

        Probe count and coverage depend on the configured farm layout.
        Each result includes sensor_id, ridge_start and ridge_end; the
        environment directory supplies the global IDs for single-probe reads.
        """
        self._sync_sensors()
        readings = []
        for sensor in self._canopy_sensors:
            reading = dict(sensor)
            if sensor["ndvi_proxy"] >= 0.0:
                noisy = sensor["ndvi_proxy"] + self.rng.uniform(-0.02, 0.02)
                reading["ndvi_proxy"] = round(max(0.0, min(1.0, noisy)), 3)
            readings.append(reading)
        return {"farm_id": self.bound_farm_id, "canopy_sensors": readings}

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def read_soil_sensor(self, sensor_id: str) -> dict[str, Any]:
        """
        Return the latest reading from a single soil probe.

        Args:
            sensor_id: "S1" through "S6".
        """
        self._sync_sensors()
        sensor = self._find_soil(sensor_id)
        if sensor is None:
            return {"error": f"Unknown sensor_id '{sensor_id}'"}
        reading = dict(sensor)
        reading["vwc"] = round(
            max(0.0, min(1.0, sensor["vwc"] + self.rng.uniform(-0.01, 0.01))), 4
        )
        reading["temp_c"] = round(sensor["temp_c"] + self.rng.uniform(-0.3, 0.3), 2)
        reading["farm_id"] = self.bound_farm_id
        return reading

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def read_canopy_sensor(self, sensor_id: str) -> dict[str, Any]:
        """
        Return the latest reading from a single canopy sensor.

        Args:
            sensor_id: "C1" through "C6".
        """
        self._sync_sensors()
        sensor = self._find_canopy(sensor_id)
        if sensor is None:
            return {"error": f"Unknown sensor_id '{sensor_id}'"}
        reading = dict(sensor)
        if sensor["ndvi_proxy"] >= 0.0:
            noisy = sensor["ndvi_proxy"] + self.rng.uniform(-0.02, 0.02)
            reading["ndvi_proxy"] = round(max(0.0, min(1.0, noisy)), 3)
        reading["farm_id"] = self.bound_farm_id
        return reading

    def update_soil_sensor(
        self, sensor_id: str, vwc: float, temp_c: float
    ) -> dict[str, Any]:
        """
        Update a soil sensor's cached reading.

        Args:
            sensor_id: "S1" through "S6".
            vwc:       Volumetric water content (0.0-1.0).
            temp_c:    Soil temperature at 5 cm depth (°C).
        """
        sensor = self._find_soil(sensor_id)
        if sensor is None:
            return {"error": f"Unknown sensor_id '{sensor_id}'"}
        sensor["vwc"] = float(vwc)
        sensor["temp_c"] = float(temp_c)
        self.is_state_modified = True
        return {"status": "ok", "sensor_id": sensor_id}

    def update_canopy_sensor(self, sensor_id: str, ndvi_proxy: float) -> dict[str, Any]:
        """
        Update a canopy sensor's cached reading.

        Args:
            sensor_id:  "C1" through "C6".
            ndvi_proxy: NDVI proxy value (0.0-1.0, or -1 for no reading).
        """
        sensor = self._find_canopy(sensor_id)
        if sensor is None:
            return {"error": f"Unknown sensor_id '{sensor_id}'"}
        sensor["ndvi_proxy"] = float(ndvi_proxy)
        self.is_state_modified = True
        return {"status": "ok", "sensor_id": sensor_id}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_soil(self, sensor_id: str) -> dict[str, Any] | None:
        for s in self._soil_sensors:
            if s["sensor_id"] == sensor_id:
                return s
        return None

    def _find_canopy(self, sensor_id: str) -> dict[str, Any] | None:
        for s in self._canopy_sensors:
            if s["sensor_id"] == sensor_id:
                return s
        return None

    def _default_soil_sensors(self) -> list[dict[str, Any]]:
        return [
            {
                "sensor_id": f"S{sid}",
                "ridge_id": ridge,
                "ridge_start": start,
                "ridge_end": end,
                "vwc": 0.22,
                "temp_c": 10.0,
            }
            for sid, ridge, start, end in self._sensor_zones
        ]

    def _sync_sensors(self) -> None:
        """Refresh sensor caches from current world state.

        Physics-active mode (preferred): pulls top_vwc / top_temp_c from the
        soil engine's truth, and canopy NDVI from the canopy/biomass engine's
        ndvi_proxy. The orchestrator's compatibility-sync already mirrors
        these onto RidgeState, but reading the engine values directly avoids
        any drift between sync points. Calling advance_physics_time first
        guarantees the agent sees the latest state.

        Legacy mode: averages RidgeState fields by zone, exactly as before.
        """
        zones = self._zones_for_ridges(self._farm_world_app.num_ridges)
        if zones != self._sensor_zones:
            self._sensor_zones = zones
            self._soil_sensors = self._default_soil_sensors()
            self._canopy_sensors = self._default_canopy_sensors()
        environment = self._farm_world_app.farm_environment
        if environment is not None:
            environment.before_tool()
        if self._farm_world_app.physics_active:
            # Sensor reads should report current truth, not initialize physics
            # early. Before the first FARM action has seeded the engines, use
            # the scenario-configured ridge state below; after that, advance
            # idempotently so reads see elapsed-time effects.
            physics = self._farm_world_app.physics
            if physics.last_physics_sim_time is not None:
                self._farm_world_app.advance_physics_time()
                physics = self._farm_world_app.physics
                for s in self._soil_sensors:
                    sid, rs, re = s["sensor_id"], s["ridge_start"], s["ridge_end"]
                    soil_states = [physics.soil.states[r] for r in range(rs, re + 1)]
                    avg_vwc = sum(st.top_vwc for st in soil_states) / len(soil_states)
                    avg_temp = sum(st.top_temp_c for st in soil_states) / len(
                        soil_states
                    )
                    self.update_soil_sensor(sid, avg_vwc, avg_temp)

                for s in self._canopy_sensors:
                    sid, rs, re = s["sensor_id"], s["ridge_start"], s["ridge_end"]
                    canopy_states = [
                        physics.canopy.states[r] for r in range(rs, re + 1)
                    ]
                    # Pre-emergence canopy state has initialized=False; report -1
                    # to match the legacy "no valid reading yet" semantic.
                    if any(not st.initialized for st in canopy_states):
                        self.update_canopy_sensor(sid, -1.0)
                    else:
                        avg_ndvi = sum(st.ndvi_proxy for st in canopy_states) / len(
                            canopy_states
                        )
                        self.update_canopy_sensor(sid, avg_ndvi)
                return

        # Legacy path, also used before physics has been seeded by the first
        # FARM action.
        for s in self._soil_sensors:
            sid, rs, re = s["sensor_id"], s["ridge_start"], s["ridge_end"]
            ridges = [self._farm_world_app.get_ridge(r) for r in range(rs, re + 1)]
            avg_vwc = sum(r.soil_vwc for r in ridges) / len(ridges)
            avg_temp = sum(r.soil_temp_c for r in ridges) / len(ridges)
            self.update_soil_sensor(sid, avg_vwc, avg_temp)
        for s in self._canopy_sensors:
            sid, rs, re = s["sensor_id"], s["ridge_start"], s["ridge_end"]
            ridges = [self._farm_world_app.get_ridge(r) for r in range(rs, re + 1)]
            planted = [r for r in ridges if r.planted]
            if not planted:
                self.update_canopy_sensor(sid, -1.0)
            else:
                avg_ndvi = sum(r.ndvi for r in planted) / len(planted)
                self.update_canopy_sensor(sid, avg_ndvi)

    def _default_canopy_sensors(self) -> list[dict[str, Any]]:
        return [
            {
                "sensor_id": f"C{sid}",
                "ridge_id": ridge,
                "ridge_start": start,
                "ridge_end": end,
                "ndvi_proxy": -1.0,
            }
            for sid, ridge, start, end in self._sensor_zones
        ]
