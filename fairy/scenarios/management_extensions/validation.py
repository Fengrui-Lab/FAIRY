"""Outcome and evidence checks; no oracle authoring or management dispatch."""

from fairy.scenarios.validation_result import ScenarioValidationResult
from .runtime import crop_options, SEEDS
from .evaluation.oracle_comparison import compare_to_oracle
from collections import Counter


class ExtensionValidation:
    def validate(self, env=None):
        farm, s = self.farm, self.farm.episode
        options = crop_options(farm)
        ridges = range(farm.num_ridges)
        failures = []
        steps = list((env.workflow if env is not None else self.workflow).dag.values())
        if not steps:
            failures.append("Empty workflow")
        seen = set()
        for step in steps:
            name = step.tool_name or ""
            if (
                step.error_stage
                or isinstance(step.content, dict)
                and "error" in step.content
            ):
                failures.append("Failed tool: " + name)
            if (
                name == "SeasonPlanning__select_crop"
                and not {
                    "SeasonPlanning__get_season_context",
                    "SeasonPlanning__get_crop_options",
                }
                <= seen
            ):
                failures.append("Crop choice lacks prior history/options observation")
            if (
                name == "SeedMarket__purchase_seed"
                and not {"SeedMarket__get_budget", "SeedMarket__list_offers"} <= seen
            ):
                failures.append("Purchase lacks prior budget/quote observation")
            if (
                name == "Tractor__plant_seeds"
                and not {
                    "Field__get_crop_capabilities",
                    "Warehouse__get_inventory",
                    "WeatherApp__get_current_weather",
                    "WeatherApp__get_forecast",
                    "Sensor__read_soil_sensors",
                    "Tractor__get_status",
                }
                <= seen
            ):
                failures.append(
                    "Planting lacks field/weather/soil/inventory/equipment preflight"
                )
            seen.add(name)
        if self.farm_environment.time_manager.time() > self.start_time + 213 * 86400:
            failures.append("November 30 full-season deadline exceeded")
        planting = [
            op
            for op in self.tractor._operation_log
            if op.get("operation") == "plant_seeds" and op.get("farm_id") == "field"
        ]
        coverage = Counter(rid for op in planting for rid in op["ridge_ids"])
        mature = (
            farm._physics is not None
            and farm.physics.crop_backend is not None
            and all(farm.is_ridge_mature(i) for i in ridges)
        )
        emerged_or_completed = farm._physics is not None and (
            all(p.emerged for p in farm.physics.phenology.states.values()) or mature
        )
        established = (
            bool(s.selection) and coverage == Counter(ridges) and emerged_or_completed
        )
        if not established:
            failures.append("Full-area native crop establishment incomplete")
        rotation_ok = None
        minimum = regret = None
        if self.rotation:
            crop = (s.selection or {}).get("crop_id")
            rotation_ok = crop in options and (
                s.soil_report["scn_eggs_per_100cc"] < 10000 or crop == "maize"
            )
            if not rotation_ok:
                failures.append("SCN rotation rule violated")
        else:
            crop = self.expected_crop
            minimum = min(
                o["seed_minor"] - o["discount_minor"] + o["delivery_minor"]
                for o in self.market.offers.values()
            )
            regret = s.spent - minimum
            if len(s.orders) != 1 or regret != 0 or s.remaining < 0:
                failures.append("Procurement cost/budget target not met")
        if crop in options:
            opt = options[crop]
            receipts = sum(
                o["quantity"]
                for o in s.orders.values()
                if o["seed_type"] == SEEDS[crop]
            )
            used = (
                self._initial_stock[SEEDS[crop]]
                + receipts
                - self.warehouse.stock.seed_stock[SEEDS[crop]]
                - self.tractor._seed_hopper
            )
            if (
                used != opt["required_seeds"]
                or sum(op["seeds_used"] for op in planting) != opt["required_seeds"]
            ):
                failures.append("Seed identity or material balance incorrect")
            if any(
                op["seeds_per_ridge"] != opt["required_seeds"] // farm.num_ridges
                or abs(op["seed_spacing_cm"] - opt["spacing_cm"]) > 1e-6
                or abs(op["depth_cm"] - opt["depth_cm"]) > 1e-6
                for op in planting
            ):
                failures.append("Planting density incorrect")
        stored = sum(
            b.quantity_kg
            for b in self.warehouse.grain_batches.values()
            if b.status == "stored"
        )
        batches = list(self.warehouse.grain_batches.values())
        mature = (
            farm._physics is not None
            and farm.physics.crop_backend is not None
            and all(farm.is_ridge_mature(i) for i in ridges)
        )
        if not mature or not all(r.harvested for r in farm._ridges) or stored <= 0:
            failures.append("Native maturity, full-field harvest and storage required")
        if Counter(rid for b in batches for rid in b.ridge_ids) != Counter(
            ridges
        ) or any(
            b.status != "stored"
            or b.origin_farm_id != "field"
            or b.crop_id != farm.crop_id
            or b.cultivar_ids != [SEEDS.get(crop)]
            or b.moisture_pct is None
            or b.moisture_pct > farm._postharvest_market.max_storage_moisture_pct
            for b in batches
        ):
            failures.append("Incomplete/unsafe grain provenance")
        if any(len(op["ridge_ids"]) > 4 for op in planting):
            failures.append("Planting pass exceeds four-ridge capacity")
        regime = farm._management_regime
        if (
            regime.irrigation_quota_mm_total is not None
            and regime.irrigation_used_mm_total
            > regime.irrigation_quota_mm_total + 1e-8
        ) or (
            regime.fertilizer_quota_kg is not None
            and regime.fertilizer_used_kg > regime.fertilizer_quota_kg + 1e-8
        ):
            failures.append("Water or fertilizer quota exceeded")
        if (
            abs(
                self._initial_fertilizer
                - self.warehouse.stock.fertilizer_kg
                - self.tractor._fertilizer_spreader_kg
                - regime.fertilizer_used_kg
            )
            > 1e-7
        ):
            failures.append("Fertilizer conservation failed")
        if (
            min(
                self.warehouse.stock.fuel_liters,
                self.warehouse.stock.fertilizer_kg,
                self.tractor._fuel_tank_l,
            )
            < -1e-8
        ):
            failures.append("Negative shared resources")
        if (
            self.tractor._grain_bin_kg > 1e-8
            or self.tractor._seed_hopper
            or self.tractor._fertilizer_spreader_kg > 1e-8
        ):
            failures.append("Unsettled equipment payload")
        production_cost = self.production_cost_minor()
        if production_cost > self.production_budget_minor:
            failures.append("Whole-season production budget exceeded")
        target = 0.99 * self.best_tested_yield_kg
        if stored + 1e-8 < target:
            failures.append("Stored yield below 99% of best tested candidate")
        if production_cost > self.oracle_cost_minor:
            failures.append("Total modeled production cost exceeds selected reference")
        accounts = self.production_accounts()
        selected = getattr(self, "ORACLE_REFERENCE", {}).get("selected")
        if selected:
            if selected.get("prices") != accounts["prices"]:
                failures.append(
                    "Reference economic prices do not match the current scenario"
                )
            else:
                compare_to_oracle(accounts, selected)
        return ScenarioValidationResult(
            success=not failures,
            message="; ".join(failures) or "Extension episode completed",
            metadata={
                **accounts,
                "rotation_rule_satisfied": rotation_ok,
                "crop_establishment_completed": bool(established),
                "purchase_cost_minor": s.spent,
                "budget_remaining_minor": s.remaining,
                "minimum_feasible_cost_minor": minimum,
                "cost_regret_minor": regret,
                "scn_population_simulated": False,
                "final_yield_evaluated": True,
                "stored_grain_kg": stored,
                "area_m2": farm.field_area_m2,
                "area_ha": farm.field_area_m2 / 10000,
                "yield_kg_ha": stored / (farm.field_area_m2 / 10000),
                "production_cost_minor": production_cost,
                "water_used_mm": regime.irrigation_used_mm_total,
                "water_used_m3": regime.irrigation_used_mm_total
                * farm.field_area_m2
                / 1000,
                "fertilizer_product_kg": regime.fertilizer_used_kg,
                "stored_batches": len(batches),
                "planting_passes": len(planting),
                "production_budget_minor": self.production_budget_minor,
                "production_budget_remaining_minor": self.production_budget_minor
                - production_cost,
                "best_tested_yield_kg": self.best_tested_yield_kg,
                "yield_target_kg": target,
                "oracle_cost_minor": self.oracle_cost_minor,
                "grain_kg_per_usd": (
                    stored / (production_cost / 100) if production_cost else None
                ),
                "yield_loss_pct": (
                    100 * (1 - stored / selected["stored_grain_kg"])
                    if selected and selected.get("stored_grain_kg")
                    else None
                ),
            },
        )
