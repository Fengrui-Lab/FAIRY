"""Paddy world and deterministic daily clock adapter for FAIRY."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from fairy.apps.app import App
from fairy.apps.farm_world.weather_app import WeatherApp
from fairy.apps.paddy.models import PaddyField
from fairy.physics.rice_backend import RiceWofostBackend
from fairy.tool_utils import app_tool, OperationType
from fairy.types import event_registered


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class PaddyWorldApp(App):
    simulation_world = True
    crop_name = "rice"

    def __init__(self, *, start_date="2026-01-01", field=None, weather=None):
        super().__init__()
        self.field = PaddyField.from_dict(copy.deepcopy(field)) if field else PaddyField()
        self.start_date = start_date
        self.sim_time = datetime.combine(date.fromisoformat(start_date), datetime.min.time(), timezone.utc).timestamp()
        self.time_manager.reset(self.sim_time)
        self.weather_config = copy.deepcopy(weather or {})
        allowed = {"rain_mm", "overrides"}
        if set(self.weather_config) - allowed:
            raise ValueError("Unsupported paddy weather configuration")
        self.backends = {p.plot_id: RiceWofostBackend(p.unit, start_date, p.soil,
                         self.weather_for(date.fromisoformat(start_date))) for p in self.field.plots}
        self.initial_field = copy.deepcopy(self.field.to_dict())
        self.actions = []
        self.daily_records = []
        self.observations = {}
        self._weather_app = PaddyWeatherApp(self)

    def weather_for(self, day):
        # Fixed synthetic tropical forcing; never labelled station observations.
        result = dict(tmin_c=23., tmax_c=31., humidity_pct=75., rain_mm=float(self.weather_config.get("rain_mm", 3.)),
                      radiation_mj_m2=18., wind_ms=2.)
        result.update(self.weather_config.get("overrides", {}).get(day.isoformat(), {}))
        return result

    def plot(self, plot_id):
        return next((p for p in self.field.plots if p.plot_id == plot_id), None)

    def channel(self, channel_id):
        return next((c for c in self.field.channels if c.channel_id == channel_id), None)

    def machine(self, machine_id):
        result = next((m for m in self.field.machines if m.machine_id == machine_id), None)
        if result is None:
            raise ValueError(f"Unknown machine: {machine_id}")
        return result

    def batch(self, batch_id):
        result = next((b for b in self.field.grain_batches if b.batch_id == batch_id), None)
        if result is None:
            raise ValueError(f"Unknown grain batch: {batch_id}")
        return result

    def sync_grain_totals(self):
        for p in self.field.plots:
            batches = [b for b in self.field.grain_batches if b.plot_id == p.plot_id]
            p.loaded_grain_dry_kg = sum(b.dry_kg for b in batches if b.location == "combine")
            p.unloaded_grain_dry_kg = sum(b.dry_kg for b in batches if b.location == "reception")
            p.stored_dry_kg = sum(b.dry_kg for b in batches if b.location == "stored")
            p.storage_moisture_pct = 14. if p.stored_dry_kg > 0 else None

    def observe(self, key, result):
        report = {"timestamp": self.sim_time, "source": "deterministic_engineering_observation_v2", **result}
        self.observations[key] = copy.deepcopy(report)
        return report

    def configure_crop_backend(self, backend, **options):
        if backend != "wofost" or options:
            raise ValueError("Paddy uses its fixed rice WOFOST profile; field/weather belong to the paddy configuration")

    def prepare_for_time_advance(self, timestamp):
        self.advance_physics_time()

    def advance_physics_time(self):
        # Ignore real wall-clock latency: only explicit scenario time advances
        # drive rice. This makes oracle and checkpoint replay deterministic.
        target = float(self.time_manager.start_time + self.time_manager.offset)
        if target > self.sim_time:
            boundary = (int(self.sim_time) // 86400 + 1) * 86400
            if target >= boundary and any(0 < p.transplanted_area_m2 < p.area_m2 and not p.planted for p in self.field.plots):
                # SystemApp adds its offset before this hook; reject atomically.
                self.time_manager.offset = self.sim_time - self.time_manager.start_time
                raise ValueError("Complete partial transplant work before advancing to another UTC day")
            self.advance_to(target)

    def advance_to(self, target, transfer=None):
        """Split finite jobs at UTC boundaries and meter each elapsed fraction.

        Surface metering is immediate. Soil/crop rates integrate once per
        completed day; intraday soil moisture is explicitly a daily estimate.
        """
        if target < self.sim_time:
            raise ValueError("Paddy time cannot run backwards")
        if (target >= (int(self.sim_time) // 86400 + 1) * 86400 and
                any(0 < p.transplanted_area_m2 < p.area_m2 and not p.planted for p in self.field.plots)):
            raise ValueError("Complete partial transplant work before advancing to another UTC day")
        while self.sim_time < target - 1e-6:
            day = datetime.fromtimestamp(self.sim_time, timezone.utc).date()
            boundary = datetime.combine(day + timedelta(days=1), datetime.min.time(), timezone.utc).timestamp()
            end = min(target, boundary)
            seconds = end - self.sim_time
            if transfer:
                transfer(seconds)
            for p in self.field.plots:
                water = self.backends[p.plot_id].water.ledger()
                if water["surface_water_mm"] > 0 and water["root_vwc"] >= .45:
                    p.soaked_hours += seconds / 3600
            self.sim_time = end
            for p in self.field.plots:
                if p.recovery_timestamp is not None and end >= p.recovery_timestamp:
                    p.stand_fraction = min(1., p.stand_fraction + p.pending_stand_recovery)
                    p.pending_stand_recovery, p.recovery_timestamp = 0., None
            if end == boundary:
                weather = self.weather_for(day)
                for p in self.field.plots:
                    backend = self.backends[p.plot_id]
                    was_mature = backend.maturity is not None
                    if p.bund_leak_mm_day:
                        backend.apply("water", amount_mm=p.bund_leak_mm_day, drain=True, leak=True)
                    if p.planted and not was_mature:
                        for key, growth in (("pests", .035), ("disease", .05 if weather["rain_mm"] > 5 else .018), ("weeds", .025)):
                            value = getattr(p, key)
                            setattr(p, key, min(1., value + growth * value * (1 - value)))
                        factor = p.stand_fraction * max(.2, 1 - .25*p.pests - .35*p.disease - .30*p.weeds)
                        backend.apply("stress", factor=factor)
                    backend.apply("day", day=day.isoformat(), weather=weather)
                    if was_mature and not p.harvested:
                        # Explicit auxiliary dry-down; this is not native WOFOST.
                        p.grain_moisture_pct = min(28., max(12., p.grain_moisture_pct +
                            (1.0 if weather["rain_mm"] > 5 else -.8)))
                        remaining = max(0., p.unit.mass_kg(float(backend.crop_values.get("TWSO") or 0))
                                        - p.harvested_dry_kg - p.harvest_loss_dry_kg - p.field_loss_dry_kg)
                        p.field_loss_dry_kg += remaining * (.006 if weather["rain_mm"] > 5 else .001)
                    self.daily_records.append({"day": day.isoformat(), **backend.snapshot()})

    def run_job(self, seconds, transfer=None):
        self.advance_physics_time()
        self.advance_to(self.sim_time + seconds, transfer)
        self.time_manager.add_offset(seconds)

    def record(self, action, **values):
        self.actions.append({"action": action, "timestamp": self.sim_time, **values})
        self.is_state_modified = True

    def crop_backend_provenance(self):
        result = copy.deepcopy(next(iter(self.backends.values())).provenance)
        result["field"] = copy.deepcopy(self.initial_field)
        result["weather"] = {"kind": "synthetic_tropical_v1", "config": self.weather_config}
        result["start_date"] = self.start_date
        result["management_profile"] = "paddy_operations_v2"
        result["observation_profile"] = "deterministic_rounded_v2; no_native_state_in_agent_tools"
        result["auxiliary_models"] = "biotic_logistic_v1; gap_fill_assimilation_proxy_v1; late_harvest_loss_v1"
        result["config_fingerprint"] = fingerprint(result)
        return result

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_inventory(self) -> dict:
        """Inspect purchased seedlings, machine loading, fuel, water and grain storage."""
        self.advance_physics_time()
        return {"seedlings": copy.deepcopy(vars(self.field.seedlings)),
                "fuel_liters": self.field.fuel_liters,
                "channels": [copy.deepcopy(vars(c)) for c in self.field.channels],
                "stored_kg_at_14pct": sum(p.stored_dry_kg / .86 for p in self.field.plots),
                "storage_capacity_kg": self.field.storage_capacity_kg,
                "fertilizer": {"product_id": "urea", "stock_kg": self.field.fertilizer_kg, "n_fraction": .46},
                "insecticide_liters": self.field.insecticide_liters, "fungicide_liters": self.field.fungicide_liters,
                "repair_material_kg": self.field.repair_material_kg,
                "electricity_kwh": self.field.electricity_kwh,
                "drying_capacity_wet_kg_day": self.field.drying_capacity_wet_kg_day,
                "grain_batches": [{"batch_id": b.batch_id, "plot_id": b.plot_id,
                                   "location": b.location, "wet_kg": round(b.wet_kg, 2)} for b in self.field.grain_batches]}

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_farm_overview(self) -> dict:
        """Read administrative plot status. Use PaddyObservationApp for current field measurements."""
        self.advance_physics_time()
        return {"field_id": self.field.field_id, "date": datetime.fromtimestamp(self.sim_time, timezone.utc).isoformat(),
                "plots": [self._plot_record(p) for p in self.field.plots], "stage_mapping": "management_proxy_v1",
                "operation_limits": {"soak_hours": 24, "transplant_max_water_mm": 30,
                    "row_spacing_cm": 20, "hill_spacing_cm": 20, "seedlings_per_hill": 3,
                    "harvest_max_water_mm": 0.1, "harvest_max_root_vwc": .42,
                    "harvest_allowed_moisture_pct": [14, 28], "harvest_preferred_moisture_pct": [20, 25],
                    "storage_moisture_pct": 14}}

    def _plot_record(self, p):
        return {key: copy.deepcopy(getattr(p, key)) for key in (
            "plot_id", "area_m2", "puddled", "levelled", "planted", "harvested",
            "transplanted_area_m2", "harvested_area_m2", "seedlings_planted", "stored_dry_kg")}

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_plot_state(self, plot_id: str) -> dict:
        """Read plot work records and previously acquired observations, including their timestamps.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
        """
        self.advance_physics_time()
        p = self.plot(plot_id)
        if p is None:
            raise ValueError("Unknown paddy plot")
        return {**self._plot_record(p), "observations": copy.deepcopy({
            k: v for k, v in self.observations.items() if v.get("plot_id") == plot_id})}

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_operation_log(self, plot_id: str | None = None) -> dict:
        """Read completed operations and metered resource use, optionally filtered by plot ID.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview. None selects all applicable plots.
        """
        return {"operations": copy.deepcopy([a for a in self.actions if plot_id is None or a.get("plot_id") == plot_id])}

    def outcome_summary(self):
        self.advance_physics_time()
        units = []
        for p in self.field.plots:
            b = self.backends[p.plot_id]
            bio = p.unit.mass_kg(float(b.crop_values.get("TWSO") or 0))
            units.append({**vars(p.unit), "mature": b.maturity is not None, "harvested": p.harvested,
                          "planted": p.planted, "biological_dry_kg": bio,
                          "harvested_dry_kg": p.harvested_dry_kg,
                          "stored_kg_at_14pct": p.stored_dry_kg / .86,
                          "water": b.water.audit(), "nitrogen": b.nitrogen.audit(),
                          "field_loss_dry_kg": p.field_loss_dry_kg,
                          "machine_loss_dry_kg": p.harvest_loss_dry_kg})
        return {"units": units, "biological_dry_kg": sum(u["biological_dry_kg"] for u in units),
                "harvested_dry_kg": sum(u["harvested_dry_kg"] for u in units),
                "stored_kg_at_14pct": sum(u["stored_kg_at_14pct"] for u in units),
                "resources_used": {"fuel_liters": self.field.fuel_used_liters,
                    "fertilizer_kg": self.field.fertilizer_applied_kg, "electricity_kwh": self.field.energy_used_kwh,
                    "repair_material_kg": self.field.repair_used_kg, **self.field.chemicals_used},
                "inventory": self.get_inventory(), "crop_backend_provenance": self.crop_backend_provenance()}

    def get_state(self):
        self.advance_physics_time()
        state = {"schema": 2, "start_date": self.start_date, "sim_time": self.sim_time,
                 "initial_field": self.initial_field, "field": self.field.to_dict(),
                 "weather": self.weather_config, "actions": self.actions,
                 "daily_records": self.daily_records,
                 "observations": self.observations,
                 "backends": {k: b.export_state() for k, b in self.backends.items()},
                 "provenance": self.crop_backend_provenance()}
        state = copy.deepcopy(state)
        state["sha256"] = fingerprint(state)
        return state

    def load_state(self, payload):
        data = copy.deepcopy(payload)
        digest = data.pop("sha256", None)
        if data.get("schema") != 2 or fingerprint(data) != digest:
            raise ValueError("Paddy checkpoint checksum/schema mismatch")
        if data["provenance"] != self.crop_backend_provenance():
            raise ValueError("Paddy checkpoint configuration mismatch")
        restored = {key: RiceWofostBackend.from_state(value) for key, value in data["backends"].items()}
        self.field = PaddyField.from_dict(data["field"])
        self.backends = restored
        self.sim_time = data["sim_time"]
        self.actions = data["actions"]
        self.daily_records = data["daily_records"]
        self.observations = data["observations"]
        self.time_manager.reset(self.sim_time)

    def reset(self):
        fresh = type(self)(start_date=self.start_date, field=self.initial_field, weather=self.weather_config)
        self.load_state(fresh.get_state())


class PaddyWeatherApp(WeatherApp):
    """Use the existing WeatherApp tools with the same forcing as native rice."""
    def __init__(self, world):
        super().__init__()
        self.world = world

    def get_state(self):
        return {"app_name": self.name, "current": self._current_weather_dict(),
                "forecast": self.get_forecast()["forecast"],
                "source": "synthetic_tropical_v1; state owned by PaddyWorldApp"}

    def load_state(self, state_dict):
        if state_dict != self.get_state():
            raise ValueError("Restore the PaddyWorldApp checkpoint to restore its weather")

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_current_weather(self) -> dict:
        """Read today's weather for this field.
        """
        return self._current_weather_dict()

    def _current_weather_dict(self):
        self.world.advance_physics_time()
        day = datetime.fromtimestamp(self.world.sim_time, timezone.utc).date()
        w = self.world.weather_for(day)
        return {"date": day.isoformat(), "temp_c": (w["tmin_c"] + w["tmax_c"]) / 2,
                "humidity_pct": w["humidity_pct"], "wind_speed_ms": w["wind_ms"],
                "rainfall_mm": w["rain_mm"], "solar_radiation": w["radiation_mj_m2"] / .0864}

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_forecast(self, days: int = 7) -> dict:
        """Read up to seven days of weather forecast for this field.


        Args:
            days: Number of forecast days requested, from 1 to 7.
        """
        self.world.advance_physics_time()
        today = datetime.fromtimestamp(self.world.sim_time, timezone.utc).date()
        forecast = []
        for i in range(1, max(1, min(7, days)) + 1):
            target = today + timedelta(days=i)
            w = self.world.weather_for(target)
            w["rain_mm"] = max(0., w["rain_mm"] + self.world.field.forecast_error_mm * (1 if target.toordinal() % 2 else -1))
            forecast.append({"date": target.isoformat(), **w})
        return {"forecast": forecast, "rain_uncertainty_mm": self.world.field.forecast_error_mm}
