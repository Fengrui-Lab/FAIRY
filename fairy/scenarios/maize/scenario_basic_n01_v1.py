"""Historical alias of the fixed MAIZE_201 family instance."""
from fairy.scenarios.registry import register_scenario
from .cultivar_instances import N01Maize201

@register_scenario('scenario_maize_l3_basic_n01_v1')
class ScenarioBasicN01(N01Maize201):
    canonical_scenario_id = 'scenario_maize_l3_basic_n01_maize201_v1'
