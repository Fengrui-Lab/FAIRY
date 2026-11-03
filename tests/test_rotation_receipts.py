"""New rotation tool receipts must pass the existing workflow JSON codec."""

import json

from fairy.scenarios.management_extensions.L4.scenario_maize_fertilizer_procurement import (
    ScenarioTwoYearMaizeFertilizerProcurement,
)


def test_crop_options_are_json_receipts_with_iso_season_dates():
    scenario = ScenarioTwoYearMaizeFertilizerProcurement(calibrating=True)
    scenario.setup()
    receipt = scenario.cycle.get_crop_options()
    assert json.loads(json.dumps(receipt)) == receipt
    assert receipt["seasons"][0]["sowing_date"] == "2024-05-05"
    assert receipt["seasons"][0]["harvest_deadline"] == "2024-10-31"
