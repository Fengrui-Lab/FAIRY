"""Reproduce scenario 01's three real-tool counterfactual seasons, without an LLM.

Run from the repository: PYTHONHASHSEED=0 .venv/bin/python
  tests/wofost_threshold_insect_experiment.py correct /tmp/fairy-threshold-v2
Repeat with `none` (no insecticide only) and `early` (June 15 instead of July 25).
All arms use the production scene's exact world, events, crop, weather and caps.
The explicit intervention schedule is test-only. No hidden native values select
operations, dates, quantities or harvest timing. Native values are output evidence.
"""
import sys, json
from pathlib import Path
from datetime import date, datetime, time
from dataclasses import asdict
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from fairy.scenarios.wofost_events import scenario_events_snapshot
from fairy.apps.farm_world import FarmWorldApp,TractorApp
from wofost_model_experiments import ModelExperimentEngine
from fairy.scenarios.wofost.scenario_full_season_heinong84_threshold_insect_limited_spray_V2 import (
    ScenarioFullSeasonHeinong84ThresholdInsectLimitedSpray_V2,
)

class Trial(ScenarioFullSeasonHeinong84ThresholdInsectLimitedSpray_V2):
    """Test-only fixed-date counterfactual, never loaded by production workflows."""
    def run_experiment(self,s):
        def call(label,app,method,**kw): return s.call(label,app+'__'+method,kw)
        def at(day,label):
            s.advance_to(label,datetime.combine(date.fromisoformat(day),time(7),s.timezone).timestamp())
        def spray(label,start=18):
            call(label+'_weather','WeatherApp','get_current_weather')
            call(label+'_soil','SensorApp','read_soil_sensors')
            call(label+'_inventory','FarmWorldApp','get_inventory')
            call(label+'_sprayer','TractorApp','attach_implement',implement='sprayer')
            call(label+'_load160L','TractorApp','load_pesticide',liters=160.)
            call(label+'_first10','TractorApp','spray_pesticide',start_ridge=start,end_ridge=start+9,liters_per_ridge=8.)
            call(label+'_second10','TractorApp','spray_pesticide',start_ridge=start+10,end_ridge=start+19,liters_per_ridge=8.)
            call(label+'_detach','TractorApp','detach_implement')
        def inspect(label):
            call(label+'_canopy','SensorApp','read_canopy_sensors')
            call(label+'_roots','SensorApp','read_root_zone_sensors')
            call(label+'_weather','WeatherApp','get_current_weather')
            call(label+'_drone_status','SurveyDrone','check_status')
            call(label+'_aerial64','SurveyDrone','fly_survey',start_ridge=0,end_ridge=63)
            call(label+'_robot_status','Robot0','check_status')
            call(label+'_ground18to21','Robot0','inspect_crop_health',start_ridge=18,end_ridge=21)
            call(label+'_ground34to37','Robot0','inspect_crop_health',start_ridge=34,end_ridge=37)
            call(label+'_density18','Robot0','inspect_ridge',ridge_id=18)
            call(label+'_density34','Robot0','inspect_ridge',ridge_id=34)
            call(label+'_charge_robot','Robot0','charge')
            call(label+'_charge_drone','SurveyDrone','charge')
            call(label+'_wait_charging','SystemApp','advance_time',hours=1)
        # The preparation and harvest schedules are fixed independently of hidden native output.
        call('soil_before_sowing','SensorApp','read_soil_sensors')
        call('weather_before_sowing','WeatherApp','get_current_weather')
        call('seed_fuel_chemical_inventory','FarmWorldApp','get_inventory')
        call('tractor_capacity','TractorApp','get_status')
        call('grader','TractorApp','attach_implement',implement='grader')
        call('level64','TractorApp','level')
        call('detach_grader','TractorApp','detach_implement')
        call('furrower','TractorApp','attach_implement',implement='furrower')
        call('form64','TractorApp','form_ridges',ridge_width_m=1.1)
        call('detach_furrower','TractorApp','detach_implement')
        payload=0
        for start in range(0,64,4):
            required=13266*4
            if payload<required:
                amount=min(300000-payload,required*((64-start)//4)-payload)
                call('seed_payload_'+str(start),'TractorApp','load_seeds',seed_type='SOYBEAN_901',count=amount)
                payload+=amount
            call('sow_'+str(start),'TractorApp','plant_seeds',start_ridge=start,end_ridge=start+3,depth_cm=4.,seed_spacing_cm=100*2/(45*1.1))
            payload-=required
        at('2019-05-13','wait_emergence')
        call('emergence_battery','Robot0','check_status')
        call('emergence_sample0to3','Robot0','inspect_emergence',start_ridge=0,end_ridge=3)
        at('2019-05-28','wait_vegetative')
        call('early_canopy','SensorApp','read_canopy_sensors')
        call('weed_sample0to3','Robot0','inspect_crop_health',start_ridge=0,end_ridge=3)
        call('recharge_before_scouting','Robot0','charge')
        call('wait_recharge','SystemApp','advance_time',hours=1)
        at('2019-06-15','wait_early_light_insect_scout')
        inspect('light')
        if self.arm=='early': spray('premature_spray')
        at('2019-06-28','wait_flowering')
        call('flowering_stage','FarmWorldApp','get_ridge_range_state',start=0,end=63)
        call('flowering_roots','SensorApp','read_root_zone_sensors')
        at('2019-07-20','wait_R3_water')
        call('R3_stage','FarmWorldApp','get_ridge_range_state',start=0,end=63)
        call('R3_roots','SensorApp','read_root_zone_sensors')
        call('R3_rain_forecast','WeatherApp','get_forecast',days=3)
        call('R3_30mm','FieldOpsApp','irrigate',start=0,end=63,hours=6.)
        at('2019-07-25','wait_outbreak_scout')
        call('outbreak_stage','FarmWorldApp','get_ridge_range_state',start=0,end=63)
        inspect('outbreak')
        if self.arm=='correct': spray('threshold_spray')
        if self.arm=='wrong_zone': spray('wrong_zone_spray',0)
        at('2019-07-28','wait_post_spray_recheck')
        call('recheck_canopy','SensorApp','read_canopy_sensors')
        call('recheck_robot_status','Robot0','check_status')
        call('recheck18to21','Robot0','inspect_crop_health',start_ridge=18,end_ridge=21)
        call('recheck34to37','Robot0','inspect_crop_health',start_ridge=34,end_ridge=37)
        call('recheck_inventory','FarmWorldApp','get_inventory')
        at('2019-08-08','wait_R5_water')
        call('R5_stage','FarmWorldApp','get_ridge_range_state',start=0,end=63)
        call('R5_roots','SensorApp','read_root_zone_sensors')
        call('R5_rain_forecast','WeatherApp','get_forecast',days=3)
        call('R5_30mm','FieldOpsApp','irrigate',start=0,end=63,hours=6.)
        at('2019-09-20','wait_harvest')
        call('maturity_all64','FarmWorldApp','get_ridge_range_state',start=0,end=63)
        call('trafficability_before_harvest','SensorApp','read_soil_sensors')
        call('harvest_weather','WeatherApp','get_current_weather')
        call('harvester','TractorApp','attach_implement',implement='harvester')
        # Conservative fixed 8-ridge loads fit the actual 2t bin in all arms.
        for start in range(0,64,8):
            for first in (start,start+4): call('harvest_'+str(first),'TractorApp','harvest',start_ridge=first,end_ridge=first+3)
            call('unload_'+str(start),'TractorApp','unload_grain')
            call('dry_'+str(start),'FarmWorldApp','dry_grain',target_moisture_pct=13.)
            call('store_'+str(start),'FarmWorldApp','store_grain')
        call('final_inventory','FarmWorldApp','get_inventory')
        farm=self.get_typed_app(FarmWorldApp)
        self.audit={'arm':self.arm,'world':asdict(self.WORLD),'events':scenario_events_snapshot(farm),'native':{rid:{'pcse':r.pcse,'specification':r.specification,'water_mm':r.cumulative_irrigation_mm,'fertilizer_kg':r.cumulative_fertilizer_kg} for rid,r in farm.physics.crop_backend._runs.items()},'resources':farm._management_regime.to_dict(),'warehouse_grain_kg':farm._inventory.warehouse_grain_kg,'tractor':self.get_typed_app(TractorApp).get_state()}
if __name__=='__main__':
    arm=sys.argv[1] if len(sys.argv)>1 else 'correct'
    if arm == 'verify':
        from test_wofost_threshold_insect_v2 import assert_counterfactuals
        output = Path(sys.argv[2]) if len(sys.argv)>2 else Path('/tmp/fairy-threshold-v2')
        report = assert_counterfactuals({key:json.loads((output/(key+'.json')).read_text())
            for key in ('correct','none','early')})
        (output/'comparison_audit.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
        sys.exit(0)
    if arm not in {'correct','none','early'}:
        raise SystemExit('Choose correct, none, early, or verify')
    scene=Trial();scene.arm=arm
    engine=ModelExperimentEngine(None,scene)
    workflow=engine.run_experiment()
    out=Path(sys.argv[2]) if len(sys.argv)>2 else Path('/tmp/fairy-threshold-v2')
    out.mkdir(parents=True,exist_ok=True)
    from types import SimpleNamespace
    scene.audit['validation']=asdict(scene.validate(SimpleNamespace(workflow=workflow,time_manager=engine.time_manager)))
    scene.audit['workflow']=workflow.to_dict()
    (out/(arm+'.json')).write_text(json.dumps(scene.audit,default=str,indent=2))
    print(arm,scene.audit['warehouse_grain_kg'],scene.audit['resources'],scene.audit['validation'],flush=True)
