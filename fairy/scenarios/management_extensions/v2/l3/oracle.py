"""Frozen public-tool Oracle, generated after finite candidate exploration."""

from fairy.types import EventRegisterer
from fairy.scenarios.management_extensions.common import capture_step, finish_capture


def capture_reference(scene):
    apps = {app.name: app for app in scene.apps}
    with EventRegisterer.capture_mode() as events:
        previous = None
        previous = capture_step(
            previous,
            apps["OperatingAccounts"].get_accounts(),
            "step0000",
            "OperatingAccounts: 读取公开粮价、成本口径及共享水余额，按实际消耗核算两作物经营收益；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["Warehouse"].get_inventory(),
            "step0001",
            "Warehouse: 核对共同库存，机上物资另计，不重复扣费；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["MaizeField"].get_crop_capabilities(),
            "step0002",
            "MaizeField: 核对当前作物的播种、成熟、收获及储存规则；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "step0003",
            "WeatherApp: 核对当前真实天气，作业不能依赖未公开未来状态；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "step0004",
            "WeatherApp: 读取公开七日预报，确认管理窗口；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["MaizeSensor"].read_soil_sensors(),
            "step0005",
            "MaizeSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["MaizeField"].get_ridge_range_state(start=0, end=15),
            "step0006",
            "MaizeField: 检查本地块全部垄的生育阶段和籽粒水分；参数 {'start': 0, 'end': 15}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].get_status(),
            "step0007",
            "Tractor: 核对共享拖拉机机具、燃油、种肥箱和粮箱；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].attach_implement(implement="grader"),
            "step0008",
            "Tractor: 切换到随后作业所需机具，沿用同一设备状态；参数 {'implement': 'grader'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].level(farm_id="maize"),
            "step0009",
            "Tractor: 按实际地块面积整平，消耗时间与燃油；参数 {'farm_id': 'maize'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].detach_implement(),
            "step0010",
            "Tractor: 卸下当前机具，准备下一项作业；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].load_fertilizer(kg=72.36),
            "step0011",
            "Tractor: 从共同库存装入本次所需肥料；装载本身不计施用成本；参数 {'kg': 72.36}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].base_fertilize(farm_id="maize", total_kg=72.36),
            "step0012",
            "Tractor: 播前均匀施入选定肥料产品的一半，由原生氮过程响应；参数 {'farm_id': 'maize', 'total_kg': 72.36}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].attach_implement(implement="furrower"),
            "step0013",
            "Tractor: 切换到随后作业所需机具，沿用同一设备状态；参数 {'implement': 'furrower'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].form_ridges(farm_id="maize", ridge_width_m=0.75),
            "step0014",
            "Tractor: 按地块实际几何起垄，不改变土地面积；参数 {'farm_id': 'maize', 'ridge_width_m': 0.75}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].detach_implement(),
            "step0015",
            "Tractor: 卸下当前机具，准备下一项作业；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].attach_implement(implement="seeder"),
            "step0016",
            "Tractor: 切换到随后作业所需机具，沿用同一设备状态；参数 {'implement': 'seeder'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].load_seeds(seed_type="MAIZE_201", count=21440),
            "step0017",
            "Tractor: 按作物身份装入本田所需种子，不能混装另一作物；参数 {'seed_type': 'MAIZE_201', 'count': 21440}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].plant_seeds(
                farm_id="maize",
                start_ridge=0,
                end_ridge=3,
                depth_cm=5.0,
                seed_spacing_cm=20.0,
            ),
            "step0018",
            "Tractor: 完成该批四垄播种，按种子数量和密度实际扣料；参数 {'farm_id': 'maize', 'start_ridge': 0, 'end_ridge': 3, 'depth_cm': 5.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].plant_seeds(
                farm_id="maize",
                start_ridge=4,
                end_ridge=7,
                depth_cm=5.0,
                seed_spacing_cm=20.0,
            ),
            "step0019",
            "Tractor: 完成该批四垄播种，按种子数量和密度实际扣料；参数 {'farm_id': 'maize', 'start_ridge': 4, 'end_ridge': 7, 'depth_cm': 5.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].plant_seeds(
                farm_id="maize",
                start_ridge=8,
                end_ridge=11,
                depth_cm=5.0,
                seed_spacing_cm=20.0,
            ),
            "step0020",
            "Tractor: 完成该批四垄播种，按种子数量和密度实际扣料；参数 {'farm_id': 'maize', 'start_ridge': 8, 'end_ridge': 11, 'depth_cm': 5.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].plant_seeds(
                farm_id="maize",
                start_ridge=12,
                end_ridge=15,
                depth_cm=5.0,
                seed_spacing_cm=20.0,
            ),
            "step0021",
            "Tractor: 完成该批四垄播种，按种子数量和密度实际扣料；参数 {'farm_id': 'maize', 'start_ridge': 12, 'end_ridge': 15, 'depth_cm': 5.0, 'seed_spacing_cm': 20.0}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].detach_implement(),
            "step0022",
            "Tractor: 卸下当前机具，准备下一项作业；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanField"].get_crop_capabilities(),
            "step0023",
            "SoybeanField: 核对当前作物的播种、成熟、收获及储存规则；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "step0024",
            "WeatherApp: 核对当前真实天气，作业不能依赖未公开未来状态；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "step0025",
            "WeatherApp: 读取公开七日预报，确认管理窗口；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanSensor"].read_soil_sensors(),
            "step0026",
            "SoybeanSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
            "step0027",
            "SoybeanField: 检查本地块全部垄的生育阶段和籽粒水分；参数 {'start': 0, 'end': 15}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].get_status(),
            "step0028",
            "Tractor: 核对共享拖拉机机具、燃油、种肥箱和粮箱；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].attach_implement(implement="grader"),
            "step0029",
            "Tractor: 切换到随后作业所需机具，沿用同一设备状态；参数 {'implement': 'grader'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].level(farm_id="soybean"),
            "step0030",
            "Tractor: 按实际地块面积整平，消耗时间与燃油；参数 {'farm_id': 'soybean'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].detach_implement(),
            "step0031",
            "Tractor: 卸下当前机具，准备下一项作业；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].attach_implement(implement="furrower"),
            "step0032",
            "Tractor: 切换到随后作业所需机具，沿用同一设备状态；参数 {'implement': 'furrower'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].form_ridges(farm_id="soybean", ridge_width_m=1.1),
            "step0033",
            "Tractor: 按地块实际几何起垄，不改变土地面积；参数 {'farm_id': 'soybean', 'ridge_width_m': 1.1}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].detach_implement(),
            "step0034",
            "Tractor: 卸下当前机具，准备下一项作业；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].attach_implement(implement="seeder"),
            "step0035",
            "Tractor: 切换到随后作业所需机具，沿用同一设备状态；参数 {'implement': 'seeder'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].load_seeds(seed_type="SOYBEAN_901", count=188672),
            "step0036",
            "Tractor: 按作物身份装入本田所需种子，不能混装另一作物；参数 {'seed_type': 'SOYBEAN_901', 'count': 188672}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].plant_seeds(
                farm_id="soybean",
                start_ridge=0,
                end_ridge=3,
                depth_cm=4.0,
                seed_spacing_cm=4.545454545454546,
            ),
            "step0037",
            "Tractor: 完成该批四垄播种，按种子数量和密度实际扣料；参数 {'farm_id': 'soybean', 'start_ridge': 0, 'end_ridge': 3, 'depth_cm': 4.0, 'seed_spacing_cm': 4.545454545454546}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].plant_seeds(
                farm_id="soybean",
                start_ridge=4,
                end_ridge=7,
                depth_cm=4.0,
                seed_spacing_cm=4.545454545454546,
            ),
            "step0038",
            "Tractor: 完成该批四垄播种，按种子数量和密度实际扣料；参数 {'farm_id': 'soybean', 'start_ridge': 4, 'end_ridge': 7, 'depth_cm': 4.0, 'seed_spacing_cm': 4.545454545454546}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].plant_seeds(
                farm_id="soybean",
                start_ridge=8,
                end_ridge=11,
                depth_cm=4.0,
                seed_spacing_cm=4.545454545454546,
            ),
            "step0039",
            "Tractor: 完成该批四垄播种，按种子数量和密度实际扣料；参数 {'farm_id': 'soybean', 'start_ridge': 8, 'end_ridge': 11, 'depth_cm': 4.0, 'seed_spacing_cm': 4.545454545454546}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].plant_seeds(
                farm_id="soybean",
                start_ridge=12,
                end_ridge=15,
                depth_cm=4.0,
                seed_spacing_cm=4.545454545454546,
            ),
            "step0040",
            "Tractor: 完成该批四垄播种，按种子数量和密度实际扣料；参数 {'farm_id': 'soybean', 'start_ridge': 12, 'end_ridge': 15, 'depth_cm': 4.0, 'seed_spacing_cm': 4.545454545454546}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].detach_implement(),
            "step0041",
            "Tractor: 卸下当前机具，准备下一项作业；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=3448207.0),
            "step0042",
            "SystemApp: 等待管理或成熟观测窗口，两地块沿公共时钟持续生长；参数 {'seconds': 3448207.0}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "step0043",
            "WeatherApp: 核对当前真实天气，作业不能依赖未公开未来状态；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "step0044",
            "WeatherApp: 读取公开七日预报，确认管理窗口；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["MaizeSensor"].read_soil_sensors(),
            "step0045",
            "MaizeSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["MaizeField"].get_ridge_range_state(start=0, end=15),
            "step0046",
            "MaizeField: 检查本地块全部垄的生育阶段和籽粒水分；参数 {'start': 0, 'end': 15}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "step0047",
            "WeatherApp: 核对当前真实天气，作业不能依赖未公开未来状态；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "step0048",
            "WeatherApp: 读取公开七日预报，确认管理窗口；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanSensor"].read_soil_sensors(),
            "step0049",
            "SoybeanSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
            "step0050",
            "SoybeanField: 检查本地块全部垄的生育阶段和籽粒水分；参数 {'start': 0, 'end': 15}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].load_fertilizer(kg=45.225),
            "step0051",
            "Tractor: 从共同库存装入本次所需肥料；装载本身不计施用成本；参数 {'kg': 45.225}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].apply_fertilizer(
                farm_id="maize", start_ridge=0, end_ridge=9, kg_per_ridge=4.5225
            ),
            "step0052",
            "Tractor: 6月营养管理窗口施入剩余肥料；剂量来自有限候选实测选择；参数 {'farm_id': 'maize', 'start_ridge': 0, 'end_ridge': 9, 'kg_per_ridge': 4.5225}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].load_fertilizer(kg=27.134999999999998),
            "step0053",
            "Tractor: 从共同库存装入本次所需肥料；装载本身不计施用成本；参数 {'kg': 27.134999999999998}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].apply_fertilizer(
                farm_id="maize", start_ridge=10, end_ridge=15, kg_per_ridge=4.5225
            ),
            "step0054",
            "Tractor: 6月营养管理窗口施入剩余肥料；剂量来自有限候选实测选择；参数 {'farm_id': 'maize', 'start_ridge': 10, 'end_ridge': 15, 'kg_per_ridge': 4.5225}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=1814020.0),
            "step0055",
            "SystemApp: 等待管理或成熟观测窗口，两地块沿公共时钟持续生长；参数 {'seconds': 1814020.0}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "step0056",
            "WeatherApp: 核对当前真实天气，作业不能依赖未公开未来状态；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "step0057",
            "WeatherApp: 读取公开七日预报，确认管理窗口；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["MaizeSensor"].read_soil_sensors(),
            "step0058",
            "MaizeSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["MaizeField"].get_ridge_range_state(start=0, end=15),
            "step0059",
            "MaizeField: 检查本地块全部垄的生育阶段和籽粒水分；参数 {'start': 0, 'end': 15}",
        )
        previous = capture_step(
            previous,
            apps["MaizeIrrigation"].irrigate(start=0, end=15, hours=8.25),
            "step0060",
            "MaizeIrrigation: 按选定跨作物水量分配灌溉，工具检查土壤和900m³共享供水上限；参数 {'start': 0, 'end': 15, 'hours': 8.25}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(days=1),
            "step0061",
            "SystemApp: 等待管理或成熟观测窗口，两地块沿公共时钟持续生长；参数 {'days': 1}",
        )
        previous = capture_step(
            previous,
            apps["MaizeSensor"].read_soil_sensors(),
            "step0062",
            "MaizeSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=229200.0),
            "step0063",
            "SystemApp: 等待管理或成熟观测窗口，两地块沿公共时钟持续生长；参数 {'seconds': 229200.0}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "step0064",
            "WeatherApp: 核对当前真实天气，作业不能依赖未公开未来状态；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "step0065",
            "WeatherApp: 读取公开七日预报，确认管理窗口；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanSensor"].read_soil_sensors(),
            "step0066",
            "SoybeanSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
            "step0067",
            "SoybeanField: 检查本地块全部垄的生育阶段和籽粒水分；参数 {'start': 0, 'end': 15}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=5.0),
            "step0068",
            "SoybeanIrrigation: 按选定跨作物水量分配灌溉，工具检查土壤和900m³共享供水上限；参数 {'start': 0, 'end': 15, 'hours': 5.0}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(days=1),
            "step0069",
            "SystemApp: 等待管理或成熟观测窗口，两地块沿公共时钟持续生长；参数 {'days': 1}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanSensor"].read_soil_sensors(),
            "step0070",
            "SoybeanSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=759300.0),
            "step0071",
            "SystemApp: 等待管理或成熟观测窗口，两地块沿公共时钟持续生长；参数 {'seconds': 759300.0}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "step0072",
            "WeatherApp: 核对当前真实天气，作业不能依赖未公开未来状态；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "step0073",
            "WeatherApp: 读取公开七日预报，确认管理窗口；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["MaizeSensor"].read_soil_sensors(),
            "step0074",
            "MaizeSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["MaizeField"].get_ridge_range_state(start=0, end=15),
            "step0075",
            "MaizeField: 检查本地块全部垄的生育阶段和籽粒水分；参数 {'start': 0, 'end': 15}",
        )
        previous = capture_step(
            previous,
            apps["MaizeIrrigation"].irrigate(start=0, end=15, hours=8.25),
            "step0076",
            "MaizeIrrigation: 按选定跨作物水量分配灌溉，工具检查土壤和900m³共享供水上限；参数 {'start': 0, 'end': 15, 'hours': 8.25}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(days=1),
            "step0077",
            "SystemApp: 等待管理或成熟观测窗口，两地块沿公共时钟持续生长；参数 {'days': 1}",
        )
        previous = capture_step(
            previous,
            apps["MaizeSensor"].read_soil_sensors(),
            "step0078",
            "MaizeSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=315600.0),
            "step0079",
            "SystemApp: 等待管理或成熟观测窗口，两地块沿公共时钟持续生长；参数 {'seconds': 315600.0}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "step0080",
            "WeatherApp: 核对当前真实天气，作业不能依赖未公开未来状态；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "step0081",
            "WeatherApp: 读取公开七日预报，确认管理窗口；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanSensor"].read_soil_sensors(),
            "step0082",
            "SoybeanSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
            "step0083",
            "SoybeanField: 检查本地块全部垄的生育阶段和籽粒水分；参数 {'start': 0, 'end': 15}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=5.0),
            "step0084",
            "SoybeanIrrigation: 按选定跨作物水量分配灌溉，工具检查土壤和900m³共享供水上限；参数 {'start': 0, 'end': 15, 'hours': 5.0}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(days=1),
            "step0085",
            "SystemApp: 等待管理或成熟观测窗口，两地块沿公共时钟持续生长；参数 {'days': 1}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanSensor"].read_soil_sensors(),
            "step0086",
            "SoybeanSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=932100.0),
            "step0087",
            "SystemApp: 等待管理或成熟观测窗口，两地块沿公共时钟持续生长；参数 {'seconds': 932100.0}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "step0088",
            "WeatherApp: 核对当前真实天气，作业不能依赖未公开未来状态；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "step0089",
            "WeatherApp: 读取公开七日预报，确认管理窗口；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["MaizeSensor"].read_soil_sensors(),
            "step0090",
            "MaizeSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["MaizeField"].get_ridge_range_state(start=0, end=15),
            "step0091",
            "MaizeField: 检查本地块全部垄的生育阶段和籽粒水分；参数 {'start': 0, 'end': 15}",
        )
        previous = capture_step(
            previous,
            apps["MaizeIrrigation"].irrigate(start=0, end=15, hours=8.25),
            "step0092",
            "MaizeIrrigation: 按选定跨作物水量分配灌溉，工具检查土壤和900m³共享供水上限；参数 {'start': 0, 'end': 15, 'hours': 8.25}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(days=1),
            "step0093",
            "SystemApp: 等待管理或成熟观测窗口，两地块沿公共时钟持续生长；参数 {'days': 1}",
        )
        previous = capture_step(
            previous,
            apps["MaizeSensor"].read_soil_sensors(),
            "step0094",
            "MaizeSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=229200.0),
            "step0095",
            "SystemApp: 等待管理或成熟观测窗口，两地块沿公共时钟持续生长；参数 {'seconds': 229200.0}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "step0096",
            "WeatherApp: 核对当前真实天气，作业不能依赖未公开未来状态；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "step0097",
            "WeatherApp: 读取公开七日预报，确认管理窗口；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanSensor"].read_soil_sensors(),
            "step0098",
            "SoybeanSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
            "step0099",
            "SoybeanField: 检查本地块全部垄的生育阶段和籽粒水分；参数 {'start': 0, 'end': 15}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanIrrigation"].irrigate(start=0, end=15, hours=5.0),
            "step0100",
            "SoybeanIrrigation: 按选定跨作物水量分配灌溉，工具检查土壤和900m³共享供水上限；参数 {'start': 0, 'end': 15, 'hours': 5.0}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(days=1),
            "step0101",
            "SystemApp: 等待管理或成熟观测窗口，两地块沿公共时钟持续生长；参数 {'days': 1}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanSensor"].read_soil_sensors(),
            "step0102",
            "SoybeanSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=759300.0),
            "step0103",
            "SystemApp: 等待管理或成熟观测窗口，两地块沿公共时钟持续生长；参数 {'seconds': 759300.0}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "step0104",
            "WeatherApp: 核对当前真实天气，作业不能依赖未公开未来状态；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_forecast(days=7),
            "step0105",
            "WeatherApp: 读取公开七日预报，确认管理窗口；参数 {'days': 7}",
        )
        previous = capture_step(
            previous,
            apps["MaizeSensor"].read_soil_sensors(),
            "step0106",
            "MaizeSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["MaizeField"].get_ridge_range_state(start=0, end=15),
            "step0107",
            "MaizeField: 检查本地块全部垄的生育阶段和籽粒水分；参数 {'start': 0, 'end': 15}",
        )
        previous = capture_step(
            previous,
            apps["MaizeIrrigation"].irrigate(start=0, end=15, hours=8.25),
            "step0108",
            "MaizeIrrigation: 按选定跨作物水量分配灌溉，工具检查土壤和900m³共享供水上限；参数 {'start': 0, 'end': 15, 'hours': 8.25}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(days=1),
            "step0109",
            "SystemApp: 等待管理或成熟观测窗口，两地块沿公共时钟持续生长；参数 {'days': 1}",
        )
        previous = capture_step(
            previous,
            apps["MaizeSensor"].read_soil_sensors(),
            "step0110",
            "MaizeSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=2043600.0),
            "step0111",
            "SystemApp: 等待管理或成熟观测窗口，两地块沿公共时钟持续生长；参数 {'seconds': 2043600.0}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanField"].get_crop_capabilities(),
            "step0112",
            "SoybeanField: 核对当前作物的播种、成熟、收获及储存规则；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "step0113",
            "WeatherApp: 核对当前真实天气，作业不能依赖未公开未来状态；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanField"].get_ridge_range_state(start=0, end=15),
            "step0114",
            "SoybeanField: 检查本地块全部垄的生育阶段和籽粒水分；参数 {'start': 0, 'end': 15}",
        )
        previous = capture_step(
            previous,
            apps["SoybeanSensor"].read_soil_sensors(),
            "step0115",
            "SoybeanSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].refuel(liters=100.0),
            "step0116",
            "Tractor: 从共同库存补充油箱，只扣实际转入量；参数 {'liters': 100.0}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].attach_implement(implement="harvester"),
            "step0117",
            "Tractor: 切换到随后作业所需机具，沿用同一设备状态；参数 {'implement': 'harvester'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].harvest(farm_id="soybean", start_ridge=0, end_ridge=3),
            "step0118",
            "Tractor: 公开观测满足成熟和水分条件后收获四垄，仍检查天气、通行和粮箱容量；参数 {'farm_id': 'soybean', 'start_ridge': 0, 'end_ridge': 3}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].unload_grain(batch_id="soybean-2019-00"),
            "step0119",
            "Tractor: 卸空本批粮箱并保留地块、作物和垄号来源；参数 {'batch_id': 'soybean-2019-00'}",
        )
        previous = capture_step(
            previous,
            apps["Warehouse"].dry_grain(
                batch_id="soybean-2019-00", target_moisture_pct=13.0
            ),
            "step0120",
            "Warehouse: 按作物安全水分处理实际粮批，核算真实干燥吞吐；参数 {'batch_id': 'soybean-2019-00', 'target_moisture_pct': 13.0}",
        )
        previous = capture_step(
            previous,
            apps["Warehouse"].store_grain(batch_id="soybean-2019-00"),
            "step0121",
            "Warehouse: 将安全粮批实际入库，按对应作物价格计值；参数 {'batch_id': 'soybean-2019-00'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].harvest(farm_id="soybean", start_ridge=4, end_ridge=7),
            "step0122",
            "Tractor: 公开观测满足成熟和水分条件后收获四垄，仍检查天气、通行和粮箱容量；参数 {'farm_id': 'soybean', 'start_ridge': 4, 'end_ridge': 7}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].unload_grain(batch_id="soybean-2019-04"),
            "step0123",
            "Tractor: 卸空本批粮箱并保留地块、作物和垄号来源；参数 {'batch_id': 'soybean-2019-04'}",
        )
        previous = capture_step(
            previous,
            apps["Warehouse"].dry_grain(
                batch_id="soybean-2019-04", target_moisture_pct=13.0
            ),
            "step0124",
            "Warehouse: 按作物安全水分处理实际粮批，核算真实干燥吞吐；参数 {'batch_id': 'soybean-2019-04', 'target_moisture_pct': 13.0}",
        )
        previous = capture_step(
            previous,
            apps["Warehouse"].store_grain(batch_id="soybean-2019-04"),
            "step0125",
            "Warehouse: 将安全粮批实际入库，按对应作物价格计值；参数 {'batch_id': 'soybean-2019-04'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].harvest(farm_id="soybean", start_ridge=8, end_ridge=11),
            "step0126",
            "Tractor: 公开观测满足成熟和水分条件后收获四垄，仍检查天气、通行和粮箱容量；参数 {'farm_id': 'soybean', 'start_ridge': 8, 'end_ridge': 11}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].unload_grain(batch_id="soybean-2019-08"),
            "step0127",
            "Tractor: 卸空本批粮箱并保留地块、作物和垄号来源；参数 {'batch_id': 'soybean-2019-08'}",
        )
        previous = capture_step(
            previous,
            apps["Warehouse"].dry_grain(
                batch_id="soybean-2019-08", target_moisture_pct=13.0
            ),
            "step0128",
            "Warehouse: 按作物安全水分处理实际粮批，核算真实干燥吞吐；参数 {'batch_id': 'soybean-2019-08', 'target_moisture_pct': 13.0}",
        )
        previous = capture_step(
            previous,
            apps["Warehouse"].store_grain(batch_id="soybean-2019-08"),
            "step0129",
            "Warehouse: 将安全粮批实际入库，按对应作物价格计值；参数 {'batch_id': 'soybean-2019-08'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].harvest(farm_id="soybean", start_ridge=12, end_ridge=15),
            "step0130",
            "Tractor: 公开观测满足成熟和水分条件后收获四垄，仍检查天气、通行和粮箱容量；参数 {'farm_id': 'soybean', 'start_ridge': 12, 'end_ridge': 15}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].unload_grain(batch_id="soybean-2019-12"),
            "step0131",
            "Tractor: 卸空本批粮箱并保留地块、作物和垄号来源；参数 {'batch_id': 'soybean-2019-12'}",
        )
        previous = capture_step(
            previous,
            apps["Warehouse"].dry_grain(
                batch_id="soybean-2019-12", target_moisture_pct=13.0
            ),
            "step0132",
            "Warehouse: 按作物安全水分处理实际粮批，核算真实干燥吞吐；参数 {'batch_id': 'soybean-2019-12', 'target_moisture_pct': 13.0}",
        )
        previous = capture_step(
            previous,
            apps["Warehouse"].store_grain(batch_id="soybean-2019-12"),
            "step0133",
            "Warehouse: 将安全粮批实际入库，按对应作物价格计值；参数 {'batch_id': 'soybean-2019-12'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].detach_implement(),
            "step0134",
            "Tractor: 卸下当前机具，准备下一项作业；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["SystemApp"].advance_time(seconds=947396.0),
            "step0135",
            "SystemApp: 等待管理或成熟观测窗口，两地块沿公共时钟持续生长；参数 {'seconds': 947396.0}",
        )
        previous = capture_step(
            previous,
            apps["MaizeField"].get_crop_capabilities(),
            "step0136",
            "MaizeField: 核对当前作物的播种、成熟、收获及储存规则；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["WeatherApp"].get_current_weather(),
            "step0137",
            "WeatherApp: 核对当前真实天气，作业不能依赖未公开未来状态；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["MaizeField"].get_ridge_range_state(start=0, end=15),
            "step0138",
            "MaizeField: 检查本地块全部垄的生育阶段和籽粒水分；参数 {'start': 0, 'end': 15}",
        )
        previous = capture_step(
            previous,
            apps["MaizeSensor"].read_soil_sensors(),
            "step0139",
            "MaizeSensor: 观察本地块土壤状态，不把另一地块观测替代本场；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].refuel(liters=100.0),
            "step0140",
            "Tractor: 从共同库存补充油箱，只扣实际转入量；参数 {'liters': 100.0}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].attach_implement(implement="harvester"),
            "step0141",
            "Tractor: 切换到随后作业所需机具，沿用同一设备状态；参数 {'implement': 'harvester'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].harvest(farm_id="maize", start_ridge=0, end_ridge=3),
            "step0142",
            "Tractor: 公开观测满足成熟和水分条件后收获四垄，仍检查天气、通行和粮箱容量；参数 {'farm_id': 'maize', 'start_ridge': 0, 'end_ridge': 3}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].unload_grain(batch_id="maize-2019-00"),
            "step0143",
            "Tractor: 卸空本批粮箱并保留地块、作物和垄号来源；参数 {'batch_id': 'maize-2019-00'}",
        )
        previous = capture_step(
            previous,
            apps["Warehouse"].dry_grain(
                batch_id="maize-2019-00", target_moisture_pct=14.0
            ),
            "step0144",
            "Warehouse: 按作物安全水分处理实际粮批，核算真实干燥吞吐；参数 {'batch_id': 'maize-2019-00', 'target_moisture_pct': 14.0}",
        )
        previous = capture_step(
            previous,
            apps["Warehouse"].store_grain(batch_id="maize-2019-00"),
            "step0145",
            "Warehouse: 将安全粮批实际入库，按对应作物价格计值；参数 {'batch_id': 'maize-2019-00'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].harvest(farm_id="maize", start_ridge=4, end_ridge=7),
            "step0146",
            "Tractor: 公开观测满足成熟和水分条件后收获四垄，仍检查天气、通行和粮箱容量；参数 {'farm_id': 'maize', 'start_ridge': 4, 'end_ridge': 7}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].unload_grain(batch_id="maize-2019-04"),
            "step0147",
            "Tractor: 卸空本批粮箱并保留地块、作物和垄号来源；参数 {'batch_id': 'maize-2019-04'}",
        )
        previous = capture_step(
            previous,
            apps["Warehouse"].dry_grain(
                batch_id="maize-2019-04", target_moisture_pct=14.0
            ),
            "step0148",
            "Warehouse: 按作物安全水分处理实际粮批，核算真实干燥吞吐；参数 {'batch_id': 'maize-2019-04', 'target_moisture_pct': 14.0}",
        )
        previous = capture_step(
            previous,
            apps["Warehouse"].store_grain(batch_id="maize-2019-04"),
            "step0149",
            "Warehouse: 将安全粮批实际入库，按对应作物价格计值；参数 {'batch_id': 'maize-2019-04'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].harvest(farm_id="maize", start_ridge=8, end_ridge=11),
            "step0150",
            "Tractor: 公开观测满足成熟和水分条件后收获四垄，仍检查天气、通行和粮箱容量；参数 {'farm_id': 'maize', 'start_ridge': 8, 'end_ridge': 11}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].unload_grain(batch_id="maize-2019-08"),
            "step0151",
            "Tractor: 卸空本批粮箱并保留地块、作物和垄号来源；参数 {'batch_id': 'maize-2019-08'}",
        )
        previous = capture_step(
            previous,
            apps["Warehouse"].dry_grain(
                batch_id="maize-2019-08", target_moisture_pct=14.0
            ),
            "step0152",
            "Warehouse: 按作物安全水分处理实际粮批，核算真实干燥吞吐；参数 {'batch_id': 'maize-2019-08', 'target_moisture_pct': 14.0}",
        )
        previous = capture_step(
            previous,
            apps["Warehouse"].store_grain(batch_id="maize-2019-08"),
            "step0153",
            "Warehouse: 将安全粮批实际入库，按对应作物价格计值；参数 {'batch_id': 'maize-2019-08'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].harvest(farm_id="maize", start_ridge=12, end_ridge=15),
            "step0154",
            "Tractor: 公开观测满足成熟和水分条件后收获四垄，仍检查天气、通行和粮箱容量；参数 {'farm_id': 'maize', 'start_ridge': 12, 'end_ridge': 15}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].unload_grain(batch_id="maize-2019-12"),
            "step0155",
            "Tractor: 卸空本批粮箱并保留地块、作物和垄号来源；参数 {'batch_id': 'maize-2019-12'}",
        )
        previous = capture_step(
            previous,
            apps["Warehouse"].dry_grain(
                batch_id="maize-2019-12", target_moisture_pct=14.0
            ),
            "step0156",
            "Warehouse: 按作物安全水分处理实际粮批，核算真实干燥吞吐；参数 {'batch_id': 'maize-2019-12', 'target_moisture_pct': 14.0}",
        )
        previous = capture_step(
            previous,
            apps["Warehouse"].store_grain(batch_id="maize-2019-12"),
            "step0157",
            "Warehouse: 将安全粮批实际入库，按对应作物价格计值；参数 {'batch_id': 'maize-2019-12'}",
        )
        previous = capture_step(
            previous,
            apps["Tractor"].detach_implement(),
            "step0158",
            "Tractor: 卸下当前机具，准备下一项作业；参数 {}",
        )
        previous = capture_step(
            previous,
            apps["OperatingAccounts"].get_accounts(),
            "step0159",
            "OperatingAccounts: 读取公开粮价、成本口径及共享水余额，按实际消耗核算两作物经营收益；参数 {}",
        )
    return finish_capture(scene, events)
