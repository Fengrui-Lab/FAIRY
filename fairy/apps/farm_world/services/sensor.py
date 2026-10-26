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
        """Read modeled root-zone water probes for irrigation decisions.

        Requires active soil physics. These are separate from the 5 cm surface
        probes. Each reading averages its local coverage zone with +/-0.005
        VWC noise. Reading consumes observation randomness, not battery or time.

        Args:
            farm_id: Farm whose configured root-zone probes should be read.

        Returns:
            Receipt with root_zone_sensors (coverage and root_vwc), source
            and measurement_noise_vwc in data.
        """
        return self._execute("read_root_zone_sensors", farm_id=farm_id)

    @service_tool(OperationType.READ, routing=("farm_id",))
    def read_soil_sensors(self, farm_id: FarmId) -> dict[str, Any]:
        """Read all configured 5 cm soil probes in one farm.

        Probe count and coverage follow the actual farm layout. Each VWC
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
        yet. This operation consumes observation randomness without advancing time.

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
        accepted. The noisy reading represents its coverage zone at 5 cm depth.

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
