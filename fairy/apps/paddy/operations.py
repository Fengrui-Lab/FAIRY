"""Finite paddy operations with explicit assets, batches and native inputs."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from fairy.apps.app import App
from fairy.apps.paddy.models import positive, GrainBatch
from fairy.apps.paddy.machinery import require_machine, consume_fuel
from fairy.apps.paddy.observations import require_plot
from fairy.tool_utils import app_tool, OperationType
from fairy.types import event_registered


class PaddyOpsApp(App):
    def __init__(self, world):
        super().__init__()
        self.world = world

    def _plot(self, plot_id):
        return require_plot(self.world, plot_id)

    def _channel_duration(self, channel, volume):
        seconds = max(1, math.ceil(volume / (channel.flow_m3_hour * (1 - channel.blockage_fraction)) * 3600))
        if (channel.open_hour, channel.close_hour) != (0, 24):
            within_day = self.world.sim_time % 86400
            if within_day < channel.open_hour * 3600 or within_day + seconds > channel.close_hour * 3600:
                raise ValueError(f"Channel {channel.channel_id} job must fit UTC {channel.open_hour}:00..{channel.close_hour}:00")
        return seconds

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def irrigate(self, plot_id: str, water_mm: float) -> dict:
        """Deliver water_mm through the supply canal. Quota includes conveyance losses; flow and opening hours constrain duration.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
            water_mm: Positive requested surface-water depth in mm.
        """
        p = self._plot(plot_id)
        amount = positive(water_mm, "water_mm")
        channel = self.world.channel("supply")
        if plot_id not in channel.connected_plots:
            raise ValueError("Plot has no supply connection")
        withdrawn = p.unit.volume_m3(amount) / channel.efficiency
        if withdrawn > channel.quota_m3 - channel.withdrawn_m3 + 1e-9:
            raise ValueError("Insufficient canal water quota")
        seconds = self._channel_duration(channel, withdrawn)
        delivered = 0.

        def transfer(dt):
            nonlocal delivered
            mm = amount * dt / seconds
            self.world.backends[plot_id].apply("water", amount_mm=mm)
            delivered += p.unit.volume_m3(mm)

        self.world.run_job(seconds, transfer)
        channel.withdrawn_m3 += withdrawn
        channel.delivered_m3 += delivered
        self.world.record("irrigate", plot_id=plot_id, water_mm=amount,
                          withdrawn_m3=withdrawn, delivered_m3=delivered, duration_s=seconds)
        return {"status": "ok", "delivered_mm": amount, "withdrawn_m3": withdrawn, "duration_s": seconds}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def drain(self, plot_id: str, water_mm: float) -> dict:
        """Drain up to water_mm of ponded surface water; never directly remove root-zone water.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
            water_mm: Positive requested surface-water depth in mm.
        """
        p = self._plot(plot_id)
        amount = positive(water_mm, "water_mm")
        channel = self.world.channel("drain")
        if plot_id not in channel.connected_plots:
            raise ValueError("Plot has no drainage connection")
        amount = min(amount, max(0., self.world.backends[plot_id].water.ledger()["surface_water_mm"]))
        if amount == 0:
            raise ValueError("No surface water to drain")
        seconds = self._channel_duration(channel, p.unit.volume_m3(amount))
        actual = 0.

        def transfer(dt):
            nonlocal actual
            actual += self.world.backends[plot_id].apply("water", amount_mm=amount * dt / seconds, drain=True)

        self.world.run_job(seconds, transfer)
        channel.discharged_m3 += p.unit.volume_m3(actual)
        self.world.record("drain", plot_id=plot_id, requested_mm=water_mm, actual_mm=actual, duration_s=seconds)
        return {"status": "ok", "drained_mm": actual, "duration_s": seconds}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def soak(self, plot_id: str, hours: int = 24) -> dict:
        """Wait 1..72 hours for a ponded, unpuddled plot to soak. Read sensors to verify effective wet time.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
            hours: Soaking duration in whole hours, from 1 to 72.
        """
        p = self._plot(plot_id)
        if p.planted or p.puddled:
            raise ValueError("Soaking is a pre-puddling operation")
        if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 72:
            raise ValueError("Soak duration must be 1..72 whole hours")
        if self.world.backends[plot_id].water.states.SS <= 0:
            raise ValueError("Irrigate before soaking")
        self.world.run_job(hours * 3600)
        self.world.record("soak", plot_id=plot_id, duration_s=hours * 3600)
        return {"status": "ok", "duration_s": hours * 3600}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def puddle_and_level(self, plot_id: str) -> dict:
        """Puddle/level using the tractor with puddler, after 24 wet hours with >=5 mm ponding and root VWC >=0.45.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
        """
        p = self._plot(plot_id)
        if p.planted or p.puddled:
            raise ValueError("Plot already puddled or planted")
        water = self.world.backends[plot_id].water.ledger()
        if p.soaked_hours < 24 or water["surface_water_mm"] < 5 or water["root_vwc"] < .45:
            raise ValueError("Puddling requires 24 wet hours, saturated topsoil and >=5 mm water")
        fuel = p.area_m2 * .004
        machine = require_machine(self.world, "tractor", fuel, "puddler")
        self.world.run_job(math.ceil(p.area_m2 / 1000 * 3600))
        self.world.backends[plot_id].apply(
            "puddle", sope_cm_day=p.soil.get("puddled_sope_cm_day", 1.),
            ksub_cm_day=p.soil.get("puddled_ksub_cm_day", .2))
        consume_fuel(self.world, machine, fuel)
        p.puddled = p.levelled = True
        self.world.record("puddle_and_level", plot_id=plot_id, fuel_liters=fuel)
        return {"status": "ok", "plot_id": plot_id, "puddled": True, "levelled": True}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def load_seedlings(self, batch_id: str, quantity: int) -> dict:
        """Transfer purchased seedlings from stock to the transplanter, subject to onboard capacity.

        Args:
            batch_id: Exact seedling-batch ID from inventory.
            quantity: Positive number of individual seedlings.
        """
        self.world.advance_physics_time()
        batch = self.world.field.seedlings
        if batch_id != batch.batch_id:
            raise ValueError("Unknown seedling batch")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("Seedling quantity must be a positive integer")
        if quantity > batch.quantity or quantity + batch.loaded > self.world.machine("transplanter").seedling_capacity:
            raise ValueError("Insufficient stock or transplanter capacity exceeded")
        self.world.run_job(600)
        batch.quantity -= quantity
        batch.loaded += quantity
        self.world.record("load_seedlings", batch_id=batch_id, quantity=quantity)
        return {"status": "ok", "loaded": batch.loaded, "inventory_remaining": batch.quantity}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def transplant(self, plot_id: str, batch_id: str, row_spacing_cm: float = 20.,
                   hill_spacing_cm: float = 20., seedlings_per_hill: int = 3,
                   area_m2: float | None = None) -> dict:
        """Transplant all remaining plot area or a specified work batch.

        Use 20 cm row and hill spacing with 3 seedlings per hill. Complete each
        plot's batches within one UTC calendar day. Partial work is recorded;
        the plot is marked fully transplanted when its remaining area is completed.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
            batch_id: Exact seedling-batch ID from inventory.
            row_spacing_cm: Row spacing in cm; supported value 20.
            hill_spacing_cm: Hill spacing in cm; supported value 20.
            seedlings_per_hill: Seedlings per hill; supported value 3.
            area_m2: Requested work area in square metres; None requests all remaining area, subject to the operation limit.
        """
        p = self._plot(plot_id)
        batch = self.world.field.seedlings
        if (row_spacing_cm, hill_spacing_cm, seedlings_per_hill) != (20., 20., 3):
            raise ValueError("Only the standard density profile is supported")
        if p.planted or not (p.puddled and p.levelled):
            raise ValueError("Transplanting requires a prepared, unplanted plot")
        if batch_id != batch.batch_id or batch.cultivar != "Rice_IR72":
            raise ValueError("Wrong seedling batch/cultivar")
        backend = self.world.backends[plot_id]
        water = backend.water.ledger()
        if water["surface_water_mm"] > 30 or water["root_vwc"] < .40:
            raise ValueError("Transplanting requires moist soil and 0..30 mm surface water")
        remaining = p.area_m2 - p.transplanted_area_m2
        area = remaining if area_m2 is None else positive(area_m2, "area_m2")
        if area > remaining + 1e-8:
            raise ValueError("Transplant area exceeds remaining area")
        day = backend.model.day.isoformat()
        seconds = math.ceil(area / 2000 * 3600)
        if (p.transplant_day is not None and p.transplant_day != day) or self.world.sim_time % 86400 + seconds >= 86400:
            raise ValueError("Finish partial transplant work in the same UTC day")
        count = math.ceil(area * 75.)
        if batch.loaded < count:
            raise ValueError("Load sufficient seedlings before transplanting")
        fuel = area * .002
        machine = require_machine(self.world, "transplanter", fuel)
        self.world.run_job(seconds)
        batch.loaded -= count
        consume_fuel(self.world, machine, fuel)
        p.transplant_day = day
        p.transplanted_area_m2 += area
        p.seedling_batch_id = batch_id
        p.seedlings_planted += count
        if p.transplanted_area_m2 >= p.area_m2 - 1e-8:
            backend.apply("transplant", day=day)
            p.planted = True
            p.transplant_timestamp = self.world.sim_time
        self.world.record("transplant", plot_id=plot_id, batch_id=batch_id, quantity=count, area_m2=area)
        return {"status": "ok", "seedlings_planted": count, "completed": p.planted,
                "transplanted_area_m2": p.transplanted_area_m2}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def harvest(self, plot_id: str, area_m2: float | None = None) -> dict:
        """Harvest mature rice in a finite work batch. Check combine capacity and unload between batches.

        Requires surface water <=0.1 mm, root VWC <=0.42, grain moisture
        14..28%, rainfall <=5 mm. Moisture outside 20..25% adds recovery loss.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
            area_m2: Requested work area in square metres; None requests all remaining area, subject to the operation limit.
        """
        p = self._plot(plot_id)
        b = self.world.backends[plot_id]
        water = b.water.ledger()
        if not b.maturity or p.harvested:
            raise ValueError("Harvest requires mature, unharvested rice")
        if water["surface_water_mm"] > .1 or water["root_vwc"] > .42:
            raise ValueError("Drain and allow soil to become trafficable before harvest")
        day = datetime.fromtimestamp(self.world.sim_time, timezone.utc).date()
        if not 14 <= p.grain_moisture_pct <= 28 or self.world.weather_for(day)["rain_mm"] > 5:
            raise ValueError("Harvest moisture/weather window is closed")
        remaining_area = p.area_m2 - p.harvested_area_m2
        area = remaining_area if area_m2 is None else positive(area_m2, "area_m2")
        if area > remaining_area + 1e-8:
            raise ValueError("Harvest area exceeds remaining standing crop")
        bio = p.unit.mass_kg(float(b.crop_values.get("TWSO") or 0))
        available = bio - p.harvested_dry_kg - p.harvest_loss_dry_kg - p.field_loss_dry_kg
        if available <= 0:
            raise ValueError("No grain available for harvest")
        fuel = area * .003
        machine = require_machine(self.world, "combine", fuel)
        loaded = sum(batch.wet_kg for batch in self.world.field.grain_batches if batch.location == "combine")
        # Conservative wet-mass capacity check before advancing time.
        if loaded + available * area / remaining_area / .72 > machine.grain_capacity_wet_kg + 1e-8:
            raise ValueError("Combine grain capacity exceeded; unload or select a smaller area_m2")
        self.world.run_job(math.ceil(area / 2000 * 3600))
        consume_fuel(self.world, machine, fuel)
        available = bio - p.harvested_dry_kg - p.harvest_loss_dry_kg - p.field_loss_dry_kg
        removed = max(0., available) * area / remaining_area
        loss_fraction = .03 + .01 * max(0., 20 - p.grain_moisture_pct) + .005 * max(0., p.grain_moisture_pct - 25)
        loss, grain = removed * loss_fraction, removed * (1 - loss_fraction)
        p.harvest_loss_dry_kg += loss
        p.harvested_dry_kg += grain
        p.harvested_area_m2 += area
        p.harvested = p.harvested_area_m2 >= p.area_m2 - 1e-8
        batch_id = f"grain_{len(self.world.field.grain_batches) + 1:04d}"
        self.world.field.grain_batches.append(GrainBatch(batch_id, plot_id, grain, p.grain_moisture_pct))
        self.world.sync_grain_totals()
        self.world.record("harvest", plot_id=plot_id, batch_id=batch_id, area_m2=area,
                          grain_dry_kg=grain, loss_dry_kg=loss)
        return {"status": "ok", "batch_id": batch_id, "wet_kg": self.world.batch(batch_id).wet_kg,
                "harvested_area_m2": p.harvested_area_m2, "completed": p.harvested}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def unload_grain(self, plot_id: str | None = None) -> dict:
        """Unload combine batches to the dryer reception area, optionally selecting their source plot.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview. None selects all applicable plots.
        """
        self.world.advance_physics_time()
        if plot_id:
            self._plot(plot_id)
        batches = [b for b in self.world.field.grain_batches if b.location == "combine" and (not plot_id or b.plot_id == plot_id)]
        if not batches:
            raise ValueError("No loaded grain to unload")
        self.world.run_job(900)
        for batch in batches:
            batch.location = "reception"
        self.world.sync_grain_totals()
        self.world.record("unload_grain", plot_id=plot_id, batch_ids=[b.batch_id for b in batches])
        return {"status": "ok", "batch_ids": [b.batch_id for b in batches]}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def dry_grain(self, batch_id: str, target_moisture_pct: float = 14.) -> dict:
        """Dry one reception batch to the reference 14% standard, consuming throughput time and electricity.

        Args:
            batch_id: Exact grain-batch ID from the grain listing.
            target_moisture_pct: Target grain moisture percentage; this dryer supports 14 only.
        """
        self.world.advance_physics_time()
        batch = self.world.batch(batch_id)
        if batch.location != "reception" or target_moisture_pct != 14.:
            raise ValueError("Drying requires a reception batch and the 14% reference target")
        wet = batch.wet_kg
        evaporated = max(0., wet - batch.dry_kg / .86)
        energy = evaporated * .06
        if energy > self.world.field.electricity_kwh:
            raise ValueError("Insufficient drying electricity")
        if evaporated > 0:
            self.world.run_job(max(1, math.ceil(wet / self.world.field.drying_capacity_wet_kg_day * 86400)))
            batch.moisture_pct = 14.
        self.world.field.electricity_kwh -= energy
        self.world.field.energy_used_kwh += energy
        self.world.record("dry_grain", plot_id=batch.plot_id, batch_id=batch_id,
                          evaporated_water_kg=evaporated, electricity_kwh=energy)
        return {"status": "ok", "batch_id": batch_id, "evaporated_water_kg": evaporated,
                "electricity_kwh": energy, "moisture_pct": batch.moisture_pct}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def store_grain(self, batch_id: str) -> dict:
        """Move a reception batch at <=14% moisture into warehouse capacity; no automatic drying occurs.

        Args:
            batch_id: Exact grain-batch ID from the grain listing.
        """
        self.world.advance_physics_time()
        batch = self.world.batch(batch_id)
        if batch.location != "reception" or batch.moisture_pct > 14.:
            raise ValueError("Storage requires a dry reception batch at <=14% moisture")
        stored = sum(b.wet_kg for b in self.world.field.grain_batches if b.location == "stored")
        if stored + batch.wet_kg > self.world.field.storage_capacity_kg + 1e-9:
            raise ValueError("Insufficient grain storage capacity")
        self.world.run_job(300)
        batch.location = "stored"
        self.world.sync_grain_totals()
        self.world.record("store_grain", plot_id=batch.plot_id, batch_id=batch_id, stored_kg=batch.wet_kg)
        return {"status": "ok", "stored_kg": batch.wet_kg, "stored_kg_at_14pct": batch.dry_kg / .86}

    def dry_and_store(self, plot_id: str) -> dict:
        """Python compatibility helper only; agent workflows use the two explicit tools."""
        self._plot(plot_id)
        batches = [b for b in self.world.field.grain_batches if b.plot_id == plot_id and b.location == "reception"]
        if not batches:
            raise ValueError("Unload grain before drying and storage")
        result = {"stored_kg_at_14pct": 0., "evaporated_water_kg": 0.}
        for batch in batches:
            result["evaporated_water_kg"] += self.dry_grain(batch.batch_id)["evaporated_water_kg"]
            result["stored_kg_at_14pct"] += self.store_grain(batch.batch_id)["stored_kg_at_14pct"]
        return result

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def load_fertilizer(self, kg: float, product_id: str = "urea") -> dict:
        """Load the declared 46%-N urea product from warehouse stock to the tractor spreader supply.

        Args:
            kg: Positive fertilizer product mass in kg to load.
            product_id: Fertilizer product ID from stock; supported value urea.
        """
        self.world.advance_physics_time()
        amount = positive(kg, "kg")
        machine = self.world.machine("tractor")
        if product_id != "urea" or amount > self.world.field.fertilizer_kg or amount + machine.fertilizer_kg > machine.fertilizer_capacity_kg:
            raise ValueError("Unknown product, insufficient fertilizer stock or loading capacity exceeded")
        self.world.run_job(600)
        self.world.field.fertilizer_kg -= amount
        machine.fertilizer_kg += amount
        self.world.record("load_fertilizer", product_id=product_id, kg=amount)
        return {"status": "ok", "loaded_kg": machine.fertilizer_kg}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply_fertilizer(self, plot_id: str, kg_per_ha: float, product_id: str = "urea") -> dict:
        """Apply loaded urea using the tractor and spreader.

        Dose is kg of fertilizer product per hectare, at most 300 kg/ha per
        application. Requires a puddled plot before maturity and surface water
        at or below 50 mm. The declared product contains 46% nitrogen; product
        mass and elemental nitrogen mass differ.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
            kg_per_ha: Positive fertilizer product dose in kg/ha, at most 300 per application.
            product_id: Fertilizer product ID from stock; supported value urea.
        """
        p = self._plot(plot_id)
        dose = positive(kg_per_ha, "kg_per_ha")
        b = self.world.backends[plot_id]
        amount = p.unit.mass_kg(dose)
        fuel = p.area_m2 * .001
        machine = require_machine(self.world, "tractor", fuel, "spreader")
        if product_id != "urea" or dose > 300 or not p.puddled or b.maturity or b.water.states.SS > 5:
            raise ValueError("Fertilizer requires a puddled pre-maturity plot, <=50 mm water and a valid urea dose")
        if machine.fertilizer_kg + 1e-9 < amount:
            raise ValueError("Load sufficient fertilizer first")
        self.world.run_job(math.ceil(p.area_m2 / 4000 * 3600))
        b.apply("fertilize", n_kg_ha=dose * .46, recovery=.7)
        machine.fertilizer_kg -= amount
        self.world.field.fertilizer_applied_kg += amount
        consume_fuel(self.world, machine, fuel)
        self.world.record("apply_fertilizer", plot_id=plot_id, product_id=product_id, product_kg=amount,
                          n_kg=amount * .46, recovered_n_kg=amount * .46 * .7)
        return {"status": "ok", "product_kg": amount, "n_kg": amount * .46, "recovered_n_kg": amount * .46 * .7}

    def _treat(self, plot_id, kind, dose):
        p = self._plot(plot_id)
        dose = positive(dose, "liters_per_ha")
        day = datetime.fromtimestamp(self.world.sim_time, timezone.utc).date()
        weather = self.world.weather_for(day)
        if not p.planted or self.world.backends[plot_id].maturity or dose > 2:
            raise ValueError("Treatment requires a growing crop and a scenario dose <=2 L/ha")
        if weather["rain_mm"] > 5 or weather["wind_ms"] > 6:
            raise ValueError("Spraying weather window is closed")
        fuel = p.area_m2 * .001
        machine = require_machine(self.world, "tractor", fuel, "sprayer")
        stock = "insecticide_liters" if kind == "pests" else "fungicide_liters"
        amount = p.unit.mass_kg(dose)
        if amount > getattr(self.world.field, stock):
            raise ValueError("Insufficient chemical stock")
        self.world.run_job(math.ceil(p.area_m2 / 4000 * 3600))
        setattr(self.world.field, stock, getattr(self.world.field, stock) - amount)
        self.world.field.chemicals_used[stock] += amount
        setattr(p, kind, getattr(p, kind) * (1 - .7 * min(1., dose)))
        consume_fuel(self.world, machine, fuel)
        action = "apply_pesticide" if kind == "pests" else "apply_fungicide"
        self.world.record(action, plot_id=plot_id, liters=amount)
        return {"status": "ok", "liters_used": amount}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply_pesticide(self, plot_id: str, liters_per_ha: float = 1.) -> dict:
        """Apply insecticide using the tractor and sprayer with sufficient chemical stock.

        Requires a growing crop before maturity, a positive dose no greater than
        2 L/ha, rain no greater than 5 mm and wind no greater than 6 m/s.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
            liters_per_ha: Positive working-fluid dose in L/ha, at most 2 per application.
        """
        return self._treat(plot_id, "pests", liters_per_ha)

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def apply_fungicide(self, plot_id: str, liters_per_ha: float = 1.) -> dict:
        """Apply fungicide using the tractor and sprayer with sufficient chemical stock.

        Requires a growing crop before maturity, a positive dose no greater than
        2 L/ha, rain no greater than 5 mm and wind no greater than 6 m/s.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
            liters_per_ha: Positive working-fluid dose in L/ha, at most 2 per application.
        """
        return self._treat(plot_id, "disease", liters_per_ha)

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def control_weeds(self, plot_id: str) -> dict:
        """Perform manual/mechanical rice weeding in <=30 mm ponding; consumes work time, not herbicide.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
        """
        p = self._plot(plot_id)
        if not p.planted or self.world.backends[plot_id].maturity or self.world.backends[plot_id].water.states.SS > 3:
            raise ValueError("Weeding requires growing rice and <=30 mm water")
        self.world.run_job(math.ceil(p.area_m2 / 500 * 3600))
        p.weeds *= .25
        self.world.record("control_weeds", plot_id=plot_id, method="manual_mechanical")
        return {"status": "ok", "plot_id": plot_id}

    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def replant_seedlings(self, plot_id: str, quantity: int) -> dict:
        """Gap-fill missing plants within 14 days of transplanting.

        Requires loaded seedlings, moist soil and surface water at or below
        30 mm. Recovery is reported after two days. Gap-filling does not restart
        the existing crop's development schedule.

        Args:
            plot_id: Exact hydraulic-plot ID from the field overview.
            quantity: Positive number of individual seedlings.
        """
        p = self._plot(plot_id)
        b = self.world.backends[plot_id]
        if not p.planted or p.transplant_timestamp is None or self.world.sim_time - p.transplant_timestamp > 14*86400:
            raise ValueError("Gap filling is restricted to the first 14 days after transplant")
        maximum = math.floor((1 - p.stand_fraction) * p.area_m2 * 75 + 1e-7)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 0 < quantity <= maximum or p.pending_stand_recovery:
            raise ValueError("Gap-fill quantity exceeds missing stand or recovery is already pending")
        if self.world.field.seedlings.loaded < quantity or b.water.states.SS > 3 or b.water.states.SM < .4:
            raise ValueError("Gap filling needs loaded seedlings, moist soil and <=30 mm water")
        fuel = p.area_m2 * .001
        machine = require_machine(self.world, "transplanter", fuel)
        self.world.run_job(1800)
        self.world.field.seedlings.loaded -= quantity
        p.seedlings_planted += quantity
        p.pending_stand_recovery = quantity / (p.area_m2 * 75)
        p.recovery_timestamp = self.world.sim_time + 2*86400
        consume_fuel(self.world, machine, fuel)
        self.world.record("replant_seedlings", plot_id=plot_id, quantity=quantity, recovery_timestamp=p.recovery_timestamp)
        return {"status": "ok", "quantity": quantity, "recovery_timestamp": p.recovery_timestamp}
