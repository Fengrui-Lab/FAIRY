from fairy.scenarios.registry import register_scenario

from fairy.scenarios.baseline_farm_world.scenario_drone_survey import ScenarioFarmWorldDroneSurvey
from fairy.scenarios.baseline_farm_world.scenario_fertilizer import ScenarioFarmWorldFertilizer
from fairy.scenarios.baseline_farm_world.scenario_field_prep import ScenarioFarmWorldFieldPrep
from fairy.scenarios.baseline_farm_world.scenario_field_prep_planting import ScenarioFarmWorldFieldPrepPlanting
from fairy.scenarios.baseline_farm_world.scenario_harvest import ScenarioFarmWorldHarvest
from fairy.scenarios.baseline_farm_world.scenario_irrigation import ScenarioFarmWorldIrrigation
from fairy.scenarios.baseline_farm_world.scenario_pesticide import ScenarioFarmWorldPesticide
from fairy.scenarios.baseline_farm_world.scenario_pesticide_outbreak import ScenarioFarmWorldPesticideOutbreak
from fairy.scenarios.baseline_farm_world.scenario_planting import ScenarioFarmWorldPlanting
from fairy.scenarios.baseline_farm_world.scenario_survey_fertilizer_irrigation import ScenarioFarmWorldSurveyFertilizerIrrigation
from fairy.scenarios.baseline_farm_world.scenario_survey_pesticide_irrigation import ScenarioFarmWorldSurveyPesticideIrrigation

for _cls in [
    ScenarioFarmWorldDroneSurvey,
    ScenarioFarmWorldFertilizer,
    ScenarioFarmWorldFieldPrep,
    ScenarioFarmWorldFieldPrepPlanting,
    ScenarioFarmWorldHarvest,
    ScenarioFarmWorldIrrigation,
    ScenarioFarmWorldPesticide,
    ScenarioFarmWorldPesticideOutbreak,
    ScenarioFarmWorldPlanting,
    ScenarioFarmWorldSurveyFertilizerIrrigation,
    ScenarioFarmWorldSurveyPesticideIrrigation,
]:
    register_scenario(_cls.scenario_id)(_cls)

__all__ = [name for name in globals() if name.startswith("Scenario")]

