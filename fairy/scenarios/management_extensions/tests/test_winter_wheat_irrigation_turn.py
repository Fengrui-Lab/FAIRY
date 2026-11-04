"""The station must reject deliveries before debiting water or advancing time."""

from datetime import datetime
from types import SimpleNamespace

from fairy.scenarios.management_extensions.apps.winter_wheat_irrigation_app import (
    WinterWheatIrrigation,
)
from fairy.scenarios.management_extensions.apps.winter_wheat_turn_irrigation_app import (
    WinterWheatTurnIrrigation,
)


def test_station_turn_enforces_batch_size_and_completion_time(monkeypatch):
    opens = "2020-04-29T07:00:00+08:00"
    closes = "2020-04-29T08:05:00+08:00"
    now = datetime.fromisoformat(opens).timestamp()
    farm = SimpleNamespace(attach_weather_app=lambda weather: None)
    station = WinterWheatTurnIrrigation(
        farm, None, max_blocks=8, supply_windows=((opens, closes),)
    )
    station.register_time_manager(SimpleNamespace(time=lambda: now))
    delegated = []

    def deliver(self, blocks, duration_hours):
        delegated.append((blocks, duration_hours))
        return {"status": "ok"}

    monkeypatch.setattr(WinterWheatIrrigation, "_start_irrigation", deliver)
    batch = list(range(8))
    assert "error" in station._start_irrigation(list(range(9)), 1)
    assert "error" in station._start_irrigation(batch, 1 + 1 / 60)
    assert not delegated
    assert station._start_irrigation(batch, 1) == {"status": "ok"}
    assert delegated == [(batch, 1)]

    now = datetime.fromisoformat(closes).timestamp()
    assert not station.get_supply_schedule()["remaining_turns"]
    assert "error" in station._start_irrigation(batch, 1)
    assert delegated == [(batch, 1)]
