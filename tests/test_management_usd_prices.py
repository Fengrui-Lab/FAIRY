"""Economic unit, cash and signed-comparison regressions for extension-only pricing."""

import importlib
import inspect
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from fairy.scenarios.management_extensions import SCENARIO_MODULES
from fairy.scenarios.management_extensions.china_market_prices import (
    operating_prices,
    usd,
    usd_cents,
)
from fairy.scenarios.management_extensions.evaluation.oracle_comparison import (
    biological_grain_kg,
    compare_to_oracle,
    recovered_grain_kg,
    relative_difference,
)


def test_farmer_units_and_whole_payment_rounding():
    p = operating_prices()
    assert p["currency"] == "USD"
    # Adopted 80 CNY/4200 grains proxy; do not round one grain to zero cents.
    assert 4200 * p["seed_per_unit"]["MAIZE_201"] == pytest.approx(usd(80))
    assert 1000 * p["seed_per_unit"]["SOYBEAN_901"] == pytest.approx(usd(7.6 * 0.2))
    assert p["fertilizer_per_kg"] == pytest.approx(usd(2.05))
    assert 100 * p["fuel_per_liter"] == pytest.approx(usd(663))
    assert usd_cents(80) == 1115
    assert p["water_per_m3"] < operating_prices(high_water=True)["water_per_m3"]


def test_loading_maps_cannot_mutate_another_scenario_price_table():
    a, b = operating_prices(), operating_prices()
    a["seed_per_unit"]["MAIZE_201"] = 1000
    assert b["seed_per_unit"]["MAIZE_201"] < 0.01


def test_biological_yield_loss_is_signed_and_separate_from_stored_weight():
    a = {
        "currency": "USD",
        "production_cost": 150.0,
        "net_operating_margin": 300.0,
        "biological_kg_by_crop": {"maize": 310.0},
        "recovered_kg_by_crop": {"maize": 70.0},
        "stored_kg_by_crop": {"maize": 150.0},
    }
    o = {
        "currency": "USD",
        "production_cost": 100.0,
        "net_operating_margin": 200.0,
        "biological_kg_by_crop": {"maize": 200.0},
        "recovered_kg_by_crop": {"maize": 100.0},
        "stored_kg_by_crop": {"maize": 100.0},
    }
    compare_to_oracle(a, o)
    c = a["oracle_comparison"]
    assert c["metrics"]["production_cost"]["relative_difference_pct"] == 50
    assert c["metrics"]["production_cost"]["better"] == "lower"
    assert c["metrics"]["net_operating_margin"]["relative_difference_pct"] == 50
    assert c["stored_kg_by_crop"]["maize"]["relative_difference_pct"] == 50
    assert a["yield_loss_pct"] == pytest.approx(-55)
    assert a["yield_loss_pct_by_crop"] == {"maize": pytest.approx(-55)}
    assert a["recovered_yield_loss_pct"] == 30
    assert a["recovered_yield_loss_pct_by_crop"] == {"maize": 30}
    assert a["stored_yield_loss_pct_by_crop"] == {"maize": -50}


def test_zero_and_negative_oracle_denominators_are_explicit():
    zero = relative_difference(10, 0, unit="USD", better="higher")
    assert zero["relative_difference"] is None and zero["difference"] == 10
    assert zero["undefined_reason"]
    negative = relative_difference(-50, -100, unit="USD", better="higher")
    assert negative["relative_difference_pct"] == -50
    assert negative["difference"] == 50 and negative["negative_denominator"]


def test_crops_and_seasons_are_matched_without_summing_unlike_kg():
    a = {"currency": "USD", "stored_kg_by_crop": {"soybean": 200}}
    o = {"currency": "USD", "stored_kg_by_crop": {"maize": 500}}
    compare_to_oracle(
        a,
        o,
        agent_seasons=[{"year": 2025, "crop_id": "soybean", "stored_grain_kg": 200}],
        oracle_seasons=[{"year": 2025, "crop_id": "maize", "stored_grain_kg": 500}],
    )
    c = a["oracle_comparison"]
    assert c["stored_kg_by_crop"] == {}
    assert c["seasons"][0]["yield"] is None and c["seasons"][0]["not_comparable_reason"]
    assert a["yield_loss_pct"] is None
    assert c["seasons"][0]["yield_loss_pct"] is None
    with pytest.raises(ValueError, match="currency"):
        compare_to_oracle(a, {"currency": "CNY"})


def test_same_crop_seasons_are_weighted_by_oracle_biological_yield():
    a = {"currency": "USD"}
    o = {"currency": "USD"}
    agent_seasons = [
        {
            "year": 2025,
            "biological_grain_kg": 20,
            "recovered_grain_kg": 0,
            "stored_grain_kg": 0,
        },
        {
            "year": 2026,
            "biological_grain_kg": 20,
            "recovered_grain_kg": 8,
            "stored_grain_kg": 0,
        },
    ]
    oracle_seasons = [
        {
            "year": 2025,
            "biological_grain_kg": 10,
            "recovered_grain_kg": 10,
            "stored_grain_kg": 10,
        },
        {
            "year": 2026,
            "biological_grain_kg": 40,
            "recovered_grain_kg": 20,
            "stored_grain_kg": 40,
        },
    ]
    compare_to_oracle(a, o, agent_seasons=agent_seasons, oracle_seasons=oracle_seasons)
    assert a["yield_loss_pct"] == 20
    first, second = a["oracle_comparison"]["seasons"]
    assert first["yield_loss_pct"] == -100
    assert second["yield_loss_pct"] == 50
    assert first["recovered_yield_loss_pct"] == 100
    assert second["recovered_yield_loss_pct"] == 60
    assert a["recovered_yield_loss_pct"] == pytest.approx(100 * (1 - 8 / 30))
    assert second["stored_yield_loss_pct"] == 100

    compare_to_oracle(a, o, agent_seasons=agent_seasons[:1], oracle_seasons=oracle_seasons)
    assert a["yield_loss_pct"] is None
    assert a["oracle_comparison"]["seasons"][0]["yield_loss_pct"] == -100


def test_missing_or_zero_biological_yield_baseline_does_not_use_stored_weight():
    a = {"currency": "USD", "biological_kg_by_crop": {"maize": 4, "soybean": 2}}
    o = {
        "currency": "USD",
        "biological_kg_by_crop": {"maize": 0},
        "stored_kg_by_crop": {"maize": 3, "soybean": 1},
    }
    compare_to_oracle(a, o)
    assert a["yield_loss_pct_by_crop"] == {"maize": None, "soybean": None}


def test_maturity_extrapolates_biology_on_a_copy_and_never_counts_unharvested_grain():
    from types import SimpleNamespace

    class Farm:
        ridge_area_m2 = 250

        def __init__(self):
            self._ridges = [SimpleNamespace(planted=True, harvested=False)]
            self.yield_state = SimpleNamespace(
                biological_yield_g_m2=10,
                recovered_yield_g_m2_at_market_moisture=2,
                harvested=False,
            )
            self.physics = SimpleNamespace(
                last_physics_sim_time=0,
                yield_recovery=SimpleNamespace(states={0: self.yield_state}),
            )

        def is_ridge_mature(self, index):
            return self.yield_state.biological_yield_g_m2 == 100

        def advance_physics_time(self, timestamp):
            self.physics.last_physics_sim_time = timestamp
            self.yield_state.biological_yield_g_m2 = 100

    farm = Farm()
    assert biological_grain_kg(farm, deadline=86400) == 25
    assert biological_grain_kg(farm) == 2.5
    assert recovered_grain_kg(farm) == 0


def test_affordable_usd_fertilizer_order_survives_cash_checkpoint():
    from types import SimpleNamespace
    from fairy.scenarios.management_extensions.apps.fertilizer_market_app import (
        FertilizerMarket,
    )
    from fairy.time_manager import SimulationTimeManager
    from datetime import date

    farm = SimpleNamespace(
        _inventory=SimpleNamespace(fertilizer_kg=125.0),
        simulation_date=lambda timestamp: date(2024, 10, 1),
    )
    tractor = SimpleNamespace(_fertilizer_spreader_kg=0.0)
    app = FertilizerMarket(
        farm,
        tractor,
        cash=usd(341.25),
        initial_fertilizer_kg=125.0,
        initial_unit_cost=usd(2.05),
        offers=[
            {
                "offer_id": "advance",
                "announced_on": "2024-05-01",
                "valid_from": "2024-05-01",
                "valid_until": "2025-04-30",
                "unit_price": usd(1.95),
            }
        ],
    )
    app.register_time_manager(SimulationTimeManager())
    receipt = app.purchase_fertilizer("advance", 175.0, "reserve")
    assert receipt["paid"] == pytest.approx(usd(341.25))
    assert app.cash == 0 and farm._inventory.fertilizer_kg == 300
    app.load_state(app.get_state())
    assert app.cash == 0


def test_oracle_export_preserves_live_briefing_overrides(tmp_path):
    from types import SimpleNamespace
    from fairy.apps.agent_user_interface import AgentUserInterface
    from fairy.scenarios.management_extensions.management_oracles import (
        export_candidate,
    )

    scene = SimpleNamespace(
        input_fingerprint=lambda: "USD-input",
        input_signature=lambda: {"currency": "USD"},
        prepare_oracle_capture=lambda: True,
        apps=[AgentUserInterface()],
        scenario_input="Current brief user task",
    )
    selected = {
        "feasible": True,
        "input_fingerprint": "USD-input",
        "trace": [
            {
                "tool_name": "AgentUserInterface__send_message_to_agent",
                "tool_args": {
                    "content": "Captured detailed guidance must not be frozen"
                },
            }
        ],
    }
    export_candidate(scene, {}, selected, tmp_path)
    source = (tmp_path / "oracle_method_draft.py").read_text()
    namespace = {}
    exec(compile(source, "oracle_method_draft.py", "exec"), namespace)
    events = namespace["build_events_flow"](scene)
    assert events[0].kwargs["content"] == scene.scenario_input
    assert "Captured detailed guidance" not in source


@pytest.mark.parametrize(
    "scenario_id",
    [
        "scenario_multiobjective_seed_discount",
        "scenario_multiseason_scn_continue_maize",
    ],
)
def test_short_task_keeps_prices_queryable_without_adding_expert_guidance(scenario_id):
    from fairy.scenarios.registry import get_scenario_class

    scene = get_scenario_class(scenario_id)(detailed_briefing=False)
    scene.setup()
    assert scene.scenario_input == scene.BASIC_BRIEFING
    if scene.rotation:
        result = scene.planning.get_season_context("field")
    else:
        result = scene.market.get_budget()
        assert result["production_budget_minor"] > result["initial_minor"]
    assert result["currency"] == result["prices"]["currency"] == "USD"
    assert result["prices"]["fuel_per_liter"] == pytest.approx(usd(6.63))


def test_legacy_oracle_publisher_keeps_following_lifecycle_methods(
    tmp_path, monkeypatch
):
    import scripts.calibrate_management_extension_oracles as calibration

    path = tmp_path / "fairy/scenarios/management_extensions/example.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "class Example:\n    best_tested_yield_kg = 1.0\n    oracle_cost_minor = 1\n    def build_events_flow(self):\n        return []\n    def __post_init__(self):\n        self.guard = 'preserved'\n    def custom_hook(self):\n        return 42\n"
    )
    monkeypatch.setattr(calibration, "ROOT", tmp_path)
    calibration.publish(
        "example",
        {"price_book_id": "USD-test", "production_cost_minor": 200, "trace": []},
        3.0,
    )
    namespace = {}
    exec(compile(path.read_text(), str(path), "exec"), namespace)
    scene = namespace["Example"]()
    scene.__post_init__()
    assert scene.guard == "preserved" and scene.custom_hook() == 42
    assert scene.best_tested_yield_kg == 3.0 and scene.oracle_cost_minor == 200


@pytest.mark.parametrize("module_name", SCENARIO_MODULES)
@pytest.mark.parametrize("detailed", [False, True])
def test_task_uses_queryable_prices_in_both_briefing_modes(module_name, detailed):
    from fairy.agents.agent.toolset_builder import build_toolset
    from fairy.controllers.engine import Engine
    from fairy.scenarios.scenario import Scenario

    module = importlib.import_module(
        f"fairy.scenarios.management_extensions.{module_name}"
    )
    cls = next(
        candidate
        for _, candidate in inspect.getmembers(module, inspect.isclass)
        if candidate.__module__ == module.__name__ and issubclass(candidate, Scenario)
    )
    scene = cls(seed=0, detailed_briefing=detailed)
    scene.setup()
    task = Engine(None, scene)._resolve_agent_task()
    _, _, tools = build_toolset(list(scene.apps))

    if "OperatingAccounts__get_accounts" in tools:
        query = "OperatingAccounts__get_accounts"
        account = tools[query]()
        prices = account["prices"]
        assert (
            account["operation_deadline"]
            == datetime.fromtimestamp(
                scene.start_time + scene.duration, ZoneInfo(scene.timezone_name)
            ).isoformat()
        )
    elif "CropRotation__get_crop_options" in tools:
        query = "CropRotation__get_crop_options"
        prices = tools[query]()["prices"]
    elif "SeasonCycle__get_season_ledger" in tools:
        query = "SeasonCycle__get_season_ledger"
        prices = tools[query]()["operating_accounts"]["prices"]
    elif "SeedMarket__get_budget" in tools:
        query = "SeedMarket__get_budget"
        prices = tools[query]()["prices"]
    else:
        query = "SeasonPlanning__get_season_context"
        prices = tools[query](farm_id="field")["prices"]

    if hasattr(scene, "cycle"):
        name = (
            "CropRotation"
            if "CropRotation__get_season_ledger" in tools
            else "SeasonCycle"
        )
        ledger = tools[f"{name}__get_season_ledger"]()
        assert ledger["fertilizer_budget_kg"] == scene.cycle.fertilizer_budget_kg
        assert ledger["water_budget_mm"] == scene.cycle.water_budget_mm
        assert len(ledger["seasons"]) == len(scene.cycle.seasons)
    if hasattr(scene, "rotation") and not scene.rotation:
        objective = tools["Field__get_crop_capabilities"]()["management_objective"]
        assert objective["minimum_stored_grain_kg"] == pytest.approx(
            0.99 * scene.best_tested_yield_kg
        )
        assert objective["maximum_production_cost_minor"] == scene.oracle_cost_minor
        assert (
            datetime.fromisoformat(objective["deadline"]).timestamp()
            == scene.start_time + scene.duration
        )

    if hasattr(scene, "fields"):
        geometry = [
            (
                f["ridge_count"] * f["ridge_width_m"] * f["field_length_m"],
                f["ridge_width_m"],
            )
            for f in scene.fields
        ]
    elif hasattr(scene, "field"):
        f = scene.field
        geometry = [
            (
                f["ridge_count"] * f["ridge_width_m"] * f["field_length_m"],
                f["ridge_width_m"],
            )
        ]
    elif "WheatField__get_field_info" in tools:
        geometry = [(scene.resources.area_ha * 10000,)]
    else:
        geometry = [(scene.farm.field_area_m2, scene.farm.ridge_width_m)]
    allowed = {round(number, 6) for pair in geometry for number in pair}
    exposed = {float(n) for n in re.findall(r"\d+(?:\.\d+)?", task)}
    if detailed and "WheatField__get_field_info" in tools:
        assert allowed <= exposed
    else:
        assert exposed == allowed
    if "WheatField__get_field_info" in tools:
        assert ("根区" in task) is detailed
    elif detailed:
        assert "read_soil_sensors" in task and "read_canopy_sensors" in task
    else:
        assert "read_soil_sensors" not in task and "read_canopy_sensors" not in task

    expected = asdict(scene.prices) if is_dataclass(scene.prices) else scene.prices
    assert prices == expected
    assert prices["currency"] == "USD"
    if "WheatField__get_field_info" in tools and detailed:
        assert "价格" in task
    else:
        assert query.replace("__", ".") in task
    assert "美元经营价格" not in task
    assert prices["price_book_id"] not in task
    assert not re.search(r"开头.{0,12}(?:价格|美元)", task)
    assert not re.search(
        r"\d+(?:\.\d+)?\s*(?:USD|CNY|美元|元)\s*/\s*(?:kg|ha|L|粒|m³|m3|亩)",
        task,
    )
