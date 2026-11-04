"""A reduced, opt-in winter wheat stripe rust model.

The declared source is latent infection in a small focus. Daily rain and RH
approximate wetness. There is no hourly wetness or wind direction in the
forcing. Parameters are scenario assumptions, not a local disease forecast.
"""

from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta

ARRIVAL_DAY = date(2020, 4, 9)
FOCUS = (6, 7)
LATENCY_DAYS = 8
PROTECTION_DAYS = 13
PROTECTED_INFECTION_FRACTION = 0.12


@dataclass
class StripeRustBlock:
    latent: float = 0.0
    symptomatic: float = 0.0
    protected_until: str = ""


class StripeRust:
    def __init__(self, block_count, *, arrival_day=ARRIVAL_DAY, focus=FOCUS):
        self.blocks = [StripeRustBlock() for _ in range(block_count)]
        self.arrival_day = arrival_day
        self.focus = focus

    def apply(self, blocks, day):
        for index in blocks:
            self.blocks[index].protected_until = (
                day + timedelta(days=PROTECTION_DAYS)
            ).isoformat()

    def advance_day(self, day, weather, active):
        """Advance all blocks simultaneously using yesterday's state."""
        today = day.isoformat()
        previous = self.blocks
        updated = []
        temperature = max(0.0, 1.0 - abs(weather.tmean_c - 12.0) / 14.0)
        wetness = min(
            1.0, 0.27 + weather.rain_mm * 0.17 + max(0.0, weather.rh_pct - 50.0) / 70.0
        )
        suitability = temperature * wetness
        for i, state in enumerate(previous):
            if not active[i]:
                updated.append(state)
                continue
            neighbors = previous[max(0, i - 1) : i] + previous[i + 1 : i + 2]
            local_inoculum = 0.95 * state.symptomatic
            incoming = 0.23 * sum(neighbor.symptomatic for neighbor in neighbors)
            susceptible = max(0.0, 1.0 - state.latent - state.symptomatic)
            protection = (
                PROTECTED_INFECTION_FRACTION if today <= state.protected_until else 1.0
            )
            arrival = 0.17 if day == self.arrival_day and i in self.focus else 0.0
            new = min(
                susceptible,
                arrival
                + susceptible * suitability * (local_inoculum + incoming) * protection,
            )
            expressed = state.latent / LATENCY_DAYS
            updated.append(
                replace(
                    state,
                    latent=state.latent - expressed + new,
                    symptomatic=state.symptomatic + expressed,
                )
            )
        self.blocks = updated
        # Couple once at the gross assimilation input to the existing native
        # carbon balance. A spray does not reverse already damaged tissue.
        return [1.0 - 0.83 * block.symptomatic for block in updated]

    def get_state(self):
        return [asdict(block) for block in self.blocks]

    def load_state(self, state):
        if len(state) != len(self.blocks):
            raise ValueError("Stripe rust checkpoint must contain every block")
        self.blocks = [StripeRustBlock(**block) for block in state]
