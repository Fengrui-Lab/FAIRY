#!/usr/bin/env python3
"""Run the finite oracle grid or replay an already tested reference. No fabricated reference."""

import argparse
from importlib import import_module
import json
from pathlib import Path
import sys

SCENARIOS = {
    "full_season": ("L3.scenario_sugarbeet_full_season", "ScenarioSugarBeetFullSeason"),
    "water_limit": ("L3.scenario_sugarbeet_water_limit", "ScenarioSugarBeetWaterLimit"),
    "nitrogen_limit": (
        "L3.scenario_sugarbeet_nitrogen_limit",
        "ScenarioSugarBeetNitrogenLimit",
    ),
    "high_water_price": (
        "L3.scenario_sugarbeet_high_water_price",
        "ScenarioSugarBeetHighWaterPrice",
    ),
    "rotation": (
        "L4.scenario_wheat_sugarbeet_rotation",
        "ScenarioWheatSugarBeetRotation",
    ),
    "seedling_rescue": ("L3.scenario_sugarbeet_seedling_rescue", "ScenarioSugarBeetSeedlingRescue"),
    "soil_water_priority": ("L3.scenario_sugarbeet_soil_water_priority", "ScenarioSugarBeetSoilWaterPriority"),
    "shared_resources": ("L4.scenario_wheat_sugarbeet_shared_resources", "ScenarioWheatSugarBeetSharedResources"),
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scenario", choices=SCENARIOS, default="full_season")
    p.add_argument("--input-dir", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument(
        "--objective", choices=("root_yield", "net_operating_margin", "rotation_yield")
    )
    p.add_argument("--max-candidates", type=int)
    p.add_argument("--replay-reference", type=Path)
    a = p.parse_args()
    if a.max_candidates is not None and a.max_candidates < 1:
        p.error("--max-candidates must be positive")
    module, name = SCENARIOS[a.scenario]
    cls = getattr(
        import_module("fairy.scenarios.management_extensions." + module), name
    )
    from fairy.scenarios.management_extensions.sugarbeet.oracle import (
        search,
        replay_workflow,
    )

    def factory():
        return cls(input_dir=a.input_dir, calibrating=True, seed=0)

    if a.replay_reference:
        reference = json.loads(a.replay_reference.read_text(encoding="utf-8"))
        probe = factory()
        probe.setup()
        if reference["input_fingerprint"] != probe.input_fingerprint():
            raise ValueError("Stale reference")
        result = replay_workflow(factory, reference["workflow"], reference["selected"])
        a.output.mkdir(parents=True, exist_ok=True)
        (a.output / "fresh_replay.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 0
    options = {}
    if cls.yield_management:
        from fairy.scenarios.management_extensions.sugarbeet.yield_oracles import YieldController, yield_policy_grid
        options = dict(policies=yield_policy_grid(cls.variant), controller_type=YieldController)
    result = search(
        factory,
        a.output,
        rotation=cls.rotation,
        objective=a.objective or cls.objective_metric,
        max_candidates=a.max_candidates,
        **options,
    )
    print(
        json.dumps(
            {
                k: result.get(k)
                for k in (
                    "status",
                    "complete",
                    "feasible_count",
                    "global_optimum_proven",
                )
            },
            ensure_ascii=False,
        )
    )
    return 0 if result.get("best") is not None else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Oracle blocked: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
