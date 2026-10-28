"""Public probe readings with explicit farm or globally unique probe IDs."""
from __future__ import annotations

from typing import Any

from fairy.tool_utils import OperationType
from .base import FarmId, SensorId, SharedFarmService, service_tool


class SensorService(SharedFarmService):
    service_name = "Sensor"
    service_kind = "sensor"

    @service_tool(OperationType.READ, routing=("farm_id",))
    def read_root_zone_sensors(self, farm_id: FarmId) -> dict[str, Any]:
        """Read root-zone soil-water estimates for irrigation decisions.

        Each reading averages its coverage zone with +/-0.005 VWC uncertainty.
        These estimates are not an independent shallow measurement. This query
        does not consume battery or advance time.

        Args:
            farm_id: Farm whose configured root-zone probes should be read.

        Returns:
            Receipt with root_zone_sensors (coverage and root_vwc), source
            and measurement_noise_vwc in data.
        """
        return self._execute("read_root_zone_sensors", farm_id=farm_id)

    @service_tool(OperationType.READ, routing=("farm_id",))
    def read_soil_sensors(self, farm_id: FarmId) -> dict[str, Any]:
        """Read configured soil-water and shallow-temperature estimates in one farm.

        Probe count and coverage follow the actual farm layout. Water is for the
        5 cm layer on layered fields; root-zone-only fields report their rooting-layer
        estimate instead of an independent shallow measurement. Each VWC
        and temperature reading includes measurement noise. No time advances.

        Args:
            farm_id: Farm whose configured soil probe zones should be read.

        Returns:
            Receipt with soil_sensors containing local probe IDs, inclusive
            ridge_start/ridge_end coverage, vwc and temp_c in data.
        """
        return self._execute("read_soil_sensors", farm_id=farm_id)

    @service_tool(OperationType.READ, routing=("farm_id",))
    def read_canopy_sensors(self, farm_id: FarmId) -> dict[str, Any]:
        """Read canopy probes and their actual ridge coverage in one farm.

        NDVI proxy readings contain noise; -1 means no valid canopy reading
        yet. This query does not advance time.

        Args:
            farm_id: Farm whose configured canopy probe zones should be read.

        Returns:
            Receipt with canopy_sensors containing local probe IDs,
            ridge_start/ridge_end and ndvi_proxy in data.
        """
        return self._execute("read_canopy_sensors", farm_id=farm_id)

    @service_tool(OperationType.READ)
    def read_soil_sensor(self, sensor_id: SensorId) -> dict[str, Any]:
        """Read one soil probe selected by its globally unique ID.

        Resolve the ID from World, such as maize:S1; unqualified S1 is not
        accepted. The uncertain reading represents its coverage zone: shallow water on layered
        fields, or the rooting-layer estimate on root-zone-only fields.

        Args:
            sensor_id: Global soil probe ID from the environment directory.

        Returns:
            Receipt identifying the farm, with probe ID, local coverage,
            volumetric water content and temperature in data.
        """
        return self._execute("read_soil_sensor", sensor_id=sensor_id)

    @service_tool(OperationType.READ)
    def read_canopy_sensor(self, sensor_id: SensorId) -> dict[str, Any]:
        """Read one canopy probe selected by its globally unique ID.

        Resolve the ID from World, such as maize:C1; unqualified C1 is not
        accepted. NDVI proxy is noisy; -1 means no valid reading yet.

        Args:
            sensor_id: Global canopy probe ID from the environment directory.

        Returns:
            Receipt identifying the farm, with probe ID, local coverage
            and ndvi_proxy in data. This read does not advance time.
        """
        return self._execute("read_canopy_sensor", sensor_id=sensor_id)
