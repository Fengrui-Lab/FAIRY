"""Frozen public-tool Oracle selected by the documented finite-candidate search."""

from fairy.types import EventRegisterer
from fairy.scenarios.management_extensions.common import capture_step, finish_capture


def capture_reference(scene):
    apps = {app.name: app for app in scene.apps}
    with EventRegisterer.capture_mode() as events:
        previous = (
            apps["AgentUserInterface"]
            .send_message_to_agent(content=scene.scenario_input)
            .with_id("briefing")
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_000",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_inventory(),
            "l4_001",
            "执行公开农场工具 get_inventory；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].attach_implement(implement="grader"),
            "l4_002",
            "执行公开农场工具 attach_implement；参数 {'implement': 'grader'}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].level(),
            "l4_003",
            "执行公开农场工具 level；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].detach_implement(),
            "l4_004",
            "执行公开农场工具 detach_implement；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].load_fertilizer(kg=200.0),
            "l4_005",
            "执行公开农场工具 load_fertilizer；参数 {'kg': 200.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].base_fertilize(total_kg=200.0),
            "l4_006",
            "执行公开农场工具 base_fertilize；参数 {'total_kg': 200.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].attach_implement(implement="furrower"),
            "l4_007",
            "执行公开农场工具 attach_implement；参数 {'implement': 'furrower'}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].form_ridges(ridge_width_m=0.75),
            "l4_008",
            "执行公开农场工具 form_ridges；参数 {'ridge_width_m': 0.75}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].detach_implement(),
            "l4_009",
            "执行公开农场工具 detach_implement；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].load_seeds(seed_type="MAIZE_201", count=85760),
            "l4_010",
            "执行公开农场工具 load_seeds；参数 {'seed_type': 'MAIZE_201', 'count': 85760}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_011",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 0, 'end_ridge': 3, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_012",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 4, 'end_ridge': 7, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_013",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 8, 'end_ridge': 11, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_014",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 12, 'end_ridge': 15, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=16, end_ridge=19, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_015",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 16, 'end_ridge': 19, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=20, end_ridge=23, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_016",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 20, 'end_ridge': 23, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=24, end_ridge=27, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_017",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 24, 'end_ridge': 27, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=28, end_ridge=31, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_018",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 28, 'end_ridge': 31, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=32, end_ridge=35, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_019",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 32, 'end_ridge': 35, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=36, end_ridge=39, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_020",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 36, 'end_ridge': 39, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=40, end_ridge=43, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_021",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 40, 'end_ridge': 43, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=44, end_ridge=47, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_022",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 44, 'end_ridge': 47, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=48, end_ridge=51, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_023",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 48, 'end_ridge': 51, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=52, end_ridge=55, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_024",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 52, 'end_ridge': 55, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=56, end_ridge=59, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_025",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 56, 'end_ridge': 59, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=60, end_ridge=63, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_026",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 60, 'end_ridge': 63, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].commit_daily_physics(),
            "l4_027",
            "执行公开农场工具 commit_daily_physics；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=1194558.0),
            "l4_028",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "l4_029",
            "执行公开农场工具 get_forecast；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_farm_overview(),
            "l4_030",
            "执行公开农场工具 get_farm_overview；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].apply_fertigation(
                start_ridge=0, end_ridge=63, nutrient_amount=0.078125, water_mm=0.0
            ),
            "l4_031",
            "执行公开农场工具 apply_fertigation；参数 {'start_ridge': 0, 'end_ridge': 63, 'nutrient_amount': 0.078125, 'water_mm': 0.0}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=432000.0),
            "l4_032",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "l4_033",
            "执行公开农场工具 get_forecast；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_farm_overview(),
            "l4_034",
            "执行公开农场工具 get_farm_overview；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SensorApp"].read_soil_sensors(),
            "l4_035",
            "公开覆盖区观测中最大VWC为0.2254；低于0.28阈值，随后按本季分配剂量灌溉",
        )
        previous = capture_step(
            previous,
            apps["FieldOpsApp"].irrigate(start=0, end=63, hours=7.5),
            "l4_036",
            "执行公开农场工具 irrigate；参数 {'start': 0, 'end': 63, 'hours': 7.5}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=836700.0),
            "l4_037",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "l4_038",
            "执行公开农场工具 get_forecast；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_farm_overview(),
            "l4_039",
            "执行公开农场工具 get_farm_overview；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].apply_fertigation(
                start_ridge=0, end_ridge=63, nutrient_amount=0.078125, water_mm=0.0
            ),
            "l4_040",
            "执行公开农场工具 apply_fertigation；参数 {'start_ridge': 0, 'end_ridge': 63, 'nutrient_amount': 0.078125, 'water_mm': 0.0}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=2592000.0),
            "l4_041",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "l4_042",
            "执行公开农场工具 get_forecast；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_farm_overview(),
            "l4_043",
            "执行公开农场工具 get_farm_overview；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SensorApp"].read_soil_sensors(),
            "l4_044",
            "公开覆盖区观测中最大VWC为0.2428；低于0.28阈值，随后按本季分配剂量灌溉",
        )
        previous = capture_step(
            previous,
            apps["FieldOpsApp"].irrigate(start=0, end=63, hours=7.5),
            "l4_045",
            "执行公开农场工具 irrigate；参数 {'start': 0, 'end': 63, 'hours': 7.5}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=836700.0),
            "l4_046",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "l4_047",
            "执行公开农场工具 get_forecast；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_farm_overview(),
            "l4_048",
            "执行公开农场工具 get_farm_overview；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SensorApp"].read_soil_sensors(),
            "l4_049",
            "公开覆盖区观测中最大VWC为0.2207；低于0.28阈值，随后按本季分配剂量灌溉",
        )
        previous = capture_step(
            previous,
            apps["FieldOpsApp"].irrigate(start=0, end=63, hours=7.5),
            "l4_050",
            "执行公开农场工具 irrigate；参数 {'start': 0, 'end': 63, 'hours': 7.5}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=836700.0),
            "l4_051",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "l4_052",
            "执行公开农场工具 get_forecast；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_farm_overview(),
            "l4_053",
            "执行公开农场工具 get_farm_overview；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SensorApp"].read_soil_sensors(),
            "l4_054",
            "公开覆盖区观测中最大VWC为0.2434；低于0.28阈值，随后按本季分配剂量灌溉",
        )
        previous = capture_step(
            previous,
            apps["FieldOpsApp"].irrigate(start=0, end=63, hours=7.5),
            "l4_055",
            "执行公开农场工具 irrigate；参数 {'start': 0, 'end': 63, 'hours': 7.5}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=1614300.0),
            "l4_056",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_057",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_058",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_059",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_060",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_061",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_062",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_063",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_064",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_065",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_066",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_067",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_068",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_069",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_070",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].refuel(liters=100.0),
            "l4_071",
            "执行公开农场工具 refuel；参数 {'liters': 100.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=0, end_ridge=3),
            "l4_072",
            "执行公开农场工具 harvest；参数 {'start_ridge': 0, 'end_ridge': 3}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_073",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=4, end_ridge=7),
            "l4_074",
            "执行公开农场工具 harvest；参数 {'start_ridge': 4, 'end_ridge': 7}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_075",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=8, end_ridge=11),
            "l4_076",
            "执行公开农场工具 harvest；参数 {'start_ridge': 8, 'end_ridge': 11}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_077",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=12, end_ridge=15),
            "l4_078",
            "执行公开农场工具 harvest；参数 {'start_ridge': 12, 'end_ridge': 15}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_079",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=16, end_ridge=19),
            "l4_080",
            "执行公开农场工具 harvest；参数 {'start_ridge': 16, 'end_ridge': 19}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_081",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=20, end_ridge=23),
            "l4_082",
            "执行公开农场工具 harvest；参数 {'start_ridge': 20, 'end_ridge': 23}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_083",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=24, end_ridge=27),
            "l4_084",
            "执行公开农场工具 harvest；参数 {'start_ridge': 24, 'end_ridge': 27}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_085",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=28, end_ridge=31),
            "l4_086",
            "执行公开农场工具 harvest；参数 {'start_ridge': 28, 'end_ridge': 31}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_087",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=32, end_ridge=35),
            "l4_088",
            "执行公开农场工具 harvest；参数 {'start_ridge': 32, 'end_ridge': 35}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_089",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=36, end_ridge=39),
            "l4_090",
            "执行公开农场工具 harvest；参数 {'start_ridge': 36, 'end_ridge': 39}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_091",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=40, end_ridge=43),
            "l4_092",
            "执行公开农场工具 harvest；参数 {'start_ridge': 40, 'end_ridge': 43}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_093",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=44, end_ridge=47),
            "l4_094",
            "执行公开农场工具 harvest；参数 {'start_ridge': 44, 'end_ridge': 47}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_095",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=48, end_ridge=51),
            "l4_096",
            "执行公开农场工具 harvest；参数 {'start_ridge': 48, 'end_ridge': 51}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_097",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=52, end_ridge=55),
            "l4_098",
            "执行公开农场工具 harvest；参数 {'start_ridge': 52, 'end_ridge': 55}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_099",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=56, end_ridge=59),
            "l4_100",
            "执行公开农场工具 harvest；参数 {'start_ridge': 56, 'end_ridge': 59}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_101",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=60, end_ridge=63),
            "l4_102",
            "执行公开农场工具 harvest；参数 {'start_ridge': 60, 'end_ridge': 63}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_103",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].dry_grain(target_moisture_pct=14.0),
            "l4_104",
            "执行公开农场工具 dry_grain；参数 {'target_moisture_pct': 14.0}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].store_grain(),
            "l4_105",
            "执行公开农场工具 store_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SeasonCycle"].close_season(year=2026),
            "l4_106",
            "核验当年真实成熟收获和安全入库，并冻结本季增量粮账",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=22624784.0),
            "l4_107",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["SeasonCycle"].open_next_season(year=2027),
            "l4_108",
            "沿用原生土壤、设备、库存和共享额度开启第二年作物",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_109",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_inventory(),
            "l4_110",
            "执行公开农场工具 get_inventory；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].attach_implement(implement="grader"),
            "l4_111",
            "执行公开农场工具 attach_implement；参数 {'implement': 'grader'}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].level(),
            "l4_112",
            "执行公开农场工具 level；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].detach_implement(),
            "l4_113",
            "执行公开农场工具 detach_implement；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].load_fertilizer(kg=200.0),
            "l4_114",
            "执行公开农场工具 load_fertilizer；参数 {'kg': 200.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].base_fertilize(total_kg=200.0),
            "l4_115",
            "执行公开农场工具 base_fertilize；参数 {'total_kg': 200.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].attach_implement(implement="furrower"),
            "l4_116",
            "执行公开农场工具 attach_implement；参数 {'implement': 'furrower'}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].form_ridges(ridge_width_m=0.75),
            "l4_117",
            "执行公开农场工具 form_ridges；参数 {'ridge_width_m': 0.75}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].detach_implement(),
            "l4_118",
            "执行公开农场工具 detach_implement；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].load_seeds(seed_type="MAIZE_201", count=85760),
            "l4_119",
            "执行公开农场工具 load_seeds；参数 {'seed_type': 'MAIZE_201', 'count': 85760}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=0, end_ridge=3, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_120",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 0, 'end_ridge': 3, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=4, end_ridge=7, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_121",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 4, 'end_ridge': 7, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=8, end_ridge=11, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_122",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 8, 'end_ridge': 11, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=12, end_ridge=15, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_123",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 12, 'end_ridge': 15, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=16, end_ridge=19, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_124",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 16, 'end_ridge': 19, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=20, end_ridge=23, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_125",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 20, 'end_ridge': 23, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=24, end_ridge=27, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_126",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 24, 'end_ridge': 27, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=28, end_ridge=31, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_127",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 28, 'end_ridge': 31, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=32, end_ridge=35, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_128",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 32, 'end_ridge': 35, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=36, end_ridge=39, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_129",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 36, 'end_ridge': 39, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=40, end_ridge=43, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_130",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 40, 'end_ridge': 43, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=44, end_ridge=47, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_131",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 44, 'end_ridge': 47, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=48, end_ridge=51, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_132",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 48, 'end_ridge': 51, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=52, end_ridge=55, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_133",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 52, 'end_ridge': 55, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=56, end_ridge=59, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_134",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 56, 'end_ridge': 59, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].plant_seeds(
                start_ridge=60, end_ridge=63, depth_cm=4.0, seed_spacing_cm=20.0
            ),
            "l4_135",
            "执行公开农场工具 plant_seeds；参数 {'start_ridge': 60, 'end_ridge': 63, 'depth_cm': 4.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].commit_daily_physics(),
            "l4_136",
            "执行公开农场工具 commit_daily_physics；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=1194558.0),
            "l4_137",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "l4_138",
            "执行公开农场工具 get_forecast；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_farm_overview(),
            "l4_139",
            "执行公开农场工具 get_farm_overview；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].apply_fertigation(
                start_ridge=0,
                end_ridge=63,
                nutrient_amount=0.13020833333333334,
                water_mm=0.0,
            ),
            "l4_140",
            "执行公开农场工具 apply_fertigation；参数 {'start_ridge': 0, 'end_ridge': 63, 'nutrient_amount': 0.13020833333333334, 'water_mm': 0.0}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=432000.0),
            "l4_141",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "l4_142",
            "执行公开农场工具 get_forecast；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_farm_overview(),
            "l4_143",
            "执行公开农场工具 get_farm_overview；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SensorApp"].read_soil_sensors(),
            "l4_144",
            "公开覆盖区观测中最大VWC为0.3446；达到0.28阈值，本窗口跳过灌溉并保留未用水",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=864000.0),
            "l4_145",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "l4_146",
            "执行公开农场工具 get_forecast；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_farm_overview(),
            "l4_147",
            "执行公开农场工具 get_farm_overview；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].apply_fertigation(
                start_ridge=0,
                end_ridge=63,
                nutrient_amount=0.13020833333333334,
                water_mm=0.0,
            ),
            "l4_148",
            "执行公开农场工具 apply_fertigation；参数 {'start_ridge': 0, 'end_ridge': 63, 'nutrient_amount': 0.13020833333333334, 'water_mm': 0.0}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=2592000.0),
            "l4_149",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "l4_150",
            "执行公开农场工具 get_forecast；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_farm_overview(),
            "l4_151",
            "执行公开农场工具 get_farm_overview；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SensorApp"].read_soil_sensors(),
            "l4_152",
            "公开覆盖区观测中最大VWC为0.1966；低于0.28阈值，随后按本季分配剂量灌溉",
        )
        previous = capture_step(
            previous,
            apps["FieldOpsApp"].irrigate(start=0, end=63, hours=12.5),
            "l4_153",
            "执行公开农场工具 irrigate；参数 {'start': 0, 'end': 63, 'hours': 12.5}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=818700.0),
            "l4_154",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "l4_155",
            "执行公开农场工具 get_forecast；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_farm_overview(),
            "l4_156",
            "执行公开农场工具 get_farm_overview；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SensorApp"].read_soil_sensors(),
            "l4_157",
            "公开覆盖区观测中最大VWC为0.2317；低于0.28阈值，随后按本季分配剂量灌溉",
        )
        previous = capture_step(
            previous,
            apps["FieldOpsApp"].irrigate(start=0, end=63, hours=12.5),
            "l4_158",
            "执行公开农场工具 irrigate；参数 {'start': 0, 'end': 63, 'hours': 12.5}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=818700.0),
            "l4_159",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "l4_160",
            "执行公开农场工具 get_forecast；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_farm_overview(),
            "l4_161",
            "执行公开农场工具 get_farm_overview；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SensorApp"].read_soil_sensors(),
            "l4_162",
            "公开覆盖区观测中最大VWC为0.3117；达到0.28阈值，本窗口跳过灌溉并保留未用水",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=1641600.0),
            "l4_163",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_164",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_165",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_166",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_167",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_168",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_169",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_170",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_171",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_172",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_173",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_174",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_175",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_176",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_177",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_178",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_179",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_180",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_181",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_182",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_183",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_184",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_185",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_186",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_187",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_188",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_189",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_190",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_191",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_192",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_193",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_194",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_195",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_196",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_197",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_198",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_199",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_200",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_201",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_202",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_203",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_204",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_205",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_206",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_207",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_208",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_209",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_210",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_211",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_212",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_213",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_214",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_215",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_216",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_217",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_218",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_219",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_220",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_221",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_222",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=86400.0),
            "l4_223",
            "等待公开管理窗口；全部中间日继续水氮、天气和作物结算",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].get_ridge_range_state(start=0, end=63),
            "l4_224",
            "核对全田公开成熟阶段和籽粒水分",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "l4_225",
            "执行公开农场工具 get_current_weather；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].refuel(liters=100.0),
            "l4_226",
            "执行公开农场工具 refuel；参数 {'liters': 100.0}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=0, end_ridge=3),
            "l4_227",
            "执行公开农场工具 harvest；参数 {'start_ridge': 0, 'end_ridge': 3}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_228",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=4, end_ridge=7),
            "l4_229",
            "执行公开农场工具 harvest；参数 {'start_ridge': 4, 'end_ridge': 7}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_230",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=8, end_ridge=11),
            "l4_231",
            "执行公开农场工具 harvest；参数 {'start_ridge': 8, 'end_ridge': 11}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_232",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=12, end_ridge=15),
            "l4_233",
            "执行公开农场工具 harvest；参数 {'start_ridge': 12, 'end_ridge': 15}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_234",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=16, end_ridge=19),
            "l4_235",
            "执行公开农场工具 harvest；参数 {'start_ridge': 16, 'end_ridge': 19}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_236",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=20, end_ridge=23),
            "l4_237",
            "执行公开农场工具 harvest；参数 {'start_ridge': 20, 'end_ridge': 23}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_238",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=24, end_ridge=27),
            "l4_239",
            "执行公开农场工具 harvest；参数 {'start_ridge': 24, 'end_ridge': 27}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_240",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=28, end_ridge=31),
            "l4_241",
            "执行公开农场工具 harvest；参数 {'start_ridge': 28, 'end_ridge': 31}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_242",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=32, end_ridge=35),
            "l4_243",
            "执行公开农场工具 harvest；参数 {'start_ridge': 32, 'end_ridge': 35}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_244",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=36, end_ridge=39),
            "l4_245",
            "执行公开农场工具 harvest；参数 {'start_ridge': 36, 'end_ridge': 39}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_246",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=40, end_ridge=43),
            "l4_247",
            "执行公开农场工具 harvest；参数 {'start_ridge': 40, 'end_ridge': 43}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_248",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=44, end_ridge=47),
            "l4_249",
            "执行公开农场工具 harvest；参数 {'start_ridge': 44, 'end_ridge': 47}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_250",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=48, end_ridge=51),
            "l4_251",
            "执行公开农场工具 harvest；参数 {'start_ridge': 48, 'end_ridge': 51}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_252",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=52, end_ridge=55),
            "l4_253",
            "执行公开农场工具 harvest；参数 {'start_ridge': 52, 'end_ridge': 55}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_254",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=56, end_ridge=59),
            "l4_255",
            "执行公开农场工具 harvest；参数 {'start_ridge': 56, 'end_ridge': 59}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_256",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].harvest(start_ridge=60, end_ridge=63),
            "l4_257",
            "执行公开农场工具 harvest；参数 {'start_ridge': 60, 'end_ridge': 63}",
        )
        previous = capture_step(
            previous,
            apps["TractorApp"].unload_grain(),
            "l4_258",
            "执行公开农场工具 unload_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].dry_grain(target_moisture_pct=14.0),
            "l4_259",
            "执行公开农场工具 dry_grain；参数 {'target_moisture_pct': 14.0}",
        )
        previous = capture_step(
            previous,
            apps["FarmWorldApp"].store_grain(),
            "l4_260",
            "执行公开农场工具 store_grain；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SeasonCycle"].close_season(year=2027),
            "l4_261",
            "核验当年真实成熟收获和安全入库，并冻结本季增量粮账",
        )
    return finish_capture(scene, events)
