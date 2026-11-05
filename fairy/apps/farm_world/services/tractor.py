"""Explicit farm/tractor operations. Agricultural implementation lives below
the runtime executor; these methods declare the complete public contract.
"""
from __future__ import annotations

from typing import Annotated, Any

from fairy.apps.farm_world.models import SeedType
from fairy.apps.farm_world.tractor_app import ATTACHMENTS
from fairy.tool_utils import OperationType, ToolParameter
from .base import (AssetId, Centimeters, FarmId, KgPerRidge, Kilograms, Liters,
                   LitersPerRidge, Meters, RidgeId, SharedFarmService, service_tool)


class TractorService(SharedFarmService):
    service_name = "Tractor"
    service_kind = "tractor"
    asset_kind = "tractor"

    @service_tool(OperationType.WRITE, routing=("asset_id",))
    def attach_implement(
        self, asset_id: AssetId,
        implement: Annotated[str, ToolParameter(enum=tuple(ATTACHMENTS))],
    ) -> dict[str, Any]:
        """Attach a configured implement to one tractor without advancing time.

        A different attached implement must be detached first. No farm target
        is selected and no field preparation is performed by attachment.

        Args:
            asset_id: Physical tractor ID whose implement will change.
            implement: Exact configured implement name from the parameter enum.

        Returns:
            Receipt with attached_implement in data, or a rejection if occupied.
        """
        return self._execute("attach_implement", asset_id=asset_id, implement=implement)

    @service_tool(OperationType.WRITE, routing=("asset_id",))
    def detach_implement(self, asset_id: AssetId) -> dict[str, Any]:
        """Remove one tractor's current implement without advancing time.

        Requires an attached implement. Device payload remains aboard.

        Args:
            asset_id: Physical tractor ID; no farm target is required.

        Returns:
            Receipt with the detached implement name in data.
        """
        return self._execute("detach_implement", asset_id=asset_id)

    @service_tool(OperationType.READ, routing=("asset_id",))
    def get_status(self, asset_id: AssetId) -> dict[str, Any]:
        """Read one tractor's resources, attachment and payload provenance.

        Does not choose a farm or advance time. Crop-specific harvest limits
        are available from World.get_capabilities for the intended farm.

        Args:
            asset_id: Physical tractor ID whose persistent state should be read.

        Returns:
            Receipt with fuel, fertilizer, pesticide, seed hopper, grain bin,
            attachment, harvest setting, payload_origin_farm_id and last_farm_id in data.
        """
        return self._execute("get_status", asset_id=asset_id)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def refuel(self, farm_id: FarmId, asset_id: AssetId, liters: Liters) -> dict[str, Any]:
        """Transfer fuel from an explicit farm's stock into one tractor.

        Requires eligible farm/asset association, compatible current payload
        origin and enough farm fuel for the capacity-limited transfer.
        Transfers at most free tank capacity. Does not advance time.

        Args:
            farm_id: Farm supplying fuel from its own warehouse.
            asset_id: Physical tractor ID to refuel.
            liters: Positive requested fuel transfer in L; limited by free capacity.

        Returns:
            Receipt with updated fuel_tank_l or an already-full message in data.
        """
        return self._execute("refuel", farm_id=farm_id, asset_id=asset_id, liters=liters)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def load_seeds(
        self, farm_id: FarmId, asset_id: AssetId,
        seed_type: Annotated[str, ToolParameter(enum=tuple(seed.value for seed in SeedType))],
        count: Annotated[int, ToolParameter(exclusive_minimum=0, unit="seeds")],
    ) -> dict[str, Any]:
        """Transfer crop-compatible seeds from one farm into the tractor hopper.

        Requires eligible association, compatible payload origin, enough farm
        stock and either an empty hopper or the same seed type. Transfer is
        limited by free hopper capacity. No time advances; planting is separate.

        Args:
            farm_id: Farm supplying seeds; its crop must match seed_type.
            asset_id: Physical tractor ID receiving the seeds.
            seed_type: Compatible seed identifier from this farm's capabilities.
            count: Positive requested number of seeds, limited by free hopper space.

        Returns:
            Receipt with loaded seed_type and total seed_hopper count, or an
            already-full message, in data.
        """
        return self._execute("load_seeds", farm_id=farm_id, asset_id=asset_id, seed_type=seed_type, count=count)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def load_fertilizer(self, farm_id: FarmId, asset_id: AssetId, kg: Kilograms) -> dict[str, Any]:
        """Move farm fertilizer into a tractor spreader without applying it.

        Requires eligible association, compatible payload origin and enough
        warehouse stock for the capacity-limited transfer. Application quota
        is charged when fertilizer is applied, not when loaded. No time advances.

        Args:
            farm_id: Farm supplying fertilizer from its own warehouse.
            asset_id: Physical tractor ID receiving the fertilizer.
            kg: Positive requested fertilizer mass in kg, limited by free capacity.

        Returns:
            Receipt with total fertilizer_spreader_kg or an already-full message in data.
        """
        return self._execute("load_fertilizer", farm_id=farm_id, asset_id=asset_id, kg=kg)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def load_pesticide(self, farm_id: FarmId, asset_id: AssetId, liters: Liters) -> dict[str, Any]:
        """Load the tractor pesticide tank from an explicit farm's chemical stock.

        Requires eligible association, compatible payload origin and enough
        warehouse stock. Fills at most free tank capacity without advancing
        time. This tank supplies insecticide and herbicide operations.

        Args:
            farm_id: Farm supplying the warehouse chemical.
            asset_id: Physical tractor ID receiving chemical.
            liters: Positive requested chemical volume in L, limited by free capacity.

        Returns:
            Receipt with total pesticide_tank_l or an already-full message in data.
        """
        return self._execute("load_pesticide", farm_id=farm_id, asset_id=asset_id, liters=liters)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def load_fungicide(self, farm_id: FarmId, asset_id: AssetId, liters: Liters) -> dict[str, Any]:
        """Load the separate fungicide tank from one farm's chemical stock.

        Uses the farm's pesticide_liters warehouse pool but fills a separate
        onboard tank. Requires eligible association, compatible payload origin
        and enough stock. Transfer is capacity-limited and does not advance time.

        Args:
            farm_id: Farm supplying fungicide from its warehouse chemical pool.
            asset_id: Physical tractor ID receiving fungicide.
            liters: Positive requested fungicide volume in L, limited by free capacity.

        Returns:
            Receipt with total fungicide_tank_l or an already-full message in data.
        """
        return self._execute("load_fungicide", farm_id=farm_id, asset_id=asset_id, liters=liters)

    @service_tool(OperationType.WRITE, routing=("asset_id",))
    def return_supplies(self, asset_id: AssetId) -> dict[str, Any]:
        """Return unused seed, fertilizer and chemicals to their recorded origin.

        Resolve the destination from asset provenance, not the last selected
        farm. Empties these onboard supplies without refunding actual usage or
        advancing time. Does not unload grain or return fuel. Call before
        changing farms when supplies remain; no supplies is a successful no-op.

        Args:
            asset_id: Physical tractor ID whose unused supplies should be returned.

        Returns:
            Receipt with returned quantities and origin_farm_id when supplies
            existed, or an empty returned mapping when already empty, in data.
        """
        return self._execute("return_supplies", asset_id=asset_id)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def level(self, farm_id: FarmId, asset_id: AssetId) -> dict[str, Any]:
        """Level the entire selected farm using the attached grader.

        Requires the grader, trafficable local soil, sufficient fuel and
        compatible asset eligibility/payload. Consumes fuel, advances shared
        time and records preparation on this farm, not on the machine.

        Args:
            farm_id: Farm whose whole configured field should be levelled.
            asset_id: Physical tractor ID with the grader attached.

        Returns:
            Receipt with implement, working width, duration and remaining fuel in data.
        """
        return self._execute("level", farm_id=farm_id, asset_id=asset_id)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def base_fertilize(self, farm_id: FarmId, asset_id: AssetId) -> dict[str, Any]:
        """Apply the configured full-field base fertilizer dose to one farm.

        Requires fertilizer aboard, fuel, trafficable local soil and remaining
        farm fertilizer allowance. Uses an area-scaled dose, consumes resources,
        advances shared time and records this farm's preparation step.

        Args:
            farm_id: Farm receiving base fertilizer and charged for fertilizer usage.
            asset_id: Physical tractor ID carrying fertilizer from this farm.

        Returns:
            Receipt with fertilizer_used_kg, duration_minutes and remaining fuel in data.
        """
        return self._execute("base_fertilize", farm_id=farm_id, asset_id=asset_id)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def form_ridges(self, farm_id: FarmId, asset_id: AssetId, ridge_width_m: Meters) -> dict[str, Any]:
        """Prepare the whole farm's bare ridges at its declared ridge width.

        Requires fuel, trafficable soil and a width exactly matching the frozen
        layout. This is a preparation operation: it resets ridge planting/crop
        fields, consumes fuel and advances shared time. Use before sowing, not
        as a geometry editor on an established crop.

        Args:
            farm_id: Farm whose full field should be prepared.
            asset_id: Eligible physical tractor ID with compatible payload origin.
            ridge_width_m: Declared ridge width in m; cannot resize this farm.

        Returns:
            Receipt with ridge_width_m, num_ridges, duration and remaining fuel in data.
        """
        return self._execute("form_ridges", farm_id=farm_id, asset_id=asset_id, ridge_width_m=ridge_width_m)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def plant_seeds(
        self, farm_id: FarmId, asset_id: AssetId, start_ridge: RidgeId, end_ridge: RidgeId,
        depth_cm: Centimeters, seed_spacing_cm: Centimeters,
    ) -> dict[str, Any]:
        """Sow up to four contiguous bare ridges in the selected farm.

        Requires the field preparation listed in World capabilities, compatible
        loaded seeds, sufficient seeds and fuel, the planting window and the crop's
        soil, depth and spacing conditions. Consumes seed, fuel and working time.
        Emergence occurs later; inspect the crop before assessing establishment.

        Args:
            farm_id: Farm containing all ridges to sow and matching the loaded seed crop.
            asset_id: Physical tractor ID carrying this farm's seed payload.
            start_ridge: First local ridge ID, inclusive.
            end_ridge: Last local ridge ID; inclusive span must be at most four ridges.
            depth_cm: Sowing depth in cm within this farm's crop-specific range.
            seed_spacing_cm: In-row seed spacing in cm within this crop's range.

        Returns:
            Receipt with planted_ridges, depth_cm, seed_spacing_cm,
            seeds_per_ridge and seeds_used in data.
        """
        return self._execute("plant_seeds", farm_id=farm_id, asset_id=asset_id,
                             start_ridge=start_ridge, end_ridge=end_ridge,
                             depth_cm=depth_cm, seed_spacing_cm=seed_spacing_cm)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def replant_seeds(
        self, farm_id: FarmId, asset_id: AssetId, start_ridge: RidgeId, end_ridge: RidgeId,
        depth_cm: Centimeters, seed_spacing_cm: Centimeters, full_replant: bool = False,
    ) -> dict[str, Any]:
        """Re-sow or gap-fill up to four contiguous local ridges.

        Requires compatible loaded seeds, sufficient seed and fuel, valid depth
        and spacing, and a supported replanting method. Uses seed and working
        time. Gap-filling preserves the established crop's development schedule;
        full_replant requests a restart only where that method is supported.

        Args:
            farm_id: Farm containing the ridges to re-sow or gap-fill.
            asset_id: Physical tractor ID carrying compatible seed from this farm.
            start_ridge: First local ridge ID, inclusive.
            end_ridge: Last local ridge ID; inclusive span must be at most four ridges.
            depth_cm: Sowing depth in cm within this farm's crop-specific range.
            seed_spacing_cm: In-row seed spacing in cm within this crop's range.
            full_replant: Request a restart of the ridge crop cycle where supported.

        Returns:
            Receipt with replanted_ridges, seeds_used, stand before/after and
            phenology_reset_ridges in data.
        """
        return self._execute("replant_seeds", farm_id=farm_id, asset_id=asset_id,
                             start_ridge=start_ridge, end_ridge=end_ridge, depth_cm=depth_cm,
                             seed_spacing_cm=seed_spacing_cm, full_replant=full_replant)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def apply_fertilizer(
        self, farm_id: FarmId, asset_id: AssetId, start_ridge: RidgeId, end_ridge: RidgeId,
        kg_per_ridge: KgPerRidge,
    ) -> dict[str, Any]:
        """Apply spreader fertilizer to at most ten contiguous local ridges.

        Requires trafficable soil, onboard fertilizer/fuel and remaining farm
        fertilizer allowance. Consumes resources and advances shared time.
        Field response may be delayed; reassess crop condition after application.

        Args:
            farm_id: Farm receiving fertilizer and charged for actual application.
            asset_id: Physical tractor ID carrying fertilizer from this farm.
            start_ridge: First local ridge ID, inclusive.
            end_ridge: Last local ridge ID; inclusive span must be at most ten ridges.
            kg_per_ridge: Positive fertilizer application mass in kg/ridge.

        Returns:
            Receipt with fertilized_ridges and fertilizer_used_kg in data.
        """
        return self._execute("apply_fertilizer", farm_id=farm_id, asset_id=asset_id,
                             start_ridge=start_ridge, end_ridge=end_ridge, kg_per_ridge=kg_per_ridge)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def apply_pesticide(
        self, farm_id: FarmId, asset_id: AssetId, start_ridge: RidgeId, end_ridge: RidgeId,
    ) -> dict[str, Any]:
        """Spray insecticide at 8 L/ridge on at most ten contiguous ridges.

        Requires sprayable weather, trafficable soil, onboard pesticide/fuel
        and chemical-management permission. Consumes resources, records
        insecticide usage, queues treatment and advances the shared clock.

        Args:
            farm_id: Farm receiving insecticide and charged for chemical usage.
            asset_id: Physical tractor ID carrying chemical from this farm.
            start_ridge: First local ridge ID, inclusive.
            end_ridge: Last local ridge ID; inclusive span must be at most ten ridges.

        Returns:
            Receipt with sprayed_ridges, pesticide_used_liters and management usage in data.
        """
        return self._execute("apply_pesticide", farm_id=farm_id, asset_id=asset_id,
                             start_ridge=start_ridge, end_ridge=end_ridge)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def spray_pesticide(
        self, farm_id: FarmId, asset_id: AssetId, start_ridge: RidgeId, end_ridge: RidgeId,
        liters_per_ridge: LitersPerRidge = 8.0,
    ) -> dict[str, Any]:
        """Spray a chosen insecticide dose on at most ten contiguous ridges.

        Requires sprayable weather, trafficable soil, onboard pesticide/fuel
        and chemical-management permission. Consumes resources, records
        insecticide usage, queues treatment and advances shared time.

        Args:
            farm_id: Farm receiving insecticide and charged for chemical usage.
            asset_id: Physical tractor ID carrying chemical from this farm.
            start_ridge: First local ridge ID, inclusive.
            end_ridge: Last local ridge ID; inclusive span must be at most ten ridges.
            liters_per_ridge: Positive insecticide volume in L/ridge; default 8.0.

        Returns:
            Receipt with sprayed_ridges, pesticide_used_liters and management usage in data.
        """
        return self._execute("spray_pesticide", farm_id=farm_id, asset_id=asset_id,
                             start_ridge=start_ridge, end_ridge=end_ridge, liters_per_ridge=liters_per_ridge)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def apply_fungicide(
        self, farm_id: FarmId, asset_id: AssetId, start_ridge: RidgeId, end_ridge: RidgeId,
        liters_per_ridge: LitersPerRidge,
    ) -> dict[str, Any]:
        """Spray fungicide on at most ten contiguous local ridges.

        Requires sprayable weather, trafficable soil, sufficient fungicide in
        the separate tank, fuel and disease-treatment permission. Consumes
        resources, records fungicide usage and advances shared time. Disease
        control takes effect over time rather than instantly reversing crop damage.

        Args:
            farm_id: Farm receiving fungicide and charged for chemical usage.
            asset_id: Physical tractor ID with fungicide loaded from this farm.
            start_ridge: First local ridge ID, inclusive.
            end_ridge: Last local ridge ID; inclusive span must be at most ten ridges.
            liters_per_ridge: Positive fungicide volume in L/ridge.

        Returns:
            Receipt with sprayed_ridges, fungicide_used_liters and management usage in data.
        """
        return self._execute("apply_fungicide", farm_id=farm_id, asset_id=asset_id,
                             start_ridge=start_ridge, end_ridge=end_ridge, liters_per_ridge=liters_per_ridge)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def apply_herbicide(
        self, farm_id: FarmId, asset_id: AssetId, start_ridge: RidgeId, end_ridge: RidgeId,
        liters_per_ridge: LitersPerRidge,
    ) -> dict[str, Any]:
        """Spray herbicide on at most ten contiguous local ridges.

        Uses the onboard pesticide tank. Requires sprayable weather,
        trafficable soil, tank chemical, fuel and herbicide permission.
        Consumes resources, records herbicide usage, queues weed knockdown
        and residual effects, and advances the shared clock.

        Args:
            farm_id: Farm receiving herbicide and charged for chemical usage.
            asset_id: Physical tractor ID carrying chemical from this farm.
            start_ridge: First local ridge ID, inclusive.
            end_ridge: Last local ridge ID; inclusive span must be at most ten ridges.
            liters_per_ridge: Positive herbicide volume in L/ridge.

        Returns:
            Receipt with treated_ridges, herbicide_used_liters and management usage in data.
        """
        return self._execute("apply_herbicide", farm_id=farm_id, asset_id=asset_id,
                             start_ridge=start_ridge, end_ridge=end_ridge, liters_per_ridge=liters_per_ridge)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def mechanical_weed_control(
        self, farm_id: FarmId, asset_id: AssetId, start_ridge: RidgeId, end_ridge: RidgeId,
    ) -> dict[str, Any]:
        """Cultivate weeds on at most ten contiguous local ridges.

        Requires trafficable soil, fuel, machine-pass budget and the farm's
        mechanical-weeding ridge allowance. Consumes fuel, records one machine
        pass and advances time. Queues mechanical weed knockdown without
        herbicide residual or chemical usage.

        Args:
            farm_id: Farm receiving cultivation and charged for machine/ridge usage.
            asset_id: Physical tractor ID eligible for this farm with compatible payload.
            start_ridge: First local ridge ID, inclusive.
            end_ridge: Last local ridge ID; inclusive span must be at most ten ridges.

        Returns:
            Receipt with treated_ridges and management_regime usage in data.
        """
        return self._execute("mechanical_weed_control", farm_id=farm_id, asset_id=asset_id,
                             start_ridge=start_ridge, end_ridge=end_ridge)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def harvest(
        self, farm_id: FarmId, asset_id: AssetId, start_ridge: RidgeId, end_ridge: RidgeId,
    ) -> dict[str, Any]:
        """Harvest at most four contiguous mature ridges into this asset's bin.

        Requires planted mature crop, no rain, trafficable soil, fuel, bin
        capacity and grain moisture within the crop/asset effective limit.
        Consumes fuel and advances shared time. Recovered yield enters
        asset-owned origin batches; unload before changing farms. This does
        not move grain to trailer or safe warehouse storage.

        Args:
            farm_id: Farm owning all requested mature local ridges.
            asset_id: Physical tractor/combine ID eligible for this farm.
            start_ridge: First local ridge ID, inclusive.
            end_ridge: Last local ridge ID; inclusive span must be at most four ridges.

        Returns:
            Receipt with harvested_ridges, grain_kg_added, grain_bin_kg and
            grain_bin_max_kg in data.
        """
        return self._execute("harvest", farm_id=farm_id, asset_id=asset_id,
                             start_ridge=start_ridge, end_ridge=end_ridge)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def unload_grain(self, farm_id: FarmId, asset_id: AssetId) -> dict[str, Any]:
        """Unload one asset's grain batches into their origin farm's trailer.

        Requires a nonempty bin whose entire batch provenance matches farm_id.
        Moves only this asset's grain, clears its bin/batches and advances
        shared time by about eight minutes. Grain remains pending postharvest
        handling; use Farm.dry_grain and Farm.store_grain as needed.

        Args:
            farm_id: Origin farm owning all grain currently aboard this asset.
            asset_id: Physical tractor/combine ID whose bin should be unloaded.

        Returns:
            Receipt with grain_kg_unloaded, empty grain_bin_kg and duration in data.
        """
        return self._execute("unload_grain", farm_id=farm_id, asset_id=asset_id)

    @service_tool(OperationType.WRITE, routing=("farm_id", "asset_id"))
    def incorporate_residue(
        self, farm_id: FarmId, asset_id: AssetId, start_ridge: RidgeId, end_ridge: RidgeId,
    ) -> dict[str, Any]:
        """Incorporate crop residue on at most ten contiguous local ridges.

        Schedule this after harvest. Requires fuel and compatible equipment and
        payload origin. Consumes fuel and working time and records the operation;
        it does not report a measured increase in soil carbon or fertility.

        Args:
            farm_id: Farm receiving the residue incorporation pass.
            asset_id: Eligible physical tractor ID with compatible payload origin.
            start_ridge: First local ridge ID, inclusive.
            end_ridge: Last local ridge ID; inclusive span must be at most ten ridges.

        Returns:
            Receipt with processed ridge_ids in data.
        """
        return self._execute("incorporate_residue", farm_id=farm_id, asset_id=asset_id,
                             start_ridge=start_ridge, end_ridge=end_ridge)
