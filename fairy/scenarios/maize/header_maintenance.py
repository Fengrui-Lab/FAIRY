"""Candidate-only header maintenance; the native recovery engine owns losses.

The fault quality and operation durations are frozen engineering assumptions,
not calibrated combine specifications. Existing TractorApp tools are unchanged.
"""
from __future__ import annotations

from copy import deepcopy
from math import isclose, isfinite
from typing import Any
import uuid

from fairy.apps.farm_world.farm_action_record import FarmActionRecord
from fairy.apps.farm_world.tractor_app import TractorApp
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered
from fairy.utils.type_utils import type_check


HEADER_SCHEMA_VERSION = 1
HEADER_COMPONENT = "header_ear_retention"
HEADER_CONDITIONS = frozenset({"serviceable", "maintenance_required"})
HEADER_QUALITY = {"serviceable": 0.95, "maintenance_required": 0.85}
INSPECTION_DURATION_SECONDS = 600
SERVICE_DURATION_SECONDS = 3600


class HeaderMaintenanceTractorApp(TractorApp):
    """One frozen header condition, synchronous inspection and service tools."""

    def __init__(self, farm_world_app, weather_app, name="TractorApp", *,
                 equipment=None, initial_condition="maintenance_required"):
        self._validate_condition(initial_condition)
        if name != "TractorApp":
            raise ValueError("H01 retains the TractorApp public tool prefix")
        super().__init__(farm_world_app, weather_app, name=name, equipment=equipment)
        self._h01_initial_condition = initial_condition
        self._reset_header_state()

    @staticmethod
    def _validate_condition(condition):
        if not isinstance(condition, str) or condition not in HEADER_CONDITIONS:
            raise ValueError("Unknown H01 header condition")

    def _reset_header_state(self):
        self._header_condition = self._h01_initial_condition
        self._last_inspection_at = None
        self._last_service_at = None
        self._maintenance_events = []
        self._harvest_batches = []
        self._header_operation_active = False
        self._h01_pass = None

    @property
    def harvest_batches(self):
        """Audit copy; never an Agent observation or a mutable state handle."""
        return deepcopy(self._harvest_batches)

    @property
    def maintenance_events(self):
        return deepcopy(self._maintenance_events)

    def get_state(self) -> dict[str, Any]:
        if self._header_operation_active:
            raise ValueError("H01 only snapshots completed synchronous operations")
        state = super().get_state()
        state["h01_header"] = {
            "schema_version": HEADER_SCHEMA_VERSION,
            "initial_condition": self._h01_initial_condition,
            "condition": self._header_condition,
            "last_inspection_at": self._last_inspection_at,
            "last_service_at": self._last_service_at,
            "maintenance_events": self.maintenance_events,
            "harvest_batches": self.harvest_batches,
        }
        return state

    def load_state(self, state_dict: dict[str, Any]) -> None:
        if self._header_operation_active:
            raise ValueError("Cannot restore H01 during an operation")
        header = state_dict.get("h01_header")
        if not isinstance(header, dict) or header.get("schema_version") != HEADER_SCHEMA_VERSION:
            raise ValueError("H01 device state requires its versioned header state")
        self._validate_condition(header.get("condition"))
        self._validate_condition(header.get("initial_condition"))
        for key in ("last_inspection_at", "last_service_at"):
            value = header.get(key)
            if value is not None and (isinstance(value, bool)
                    or not isinstance(value, (int, float)) or not isfinite(value)):
                raise ValueError(f"Invalid H01 {key}")
        for key in ("maintenance_events", "harvest_batches"):
            if not isinstance(header.get(key), list):
                raise ValueError(f"H01 state requires {key}")
        super().load_state(state_dict)
        self._h01_initial_condition = header["initial_condition"]
        self._header_condition = header["condition"]
        self._last_inspection_at = header.get("last_inspection_at")
        self._last_service_at = header.get("last_service_at")
        self._maintenance_events = deepcopy(header["maintenance_events"])
        self._harvest_batches = deepcopy(header["harvest_batches"])
        self._h01_pass = None

    def reset(self) -> None:
        super().reset()
        self._reset_header_state()

    def _header_precondition(self):
        if self._header_operation_active:
            return {"error": "Header operations require a completed synchronous operation boundary"}
        if "harvester" not in self._tractor_available_implements():
            return {"error": "This device does not own a harvester header"}
        if not self._farm_world_app.is_native_maize:
            return {"error": "H01 header maintenance requires the native maize candidate"}
        return None

    def _record_maintenance(self, operation, result):
        event = deepcopy(result)
        event["operation"] = operation
        event["operation_id"] = "h01_" + uuid.uuid4().hex[:12]
        self._maintenance_events.append(event)
        self._farm_world_app.record_action(FarmActionRecord(
            action_id=event["operation_id"], timestamp=float(self.time_manager.time()),
            actor_app=self.name, action_type=operation, ridge_ids=[],
            parameters={"component": HEADER_COMPONENT},
            direct_effect_summary=deepcopy(result),
            status="failed" if result["status"].endswith("failed") else "ok",
        ))
        self.is_state_modified = True

    def _header_operation(self, *, service):
        error = self._header_precondition()
        if error:
            return error
        self._bind_farm_context()
        before = self._header_condition
        started = float(self.time_manager.time())
        operation = "service_header" if service else "inspect_header"
        if service and before == "serviceable":
            result = dict(status="already_serviceable", component=HEADER_COMPONENT,
                          before_condition=before, condition=before, started_at=started,
                          service_completed_at=started, duration_seconds=0)
            self._record_maintenance(operation, result)
            return result
        duration = SERVICE_DURATION_SECONDS if service else INSPECTION_DURATION_SECONDS
        self._header_operation_active = True
        try:
            # A legacy single-farm clock jump alone does not evolve physics.
            # The environment path also accepts these idempotent syncs.
            self._farm_world_app.advance_physics_time()
            self._farm_context.advance_time(duration)
            self._farm_world_app.advance_physics_time()
            finished = float(self.time_manager.time())
            if service:
                self._header_condition = "serviceable"
                self._last_service_at = finished
            else:
                self._last_inspection_at = finished
            result = dict(status="service_completed" if service else "inspection_completed",
                          component=HEADER_COMPONENT, condition=self._header_condition,
                          started_at=started, duration_seconds=duration)
            result["service_completed_at" if service else "inspection_completed_at"] = finished
            if service:
                result["before_condition"] = before
            self._record_maintenance(operation, result)
            return result
        except Exception as exc:
            # Preserve elapsed time and the unrepaired condition on an error.
            self._record_maintenance(operation, dict(
                status="service_failed" if service else "inspection_failed",
                component=HEADER_COMPONENT, before_condition=before,
                condition=self._header_condition, started_at=started,
                stopped_at=float(self.time_manager.time()),
                duration_seconds=float(self.time_manager.time()) - started,
                exception_type=type(exc).__name__,
            ))
            raise
        finally:
            self._header_operation_active = False

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def inspect_header(self) -> dict[str, Any]:
        """Inspect the ear-retention component in 600 simulated seconds.

        Returns its observed condition at completion. Inspection does not repair
        the header or harvest any crop. Only synchronous operation boundaries
        are supported; no engine-stop or mechanical safety sensor is simulated.
        A maintenance_required condition is an ordinary finding, not a warning.
        """
        return self._header_operation(service=False)

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def service_header(self) -> dict[str, Any]:
        """Service the ear-retention component in 3600 simulated seconds.

        Prior inspection is optional. A serviceable component returns
        already_serviceable with zero duration and no additional benefit.
        Service affects only subsequent harvest passes; existing grain is never
        recomputed. Work is synchronous and weather advances normally.
        """
        return self._header_operation(service=True)

    def _operate_harvest(self, farm, start_ridge, end_ridge):
        if self._header_operation_active:
            return {"error": "Cannot harvest during a header operation"}
        self._header_operation_active = True
        try:
            result = super()._operate_harvest(farm, start_ridge, end_ridge)
            if result.get("status") == "ok" and self._h01_pass is not None:
                # Candidate-only trace enrichment; public grain receipts keep
                # their established quantity semantics.
                self._operation_log[-1].update(
                    h01_operation_id=self._h01_pass["operation_id"],
                    machine_quality=self._h01_pass["q_pass"],
                )
            return result
        finally:
            self._h01_pass = None
            self._header_operation_active = False

    def _tractor_harvest_quality_for_pass(self, farm, ridge_ids):
        self._validate_condition(self._header_condition)
        q_pass = HEADER_QUALITY[self._header_condition]
        self._h01_pass = dict(
            operation_id="h01_" + uuid.uuid4().hex[:12],
            ridge_ids=list(ridge_ids), condition_at_start=self._header_condition,
            q_pass=q_pass, harvest_started_at=float(self.time_manager.time()),
        )
        return q_pass

    def _tractor_register_harvest_with_physics(
        self, farm, ridge_ids, *, machine_quality=0.95, operation_id=None,
    ):
        snapshot = self._h01_pass
        if (snapshot is None or snapshot["ridge_ids"] != list(ridge_ids)
                or snapshot["q_pass"] != machine_quality):
            raise ValueError("H01 harvest must use its immutable legal-pass snapshot")
        finished = float(self.time_manager.time())
        grain = super()._tractor_register_harvest_with_physics(
            farm, ridge_ids, machine_quality=machine_quality,
            operation_id=snapshot["operation_id"],
        )
        record = farm.world.physics.action_log[-1]
        if record.action_id != snapshot["operation_id"] or record.action_type != "harvest":
            raise ValueError("Native harvest action record is missing")
        batch = deepcopy(snapshot)
        batch.update(harvest_finished_at=finished,
                     harvest_registered_at=record.timestamp,
                     action_machine_quality=record.parameters["machine_quality"],
                     grain_added_kg_rounded=grain,
                     per_ridge=[self._recovery_row(farm, rid, machine_quality) for rid in ridge_ids])
        for field in ("area_m2", "biological_dm_kg", "field_loss_dm_kg",
                      "harvestable_dm_kg", "machine_loss_dm_kg", "recovered_dm_kg", "standard_grain_kg"):
            batch[field] = sum(row[field] for row in batch["per_ridge"])
        batch["loss_components"] = {
            "source": "native recovery fractions and current maize harvest inputs",
            "machine_loss_scope": "total native machine loss, not q-only loss",
            "any_clipping": any(row["loss_components"]["clipping_applied"] for row in batch["per_ridge"]),
        }
        self._harvest_batches.append(batch)
        return grain

    @staticmethod
    def _recovery_row(farm, ridge, q_pass):
        physics = farm.world.physics
        state = physics.yield_recovery.states[ridge]
        params = physics.yield_recovery.params
        if not params.biological_yield_is_dry_matter or not isclose(params.market_moisture_frac, .14):
            raise ValueError("H01 ledger requires dry biological mass and 14% market grain")
        area = float(farm.world.ridge_area_m2)
        biological = state.biological_yield_g_m2 * area / 1000.0
        field_loss = biological * state.field_loss_fraction
        harvestable = biological - field_loss
        machine_loss = harvestable * state.machine_loss_fraction
        standard = state.recovered_yield_g_m2_at_market_moisture * area / 1000.0
        recovered = standard * (1.0 - params.market_moisture_frac)
        moisture = state.grain_moisture_frac
        # This is diagnostic decomposition only. Native settle_harvest has
        # already applied the loss once. The current maize orchestrator supplies
        # no lodging severity; keep that declared zero explicit in the ledger.
        components = {
            "base": params.base_machine_loss_fraction,
            "low_moisture": params.low_moisture_machine_loss_bonus if moisture < params.dry_shatter_threshold else 0.0,
            "high_moisture": params.high_moisture_machine_loss_bonus if moisture > params.wet_harvest_threshold else 0.0,
            "lodging": 0.0,
            "machine_quality": (1.0 - q_pass) * 0.10,
        }
        raw = sum(components.values())
        clipped = min(params.max_machine_loss_fraction, max(0.0, raw))
        return dict(
            ridge=ridge, area_m2=area, harvested=state.harvested,
            harvest_date=state.harvest_date.isoformat() if state.harvest_date else None,
            grain_moisture_frac_at_harvest=moisture,
            biological_yield_g_m2=state.biological_yield_g_m2,
            recovered_yield_g_m2_at_market_moisture=state.recovered_yield_g_m2_at_market_moisture,
            biological_dm_kg=biological,
            field_loss_fraction=state.field_loss_fraction, field_loss_dm_kg=field_loss,
            harvestable_dm_kg=harvestable,
            machine_loss_fraction=state.machine_loss_fraction, machine_loss_dm_kg=machine_loss,
            recovered_dm_kg=recovered, standard_grain_kg=standard,
            loss_components=dict(components, raw=raw, clipped=state.machine_loss_fraction,
                                 clip_upper_bound=params.max_machine_loss_fraction,
                                 clipping_applied=not isclose(raw, state.machine_loss_fraction, abs_tol=1e-12),
                                 matches_native=isclose(clipped, state.machine_loss_fraction, abs_tol=1e-12)),
            dm_balance_residual_kg=biological - field_loss - machine_loss - recovered,
        )
