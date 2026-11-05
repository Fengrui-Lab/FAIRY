"""Inspect and repair simulated hydraulic faults; existing canals remain finite jobs."""
from dataclasses import asdict

from fairy.apps.app import App
from fairy.apps.paddy.observations import require_plot
from fairy.tool_utils import app_tool, OperationType
from fairy.types import event_registered


class PaddyInfrastructureApp(App):
    def __init__(self, world):
        super().__init__()
        self.world = world

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def inspect_infrastructure(self, plot_id: str) -> dict:
        """Inspect a plot's bund and connected supply/drain channels; spend 20 minutes.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
        """
        p = require_plot(self.world, plot_id)
        self.world.run_job(1200)
        return self.world.observe(f"infrastructure:{plot_id}", {
            "plot_id": plot_id, "bund_leak_mm_day_estimate": round(p.bund_leak_mm_day, 1),
            "channels": [asdict(c) for c in self.world.field.channels if plot_id in c.connected_plots]})

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def clear_channel(self, channel_id: str) -> dict:
        """Remove a channel blockage with one hour of manual work; restore nominal metered flow.

        Args:
            channel_id: Exact channel ID from the infrastructure inspection.
        """
        self.world.advance_physics_time()
        channel = self.world.channel(channel_id)
        if channel is None or channel.blockage_fraction <= 0:
            raise ValueError("Unknown channel or no blockage to clear")
        self.world.run_job(3600)
        channel.blockage_fraction = 0.
        self.world.record("clear_channel", channel_id=channel_id)
        return {"status": "ok", "channel_id": channel_id, "flow_m3_hour": channel.flow_m3_hour}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def repair_bund(self, plot_id: str) -> dict:
        """Repair the plot's leaking bund using 10 kg of repair material and two hours of work.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
        """
        p = require_plot(self.world, plot_id)
        if p.bund_leak_mm_day <= 0 or self.world.field.repair_material_kg < 10:
            raise ValueError("No bund leak or insufficient repair material")
        self.world.run_job(7200)
        self.world.field.repair_material_kg -= 10
        self.world.field.repair_used_kg += 10
        p.bund_leak_mm_day = 0.
        self.world.record("repair_bund", plot_id=plot_id, material_kg=10.)
        return {"status": "ok", "plot_id": plot_id}
