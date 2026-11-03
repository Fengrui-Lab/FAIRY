"""Native full-season episodes: fixed plans, fresh file replay, and decision counterexamples."""
from copy import deepcopy
import json

import pytest

from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class, list_scenarios
from fairy.scenarios.workflow import Workflow
from fairy.scenarios.management_extensions.catalog import SCENARIO_IDS
from fairy.scenarios.management_extensions.runtime import SEEDS, crop_options


def clean_ids(value):
    if isinstance(value, dict):
        return {k: clean_ids(v) for k, v in value.items() if k not in {"action_id", "op_id"}}
    if isinstance(value, (list, tuple)):
        return [clean_ids(v) for v in value]
    if isinstance(value, float):
        return round(value, 10)
    return value


def create(sid):
    s = get_scenario_class(sid)()
    s.setup()
    return s, Engine(None, s)


def stored_grain(scene):
    return sum(b.quantity_kg for b in scene.warehouse.grain_batches.values() if b.status == "stored")


def reference(sid):
    s, engine = create(sid)
    before = deepcopy(s.farm.get_state())
    stock = deepcopy(s.warehouse.get_state())
    clock = engine.time_manager.time()
    plan = engine.build_oracle_workflow(run_oracle=False)
    assert s.farm.get_state() == before
    assert s.warehouse.get_state() == stock
    assert engine.time_manager.time() == clock
    assert not s.farm.episode.orders
    return plan


@pytest.fixture(scope="module")
def completed_oracles():
    """Share completed, independently executed references for snapshot assertions."""
    cache = {}
    def get(sid):
        if sid not in cache:
            scene, engine = create(sid)
            engine.run_scenario_oracle(run_oracle=True)
            cache[sid] = scene, engine
        return cache[sid]
    return get


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_static_plan_executes_and_fresh_json_replay_matches(sid, tmp_path, completed_oracles):
    assert sid in list_scenarios()
    plan = reference(sid)
    path = tmp_path / "oracle.json"
    plan.save_workflow(str(path))
    direct, a = completed_oracles(sid)
    replay, b = create(sid)
    b.replay_workflow(Workflow.load_workflow(str(path)))
    assert a.evaluate().success, a.evaluate().message
    assert b.evaluate().success, b.evaluate().message
    assert a.time_manager.time() == b.time_manager.time()
    assert direct.warehouse.get_state() == replay.warehouse.get_state()
    assert clean_ids(direct.farm.get_state()) == clean_ids(replay.farm.get_state())
    assert all(r.harvested for r in replay.farm._ridges)
    assert stored_grain(replay) > 0
    assert replay.farm.field_area_m2 == (18867.2 if "discount" in sid else 12864.0)
    metadata = b.evaluate().metadata
    assert metadata["purchase_cost_minor"] == (14387 if "discount" in sid else 22765 if "total_cost" in sid else 0)
    assert metadata["budget_remaining_minor"] == (6517 if "discount" in sid else 5107 if "total_cost" in sid else 83616)
    assert len(replay.farm.physics.crop_backend.export_state()["runs"]) == 64


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_do_nothing_and_missing_storage_fail(sid):
    s, engine = create(sid)
    assert not engine.evaluate().success
    plan = reference(sid)
    del plan.dag["store_00"]
    for step in plan.dag.values():
        step.depends_on = [x for x in step.depends_on if x != "store_00"]
    engine.replay_workflow(plan)
    assert not engine.evaluate().success


@pytest.mark.parametrize("sid", SCENARIO_IDS[:2])
def test_wrong_rotation_is_executable_but_fails_rule(sid):
    plan = reference(sid)
    plan.dag["select"].tool_args.update(crop_id="soybean", cultivar_id=SEEDS["soybean"])
    # Same land boundary: soybean uses two rows and 40 plants/m² here.
    for name, step in plan.dag.items():
        if name == "load_00":
            step.tool_args.update(seed_type=SEEDS["soybean"], count=257280)
        elif name == "plant_32":
            # Insert a second public load when the first 32 ridges empty the hopper.
            from fairy.scenarios.workflow import WorkflowStep
            previous = list(plan.dag).index(name)
            anchor = list(plan.dag)[previous-1]
            extra = WorkflowStep(name="counterfactual_load_32", tool_name="Tractor__load_seeds", tool_args={"seed_type":SEEDS["soybean"],"count":257280}, depends_on=[anchor])
            step.depends_on = [extra.name]
            items=list(plan.dag.items());items.insert(previous,(extra.name,extra));plan.dag=dict(items)
        if step.tool_name == "Tractor__plant_seeds":
            step.tool_args.update(depth_cm=4., seed_spacing_cm=20/3)
        if step.tool_name == "Warehouse__dry_grain":
            step.tool_args["target_moisture_pct"] = 13.
    s, engine = create(sid)
    engine.replay_workflow(plan)
    result = engine.evaluate()
    assert result.metadata["crop_establishment_completed"]
    assert not result.metadata["rotation_rule_satisfied"]
    assert not result.success
    # The decision rule uses evidence, not the scenario's ID or oracle crop.
    s.farm.episode.soil_report["scn_eggs_per_100cc"] = 100
    assert engine.evaluate().metadata["rotation_rule_satisfied"]


@pytest.mark.parametrize("sid,offer,cost", [(SCENARIO_IDS[2], "regular", 15986), (SCENARIO_IDS[3], "low_sticker", 22906)])
def test_legal_expensive_choice_grows_crop_but_fails_cost(sid, offer, cost):
    plan = reference(sid)
    plan.dag["purchase"].tool_args["offer_id"] = offer
    s, engine = create(sid)
    engine.replay_workflow(plan)
    result = engine.evaluate()
    assert result.metadata["crop_establishment_completed"]
    assert result.metadata["purchase_cost_minor"] == cost
    assert result.metadata["cost_regret_minor"] > 0
    assert not result.success


def test_purchase_retries_budget_and_supply_are_atomic():
    s, _ = create(SCENARIO_IDS[2])
    before = deepcopy(s.farm.get_state()), deepcopy(s.warehouse.get_state())
    assert "error" in s.market.purchase_seed("discount", -1, "bad")
    assert "error" in s.market.purchase_seed("discount", 754688, "")
    assert before == (s.farm.get_state(), s.warehouse.get_state())
    receipt = s.market.purchase_seed("discount", 754688, "one")
    after = deepcopy(s.farm.get_state()), deepcopy(s.warehouse.get_state())
    assert receipt == s.market.purchase_seed("discount", 754688, "one")
    assert "error" in s.market.purchase_seed("regular", 754688, "one")
    assert "error" in s.market.purchase_seed("discount", 754688, "two")
    assert "error" in s.market.purchase_seed("regular", 754688, "three")  # remaining cash is below the regular lot price
    assert after == (s.farm.get_state(), s.warehouse.get_state())


def test_selection_preserves_land_and_locks_without_affecting_other_scene():
    s, _ = create(SCENARIO_IDS[0])
    other, _ = create(SCENARIO_IDS[0])
    original = deepcopy(s.farm.get_state()), deepcopy(s.warehouse.get_state())
    assert "error" in s.planning.select_crop("field", "maize", "SOYBEAN_901", "preplant-2019")
    assert original == (s.farm.get_state(), s.warehouse.get_state())
    assert "error" in s.tractor.level("field")
    s.planning.select_crop("field", "soybean", "SOYBEAN_901", "preplant-2019")
    assert s.farm.field_area_m2 == 12864.0 and s.sensor._farm_world_app is s.farm
    assert s.farm.crop_type == "soybean" and s.farm.physics.crop_backend.config.crop_name == "soybean"
    assert not other.farm.episode.selection
    assert "error" in s.planning.select_crop("field", "maize", "MAIZE_201", "preplant-2019")


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_state_roundtrip_includes_native_crop_history_budget_and_orders(sid, completed_oracles):
    s, engine = completed_oracles(sid)
    saved = json.loads(json.dumps(s.farm.get_state()))
    old = deepcopy(s.farm.episode)
    s.farm.load_state(saved)
    assert s.farm.episode == old
    assert engine.evaluate().success


@pytest.mark.parametrize("sid,omitted", [(SCENARIO_IDS[0], "history"), (SCENARIO_IDS[1], "options"),
    (SCENARIO_IDS[2], "quotes"), (SCENARIO_IDS[3], "budget"), (SCENARIO_IDS[2], "weather")])
def test_missing_observation_fails_even_when_outcome_succeeds(sid, omitted):
    plan = reference(sid)
    del plan.dag[omitted]
    for step in plan.dag.values():
        step.depends_on = [d for d in step.depends_on if d != omitted]
    s, engine = create(sid)
    engine.replay_workflow(plan)
    result = engine.evaluate()
    assert result.metadata["crop_establishment_completed"]
    assert not result.success


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_native_and_business_state_restore_into_fresh_world(sid, completed_oracles):
    source, a = completed_oracles(sid)
    raw = json.loads(json.dumps(source.farm.get_state()))
    target, b = create(sid)
    b.time_manager.reset(a.time_manager.time())
    # Restore the chosen crop before admitting its cultivar-tagged grain batches.
    target.farm.load_state(raw)
    target.warehouse.load_state(json.loads(json.dumps(source.warehouse.get_state())))
    assert target.farm.episode == source.farm.episode
    assert clean_ids(target.farm.get_state()) == clean_ids(source.farm.get_state())
    # Continue real native growth after restoration, rather than checking just labels.
    control, c = create(sid)
    c.time_manager.reset(a.time_manager.time())
    control.farm.load_state(raw)
    control.warehouse.load_state(json.loads(json.dumps(source.warehouse.get_state())))
    control.system.advance_time(days=1)
    target.system.advance_time(days=1)
    assert clean_ids(target.farm.get_state()) == clean_ids(control.farm.get_state())


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_each_scene_owns_literal_full_season_oracle(sid):
    import ast
    import inspect
    from pathlib import Path
    cls = get_scenario_class(sid)
    assert Path(inspect.getfile(cls)).name == sid + ".py"
    assert "build_events_flow" in cls.__dict__
    tree = ast.parse(inspect.getsource(inspect.getmodule(cls)))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "build_events_flow")
    assert not any(isinstance(n, (ast.For, ast.While, ast.If)) for n in ast.walk(method))
    plan = reference(sid)
    methods = {step.tool_name.split("__")[-1] for step in plan.dag.values()}
    assert {"plant_seeds", "irrigate", "harvest", "unload_grain", "dry_grain", "store_grain"} <= methods


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_no_irrigation_loses_yield_and_fails_target(sid):
    plan = reference(sid)
    # Keep the exact operation duration when omitting water. Otherwise the
    # fixed waits would move harvest earlier and confound water with calendar.
    for step in plan.dag.values():
        if step.tool_name == "Irrigation__irrigate":
            seconds = step.tool_args["hours"]*3600 + 300
            step.tool_name = "SystemApp__advance_time"
            step.tool_args = {"seconds": seconds}
    s, engine = create(sid)
    engine.replay_workflow(plan)
    result = engine.evaluate()
    assert result.metadata["stored_grain_kg"] > 0
    assert result.metadata["stored_grain_kg"] < result.metadata["yield_target_kg"]
    assert not result.success


def test_endowed_seed_is_valued_when_consumed_not_merely_loaded():
    s, _ = create(SCENARIO_IDS[0])
    assert s.production_cost_minor() == 0
    s.tractor.load_seeds("MAIZE_201", 1000)
    assert s.production_cost_minor() == 0


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_matches_original_full_season_geometry_resources_and_capacity_splits(sid):
    from fairy.scenarios.two_farm.scenario_two_farm_wofost_soybean_maize_full_season import NUM_RIDGES, FIELD_LENGTH_M
    s, _ = create(sid)
    assert (s.farm.num_ridges, s.farm.field_length_m) == (NUM_RIDGES, FIELD_LENGTH_M)
    assert s.farm.ridge_width_m == (1.1 if "discount" in sid else .75)
    opt = crop_options(s.farm)[s.expected_crop]
    assert opt["required_seeds"] == (754688 if "discount" in sid else 85760)
    assert s.warehouse.storage_capacity_kg == 20000
    assert s.warehouse.drying_capacity_kg_per_day == 20000
    assert s.warehouse.stock.fuel_liters == 800
    assert s.warehouse.stock.fertilizer_kg >= s.farm.field_area_m2*.06
    plan = reference(sid)
    planting = [step for step in plan.dag.values() if step.tool_name == "Tractor__plant_seeds"]
    harvest = [step for step in plan.dag.values() if step.tool_name == "Tractor__harvest"]
    loading = [step for step in plan.dag.values() if step.tool_name == "Tractor__load_seeds"]
    assert len(planting) == len(harvest) == 16
    assert sum(step.tool_args["count"] for step in loading) == opt["required_seeds"]
    assert all(step.tool_args["count"] <= 300000 for step in loading)
    assert len(loading) == (3 if "discount" in sid else 1)
    for operation in planting+harvest:
        assert operation.tool_args["end_ridge"]-operation.tool_args["start_ridge"]+1 <= 4
    for step in plan.dag.values():
        if step.tool_name == "Tractor__apply_fertilizer":
            assert step.tool_args["end_ridge"]-step.tool_args["start_ridge"]+1 <= 10
        if step.tool_name == "Tractor__load_fertilizer":
            assert step.tool_args["kg"] <= 500


@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_total_production_budget_includes_consumed_endowments(sid, completed_oracles):
    scene, engine = completed_oracles(sid)
    cost = scene.production_cost_minor()
    assert cost > scene.farm.episode.spent
    budget = scene.production_budget_minor
    assert cost <= budget
    try:
        scene.production_budget_minor = cost-1
        assert "Whole-season production budget exceeded" in engine.evaluate().message
    finally:
        scene.production_budget_minor = budget
    assert engine.evaluate().success
    if not scene.rotation:
        assert scene.market.get_budget()["accounted_production_cost_minor"] == cost
        assert scene.market.get_budget()["production_budget_remaining_minor"] == budget-cost


def test_maize_initial_states_match_before_sharing_candidate_comparisons():
    states = []
    for sid in (SCENARIO_IDS[0], SCENARIO_IDS[1], SCENARIO_IDS[3]):
        scene, _ = create(sid)
        if scene.rotation:
            scene.planning.select_crop("field", "maize", "MAIZE_201", "preplant-2019")
        raw = scene.farm.get_state()
        raw.pop("management_extension")
        # The shared candidate plans finish in September. B1/B2 now have an
        # explicit October-only rain override; all other inputs still match.
        raw["physics_state"]["scenario_metadata"].pop("weather_override", None)
        for kind in ("day_cache", "day_overrides"):
            for day, weather in raw["physics_state"]["weather_generator"][kind].items():
                if day.startswith("2019-10-"):
                    weather["rain_mm"] = 0.
                    weather["is_raining"] = False
        states.append(raw)
    assert states[0] == states[1] == states[2]
