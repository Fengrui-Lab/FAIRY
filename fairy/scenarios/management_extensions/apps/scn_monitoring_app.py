"""Public SCN soil diagnostics and the matching rotation-world checkpoint codec."""

from dataclasses import asdict

from fairy.apps.app import App
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered

from ..engines.soybean_cyst_nematode import SoybeanCystNematodeBackend
from .crop_rotation_farm_app import CropRotationFarm


class ScnRotationFarm(CropRotationFarm):
    def _restore_crop_backend(self, payload):
        if payload.get("scn_model", {}).get("parameters") != asdict(
            self.physics.crop_backend.scn_parameters
        ):
            raise ValueError(
                "SCN checkpoint changes this scenario's declared assumptions"
            )
        return SoybeanCystNematodeBackend.from_state(payload)


class ScnMonitoring(App):
    def __init__(self, farm):
        super().__init__("ScnMonitoring")
        self.farm = farm

    def get_state(self):
        return {"schema": 1}

    def load_state(self, state):
        if state != {"schema": 1}:
            raise ValueError("Unsupported SCN monitoring checkpoint")

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def sample_soil(self) -> dict:
        """Read simulated soybean-cyst-nematode populations at the current time.

        Returns:
            dict: ISO date, current crop and ridges with zero-based ridge_id and
            eggs_per_100cc (eggs/100 cm3 soil). Includes host roles, model_parameters
            and source. These are simulated populations with declared reproduction
            and survival assumptions, not field lab measurements. No time advance.
        """
        self.farm.advance_physics_time()
        backend = self.farm.physics.crop_backend
        parameters = backend.scn_parameters
        return {
            "date": self.farm.simulation_date(self.time_manager.time()).isoformat(),
            "crop": self.farm.crop_type,
            "soybean_is_host": True,
            "maize_is_nonhost": True,
            "ridges": [
                {
                    "ridge_id": r,
                    "eggs_per_100cc": backend.scn_population.get(
                        r, parameters.initial_eggs_per_100cc
                    ),
                }
                for r in range(self.farm.num_ridges)
            ],
            "model_parameters": asdict(parameters),
            "measurement_scope": "Exact simulated soil population, not a field laboratory measurement; reproduction, persistence and loss coefficients are uncalibrated simulation assumptions",
            "source": "https://extension.umn.edu/agriculture/crop-production/soybean/soybean-cyst-nematode-management-guide",
        }
