"""Agronomic public-tool policies; no scene registry, scoring or file publishing."""
from fairy.scenarios.management_extensions.oracle_time import oracle_time_arguments

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from math import floor

from fairy.apps.farm_world import (
    FarmWorldApp,
    FieldOpsApp,
    SensorApp,
    TractorApp,
    WeatherApp,
)
from fairy.apps.system import SystemApp

from .runtime import SEEDS, crop_options


def manage_joint_fields(scene, engine, call, *, fields, irrigation_shift_days=0):
    """A public-tool policy parameterized per plot, including repeated crop species."""
    if set(fields) != {f.farm_id for f in scene.farms}:
        raise ValueError("Candidate must declare every field exactly once")

    def until(day):
        target = (
            datetime.fromisoformat(str(scene.start.year) + "-" + day + "T07:00:00")
            .replace(tzinfo=ZoneInfo(scene.timezone_name))
            .timestamp()
        )
        delta = target - engine.time_manager.time()
        if delta < 0:
            raise RuntimeError(f"Passed candidate management date {day}")
        if delta:
            call(scene.system, "advance_time", **oracle_time_arguments(delta))

    def observe(farm):
        call(scene.weather, "get_current_weather")
        call(scene.weather, "get_forecast", days=7)
        call(scene.sensors[farm.farm_id], "read_soil_sensors")
        call(farm, "get_ridge_range_state", start=0, end=farm.num_ridges - 1)

    call(scene.accounts, "get_accounts")
    call(scene.warehouse, "get_inventory")
    for farm in scene.farms:
        crop = farm.crop_id
        opt = crop_options(farm)[crop]
        call(farm, "get_crop_capabilities")
        observe(farm)
        call(scene.tractor, "get_status")
        call(scene.tractor, "attach_implement", implement="grader")
        call(scene.tractor, "level", farm_id=farm.farm_id)
        call(scene.tractor, "detach_implement")
        fertilizer = (
            fields[farm.farm_id]["fertilizer_kg_ha"] * farm.field_area_m2 / 10000
        )
        if fertilizer:
            call(scene.tractor, "load_fertilizer", kg=fertilizer / 2)
            call(
                scene.tractor,
                "base_fertilize",
                farm_id=farm.farm_id,
                total_kg=fertilizer / 2,
            )
        call(scene.tractor, "attach_implement", implement="furrower")
        call(
            scene.tractor,
            "form_ridges",
            farm_id=farm.farm_id,
            ridge_width_m=farm.ridge_width_m,
        )
        call(scene.tractor, "detach_implement")
        call(scene.tractor, "attach_implement", implement="seeder")
        call(
            scene.tractor,
            "load_seeds",
            seed_type=SEEDS[crop],
            count=opt["required_seeds"],
        )
        for start in range(0, farm.num_ridges, 4):
            call(
                scene.tractor,
                "plant_seeds",
                farm_id=farm.farm_id,
                start_ridge=start,
                end_ridge=min(start + 3, farm.num_ridges - 1),
                depth_cm=opt["depth_cm"],
                seed_spacing_cm=opt["spacing_cm"],
            )
        call(scene.tractor, "detach_implement")
    until("06-10")
    for farm in scene.farms:
        observe(farm)
    for farm in scene.farms:
        total = (
            fields[farm.farm_id]["fertilizer_kg_ha"] * farm.field_area_m2 / 10000 / 2
        )
        if total:
            for start in range(0, farm.num_ridges, 10):
                end = min(start + 9, farm.num_ridges - 1)
                call(
                    scene.tractor,
                    "load_fertilizer",
                    kg=total * (end - start + 1) / farm.num_ridges,
                )
                call(
                    scene.tractor,
                    "apply_fertilizer",
                    farm_id=farm.farm_id,
                    start_ridge=start,
                    end_ridge=end,
                    kg_per_ridge=total / farm.num_ridges,
                )
    schedule = sorted(
        (
            day,
            farm.farm_id,
            fields[farm.farm_id]["water_mm"]
            / len(fields[farm.farm_id]["irrigation_dates"]),
        )
        for farm in scene.farms
        for day in fields[farm.farm_id]["irrigation_dates"]
    )
    for day, farm_id, mm in schedule:
        shifted = (
            datetime.fromisoformat(str(scene.start.year) + "-" + day)
            + timedelta(days=irrigation_shift_days)
        ).strftime("%m-%d")
        until(shifted)
        farm = next(f for f in scene.farms if f.farm_id == farm_id)
        observe(farm)
        if mm:
            call(
                scene.irrigation[farm_id],
                "irrigate",
                start=0,
                end=farm.num_ridges - 1,
                hours=mm / 5,
            )
            call(scene.system, "advance_time", days=1)
            call(scene.sensors[farm.farm_id], "read_soil_sensors")
    for day, farm_id in sorted(
        (fields[f.farm_id]["harvest_not_before"], f.farm_id) for f in scene.farms
    ):
        target = (
            datetime.fromisoformat(str(scene.start.year) + "-" + day + "T07:00:00")
            .replace(tzinfo=ZoneInfo(scene.timezone_name))
            .timestamp()
        )
        if target > engine.time_manager.time():
            until(day)
        farm = next(f for f in scene.farms if f.farm_id == farm_id)
        caps = call(farm, "get_crop_capabilities")
        while True:
            weather = call(scene.weather, "get_current_weather")
            states = call(
                farm, "get_ridge_range_state", start=0, end=farm.num_ridges - 1
            )["ridges"]
            ready = all(
                r["growth_stage"] in caps["harvest"]["stage_codes"]
                and r["grain_moisture_pct"] <= caps["harvest"]["max_moisture_pct"]
                for r in states
            )
            if ready and weather["rainfall_mm"] == 0:
                break
            if engine.time_manager.time() + 86400 > scene.start_time + scene.duration:
                raise RuntimeError("No observed safe harvest window before deadline")
            call(scene.system, "advance_time", days=1)
        call(scene.sensors[farm.farm_id], "read_soil_sensors")
        call(scene.tractor, "refuel", liters=100.0)
        call(scene.tractor, "attach_implement", implement="harvester")
        for start in range(0, farm.num_ridges, 4):
            batch = f"{farm.farm_id}-{scene.start.year}-{start:02d}"
            call(
                scene.tractor,
                "harvest",
                farm_id=farm.farm_id,
                start_ridge=start,
                end_ridge=min(start + 3, farm.num_ridges - 1),
            )
            call(scene.tractor, "unload_grain", batch_id=batch)
            call(
                scene.warehouse,
                "dry_grain",
                batch_id=batch,
                target_moisture_pct=min(
                    scene.safe_moisture_pct,
                    farm._postharvest_market.max_storage_moisture_pct,
                ),
            )
            call(scene.warehouse, "store_grain", batch_id=batch)
        call(scene.tractor, "detach_implement")


def manage_annual_maize(scene, engine, call, *, seasons):
    """Observed maize policy for any declared number of annual crop seasons.

    The crop-specific sowing density and management windows are deliberate;
    other crops require a suitable policy, not a disguised maize recipe.
    """
    if len(seasons) != len(scene.seasons) or scene.field["crop_id"] != "maize":
        raise ValueError("Declare one maize allocation per planned season")
    farm = scene.get_typed_app(FarmWorldApp)
    tractor = scene.get_typed_app(TractorApp)
    weather = scene.get_typed_app(WeatherApp)
    sensor = scene.get_typed_app(SensorApp)
    ops = scene.get_typed_app(FieldOpsApp)
    system = scene.get_typed_app(SystemApp)

    def until(day):
        target = datetime.combine(day, time(7), farm.simulation_timezone).timestamp()
        if target > engine.time_manager.time():
            call(system, "advance_time", **oracle_time_arguments(target - engine.time_manager.time()))

    for index, (season, allocation) in enumerate(zip(scene.seasons, seasons)):
        year, sow = season.year, season.sowing_date
        fertilizer, water = allocation["fertilizer_kg"], allocation["water_mm"]
        until(sow)
        if index:
            call(scene.cycle, "open_next_season", year=year)
        call(weather, "get_current_weather")
        call(farm, "get_inventory")
        call(tractor, "attach_implement", implement="grader")
        call(tractor, "level")
        call(tractor, "detach_implement")
        call(tractor, "load_fertilizer", kg=min(200.0, fertilizer))
        call(tractor, "base_fertilize", total_kg=min(200.0, fertilizer))
        call(tractor, "attach_implement", implement="furrower")
        call(tractor, "form_ridges", ridge_width_m=farm.ridge_width_m)
        call(tractor, "detach_implement")
        call(
            tractor,
            "load_seeds",
            seed_type=scene.field["seed_type"],
            count=int(farm.field_length_m / 0.2) * farm.num_ridges,
        )
        for start in range(0, farm.num_ridges, 4):
            call(
                tractor,
                "plant_seeds",
                start_ridge=start,
                end_ridge=min(start + 3, farm.num_ridges - 1),
                depth_cm=4.0,
                seed_spacing_cm=20.0,
            )
        call(farm, "commit_daily_physics")
        for day in sorted({15, 30, 20, 60, 70, 80}):
            until(sow + timedelta(days=day))
            call(weather, "get_forecast", days=7)
            call(farm, "get_farm_overview")
            if day in (15, 30) and fertilizer > 200:
                call(
                    farm,
                    "apply_fertigation",
                    start_ridge=0,
                    end_ridge=farm.num_ridges - 1,
                    nutrient_amount=(fertilizer - 200) / 2 / (30 * farm.num_ridges),
                    water_mm=0.0,
                )
            if day in (20, 60, 70, 80) and water:
                observation = call(sensor, "read_soil_sensors")
                readings = observation["soil_sensors"]
                if readings and all(probe["vwc"] < 0.28 for probe in readings):
                    call(
                        ops,
                        "irrigate",
                        start=0,
                        end=farm.num_ridges - 1,
                        hours=water / 4 / 5,
                    )
        # Public maturity and weather observations determine harvest readiness.
        for day in range(99, 171):
            until(sow + timedelta(days=day))
            state = call(
                farm, "get_ridge_range_state", start=0, end=farm.num_ridges - 1
            )
            conditions = call(weather, "get_current_weather")
            rows = state.get("ridges", []) if isinstance(state, dict) else state
            if (
                rows
                and all(
                    r.get("growth_stage") in ("MATURE", "R8")
                    and r.get("grain_moisture_pct", 100)
                    <= scene.maximum_harvest_moisture_pct
                    for r in rows
                )
                and conditions.get("rainfall_mm", 0) == 0
            ):
                break
        call(tractor, "refuel", liters=100.0)
        for start in range(0, farm.num_ridges, 4):
            call(
                tractor,
                "harvest",
                start_ridge=start,
                end_ridge=min(start + 3, farm.num_ridges - 1),
            )
            call(tractor, "unload_grain")
        call(farm, "dry_grain", target_moisture_pct=scene.safe_moisture_pct)
        call(farm, "store_grain")
        call(scene.cycle, "close_season", year=year)


def manage_rotating_crops(
    scene,
    engine,
    call,
    *,
    allocations,
    market_actions=None,
    policy_actions=None,
    resume_first_season=False,
):
    """Offline public-tool candidates for annual crop choice and resource planning.

    Scenario runtime uses only its own frozen literal workflow. No optimization
    or future yield reads are performed by the scenario initialization.
    """
    farm = scene.get_typed_app(FarmWorldApp)
    tractor = scene.get_typed_app(TractorApp)
    weather = scene.get_typed_app(WeatherApp)
    sensor = scene.get_typed_app(SensorApp)
    system = scene.get_typed_app(SystemApp)
    ops = scene.get_typed_app(FieldOpsApp)
    if len(allocations) != len(scene.seasons):
        raise ValueError("Declare one public management allocation per season")

    def until(day):
        target = datetime.combine(day, time(7), farm.simulation_timezone).timestamp()
        if target > engine.time_manager.time():
            call(system, "advance_time", **oracle_time_arguments(target - engine.time_manager.time()))

    for index, (season, allocation) in enumerate(zip(scene.seasons, allocations)):
        crop = allocation["crop_id"]
        fertilizer = allocation["fertilizer_kg"]
        water = allocation["water_mm"]
        if index == 0 and crop != farm.crop_type:
            call(scene.cycle, "select_first_crop", crop_id=crop)
        sow = season.sowing_date
        if index and policy_actions is not None:
            until(date(season.year, 3, 25))
            call(
                scene.subsidy,
                "search_policies",
                year=season.year,
                county=scene.registered_county,
            )
        until(sow)
        if index:
            call(scene.cycle, "get_crop_options")
            call(scene.cycle, "get_season_ledger")
            if tractor._seed_hopper and tractor.seed_type != (
                "MAIZE_201" if crop == "maize" else "SOYBEAN_901"
            ):
                call(scene.cycle, "unload_unused_seeds")
            call(scene.cycle, "open_next_crop", year=season.year, crop_id=crop)
        if not (index == 0 and resume_first_season):
            call(weather, "get_current_weather")
            call(weather, "get_forecast", days=7)
            call(farm, "get_inventory")
            call(farm, "get_crop_capabilities")
            call(sensor, "read_soil_sensors")
            if hasattr(scene, "market"):
                inventory = call(farm, "get_inventory")
                machine = call(tractor, "get_status")
                stock = inventory["fertilizer_kg"] + machine["fertilizer_spreader_kg"]
                if fertilizer > stock:
                    offers = call(scene.market, "get_offers")
                    active = [
                        o
                        for o in offers["offers"]
                        if o["valid_from"] <= offers["date"] <= o["valid_until"]
                    ]
                    if active:
                        offer = min(active, key=lambda o: o["unit_price"])
                        amount = min(
                            fertilizer - stock, offers["cash"] / offer["unit_price"]
                        )
                        if amount > 1e-8:
                            call(
                                scene.market,
                                "purchase_fertilizer",
                                offer_id=offer["offer_id"],
                                kg=amount,
                                order_id=f"season-{season.year}",
                            )
                inventory = call(farm, "get_inventory")
                fertilizer = min(
                    fertilizer,
                    inventory["fertilizer_kg"] + machine["fertilizer_spreader_kg"],
                )
            call(tractor, "attach_implement", implement="grader")
            call(tractor, "level")
            call(tractor, "detach_implement")
            base = min(50.0, fertilizer)
            if base:
                call(tractor, "load_fertilizer", kg=base)
                call(tractor, "base_fertilize", total_kg=base)
            call(tractor, "attach_implement", implement="furrower")
            call(tractor, "form_ridges", ridge_width_m=farm.ridge_width_m)
            call(tractor, "detach_implement")
            rows = 1 if crop == "maize" else 2
            density = 20 / 3 if crop == "maize" else 40.0
            spacing = 100 * rows / (farm.ridge_width_m * density)
            count = round(farm.field_length_m * rows * 100 / spacing) * farm.num_ridges
            seed = "MAIZE_201" if crop == "maize" else "SOYBEAN_901"
            call(tractor, "load_seeds", seed_type=seed, count=count)
            for start in range(0, farm.num_ridges, 4):
                call(
                    tractor,
                    "plant_seeds",
                    start_ridge=start,
                    end_ridge=min(start + 3, farm.num_ridges - 1),
                    depth_cm=4.0,
                    seed_spacing_cm=spacing,
                )
            call(farm, "commit_daily_physics")
            if (
                index
                and (policy_actions or {}).get("apply", True)
                and policy_actions is not None
            ):
                call(
                    scene.subsidy,
                    "apply_for_subsidy",
                    year=season.year,
                    crop_id=crop,
                    county=scene.registered_county,
                    document_id="jilin_2025_march_program",
                )
            for day in (15, 20, 30, 60, 70, 80):
                until(sow + timedelta(days=day))
                call(weather, "get_forecast", days=7)
                call(farm, "get_farm_overview")
                if day in (15, 30) and fertilizer > base:
                    # The existing tool settles product use to 0.0001 kg.
                    # Cash-limited USD purchases can leave fractional stock: do
                    # not round two planned half-doses above available product.
                    dose_kg = floor((fertilizer - base) / 2 * 10000) / 10000
                    call(
                        farm,
                        "apply_fertigation",
                        start_ridge=0,
                        end_ridge=farm.num_ridges - 1,
                        nutrient_amount=dose_kg / (30 * farm.num_ridges),
                        water_mm=0.0,
                    )
                if day in (20, 60, 70, 80) and water:
                    observation = call(sensor, "read_soil_sensors")
                    readings = observation["soil_sensors"]
                    if readings and all(probe["vwc"] < 0.28 for probe in readings):
                        call(
                            ops,
                            "irrigate",
                            start=0,
                            end=farm.num_ridges - 1,
                            hours=water / 4 / 5,
                        )
        cap = call(farm, "get_crop_capabilities")
        ready = False
        for day in range(99, 180):
            until(sow + timedelta(days=day))
            state = call(
                farm, "get_ridge_range_state", start=0, end=farm.num_ridges - 1
            )
            conditions = call(weather, "get_current_weather")
            rows = state.get("ridges", [])
            if (
                rows
                and all(
                    r["growth_stage"] in cap["harvest"]["stage_codes"]
                    and r["grain_moisture_pct"] <= cap["harvest"]["max_moisture_pct"]
                    for r in rows
                )
                and conditions.get("rainfall_mm", 0) == 0
            ):
                ready = True
                break
        if not ready:
            raise ValueError("No real safe harvest window before the annual deadline")
        call(tractor, "refuel", liters=100.0)
        for start in range(0, farm.num_ridges, 4):
            call(
                tractor,
                "harvest",
                start_ridge=start,
                end_ridge=min(start + 3, farm.num_ridges - 1),
            )
            call(tractor, "unload_grain")
        call(farm, "dry_grain", target_moisture_pct=14.0 if crop == "maize" else 13.0)
        call(farm, "store_grain")
        call(scene.cycle, "close_season", year=season.year)
        if index and policy_actions is not None:
            until(date(season.year, 9, 11))
            call(
                scene.subsidy,
                "search_policies",
                year=season.year,
                county=scene.registered_county,
            )
            if policy_actions.get("apply", True) and policy_actions.get(
                "collect", True
            ):
                call(scene.subsidy, "collect_subsidy", year=season.year)
        if (
            hasattr(scene, "market")
            and index == 0
            and (market_actions or {}).get("mode") == "stock_up"
        ):
            until(date(season.year, 10, 1))
            offers = call(scene.market, "get_offers")
            inventory = call(farm, "get_inventory")
            machine = call(tractor, "get_status")
            target = (
                allocations[index + 1]["fertilizer_kg"]
                - inventory["fertilizer_kg"]
                - machine["fertilizer_spreader_kg"]
            )
            active = [
                o
                for o in offers["offers"]
                if o["valid_from"] <= offers["date"] <= o["valid_until"]
            ]
            if active:
                offer = min(active, key=lambda o: o["unit_price"])
                amount = min(target, offers["cash"] / offer["unit_price"])
                if amount > 1e-8:
                    call(
                        scene.market,
                        "purchase_fertilizer",
                        offer_id=offer["offer_id"],
                        kg=amount,
                        order_id="next-season-reserve",
                    )
    call(scene.cycle, "get_accounts")
    if hasattr(scene, "market"):
        call(scene.market, "get_purchase_accounts")
    if policy_actions is not None:
        call(scene.subsidy, "get_subsidy_accounts")


def manage_soybean_pest_choice(scene, engine, call, *, treatments, water_mm=180.0):
    """Full-season public-tool candidate; product choice and treatment dates stay explicit."""
    farm = scene.farms[0]
    field_id = farm.farm_id
    options = crop_options(farm)["soybean"]

    def until(month_day):
        day = datetime.fromisoformat(f"{scene.start.year}-{month_day}T07:00:00")
        target = day.replace(tzinfo=ZoneInfo(scene.timezone_name)).timestamp()
        if target > engine.time_manager.time():
            call(
                scene.system,
                "advance_time",
                **oracle_time_arguments(target - engine.time_manager.time()),
            )

    def observe():
        call(scene.weather, "get_current_weather")
        call(scene.weather, "get_forecast", days=7)
        call(scene.sensors[field_id], "read_soil_sensors")
        call(scene.protection, "scout")

    call(scene.accounts, "get_accounts")
    call(scene.warehouse, "get_inventory")
    catalog = call(scene.protection, "get_products")
    products = {p["product_id"]: p for p in catalog["products"]}
    call(farm, "get_crop_capabilities")
    observe()
    call(scene.tractor, "get_status")
    call(scene.tractor, "attach_implement", implement="grader")
    call(scene.tractor, "level", farm_id=field_id)
    call(scene.tractor, "detach_implement")
    call(scene.tractor, "attach_implement", implement="furrower")
    call(
        scene.tractor, "form_ridges", farm_id=field_id, ridge_width_m=farm.ridge_width_m
    )
    call(scene.tractor, "detach_implement")
    call(scene.tractor, "attach_implement", implement="seeder")
    call(
        scene.tractor,
        "load_seeds",
        seed_type="SOYBEAN_901",
        count=options["required_seeds"],
    )
    for start in range(0, farm.num_ridges, 4):
        call(
            scene.tractor,
            "plant_seeds",
            farm_id=field_id,
            start_ridge=start,
            end_ridge=min(start + 3, farm.num_ridges - 1),
            depth_cm=options["depth_cm"],
            seed_spacing_cm=options["spacing_cm"],
        )
    call(scene.tractor, "detach_implement")
    water_days = ("06-20", "07-10", "07-25", "08-10")
    scout_days = (
        "06-20",
        "06-27",
        "07-01",
        "07-08",
        "07-15",
        "07-22",
        "07-29",
        "08-05",
        "08-12",
        "08-19",
    )
    for day in sorted(
        set(water_days) | set(scout_days) | {r["day"] for r in treatments}
    ):
        until(day)
        observe()
        for index, treatment in enumerate(treatments):
            if treatment["day"] != day:
                continue
            product = products[treatment["product_id"]]
            account = call(scene.protection, "get_protection_accounts")
            first_ridge_history = sorted(
                (r for r in account["applications"].values() if 0 in r["ridge_ids"]),
                key=lambda r: r["timestamp"],
            )
            consecutive = 0
            for previous in reversed(first_ridge_history):
                if previous["product_id"] != product["product_id"]:
                    break
                consecutive += 1
            if consecutive >= product["max_consecutive_applications"]:
                raise ValueError(
                    "Candidate violates retained consecutive-application limit"
                )
            rate = (
                product["min_rate_per_ha"]
                if treatment.get("rate", "min") == "min"
                else product["max_rate_per_ha"]
            )
            account = call(scene.protection, "get_protection_accounts")
            eligible = []
            for prior in account["applications"].values():
                interval = catalog["simulation_assumptions"][
                    "minimum_service_interval_days"
                ]
                if prior["product_id"] == product["product_id"]:
                    interval = max(interval, product["min_interval_days"])
                prior_day = datetime.fromtimestamp(
                    prior["timestamp"], ZoneInfo(scene.timezone_name)
                ).date()
                eligible.append(prior_day + timedelta(days=interval))
            if eligible:
                until(max(eligible).strftime("%m-%d"))
            for _ in range(8):
                weather = call(scene.weather, "get_current_weather")
                if weather["rainfall_mm"] == 0 and weather["wind_speed_ms"] <= 5.0:
                    break
                call(scene.system, "advance_time", days=1)
                call(scene.protection, "scout")
            else:
                raise RuntimeError("No observed ground-spray window within eight days")
            call(
                scene.protection,
                "purchase",
                product_id=product["product_id"],
                quantity=rate * farm.field_area_m2 / 10000,
                order_id=f"t{index}-purchase",
            )
            for start in range(0, farm.num_ridges, 4):
                call(
                    scene.protection,
                    "apply",
                    product_id=product["product_id"],
                    start_ridge=start,
                    end_ridge=min(start + 3, farm.num_ridges - 1),
                    rate_per_ha=rate,
                    application_id=f"t{index}-r{start}",
                )
            call(scene.protection, "get_protection_accounts")
            call(scene.system, "advance_time", days=1)
            call(scene.protection, "scout")
        if day in water_days and water_mm:
            call(
                scene.irrigation[field_id],
                "irrigate",
                start=0,
                end=farm.num_ridges - 1,
                hours=water_mm / len(water_days) / 5,
            )
            call(scene.system, "advance_time", days=1)
            call(scene.sensors[field_id], "read_soil_sensors")
    until("09-01")
    caps = call(farm, "get_crop_capabilities")
    protection = call(scene.protection, "get_protection_accounts")
    harvest_from = max(
        (r["harvest_allowed_from"] for r in protection["applications"].values()),
        default="1900-01-01",
    )
    while True:
        weather = call(scene.weather, "get_current_weather")
        states = call(farm, "get_ridge_range_state", start=0, end=farm.num_ridges - 1)[
            "ridges"
        ]
        ready = all(
            r["growth_stage"] in caps["harvest"]["stage_codes"]
            and r["grain_moisture_pct"] <= caps["harvest"]["max_moisture_pct"]
            for r in states
        )
        today = (
            datetime.fromtimestamp(
                engine.time_manager.time(), ZoneInfo(scene.timezone_name)
            )
            .date()
            .isoformat()
        )
        if ready and weather["rainfall_mm"] == 0 and today >= harvest_from:
            break
        if engine.time_manager.time() + 86400 > scene.start_time + scene.duration:
            raise RuntimeError("No actual safe harvest window before the deadline")
        call(scene.system, "advance_time", days=1)
    call(scene.tractor, "refuel", liters=100.0)
    call(scene.tractor, "attach_implement", implement="harvester")
    for start in range(0, farm.num_ridges, 4):
        batch = f"soybean-{scene.start.year}-{start:02d}"
        call(
            scene.tractor,
            "harvest",
            farm_id=field_id,
            start_ridge=start,
            end_ridge=min(start + 3, farm.num_ridges - 1),
        )
        call(scene.tractor, "unload_grain", batch_id=batch)
        call(
            scene.warehouse,
            "dry_grain",
            batch_id=batch,
            target_moisture_pct=scene.safe_moisture_pct,
        )
        call(scene.warehouse, "store_grain", batch_id=batch)
    call(scene.tractor, "detach_implement")
    call(scene.protection, "get_protection_accounts")
    call(scene.accounts, "get_accounts")


def manage_soybean_variety_choice(
    scene, engine, call, *, seed_type, water_mm, shift_days=0
):
    """Select an unchanged official variety, then reuse the existing agronomic operations."""
    call(scene.selection, "get_options")
    call(scene.selection, "select_variety", seed_type=seed_type)

    def selected_seed_call(app, method, **args):
        if app is scene.tractor and method == "load_seeds":
            args["seed_type"] = seed_type
        return call(app, method, **args)

    manage_joint_fields(
        scene,
        engine,
        selected_seed_call,
        fields={
            "soybean": {
                "fertilizer_kg_ha": 0.0,
                "water_mm": water_mm,
                "irrigation_dates": ["07-05", "07-20", "08-05"],
                "harvest_not_before": "09-01",
            }
        },
        irrigation_shift_days=shift_days,
    )


def manage_scn_rotation(scene, engine, call, *, allocations):
    """Observe real simulated soil populations before planting and after each actual harvest."""
    call(scene.scn, "sample_soil")

    def sampled_call(app, method, **args):
        result = call(app, method, **args)
        if app is scene.cycle and method == "close_season":
            call(scene.scn, "sample_soil")
        return result

    manage_rotating_crops(scene, engine, sampled_call, allocations=allocations)
