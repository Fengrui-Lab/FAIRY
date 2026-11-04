"""Execute wheat Oracle trials and capture their frozen public tool calls."""

from datetime import date, datetime, time, timedelta

from fairy.types import EventRegisterer

from .apps.winter_wheat_accounts_app import SEED
from .common import capture_step, finish_capture


def capture_wheat_oracle(scene, steps):
    """Attach the live briefing and the selected trial without running any tools."""
    reference = scene.ORACLE_REFERENCE
    if scene.calibrating or not reference:
        return []
    if scene.input_fingerprint() != reference["input_fingerprint"]:
        return []
    with EventRegisterer.capture_mode() as events:
        previous = capture_step(
            None,
            scene.aui.send_message_to_agent(scene.scenario_input),
            "task",
            "Read the current task and operating objective.",
        )
        for index, (app, method, args, reason) in enumerate(steps, 1):
            tool = getattr(getattr(scene, app), method)
            previous = capture_step(
                previous,
                tool(**args),
                f"{method}_{index:03d}",
                reason,
            )
    return finish_capture(scene, events)


class WheatOracleTrial:
    """Record actual public operations on a fresh, calibrating wheat scene."""

    def __init__(self, scene):
        self.scene = scene
        self.steps = []
        scene.setup()

    def call(self, app, method, *, reason=None, **kwargs):
        response = getattr(getattr(self.scene, app), method)(**kwargs)
        if isinstance(response, dict) and (
            response.get("error")
            or response.get("status") in {"failed", "partial", "irrigation_pending"}
        ):
            raise ValueError(f"{app}.{method} {kwargs}: {response}")
        self.steps.append((app, method, kwargs, reason or method.replace("_", " ")))
        return response

    def goto(self, day):
        day = date.fromisoformat(day) if isinstance(day, str) else day
        target = datetime.combine(day, time(7), self.scene.simulation_timezone)
        now = self.scene.farm_environment.time_manager.time()
        if self.scene.farm.simulation_date(now) > day:
            raise ValueError(f"Cannot schedule {day}: the farm clock already passed it")
        if target.timestamp() > now:
            self.call("system", "advance_time", seconds=target.timestamp() - now)

    def observe(self):
        self.call("weather", "get_current_weather")
        self.call("sensor", "read_root_zone_sensors")
        self.call("sensor", "read_canopy_sensors")
        self.call(
            "farm",
            "inspect_blocks",
            start_block=0,
            end_block=self.scene.farm.num_ridges - 1,
        )

    def attach(self, implement):
        tractor = self.scene.tractor
        if tractor._attached_implement == implement:
            return
        if tractor._attached_implement is not None:
            self.call("tractor", "detach_implement")
        self.call("tractor", "attach_implement", implement=implement)

    def refuel(self):
        if (
            self.scene.tractor._fuel_tank_l < 30
            and self.scene.warehouse.stock.fuel_liters > 0
        ):
            self.call(
                "tractor",
                "refuel",
                liters=min(50.0, self.scene.warehouse.stock.fuel_liters),
            )

    def sow(self, day, *, seed_type=SEED, start=0, end=None):
        scene = self.scene
        end = scene.farm.num_ridges - 1 if end is None else end
        if "level" not in scene.farm.completed_prep_ops:
            self.call("farm", "get_field_info")
            self.call("accounts", "get_accounts")
            self.call("tractor", "get_status")
            self.attach("grader")
            self.call("tractor", "prepare_field")
        self.goto(day)
        self.observe()
        self.attach("seeder")
        for block in range(start, end + 1):
            self.refuel()
            self.call(
                "tractor",
                "load_seeds",
                seed_type=seed_type,
                count=scene.resources.seeds_per_block,
            )
            self.call(
                "tractor", "sow", start_block=block, end_block=block, depth_cm=3.0
            )

    def fertilize(self, pure_n_kg_ha, *, start=0, end=None, reason=None):
        if not pure_n_kg_ha:
            return
        scene = self.scene
        end = scene.farm.num_ridges - 1 if end is None else end
        kg_per_block = (
            pure_n_kg_ha
            * scene.farm.ridge_area_m2
            / 10000
            / scene.resources.fertilizer_n_fraction
        )
        self.call("tractor", "load_fertilizer", kg=kg_per_block * (end - start + 1))
        for first in range(start, end + 1, 10):
            self.refuel()
            self.call(
                "tractor",
                "fertilize",
                reason=reason,
                start_block=first,
                end_block=min(first + 9, end),
                kg_per_block=kg_per_block,
            )

    def irrigate(self, depth_mm, *, start=0, end=None, reason=None):
        if depth_mm:
            self.call(
                "irrigation",
                "irrigate",
                reason=reason,
                start_block=start,
                end_block=self.scene.farm.num_ridges - 1 if end is None else end,
                depth_mm=depth_mm,
            )

    def harvest(self, *, start=0, end=None):
        scene, farm = self.scene, self.scene.farm
        end = farm.num_ridges - 1 if end is None else end
        context = scene.farm_environment.get_farm("wheat")
        while (
            any(not farm.is_ridge_mature(i) for i in range(start, end + 1))
            or scene.weather.rainfall_mm > 0
            or scene.tractor._tractor_trafficability_error(context, "harvest")
        ):
            day = farm.simulation_date() + timedelta(days=1)
            if day > farm.bundle.season.deadline:
                raise ValueError("No legal harvest window before deadline")
            self.goto(day)
        self.observe()
        self.attach("harvester")
        for first in range(start, end + 1, 2):
            self.refuel()
            self.call(
                "tractor",
                "harvest_blocks",
                start_block=first,
                end_block=min(first + 1, end),
            )
            batch_id = f"wheat_{first}"
            self.call("tractor", "unload_grain", batch_id=batch_id)
            self.call(
                "warehouse",
                "dry_grain",
                batch_id=batch_id,
                target_moisture_pct=scene.resources.storage_moisture_pct,
            )
            self.call("warehouse", "store_grain", batch_id=batch_id)
        self.call("accounts", "get_accounts")
