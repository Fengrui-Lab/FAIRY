"""Farm ownership and one shared clock for a scene containing several farms.

This module does not expose tools. A fixed installation holds one FarmContext;
a mobile tool selects a FarmContext by its explicit ``farm_id`` argument.
Weather inputs are shared because this first two-farm scene uses one region.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from math import isfinite
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from fairy.time_manager import SimulationTimeManager, TimeManager

if TYPE_CHECKING:
    from fairy.apps.farm_world.farm_world_app import FarmWorldApp
    from fairy.apps.farm_world.weather_app import WeatherApp
    from fairy.apps.farm_world.warehouse_app import WarehouseApp


@dataclass
class FarmContext:
    """One farm's state and permanently installed equipment.

    ``legacy_clock`` only supports existing single-farm device wrappers. In a
    FarmEnvironment every operation uses the environment's common clock.
    """

    farm_id: str
    world: FarmWorldApp
    weather: WeatherApp
    sensors: Any | None = None
    irrigation: Any | None = None
    environment: FarmEnvironment | None = field(default=None, repr=False)
    legacy_clock: TimeManager | None = field(default=None, repr=False)

    def advance_time(self, seconds: float) -> None:
        """Charge an operation's duration to the scene's clock once."""
        environment = self.environment or self.world.farm_environment
        if environment is not None:
            environment.advance_time(seconds)
        else:
            clock = self.legacy_clock or self.world.time_manager
            clock.add_offset(seconds)


class FarmEnvironment:
    """Keep farm state independent while advancing every farm together.

    A scenario explicitly creates this object and gives it to Engine as
    ``scenario.farm_environment``. It binds one common warehouse; sensors and
    irrigation belong to each FarmContext, while mobile Apps own their tanks,
    batteries and logs. A single legacy farm can retain its inventory adapter.
    """

    def __init__(
        self,
        farms: list[FarmContext],
        weather: WeatherApp,
        time_manager: TimeManager | None = None,
        *,
        start_time: float | None = None,
        timezone_name: str = "UTC",
        warehouse: WarehouseApp | None = None,
    ) -> None:
        if time_manager is None and start_time is None:
            raise ValueError("FarmEnvironment requires a scene start_time or an explicit clock")
        if time_manager is not None and start_time is not None:
            raise ValueError("Provide either a scene start_time or an explicit clock, not both")
        if not farms:
            raise ValueError("FarmEnvironment requires at least one farm")
        if len(farms) > 1 and warehouse is None:
            raise ValueError("Multiple farms require one explicitly configured common WarehouseApp")
        if warehouse is not None and warehouse.environment is not None:
            raise ValueError("Warehouse already belongs to an environment")
        self.farms: dict[str, FarmContext] = {}
        worlds: set[int] = set()
        for farm in farms:
            if not farm.farm_id or farm.farm_id in self.farms:
                raise ValueError(f"Duplicate or empty farm_id: {farm.farm_id!r}")
            if id(farm.world) in worlds:
                raise ValueError("Each farm must have a separate FarmWorldApp")
            if farm.world.farm_environment is not None:
                raise ValueError(f"Farm world {farm.farm_id!r} already has an environment")
            if farm.weather is not weather:
                raise ValueError("This environment requires one common WeatherApp")
            if farm.environment is not None and farm.environment is not self:
                raise ValueError(f"Farm {farm.farm_id!r} already has an environment")
            self.farms[farm.farm_id] = farm
            worlds.add(id(farm.world))
        self.weather = weather
        self.warehouse = warehouse
        self.simulation_timezone = ZoneInfo(timezone_name)
        self.time_manager = time_manager or SimulationTimeManager()
        if start_time is not None:
            self.time_manager.reset(start_time)
        self._validate_clock_not_before_physics(self.time_manager)
        self.weather.simulation_timezone = self.simulation_timezone
        self._syncing = False
        self._daily_weather: dict[date, dict[str, Any]] = {}
        if self.warehouse is not None:
            self.warehouse.bind_environment(self)
        for farm in farms:
            farm.environment = self
            farm.world.farm_id = farm.farm_id
            farm.world.farm_environment = self
            if self.warehouse is not None:
                # A bound field cannot retain a second, hidden stock ledger.
                farm.world._legacy_inventory = None
            farm.world.simulation_timezone = self.simulation_timezone
            farm.world.attach_weather_app(weather)
        self.register_time_manager(self.time_manager)

    def get_farm(self, farm_id: str) -> FarmContext:
        """Resolve an explicit farm ID without changing any device binding."""
        try:
            return self.farms[farm_id]
        except KeyError:
            raise ValueError(
                f"Unknown farm_id {farm_id!r}; choose one of {list(self.farms)}"
            ) from None

    def register_time_manager(self, time_manager: TimeManager) -> None:
        """Bind the scene clock to all farms and fixed installations."""
        self._validate_clock_not_before_physics(time_manager)
        self.time_manager = time_manager
        self.weather.register_time_manager(time_manager)
        if self.warehouse is not None:
            self.warehouse.register_time_manager(time_manager)
        for farm in self.farms.values():
            farm.world.register_time_manager(time_manager)
            for installation in (farm.sensors, farm.irrigation):
                if installation is not None:
                    installation.register_time_manager(time_manager)

    def _validate_clock_not_before_physics(self, time_manager: TimeManager) -> None:
        """Reject time travel before changing any farm or equipment binding."""
        initialized_times = [
            farm.world._physics.last_physics_sim_time
            for farm in self.farms.values()
            if farm.world._physics is not None
            and farm.world._physics.last_physics_sim_time is not None
        ]
        if initialized_times and time_manager.time() < max(initialized_times):
            raise ValueError("Cannot bind a clock earlier than initialized farm physics")

    def before_tool(self) -> dict[str, dict[str, Any]]:
        """Synchronize every registered farm before reading or taking action."""
        return self.sync()

    def sync(self, target_sim_time: float | None = None) -> dict[str, dict[str, Any]]:
        """Run every farm's physical state up to one common timestamp."""
        if self._syncing:
            return {}
        target = (
            float(self.time_manager.time())
            if target_sim_time is None
            else float(target_sim_time)
        )
        if any(
            farm.world._physics is not None
            and farm.world._physics.last_physics_sim_time is not None
            and target < farm.world._physics.last_physics_sim_time
            for farm in self.farms.values()
        ):
            raise ValueError("Cannot synchronize farm physics backwards")
        self._syncing = True
        try:
            results = {
                farm_id: farm.world._advance_physics_time_local(target)
                for farm_id, farm in self.farms.items()
            }
            # These native worlds settle yesterday's forcing at midnight.  The
            # common station must still publish today's working conditions,
            # including before sowing and on idempotent same-time reads.  This
            # projection neither integrates a crop day nor fills the daily
            # biological-input cache; its current day may already be cached.
            if any(
                farm.world._physics is not None
                and farm.world._physics.engines_active
                and farm.world._physics.crop_backend_name == "wofost"
                and (getattr(farm.world._physics, "scenario_metadata", None) or {}).get("daily_settlement")
                == "completed_calendar_day"
                for farm in self.farms.values()
            ):
                from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs

                source = next(farm.world._physics for farm in self.farms.values()
                              if farm.world.physics_active)
                _build_weather_inputs(
                    self.weather,
                    datetime.fromtimestamp(target, self.simulation_timezone).date(),
                    physics=source,
                    advance_weather=False,
                    update_soil_vwc=False,
                    align_date_to_tick=True,
                )
            return results
        finally:
            self._syncing = False

    def advance_time(self, seconds: float) -> dict[str, dict[str, Any]]:
        """Advance the clock once and evolve all farms, including idle farms."""
        seconds = float(seconds)
        if not isfinite(seconds) or seconds < 0:
            raise ValueError("Time advance must be finite and non-negative")
        # Seed every farm before the jump so none loses its first day.
        self.sync()
        self.time_manager.add_offset(seconds)
        return self.sync()

    def weather_inputs(self, day: date, advance_weather: bool) -> dict[str, Any]:
        """Build one common set of engine inputs for each day.

        The first active farm supplies the scenario's regional weather profile.
        Other farms reuse these exact inputs; they cannot consume another
        forecast day or overwrite the station with its soil moisture.
        """
        from fairy.apps.farm_world.physics_orchestrator import _build_weather_inputs

        if day in self._daily_weather:
            return self._daily_weather[day]
        source_physics = next(
            (
                farm.world._physics
                for farm in self.farms.values()
                if farm.world.physics_active
            ),
            None,
        )
        inputs = _build_weather_inputs(
            self.weather,
            day,
            physics=source_physics,
            advance_weather=advance_weather,
            update_soil_vwc=False,
            align_date_to_tick=True,
        )
        if advance_weather:
            self._daily_weather[day] = inputs
        return inputs
