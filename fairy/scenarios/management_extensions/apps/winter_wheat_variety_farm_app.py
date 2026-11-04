"""Assign distinct official wheat parameters and seed lots to management blocks."""

from collections import Counter
from copy import copy, deepcopy
from dataclasses import replace
from inspect import unwrap

from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered

from ..engines.winter_wheat_inputs import fingerprint
from .winter_wheat_accounts_app import SEED
from .winter_wheat_farm_app import DEFINITION, WheatFieldPhysics, WinterWheatFarm


LATE_SEED = "WINTER_WHEAT_101"
LATE_VARIETY = "Winter_wheat_101"


class VarietyFieldPhysics(WheatFieldPhysics):
    def __init__(self, world):
        super().__init__(world)
        self.config.cultivar_map = world.varieties.copy()

    def validate_planting(self, event):
        self.world.bundle.season.check_sowing(event.planting_date)
        for block in event.ridge_ids:
            expected = self.world.seed_by_block[block]
            if event.seed_type != expected:
                raise ValueError(f"Block {block} requires {expected}")
            backend = self.world.backends[block]
            if backend.sown or any(action["kind"] == "sow" for action in backend.pending):
                raise ValueError(f"Block {block} is already sown")


class VarietyWheatFarm(WinterWheatFarm):
    """One field with a fixed, observable seed assignment per block."""

    physics_class = VarietyFieldPhysics

    def __init__(self, bundle, resources, *, seed_by_block):
        self.seed_by_block = tuple(seed_by_block)
        if len(self.seed_by_block) != resources.block_count:
            raise ValueError("Declare one seed assignment per management block")
        catalog = {SEED: bundle.cultivar, LATE_SEED: LATE_VARIETY}
        self.varieties = {seed: catalog[seed] for seed in dict.fromkeys(self.seed_by_block)}
        self._definition = replace(
            DEFINITION,
            cultivar_id=next(iter(self.varieties)),
            seed_types=tuple(self.varieties),
        )
        self._block_bundles = {}
        for seed, cultivar in self.varieties.items():
            if cultivar == bundle.cultivar:
                self._block_bundles[seed] = bundle
                continue
            variant = copy(bundle)
            variant.manifest = deepcopy(bundle.manifest)
            variant.manifest["crop"]["cultivar"] = cultivar
            variant.cultivar = cultivar
            variant.identity = fingerprint(variant.manifest)
            self._block_bundles[seed] = variant
        single_variety = len(self.varieties) == 1
        primary_seed = self._definition.cultivar_id
        field_bundle = self._block_bundles[primary_seed] if single_variety else bundle
        super().__init__(field_bundle, resources)
        self._cultivar_id = primary_seed
        self.variety_name = self.varieties[primary_seed] if single_variety else None

    @property
    def crop_definition(self):
        return self._definition

    def seed_inventory(self):
        total = round(self.resources.seed_stock_kg / self.resources.seed_mass_kg)
        count, remainder = divmod(total, len(self.seed_by_block))
        stock = Counter()
        for block, seed in enumerate(self.seed_by_block):
            stock[seed] += count + (block < remainder)
        return dict(stock)

    def block_inputs(self, block_id):
        return self._block_bundles[self.seed_by_block[block_id]]

    def validate_seed_for_crop(self, seed_type):
        if seed_type not in self.varieties:
            return "Load a seed type assigned to this field"

    def check_planting_window(self, ridge_ids, seed_type):
        for block in ridge_ids:
            expected = self.seed_by_block[block]
            if seed_type != expected:
                return f"Block {block} requires {expected}"
        return super().check_planting_window(ridge_ids, seed_type)

    def crop_backend_provenance(self):
        return {
            **super().crop_backend_provenance(),
            "variety": self.variety_name,
            "cultivars": self.varieties.copy(),
            "input_fingerprint": fingerprint(
                [self.block_inputs(i).identity for i in range(self.num_ridges)]
            ),
            "block_seed_types": list(self.seed_by_block),
        }

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_field_info(self) -> dict:
        """Read block area, assigned seed and official cultivar, and planting rules.

        Returns:
            dict: Blocks carry their required seed type. The seed catalogue maps
            warehouse seed IDs to native WOFOST cultivars. Query each block's
            crop stage before deciding field work or harvest.
        """
        info = unwrap(WinterWheatFarm.get_field_info)(self)
        info["seed_catalogue"] = self.varieties.copy()
        info["variety"] = self.variety_name
        info["seed_type"] = self._cultivar_id if len(self.varieties) == 1 else None
        for block in info["blocks"]:
            seed = self.seed_by_block[block["block_id"]]
            block.update(seed_type=seed, variety=self.varieties[seed])
        return info

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def inspect_blocks(self, start_block: int, end_block: int) -> dict:
        """Read crop stage, moisture, nitrogen and assigned cultivar by block.

        Args:
            start_block: First block ID, inclusive.
            end_block: Last block ID, inclusive, at least start_block.

        Returns:
            dict: Native block telemetry with seed and cultivar identity. Moisture
            is m³/m³ and available nitrogen is kg N/ha. Pending inputs settle daily.
        """
        info = unwrap(WinterWheatFarm.inspect_blocks)(self, start_block, end_block)
        for block in info.get("blocks", ()):
            seed = self.seed_by_block[block["block_id"]]
            block.update(seed_type=seed, variety=self.varieties[seed])
        return info
