"""Bind tractor operations to crop rules, configured equipment and field scope.

There are no species branches here. A new registered crop supplies its typed
rules; the same operation contracts publish and validate its parameters.
Current weather, resource accounting and physical changes stay in operations.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Mapping

from fairy.apps.farm_world.equipment import TractorEquipment
from fairy.crops.rules import PlantingRules, ScalarRange
from fairy.tool_contracts import OperationContract, ParameterContract

if TYPE_CHECKING:
    from fairy.apps.farm_world.farm_world_app import FarmWorldApp


@dataclass(frozen=True)
class TractorContractContext:
    farms: Callable[[], Mapping[str, FarmWorldApp]]
    equipment: Callable[[], TractorEquipment]
    seed_types: Callable[[], tuple[str, ...]]
    has_farm_selector: bool = False

    def target_world(self, arguments: Mapping[str, Any]) -> FarmWorldApp | None:
        farms = self.farms()
        if self.has_farm_selector:
            return farms.get(arguments.get("farm_id"))
        return next(iter(farms.values()))


def _farm_rules(context: TractorContractContext, render: Callable[[FarmWorldApp], str]) -> str:
    return " ".join(
        f"{farm_id} ({world.crop_id}): {render(world)}"
        for farm_id, world in context.farms().items()
    )


def _range_parameters(context: TractorContractContext) -> dict[str, ParameterContract]:
    maximum = max(world.num_ridges for world in context.farms().values()) - 1
    return {
        "start_ridge": ParameterContract("First local ridge in the target farm, inclusive.", numeric=ScalarRange(0, maximum)),
        "end_ridge": ParameterContract("Last local ridge in the target farm, inclusive; respect the pass limit.", numeric=ScalarRange(0, maximum)),
    }


def _range_error(context: TractorContractContext, arguments: Mapping[str, Any], limit: int) -> str | None:
    world = context.target_world(arguments)
    if world is None:
        return "A registered target farm_id is required"
    start, end = arguments["start_ridge"], arguments["end_ridge"]
    if not 0 <= start <= end < world.num_ridges:
        return f"Invalid ridge range [{start}, {end}] for farm {world.farm_id!r}"
    if end - start + 1 > limit:
        return f"Range cannot exceed {limit} ridges per pass"
    return None


def _planting_rules(world: FarmWorldApp, replant: bool) -> PlantingRules:
    definition = world.crop_definition
    return ((definition.replanting_rules or definition.planting_rules)
            if replant else definition.planting_rules)


def _combined_depth_range(context: TractorContractContext, replant: bool) -> ScalarRange:
    """Publish an envelope; runtime resolves the exact selected farm's rule."""
    bounds = [_planting_rules(world, replant).depth_cm for world in context.farms().values()]
    minimum = None if any(rule.minimum is None for rule in bounds) else min(rule.minimum for rule in bounds)
    maximum = None if any(rule.maximum is None for rule in bounds) else max(rule.maximum for rule in bounds)
    minimum_inclusive = any(rule.minimum_inclusive for rule in bounds if rule.minimum == minimum)
    maximum_inclusive = any(rule.maximum_inclusive for rule in bounds if rule.maximum == maximum)
    return ScalarRange(minimum, maximum, minimum_inclusive, maximum_inclusive)


def planting_contract(context: TractorContractContext, *, replant: bool = False) -> OperationContract:
    equipment = context.equipment()
    spacing_name = "spacing_cm" if replant else "seed_spacing_cm"
    parameters = _range_parameters(context)
    parameters["depth_cm"] = ParameterContract(
        "Sowing depth in cm; use the selected farm's crop range below.", numeric=_combined_depth_range(context, replant),
    )
    parameters[spacing_name] = ParameterContract(
        "Positive in-row seed spacing in cm; resulting density must satisfy the target crop's rule.",
        numeric=ScalarRange(minimum=0, minimum_inclusive=False),
    )

    def describe(world):
        rules = _planting_rules(world, replant)
        implement = (f"attached '{rules.required_implement}'" if rules.required_implement is not None
                     else "no additional crop-specific implement restriction")
        temperature = rules.soil_temperature_c.describe("°C")
        exceptions = "; ".join(
            f"{seed}: {rule.describe('°C')}" for seed, rule in rules.soil_temperature_by_seed
        )
        density = (f" Density {rules.density_plants_m2.describe('plants/m²')}."
                   if rules.density_plants_m2 is not None else "")
        replanting = (f" Supported replant modes: {', '.join(rules.supported_replant_modes)}. "
                     "full_replant=True restarts the target ridge's season."
                     if replant else "")
        preparation = (f"completed preparation: {', '.join(rules.required_preparation)}"
                       if rules.required_preparation else "no preparation prerequisite")
        window = ("Scenario planting windows apply." if rules.respect_scenario_window
                  else "No scenario planting-window restriction applies to this operation.")
        return (
            f"requires {implement}; {preparation}. "
            f"Depth {rules.depth_cm.describe('cm')}; target-block average soil temperature {temperature}"
            f"{f' (seed exceptions: {exceptions})' if exceptions else ''}; "
            f"target-block average soil VWC {rules.soil_vwc.describe()}. "
            f"Seed use follows {world.field_length_m:g} m ridge length and "
            f"{world.rows_per_ridge} planted row(s) per ridge.{density} {window}{replanting}"
        )

    def validate(arguments):
        error = _range_error(context, arguments, equipment.planting_max_ridges_per_pass)
        if error is not None:
            return error
        world = context.target_world(arguments)
        rules = _planting_rules(world, replant)
        error = rules.validate_parameters(arguments["depth_cm"], arguments[spacing_name])
        if error is None and rules.density_plants_m2 is not None:
            try:
                density = (world.plants_per_ridge_from_spacing(arguments[spacing_name])
                           / world.field_geometry.ridge_area_m2)
            except (OverflowError, ValueError, ZeroDivisionError):
                return "Seed spacing produces an invalid planting density"
            error = rules.density_plants_m2.validate(density, "Planting density (plants/m²)")
        return error

    return OperationContract(
        f"{'Replant' if replant else 'Sow'} the target field; up to "
        f"{equipment.planting_max_ridges_per_pass} contiguous ridges per pass. "
        + _farm_rules(context, describe),
        parameters, validate,
    )


def harvest_contract(context: TractorContractContext) -> OperationContract:
    equipment = context.equipment()

    def describe(world):
        rules = world.crop_definition.harvest_rules
        implement = (f"attached '{rules.required_implement}'; " if rules.required_implement is not None else "")
        return (f"requires {implement}mature stage {', '.join(rules.stage_codes)} and grain moisture "
                f"<= {rules.max_moisture_pct:g}%. ")

    return OperationContract(
        f"Harvest up to {equipment.harvest_max_ridges_per_pass} contiguous ridges per pass. "
        "Requires dry weather, trafficable soil, fuel and grain-bin capacity. "
        + _farm_rules(context, describe),
        _range_parameters(context),
        lambda arguments: _range_error(context, arguments, equipment.harvest_max_ridges_per_pass),
    )


def seed_loading_contract(context: TractorContractContext) -> OperationContract:
    return OperationContract(
        "Transfer the selected seed from the bound warehouse into this tractor's seed hopper. "
        "The hopper holds one seed type at a time; field crop compatibility is checked when sowing.",
        {
            "seed_type": ParameterContract("Seed identity accepted by this loading point.", choices=context.seed_types()),
            "count": ParameterContract("Positive seed count; transfer is capped by hopper capacity.", numeric=ScalarRange(minimum=0, minimum_inclusive=False)),
        },
    )


def attachment_contract(context: TractorContractContext) -> OperationContract:
    return OperationContract(
        "Attach one implement actually owned by this tractor. Detach the currently mounted "
        "implement before switching; crop requirements do not create equipment.",
        {"implement": ParameterContract("Owned implement to mount.", choices=context.equipment().implements)},
    )


def ridging_contract(context: TractorContractContext) -> OperationContract:
    implement = context.equipment().ridging_implement
    capability = f"attached '{implement}'" if implement is not None else "this tractor's built-in ridging capability"
    widths = tuple(dict.fromkeys(world.field_geometry.ridge_width_m for world in context.farms().values()))

    def validate(arguments):
        world = context.target_world(arguments)
        if world is None:
            return "A registered target farm_id is required"
        if arguments["ridge_width_m"] != world.field_geometry.ridge_width_m:
            return f"ridge_width_m must match the configured field spacing {world.field_geometry.ridge_width_m:g} m"
        return None

    return OperationContract(
        f"Form ridges using {capability}. "
        "An existing planted crop must be terminated through an explicit supported operation first; "
        "this operation cannot silently erase a crop. The spacing must equal the selected field's configured geometry. "
        + _farm_rules(context, lambda world: f"ridge spacing {world.field_geometry.ridge_width_m:g} m."),
        {"ridge_width_m": ParameterContract("Configured target-field ridge spacing in metres.", choices=widths)},
        validate,
    )


def tractor_operation_contract(context: TractorContractContext, method_name: str) -> OperationContract | None:
    """Operation dispatch is independent of species; each builder has one job."""
    builders = {
        "plant_seeds": planting_contract,
        "replant_seeds": lambda value: planting_contract(value, replant=True),
        "harvest": harvest_contract,
        "load_seeds": seed_loading_contract,
        "attach_implement": attachment_contract,
        "form_ridges": ridging_contract,
    }
    builder = builders.get(method_name)
    if builder is None:
        return None
    contract = builder(context)
    if context.has_farm_selector and method_name in {"plant_seeds", "replant_seeds", "harvest", "form_ridges"}:
        parameters = dict(contract.parameters)
        parameters["farm_id"] = ParameterContract(
            "Registered target farm; all ridge IDs and crop rules are local to it.",
            choices=tuple(context.farms()),
        )
        contract = OperationContract(contract.description, parameters, contract.validator)
    return contract
