"""Offline bounded search through real public tools; never called by scene setup."""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta
from itertools import product
import json
import hashlib
from pathlib import Path
from zoneinfo import ZoneInfo

from fairy.controllers.engine import Engine
from .scenario import ScenarioJointCropOperatingMargin
from fairy.scenarios.management_extensions.runtime import crop_options, SEEDS

HERE = Path(__file__).resolve().parent


def execute_candidate(
    fertilizer_kg_ha, maize_water_mm, soybean_water_mm, irrigation_shift_days=0
):
    scene = ScenarioJointCropOperatingMargin(calibrating=True)
    scene.setup()
    engine = Engine(None, scene)
    trace = []

    def call(app, method, **args):
        name = f"step{len(trace):04d}"
        before = engine.time_manager.time()
        result = getattr(app, method)(**args)
        trace.append(
            {
                "name": name,
                "tool_name": app.name + "__" + method,
                "tool_args": args,
                "time_before": before,
                "time_after": engine.time_manager.time(),
                "content": result,
            }
        )
        if isinstance(result, dict) and (
            result.get("error")
            or result.get("status") in {"partial", "irrigation_pending"}
        ):
            raise RuntimeError(f"{app.name}.{method}: {result}")
        return result

    def until(day):
        target = (
            datetime.fromisoformat("2019-" + day + "T07:00:00")
            .replace(tzinfo=ZoneInfo("Europe/Paris"))
            .timestamp()
        )
        delta = target - engine.time_manager.time()
        if delta < 0:
            raise RuntimeError(f"Passed candidate management date {day}")
        if delta:
            call(scene.system, "advance_time", seconds=delta)

    def observe(farm):
        call(scene.weather, "get_current_weather")
        call(scene.weather, "get_forecast", days=7)
        call(scene.sensors[farm.crop_id], "read_soil_sensors")
        call(farm, "get_ridge_range_state", start=0, end=farm.num_ridges - 1)

    try:
        call(scene.accounts, "get_accounts")
        call(scene.warehouse, "get_inventory")
        for farm in scene.farms:
            crop = farm.crop_id
            opt = crop_options(farm)[crop]
            call(farm, "get_crop_capabilities")
            observe(farm)
            call(scene.tractor, "get_status")
            call(scene.tractor, "attach_implement", implement="grader")
            call(scene.tractor, "level", farm_id=crop)
            call(scene.tractor, "detach_implement")
            fertilizer = (
                fertilizer_kg_ha * farm.field_area_m2 / 10000
                if crop == "maize"
                else 0.0
            )
            if fertilizer:
                call(scene.tractor, "load_fertilizer", kg=fertilizer / 2)
                call(
                    scene.tractor,
                    "base_fertilize",
                    farm_id=crop,
                    total_kg=fertilizer / 2,
                )
            call(scene.tractor, "attach_implement", implement="furrower")
            call(
                scene.tractor,
                "form_ridges",
                farm_id=crop,
                ridge_width_m=farm.ridge_width_m,
            )
            call(scene.tractor, "detach_implement")
            call(scene.tractor, "attach_implement", implement="seeder")
            call(
                scene.tractor,
                "load_seeds",
                seed_type=SEEDS[crop],
                count=opt["required_seeds"],
            )
            for start in range(0, farm.num_ridges, 4):
                call(
                    scene.tractor,
                    "plant_seeds",
                    farm_id=crop,
                    start_ridge=start,
                    end_ridge=start + 3,
                    depth_cm=opt["depth_cm"],
                    seed_spacing_cm=opt["spacing_cm"],
                )
            call(scene.tractor, "detach_implement")
        until("06-10")
        for farm in scene.farms:
            observe(farm)
        if fertilizer_kg_ha:
            maize = scene.farms[0]
            total = fertilizer_kg_ha * maize.field_area_m2 / 10000 / 2
            for start in range(0, 16, 10):
                end = min(start + 9, 15)
                amount = total * (end - start + 1) / 16
                call(scene.tractor, "load_fertilizer", kg=amount)
                call(
                    scene.tractor,
                    "apply_fertilizer",
                    farm_id="maize",
                    start_ridge=start,
                    end_ridge=end,
                    kg_per_ridge=total / 16,
                )
        # Same dates across candidates. Both fields evolve whenever any tool/wait advances the common clock.
        schedule = [
            ("07-01", "maize", maize_water_mm / 4),
            ("07-05", "soybean", soybean_water_mm / 3),
            ("07-15", "maize", maize_water_mm / 4),
            ("07-20", "soybean", soybean_water_mm / 3),
            ("08-01", "maize", maize_water_mm / 4),
            ("08-05", "soybean", soybean_water_mm / 3),
            ("08-15", "maize", maize_water_mm / 4),
        ]
        for day, crop, mm in schedule:
            shifted = (
                datetime.fromisoformat("2019-" + day)
                + timedelta(days=irrigation_shift_days)
            ).strftime("%m-%d")
            until(shifted)
            farm = next(f for f in scene.farms if f.crop_id == crop)
            observe(farm)
            if mm:
                call(scene.irrigation[crop], "irrigate", start=0, end=15, hours=mm / 5)
                call(scene.system, "advance_time", days=1)
                call(scene.sensors[crop], "read_soil_sensors")
        for crop, day in (("soybean", "09-09"), ("maize", "09-20")):
            target = (
                datetime.fromisoformat("2019-" + day + "T07:00:00")
                .replace(tzinfo=ZoneInfo("Europe/Paris"))
                .timestamp()
            )
            if target > engine.time_manager.time():
                until(day)
            farm = next(f for f in scene.farms if f.crop_id == crop)
            caps = call(farm, "get_crop_capabilities")
            while True:
                weather = call(scene.weather, "get_current_weather")
                states = call(farm, "get_ridge_range_state", start=0, end=15)["ridges"]
                ready = all(
                    r["growth_stage"] in caps["harvest"]["stage_codes"]
                    and r["grain_moisture_pct"] <= caps["harvest"]["max_moisture_pct"]
                    for r in states
                )
                if ready and weather["rainfall_mm"] == 0:
                    break
                if (
                    engine.time_manager.time() + 86400
                    > scene.start_time + scene.duration
                ):
                    raise RuntimeError(
                        "No observed safe harvest window before deadline"
                    )
                call(scene.system, "advance_time", days=1)
            call(scene.sensors[crop], "read_soil_sensors")
            call(scene.tractor, "refuel", liters=100.0)
            call(scene.tractor, "attach_implement", implement="harvester")
            for start in range(0, 16, 4):
                batch = f"{crop}-2019-{start:02d}"
                call(
                    scene.tractor,
                    "harvest",
                    farm_id=crop,
                    start_ridge=start,
                    end_ridge=start + 3,
                )
                call(scene.tractor, "unload_grain", batch_id=batch)
                call(
                    scene.warehouse,
                    "dry_grain",
                    batch_id=batch,
                    target_moisture_pct=13.0 if crop == "soybean" else 14.0,
                )
                call(scene.warehouse, "store_grain", batch_id=batch)
            call(scene.tractor, "detach_implement")
        result = call(scene.accounts, "get_accounts")
        validation = scene.validate()
        return {
            "candidate": [
                fertilizer_kg_ha,
                maize_water_mm,
                soybean_water_mm,
                irrigation_shift_days,
            ],
            "feasible": validation.success,
            "error": None if validation.success else validation.message,
            **result,
            "trace": trace,
        }
    except Exception as exc:
        return {
            "candidate": [
                fertilizer_kg_ha,
                maize_water_mm,
                soybean_water_mm,
                irrigation_shift_days,
            ],
            "feasible": False,
            "error": f"{type(exc).__name__}: {exc}",
            "trace": trace,
        }


def choose(rows):
    feasible = [r for r in rows if r["feasible"]]
    if not feasible:
        raise RuntimeError("No feasible candidate; do not publish an Oracle")
    selected = max(
        feasible,
        key=lambda r: (
            r["net_operating_margin"],
            -r["water_m3"],
            -r["fertilizer_product_kg"],
        ),
    )
    pareto = [
        r
        for r in feasible
        if not any(
            q["stored_grain_value"] >= r["stored_grain_value"]
            and q["production_cost"] <= r["production_cost"]
            and q["water_m3"] <= r["water_m3"]
            and (
                q["stored_grain_value"] > r["stored_grain_value"]
                or q["production_cost"] < r["production_cost"]
                or q["water_m3"] < r["water_m3"]
            )
            for q in feasible
        )
    ]
    clean = lambda r: {k: v for k, v in r.items() if k != "trace"}
    rejection_counts = Counter(
        "shared_water_supply_exceeded"
        if "Shared seasonal water supply exceeded" in str(row.get("error"))
        else str(row.get("error") or "unspecified_infeasibility")
        for row in rows
        if not row["feasible"]
    )
    return {
        "rejection_counts": dict(rejection_counts),
        "scope": "Finite candidates: maize fertilizer product [0,300,600] kg/ha, each crop irrigation [0,60,120,180] mm; fixed dates, cultivar, weather, geometry and public prices. No claim of global optimum.",
        "candidate_count": len(rows),
        "feasible_count": len(feasible),
        "selected": clean(selected),
        "cropwise_max_kg_not_jointly_attainable": {
            crop: max(r["stored_kg_by_crop"][crop] for r in feasible)
            for crop in ("maize", "soybean")
        },
        "maximum_joint_grain_value": clean(
            max(feasible, key=lambda r: r["stored_grain_value"])
        ),
        "pareto": list(map(clean, pareto)),
    }, selected


def explain_step(step):
    app, method = step["tool_name"].split("__")
    args = step["tool_args"]
    purposes = {
        "get_accounts": "读取公开粮价、成本口径及共享水余额，按实际消耗核算两作物经营收益",
        "get_inventory": "核对共同库存，机上物资另计，不重复扣费",
        "get_crop_capabilities": "核对当前作物的播种、成熟、收获及储存规则",
        "get_current_weather": "核对当前真实天气，作业不能依赖未公开未来状态",
        "get_forecast": "读取公开七日预报，确认管理窗口",
        "read_soil_sensors": "观察本地块土壤状态，不把另一地块观测替代本场",
        "get_ridge_range_state": "检查本地块全部垄的生育阶段和籽粒水分",
        "get_status": "核对共享拖拉机机具、燃油、种肥箱和粮箱",
        "attach_implement": "切换到随后作业所需机具，沿用同一设备状态",
        "detach_implement": "卸下当前机具，准备下一项作业",
        "level": "按实际地块面积整平，消耗时间与燃油",
        "load_fertilizer": "从共同库存装入本次所需肥料；装载本身不计施用成本",
        "base_fertilize": "播前均匀施入选定肥料产品的一半，由原生氮过程响应",
        "form_ridges": "按地块实际几何起垄，不改变土地面积",
        "load_seeds": "按作物身份装入本田所需种子，不能混装另一作物",
        "plant_seeds": "完成该批四垄播种，按种子数量和密度实际扣料",
        "apply_fertilizer": "6月营养管理窗口施入剩余肥料；剂量来自有限候选实测选择",
        "irrigate": "按选定跨作物水量分配灌溉，工具检查土壤和900m³共享供水上限",
        "advance_time": "等待管理或成熟观测窗口，两地块沿公共时钟持续生长",
        "refuel": "从共同库存补充油箱，只扣实际转入量",
        "harvest": "公开观测满足成熟和水分条件后收获四垄，仍检查天气、通行和粮箱容量",
        "unload_grain": "卸空本批粮箱并保留地块、作物和垄号来源",
        "dry_grain": "按作物安全水分处理实际粮批，核算真实干燥吞吐",
        "store_grain": "将安全粮批实际入库，按对应作物价格计值",
    }
    return f"{app}: {purposes.get(method, method)}；参数 {args}"


def publish(reference, selected):
    reference["workflow_steps"] = len(selected["trace"])
    scene = ScenarioJointCropOperatingMargin(calibrating=True)
    scene.setup()
    reference["input_signature"] = scene.input_signature()
    reference["input_fingerprint"] = scene.input_fingerprint()
    HERE.joinpath("reference.json").write_text(
        json.dumps(reference, ensure_ascii=False, indent=2)
    )
    lines = [
        '"""Frozen public-tool Oracle, generated after finite candidate exploration."""',
        "from fairy.types import EventRegisterer",
        "from fairy.scenarios.management_extensions.common import capture_step, finish_capture",
        "",
        "def capture_reference(scene):",
        "    apps = {app.name: app for app in scene.apps}",
        "    with EventRegisterer.capture_mode() as events:",
        "        previous = None",
    ]
    for t in selected["trace"]:
        app, method = t["tool_name"].split("__")
        args = ", ".join(f"{k}={v!r}" for k, v in t["tool_args"].items())
        lines.append(
            f"        previous = capture_step(previous, apps[{app!r}].{method}({args}), {t['name']!r}, {explain_step(t)!r})"
        )
    lines.append("    return finish_capture(scene, events)")
    HERE.joinpath("oracle.py").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    input_scene = ScenarioJointCropOperatingMargin(calibrating=True)
    input_scene.setup()
    manifest = {
        "input_signature": input_scene.input_signature(),
        "input_fingerprint": input_scene.input_fingerprint(),
        "source_sha256": {
            str(f.relative_to(HERE.parents[4])): hashlib.sha256(
                f.read_bytes()
            ).hexdigest()
            for f in sorted(HERE.glob("*.py"))
        },
    }
    (args.output / "input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    grid = (
        [(600.0, 180.0, 60.0)]
        if args.smoke
        else list(
            product(
                (0.0, 300.0, 600.0),
                (0.0, 60.0, 120.0, 180.0),
                (0.0, 60.0, 120.0, 180.0),
            )
        )
    )
    # Deliberately retain infeasible supply combinations, demonstrating hard-tool enforcement.
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(execute_candidate, *values): values for values in grid}
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            slug = "_".join(f"{x:g}" for x in row["candidate"])
            (args.output / (slug + ".json")).write_text(
                json.dumps(row, ensure_ascii=False, indent=2)
            )
            print(
                row["candidate"],
                row["feasible"],
                row.get("net_operating_margin"),
                row.get("error"),
                flush=True,
            )
    reference, selected = choose(rows)
    (args.output / "summary.json").write_text(
        json.dumps(reference, ensure_ascii=False, indent=2)
    )
    if args.publish:
        if args.smoke:
            raise ValueError("Smoke results cannot publish a calibrated reference")
        publish(reference, selected)
    print(json.dumps(reference, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
