"""Four paddy source seasons, four diagnosis windows and two targeted actions."""
from .runtime import register_challenges

register_challenges("rice", __name__)


# Full seasons use the selected frozen L3 plans. Their L1/L2 children load
# independently checksummed slices of those exact plans; historical challenge
# evidence remains archived and is not reused as new split calibration.
def _init_l3_default(self):
    from .runtime import CropChallengeScenario
    from fairy.scenarios.rice.l3_defaults import detailed_briefing
    supplied_task=self.scenario_input
    CropChallengeScenario.init_and_populate_apps(self)
    mode=self.detailed_briefing
    if isinstance(mode,str) and mode.lower() in {"true","false"}:
        mode=mode.lower()=="true"
    if not isinstance(mode,bool):
        raise ValueError("Rice detailed_briefing supports true/false")
    self.detailed_briefing=mode
    if mode and not getattr(self,"_authoring",False):
        self.scenario_input=supplied_task or detailed_briefing(self.scenario_id)


def _build_l3_default(self):
    if getattr(self,"_authoring",False):
        from .runtime import CropChallengeScenario
        return CropChallengeScenario.build_events_flow(self)
    from fairy.scenarios.rice.l3_defaults import capture_challenge_events
    capture_challenge_events(self)


def _init_split_default(self):
    from .runtime import CropChallengeScenario, measurements
    from . import artifacts
    from fairy.scenarios.rice.l3_defaults import load_asset, split_briefing

    supplied_task = self.scenario_input
    CropChallengeScenario.init_and_populate_apps(self)
    if getattr(self, "_authoring", False):
        return
    mode = self.detailed_briefing
    if isinstance(mode, str) and mode.lower() in {"true", "false"}:
        mode = mode.lower() == "true"
    if not isinstance(mode, bool):
        raise ValueError("Rice detailed_briefing supports true/false")
    self.detailed_briefing = mode
    data = load_asset("split_challenges/" + self.source_l3_scenario_id + ".json")
    task = data["tasks"][self.scenario_id]
    checkpoint = data["checkpoints"][self.source_checkpoint_label]
    from hashlib import sha256
    from fairy.scenarios.rice import l3_defaults
    parent_path = l3_defaults.ROOT / "challenge_plans" / (self.source_l3_scenario_id + ".json")
    parent = load_asset("challenge_plans/" + self.source_l3_scenario_id + ".json")
    begin, end = task["source_step_range"]
    if (data["source_id"] != self.source_l3_scenario_id or
            data["source_l3_plan_sha256"] != sha256(parent_path.read_bytes()).hexdigest() or
            task["source_l3_plan_sha256"] != data["source_l3_plan_sha256"] or
            not 0 <= begin < end <= len(parent["steps"]) or
            task["plan"] != parent["steps"][begin:end]):
        raise ValueError("Rice split differs from installed L3 source; rebuild rice artifacts")
    if (artifacts.digest(checkpoint) != task["initial_checkpoint_digest"] or
            artifacts.digest(task["plan"]) != task["plan_digest"]):
        raise ValueError("Rice split checkpoint/plan differs from source evidence")
    self._restore(checkpoint)
    self._initial_checkpoint_digest = artifacts.digest(checkpoint)
    self._initial_measurements = measurements(self)
    self._challenge_evidence = data
    self.scenario_input = supplied_task or split_briefing(self.scenario_id, mode)


for _class in tuple(globals().values()):
    if isinstance(_class,type) and getattr(_class,"challenge_id","").startswith("scenario_rice_l3_"):
        _class.init_and_populate_apps=_init_l3_default
        _class.build_events_flow=_build_l3_default

    elif isinstance(_class, type) and getattr(_class, "challenge_id", "").startswith(("scenario_rice_l1_", "scenario_rice_l2_")):
        _class.init_and_populate_apps = _init_split_default
