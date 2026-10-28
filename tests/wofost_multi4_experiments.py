"""Reproduce multi-farm correct / no focal management / wrong management controls.

Recipes schedule only public tools. They are test inputs, never production
policies. Production scenarios contain their own complete literal Oracle.
Usage: python tests/wofost_multi4_experiments.py 1 correct /tmp/multi-controls
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, time
import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from wofost_model_experiments import ModelExperimentEngine
from fairy.scenarios.wofost_events import scenario_events_snapshot


def recipe(number):
    return json.loads((ROOT / 'tests/data/wofost_multi4' / f'{number:02d}.json').read_text())


def run(number, arm, output):
    c = recipe(number)
    module = importlib.import_module(c['module'])
    scene = getattr(module, c['class_name'])()
    checkpoints, expected_failures = {}, []
    def experiment(s):
        try:
            for item in c['actions']:
                if item.get('arms') and arm not in item['arms']:
                    continue
                if 'at' in item:
                    target = datetime.fromisoformat(item['at']).replace(tzinfo=scene.simulation_timezone).timestamp()
                    response = s.advance_to(item['label'], target)
                    print(number, arm, item['at'], flush=True)
                else:
                    try:
                        response = s.call(item['label'], item['tool'], item.get('args', {}))
                        if item.get('expected_error'):
                            raise AssertionError('Expected refusal did not occur: ' + item['label'])
                    except RuntimeError:
                        response = s.workflow.dag[s.previous].content
                        if not item.get('expected_error') or item['expected_error'] not in str(response):
                            raise
                        expected_failures.append(s.previous)
                s.workflow.dag[s.previous].raw_arguments = item.get('round')
                if item.get('checkpoint'):
                    checkpoints[item['checkpoint']] = {'response': deepcopy(response), 'farms': {
                        fid: {'pcse': {str(rid): deepcopy(run.pcse) for rid, run in f.physics.crop_backend._runs.items()},
                              'biotic': {str(rid): asdict(st) for rid, st in f.physics.biotic.states.items()}}
                        for fid, f in scene.farms.items()}}
        finally:
            scene.experiment_partial = s.workflow.to_dict()
    scene.run_experiment = experiment
    engine = ModelExperimentEngine(None, scene)
    output = Path(output) / f'{number:02d}'
    output.mkdir(parents=True, exist_ok=True)
    try:
        workflow = engine.run_experiment()
    except Exception:
        (output / f'{arm}-failed.json').write_text(json.dumps(getattr(scene, 'experiment_partial', {}), ensure_ascii=False, indent=2, default=str))
        raise
    validation = scene.validate(engine)
    native = {fid: {str(rid): {'pcse': deepcopy(run.pcse), 'specification': deepcopy(run.specification)}
                   for rid, run in f.physics.crop_backend._runs.items()} for fid, f in scene.farms.items()}
    operations = []
    for step in workflow.dag.values():
        method = step.tool_name.split('__')[1]
        if method in {'level','form_ridges','plant_seeds','harvest','irrigate','apply_fertilizer','base_fertilize','apply_fungicide','spray_pesticide'} and not step.error_stage:
            operations.append((step.tool_args.get('farm_id', step.tool_name.split('__')[0]), method, step.raw_arguments))
    result = {'arm': arm, 'fields': [asdict(f) for f in scene.FARMS], 'initial_stock': asdict(scene.SUPPLIES),
              'regional_events': [asdict(e) for e in scene.REGIONAL_EVENTS], 'regional_changes': scene.regional_weather_changes,
              'events': {fid: scenario_events_snapshot(f) for fid, f in scene.farms.items()},
              'native': native, 'resources': {fid: f._management_regime.to_dict() for fid, f in scene.farms.items()},
              'warehouse': scene.warehouse.get_state(), 'tractor': scene.tractor.get_state(),
              'validation': validation.to_dict(), 'checkpoints': checkpoints, 'expected_failures': expected_failures,
              'tool_calls': len(workflow.dag), 'field_operation_rounds': len(set(operations)),
              'operation_round_groups': sorted(set(operations)), 'workflow': workflow.to_dict(),
              'final_time': engine.time_manager.time()}
    (output / f'{arm}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print('RESULT', number, arm, json.dumps(validation.to_dict(), ensure_ascii=False), flush=True)
    assert validation.success, validation.message
    return result


if __name__ == '__main__':
    run(int(sys.argv[1]), sys.argv[2], sys.argv[3])
