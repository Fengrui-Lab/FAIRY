"""Derive rice L1/L2 assets by replaying the installed frozen L3 tool plans.

No management policy is rerun and no L3 plan or physical limit is changed.
Every child stores its exact parent plan hash, half-open step range and states.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, sys, shutil, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO/'scripts'))
from fairy.apps.paddy.world import PaddyWorldApp
from fairy.controllers.engine import Engine
from fairy.scenarios.registry import get_scenario_class
from fairy.scenarios.rice.rice_scenario_catalog import SPECS, VARIANTS
from fairy.scenarios.rice import farm_checkpoint_state as artifacts
from fairy.scenarios.crop_challenges import artifacts as challenges
from fairy.scenarios.crop_challenges.catalog import TASKS
from fairy.scenarios.crop_challenges.runtime import measurements
from scripts.crop_challenge_policy import Recorder
from scripts.build_crop_challenges import replay_control, gates_for, normalize, weather_digest, measurements_from_checkpoint

RELEASE='rice_oracle_release_20261101_v1'
def digest_bytes(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p, value, compact=False):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,**({'separators':(',',':')} if compact else {'indent':2}))+'\n')
def method(s): return s['tool_name'].split('__')[-1]
def reading(s): return method(s).startswith(('get_','read_','inspect_','measure_','check_'))
def find(steps, name, pid=None, start=0):
    return next(i for i in range(start,len(steps)) if method(steps[i])==name and (pid is None or steps[i]['tool_args'].get('plot_id')==pid))
def before_read(steps, action, name, pid=None):
    return max(i for i in range(action) if method(steps[i])==name and (pid is None or steps[i]['tool_args'].get('plot_id')==pid))
def after_read(steps,index):
    return next(i+1 for i in range(index,len(steps)) if reading(steps[i]))
def timeline(steps,start=1767225600.):
    times=[start]
    for s in steps: times.append(times[-1]+s['duration_seconds'])
    return times

def boundaries(steps):
    transplant=[i for i,s in enumerate(steps) if method(s)=='transplant']
    planted=max(transplant)+1
    harvest=find(steps,'harvest','p1')
    labels={
        'initial_before_field_prep':0,
        'before_puddle':find(steps,'puddle_and_level','p1'),
        'before_transplant':find(steps,'load_seedlings'),
        'after_transplant':planted,
        'management_start':planted,
        'before_irrigate':before_read(steps,find(steps,'irrigate','p1',planted),'read_water_sensors','p1'),
        'before_drain':before_read(steps,find(steps,'drain','p1'),'read_water_sensors','p1'),
        'before_topdress':before_read(steps,find(steps,'apply_fertilizer','p1',planted),'inspect_crop','p1'),
        'before_treat':find(steps,'inspect_pests','p1',planted),
        'before_harvest':before_read(steps,harvest,'inspect_crop','p1'),
        'before_dry':find(steps,'measure_grain_moisture',start=harvest+1),
        'before_store':find(steps,'store_grain'),
        'before_water_observation':find(steps,'read_water_sensors','p1',planted),
    }
    refuels=[i for i,s in enumerate(steps) if method(s)=='refuel' and s['tool_args']['machine_id']=='tractor']
    if refuels:labels['before_refuel']=refuels[0]
    repairs=[i for i,s in enumerate(steps) if method(s)=='repair_bund']
    if repairs:labels['before_bund_repair']=before_read(steps,repairs[0],'inspect_infrastructure','p1')
    return labels

def regular_ranges(steps,labels,times):
    planted=labels['after_transplant']
    def window(days):
        # Include the first public recheck after the horizon; never split a wait.
        k=next(i for i,t in enumerate(times) if t>=times[planted]+days*86400)
        return after_read(steps,k)
    ranges={
      'establishment':(0,planted),
      'irrigation_management':(planted,window(10)),
      'nutrition_management':(planted,window(25)),
      'harvest_storage':(labels['before_harvest'],len(steps)),
      'harvest_batches':(labels['before_harvest'],len(steps)),
      'puddle':(labels['before_puddle'],find(steps,'puddle_and_level','p1')+1),
      'transplant':(labels['before_transplant'],find(steps,'transplant','p1')+1),
      'irrigate':(labels['before_irrigate'],find(steps,'irrigate','p1',planted)+1),
      'drain':(labels['before_drain'],find(steps,'drain','p1')+1),
      'harvest':(labels['before_harvest'],find(steps,'harvest','p1')+1),
      'observe_water':(labels['before_water_observation'],labels['before_water_observation']+1),
      'dry':(labels['before_dry'],find(steps,'dry_grain')+1),
      'store':(labels['before_store'],labels['before_store']+1),
      'fertilize':(labels['before_topdress'],find(steps,'apply_fertilizer','p1',planted)+1),
      'scout':(labels['before_treat'],labels['before_treat']+1),
      'crop_protection':(labels['before_treat'],find(steps,'advance_time',start=labels['before_treat'])),
    }
    if 'before_refuel' in labels:ranges['refuel']=(labels['before_refuel'],labels['before_refuel']+1)
    if 'before_bund_repair' in labels:
        repair=find(steps,'repair_bund')
        ranges['repair_bund']=(labels['before_bund_repair'],after_read(steps,repair+1))
        ranges['infrastructure_recovery']=(0,after_read(steps,repair+1))
    fills=[i for i,s in enumerate(steps) if method(s)=='replant_seedlings']
    if fills:
        end=find(steps,'inspect_establishment','p1',fills[0]+1)+1
        ranges['gap_fill']=(planted,end)
    return ranges

def challenge_ranges(name,steps,labels,times):
    planted=labels['after_transplant']
    def horizon(days):
        k=next(i for i,t in enumerate(times) if t>=times[planted]+days*86400)
        return after_read(steps,k)
    if name=='infrastructure_water_priority':
        repair=find(steps,'repair_bund')
        end=after_read(steps,repair+1)
        clear=find(steps,'clear_channel')
        return {'diagnosis':(0,end),'channel_clearance':(before_read(steps,clear,'inspect_infrastructure','p1'),after_read(steps,clear+1))}
    if name=='zonal_water_n_allocation':return {'diagnosis':(planted,horizon(42))}
    if name=='zonal_crop_protection':
        start=find(steps,'inspect_pests','p1',planted)
        # The next explicit wait closes the first complete targeted treatment round.
        stop=find(steps,'advance_time',start=start)
        assert reading(steps[stop-1])
        return {'diagnosis':(planted,horizon(21)),'targeted_protection':(start,stop)}
    if name=='rainy_harvest_capacity':
        h=find(steps,'harvest','p1')
        # Include late-rain drainage and public trafficability/maturity checks.
        late=[i for i,s in enumerate(steps[:h]) if method(s)=='drain' and i>planted]
        start=before_read(steps,late[0],'inspect_crop','p1') if late else labels['before_harvest']
        return {'diagnosis':(start,len(steps))}
    raise ValueError(name)

GOALS={
 'irrigate':'根据水位和根区观测，为 p1 完成 20 毫米到田灌水。',
 'drain':'把 p1 的田面水调整至约 20 毫米，为基肥和插秧准备浅水条件。',
 'puddle':'完成 p1 耙田整平，泡田前置条件和机具已经具备。',
 'transplant':'检查并装载成品秧苗，完成 p1 标准密度插秧。',
 'harvest':'复核成熟、水分、天气和通行性，收割 p1。',
 'observe_water':'读取 p1 的田面水和根区水分传感器，保留带时间戳的观测。',
 'refuel':'为拖拉机补充 59 升燃油，使当前 1 升余油补至 60 升满箱。',
 'dry':'测量接粮区目标粮批含水率，干燥至 14%，保留在接粮区。',
 'store':'将已干燥至 14% 的目标粮批安全入库。',
 'fertilize':'检查 p1 生育阶段，装载尿素，完成 300 千克/公顷的一轮追肥。',
 'scout':'落地检查 p1 的虫、病、草害，保留分项观测；本任务只诊断。',
 'repair_bund':'根据 p1 田埂巡检修复渗漏，并复查修复结果。',
 'gap_fill':'检查 p1 缺苗，使用剩余成品秧苗补苗，等待两天后复查成活。',
 'establishment':'完成两个田格的泡田、耙田整平、基肥、浅水调整和成品苗插秧。',
 'irrigation_management':'根据观测完成本窗口至少 10 天的水分管理，避免胁迫并遵守共享水额。',
 'nutrition_management':'根据观测完成本窗口至少 25 天的水肥管理，在分蘖期为两个田格各完成一轮 300 千克/公顷尿素追肥。',
 'crop_protection':'落地确诊两个田格的虫、病、草害，按对象、天气和水层处理并复查。',
 'infrastructure_recovery':'巡查田埂和渠道，疏通堵塞并修复渗漏，复查恢复情况。',
 'harvest_storage':'从新版来源季的收获窗口开始，复核成熟、天气、水分与通行性，完成两个田格收割、卸粮、干燥至 14% 和入库。',
 'harvest_batches':'在 600 千克粮箱和每日 2000 千克湿谷干燥能力下，分批完成两个田格收割、卸粮、干燥至 14% 和入库；避免湿谷长时间排队。',
}

def context(world,source,begin,end,times):
    f=world.field
    date=lambda t:__import__('datetime').datetime.fromtimestamp(t,__import__('datetime').timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    plots='；'.join(f"{p.plot_id} 面积 {p.area_m2:g} 平方米" for p in f.plots)
    planted='；'.join(f"{p.plot_id} 插秧日期 {p.transplant_day}" for p in f.plots if p.planted)
    return (f"来源季 {source}，切分起点 {date(times[begin])}，本窗口终点 {date(times[end])}。"
      f"品种与来源季一致，{plots}。"+planted+'。'
      'PaddyWorldApp 查看台账与库存，PaddyObservationApp 获取田间观测，PaddyMachineryApp 管理燃油与机具，'
      'PaddyOpsApp 执行农事，PaddyInfrastructureApp 维护水利，WeatherApp 查看天气，SystemApp 推进时间。'
      '从当前快照继续，不重复已完成工序；田格分批插秧应在同一 UTC 日完成。')

def replay_source(sid,steps,indices):
    scenario=get_scenario_class(sid)(seed=0,detailed_briefing=True)
    scenario.setup();engine=Engine(None,scenario);engine.time_manager.real_time_passed=lambda:0.
    recorder=Recorder(scenario,engine)
    world=scenario.get_typed_app(PaddyWorldApp)
    states={};metrics={}
    if 0 in indices:
        states[0]=world.get_state()
        if hasattr(scenario,'definition'):metrics[0]=measurements(scenario)
    for i,s in enumerate(steps):
        app,name=s['tool_name'].split('__')
        before=world.sim_time
        recorder.call(app,name,**s['tool_args'])
        actual=world.sim_time-before
        assert abs(actual-s['duration_seconds'])<1e-6,(sid,i,actual,s['duration_seconds'])
        if i+1 in indices:
            states[i+1]=world.get_state()
            if hasattr(scenario,'definition'):metrics[i+1]=measurements(scenario)
    scenario.workflow=recorder.workflow
    return scenario,recorder,states,metrics

def derive_assets(output):
    output=Path(output);rice=output/'rice';defaults=rice/'l3_defaults'
    manifest=copy.deepcopy(json.loads((artifacts.ARTIFACT_ROOT/artifacts.MANIFEST_NAME).read_text()))
    default_manifest=copy.deepcopy(json.loads((artifacts.ARTIFACT_ROOT/'l3_defaults/manifest.json').read_text()))
    manifest['split_source_release']=RELEASE
    manifest['generator']='scripts/build_rice_scenario_artifacts.py'
    briefs={};lineage={};reports=[]
    def write(relative,value):
        path=rice/relative;dump(path,value,compact='checkpoints/' in relative)
        manifest['files'][relative]=digest_bytes(path)
    def write_default(relative,value):
        path=defaults/relative;dump(path,value)
        default_manifest['files'][relative]=digest_bytes(path)
    for name in (*VARIANTS,'zonal_water_n_allocation','infrastructure_water_priority','zonal_crop_protection','rainy_harvest_capacity'):
        sid='scenario_rice_l3_'+name
        regular=name in VARIANTS
        path=artifacts.ARTIFACT_ROOT/('oracle_plans/'+sid+'.json' if regular else 'l3_defaults/challenge_plans/'+sid+'.json')
        parent=json.loads(path.read_text());steps=parent['steps'];labels=boundaries(steps);times=timeline(steps)
        if regular:
            all_ranges=regular_ranges(steps,labels,times)
            child_labels={'observe_water':'before_water_observation','refuel':'before_refuel','repair_bund':'before_bund_repair','harvest_storage':'before_harvest','harvest_batches':'before_harvest'}
            children={s.scenario_id:(s.task,child_labels.get(s.task,s.source_checkpoint_label),all_ranges[s.task]) for s in SPECS.values() if s.level!='L3' and s.variant==name}
            if 'crop_protection' in [s.task for s in SPECS.values() if s.variant==name]:
                start=labels['before_treat'];stop=find(steps,'advance_time',start=start)
                children['scenario_rice_l2_crop_protection']=('crop_protection','before_treat',(start,stop))
        else:
            ranges=challenge_ranges(name,steps,labels,times)
            children={task:(label,label,ranges[label]) for task,(source,level,label) in TASKS.items() if source==sid and level!='L3'}
        indices={0,len(steps),*labels.values()}
        for _,_,(begin,end) in children.values():indices.update((begin,end))
        scenario,rec,states,metrics=replay_source(sid,steps,indices)
        assert states[len(steps)]['sha256']==parent['expected_final_state_sha256'],(sid,'source changed')
        print(sid,'source final state verified',flush=True)
        if regular:
            for label,index in labels.items():write(str(artifacts.checkpoint_relative_path(name,label)),states[index])
        else:
            # Reuse existing matched-action controls on the new source timeline.
            rec.boundaries={'diagnosis':children['scenario_rice_l2_'+name][2][0]}
            rec.endpoints={label:{'step':end,'measurements':metrics[end],'state':states[end]} for _,label,(_,end) in children.values()}
            controls=[replay_control(sid,rec,policy) for policy in scenario.definition.controls]
            overlay={'source_id':sid,'source_l3_plan_sha256':digest_bytes(path),'source_release':RELEASE,
                     'controls':controls,'checkpoints':{},'tasks':{}}
        for child,(task,label,(begin,end)) in children.items():
            opening=states[begin];closing=states[end];sliced=copy.deepcopy(steps[begin:end])
            info={'source_l3_scenario_id':sid,'source_l3_plan_sha256':digest_bytes(path),'source_release':RELEASE,
                  'source_step_range':[begin,end],'initial_checkpoint_sha256':opening['sha256'],'expected_final_state_sha256':closing['sha256']}
            lineage[child]=info
            if regular:
                goal=GOALS[task]
                # Use a restored copy solely for public-readable starting context.
                source_world=scenario.get_typed_app(PaddyWorldApp)
                w=PaddyWorldApp(start_date=source_world.start_date,field=source_world.initial_field,weather=source_world.weather_config);w.load_state(opening)
                text=goal+'\n'+context(w,sid,begin,end,times)
                if task in ('irrigation_management','nutrition_management'):
                    text+=' 灌水按现场水层和根区共同判断：来源管理在田面水低于 3 毫米且根区 VWC 低于 0.37 时补至约 20 毫米；定期复测，避免机械每日灌排。'
                if task in ('fertilize','nutrition_management'):
                    text+=' 尿素用量指产品量；先核对生育阶段、浅水和装载量。本窗口只执行到期追肥，后续轮次与库存留给后续任务。'
                if task in ('harvest_storage','harvest_batches','harvest'):
                    text+=' 有田面水才按需排水，并核实根区 VWC 不高于 0.42；收割需成熟、谷物含水率 14%–28%、当日降雨不超过 5 毫米。'
                briefs[child]={'briefing_text':goal,'detailed_briefing_text':text}
                plan={k:copy.deepcopy(v) for k,v in parent.items() if k not in ('legacy_checkpoint_note','policy_origin','release_id','steps','checkpoint_steps')}
                plan.update(schema_version=1,scenario_id=child,task=task,source_checkpoint_label=label,
                            initial_checkpoint_sha256=opening['sha256'],expected_final_state_sha256=closing['sha256'],checkpoint_steps={},steps=sliced,**{k:v for k,v in info.items() if k not in ('initial_checkpoint_sha256','expected_final_state_sha256','source_l3_scenario_id')})
                write(str(artifacts.plan_relative_path(child)),plan)
            else:
                level=TASKS[child][1]
                metric='stored_kg_at_14pct' if 'harvest' in name else 'biomass_dry_kg'
                gates,status,note=gates_for(scenario.definition,level,metric,metrics[end],controls)
                previous=scenario._challenge_evidence['tasks'][child]
                if level=='L1':gates,status,note=[],'calibrated','Action contract; not an agronomic yield claim'
                if previous['status']!='calibrated':
                    status='experimental';note='Previous calibration pending; new source slices and matched controls recorded, no promotion claimed'
                if name=='zonal_water_n_allocation':status='experimental';note='Juvenile nitrogen observability gate pending'
                initial=measurements_from_checkpoint(scenario,opening)
                budgets={key:max(0.,metrics[end][key]-v)*(1.01 if level=='L1' else 1.1) for key,v in initial.items()}
                source_world=scenario.get_typed_app(PaddyWorldApp)
                w=PaddyWorldApp(start_date=source_world.start_date,field=source_world.initial_field,weather=source_world.weather_config);w.load_state(opening)
                goal={'zonal_water_n_allocation':'根据分区水分与适用的氮信号完成本窗口的水肥分配。',
                      'infrastructure_water_priority':'在窄供水窗口下疏渠，按根水需要救急补水，修复漏埂并复查。',
                      'zonal_crop_protection':'确诊两个田格的虫、病、草害，按分区、天气和水层选择处理并复查。',
                      'rainy_harvest_capacity':'在晚雨、小粮箱和有限干燥能力下，完成两个田格的收获、干燥至 14% 和安全入库。'}[name]
                if task=='channel_clearance':goal='巡检并疏通供水渠，复查堵塞和供水能力；保留后续救急灌水与修埂资源。'
                if task=='targeted_protection':goal='确诊两个田格当前虫、病、草害组成，完成本轮分区处理并复查；不执行后续季节管理。'
                text=goal+'\n'+context(w,sid,begin,end,times)
                text+=' 观察终点为 '+metrics[end]['day']+'。窗口增量预算：'+json.dumps(budgets,ensure_ascii=False)+'。取水单位 m³，肥料产品 kg，电力 kWh，药剂 L，维修材料 kg。'
                if gates:text+=' 结果门槛：'+json.dumps(gates,ensure_ascii=False)+'。'
                if status!='calibrated':text+=' 本诊断机制仍为实验状态，尚未通过正式配对校准。'
                briefs[child]={'briefing_text':goal,'detailed_briefing_text':text}
                overlay['checkpoints'][label]=opening
                overlay['tasks'][child]=dict(status=status,calibration_note=note,reference=metrics[end],gates=gates,
                    window_budgets=budgets,endpoint_state_digest=challenges.digest(normalize(closing)),
                    initial_checkpoint_digest=challenges.digest(opening),plan_digest=challenges.digest(sliced),
                    plan=sliced,briefing=text,**info)
            reports.append(dict(scenario_id=child,tool_calls=len(sliced),start_time=times[begin],end_time=times[end],**info))
            print(' ',child,len(sliced),'tools',flush=True)
        if not regular:write_default('split_challenges/'+sid+'.json',overlay)
    write('split_lineage.json',lineage)
    write_default('split_briefings.json',briefs)
    dump(rice/artifacts.MANIFEST_NAME,manifest)
    dump(defaults/'manifest.json',default_manifest)
    dump(output/'SPLIT_RESULTS.json',reports)
    assert len(reports)==26
    return reports

def verify_event_plans(root):
    """Check pure capture, source endpoint equality and independent replay."""
    from fairy.scenarios.rice import l3_defaults
    previous = artifacts.ARTIFACT_ROOT, l3_defaults.ROOT
    artifacts.ARTIFACT_ROOT = Path(root)
    l3_defaults.ROOT = Path(root) / "l3_defaults"
    try:
        lineage = artifacts.load_artifact("split_lineage.json")
        results = []
        for sid, info in lineage.items():
            scenario = get_scenario_class(sid)(seed=0, detailed_briefing=True)
            scenario.setup()
            scenario._building_baseline = True
            engine = Engine(None, scenario)
            world = scenario.get_typed_app(PaddyWorldApp)
            before = world.get_state()
            assert before["sha256"] == info["initial_checkpoint_sha256"], sid
            engine.build_oracle_workflow(run_oracle=False)
            assert world.get_state() == before, sid
            workflow = engine.run_scenario_oracle(run_oracle=True)
            final = world.get_state()
            assert final["sha256"] == info["expected_final_state_sha256"], sid
            replay_scenario = get_scenario_class(sid)(seed=0, detailed_briefing=True)
            replay_scenario._building_baseline = True
            replay = Engine(None, replay_scenario)
            replay.replay_workflow(workflow)
            assert replay_scenario.get_typed_app(PaddyWorldApp).get_state() == final, sid
            validation = replay.evaluate()
            assert validation.success or validation.metadata.get("failures") == [
                "experimental: decision mechanism has not passed matched-control calibration"], (sid, validation.to_dict())
            results.append({"scenario_id": sid, "full_state_equal": True,
                            "native_validation": validation.to_dict()})
            print(sid + ": source continuation and independent replay verified", flush=True)
        return results
    finally:
        artifacts.ARTIFACT_ROOT, l3_defaults.ROOT = previous


def build_artifacts(output_dir):
    """Preserve parent defaults; publish derived assets only after acceptance."""
    output_dir = Path(output_dir).resolve()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rice-splits-") as temporary:
        base = Path(temporary)
        staging = base / "rice"
        manifest = json.loads((artifacts.ARTIFACT_ROOT / artifacts.MANIFEST_NAME).read_text())
        defaults = json.loads((artifacts.ARTIFACT_ROOT / "l3_defaults/manifest.json").read_text())
        names = set(manifest["files"]) | {"l3_defaults/" + name for name in defaults["files"]}
        names.update((artifacts.MANIFEST_NAME, "l3_defaults/manifest.json"))
        for name in names:
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(artifacts.ARTIFACT_ROOT / name, target)
        derive_assets(base)
        verified = verify_event_plans(staging)
        dump(base / "VERIFICATION.json", verified)
        # Publish both checksum manifests after all payloads have been copied.
        files = [path for path in staging.rglob("*") if path.is_file()]
        manifests = {staging / artifacts.MANIFEST_NAME, staging / "l3_defaults/manifest.json"}
        for path in sorted(files, key=lambda path: path in manifests):
            target = output_dir / path.relative_to(staging)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    return verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=artifacts.ARTIFACT_ROOT,
                        help="Rice artifact root, retaining the existing package layout")
    parser.add_argument("--verify-only", action="store_true",
                        help="Verify installed source slices without rebuilding")
    args = parser.parse_args()
    results = verify_event_plans(args.output_dir) if args.verify_only else build_artifacts(args.output_dir)
    print(f"Verified {len(results)} source-derived rice splits", flush=True)


if __name__ == "__main__":
    main()
