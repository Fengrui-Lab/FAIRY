"""Deterministic, rounded observations distinct from native simulation truth."""
import math

from fairy.apps.app import App
from fairy.tool_utils import app_tool, OperationType
from fairy.types import event_registered


def require_plot(world, plot_id):
    world.advance_physics_time()
    plot = world.plot(plot_id)
    if plot is None:
        raise ValueError(f"Unknown paddy plot: {plot_id}")
    return plot


def crop_report(world, plot):
    backend = world.backends[plot.plot_id]
    dvs = backend.crop_values.get("DVS")
    stage = ("not_planted" if dvs is None else "mature" if backend.maturity else
             "late_grain_filling" if dvs >= 1.6 else "grain_filling" if dvs >= 1 else
             "panicle_development_proxy" if dvs >= .65 else "late_tillering_proxy" if dvs >= .5 else
             "tillering_proxy" if dvs >= .25 else "establishment_proxy")
    rftra = backend.last_rates.get("RFTRA")
    rfrgrl = backend.last_rates.get("RFRGRL")
    # WOFOST81 leaf dynamics applies this factor only to juvenile leaf-area
    # expansion (DVS < .2, LAI < .75), not general season-long N sufficiency.
    last_day = next((e["day"] for e in reversed(backend.journal) if e["kind"] == "day"), None)
    lai = float(backend.crop_values.get("LAI") or 0)
    valid_n = (plot.planted and not backend.maturity and last_day is not None
               and dvs is not None and dvs < .2 and lai < .75
               and isinstance(rfrgrl, (float, int)) and math.isfinite(rfrgrl))
    return {"plot_id": plot.plot_id, "stage": stage,
            "canopy_cover_fraction": round(1 - math.exp(-.6 * float(backend.crop_values.get("LAI") or 0)), 2),
            "wilting_index": round(1 - rftra, 2) if rftra is not None else None,
            "nitrogen_stress_signal": ("low" if rfrgrl >= .95 else "elevated") if valid_n else "unknown",
            "nitrogen_signal_date": last_day,
            "nitrogen_signal_basis": "WOFOST juvenile leaf-area limitation proxy; not soil nitrogen measurement",
            "nitrogen_signal_applicable": bool(valid_n),
            "stage_uncertainty": "management proxy; no tiller or panicle counts",
            "maturity_observed": bool(backend.maturity)}


class PaddyObservationApp(App):
    def __init__(self, world):
        super().__init__()
        self.world = world

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def read_water_sensors(self, plot_id: str) -> dict:
        """Read plot pond depth and estimated root-zone VWC. This is not a groundwater tube reading.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
        """
        p = require_plot(self.world, plot_id)
        water = self.world.backends[plot_id].water.ledger()
        return self.world.observe(f"water:{plot_id}", {
            "plot_id": plot_id, "surface_water_mm": round(water["surface_water_mm"], 1),
            "root_vwc": round(water["root_vwc"], 3), "soil_update_date": self.world.backends[plot_id].model.day.isoformat(),
            "resolution": {"surface_water_mm": .1, "root_vwc": .001},
            "preparation_wet_hours": math.floor(p.soaked_hours * 10) / 10})

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def inspect_crop(self, plot_id: str) -> dict:
        """Spend 15 minutes inspecting crop stage, canopy cover and stress symptoms.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
        """
        p = require_plot(self.world, plot_id)
        self.world.run_job(900)
        return self.world.observe(f"crop:{plot_id}", crop_report(self.world, p))

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def measure_grain_moisture(self, plot_id: str | None = None, batch_id: str | None = None) -> dict:
        """Measure standing mature grain or a harvested batch; select exactly one target.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview. Supply exactly one of plot_id or batch_id.
            batch_id: Exact grain-batch ID from the grain listing. Supply exactly one of plot_id or batch_id.
        """
        self.world.advance_physics_time()
        if (plot_id is None) == (batch_id is None):
            raise ValueError("Select exactly one plot_id or batch_id")
        if batch_id:
            target = self.world.batch(batch_id)
        else:
            target = require_plot(self.world, plot_id)
            if not self.world.backends[plot_id].maturity:
                raise ValueError("Standing-grain moisture requires mature rice")
        self.world.run_job(300)
        moisture = target.moisture_pct if batch_id else target.grain_moisture_pct
        return self.world.observe(f"grain:{batch_id or plot_id}", {
            "plot_id": target.plot_id, "batch_id": batch_id, "moisture_pct": round(moisture, 1),
            "resolution_pct": .1})

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def inspect_pests(self, plot_id: str) -> dict:
        """Spend 15 minutes inspecting insect, disease and weed symptoms. Severity scores are field estimates; combine them with other evidence when choosing treatment.


        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
        """
        p = require_plot(self.world, plot_id)
        self.world.run_job(900)
        return self.world.observe(f"pests:{plot_id}", {"plot_id": plot_id,
            "insect_severity": round(p.pests, 2), "disease_severity": round(p.disease, 2),
            "weed_cover_fraction": round(p.weeds, 2), "resolution": .01})

    @app_tool()
    @event_registered(operation_type=OperationType.READ)
    def inspect_establishment(self, plot_id: str) -> dict:
        """Sample the established stand fraction after transplanting. This is an estimated proportion, not a complete individual-plant count.


        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
        """
        p = require_plot(self.world, plot_id)
        if not p.planted:
            raise ValueError("Transplant before inspecting establishment")
        self.world.run_job(600)
        return self.world.observe(f"stand:{plot_id}", {"plot_id": plot_id,
            "stand_fraction_estimate": round(p.stand_fraction, 2), "resolution": .01,
            "gap_fill_pending": p.pending_stand_recovery > 0})
