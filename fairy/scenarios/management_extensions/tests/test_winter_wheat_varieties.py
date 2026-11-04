"""Native seed identity follows the configured wheat block."""

from fairy.scenarios.management_extensions.apps.winter_wheat_accounts_app import SEED
from fairy.scenarios.management_extensions.apps.winter_wheat_variety_farm_app import LATE_SEED
from fairy.scenarios.management_extensions.L3.scenario_winter_wheat_full_season import (
    ScenarioWinterWheatFullSeason,
)
from fairy.scenarios.management_extensions.L3.scenario_winter_wheat_two_varieties import (
    ScenarioWinterWheatTwoVarieties,
)
from fairy.scenarios.management_extensions.winter_wheat_workflow import WheatOracleTrial


def test_wrong_seed_leaves_split_field_unplanted_and_does_not_consume_resources():
    scene = ScenarioWinterWheatTwoVarieties(calibrating=True)
    trial = WheatOracleTrial(scene)
    trial.attach("grader")
    trial.call("tractor", "prepare_field")
    trial.goto("2019-10-15")
    trial.attach("seeder")
    trial.call(
        "tractor", "load_seeds", seed_type=SEED, count=scene.resources.seeds_per_block
    )
    before = (
        scene.farm_environment.time_manager.time(),
        scene.tractor._seed_hopper,
        scene.tractor._fuel_tank_l,
    )
    response = scene.tractor.sow(start_block=8, end_block=8)
    assert LATE_SEED in response["error"]
    assert not scene.farm.backends[8].pending
    assert before == (
        scene.farm_environment.time_manager.time(),
        scene.tractor._seed_hopper,
        scene.tractor._fuel_tank_l,
    )

    trial.call("tractor", "sow", start_block=0, end_block=0)
    trial.call(
        "tractor", "load_seeds", seed_type=LATE_SEED, count=scene.resources.seeds_per_block
    )
    trial.call("tractor", "sow", start_block=8, end_block=8)
    trial.goto("2019-10-16")

    assert scene.farm.backends[0].sown
    assert scene.farm.backends[8].sown
    assert scene.farm.backends[0].bundle.cultivar == "Winter_wheat_104"
    assert scene.farm.backends[8].bundle.cultivar == "Winter_wheat_101"
    assert scene.accounts.compute_accounts()["consumed_seeds"] == {
        SEED: scene.resources.seeds_per_block,
        LATE_SEED: scene.resources.seeds_per_block,
    }
    assert scene.farm.inspect_blocks(7, 8)["blocks"][1]["seed_type"] == LATE_SEED


def test_normal_scene_keeps_its_existing_seed_and_input_fingerprint():
    scene = ScenarioWinterWheatFullSeason()
    scene.setup()
    assert scene.warehouse.stock.seed_stock == {SEED: 4_000_000}
    assert list(scene.prices.seed_per_unit) == [SEED]
    assert "seed_catalogue" not in scene.farm.get_field_info()
    assert scene.input_fingerprint() == scene.ORACLE_REFERENCE["input_fingerprint"]
