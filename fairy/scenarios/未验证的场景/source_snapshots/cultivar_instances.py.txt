"""Fixed single-cultivar instances of three unchanged management families.

Non-201 instances have only task delivery in their event graph until their own
reference execution produces an oracle. A 201 trajectory is never relabelled.
"""
from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.types import EventRegisterer
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.farm_world_fullseason_v2.harbin_l3_scenario_helpers import collect_event_graph
from fairy.crops.maize_identity import MAIZE_WOFOST_VARIANTS, native_variety
from .basic_management import BasicManagementScenario, candidate_spec
from .scenario_basic_h01_v0 import BasicH01Scenario

class FixedCultivarMixin:
    family = ''
    variant = None
    def __init__(self, **kwargs):
        requested = kwargs.pop('scenario_id', self.scenario_id)
        if requested != self.scenario_id:
            raise ValueError('Fixed cultivar scenario ID cannot be overridden')
        super().__init__(scenario_id=requested, **kwargs)

    def init_and_populate_apps(self, *args, **kwargs):
        super().init_and_populate_apps(*args, **kwargs)
        self.scenario_input = self.scenario_input.replace('MAIZE_201', self.public_seed_type).replace(
            'Grain_maize_201', native_variety(self.public_seed_type))

    def build_events_flow(self):
        if self.variant == 201 and self.family != 'H01':
            return super().build_events_flow()
        with EventRegisterer.capture_mode():
            first = self.get_typed_app(AgentUserInterface).send_message_to_agent(
                content=self.scenario_input).with_id('briefing')
            self.events = collect_event_graph(first)

for family in ('W01', 'N01', 'H01'):
    for seed in MAIZE_WOFOST_VARIANTS:
        variant = int(seed.rsplit('_', 1)[1])
        sid = f'scenario_maize_l3_basic_{family.lower()}_maize{variant}_v1'
        cls = type(f'{family}Maize{variant}', (FixedCultivarMixin,
                   BasicH01Scenario if family == 'H01' else BasicManagementScenario), {
            '__module__': __name__, 'family': family, 'variant': variant,
            'public_seed_type': seed, 'candidate': 'N01' if family == 'H01' else family,
            'spec': candidate_spec('N01' if family == 'H01' else family),
            'event_graph_policy': 'historical 201 only; other instances briefing pending own reference',
        })
        globals()[cls.__name__] = register_scenario(sid)(cls)
