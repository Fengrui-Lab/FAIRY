"""Existing aerial and ground scouting operations on winter wheat blocks."""

from datetime import datetime
from typing import Any

from fairy.apps.farm_world.farm_environment import FarmContext, FarmEnvironment
from fairy.apps.farm_world.shared_drone_app import SharedDroneApp
from fairy.apps.farm_world.shared_robot_app import SharedRobotApp
from fairy.crops.runtime import CropObservationTraits
from fairy.physics import HiddenRidgeTruth, ObservationModel
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered


def _block_ids(farm: FarmContext, start: int, end: int) -> range:
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start <= end < farm.world.num_ridges
    ):
        raise ValueError(f"Invalid block range [{start}, {end}]")
    return range(start, end + 1)


def _observed_at(farm: FarmContext) -> str:
    return datetime.fromtimestamp(
        farm.world.time_manager.time(), farm.world.simulation_timezone
    ).isoformat()


def _crop_status(farm: FarmContext, block: int):
    physics = farm.world.physics
    return physics.crop.project(block, physics.management.states[block])


class _ScoutingMeasurements:
    """Keep observation noise on the existing device RNG stream."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._measurements = ObservationModel()

    @property
    def _observation_model(self) -> ObservationModel:
        self._measurements.rng = self.rng
        return self._measurements

    def get_state(self) -> dict[str, Any]:
        version, internal, gaussian = self.rng.getstate()
        return {
            **super().get_state(),
            "random_state": [version, list(internal), gaussian],
        }

    def load_state(self, state_dict: dict[str, Any]) -> None:
        super().load_state(state_dict)
        if "random_state" in state_dict:
            version, internal, gaussian = state_dict["random_state"]
            self.rng.setstate((version, tuple(internal), gaussian))


class WheatScoutDrone(_ScoutingMeasurements, SharedDroneApp):
    """Survey wheat canopies with the existing drone and optical products."""

    def __init__(self, environment: FarmEnvironment):
        super().__init__(
            environment,
            name="Drone",
            description="Multispectral and thermal scouting of wheat blocks",
            effective_ridges_per_pass=1,
        )
        self.tool_allowlist = {"survey_blocks", "check_status", "charge"}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def survey_blocks(self, start_block: int, end_block: int) -> dict[str, Any]:
        """Fly one pass per wheat block using the shared drone battery and clock.

        Args:
            start_block: First local block ID, inclusive.
            end_block: Last local block ID, inclusive and at least start_block.

        Returns:
            Mission ID, surveyed and uncovered blocks, end-of-flight NDVI and
            thermal proxies (°C), elapsed time and remaining battery. Null
            canopy readings indicate unavailable canopy. Rain, wind or
            charging may refuse flight; low battery may limit coverage.
        """
        farm = self.farm_environment.get_farm("wheat")
        try:
            requested = _block_ids(farm, start_block, end_block)
        except ValueError as exc:
            return {"error": str(exc)}
        self.farm_environment.before_tool()
        result = self._fly_survey(farm, start_block, end_block)
        if "error" in result:
            return result
        covered = result.pop("surveyed_ridges")
        result.pop("warning", None)
        result["observations"] = [
            {
                "block_id": row["ridge_id"],
                "ndvi": row["ndvi"] if row["ndvi"] >= 0 else None,
                "canopy_temp_c": row["canopy_temp_c"] if row["ndvi"] >= 0 else None,
            }
            for row in result["observations"]
        ]
        params = self._observation_model.params
        return {
            **result,
            "observed_at": _observed_at(farm),
            "surveyed_blocks": covered,
            "uncovered_blocks": [block for block in requested if block not in covered],
            "ndvi_std": params.uav_ndvi_noise_std,
            "thermal_std_c": params.thermal_noise_std_c,
        }

    def _observe_pass_via_observation_model(
        self, farm: FarmContext, pass_ridges: list[int]
    ) -> list[dict[str, Any]]:
        physics = farm.world.physics
        threshold = physics.crop.observation_traits.unstressed_root_vwc
        air_temp = farm.weather.get_current_weather_snapshot()["temp_c"]
        truth = {}
        for block in pass_ridges:
            crop = _crop_status(farm, block)
            canopy = physics.canopy.states[block]
            if crop.current_planted and crop.emerged and canopy.initialized:
                root_vwc = physics.soil.states[block].root_vwc
                # Same temperature proxy as the existing ridge survey.
                temp_c = air_temp + 2.0 + max(0.0, threshold - root_vwc) * 25.0
                truth[block] = HiddenRidgeTruth(
                    ridge_id=block, ndvi_proxy=canopy.ndvi_proxy, canopy_temp_c=temp_c
                )
        if not truth:
            return [
                dict(ridge_id=block, ndvi=-1.0, canopy_temp_c=-1.0)
                for block in pass_ridges
            ]
        model = self._observation_model
        day = farm.world.simulation_date()
        ndvi = model.observe_uav_multispectral(day, truth, list(truth), self.name)
        thermal = model.observe_uav_thermal(day, truth, list(truth), self.name)
        return [
            dict(
                ridge_id=block,
                ndvi=ndvi.values.get(block, -1.0),
                canopy_temp_c=thermal.values.get(block, -1.0),
            )
            for block in pass_ridges
        ]


class WheatScoutRobot(_ScoutingMeasurements, SharedRobotApp):
    """Visit wheat blocks with the existing ground robot and leaf meter."""

    def __init__(self, environment: FarmEnvironment):
        super().__init__(
            environment,
            name="Robot",
            description="Near-ground crop checks and sparse leaf readings",
        )
        self.tool_allowlist = {"inspect_blocks", "check_status", "charge"}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def inspect_blocks(self, start_block: int, end_block: int) -> dict[str, Any]:
        """Walk wheat blocks and sample the living canopy at ground level.

        Args:
            start_block: First local block ID, inclusive.
            end_block: Last local block ID, inclusive and at least start_block.

        Returns:
            Covered and uncovered blocks, near-ground stage and noisy SPAD
            proxies, inspection IDs, elapsed time and remaining battery. Each
            block uses one round trip and 20 battery percentage points.
            Missing leaf evidence and unsupported biotic detections are null.
        """
        farm = self.farm_environment.get_farm("wheat")
        try:
            requested = _block_ids(farm, start_block, end_block)
        except ValueError as exc:
            return {"error": str(exc)}
        self.farm_environment.before_tool()
        started_at = self.time_manager.time()
        observations = []
        warning = None
        for block in requested:
            inspection = self._inspect_ridge(farm, block)
            if "error" in inspection:
                if not observations:
                    return inspection
                warning = inspection["error"]
                break
            row = dict(inspection["result"])
            row["block_id"] = row.pop("ridge_id")
            row["inspection_id"] = inspection["inspection_id"]
            row["observed_at"] = _observed_at(farm)
            observations.append(row)
        covered = [row["block_id"] for row in observations]
        return {
            "status": "partial" if warning else "ok",
            "farm_id": farm.farm_id,
            "covered_blocks": covered,
            "uncovered_blocks": [block for block in requested if block not in covered],
            "observations": observations,
            "spad_std": self._observation_model.params.spad_noise_std,
            "duration_s": self.time_manager.time() - started_at,
            "battery_remaining_pct": self._battery_pct,
            **({"warning": warning} if warning else {}),
        }

    def _observe_generic_ridge(
        self, farm: FarmContext, ridge_id: int, traits: CropObservationTraits
    ) -> dict[str, Any]:
        crop = _crop_status(farm, ridge_id)
        spad = None
        if crop.current_planted and crop.emerged:
            native = farm.world.backends[ridge_id].model
            leaf_mass = native.get_variable("WLV")
            leaf_n = native.get_variable("NamountLV")
            dvs = native.get_variable("DVS")
            if (
                native.crop is not None
                and leaf_mass
                and leaf_n is not None
                and dvs is not None
            ):
                maximum_n = native.crop.n_stress.params.NMAXLV_TB(dvs)
                if maximum_n > 0:
                    canopy = farm.world.physics.canopy.states[ridge_id]
                    truth = HiddenRidgeTruth(
                        ridge_id=ridge_id,
                        ndvi_proxy=canopy.ndvi_proxy,
                        nutrient_index=leaf_n / leaf_mass / maximum_n,
                    )
                    spad = self._observation_model.observe_spad(
                        farm.world.simulation_date(),
                        {ridge_id: truth},
                        [ridge_id],
                        self.name,
                    ).values[ridge_id]
        return {
            "ridge_id": ridge_id,
            "growth_stage": crop.stage,
            "emerged": crop.current_planted and crop.emerged,
            "spad_proxy": spad,
            "pest_detected": None,
            "disease_detected": None,
            "weed_detected": None,
        }
