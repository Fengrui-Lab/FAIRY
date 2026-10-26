"""Shared machinery assets; physical work consumes onboard resources."""
from dataclasses import asdict

from fairy.apps.app import App
from fairy.apps.paddy.models import positive
from fairy.tool_utils import app_tool, OperationType
from fairy.types import event_registered


class PaddyMachineryApp(App):
    def __init__(self, world):
        super().__init__()
        self.world = world

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_machine_status(self, machine_id: str | None = None) -> dict:
        """Inspect tractor, transplanter or combine fuel, implement and onboard loads."""
        self.world.advance_physics_time()
        machines = [self.world.machine(machine_id)] if machine_id else self.world.field.machines
        return {"machines": [asdict(m) for m in machines],
                "fuel_liters_per_m2": {"puddle": .004, "transplant": .002, "harvest": .003,
                                       "fertilize": .001, "spray": .001, "gap_fill": .001},
                "seedlings_loaded": self.world.field.seedlings.loaded,
                "combine_wet_kg": sum(b.wet_kg for b in self.world.field.grain_batches if b.location == "combine")}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def refuel(self, machine_id: str, liters: float) -> dict:
        """Transfer a finite amount from warehouse fuel into the selected machine tank."""
        self.world.advance_physics_time()
        m = self.world.machine(machine_id)
        amount = positive(liters, "liters")
        if amount > self.world.field.fuel_liters or amount + m.fuel_liters > m.tank_capacity_liters:
            raise ValueError("Insufficient warehouse fuel or tank capacity")
        self.world.run_job(300)
        self.world.field.fuel_liters -= amount
        m.fuel_liters += amount
        self.world.record("refuel", machine_id=machine_id, liters=amount)
        return {"status": "ok", "fuel_liters": m.fuel_liters}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def attach_implement(self, machine_id: str, implement: str) -> dict:
        """Attach puddler, spreader or sprayer to the tractor; other machines are dedicated assets."""
        self.world.advance_physics_time()
        m = self.world.machine(machine_id)
        if m.kind != "tractor" or implement not in {"puddler", "spreader", "sprayer"}:
            raise ValueError("Unsupported machine/implement combination")
        if m.implement is not None:
            raise ValueError("Detach the current implement first")
        self.world.run_job(300)
        m.implement = implement
        self.world.record("attach_implement", machine_id=machine_id, implement=implement)
        return {"status": "ok", "implement": implement}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def detach_implement(self, machine_id: str) -> dict:
        """Detach the tractor implement after completing a work sequence."""
        self.world.advance_physics_time()
        m = self.world.machine(machine_id)
        if m.kind != "tractor" or m.implement is None:
            raise ValueError("No attached tractor implement")
        self.world.run_job(300)
        detached, m.implement = m.implement, None
        self.world.record("detach_implement", machine_id=machine_id, implement=detached)
        return {"status": "ok", "detached": detached}


def require_machine(world, machine_id, fuel, implement=None):
    machine = world.machine(machine_id)
    if machine.fuel_liters + 1e-9 < fuel:
        raise ValueError(f"Insufficient onboard fuel in {machine_id}; refuel first")
    if implement and machine.implement != implement:
        raise ValueError(f"Attach {implement} to {machine_id} first")
    return machine


def consume_fuel(world, machine, amount):
    machine.fuel_liters -= amount
    world.field.fuel_used_liters += amount
