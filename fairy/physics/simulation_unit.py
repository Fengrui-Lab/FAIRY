"""Area-bearing simulation identity shared by crop adapters and reports."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class SimulationUnit:
    unit_id: str
    unit_kind: str
    area_m2: float

    def __post_init__(self):
        if not self.unit_id or self.unit_kind not in {"ridge", "paddy_plot"}:
            raise ValueError("A simulation unit needs an ID and a supported kind")
        if not math.isfinite(self.area_m2) or self.area_m2 <= 0:
            raise ValueError("Simulation area must be finite and positive")

    def volume_m3(self, depth_mm: float) -> float:
        return self.area_m2 * depth_mm / 1000.0

    def mass_kg(self, yield_kg_ha: float) -> float:
        return yield_kg_ha * self.area_m2 / 10000.0
