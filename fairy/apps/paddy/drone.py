"""Area-based paddy survey with a shared battery and labelled proxy products."""
from datetime import datetime, timezone
import math

from fairy.apps.app import App
from fairy.apps.paddy.observations import crop_report
from fairy.tool_utils import app_tool, OperationType
from fairy.types import event_registered


class PaddyDroneApp(App):
    def __init__(self, world):
        super().__init__()
        self.world = world

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def check_status(self) -> dict:
        """Read drone battery, survey cost and charging electricity requirements."""
        return {"battery_pct": self.world.field.drone_battery_pct,
                "survey_battery_pct_per_1000m2": 8., "full_charge_kwh": .4}

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def fly_survey(self, plot_ids: list[str]) -> dict:
        """Survey selected plots for canopy cover and signs of stress.

        Consumes flight time and battery. Read surveyed plots and the uncertainty
        of the estimated canopy and stress observations.

        Args:
            plot_ids: Hydraulic-plot IDs to survey, from the field overview.
        """
        self.world.advance_physics_time()
        if not plot_ids or len(plot_ids) != len(set(plot_ids)):
            raise ValueError("Select distinct plot IDs")
        plots = [self.world.plot(pid) for pid in plot_ids]
        if any(p is None for p in plots):
            raise ValueError("Unknown survey plot")
        day = datetime.fromtimestamp(self.world.sim_time, timezone.utc).date()
        weather = self.world.weather_for(day)
        if weather["rain_mm"] > 5 or weather["wind_ms"] > 10:
            raise ValueError("Survey weather window is closed")
        area = sum(p.area_m2 for p in plots)
        battery = area / 1000 * 8
        if battery > self.world.field.drone_battery_pct:
            raise ValueError("Charge drone before this survey")
        self.world.run_job(math.ceil(area / 10000 * 3600))
        self.world.field.drone_battery_pct -= battery
        products = []
        for p in plots:
            crop = crop_report(self.world, p)
            products.append(self.world.observe(f"survey:{p.plot_id}", {
                "plot_id": p.plot_id, "coverage_m2": p.area_m2,
                "canopy_cover_fraction": crop["canopy_cover_fraction"],
                "anomaly": ("inspect_on_ground" if max(p.pests, p.disease, p.weeds) > .15
                            or p.stand_fraction < .9 or crop["nitrogen_stress_signal"] == "elevated" else "none_detected"),
                "resolution": "plot-average proxy; not a diagnosis"}))
        self.world.record("fly_survey", plot_ids=plot_ids, battery_pct=battery)
        return {"products": products, "battery_remaining_pct": self.world.field.drone_battery_pct}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def charge(self) -> dict:
        """Charge the drone to 100%, consuming up to one hour and 0.4 kWh."""
        self.world.advance_physics_time()
        missing = 100 - self.world.field.drone_battery_pct
        energy = missing / 100 * .4
        if energy > self.world.field.electricity_kwh:
            raise ValueError("Insufficient charging electricity")
        self.world.run_job(math.ceil(missing / 100 * 3600))
        self.world.field.drone_battery_pct = 100.
        self.world.field.electricity_kwh -= energy
        self.world.field.energy_used_kwh += energy
        self.world.record("charge_drone", electricity_kwh=energy)
        return {"status": "ok", "battery_pct": 100., "electricity_kwh": energy}
