"""Offline initialized tool/menu audit; no oracle and no model calls."""
import json, inspect, argparse
from pathlib import Path
from fairy.scenarios.registry import list_scenarios, get_scenario_class
from fairy.agents.agent.toolset_builder import build_toolset
from fairy.controllers.agent_builder import FARM_AGENT_HIDDEN_TOOL_NAMES
from fairy.controllers.engine import Engine
from fairy.agents.jev.menu import build_arg_menu, arg_descriptions, task_numbers, build_tool_menus, EmptyMenuError
from fairy.agents.jev.snapshot import build_snapshot
from fairy.controllers.agent_builder import build_controller_agent
from types import SimpleNamespace

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
 rows=[]
 selected=set()
 for name in ("selected_l2_l1_20_30_scenario_ids.txt", "l3_mini_20_scenario_ids.txt"):
  selected.update((x.split(",")[2] if "," in x else x.strip()) for x in (Path("scripts/fullseason")/name).read_text().splitlines() if x.strip() and not x.startswith("#"))
 for sid in list_scenarios():
  cls=get_scenario_class(sid)
  if not any(x in cls.__module__ for x in ('.wofost.','.two_farm.','.three_farm.','.rice.','.maize.','.crop_challenges.','.farm_world_diverse.')) and sid not in selected:continue
  row={'scenario':sid,'source':inspect.getfile(cls),'tools':[]};rows.append(row)
  try:
   s=cls(seed=0,detailed_briefing=True);s.setup();task=Engine(agent=None,scenario=s)._resolve_agent_task(); tools=build_toolset(s.apps,excluded_tool_names=FARM_AGENT_HIDDEN_TOOL_NAMES)[2]
   agent=build_controller_agent("farm_jev",llm=SimpleNamespace(provider="typesafe",model="offline",system_one=lambda *a,**k: (_ for _ in ()).throw(AssertionError("No model requests during audit"))),toolsets=s.apps)
   for name,t in tools.items():
    tr={'name':name,'class':t.class_name,'args':[]};row['tools'].append(tr)
    for arg in t.args:
     if t.class_name=='SystemApp' and t.name in ('advance_time','wait_for_notification'):continue
     ar={'name':arg.name,'type':arg.arg_type};tr['args'].append(ar)
     try:
      m=build_arg_menu(t,arg,descriptions=arg_descriptions(t.function_description),numbers=task_numbers(task),num_ridges=agent._num_ridges,task_text=task);ar.update(source=m.source,options=list(m.options),status='supported')
     except EmptyMenuError as e:ar.update(status=e.reason,error=str(e))
     except Exception as e:ar.update(status='unsupported',error=str(e))
   agent=build_controller_agent('farm_jev',llm=SimpleNamespace(provider='typesafe',model='offline',system_one=lambda *a,**k: (_ for _ in ()).throw(AssertionError('No model requests during audit'))),toolsets=s.apps)
   menus=build_tool_menus(tools,task_text=task,num_ridges=agent._num_ridges)
   snap,facts=build_snapshot(s.apps,SimpleNamespace(dag={}),s.start_time)
   row['available_tools']=list(menus)
   row['status']='initialized'

  except Exception as e:row.update(status='initialization_failed',error=f'{type(e).__name__}: {e}')
  Path(a.output).write_text(json.dumps(rows,indent=2,ensure_ascii=False))
 print(len(rows),'scenarios')
if __name__=='__main__':main()
