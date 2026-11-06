"""Continuous native WOFOST81 rotation; one soil object for the entire experiment.

Reuses FAIRY's deferred-rate runtime and wheat weather conversion. There is no
fallback crop-growth model. Harvest is a start-of-native-day boundary operation.
"""

from __future__ import annotations
from copy import deepcopy
from datetime import date, timedelta
from .winter_wheat_wofost import WinterWheatBackend
from .winter_wheat_inputs import json_safe, fingerprint, number, stage_from_native

CROP_VARS = (
    "DVS",
    "TSUM",
    "TSUME",
    "LAI",
    "TAGP",
    "TWSO",
    "TWLV",
    "TWST",
    "TWRT",
    "RD",
    "DOE",
    "DOA",
    "DOM",
    "VERN",
    "NuptakeTotal",
)
SOIL_VARS = (
    "SM",
    "NAVAIL",
    "NSOIL",
    "W",
    "WLOW",
    "WWLOW",
    "SS",
    "TOTIRR",
    "TSR",
    "PERCT",
    "LOSST",
    "EVST",
    "WTRAT",
)
VARS = CROP_VARS + SOIL_VARS


class SugarBeetBackend:
    _weather_container = WinterWheatBackend._weather_container

    def __init__(self, bundle):
        from fairy.physics.wofost_backend import _load_runtime
        from pcse.base import MultiCropDataProvider

        self.bundle, self.runtime = bundle, _load_runtime()
        r = self.runtime
        self.version = str(r["pcse"].__version__)
        self.parameters_by_cycle = bundle.load_parameters(r["yaml"])
        self.parameter_hash = fingerprint(self.parameters_by_cycle)
        mapping = {
            (c.native_name, c.cultivar): self.parameters_by_cycle[c.cycle_id]
            for c in bundle.cycles
        }

        class CropProvider(MultiCropDataProvider):
            def set_active_crop(self, crop_name, variety_name):
                self.clear()
                self.update(deepcopy(mapping[(crop_name, variety_name)]))

        crops = CropProvider()
        first = bundle.cycles[0]
        crops.set_active_crop(first.native_name, first.cultivar)
        provider = r["ParameterProvider"](
            cropdata=crops,
            soildata=deepcopy(bundle.manifest["native_soil_parameters"]),
            sitedata=r["SiteProvider"](**bundle.manifest["native_site_parameters"]),
        )
        self.weather_provider = r["WeatherDataProvider"]()
        for day in sorted(bundle.weather.rows):
            self.weather_provider._store_WeatherDataContainer(
                self._weather_container(day), day
            )
        self.model = r["Model"](
            provider,
            self.weather_provider,
            [
                {
                    bundle.season.start: {
                        "CropCalendar": None,
                        "TimedEvents": None,
                        "StateEvents": None,
                    }
                },
                {bundle.season.deadline + timedelta(days=366): None},
            ],
            output_vars=list(VARS),
            summary_vars=list(VARS),
        )
        self.next_day = bundle.season.start
        if self.model.day != self.next_day:
            raise RuntimeError("Native/model calendar initialization mismatch")
        self.cycle_index = 0
        self.sown = False
        self.maturity = None
        self.pending = []
        self.receipts = {}
        self.events = []
        self.harvests = {}
        self.failed = None
        self.n_by_cycle = {c.cycle_id: 0.0 for c in bundle.cycles}
        self.last_irrigation = None
        self.sowing_day = None
        self.efficiency = number(
            bundle.manifest["management"]["irrigation_efficiency"],
            "irrigation efficiency",
            minimum=0.001,
            maximum=1,
        )
        self.n_recovery = number(
            bundle.manifest["management"]["nitrogen_recovery_fraction"],
            "N recovery",
            minimum=0.001,
            maximum=1,
        )
        self.values = self._read()
        self._soil_object_id = id(self.model.soil)
        self.rotation_audit = []

    @property
    def cycle(self):
        return self.bundle.cycles[self.cycle_index]

    def _read(self):
        return json_safe({k: self.model.get_variable(k) for k in VARS})

    def _healthy(self):
        if self.failed:
            raise RuntimeError(f"Native engine invalid after {self.failed}")
        if id(self.model.soil) != self._soil_object_id:
            raise RuntimeError("Rotation soil was replaced")
        if self.model.day != self.next_day:
            raise RuntimeError("Native and FAIRY calendars diverged")

    def preflight(self, kind, amount=0):
        self._healthy()
        c, day = self.cycle, self.next_day
        amount = number(amount, "amount", minimum=0)
        if kind not in {"sow", "irrigate", "fertilize"}:
            raise ValueError("Unsupported crop input")
        if c.cycle_id in self.harvests:
            raise ValueError("Crop already harvested; explicitly begin the next cycle")
        if kind == "sow":
            c.check_sowing(day)
            if amount or self.sown or any(a["kind"] == "sow" for a in self.pending):
                raise ValueError("Invalid or duplicate sowing")
        elif kind == "fertilize":
            c.check_nitrogen(day, self.n_by_cycle[c.cycle_id], amount)
            if self.maturity is not None:
                raise ValueError("Do not fertilize mature wheat")
        else:
            if not self.sown and not any(a["kind"] == "sow" for a in self.pending):
                raise ValueError("Irrigation requires a planted crop")
            if amount <= 0 or self.maturity is not None:
                raise ValueError("Positive irrigation and a growing crop required")
            if day > c.harvest_close - timedelta(days=c.irrigation_withholding_days):
                raise ValueError(
                    "Too late to irrigate and respect the last legal harvest date"
                )
        return amount

    def queue(self, operation_id, kind, amount=0):
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("Operation ID required")
        amount = number(amount, "amount", minimum=0)
        if operation_id in self.receipts:
            prev = self.receipts[operation_id]
            if (prev["kind"], prev["amount"]) != (kind, amount):
                raise ValueError("Operation ID reused with different content")
            return deepcopy(prev)
        self.preflight(kind, amount)
        item = dict(
            id=operation_id,
            kind=kind,
            amount=amount,
            day=self.next_day.isoformat(),
            cycle_id=self.cycle.cycle_id,
        )
        if kind == "fertilize":
            self.n_by_cycle[self.cycle.cycle_id] += amount
        if kind == "irrigate":
            self.last_irrigation = self.next_day
        self.pending.append(item)
        self.receipts[operation_id] = item
        self.events.append(dict(type="queue", **item))
        return deepcopy(item)

    def _delete_native_crop(self):
        if self.model.crop is not None:
            self.model._send_signal(
                signal=self.runtime["signals"].crop_finish,
                day=self.next_day,
                finish_type="harvest",
                crop_delete=True,
            )
            # No intervening growth integration or synthetic water/N reset.
            self.model._finish_cropsimulation(self.next_day)
        if self.model.crop is not None:
            raise RuntimeError("Native crop deletion failed")

    def advance_day(self):
        self._healthy()
        day = self.next_day
        if day >= self.bundle.season.deadline:
            raise ValueError("Experiment deadline reached")
        self.bundle.weather.require(day, day + timedelta(days=1))
        actions = deepcopy(self.pending)
        try:
            if self.maturity is not None and self.cycle.crop == "winter_wheat":
                self._delete_native_crop()
            self.model.drv = self.model._get_driving_variables(day)
            if any(a["kind"] == "sow" for a in actions):
                c = self.cycle
                self.model._send_signal(
                    signal=self.runtime["signals"].crop_start,
                    day=day,
                    crop_name=c.native_name,
                    variety_name=c.cultivar,
                    crop_start_type="sowing",
                    crop_end_type="maturity" if c.crop == "winter_wheat" else "harvest",
                )
                self.sown = True
                self.sowing_day = day
            water = sum(a["amount"] for a in actions if a["kind"] == "irrigate")
            nitrogen = sum(a["amount"] for a in actions if a["kind"] == "fertilize")
            if water:
                self.model._send_signal(
                    signal=self.runtime["signals"].irrigate,
                    amount=water / 10,
                    efficiency=self.efficiency,
                )
            if nitrogen:
                self.model._send_signal(
                    signal=self.runtime["signals"].apply_n,
                    N_amount=nitrogen,
                    N_recovery=self.n_recovery,
                )
            self.model.calculate_current_day()
            self.model.run(days=1)
            if self.model.day != day + timedelta(days=1):
                raise RuntimeError(
                    "Native model ended or stepped by the wrong interval"
                )
            values = self._read()
            if (
                self.cycle.crop == "winter_wheat"
                and self.maturity is None
                and values.get("DOM")
            ):
                self.maturity = deepcopy(values)
            if self.sown and self.model.crop is None and self.maturity is None:
                raise RuntimeError(
                    "Native crop disappeared without a permitted harvest/maturity"
                )
            if self.maturity:
                values.update({k: self.maturity.get(k) for k in CROP_VARS})
            if self.cycle.cycle_id in self.harvests:
                values.update({k: None for k in CROP_VARS})
            self.values = values
            self.next_day += timedelta(days=1)
            self.pending.clear()
            self.events.append(dict(type="advance", day=day.isoformat()))
        except Exception as exc:
            self.failed = f"{type(exc).__name__}: {exc}"
            raise
        return self.snapshot()

    def harvest_preflight(self):
        self._healthy()
        if not self.sown or self.cycle.cycle_id in self.harvests:
            raise ValueError("No unharvested crop")
        if self.pending:
            raise ValueError("Settle today's inputs before harvesting")
        self.cycle.check_harvest(self.next_day, self.last_irrigation)
        if self.cycle.crop == "winter_wheat" and self.maturity is None:
            raise ValueError("Wheat must reach native maturity")
        if not self.values.get("DOE") or float(self.values.get("TWSO") or 0) <= 0:
            raise ValueError("No positive native storage-organ dry matter")
        return deepcopy(self.values)

    def harvest_now(self, operation_id):
        if operation_id in self.receipts:
            old = self.receipts[operation_id]
            if old["kind"] != "harvest":
                raise ValueError("Operation ID conflict")
            return deepcopy(self.harvests[old["cycle_id"]])
        if not operation_id:
            raise ValueError("Harvest ID required")
        values = self.harvest_preflight()
        try:
            self._delete_native_crop()
        except Exception as exc:
            self.failed = f"harvest: {exc}"
            raise
        result = dict(
            cycle_id=self.cycle.cycle_id,
            crop=self.cycle.crop,
            day=self.next_day.isoformat(),
            native=values,
            last_irrigation=json_safe(self.last_irrigation),
        )
        self.harvests[self.cycle.cycle_id] = result
        self.receipts[operation_id] = dict(
            kind="harvest", cycle_id=self.cycle.cycle_id, amount=0
        )
        self.events.append(
            dict(type="harvest", id=operation_id, day=self.next_day.isoformat())
        )
        self.sown = False
        self.values = self._read()
        return deepcopy(result)

    def begin_next_cycle(self):
        self._healthy()
        if (
            self.cycle.cycle_id not in self.harvests
            or self.pending
            or self.model.crop is not None
        ):
            raise ValueError("Previous crop must be harvested and all inputs settled")
        if self.cycle_index + 1 >= len(self.bundle.cycles):
            raise ValueError("No remaining crop cycle")
        upcoming = self.bundle.cycles[self.cycle_index + 1]
        if not upcoming.prepare_open <= self.next_day <= upcoming.sowing_close:
            raise ValueError("Advance the same soil through the fallow period first")
        before = {k: self.model.get_variable(k) for k in SOIL_VARS}
        self.cycle_index += 1
        self.sown = False
        self.maturity = None
        self.sowing_day = None
        self.last_irrigation = None
        # The MultiCropDataProvider is switched by native crop_start, not here.
        after = {k: self.model.get_variable(k) for k in SOIL_VARS}
        if before != after:
            raise RuntimeError("Cycle switch changed native soil state")
        self.rotation_audit.append(
            dict(
                day=self.next_day.isoformat(),
                before=json_safe(before),
                after=json_safe(after),
            )
        )
        self.events.append(dict(type="next_cycle", day=self.next_day.isoformat()))
        self.values = self._read()

    def snapshot(self):
        v = self.values
        if self.cycle.cycle_id in self.harvests or not self.sown:
            stage = "BARE"
        elif self.cycle.crop == "winter_wheat":
            stage = stage_from_native(v, sown=self.sown)
        elif not v.get("DOE"):
            stage = "SOWN_NOT_EMERGED"
        elif float(v.get("TWSO") or 0) > 0:
            stage = (
                "ROOT_BULKING"  # operational label, not a BBCH or flowering prediction
            )
        else:
            stage = "CANOPY_EXPANSION"
        return dict(
            day=self.next_day.isoformat(),
            cycle_id=self.cycle.cycle_id,
            crop=self.cycle.crop,
            stage=stage,
            native=deepcopy(v),
            failed=self.failed,
        )

    def export_state(self):
        return dict(
            schema="fairy.sugarbeet.native.v1",
            input_fingerprint=self.bundle.identity,
            pcse_version=self.version,
            parameter_hash=self.parameter_hash,
            events=deepcopy(self.events),
            snapshot=self.snapshot(),
            harvests=deepcopy(self.harvests),
        )

    @classmethod
    def restore(cls, bundle, state):
        b = cls(bundle)
        if (
            state.get("schema") != "fairy.sugarbeet.native.v1"
            or state["input_fingerprint"] != bundle.identity
            or state["pcse_version"] != b.version
            or state["parameter_hash"] != b.parameter_hash
        ):
            raise ValueError("Native checkpoint version/input mismatch")
        for e in state["events"]:
            if date.fromisoformat(e["day"]) != b.next_day:
                raise ValueError("Replay calendar mismatch")
            if e["type"] == "queue":
                b.queue(e["id"], e["kind"], e["amount"])
            elif e["type"] == "advance":
                b.advance_day()
            elif e["type"] == "harvest":
                b.harvest_now(e["id"])
            elif e["type"] == "next_cycle":
                b.begin_next_cycle()
            else:
                raise ValueError("Unknown native replay operation")
        if fingerprint(b.export_state()) != fingerprint(state):
            raise ValueError("Native checkpoint replay failed exact verification")
        return b

    @property
    def journal(self):
        # Wheat's read-only compatibility view needs only the current sowing date.
        return (
            [dict(day=self.sowing_day.isoformat(), actions=[dict(kind="sow")])]
            if self.sowing_day
            else []
        )
