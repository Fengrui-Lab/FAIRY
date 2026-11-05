"""Checksummed default L3 rice descriptions and frozen challenge tool plans.

This module never imports or runs authoring policies. L1/L2 checkpoints and plans are derived offline from the installed L3
plans. Challenge split controls are recorded separately from historical evidence.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

ROOT=Path(__file__).with_name("l3_defaults")

def load_asset(relative):
    manifest=json.loads((ROOT/"manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version")!=1 or relative not in manifest["files"]:
        raise ValueError("Unknown default L3 rice artifact")
    raw=(ROOT/relative).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=manifest["files"][relative]:
        raise ValueError("Default L3 rice artifact checksum mismatch")
    return json.loads(raw)

def detailed_briefing(scenario_id):
    return load_asset("detailed_briefings.json")[scenario_id]

def split_briefing(scenario_id, detailed=True):
    row = load_asset("split_briefings.json")[scenario_id]
    return row["detailed_briefing_text" if detailed else "briefing_text"]


def capture_challenge_events(scenario):
    from fairy.apps.agent_user_interface import AgentUserInterface
    from fairy.apps.paddy.world import PaddyWorldApp
    from fairy.types import EventRegisterer
    plan=load_asset("challenge_plans/"+scenario.scenario_id+".json")
    world=scenario.get_typed_app(PaddyWorldApp)
    if (plan["scenario_id"]!=scenario.scenario_id or
        plan["initial_checkpoint_sha256"]!=scenario._initial_state["sha256"] or
        plan["config_fingerprint"]!=world.crop_backend_provenance()["config_fingerprint"]):
        raise ValueError("Default L3 rice plan configuration/checkpoint mismatch")
    apps={app.name:app for app in scenario.apps}
    allowed={app.name:{tool.name for tool in app.get_tools()} for app in scenario.apps}
    entries=[]
    for step in plan["steps"]:
        app,sep,method=step["tool_name"].partition("__")
        args,duration=step["tool_args"],step["duration_seconds"]
        if not sep or method not in allowed.get(app,set()) or not isinstance(args,dict):
            raise ValueError("Invalid default L3 rice tool step")
        if isinstance(duration,bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<0:
            raise ValueError("Invalid default L3 rice duration")
        explicit=sum(float(args.get(k,0))*scale for k,scale in
                     (("seconds",1),("minutes",60),("hours",3600),("days",86400))) if app=="SystemApp" and method=="advance_time" else 0.
        if duration<explicit-1e-6:
            raise ValueError("Default L3 rice duration shorter than explicit wait")
        entries.append((apps[app],method,args,max(0.,duration-explicit)))
    with EventRegisterer.capture_mode() as captured:
        previous=scenario.get_typed_app(AgentUserInterface).send_message_to_agent(content=scenario.scenario_input).with_id("briefing")
        for i,(app,method,args,delay) in enumerate(entries):
            previous=getattr(app,method)(**args).oracle().with_id(f"rice_l3_v2_{i:04d}_{method}").depends_on(previous,delay_seconds=delay)
    scenario.events=list(captured)
