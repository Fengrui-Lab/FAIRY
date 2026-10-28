"""Real FAIRY/PCSE integration tests for visualization projection boundaries."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json

import pytest

from fairy.visualization.adapter import FarmAdapter, SCENARIO_ID, catalog


_RUNTIME_AVAILABLE = all(importlib.util.find_spec(name) for name in ("pcse", "numpy"))
requires_runtime = pytest.mark.skipif(not _RUNTIME_AVAILABLE, reason="Real PCSE dependencies required")


def _fingerprint(adapter):
    """Only direct reads; no application get_state methods with charge sync."""
    physics = adapter.farm._physics
    return {
        "time": adapter.sim_time,
        "ridges": deepcopy([vars(ridge) for ridge in adapter.farm._ridges]),
        "inventory": deepcopy(vars(adapter.farm._inventory)),
        "management": deepcopy(vars(adapter.farm._management_regime)),
        "rng": [app.rng.getstate() for app in adapter.apps],
        "native": deepcopy(physics.crop_backend.export_state()),
        "pending": deepcopy(adapter.farm._pending_irrigation),
    }


def _execute(adapter, name, **arguments):
    result = adapter.execute(name, arguments)
    assert result["ok"], result
    return result["data"]


def _plant_four(adapter):
    _execute(adapter, "TractorApp__attach_implement", implement="grader")
    _execute(adapter, "TractorApp__level")
    _execute(adapter, "TractorApp__detach_implement")
    _execute(adapter, "TractorApp__attach_implement", implement="furrower")
    _execute(adapter, "TractorApp__form_ridges", ridge_width_m=1.1)
    _execute(adapter, "TractorApp__detach_implement")
    _execute(adapter, "TractorApp__load_seeds", seed_type="SOYBEAN_901", count=100000)
    _execute(adapter, "TractorApp__plant_seeds", start_ridge=0, end_ridge=3,
             depth_cm=4.0, seed_spacing_cm=4.04040404040404)


def test_catalog_does_not_construct_a_world():
    value = catalog()
    assert value["schema_version"] == 1
    assert value["scenarios"][0]["id"] == SCENARIO_ID
    assert value["scenarios"][0]["location"] == "Lille, France"
    assert value["scenarios"][0]["available"] == _RUNTIME_AVAILABLE


@requires_runtime
def test_setup_captures_but_does_not_execute_oracle():
    adapter = FarmAdapter()
    assert adapter.descriptor["cultivar"] == "SOYBEAN_901"
    assert adapter.sim_datetime.startswith("2019-04-28T07:00:00")
    view = adapter.public_state()
    assert len(view["farms"][0]["ridges"]) == 64
    assert not any(ridge["planted"] for ridge in view["farms"][0]["ridges"])
    assert view["observations"] == []
    assert view["farms"][0]["inventory"]["seed_stock"]["SOYBEAN_901"] == 1000000
    assert all(row["values"]["dvs"] is None for row in adapter.audit_state()["farms"][0]["ridges"])


@requires_runtime
def test_refresh_and_audit_are_pure_detached_views():
    adapter = FarmAdapter()
    before = _fingerprint(adapter)
    public = adapter.public_state()
    audit = adapter.audit_state()
    for _ in range(20):
        assert adapter.public_state() == public
        assert adapter.audit_state() == audit
    assert _fingerprint(adapter) == before
    public["farms"][0]["ridges"][0]["planted"] = True
    audit["farms"][0]["ridges"][0]["values"]["dvs"] = 9
    assert not adapter.public_state()["farms"][0]["ridges"][0]["planted"]
    assert adapter.audit_state()["farms"][0]["ridges"][0]["values"]["dvs"] is None


@requires_runtime
def test_only_explicit_measurements_advance_observation_rng():
    adapter = FarmAdapter()
    before_rng = adapter.sensor.rng.getstate()
    for _ in range(5):
        adapter.public_state()
        adapter.audit_state()
    assert adapter.sensor.rng.getstate() == before_rng
    result = _execute(adapter, "SensorApp__read_soil_sensors")
    assert adapter.sensor.rng.getstate() != before_rng
    view = adapter.public_state()
    assert view["observations"][-1]["data"] == result
    assert view["observations"][-1]["coverage"]["ridge_ids"] == list(range(64))
    measured_at = view["observations"][-1]["observed_at"]
    rng_after = adapter.sensor.rng.getstate()
    _execute(adapter, "SystemApp__advance_time", hours=1)
    later = adapter.public_state()
    assert later["observations"][-1]["observed_at"] == measured_at
    assert adapter.sensor.rng.getstate() == rng_after


@requires_runtime
def test_public_views_do_not_leak_sensor_caches_or_native_state():
    adapter = FarmAdapter()
    public = adapter.public_state()
    serialized = json.dumps(public)
    for forbidden in ("random_state", "rng_state", "last_native_inputs", "weather_events",
                      "crop_backend_state", "LAI", "NAVAIL", "ndvi_proxy", "root_vwc"):
        assert forbidden not in serialized
    for device in public["devices"]:
        if "sensor" in device["kind"]:
            assert set(device["state"]) == {"sensor_id", "ridge_id", "ridge_start", "ridge_end"}
    for row in adapter.audit_state()["farms"][0]["ridges"]:
        assert "specification" not in row
        assert "journal" not in row


@requires_runtime
def test_tool_argument_and_private_tool_rejection_have_no_effect():
    adapter = FarmAdapter()
    before = _fingerprint(adapter)
    for name, args in (
        ("FarmWorldApp__get_state", {}),
        ("SystemApp__advance_time", {"seconds": float("nan")}),
        ("TractorApp__load_seeds", {"seed_type": "SOYBEAN_901", "count": True}),
        ("SensorApp__read_soil_sensors", {"unexpected": 1}),
    ):
        result = adapter.execute(name, args)
        assert not result["ok"]
        assert result["error"]["partial_effects"] is False
        assert _fingerprint(adapter) == before
    rejected = adapter.execute("TractorApp__level", {})
    assert not rejected["ok"], rejected
    assert _fingerprint(adapter) == before


@requires_runtime
def test_projection_subscriptions_do_not_change_real_tool_sequence():
    plain, viewed = FarmAdapter(), FarmAdapter()
    actions = [
        ("SensorApp__read_soil_sensors", {}),
        ("SensorApp__read_canopy_sensors", {}),
        ("SystemApp__advance_time", {"hours": 2}),
        ("SensorApp__read_root_zone_sensors", {}),
    ]
    for name, args in actions:
        for _ in range(4):
            viewed.public_state()
            viewed.audit_state()
        # Baseline calls the original AppTool directly, without the adapter's
        # execution/observation wrapper or any visualization subscription.
        baseline_result = plain.tools_map[name](**args)
        adapted_result = viewed.execute(name, args)
        assert adapted_result["ok"], adapted_result
        assert baseline_result == adapted_result["data"]
        assert _fingerprint(plain) == _fingerprint(viewed)
        assert plain.public_state()["farms"] == viewed.public_state()["farms"]
        assert plain.public_state()["devices"] == viewed.public_state()["devices"]


@requires_runtime
def test_native_growth_diagnostics_after_real_planting_and_day_advance():
    adapter = FarmAdapter()
    _plant_four(adapter)
    _execute(adapter, "SystemApp__advance_time", days=2)
    before = _fingerprint(adapter)
    state = adapter.public_state()
    assert all(ridge["planted"] for ridge in state["farms"][0]["ridges"][:4])
    assert not any(ridge["planted"] for ridge in state["farms"][0]["ridges"][4:])
    audit = adapter.audit_state()
    native = audit["farms"][0]["ridges"]
    assert native[0]["model_state_day"] is not None
    assert native[0]["values"]["root_vwc"] is not None
    assert native[4]["values"]["root_vwc"] is None
    assert _fingerprint(adapter) == before
