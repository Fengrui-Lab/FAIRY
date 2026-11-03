"""Historical alias of the fixed MAIZE_201 family instance."""
from fairy.scenarios.registry import register_scenario
from .cultivar_instances import W01Maize201

@register_scenario('scenario_maize_l3_basic_w01_v1')
class ScenarioBasicW01(W01Maize201):
    canonical_scenario_id = 'scenario_maize_l3_basic_w01_maize201_v1'
