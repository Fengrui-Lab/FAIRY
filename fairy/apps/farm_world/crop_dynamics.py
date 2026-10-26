"""Typed crop integration boundary and explicit biological factory registry.

Shared Apps and the orchestrator depend on this contract. Native model and
legacy-state translations live in separate species adapters. Registering crop
metadata alone never creates biological behavior.
"""
from __future__ import annotations
from datetime import date
from typing import TYPE_CHECKING, Any, Callable, Mapping, Protocol, TypedDict
from fairy.crops.runtime import CropStatus, PlantingEvent, ReplantPlan, CropObservationTraits
from fairy.crops.maize import MaizeParameters
from fairy.apps.farm_world.soybean_dynamics import SoybeanDynamics
from fairy.apps.farm_world.maize_dynamics import MaizeDynamics
from fairy.physics import (
    BioticCropInput, BioticWeatherInput, GrowthWeatherInput, HarvestAction,
    ManagementCropInput, ManagementWeatherInput, PhenologyWeatherInput,
    SoilWeatherInput, YieldWeatherInput,
)
from fairy.physics.management_effect_engine import ManagementEffectState

if TYPE_CHECKING:
    from fairy.apps.farm_world.farm_physics_state import FarmPhysicsState
    from fairy.apps.farm_world.farm_world_app import FarmWorldApp


JSONState = dict[str, Any]
WeatherInputs = TypedDict("WeatherInputs", {
    "management": ManagementWeatherInput, "soil": SoilWeatherInput,
    "phenology": PhenologyWeatherInput, "canopy": GrowthWeatherInput,
    "biotic": BioticWeatherInput, "yield": YieldWeatherInput,
})


class CropDynamics(Protocol):
    """Bridge one crop model to the environment without owning its engines."""
    observation_traits: CropObservationTraits

    max_recoverable_yield_g_m2: float

    def apply_seed_growth_overrides(self, physics: FarmPhysicsState, overrides: Mapping[str, Mapping[str, float]]) -> None: ...
    def validate_planting(self, event: PlantingEvent) -> None: ...
    def plant(self, event: PlantingEvent) -> None: ...
    def prepare_replant(self, event: PlantingEvent, management_states: Mapping[int, ManagementEffectState], full_replant: bool) -> ReplantPlan: ...
    def apply_replant(self, plan: ReplantPlan, management_states: Mapping[int, ManagementEffectState]) -> None: ...
    def project(self, ridge_id: int, management: ManagementEffectState) -> CropStatus: ...
    def initialize_from_ridges(self, world: FarmWorldApp, target_sim_time: float) -> None: ...
    def management_inputs(self, physics: FarmPhysicsState) -> dict[int, ManagementCropInput]: ...
    def biotic_inputs(self, physics: FarmPhysicsState) -> dict[int, BioticCropInput]: ...
    def advance_before_biotics(
        self, world: FarmWorldApp, physics: FarmPhysicsState, day: date, weather: WeatherInputs,
    ) -> dict[int, float] | None:
        """Grow the crop; return today's g/m² increments for deferred uptake.

        None keeps crops that already supply uptake through management_inputs
        on their existing accounting path. The orchestrator owns settlement.
        """
        ...
    def advance_after_biotics(self, physics: FarmPhysicsState, day: date, weather: WeatherInputs, harvest_actions: Mapping[int, HarvestAction]) -> None: ...
    def settle_harvest(self, physics: FarmPhysicsState, day: date, weather: WeatherInputs, harvest_actions: Mapping[int, HarvestAction]) -> None: ...
    def sync_public_fields(self, world: FarmWorldApp) -> None: ...
    def get_state(self) -> JSONState: ...
    def load_state(self, state: JSONState) -> None: ...

# Construction is the sole species selection point. Metadata and biological
# factories are explicit registrations; a name alone never invents a model.
_DYNAMICS_FACTORIES = {"soybean": SoybeanDynamics, "maize": MaizeDynamics}
_OBSERVATION_TRAITS = {
    "soybean": SoybeanDynamics.observation_traits,
    "maize": CropObservationTraits(MaizeParameters().unstressed_root_vwc, None, None),
}


def register_crop_dynamics(crop_id: str, factory: Callable[[int], CropDynamics], *, observation_traits: CropObservationTraits) -> None:
    if crop_id in _DYNAMICS_FACTORIES:
        raise ValueError(f"Crop dynamics {crop_id!r} is already registered")
    _DYNAMICS_FACTORIES[crop_id] = factory
    _OBSERVATION_TRAITS[crop_id] = observation_traits


def get_crop_observation_traits(crop_id: str) -> CropObservationTraits:
    return _OBSERVATION_TRAITS[crop_id]


def create_crop_dynamics(crop_id: str, num_ridges: int) -> CropDynamics:
    try:
        factory = _DYNAMICS_FACTORIES[crop_id]
    except KeyError:
        raise ValueError(f"Unsupported crop dynamics {crop_id!r}") from None
    return factory(num_ridges)
