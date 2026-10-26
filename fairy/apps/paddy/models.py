"""Versioned paddy assets, resources and independent grain batches."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import math

from fairy.physics.simulation_unit import SimulationUnit


def positive(value, name, *, zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < 0 or (value == 0 and not zero):
        raise ValueError(f"{name} must be {'nonnegative' if zero else 'positive'}")
    return float(value)


def default_soil():
    # Engineering fixture, not a calibrated site. cm and cm/day are native PCSE units.
    return dict(SMW=.15, SMFCF=.30, SM0=.50, CRAIRC=.06, SOPE=4., KSUB=1.,
                RDMSOL=60., initial_vwc=.30, bund_height_mm=150.,
                NAVAILI=30., NSOILBASE=40., NSOILBASE_FR=.005, BG_N_SUPPLY=.05)


@dataclass
class PaddyPlot:
    plot_id: str
    area_m2: float
    soil: dict = field(default_factory=default_soil)
    soaked_hours: float = 0.
    puddled: bool = False
    levelled: bool = False
    planted: bool = False
    harvested: bool = False
    seedling_batch_id: str | None = None
    seedlings_planted: int = 0
    transplant_timestamp: float | None = None
    grain_moisture_pct: float = 25.
    harvested_dry_kg: float = 0.
    harvest_loss_dry_kg: float = 0.
    loaded_grain_dry_kg: float = 0.
    unloaded_grain_dry_kg: float = 0.
    stored_dry_kg: float = 0.
    storage_moisture_pct: float | None = None
    transplanted_area_m2: float = 0.
    harvested_area_m2: float = 0.
    transplant_day: str | None = None
    field_loss_dry_kg: float = 0.
    stand_fraction: float = 1.
    pending_stand_recovery: float = 0.
    recovery_timestamp: float | None = None
    pests: float = 0.
    disease: float = 0.
    weeds: float = 0.
    bund_leak_mm_day: float = 0.

    def __post_init__(self):
        self.unit  # Validate identity/area without exposing ridges.
        for key in ("stand_fraction", "pests", "disease", "weeds"):
            if not math.isfinite(getattr(self, key)) or not 0 <= getattr(self, key) <= 1:
                raise ValueError(f"Invalid {key}")
        positive(self.bund_leak_mm_day, "bund leakage", zero=True)

    @property
    def unit(self):
        return SimulationUnit(self.plot_id, "paddy_plot", self.area_m2)


@dataclass
class SeedlingBatch:
    batch_id: str = "ir72_standard"
    cultivar: str = "Rice_IR72"
    quantity: int = 210000
    loaded: int = 0
    age_days_at_delivery: int = 20
    establishment_profile: str = "ir72_transplant_v1"

    def __post_init__(self):
        for key in ("quantity", "loaded", "age_days_at_delivery"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"Seedling {key} must be a nonnegative integer")
        if self.loaded > 150000:
            raise ValueError("Seedling load exceeds transplanter capacity")
        if (not self.batch_id or self.cultivar != "Rice_IR72" or
                self.establishment_profile != "ir72_transplant_v1" or self.age_days_at_delivery != 20):
            raise ValueError("Rice supports only the declared 20-day IR72 transplant profile")


@dataclass
class WaterChannel:
    channel_id: str = "supply"
    connected_plots: list[str] = field(default_factory=lambda: ["p1", "p2"])
    flow_m3_hour: float = 80.
    efficiency: float = .9
    quota_m3: float = 12000.
    withdrawn_m3: float = 0.
    delivered_m3: float = 0.
    discharged_m3: float = 0.
    blockage_fraction: float = 0.
    open_hour: int = 0
    close_hour: int = 24

    def __post_init__(self):
        positive(self.flow_m3_hour, "channel flow")
        positive(self.quota_m3, "water quota", zero=True)
        if not 0 < self.efficiency <= 1:
            raise ValueError("Channel efficiency must be in (0, 1]")
        if not 0 <= self.blockage_fraction < 1 or not 0 <= self.open_hour < self.close_hour <= 24:
            raise ValueError("Invalid channel blockage or daily opening hours")


@dataclass
class Machine:
    machine_id: str
    kind: str
    fuel_liters: float
    tank_capacity_liters: float
    implement: str | None = None
    fertilizer_kg: float = 0.
    fertilizer_capacity_kg: float = 80.
    grain_capacity_wet_kg: float = 1500.
    seedling_capacity: int = 150000

    def __post_init__(self):
        positive(self.fuel_liters, "machine fuel", zero=True)
        positive(self.tank_capacity_liters, "tank capacity")
        if self.fuel_liters > self.tank_capacity_liters:
            raise ValueError("Machine fuel exceeds capacity")
        for key in ("fertilizer_capacity_kg", "grain_capacity_wet_kg", "seedling_capacity"):
            positive(getattr(self, key), key)


@dataclass
class GrainBatch:
    batch_id: str
    plot_id: str
    dry_kg: float
    moisture_pct: float
    location: str = "combine"

    @property
    def wet_kg(self):
        return self.dry_kg / (1 - self.moisture_pct / 100)


def default_machines():
    return [Machine("tractor", "tractor", 20., 60.),
            Machine("transplanter", "transplanter", 10., 25.),
            Machine("combine", "combine", 15., 50.)]


@dataclass
class PaddyField:
    field_id: str = "rice_demo"
    plots: list[PaddyPlot] = field(default_factory=lambda: [PaddyPlot("p1", 1000.), PaddyPlot("p2", 1500.)])
    channels: list[WaterChannel] = field(default_factory=lambda: [WaterChannel(), WaterChannel("drain", efficiency=1.)])
    seedlings: SeedlingBatch = field(default_factory=SeedlingBatch)
    fuel_liters: float = 500.
    storage_capacity_kg: float = 10000.
    machines: list[Machine] = field(default_factory=default_machines)
    grain_batches: list[GrainBatch] = field(default_factory=list)
    fertilizer_kg: float = 300.
    insecticide_liters: float = 10.
    fungicide_liters: float = 10.
    repair_material_kg: float = 100.
    electricity_kwh: float = 1000.
    energy_used_kwh: float = 0.
    fuel_used_liters: float = 0.
    fertilizer_applied_kg: float = 0.
    chemicals_used: dict = field(default_factory=lambda: {"insecticide_liters": 0., "fungicide_liters": 0.})
    repair_used_kg: float = 0.
    drone_battery_pct: float = 100.
    drying_capacity_wet_kg_day: float = 10000.
    forecast_error_mm: float = 0.

    def __post_init__(self):
        ids = [p.plot_id for p in self.plots]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("Paddy plot IDs must be nonempty and unique")
        channel_ids = [c.channel_id for c in self.channels]
        if len(channel_ids) != len(set(channel_ids)) or set(channel_ids) != {"supply", "drain"}:
            raise ValueError("Rice requires supply and drain channels")
        if any(not set(c.connected_plots) <= set(ids) for c in self.channels):
            raise ValueError("Channel references an unknown plot")
        positive(self.fuel_liters, "fuel", zero=True)
        positive(self.storage_capacity_kg, "storage capacity")
        if {m.machine_id for m in self.machines} != {"tractor", "transplanter", "combine"} or len(self.machines) != 3:
            raise ValueError("Paddy requires tractor, transplanter and combine assets")
        for key in ("fertilizer_kg", "insecticide_liters", "fungicide_liters", "electricity_kwh", "repair_material_kg"):
            positive(getattr(self, key), key, zero=True)
        positive(self.drying_capacity_wet_kg_day, "dryer throughput")
        if not math.isfinite(self.forecast_error_mm) or self.forecast_error_mm < 0:
            raise ValueError("Invalid forecast error")

    @classmethod
    def from_dict(cls, payload):
        data = dict(payload)
        data["plots"] = [PaddyPlot(**p) for p in data["plots"]]
        data["channels"] = [WaterChannel(**c) for c in data["channels"]]
        data["seedlings"] = SeedlingBatch(**data["seedlings"])
        data["machines"] = [Machine(**m) for m in data.get("machines", [asdict(m) for m in default_machines()])]
        data["grain_batches"] = [GrainBatch(**b) for b in data.get("grain_batches", [])]
        return cls(**data)

    def to_dict(self):
        return asdict(self)
