"""Timing and provenance boundaries of formal90 planning, independent of PCSE."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.compile_wofost_observed_oracle import ObservedCompiler
from scripts.formal90_calibration_policy import (
    CalibrationCompiler, source_timestamp, target_range,
)


class Clock:
    def __init__(self, value=0):
        self.value = value

    def time(self):
        return self.value


def policy(tmp_path, now=0):
    value = CalibrationCompiler.__new__(CalibrationCompiler)
    value.output = tmp_path
    value.sid = "test_scene"
    value.review = {}
    value.engine = SimpleNamespace(time_manager=Clock(now))
    value.farm = SimpleNamespace(name="FarmA", farm_id="farm_a", num_ridges=64)
    value.system = SimpleNamespace(name="SystemApp")
    value._source_steps = {}
    value._source_phases = {}
    value._source_stage_wait_done = set()
    value._phase_checked = {}
    value.management_audit = []
    value.model_blocks = []
    value.rejected_guards = []
    value._observed_survey_cost = {}
    value.timing_audit = []
    value.review_notes = []
    value.changes = []
    value.deadline = now + 180 * 86400
    return value


def test_source_calendar_is_beijing_and_accepts_aware_timestamps():
    assert source_timestamp("2026-05-05 07:00:00") == source_timestamp("2026-05-04T23:00:00+00:00")
    assert source_timestamp(None) is None


def test_manual_two_ridge_operation_audits_both_targets():
    assert target_range({"ridge_id": 33, "ridge_count": 2}) == (33, 34)


def test_source_daily_wait_targets_absolute_date_instead_of_adding_day(tmp_path, monkeypatch):
    target = source_timestamp("2026-06-12 07:00:00")
    compiler = policy(tmp_path, target - 7200)
    label = "o_wait_mid_advance_day_001"
    compiler._source_steps[label] = SimpleNamespace(time="2026-06-12 07:00:00")
    calls = []
    monkeypatch.setattr(ObservedCompiler, "call", lambda self, label, tool, args, **kw: calls.append((tool, args)))
    compiler.call(label, "SystemApp__advance_time", {"days": 1})
    assert calls == [("SystemApp__advance_time", {"seconds": 7200})]
    assert compiler.changes[0]["source_target_timestamp"] == target


def test_past_source_date_becomes_registered_clock_read(tmp_path, monkeypatch):
    target = source_timestamp("2026-06-12 07:00:00")
    compiler = policy(tmp_path, target + 86400)
    label = "o_wait_mid_advance_day_001"
    compiler._source_steps[label] = SimpleNamespace(time="2026-06-12 07:00:00")
    calls = []
    monkeypatch.setattr(ObservedCompiler, "call", lambda self, label, tool, args, **kw: calls.append((tool, args)))
    compiler.call(label, "SystemApp__advance_time", {"days": 1})
    assert calls == [("SystemApp__get_current_time", {})]
    assert compiler.engine.time_manager.time() == target + 86400


def test_r1_nutrition_gates_only_its_target_and_allows_different_later_stages(tmp_path):
    compiler = policy(tmp_path)
    requests, waits = [], []
    rows = iter([
        [{"growth_stage": "V4", "ridge_id": 16}, {"growth_stage": "R1_BEGINNING_BLOOM", "ridge_id": 17}],
        [{"growth_stage": "R1_BEGINNING_BLOOM", "ridge_id": 16}, {"growth_stage": "R3_BEGINNING_POD", "ridge_id": 17}],
    ])
    compiler.ridges = lambda label, first, last: requests.append((first, last)) or next(rows)
    compiler.wait = lambda label: waits.append(label)
    compiler._ensure_target_phase("o_r1_patch_fertigation", "apply_fertigation", {"start_ridge": 16, "end_ridge": 17})
    assert requests == [(16, 17), (16, 17)]
    assert len(waits) == 1
    assert compiler.timing_audit[-1]["outside_declared_latest_stage"] is False


def test_r5_past_r6_is_reported_without_waiting_backwards(tmp_path):
    compiler = policy(tmp_path)
    compiler.ridges = lambda *a: [{"growth_stage": "R7_BEGINNING_MATURITY", "ridge_id": 20}]
    compiler.wait = lambda *a: pytest.fail("Cannot wait backwards into R5")
    compiler._ensure_target_phase("o_r5_irrigation", "irrigate", {"start": 20, "end": 20})
    assert compiler.timing_audit[-1]["outside_declared_latest_stage"] is True
    assert "beyond R6" in compiler.review_notes[-1]


def test_stage_rechecked_after_weather_wait_advances_clock(tmp_path):
    compiler = policy(tmp_path, 100)
    rows = iter([[{"growth_stage": "R5_BEGINNING_SEED"}], [{"growth_stage": "R7_BEGINNING_MATURITY"}]])
    compiler.ridges = lambda *a: next(rows)
    args = {"start": 20, "end": 20}
    compiler._ensure_target_phase("o_r5_irrigation", "irrigate", args)
    compiler.engine.time_manager.value += 10 * 86400
    compiler._ensure_target_phase("o_r5_irrigation", "irrigate", args)
    assert len(compiler.timing_audit) == 2
    assert compiler.timing_audit[-1]["outside_declared_latest_stage"] is True


def test_mixed_field_scouting_does_not_wait_for_last_zone_to_mature(tmp_path):
    compiler = policy(tmp_path)
    compiler.ridges = lambda *a: [
        {"ridge_id": 0, "growth_stage": "R8_FULL_MATURITY", "planted": True},
        {"ridge_id": 32, "growth_stage": "R5_BEGINNING_SEED", "planted": True},
    ]
    compiler.wait = lambda *a: pytest.fail("Early zone should open scouting now")
    compiler.phase_wait("o_wait_harvest_advance_day_001", "harvest")
    assert compiler.timing_audit[-1]["phase"] == "harvest"


def test_unsupported_replant_is_attempted_and_reported_not_omitted(tmp_path, monkeypatch):
    compiler = policy(tmp_path)
    called = []
    compiler._private_management_audit = lambda *a: {"not_a_policy_input": True}

    def registered(self, label, tool, args, **kw):
        called.append(tool)
        raise RuntimeError("WOFOST requires a new native season")

    monkeypatch.setattr(ObservedCompiler, "call", registered)
    with pytest.raises(RuntimeError, match="new native season"):
        compiler.call("o_emergence_replant", "TractorApp__replant_seeds", {"start_ridge": 0, "end_ridge": 3})
    assert called == ["TractorApp__replant_seeds"]
    assert compiler.model_blocks[0]["original_objective_preserved"] is True
    assert (tmp_path / "calibration_block.json").is_file()
    assert compiler.management_audit[0]["exception_type"] == "RuntimeError"


def test_trial_snapshot_does_not_overwrite_reference_evidence(tmp_path, monkeypatch):
    compiler = policy(tmp_path)
    evidence = tmp_path / "replay_final_snapshot.json"
    evidence.write_text("reference")
    monkeypatch.setattr(ObservedCompiler, "snapshot", lambda *a: {"trial": True})
    assert compiler.snapshot_unrecorded(object(), object()) == {"trial": True}
    assert evidence.read_text() == "reference"


def test_seed_supplement_uses_public_geometry_and_existing_registered_stock_tool(tmp_path):
    compiler = policy(tmp_path)
    calls = []

    def public(label, tool, args, **kw):
        calls.append((tool, args))
        if tool.endswith("__get_status"):
            return {"seed_hopper": 5, "seed_type": "HEINONG84"}
        if tool.endswith("__get_farm_overview"):
            return {"field_length_m": 10, "crop_profile": {"rows_per_ridge": 2}}
        return {"status": "ok"}

    compiler.call = public
    compiler._ensure_seed_payload("o_plant_0_3", "TractorApp__plant_seeds", {"start_ridge": 0, "end_ridge": 3, "seed_spacing_cm": 10})
    assert calls[-1] == ("TractorApp__load_seeds", {"seed_type": "HEINONG84", "count": 795})
    assert compiler.changes[-1]["inventory_created"] is False


def test_survey_learns_public_energy_cost_and_splits_full_field_without_partial(tmp_path, monkeypatch):
    compiler = policy(tmp_path)
    battery = [92.]
    missions, charges = [], []

    def registered(self, label, tool, args, **kw):
        if tool.endswith("__check_status"):
            return {"battery_pct": battery[0], "charging": False, "effective_ridges_per_pass": 5}
        if tool.endswith("__charge"):
            charges.append(label)
            battery[0] = 100.
            return {"status": "charging_started"}
        first, last = args["start_ridge"], args["end_ridge"]
        battery[0] -= 1.5 * (last - first + 1)
        assert battery[0] >= 25.  # The actual tool's undisclosed return guard.
        missions.append((first, last))
        return {"status": "ok", "surveyed_ridges": list(range(first, last + 1)), "battery_remaining_pct": battery[0]}

    monkeypatch.setattr(ObservedCompiler, "call", registered)
    compiler.gate = lambda *a: None
    compiler.wait = lambda label, seconds=86400: setattr(compiler.engine.time_manager, "value", compiler.engine.time_manager.time() + seconds)
    result = compiler.call("o_full_thermal", "Matrice4T__fly_survey", {"start_ridge": 0, "end_ridge": 63})
    assert result["surveyed_ridges"] == list(range(64))
    assert missions == [(0, 4), (5, 39), (40, 63)]
    assert len(charges) == 1
    assert compiler._observed_survey_cost["Matrice4T"] == 1.5


def test_harvest_uses_public_18_percent_limit_and_not_coarse_probe_veto(tmp_path):
    compiler = policy(tmp_path)
    compiler.sensors = {"FarmA": SimpleNamespace(name="SensorA")}
    compiler.current_weather = lambda *a: {"rainfall_mm": 0.}
    compiler.ridges = lambda *a: [{"ridge_id": 20, "growth_stage": "R8", "grain_moisture_pct": 17.8}]
    compiler.call = lambda label, tool, args: ({"harvest_moisture_limit_pct": 18.} if tool.endswith("__get_status") else {"soil_sensors": [{"ridge_start": 0, "ridge_end": 63, "vwc": .38}]})
    compiler.wait = lambda *a: pytest.fail("A coarse overlapping wet probe cannot veto this legal target")
    compiler._harvest_gate({"start_ridge": 20, "end_ridge": 20}, "o_harvest", "TractorApp")
    assert compiler.timing_audit[-1]["harvest_moisture_limit_pct"] == 18.
    assert compiler.timing_audit[-1]["coarse_soil_vwc_range"] == [.38, .38]


def test_zero_mutation_harvest_rejection_is_saved_outside_replay_trace(tmp_path, monkeypatch):
    compiler = policy(tmp_path)
    compiler.trace = []
    calls = []
    compiler.gate = lambda *a: None
    compiler._harvest_guard_signature = lambda *a: {"clock": compiler.engine.time_manager.time(), "fuel": 100}
    compiler.wait = lambda label, seconds=86400: setattr(compiler.engine.time_manager, "value", compiler.engine.time_manager.time() + seconds)

    def registered(self, label, tool, args, **kw):
        calls.append(tool)
        content = {"error": "Cannot harvest in rainy conditions"} if len(calls) == 1 else {"status": "ok", "harvested_ridges": [20]}
        self.trace.append({"tool_name": tool, "content": content, "time_before": self.engine.time_manager.time(), "time_after": self.engine.time_manager.time()})
        return content

    monkeypatch.setattr(ObservedCompiler, "call", registered)
    result = compiler.call("o_harvest", "TractorApp__harvest", {"start_ridge": 20, "end_ridge": 20}, op="WRITE")
    assert result["status"] == "ok"
    assert len(calls) == 2
    assert len(compiler.trace) == 1 and compiler.trace[0]["content"]["status"] == "ok"
    assert len(compiler.rejected_guards) == 1
    assert compiler.rejected_guards[0]["zero_mutation_verified"] is True
    assert (tmp_path / "discovery_rejected_guards.json").is_file()


def test_mutating_harvest_rejection_cannot_be_discarded_or_retried(tmp_path, monkeypatch):
    compiler = policy(tmp_path)
    compiler.trace = []
    compiler.gate = lambda *a: None
    signatures = iter([{"fuel": 100}, {"fuel": 98}])
    compiler._harvest_guard_signature = lambda *a: next(signatures)
    compiler.wait = lambda *a: pytest.fail("Mutation forbids a silent retry")

    def registered(self, label, tool, args, **kw):
        self.trace.append({"time_before": 0, "time_after": 0})
        return {"error": "Cannot harvest in rainy conditions"}

    monkeypatch.setattr(ObservedCompiler, "call", registered)
    with pytest.raises(RuntimeError, match="changed public management state"):
        compiler.call("o_harvest", "TractorApp__harvest", {"start_ridge": 20, "end_ridge": 20})
    assert len(compiler.trace) == 1
    assert compiler.rejected_guards == []


def test_explicit_seed_choice_preserves_inventory_and_identity_without_profile_edits(tmp_path):
    compiler = policy(tmp_path)

    class World:
        def __init__(self):
            self._inventory = SimpleNamespace(seed_stock={"HEINONG84": 1000, "HEINONG58": 20})
            self._ridges = [SimpleNamespace(seed_type="HEINONG84", planted=False)]
            self._planting_windows = [{"seed_type": "HEINONG84", "earliest_date": "2026-05-05"}]
            self.physics = SimpleNamespace(phenology=SimpleNamespace(states={}), canopy=SimpleNamespace(states={}), scenario_metadata={"seed_type": "HEINONG84", "cultivar": "Original HN84"})

    world = World()
    tractor = SimpleNamespace(seed_type="HEINONG84")
    scenario = SimpleNamespace(apps=[world, tractor], additional_system_prompt=None)
    compiler.i = {"FarmWorldApp": World}
    compiler._apply_seed_replacements(scenario, {"HEINONG84": "HEINONG58"})
    assert world._inventory.seed_stock == {"HEINONG58": 1020}
    assert tractor.seed_type == world._ridges[0].seed_type == "HEINONG58"
    assert world._planting_windows[0]["seed_type"] == "HEINONG58"
    assert world.physics.scenario_metadata["seed_type"] == "HEINONG58"
    assert scenario.initial_state_adjustments[-1]["seed_inventories"][0]["total_seed_count_preserved"] is True
    assert "not calibration of the old cultivar" in scenario.additional_system_prompt


def test_manual_spray_source_cannot_disable_real_operator_time(tmp_path, monkeypatch):
    compiler = policy(tmp_path, 100)
    called = []
    compiler._private_management_audit = lambda label, tool, args: {"clock": compiler.engine.time_manager.time(), "arguments": dict(args), "not_a_policy_input": True}

    def registered(self, label, tool, args, **kw):
        called.append(dict(args))
        if args.get("advance_time"):
            self.engine.time_manager.value += 700
        return {"status": "ok"}

    monkeypatch.setattr(ObservedCompiler, "call", registered)
    original = {"ridge_id": 24, "ridge_count": 2, "liters_per_ridge": 3., "advance_time": False}
    compiler.call("o_manual_spray_24_25", "FieldOpsApp__apply_pesticide_manual", original, op="WRITE")
    assert original["advance_time"] is False
    assert called[0]["advance_time"] is True
    assert compiler.engine.time_manager.time() == 800
    assert compiler.management_audit[0]["before"]["clock"] == 100
    assert compiler.management_audit[0]["after"]["clock"] == 800
    assert compiler.changes[0]["kind"] == "manual_spray_requires_real_operator_time"
