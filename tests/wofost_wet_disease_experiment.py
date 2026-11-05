"""Scene 02's three reproducible full-season controls, using registered tools.

Run: PYTHONHASHSEED=0 .venv/bin/python tests/wofost_wet_disease_experiment.py
  correct /tmp/fairy-wet-disease-v2
Repeat with none (no fungicide only), uniform (same83.6L across64ridges), or verify.
No hidden native read selects dates, doses or stops. Native states are result-only.
Production never imports this test runner or another scene's workflow.
"""
import sys,json
from pathlib import Path
from dataclasses import asdict
from datetime import date,datetime,time
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from fairy.scenarios.wofost_events import scenario_events_snapshot
from fairy.apps.farm_world import FarmWorldApp,TractorApp
from wofost_model_experiments import ModelExperimentEngine
from fairy.scenarios.wofost.scenario_full_season_heinong84_low_chemical_wet_disease_V2 import (
    ScenarioFullSeasonHeinong84LowChemicalWetDisease_V2,
)

class Trial(ScenarioFullSeasonHeinong84LowChemicalWetDisease_V2):
    """Test-only counterfactuals using the actual production world/events/apps."""
    def run_experiment(self,s):
        def call(label,app,method,**kw): return s.call(label,app+'__'+method,kw)
        def at(day,label):
            s.advance_to(label,datetime.combine(date.fromisoformat(day),time(7),s.timezone).timestamp())
            print(self.arm,day,flush=True)
        call('播前土壤温湿通行性','SensorApp','read_soil_sensors')
        call('播前天气','WeatherApp','get_current_weather')
        call('播前种肥药油库存','FarmWorldApp','get_inventory')
        call('播前机具容量与燃油','TractorApp','get_status')
        call('挂平地机','TractorApp','attach_implement',implement='grader')
        call('全田整地','TractorApp','level')
        call('卸平地机','TractorApp','detach_implement')
        call('挂起垄机','TractorApp','attach_implement',implement='furrower')
        call('一米一宽全田起垄','TractorApp','form_ridges',ridge_width_m=1.1)
        call('卸起垄机','TractorApp','detach_implement')
        payload=0
        for start in range(0,64,4):
            required=13266*4
            if payload<required:
                amount=min(300000-payload,required*((64-start)//4)-payload)
                call('批量装种_'+str(start),'TractorApp','load_seeds',seed_type='SOYBEAN_901',count=amount)
                payload+=amount
            call('同一轮播种_'+str(start),'TractorApp','plant_seeds',start_ridge=start,end_ridge=start+3,depth_cm=4.,seed_spacing_cm=200/(45*1.1))
            payload-=required
        at('2019-05-23','等实际出苗后检查')
        call('出苗样本前电量','Robot0','check_status')
        call('出苗样本仅0至3垄','Robot0','inspect_emergence',start_ridge=0,end_ridge=3)
        at('2019-05-28','等苗期冠层杂草复核')
        call('苗期冠层','SensorApp','read_canopy_sensors')
        call('杂草样本仅0至3垄','Robot0','inspect_crop_health',start_ridge=0,end_ridge=3)
        call('下轮检查前充电','Robot0','charge')
        call('等机器人充电一小时','SystemApp','advance_time',hours=1)
        at('2019-06-28','等湿期花期巡查')
        call('湿期当前降雨','WeatherApp','get_current_weather')
        call('湿期短期预报','WeatherApp','get_forecast',days=7)
        call('花期生育状态','FarmWorldApp','get_ridge_range_state',start=0,end=63)
        call('花期根水非仅看表土','SensorApp','read_root_zone_sensors')
        call('湿期冠层初筛','SensorApp','read_canopy_sensors')
        # No aircraft/spray in 8mm/day rain: wait for a real dry weather/soil window.
        at('2019-07-04','等雨后可飞可施药窗口')
        call('雨后阶段','FarmWorldApp','get_ridge_range_state',start=0,end=63)
        call('雨后根区水分排除旱情','SensorApp','read_root_zone_sensors')
        call('雨后全田冠层初筛','SensorApp','read_canopy_sensors')
        call('飞行前无雨风速','WeatherApp','get_current_weather')
        call('飞行前电量覆盖能力','SurveyDrone','check_status')
        call('无人机全田粗查非直接确诊','SurveyDrone','fly_survey',start_ridge=0,end_ridge=63)
        call('地面覆盖前确认机器人电量','Robot0','check_status')
        call('检查18至25含病区左侧参考','Robot0','inspect_crop_health',start_ridge=18,end_ridge=25)
        call('检查26至33补齐病区中段','Robot0','inspect_crop_health',start_ridge=26,end_ridge=33)
        call('检查16垄后充电','Robot0','charge')
        call('等补齐病区前充满一小时','SystemApp','advance_time',hours=1)
        call('继续检查前核对电量','Robot0','check_status')
        call('检查34至41病区后段','Robot0','inspect_crop_health',start_ridge=34,end_ridge=41)
        call('检查42至45含病区右侧参考','Robot0','inspect_crop_health',start_ridge=42,end_ridge=45)
        call('药前当天雨风窗口','WeatherApp','get_current_weather')
        call('药前复查土壤可通行','SensorApp','read_soil_sensors')
        call('药前确认额度与药剂库存','FarmWorldApp','get_inventory')
        if self.arm in {'correct','uniform'}:
            call('挂喷雾机','TractorApp','attach_implement',implement='sprayer')
            call('装杀菌工作液83点6升','TractorApp','load_fungicide',liters=83.6)
            if self.arm=='correct':
                for first,last in [(22,31),(32,41),(42,43)]:
                    call('定向杀菌_'+str(first),'TractorApp','apply_fungicide',start_ridge=first,end_ridge=last,liters_per_ridge=3.8)
            else:
                for first in range(0,64,10):
                    call('错误全田均摊_'+str(first),'TractorApp','apply_fungicide',start_ridge=first,end_ridge=min(first+9,63),liters_per_ridge=83.6/64)
            call('施药后卸喷雾机','TractorApp','detach_implement')
        call('复查前机器人充电','Robot0','charge')
        call('无人机用后充电','SurveyDrone','charge')
        call('等复查设备充电完成','SystemApp','advance_time',hours=1)
        at('2019-07-08','等药后复查')
        call('药后冠层仅作恢复线索','SensorApp','read_canopy_sensors')
        call('药后检查前电量','Robot0','check_status')
        call('药后22至25样本','Robot0','inspect_crop_health',start_ridge=22,end_ridge=25)
        call('药后40至43样本','Robot0','inspect_crop_health',start_ridge=40,end_ridge=43)
        call('药后库存与实际额度','FarmWorldApp','get_inventory')
        at('2019-07-20','等R3根区与降雨检查')
        call('R3公开生育阶段','FarmWorldApp','get_ridge_range_state',start=0,end=63)
        call('R3根区水分','SensorApp','read_root_zone_sensors')
        call('R3近期降雨','WeatherApp','get_forecast',days=3)
        # Wet-period carryover keeps roots moist: no July calendar irrigation.
        at('2019-08-08','等R5补水复核')
        call('R5公开生育阶段','FarmWorldApp','get_ridge_range_state',start=0,end=63)
        call('R5根区水分','SensorApp','read_root_zone_sensors')
        call('R5近期降雨','WeatherApp','get_forecast',days=3)
        call('R5全田一轮30毫米','FieldOpsApp','irrigate',start=0,end=63,hours=6.)
        at('2019-09-20','等自然成熟和合法收获窗口')
        call('全田成熟及粮食水分','FarmWorldApp','get_ridge_range_state',start=0,end=63)
        call('收前土壤通行性','SensorApp','read_soil_sensors')
        call('收前无雨窗口','WeatherApp','get_current_weather')
        call('挂收割机','TractorApp','attach_implement',implement='harvester')
        for start in range(0,64,8):
            for first in (start,start+4):
                call('同一轮收获_'+str(first),'TractorApp','harvest',start_ridge=first,end_ridge=first+3)
            call('粮箱限额合批卸粮_'+str(start),'TractorApp','unload_grain')
            call('批次必要干燥至百分之13_'+str(start),'FarmWorldApp','dry_grain',target_moisture_pct=13.)
            call('批次安全入库_'+str(start),'FarmWorldApp','store_grain')
        call('季末核对库存和全田交付','FarmWorldApp','get_inventory')
        farm=self.get_typed_app(FarmWorldApp)
        self.audit={'arm':self.arm,'world':asdict(self.WORLD),'events':scenario_events_snapshot(farm),'native':{rid:{'pcse':run.pcse,'specification':run.specification,'water_mm':run.cumulative_irrigation_mm,'fertilizer_kg':run.cumulative_fertilizer_kg} for rid,run in farm.physics.crop_backend._runs.items()},'resources':farm._management_regime.to_dict(),'warehouse_grain_kg':farm._inventory.warehouse_grain_kg,'tractor':self.get_typed_app(TractorApp).get_state()}
if __name__=='__main__':
    arm=sys.argv[1] if len(sys.argv)>1 else 'correct'
    if arm == 'verify':
        from test_wofost_wet_disease_v2 import assert_counterfactuals
        output=Path(sys.argv[2]) if len(sys.argv)>2 else Path('/tmp/fairy-wet-disease-v2')
        report=assert_counterfactuals({key:json.loads((output/(key+'.json')).read_text())
            for key in ('correct','none','uniform')})
        (output/'comparison_audit.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
        sys.exit(0)
    if arm not in {'correct','none','uniform'}:
        raise SystemExit('Choose correct, none, uniform, or verify')
    scene=Trial();scene.arm=arm
    engine=ModelExperimentEngine(None,scene)
    workflow=engine.run_experiment()
    out=Path(sys.argv[2]) if len(sys.argv)>2 else Path('/tmp/fairy-wet-disease-v2')
    out.mkdir(parents=True,exist_ok=True)
    scene.audit['workflow']=workflow.to_dict()
    scene.audit['validation']=asdict(scene.validate(SimpleNamespace(workflow=workflow,time_manager=engine.time_manager)))
    (out/(arm+'.json')).write_text(json.dumps(scene.audit,ensure_ascii=False,default=str,indent=2))
    print(arm,scene.audit['warehouse_grain_kg'],scene.audit['resources'],flush=True)
