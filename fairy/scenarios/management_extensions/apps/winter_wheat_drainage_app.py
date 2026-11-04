"""Surface drainage and operating costs for the local wheat waterlogging scenario."""

from copy import deepcopy
from datetime import timedelta

from fairy.apps.app import App
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered

from ..engines.winter_wheat_inputs import number
from ..engines.winter_wheat_waterlogging import WaterloggingWheatBackend
from .winter_wheat_accounts_app import WinterWheatAccounts


class WheatDrainage(App):
    def __init__(self, farm, *, flow_m3_per_hour=30.0, cost_usd_per_m3=0.10):
        super().__init__("Drainage")
        self.farm = farm
        self.flow_m3_per_hour = number(
            flow_m3_per_hour, "pump capacity (m³/hour)", minimum=1e-9
        )
        self.cost_usd_per_m3 = number(
            cost_usd_per_m3, "pump charge (USD/m³)", minimum=0
        )
        self.jobs = {}

    def get_state(self):
        return {"jobs": deepcopy(self.jobs)}

    def load_state(self, state_dict):
        self.jobs = deepcopy(state_dict["jobs"])

    @staticmethod
    def _surface_depth(backend):
        return 10 * (backend.values.get("SS") or 0)

    @staticmethod
    def _pending_depth(backend):
        return sum(
            action["amount"] for action in backend.pending if action["kind"] == "drain"
        )

    def _settled_receipts(self, backend):
        if not isinstance(backend, WaterloggingWheatBackend):
            return {}
        return backend.drainage_receipts

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def inspect_blocks(self, start_block: int, end_block: int) -> dict:
        """Check surface ponding, root-zone wetness and the pump service.

        Args:
            start_block: First wheat block ID to inspect, inclusive.
            end_block: Last wheat block ID to inspect, inclusive and at least start_block.

        Returns:
            Block surface depth (mm), unreserved depth after queued work (mm),
            root-zone moisture (m³/m³), and drainage eligibility. Consecutive
            overwet days and oxygen stress factor (1 = no stress) are native
            model diagnostics where available. Includes pump capacity, USD/m³
            and settled work receipts. Remeasure after the next daily update.
        """
        if (
            type(start_block) is not int
            or type(end_block) is not int
            or not 0 <= start_block <= end_block < self.farm.num_ridges
        ):
            raise ValueError("Select an inclusive range of valid wheat block IDs")
        self.farm.advance_physics_time()
        blocks = []
        settled_jobs = []
        for block_id in range(start_block, end_block + 1):
            backend = self.farm.backends[block_id]
            depth = self._surface_depth(backend)
            blocks.append(
                {
                    "block_id": block_id,
                    "drainage_available": isinstance(backend, WaterloggingWheatBackend),
                    "ponding_depth_mm": depth,
                    "unreserved_ponding_mm": max(
                        0.0, depth - self._pending_depth(backend)
                    ),
                    "root_zone_vwc": backend.values["SM"],
                    "consecutive_overwet_days": backend.values.get("DSOS"),
                    "oxygen_stress_factor": backend.values.get("RFOS"),
                }
            )
            receipts = self._settled_receipts(backend)
            for operation_id, job in self.jobs.items():
                receipt = receipts.get(f"drainage:{operation_id}")
                if receipt is not None:
                    settled_jobs.append({**job, **receipt})
        return {
            "as_of": self.farm.simulation_date().isoformat(),
            "flow_m3_per_hour": self.flow_m3_per_hour,
            "cost_usd_per_m3": self.cost_usd_per_m3,
            "blocks": blocks,
            "settled_jobs": settled_jobs,
        }

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def drain(self, block_id: int, depth_mm: float, operation_id: str) -> dict:
        """Pump standing surface water from one drainable wheat block.

        Args:
            block_id: Exact block ID with drainage access and unreserved ponding.
            depth_mm: Positive requested surface-water depth in mm, capped at actual ponding.
            operation_id: Unique job ID. Retrying identical inputs returns the prior job.

        Returns:
            Accepted depth (mm), pumped volume (m³), pump time (seconds), USD charge
            and the next native settlement date. Finish the job on the current day.
            Surface pumping does not directly remove root-zone water. Inspect again
            after the next daily update to verify drainage and root-zone response.
        """
        if type(block_id) is not int or not 0 <= block_id < self.farm.num_ridges:
            raise ValueError("Use a valid wheat block ID")
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("Use a nonempty drainage operation ID")
        depth_mm = number(depth_mm, "surface water depth (mm)", minimum=1e-9)
        prior = self.jobs.get(operation_id)
        if prior is not None:
            if (prior["block_id"], prior["requested_depth_mm"]) != (block_id, depth_mm):
                raise ValueError("Drainage operation ID reused with different inputs")
            return deepcopy(prior)

        backend = self.farm.backends[block_id]
        if not isinstance(backend, WaterloggingWheatBackend):
            raise ValueError("This block has no connected pump service")
        self.farm.advance_physics_time()
        if backend.failed:
            raise RuntimeError(f"Cannot pump an invalid native block: {backend.failed}")
        available = self._surface_depth(backend) - self._pending_depth(backend)
        if available <= 1e-9:
            raise ValueError("This block has no unreserved standing surface water")
        accepted = min(depth_mm, available)
        volume = accepted * self.farm.ridge_area_m2 / 1000
        duration = volume * 3600 / self.flow_m3_per_hour
        started_at = self.time_manager.time()
        completed_at = started_at + duration
        current_date = self.farm.simulation_date(started_at)
        if self.farm.simulation_date(completed_at) != current_date:
            raise ValueError("Drainage must finish today; request a smaller depth")
        if backend.next_day >= self.farm.bundle.season.deadline:
            raise ValueError("No native daily settlement remains in this wheat season")

        self.farm.farm_environment.advance_time(duration)
        backend.queue(f"drainage:{operation_id}", "drain", accepted)
        job = {
            "status": "ok",
            "operation_id": operation_id,
            "block_id": block_id,
            "requested_depth_mm": depth_mm,
            "accepted_depth_mm": accepted,
            "pumped_volume_m3": volume,
            "duration_s": duration,
            "cost_usd": volume * self.cost_usd_per_m3,
            "native_settlement_on": (backend.next_day + timedelta(days=1)).isoformat(),
        }
        self.jobs[operation_id] = job
        self.is_state_modified = True
        return deepcopy(job)

    def compute_accounts(self):
        settled_volume = sum(
            receipt["drained_mm"] * self.farm.ridge_area_m2 / 1000
            for backend in self.farm.backends
            for receipt in self._settled_receipts(backend).values()
        )
        return {
            "flow_m3_per_hour": self.flow_m3_per_hour,
            "cost_usd_per_m3": self.cost_usd_per_m3,
            "job_count": len(self.jobs),
            "pumped_volume_m3": sum(
                job["pumped_volume_m3"] for job in self.jobs.values()
            ),
            "native_settled_volume_m3": settled_volume,
            "pump_duration_s": sum(job["duration_s"] for job in self.jobs.values()),
            "total_cost_usd": sum(job["cost_usd"] for job in self.jobs.values()),
        }


class WaterloggingWheatAccounts(WinterWheatAccounts):
    drainage = None

    def compute_accounts(self):
        account = super().compute_accounts()
        drainage = self.drainage.compute_accounts()
        cost = drainage["total_cost_usd"]
        account["drainage"] = drainage
        account["cost_components"]["drainage_service"] = cost
        account["production_cost"] += cost
        account["net_operating_margin"] -= cost
        return account
