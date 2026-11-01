"""Offline finite management comparison, then publish literal calls in four scene files.

Never called by scene setup. Only public tools change farms. Raw native output is
used after a candidate finishes, for diagnostics. Failed candidates stay in the report.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime
import hashlib
import itertools
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.workflow import Workflow, WorkflowStep
from fairy.scenarios.management_extensions.catalog import SCENARIO_IDS
from fairy.scenarios.management_extensions.runtime import crop_options, SEEDS


def run_candidate(sid, fertilizer, water):
    s = get_scenario_class(sid)()
    s.setup()
    engine = Engine(None, s)
    prefix = engine.build_oracle_workflow(False)
    trace = []
    crop = s.expected_crop
    def call(name, app, method, reason, **args):
        before = engine.time_manager.time()
        result = getattr(app, method)(**args)
        entry = dict(name=name, app=app.name, method=method, args=args, reason=reason,
                     time_before=before, time_after=engine.time_manager.time())
        trace.append(entry)
        if not isinstance(result, dict) or result.get("error") or result.get("status") == "partial":
            raise RuntimeError(f"{name}: {result}")
        return result
    def until(day, name):
        timestamp = datetime.fromisoformat("2019-"+day+"T07:00:00").replace(tzinfo=ZoneInfo("Europe/Paris")).timestamp()
        delta = timestamp-engine.time_manager.time()
        if delta < 0:
            raise RuntimeError("Candidate passed its declared calendar window")
        call(name, s.system, "advance_time", f"等待至2019-{day}当地07:00；扣除先前工具真实耗时。", seconds=delta)
    def observe(label):
        call(label+"_weather", s.weather, "get_current_weather", "读取本日真实天气，核对作业窗口。")
        call(label+"_forecast", s.weather, "get_forecast", "读取近期降雨，交叉判断水分管理。", days=7)
        call(label+"_soil", s.sensor, "read_soil_sensors", "读取本场根区水分与土温。")
        call(label+"_stage", s.farm, "get_ridge_range_state", "读取全部64垄实际阶段，不用日期代替生育状态。", start=0, end=63)
    try:
        for step in prefix.dag.values():
            if step.name == "grader":
                break
            app, method = step.tool_name.split("__")
            call(step.name, next(a for a in s.apps if a.name == app), method,
                 (step.content or {}).get("oracle_reason", "执行独立场景文件中公开的初始操作。"), **step.tool_args)
        call("grader", s.tractor, "attach_implement", "挂载共享平地机。", implement="grader")
        call("level", s.tractor, "level", "整平64垄实际面积，燃油和耗时按面积计。", farm_id="field")
        call("detach_grader", s.tractor, "detach_implement", "整平后卸机具。")
        remaining = fertilizer/2
        index = 0
        while remaining > 1e-8:
            amount = min(500., remaining)
            call(f"base_load_{index:02d}", s.tractor, "load_fertilizer", "按500kg撒肥器容量装入基肥；实际扣仓。", kg=amount)
            call(f"base_fertilize_{index:02d}", s.tractor, "base_fertilize", "全田均匀施入这一箱基肥；产品46%N、回收率0.7，非直接改肥力。", farm_id="field", total_kg=amount)
            remaining -= amount
            index += 1
        call("ridger", s.tractor, "attach_implement", "挂载起垄机。", implement="furrower")
        call("ridges", s.tractor, "form_ridges", "按本场真实垄宽完成64垄起垄。", farm_id="field", ridge_width_m=s.farm.ridge_width_m)
        call("detach_ridger", s.tractor, "detach_implement", "起垄后卸机具。")
        call("planter", s.tractor, "attach_implement", "挂载已支持的播种机。", implement="seeder")
        opt = crop_options(s.farm)[crop]
        per_ridge = opt["required_seeds"]//64
        load_ridges = min(64, (300000//(per_ridge*4))*4)
        for start in range(0,64,4):
            if start % load_ridges == 0:
                amount = per_ridge*min(load_ridges,64-start)
                call(f"load_{start:02d}", s.tractor, "load_seeds", f"按30万粒种箱容量装入{amount}粒；这一箱用完再补种。", seed_type=SEEDS[crop], count=amount)
            call(f"plant_{start:02d}", s.tractor, "plant_seeds", f"第{start//4+1}趟播种第{start}—{start+3}垄；每垄{per_ridge}粒、株距{opt['spacing_cm']:g}cm、播深{opt['depth_cm']:g}cm。", farm_id="field", start_ridge=start, end_ridge=start+3, depth_cm=opt["depth_cm"], seed_spacing_cm=opt["spacing_cm"])
        call("detach_planter", s.tractor, "detach_implement", "64垄播完，种箱恰好用空后卸机具。")
        until("06-01", "wait_establishment")
        observe("establishment")
        call("canopy_establishment", s.sensor, "read_canopy_sensors", "结合冠层与全部垄状态确认建植；不做未建模的病虫诊断。")
        until("06-10", "wait_nutrition")
        observe("nutrition")
        call("canopy_nutrition", s.sensor, "read_canopy_sensors", "交叉复核营养与群体生长；大豆不例行施氮。")
        if fertilizer:
            call("topdress_refuel", s.tractor, "refuel", "追肥前从共同库存补足100L油箱；只转入剩余容量。", liters=100.)
            per_ridge_kg = fertilizer/128
            for start in range(0,64,10):
                end = min(start+9,63)
                amount = per_ridge_kg*(end-start+1)
                call(f"topdress_load_{start:02d}", s.tractor, "load_fertilizer", "仅装本趟所需肥料，受500kg容量限制。", kg=amount)
                call(f"topdress_{start:02d}", s.tractor, "apply_fertilizer", f"追肥第{start}—{end}垄，每趟最多10垄；全季产品总量{fertilizer:g}kg。", farm_id="field", start_ridge=start, end_ridge=end, kg_per_ridge=per_ridge_kg)
        dates = ["07-05","07-20","08-05"] if crop == "soybean" else ["07-01","07-15","08-01","08-15"]
        for i, day in enumerate(dates):
            label = f"management_{i+1}"
            until(day, "wait_"+label)
            observe(label)
            if water:
                call(label+"_water", s.irrigation, "irrigate", f"全64垄补水{water/len(dates):g}mm，实际用水{water/len(dates)*s.farm.field_area_m2/1000:g}m³；受180mm全季额度约束。", start=0, end=63, hours=water/len(dates)/5)
                call(label+"_settle", s.system, "advance_time", "等待下一日原生结算，避免重复交付尚未生效的灌水。", days=1)
                call(label+"_recheck", s.sensor, "read_soil_sensors", "次日复核供水后的实际水分。")
        until("08-20", "wait_late_fill")
        observe("late_fill")
        until("09-09" if crop == "soybean" else "09-20", "wait_harvest")
        observe("harvest")
        call("harvest_status", s.tractor, "get_status", "收获前复核油量、空粮箱与机具。")
        call("harvest_refuel", s.tractor, "refuel", "收获前从共同仓库补足100L油箱；不重置油量。", liters=100.)
        call("header", s.tractor, "attach_implement", "挂载本场已支持的收割机。", implement="harvester")
        for start in range(0,64,4):
            batch = f"season-2019-{start:02d}-{start+3:02d}"
            call(f"harvest_{start:02d}", s.tractor, "harvest", f"第{start//4+1}趟收获第{start}—{start+3}垄；工具检查真实成熟、天气、通行性和2t粮箱容量。", farm_id="field", start_ridge=start, end_ridge=start+3)
            call(f"unload_{start:02d}", s.tractor, "unload_grain", "每4垄卸一次，清空2t粮箱并记录来源，避免下一趟溢出。", batch_id=batch)
            call(f"dry_{start:02d}", s.warehouse, "dry_grain", "按作物标准水分干燥；共用20t/日额度，安全粮工具跳过。", batch_id=batch, target_moisture_pct=13. if crop == "soybean" else 14.)
            call(f"store_{start:02d}", s.warehouse, "store_grain", "这4垄安全粮批次入库；受20t总库容约束。", batch_id=batch)
        call("final_field", s.farm, "get_farm_overview", "逐垄核对最终收获状态。")
        call("final_inventory", s.warehouse, "get_inventory", "核对安全入库粮、种子、肥料和燃油账。")
        call("final_machine", s.tractor, "get_status", "确认空料斗、空粮箱，设备状态未重置。")
        if not s.rotation:
            call("final_budget", s.market, "get_budget", "核对种子预算余额及实付价格。")
        grain = sum(b.quantity_kg for b in s.warehouse.grain_batches.values() if b.status == "stored")
        return dict(feasible=True, crop=crop, area_m2=s.farm.field_area_m2, fertilizer_kg=fertilizer, water_mm=water,
                    stored_grain_kg=grain, production_cost_minor=s.production_cost_minor(), trace=trace)
    except Exception as exc:
        return dict(feasible=False, fertilizer_kg=fertilizer, water_mm=water, error=str(exc), trace=trace)


def publish(sid, selected, highest):
    path = ROOT / f"fairy/scenarios/management_extensions/{sid}.py"
    source = path.read_text()
    source = source[:source.index("    def build_events_flow(self):")]
    if "    # 已测试候选" in source:
        source = source[:source.index("    # 已测试候选")]
    source += f"    # 已测试候选最高安全入库量 {highest:.9f}kg；99%门槛 {highest*.99:.9f}kg。\n"
    source += f"    best_tested_yield_kg = {highest!r}\n    oracle_cost_minor = {selected['production_cost_minor']!r}\n\n"
    source += "    def build_events_flow(self):\n        # 每步字面写定；构图不执行、不读取未来状态、不运行优化器。\n        with EventRegisterer.capture_mode() as events:\n            previous = None\n"
    for t in selected["trace"]:
        args = ", ".join(f"{k}={v!r}" for k,v in t["args"].items())
        attr = {"SystemApp":"system", "Field":"farm", "WeatherApp":"weather", "Tractor":"tractor", "Sensor":"sensor", "Irrigation":"irrigation", "Warehouse":"warehouse", "SeedMarket":"market", "SeasonPlanning":"planning"}[t["app"]]
        source += f"            previous = capture_step(previous, self.{attr}.{t['method']}({args}), {t['name']!r}, {t['reason']!r})\n"
    source += "        return finish_capture(self, events)\n"
    path.write_text(source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT/"validation_runs/management_extensions_normal_scale/calibration")
    parser.add_argument("--crop", choices=["maize", "soybean"])
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--resume", action="store_true", help="Reuse completed rows in this output directory; use only with unchanged inputs")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    # Three maize scenes share identical biology, so search one and verify the
    # chosen management independently with each scene's own history/procurement.
    for sid in (SCENARIO_IDS[2], SCENARIO_IDS[3]):
        maize = sid == SCENARIO_IDS[3]
        if args.crop and args.crop != ("maize" if maize else "soybean"):
            continue
        area_ha = (12864. if maize else 18867.2)/10000
        # The old plot's intensities define a fresh finite search, never its old yield.
        # Fertilizer is kg product/ha here, converted to actual whole-field kg.
        grid = list(itertools.product([0., 155.3333333333, 310.6666666667, 466., 600.] if maize else [0.,155.3333333333,310.6666666667,600.], [0.,60.,120.,180.] if maize else [0.,60.,90.,120.,150.,180.]))
        if maize:
            grid += [(f,w) for f,w in itertools.product([533.3333333333,566.6666666667,583.3333333333,600.], [150.,165.,175.,180.]) if (f,w) not in grid]
        results = []
        progress = args.output_dir/(sid+".candidates.jsonl")
        previous = {}
        if args.resume and progress.exists():
            for line in progress.read_text().splitlines():
                row = json.loads(line)
                previous[(row["fertilizer_kg"],row["water_mm"])] = row
        elif progress.exists():
            progress.unlink()
        pending = [(round(f*area_ha,6),w) for f,w in grid if (round(f*area_ha,6),w) not in previous]
        def record(result):
            results.append(result)
            with progress.open("a") as out:
                out.write(json.dumps(result,ensure_ascii=False)+"\n")
            print(sid, result["fertilizer_kg"], result["water_mm"], result.get("stored_grain_kg"), result.get("production_cost_minor"), result.get("error", ""), flush=True)
        results.extend(previous[(round(f*area_ha,6),w)] for f,w in grid if (round(f*area_ha,6),w) in previous)
        if args.workers == 1:
            for fert,water in pending:
                record(run_candidate(sid,fert,water))
        else:
            with ProcessPoolExecutor(max_workers=args.workers) as pool:
                futures = [pool.submit(run_candidate,sid,fert,water) for fert,water in pending]
                for future in as_completed(futures):
                    record(future.result())
        results.sort(key=lambda r:(r["fertilizer_kg"],r["water_mm"]))
        feasible = [r for r in results if r["feasible"]]
        if not feasible:
            raise RuntimeError("No feasible full-season candidate")
        highest = max(r["stored_grain_kg"] for r in feasible)
        selected = min((r for r in feasible if r["stored_grain_kg"] >= .99*highest), key=lambda r:(r["production_cost_minor"], -r["stored_grain_kg"]))
        group = (SCENARIO_IDS[0],SCENARIO_IDS[1],sid) if maize else (sid,)
        for target in group:
            chosen = run_candidate(target, selected["fertilizer_kg"], selected["water_mm"]) if target != sid else selected
            if not chosen["feasible"]:
                raise RuntimeError(chosen)
            publish(target, chosen, highest)
            record = dict(scenario_id=target, criterion="minimum modeled production cost at >=99% best tested stored grain", highest_tested_kg=highest, threshold_kg=.99*highest, selected=chosen, compared_scenario=sid, candidates=results)
            (args.output_dir/f"{target}.json").write_text(json.dumps(record,indent=2,ensure_ascii=False)+"\n")
            summary.append({k:v for k,v in record.items() if k not in {"candidates","selected"}} | {"selected_yield_kg": chosen["stored_grain_kg"], "cost_minor": chosen["production_cost_minor"], "fertilizer_kg": chosen["fertilizer_kg"], "water_mm": chosen["water_mm"]})
    (args.output_dir/(f"summary-{args.crop}.json" if args.crop else "summary.json")).write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n")


if __name__ == "__main__":
    main()
