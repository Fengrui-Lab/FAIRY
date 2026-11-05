"""Two crops, two 64-ridge plots, with source-backed disease/water management.

Composition sources (all under fairy/scenarios/two_farm):
* scenario_two_farm_maize_soybean_full_season: crop identities, geometry,
  planting, implements, nutrition, harvest/storage and provenance checks.
* scenario_two_farm_full_season_hn84_disease_water: shared seed-1628 weather,
  four separate 18-mm June rain days, August dry spell, initial soybean
  disease history (20--39), soil hydraulics, 3.8-L/ridge fungicide, seven-day
  disease follow-up, and targeted 4-hour irrigation with next-day rechecks.

This is a new integration of existing mechanisms, not a copy of either
scenario's validated results. No scheduled yield/recovery assignments or
Oracle-only disturbances are used. The legacy maize cultivar is uncalibrated.
Internal crop IDs remain stable; plot_labels supplies the English UI names.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from math import isclose, isfinite
from dataclasses import replace
from datetime import timedelta

from fairy.apps.farm_world.shared_drone_app import SharedDroneApp
from fairy.physics.soil_engine import SoilHydraulicModifier
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.scenario import Scenario
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.scenarios.two_farm.scenario_two_farm_maize_soybean_full_season import (
    MAIZE_CULTIVAR, SOYBEAN_CULTIVAR, MAIZE_SPACING_CM, SOYBEAN_SPACING_CM,
    NUM_RIDGES, ScenarioTwoFarmMaizeSoybeanFullSeason,
)
from fairy.scenarios.two_farm.scenario_two_farm_full_season_hn84_disease_water import (
    BASE_WEATHER_PROFILE,
)

SCENARIO_ID = "scenario_two_farm_soybean_maize_disease_water"
TARGET_RIDGES = tuple(range(20, 40))
PLOT_LABELS = {"soybean_field": "farm plot A", "maize_field": "farm plot B"}
BRIEFING = """Manage farm plot A (soybean_field, HEINONG84) and farm plot B
(maize_field, MAIZE_EARLY_2026) from bare soil to separately stored grain.
Both have 64 ridges of length 268 m. Soybean uses 1.1-m ridges, two rows,
8-cm spacing and 4-cm sowing depth; maize uses 0.65-m ridges, one row,
25-cm spacing and 5-cm depth. Use soybean_planter/harvester for soybean and
maize_planter/maize_header for maize. Seed demand is 428800/68608 respectively.

The plots share regional weather, a clock, Tractor, Mavic3M, Matrice4T,
Robot0 and Warehouse. Each crop has its own named sensor and irrigation
installation. Mobile field tools require farm_id. Loading/returning supplies
acts on shared equipment. Keep seed and grain origins separate.

Soybean ridges 20--39 have elevated previous-disease risk; establish current
disease using canopy, multispectral and ground observations before treatment.
The inherited simulation reference uses 3.8 L/ridge fungicide on 20--39,
76 L total, in two ten-ridge passes on one application day. Reinspect the
same ground samples after seven days; do not prescribe chemicals to maize
just because soybean needs treatment. These are simulation product amounts.

Maize ridges 20--39 have the inherited lower-water-holding soil. Compare
local soil trends, canopy, crop stage and the shared rainfall forecast before
targeted irrigation. The reference dose is 4 hours (20 mm per treated ridge),
with surface and next-day infiltration checks. Reassess before repeating.
Surface sensors are observations, not exact root-zone simulation truth.

Both crops receive 200 kg base fertilizer product. Maize topdressing is
6 kg/ridge; soybean is 2 kg/ridge. Seasonal fertilizer limits are 650/400 kg;
water limits are 30/20 full-field-equivalent mm for maize/soybean. The soybean
fungicide limit is one application day. Local 20-ridge irrigation at 20 mm
uses 6.25 full-field-equivalent mm. Observe before every intervention.

Inspect each crop's actual maturity: maize R6 with grain moisture <=30%,
soybean R8 <=18%, with suitable weather/trafficability. Harvest up to four
ridges per pass, unload a uniquely traced batch, and dry/store separately:
maize <=14%, soybean <=13.5% (reference drying target 13%). Finish all 64
ridges per crop and leave no unaccounted seed, chemical or grain payload.
The synthetic weather and uncalibrated maize model support a demo, not a
field yield forecast. All waits advance both plots together.
""".strip()


@register_scenario(SCENARIO_ID)
class ScenarioTwoFarmSoybeanMaizeDiseaseWater(ScenarioTwoFarmMaizeSoybeanFullSeason):
    # Scenario's dataclass migration reads concrete class attributes only.
    start_time = ScenarioTwoFarmMaizeSoybeanFullSeason.start_time
    duration = ScenarioTwoFarmMaizeSoybeanFullSeason.duration
    queue_based_loop = True
    time_increment_in_seconds = 60
    expects_agent_harvest = True
    additional_system_prompt = BRIEFING

    def __post_init__(self):
        Scenario.__post_init__(self)
        if type(self.detailed_briefing) is not bool:
            raise ValueError("detailed_briefing must be a JSON boolean")
        if self.crop_backend != "legacy" or self.crop_backend_options:
            raise ValueError("This integrated reference requires the legacy crop backend")
        if not self.scenario_input:
            self.scenario_input = BRIEFING

    def init_and_populate_apps(self):
        super().init_and_populate_apps()
        self.plot_labels = dict(PLOT_LABELS)
        self.warehouse.stock.pesticide_liters = 320.0  # Original disease/water stock.
        self.matrice = SharedDroneApp(
            self.farm_environment, name="Matrice4T", speed_ms=4.0,
            effective_ridges_per_pass=5, battery_pct_per_ridge=1.5,
        )
        self.matrice.register_time_manager(self.farm_environment.time_manager)
        self.matrice.set_seed(self.seed)
        self.shared_equipment.append(self.matrice)
        self.apps.append(self.matrice)

        # Exact soil and risk parameters from the original disease/water scene.
        black_soil = SoilHydraulicModifier(
            root_depth_m=1.45, field_capacity_vwc=0.37,
            top_drainage_rate=0.22, root_drainage_rate=0.03,
            rainfall_capture_efficiency=0.97, irrigation_efficiency=0.92,
            max_infiltration_mm_day=85.0,
        )
        low_holding = SoilHydraulicModifier(
            root_depth_m=0.80, field_capacity_vwc=0.29,
            top_drainage_rate=0.22, root_drainage_rate=0.30,
            rainfall_capture_efficiency=0.66, irrigation_efficiency=0.80,
            max_infiltration_mm_day=72.0,
        )
        for farm, cultivar in ((self.maize, MAIZE_CULTIVAR), (self.soybean, SOYBEAN_CULTIVAR)):
            for ridge in farm._ridges:
                ridge.soil_vwc = 0.30 + ((ridge.ridge_id % 5) - 2) * 0.003
                ridge.pest_pressure_base = ridge.pest_pressure = 0.02
                ridge.disease_pressure_base = ridge.disease_pressure = 0.02
            farm.configure_physics_profile(
                BASE_WEATHER_PROFILE, location="Harbin/Heilongjiang",
                seed_type=cultivar, cultivar=cultivar, start_date="2026-05-15",
            )
            profile = deepcopy(farm.physics.profile)
            profile.biotic_outbreaks = []
            profile.weather_events = [
                replace(event, start_date=event.start_date + timedelta(days=offset),
                        duration_days=1, rain_mm=18.0)
                if event.event_type == "rain_event" else event
                for event in profile.weather_events
                for offset in range(event.duration_days if event.event_type == "rain_event" else 1)
            ]
            farm.physics.profile = profile
            farm.physics.soil.set_hydraulic_modifiers({
                rid: low_holding if farm is self.maize and rid in TARGET_RIDGES else black_soil
                for rid in range(64)
            })
        for ridge in self.soybean._ridges[20:40]:
            ridge.disease_pressure_base = ridge.disease_pressure = 0.20
        self.soybean._management_regime.max_fungicide_applications = 1
        self._initial_stock = deepcopy(self.warehouse.stock)

    def _reference_actions(self):
        actions = []

        def add(name, app, method, reason, **args):
            actions.append((name, app, method, args, reason))

        for name, app, method, args, _ in super()._reference_actions():
            # Keep crop-specific operations; all new replay text is English.
            reason = f"{name.replace('_', ' ')}: execute {method} with the target crop's rules."
            if name == "report":
                args = {"content": "Reference operations finished for farm plot A (soybean) and farm plot B (maize). Check disease and water follow-ups, both 64-ridge harvests, 32 traced storage batches and shared supplies in the validation report. Results are simulated."}
            if name == "wait_emergence":
                args = {"days": 11}
            if name == "wait_vegetative":
                add("emergence_revisit_wait", self.system, "advance_time",
                    "Revisit seedlings at the mixed-crop source's 17-day checkpoint after the earlier dry-weather survey.", days=6)
                for farm, sensor in ((self.maize, self.maize_sensor), (self.soybean, self.soybean_sensor)):
                    add(f"emergence_revisit_{farm.farm_id}", farm, "get_ridge_range_state",
                        "Confirm actual emergence; an earlier bare-field observation is insufficient.", start=0, end=63)
                    add(f"emergence_revisit_{farm.farm_id}_soil", sensor, "read_soil_sensors",
                        "Record the plot's soil conditions at the emergence revisit.")
                args = {"days": 24}
            if name == "wait_silking":
                args = {"days": 24, "hours": 12}
            if name == "wait_soybean_harvest":
                args = {"days": 19}
                reason = "Recheck soybean maturity and grain moisture in its later shared-weather harvest window."
            if name == "wait_maize_harvest":
                args = {"days": 31}
                reason = "Use the forecast dry window, then recheck actual maize maturity and trafficability."
            if name == "silking_maize_water":
                # Water diagnosis/treatment is deferred to the inherited August dry spell.
                continue
            if name == "silking_infiltration":
                continue  # No July irrigation: retain the original seven-day disease interval.
            if name == "silking_maize_field_health":
                add("disease_multispectral", self.mavic, "fly_survey",
                    "Locate the soybean anomaly before the source scenario's ground diagnosis.",
                    farm_id="soybean_field", start_ridge=20, end_ridge=39)
            if name == "wait_grain_fill":
                add("disease_followup_wait", self.system, "advance_time",
                    "Wait seven days before revisiting the treated soybean samples.", days=7)
                for first in (28, 32):
                    add(f"disease_followup_{first}", self.robot, "inspect_crop_health",
                        "Reinspect the same four-ridge soybean sample after treatment.",
                        farm_id="soybean_field", start_ridge=first, end_ridge=first + 3)
                add("disease_followup_charge", self.robot, "charge", "Recharge the shared ground robot.")
                args = {"days": 5, "hours": 16}
            if name == "grain_fill_rain_wait":
                add("drought_thermal", self.matrice, "fly_survey",
                    "Use thermal stress only as supporting evidence for local water stress.",
                    farm_id="maize_field", start_ridge=20, end_ridge=39)
                add("drought_irrigate", self.maize_irrigation, "irrigate",
                    "Apply the existing 20-mm reference dose only to maize ridges 20--39.",
                    start=20, end=39, hours=4.0)
                add("drought_surface_recheck", self.maize_sensor, "read_soil_sensors",
                    "Observe surface response; do not claim instant root-zone recovery.")
                reason = "Wait one day for infiltration before the maize follow-up."
            if name == "wait_dent":
                add("drought_second_wait", self.system, "advance_time",
                    "Use the source scenario's week-separated reassessment, not immediate repeat watering.",
                    days=5, hours=20)
                add("drought_second_weather", self.weather, "get_current_weather", "Check current shared weather.")
                add("drought_second_forecast", self.weather, "get_forecast", "Check effective rainfall before repeating irrigation.", days=4)
                add("drought_second_soil", self.maize_sensor, "read_soil_sensors", "Reassess the maize soil-water trend.")
                add("drought_second_state", self.maize, "get_ridge_range_state", "Use maize's actual reproductive stage.", start=20, end=39)
                add("drought_second_thermal", self.matrice, "fly_survey", "Thermal data supports the soil-based diagnosis.", farm_id="maize_field", start_ridge=20, end_ridge=39)
                add("drought_second_irrigate", self.maize_irrigation, "irrigate", "Repeat the inherited local 20-mm dose after reassessment.", start=20, end=39, hours=4.0)
                add("drought_second_surface", self.maize_sensor, "read_soil_sensors", "Read immediate surface response.")
                add("drought_second_infiltration", self.system, "advance_time", "Allow a day for infiltration.", days=1)
                add("drought_second_recheck", self.maize_sensor, "read_soil_sensors", "Recheck the maize soil after infiltration.")
                add("drought_second_crop_recheck", self.maize, "get_ridge_range_state", "Recheck maize crop condition.", start=20, end=39)
            add(name, app, method, reason, **args)
            if name == "silking_soybean_field_health":
                add("disease_confirm_32", self.robot, "inspect_crop_health",
                    "Extend soybean diagnosis to a second four-ridge sample before spraying.",
                    farm_id="soybean_field", start_ridge=32, end_ridge=35)
                add("disease_refuel", self.tractor, "refuel", "Refuel the shared tractor.", liters=100.0)
                add("disease_sprayer", self.tractor, "attach_implement", "Attach the inherited sprayer.", implement="sprayer")
                add("disease_load", self.tractor, "load_fungicide", "Load the source scenario's exact 76-L working-fluid dose.", liters=76.0)
                for first in (20, 30):
                    add(f"disease_treat_{first}", self.tractor, "apply_fungicide",
                        "Treat only confirmed soybean risk-zone ridges using the source dose.",
                        farm_id="soybean_field", start_ridge=first, end_ridge=first + 9, liters_per_ridge=3.8)
                add("disease_return", self.tractor, "return_supplies", "Return unused shared materials.")
                add("disease_detach", self.tractor, "detach_implement", "Detach the sprayer after local treatment.")
            if name == "grain_fill_maize_recheck":
                add("drought_crop_recheck", self.maize, "get_ridge_range_state",
                    "Check the treated maize stage and crop condition after infiltration.", start=20, end=39)
        return actions

    def validate(self, env=None) -> ScenarioValidationResult:
        """Reject malformed replay evidence without mutating the world."""
        try:
            return self._validate_results(env)
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError) as error:
            return ScenarioValidationResult(
                success=False,
                message=f"Malformed or incomplete validation data: {type(error).__name__}: {error}",
            )

    def _validate_results(self, env=None) -> ScenarioValidationResult:
        """Inspect existing results without advancing physics or consuming observations.

        Full-season checks follow the mixed-crop source; additional checks
        enforce the integrated diagnosis/treatment/follow-up contract.
        """
        failures = []
        totals = {}
        operations = self.tractor.get_state()["operation_log"]
        batches = list(self.warehouse.grain_batches.values())
        steps = list((env.workflow if env is not None else self.workflow).dag.values())
        normalized = []
        for step in steps:
            content = step.content
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except (ValueError, TypeError):
                    content = {"text": content}
            normalized.append(replace(step, content=content))
        steps = normalized
        for farm_id, farm, cultivar, spacing in (
            ("maize_field", self.maize, MAIZE_CULTIVAR, MAIZE_SPACING_CM),
            ("soybean_field", self.soybean, SOYBEAN_CULTIVAR, SOYBEAN_SPACING_CM),
        ):
            planted = [op for op in operations if op["operation"] == "plant_seeds" and op.get("farm_id") == farm_id]
            expected = set(range(NUM_RIDGES))
            if {rid for op in planted for rid in op["ridge_ids"]} != expected:
                failures.append(f"{farm_id}: planting coverage incomplete")
            if not {"level", "base_fertilize", "form_ridges"} <= set(farm.completed_prep_ops):
                failures.append(f"{farm_id}: field preparation incomplete")
            topdressing = [op for op in operations if op["operation"] == "apply_fertilizer"
                           and op.get("farm_id") == farm_id and op["fertilizer_used_kg"] > 0]
            if {rid for op in topdressing for rid in op["ridge_ids"]} != expected:
                failures.append(f"{farm_id}: seasonal topdressing coverage incomplete")
            if not all(r.harvested for r in farm._ridges):
                failures.append(f"{farm_id}: harvest coverage incomplete")
            own_batches = [batch for batch in batches if batch.origin_farm_id == farm_id]
            coverage = Counter(rid for batch in own_batches for rid in batch.ridge_ids)
            if coverage != Counter(range(NUM_RIDGES)):
                failures.append(f"{farm_id}: batch ridge coverage missing or duplicated")
            limit = min(self.warehouse.max_storage_moisture_pct, farm._postharvest_market.max_storage_moisture_pct)
            if any(batch.status != "stored" or batch.quantity_kg <= 0 or batch.crop_id != farm.crop_id
                   or batch.cultivar_ids != [cultivar] or batch.moisture_pct is None
                   or batch.moisture_pct > limit + 1e-9 for batch in own_batches):
                failures.append(f"{farm_id}: incorrect crop, provenance, storage or moisture")
            seed_used = self._initial_stock.seed_stock[cultivar] - self.warehouse.stock.seed_stock[cultivar]
            expected_seeds = farm.plants_per_ridge_from_spacing(spacing) * NUM_RIDGES
            if seed_used != expected_seeds or sum(op["seeds_used"] for op in planted) != expected_seeds:
                failures.append(f"{farm_id}: seed account mismatch")
            regime = farm._management_regime
            if regime.irrigation_used_mm_total > regime.irrigation_quota_mm_total + 1e-9:
                failures.append(f"{farm_id}: irrigation quota exceeded")
            if regime.fertilizer_used_kg > regime.fertilizer_quota_kg + 1e-9:
                failures.append(f"{farm_id}: fertilizer quota exceeded")
            observed = {
                ridge["growth_stage"] for step in steps
                if step.tool_name == f"{farm.name}__get_ridge_range_state" and isinstance(step.content, dict)
                for ridge in step.content.get("ridges", []) if "growth_stage" in ridge
            }
            if not observed & {"VE", "V3", "V4"} or not observed & {"R1", "R1_SILKING", "R3_MILK"}:
                failures.append(f"{farm_id}: emergence or reproductive observation missing")
            if not observed & set(farm.crop_definition.harvest_rules.stage_codes):
                failures.append(f"{farm_id}: maturity observation missing")
            totals[farm_id] = {
                "crop_id": farm.crop_id, "cultivar_id": cultivar,
                "area_m2": farm.field_geometry.planted_area_m2,
                "harvested_ridges": sum(r.harvested for r in farm._ridges),
                "seed_used": seed_used, "water_used_mm": regime.irrigation_used_mm_total,
                "stored_grain_kg": round(sum(batch.quantity_kg for batch in own_batches), 2),
                "market_moisture_pct": farm.crop_definition.market_moisture_pct,
                "observed_stages": sorted(observed),
            }
        if self.maize._management_regime.irrigation_used_mm_total <= 0:
            failures.append("maize_field: key-stage water management missing")
        if any(step.error_stage or (isinstance(step.content, dict)
                                   and ("error" in step.content or step.content.get("status") == "partial"))
               for step in steps):
            failures.append("workflow contains failed or partial tools")
        device = self.tractor.get_state()
        if device["grain_bin_kg"] != 0 or device["seed_hopper"] != 0:
            failures.append("shared machine retains unaccounted seed or grain")
        if self.warehouse.stock.fertilizer_kg < 0 or self.warehouse.stock.fuel_liters < 0:
            failures.append("negative shared supplies")
        if any(batch.origin_farm_id not in totals for batch in batches):
            failures.append("unknown grain origin")
        intervention_failures, intervention_metadata = validate_interventions(self, steps)
        failures.extend(intervention_failures)
        return ScenarioValidationResult(
            success=not failures, message="; ".join(failures) or "Both crop seasons and source-backed disease/water interventions completed.",
            metadata={"plot_labels": self.plot_labels, "interventions": intervention_metadata, "farms": totals, "grain_batches": len(batches),
                      "fertilizer_used_kg": self._initial_stock.fertilizer_kg - self.warehouse.stock.fertilizer_kg,
                      "model_scope": "simulation baseline; maize not field-calibrated"},
        )


def validate_interventions(scene, steps):
    """Check executed interventions without advancing any app.

    Source scenarios prescribe the doses and delays. The 0.6 confidence
    cutoff follows tests/test_wofost_wet_disease_v2.py; 7--9-day disease and
    24--48-hour water windows are explicit acceptance tolerances.
    """
    failures, metadata = [], {
        "contract": "source_doses_with_executed_evidence_v1",
        "acceptance_windows_days": {"prior_evidence_max_age": 2,
                                    "disease_followup": [7, 9],
                                    "water_followup": [1, 2],
                                    "irrigation_separation": [6, 8]},
    }
    target, sample, day = set(range(20, 40)), set(range(28, 36)), 86400.0
    soy, maize = scene.soybean.farm_id, scene.maize.farm_id
    tractor, robot, weather = scene.tractor.name, scene.robot.name, scene.weather.name

    def require(condition, message):
        if not condition:
            failures.append(message)

    def number(value):
        return type(value) in (int, float) and isfinite(value)

    def close(value, expected):
        return number(value) and isclose(value, expected, abs_tol=1e-6)

    records = []
    for index, step in enumerate(steps):
        content = step.content
        if (isinstance(content, dict) and content and not step.error_stage
                and "error" not in content
                and content.get("status") not in {"partial", "failed", "error"}
                and number(step.time_before) and number(step.time_after)
                and step.time_before <= step.time_after):
            records.append((index, step, content))

    def named(name):
        return [r for r in records if r[1].tool_name == name]

    def nearby(rows, anchor, low, high, before=False):
        return [r for r in rows if (r[0] < anchor[0] if before else r[0] > anchor[0])
                and low <= r[1].time_before <= r[1].time_after <= high]

    def ground(rows):
        result = {}
        for _, _, content in rows:
            if content.get("farm_id") != soy or content.get("uncovered_ridges"):
                continue
            covered = set(content.get("covered_ridges", []))
            for value in content.get("observations", {}).values():
                rid = value.get("ridge_id")
                if (rid in covered & sample and type(value.get("disease_present")) is bool
                        and number(value.get("disease_confidence"))):
                    result[rid] = value
        return result

    def hits(observations):
        return sorted(rid for rid, value in observations.items()
                      if value["disease_present"] and value["disease_confidence"] >= 0.6)

    sprays = named(f"{tractor}__apply_fungicide")
    spray_coverage = Counter(rid for _, _, c in sprays for rid in c.get("sprayed_ridges", []))
    require(spray_coverage == Counter(target), "soybean: fungicide target coverage missing, duplicated or excessive")
    for _, step, content in sprays:
        args, covered = step.tool_args or {}, content.get("sprayed_ridges", [])
        require(content.get("farm_id") == args.get("farm_id") == soy
                and set(covered) == set(range(args.get("start_ridge", -1), args.get("end_ridge", -2) + 1))
                and 0 < len(covered) <= 10 and close(args.get("liters_per_ridge"), 3.8)
                and close(content.get("fungicide_used_liters"), len(covered) * 3.8),
                "soybean: fungicide receipt has wrong farm, range or dose")
    liters = sum(c.get("fungicide_used_liters", 0) for _, _, c in sprays)
    require(close(liters, 76), "soybean: executed fungicide total must be 76 L")
    inspections = named(f"{robot}__inspect_crop_health")
    if sprays:
        first, last = sprays[0], sprays[-1]
        before = ground(nearby(inspections, first, first[1].time_before - 2 * day,
                               first[1].time_before, before=True))
        after = ground(nearby(inspections, last, last[1].time_after + 7 * day,
                              last[1].time_after + 9 * day))
        require(sample <= before.keys() and bool(hits(before)),
                "soybean: missing complete 28-35 diagnosis with a confident positive before treatment")
        require(sample <= after.keys(), "soybean: missing same-sample disease follow-up 7-9 days after treatment")
        metadata["disease"] = {"sample_ridges": sorted(sample), "confidence_cutoff": 0.6,
                               "positive_before": hits(before), "positive_after": hits(after)}

    operations = [op for op in scene.tractor._operation_log if op["operation"] == "apply_fungicide"]
    receipt_ops = Counter((c.get("farm_id"), tuple(c.get("sprayed_ridges", [])),
                           round(c.get("fungicide_used_liters", 0), 6)) for _, _, c in sprays)
    logged_ops = Counter((op.get("farm_id"), tuple(op["ridge_ids"]),
                          round(op["fungicide_used_liters"], 6)) for op in operations)
    require(receipt_ops == logged_ops, "soybean: fungicide workflow and tractor log disagree")
    require(close(scene._initial_stock.pesticide_liters - scene.warehouse.stock.pesticide_liters, 76),
            "shared warehouse: chemical account must show exactly 76 L used")
    require(scene.soybean._management_regime.fungicide_applications_used == 1
            and scene.maize._management_regime.fungicide_applications_used == 0,
            "fungicide application-day counters disagree with plot-specific treatment")

    water = [r for r in records if (r[1].tool_name or "").endswith("__irrigate")]
    require(len(water) == 2, "maize: exactly two executed irrigation rounds are required")
    soil = named(f"{scene.maize_sensor.name}__read_soil_sensors")
    crop = named(f"{scene.maize.name}__get_ridge_range_state")

    def soil_ok(record):
        content, coverage = record[2], set()
        for probe in content.get("soil_sensors", []):
            if number(probe.get("vwc")):
                coverage.update(range(probe.get("ridge_start", -1), probe.get("ridge_end", -2) + 1))
        return content.get("farm_id") == maize and target <= coverage

    def crop_ok(record):
        rows = {r.get("ridge_id"): r for r in record[2].get("ridges", [])
                if r.get("farm_id") == maize and r.get("crop_id") == "maize"}
        return target <= rows.keys() and all(str(rows[r].get("growth_stage", "")).startswith("R") for r in target)

    rounds, receipt_water = [], Counter()
    for ordinal, record in enumerate(water, 1):
        _, step, content = record
        args, start, end = step.tool_args or {}, step.time_before, step.time_after
        valid = (step.tool_name == f"{scene.maize_irrigation.name}__irrigate"
                 and content.get("status") == "irrigation_started" and content.get("farm_id") == maize
                 and Counter(content.get("irrigated_ridges", [])) == Counter(target)
                 and args.get("start") == 20 and args.get("end") == 39 and close(args.get("hours"), 4)
                 and close(content.get("duration_hours_per_ridge"), 4)
                 and close(content.get("estimated_water_mm_per_ridge"), 20)
                 and close(content.get("field_equivalent_irrigation_mm"), 6.25))
        require(valid, f"maize: irrigation round {ordinal} has wrong plot, target, dose or outcome")
        prior = lambda rows: nearby(rows, record, start - 2 * day, start, before=True)
        require(any(soil_ok(r) for r in prior(soil)), f"maize: round {ordinal} lacks recent prior soil evidence")
        require(any(crop_ok(r) for r in prior(crop)), f"maize: round {ordinal} lacks recent reproductive-stage evidence")
        require(any(number(r[2].get("rainfall_mm")) for r in prior(named(f"{weather}__get_current_weather"))),
                f"maize: round {ordinal} lacks recent current weather")
        require(any(r[2].get("forecast") and all(number(d.get("rainfall_mm")) for d in r[2]["forecast"])
                    for r in prior(named(f"{weather}__get_forecast"))), f"maize: round {ordinal} lacks recent rainfall forecast")
        ready = content.get("effect_ready_at")
        require(number(ready), f"maize: round {ordinal} lacks water effect time")
        lower = max(end + day, ready) if number(ready) else end + day
        following = lambda rows: nearby(rows, record, lower, end + 2 * day)
        require(any(soil_ok(r) for r in following(soil)), f"maize: round {ordinal} lacks its next-day soil recheck")
        require(any(crop_ok(r) for r in following(crop)), f"maize: round {ordinal} lacks its next-day crop recheck")
        for rid in content.get("irrigated_ridges", []):
            receipt_water[(rid, ready, content.get("duration_hours_per_ridge"),
                           content.get("estimated_water_mm_per_ridge"))] += 1
        rounds.append({"time_before": start, "time_after": end, "effect_ready_at": ready})
    if len(water) == 2:
        separation = water[1][1].time_before - water[0][1].time_before
        require(6 * day <= separation <= 8 * day, "maize: irrigation rounds must be approximately one week apart")
    logs = scene.maize_irrigation._irrigation_log
    logged_water = Counter((r["ridge_id"], r.get("effect_ready_at"), r["duration_hours"],
                            r.get("estimated_water_mm")) for r in logs)
    require(receipt_water == logged_water and not scene.soybean_irrigation._irrigation_log,
            "irrigation workflow and independent plot logs disagree")
    require(close(scene.maize._management_regime.irrigation_used_mm_total, 12.5)
            and close(scene.soybean._management_regime.irrigation_used_mm_total, 0),
            "water account must be maize 12.5 and soybean 0 full-field-equivalent mm")
    for payload in ("_seed_hopper", "_fertilizer_spreader_kg", "_pesticide_tank_l", "_fungicide_tank_l", "_grain_bin_kg"):
        require(close(getattr(scene.tractor, payload), 0), f"shared tractor: nonempty {payload.lstrip('_')}")
    metadata.update({"fungicide_liters": liters, "water_rounds": rounds,
                     "maize_field_equivalent_mm": scene.maize._management_regime.irrigation_used_mm_total})
    return failures, metadata
