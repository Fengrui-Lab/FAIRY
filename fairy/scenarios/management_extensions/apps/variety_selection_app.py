"""Pre-sowing choice among unchanged official soybean varieties."""

from copy import deepcopy
from dataclasses import asdict

from fairy.apps.app import App
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered

from ..runtime import PlanningFarm


class VarietySelectionFarm(PlanningFarm):
    """Restore only a declared pre-sowing variety change, preserving the shared-field identity checks."""

    def load_state(self, state):
        saved = state["farm_config"]
        seed = saved.get("cultivar_id")
        if seed is None:
            return super().load_state(state)
        config = self.physics.crop_backend.config
        native = state["physics_state"]["crop_backend_state"]["config"]
        expected = {
            **self.configuration(),
            "crop_id": self._explicit_crop_id,
            "cultivar_id": seed,
        }
        if (
            seed not in config.cultivar_map
            or saved != expected
            or native["variety_name"] != config.cultivar_map[seed]
            or native["cultivar_map"] != config.cultivar_map
        ):
            raise ValueError(
                "Variety checkpoint changes the declared field or official catalogue"
            )
        previous = self._cultivar_id
        self._cultivar_id = seed
        try:
            super().load_state(state)
        except Exception:
            self._cultivar_id = previous
            raise


class VarietySelection(App):
    def __init__(self, farm, tractor, field_specification, varieties):
        super().__init__("VarietySelection")
        self.farm = farm
        self.tractor = tractor
        self.field_specification = field_specification
        self.varieties = deepcopy(varieties)
        self.selected_seed = field_specification["seed_type"]

    def get_state(self):
        return {"selected_seed": self.selected_seed}

    def load_state(self, state):
        seed = state["selected_seed"]
        if seed not in self.varieties:
            raise ValueError("Unknown official variety in checkpoint")
        if self.farm.physics.crop_backend.config.variety_name != self.varieties[seed]:
            raise ValueError("Variety choice and native checkpoint disagree")
        self.selected_seed = seed
        self.field_specification["seed_type"] = seed

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_options(self) -> dict:
        """Read available official varieties and the current selection.

        Returns:
            dict: selected_seed and options with seed_type, official_variety and
            parameters: TSUM1/TSUM2 (degree-days), RDMCR (cm), DEPNR/CFET (unitless).
            Includes source provenance. Varieties differ in phenology; drought
            resistance is not separately calibrated.
        """
        backend = self.farm.physics.crop_backend
        rows = []
        for seed, variety in self.varieties.items():
            parameters = backend._crop_parameters(variety, seed)
            rows.append(
                {
                    "seed_type": seed,
                    "official_variety": variety,
                    "parameters": {
                        k: parameters[k]
                        for k in ("TSUM1", "TSUM2", "DEPNR", "CFET", "RDMCR")
                    },
                }
            )
        return {
            "selected_seed": self.selected_seed,
            "options": rows,
            "source": deepcopy(backend._data_provenance),
            "interpretation": "Official varieties differ in phenology. Compare realized seasonal water use and margin; these are not separately calibrated drought-tolerant lines.",
        }

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def select_variety(self, seed_type: str) -> dict:
        """Select a variety before field preparation or planting.

        Prerequisites:
            No crop growth, preparation or planted ridges; seed hopper empty.
            Soil, area and inventory are preserved; sow separately.

        Args:
            seed_type: Exact options[].seed_type from get_options, e.g. SOYBEAN_901,
                not the official variety name Soybean_901.

        Returns:
            dict: seed_type, official_variety and field_area_m2 (m2).
        """
        if seed_type not in self.varieties:
            raise ValueError("Select a declared official seed")
        if (
            self.farm.physics.crop_backend.has_started
            or self.farm.completed_prep_ops
            or self.tractor._seed_hopper
            or any(r.planted for r in self.farm._ridges)
        ):
            raise ValueError(
                "Variety selection is locked after field work or seed loading"
            )
        options = asdict(self.farm.physics.crop_backend.config)
        options["variety_name"] = self.varieties[seed_type]
        self.farm.configure_crop_backend("wofost", **options)
        self.farm.variety_name = self.varieties[seed_type]
        self.farm._cultivar_id = seed_type
        self.selected_seed = seed_type
        self.field_specification["seed_type"] = seed_type
        return {
            "seed_type": seed_type,
            "official_variety": self.varieties[seed_type],
            "field_area_m2": self.farm.field_area_m2,
        }
