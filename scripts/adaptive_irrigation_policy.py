"""Public-observation soybean irrigation policy; no simulator state is imported.

``decide_irrigation`` accepts raw registered-tool responses under ``clock``,
``overview``, ``ridges``, ``management``, ``forecast``, ``root_zone`` and
``surface``. Service receipts with a ``data`` dictionary are also accepted.
``capabilities`` must declare the registered application_mm_per_hour=5 and
root_zone_registered boolean. A caller must acquire fresh observations before
each decision and execute at most the single returned proposal.

History contains actual execution receipts, not plans::

    {"started_at": before_clock_timestamp, "finished_at": after_clock_timestamp,
     "tool_args": {"start": 0, "end": 9, "hours": 1.6},
     "response": irrigation_tool_response}

After a previous irrigation, ``observed_at.root_zone`` (or ``.surface``) must
contain the public System.get_current_time response captured when that probe
response was read. This establishes a post-delivery recheck without inventing
timestamps inside the sensor response. Quota is read from the latest public
management response; historical water is never subtracted a second time.

Sources support stage priorities and the need for soil/forecast observations:
FAO, https://www.fao.org/4/i2800e/i2800e.pdf (soybean chapter), and UNL G1367,
https://extensionpubs.unl.edu/publication/g1367/na/html/view . They do NOT supply
the VWC cutoffs, pulse sizes or reserve fraction below. Those are explicit,
searchable engineering settings, not a local agronomic calibration or a yield
guarantee. Public probes disclose neither field capacity nor rooting depth;
therefore this policy never calculates a purported root-zone deficit in mm.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
import math
import re
from typing import Any


@dataclass(frozen=True)
class PolicyParameters:
    """Six transparent water rules plus two bounded execution constraints."""

    root_trigger_vwc: float = 0.22
    reproductive_boost_vwc: float = 0.02
    emergency_vwc: float = 0.17
    pulse_mm: float = 8.0
    pre_pod_reserve_fraction: float = 0.35
    forecast_rain_skip_mm: float = 6.0
    min_interval_hours: float = 48.0
    max_daily_operations: int = 2

    def __post_init__(self) -> None:
        numbers = asdict(self)
        for name, value in numbers.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
        if not 0.10 <= self.emergency_vwc <= self.root_trigger_vwc <= 0.35:
            raise ValueError("Require .10 <= emergency_vwc <= root_trigger_vwc <= .35")
        if not 0 <= self.reproductive_boost_vwc <= 0.05 or self.root_trigger_vwc + self.reproductive_boost_vwc > 0.40:
            raise ValueError("reproductive_boost_vwc must be0--.05 and keep the trigger <=.40")
        if not 2 <= self.pulse_mm <= 20:
            raise ValueError("pulse_mm must be2--20mm per target ridge")
        if not 0 <= self.pre_pod_reserve_fraction <= 0.9:
            raise ValueError("pre_pod_reserve_fraction must be0--.9")
        if not 1 <= self.forecast_rain_skip_mm <= 40:
            raise ValueError("forecast_rain_skip_mm must be1--40mm over the next two days")
        if not 24 <= self.min_interval_hours <= 168:
            raise ValueError("min_interval_hours must be24--168h")
        if type(self.max_daily_operations) is not int or not 1 <= self.max_daily_operations <= 4:
            raise ValueError("max_daily_operations must be an integer1--4")


def _payload(response: Any) -> dict[str, Any]:
    if not isinstance(response, Mapping):
        return {}
    if response.get("error") or response.get("status") in {"error", "failed"}:
        return {"error": response.get("error", response.get("status"))}
    data = response.get("data")
    return dict(data) if isinstance(data, Mapping) else dict(response)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    return float(value) if math.isfinite(value) else None


def _clock(response: Any) -> tuple[float | None, datetime | None]:
    data = _payload(response)
    now = _number(data.get("current_timestamp"))
    try:
        local = datetime.fromisoformat(str(data["current_datetime"]))
    except (KeyError, ValueError):
        local = None
    return now, local


def _phase(stage: Any) -> str | None:
    text = str(stage).upper()
    reproductive = re.match(r"^R([1-8])(?:\b|_)", text)
    if reproductive:
        number = int(reproductive.group(1))
        return "mature" if number >= 7 else "pod_seed" if number >= 3 else "flowering"
    if re.match(r"^V(?:E|C|\d+)(?:\b|_)", text):
        return "vegetative"
    return None


def _segments(ids: list[int]) -> list[tuple[int, int]]:
    result = []
    for ridge_id in sorted(ids):
        if result and ridge_id == result[-1][1] + 1:
            result[-1] = (result[-1][0], ridge_id)
        else:
            result.append((ridge_id, ridge_id))
    return result


def _forecast(response: Any, local_day) -> tuple[float, int]:
    """Use only returned forecast entries in the next two local calendar days."""
    entries = _payload(response).get("forecast", [])
    total, used = 0.0, 0
    if not isinstance(entries, list):
        return total, used
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            continue
        rain = _number(entry.get("rainfall_mm"))
        if rain is None or rain < 0:
            continue
        if entry.get("date") is not None:
            try:
                delta = (datetime.fromisoformat(str(entry["date"])).date() - local_day).days
            except ValueError:
                continue
            if not 1 <= delta <= 2:
                continue
        elif index >= 2:
            continue
        total += rain
        used += 1
    return total, used


def _history(history: Sequence[Mapping[str, Any]], farm_id: str) -> list[dict[str, Any]]:
    records = []
    for item in history:
        response = _payload(item.get("response"))
        for candidate in (item.get("response"), response):
            if isinstance(candidate, Mapping) and candidate.get("farm_id") not in {None, farm_id}:
                raise ValueError("Irrigation history contains a receipt from a different farm")
        if response.get("error") or response.get("status") in {"error", "failed", "partial"}:
            continue
        ids = response.get("irrigated_ridges")
        if not isinstance(ids, list) or not ids or any(type(rid) is not int for rid in ids):
            continue
        finish = _number(item.get("finished_at"))
        if finish is None:
            raise ValueError("A successful or pending irrigation receipt requires finished_at")
        ready = _number(response.get("effect_ready_at"))
        records.append({"ids": set(ids), "finished_at": finish,
                        "ready_at": max(finish, ready if ready is not None else finish),
                        "pending": response.get("status") == "irrigation_pending"})
    return records


def decide_irrigation(
    observations: Mapping[str, Any], *, history: Sequence[Mapping[str, Any]] = (),
    parameters: PolicyParameters | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one bounded proposal using only the documented public responses.

    ``action`` is ``irrigate``, ``wait`` or ``observe``. An irrigation result
    includes farm_id, target.start/end, hours, nominal mm_per_ridge and the
    corresponding field_equivalent_mm. It is a proposal, not an executed tool.
    Reasons and audit retain the observed zone/stage/forecast/quota basis.
    Unknown native variables, scenario IDs/events and extra input keys are
    ignored; no current/future private model state is accepted or discovered.
    """
    params = parameters if isinstance(parameters, PolicyParameters) else PolicyParameters(**dict(parameters or {}))
    if not isinstance(observations, Mapping):
        raise ValueError("observations must be registered public-tool response dictionaries")
    overview = _payload(observations.get("overview"))
    farm_id = overview.get("farm_id")
    now, local = _clock(observations.get("clock"))
    audit: dict[str, Any] = {
        "parameters": asdict(params), "water_method": "VWC_threshold_bounded_pulse_no_inferred_root_deficit",
        "known_limitations": ["Public probes disclose no root depth, field capacity or wilting point; pulse depth is not a computed soil deficit.",
                              "Root probes are noisy zone averages; surface probes describe5cm soil only. Absolute VWC cutoffs and reserve size are uncalibrated engineering policy settings."],
        "stage_evidence": ["https://www.fao.org/4/i2800e/i2800e.pdf",
                           "https://extensionpubs.unl.edu/publication/g1367/na/html/view"],
        "skipped": [],
    }

    def decision(action, reasons, *, target=None, hours=0.0, mm=0.0, field_mm=0.0, recheck=None):
        return {"action": action, "farm_id": farm_id, "target": target, "hours": hours,
                "mm_per_ridge": mm, "field_equivalent_mm": field_mm,
                "reasons": reasons, "audit": audit, "recheck_after_timestamp": recheck}

    if now is None or local is None:
        return decision("observe", ["Read the public current timestamp and local datetime before scheduling irrigation."])
    if not isinstance(farm_id, str) or not farm_id:
        return decision("observe", ["Read the farm overview to identify the target farm."])
    count = overview.get("num_ridges")
    if type(count) is not int or count <= 0:
        return decision("observe", ["The public farm overview must declare the total ridge count for field-equivalent water accounting."])
    if overview.get("crop_type", "soybean") != "soybean":
        return decision("observe", ["This policy's stage rules support soybean only; another crop requires its own policy."])
    for key in ("overview", "ridges", "management", "root_zone", "surface", "forecast"):
        response = observations.get(key)
        for candidate in (response, _payload(response)):
            if isinstance(candidate, Mapping) and candidate.get("farm_id") not in {None, farm_id}:
                raise ValueError(f"{key} belongs to a different farm")
    caps = observations.get("capabilities", {})
    if (not isinstance(caps, Mapping) or _number(caps.get("application_mm_per_hour")) != 5.0
            or type(caps.get("root_zone_registered")) is not bool):
        return decision("observe", ["Confirm registered irrigation capability5mm/hour and whether the root-zone probe tool is registered."])
    rate = 5.0
    regime_data = _payload(observations.get("management"))
    regime = regime_data.get("management_regime")
    if not isinstance(regime, Mapping) or "irrigation_quota_mm_total" not in regime or "irrigation_used_mm_total" not in regime:
        return decision("observe", ["Read the public management water quota and actual usage before spending water."])
    quota = _number(regime["irrigation_quota_mm_total"])
    used = _number(regime["irrigation_used_mm_total"])
    if used is None or used < 0 or (regime["irrigation_quota_mm_total"] is not None and (quota is None or quota < 0)):
        raise ValueError("Public water quota/usage must be nonnegative finite values, or quota=None")
    remaining = None if quota is None else max(0.0, quota - used)
    audit["budget"] = {"quota_field_mm": quota, "used_field_mm": used, "remaining_field_mm": remaining,
                       "usage_source": "latest_public_management_status_only_not_history_subtracted_twice",
                       "rounding_safety_field_mm": 0.0001}
    if remaining is not None and remaining <= 0.0001:
        return decision("wait", ["The declared field-equivalent water quota is exhausted; do not add water or change the budget."], recheck=now + 86400)
    rows = _payload(observations.get("ridges")).get("ridges")
    if not isinstance(rows, list) or not rows:
        return decision("observe", ["Read public ridge planting, maturity and irrigation-pending states."])
    ridges = {}
    for row in rows:
        if not isinstance(row, Mapping) or type(row.get("ridge_id")) is not int or not 0 <= row["ridge_id"] < count:
            raise ValueError("Public ridge states must have valid local ridge IDs")
        rid = row["ridge_id"]
        if rid in ridges:
            raise ValueError("Duplicate ridge IDs in public state response")
        if row.get("farm_id") not in {None, farm_id}:
            raise ValueError("Ridge states contain a different farm")
        ridges[rid] = row
    records = _history(history, farm_id)
    # Derive today's boundary from the public local wall clock, not UTC dates.
    day_start = now - (local.hour * 3600 + local.minute * 60 + local.second + local.microsecond / 1e6)
    today_count = sum(not record["pending"] and day_start <= record["finished_at"] <= now for record in records)
    audit["successful_operations_today"] = today_count
    if today_count >= params.max_daily_operations:
        return decision("wait", ["The bounded daily irrigation-operation limit has been reached."], recheck=day_start + 86400)
    rain, rain_days = _forecast(observations.get("forecast"), local.date())
    audit["forecast"] = {"next_two_days_returned_rain_mm": rain, "valid_entries": rain_days,
                         "missing_forecast_is_not_proof_of_no_rain": rain_days == 0}
    key, field, data_key = (("root_zone", "root_vwc", "root_zone_sensors") if caps["root_zone_registered"]
                            else ("surface", "vwc", "soil_sensors"))
    readings = _payload(observations.get(key)).get(data_key)
    if not isinstance(readings, list) or not readings:
        return decision("observe", [f"Read the registered {key} probe tool before choosing an irrigation target."])
    audit["probe_source"] = key
    if key == "surface":
        audit["surface_only_rule"] = "A5cm dry surface is not an inferred dry root zone: use a lower trigger and at most4mm, then recheck. Unregistered root-zone data is ignored."
    observed_times = observations.get("observed_at", {})
    read_at, _ = _clock(observed_times.get(key)) if isinstance(observed_times, Mapping) else (None, None)
    if read_at is not None and read_at > now + 1e-6:
        raise ValueError("Probe observation timestamp is in the future")
    candidates = []
    waiting_for_observation = False
    next_review = now + 86400
    covered = set()
    for probe in readings:
        if not isinstance(probe, Mapping):
            raise ValueError("Invalid public probe reading")
        start, end, vwc = probe.get("ridge_start"), probe.get("ridge_end"), _number(probe.get(field))
        if (type(start) is not int or type(end) is not int or not 0 <= start <= end < count
                or vwc is None or not 0 <= vwc <= 1):
            raise ValueError("Probe coverage and VWC must be valid public values")
        coverage = set(range(start, end + 1))
        if covered & coverage:
            raise ValueError("Overlapping probe coverage is ambiguous; do not invent per-ridge moisture")
        covered.update(coverage)
        for phase in ("pod_seed", "flowering", "vegetative"):
            eligible = [rid for rid in coverage & ridges.keys() if ridges[rid].get("planted")
                        and not ridges[rid].get("harvested") and _phase(ridges[rid].get("growth_stage")) == phase]
            pending_ids = [rid for rid in eligible if ridges[rid].get("irrigation_pending")]
            for first, last in _segments(pending_ids):
                audit["skipped"].append({"start": first, "end": last, "phase": phase,
                                         "reason": "public_irrigation_pending"})
            eligible = [rid for rid in eligible if rid not in pending_ids]
            for first, last in _segments(eligible):
                ids = set(range(first, last + 1))
                label = {"start": first, "end": last, "phase": phase, "observed_zone_vwc": vwc}
                trigger = params.root_trigger_vwc + (params.reproductive_boost_vwc if phase == "pod_seed" else 0)
                emergency = vwc <= params.emergency_vwc
                if key == "surface":
                    trigger, emergency = min(trigger, .17), vwc <= .13
                past = [record for record in records if ids & record["ids"]]
                previous = None
                if past:
                    previous = max(past, key=lambda record: record["finished_at"])
                    if now < previous["ready_at"]:
                        next_review = min(next_review, previous["ready_at"])
                        audit["skipped"].append({**label, "reason": "wait_for_actual_tool_effect_ready_at"})
                        continue
                    if read_at is None or read_at < previous["ready_at"]:
                        waiting_for_observation = True
                        audit["skipped"].append({**label, "reason": "fresh_post_delivery_probe_required"})
                        continue
                if vwc >= trigger:
                    audit["skipped"].append({**label, "reason": "probe_above_trigger", "trigger_vwc": trigger})
                    continue
                if previous is not None:
                    interval = max(24.0, params.min_interval_hours / 2) if emergency else params.min_interval_hours
                    eligible_at = previous["finished_at"] + interval * 3600
                    if now < eligible_at:
                        next_review = min(next_review, eligible_at)
                        audit["skipped"].append({**label, "reason": "bounded_repeat_interval", "eligible_at": eligible_at})
                        continue
                if rain_days and rain >= params.forecast_rain_skip_mm and not emergency:
                    audit["skipped"].append({**label, "reason": "defer_for_returned_near_term_rain", "forecast_rain_mm": rain})
                    continue
                reserve = quota * params.pre_pod_reserve_fraction if quota is not None and phase != "pod_seed" and not emergency else 0.0
                available = None if remaining is None else max(0.0, remaining - reserve - .0001)
                target_count = last - first + 1
                pulse = min(params.pulse_mm, 4.0) if key == "surface" or (emergency and rain >= params.forecast_rain_skip_mm) else params.pulse_mm
                hours = pulse / rate if available is None else min(pulse / rate, available * count / (rate * target_count))
                # Round downward so public4-decimal quota telemetry never causes an overrun.
                hours = math.floor(hours * 1e6 + 1e-9) / 1e6
                mm, field_mm = hours * rate, hours * rate * target_count / count
                if mm < 2.0 - 1e-9:
                    audit["skipped"].append({**label, "reason": "quota_or_pre_pod_reserve_below_minimum2mm_pulse", "held_field_mm": reserve})
                    continue
                score = (100 if emergency else 0) + {"pod_seed": 30, "flowering": 20, "vegetative": 10}[phase] + 100 * (trigger - vwc)
                candidates.append({**label, "sensor_id": probe.get("sensor_id"), "sensor_range": [start, end],
                                   "trigger_vwc": trigger, "emergency": emergency, "priority_score": score,
                                   "held_for_future_pod_seed_field_mm": reserve, "hours": hours,
                                   "mm_per_ridge": mm, "field_equivalent_mm": field_mm})
    audit["ranked_candidates"] = sorted(candidates, key=lambda row: (-row["priority_score"], row["start"], row["end"]))
    if not candidates:
        if waiting_for_observation:
            return decision("observe", ["Acquire a fresh probe response after the prior irrigation delivery before considering another pulse."], recheck=now)
        return decision("wait", ["No observed growing zone currently justifies a legal bounded irrigation pulse; unused quota alone is not a reason to irrigate."], recheck=next_review)
    chosen = audit["ranked_candidates"][0]
    reasons = [f"Observed {key} zone VWC{chosen['observed_zone_vwc']:.4f} is below the declared {chosen['trigger_vwc']:.4f} trigger in {chosen['phase']}.",
               "Prioritize observed water shortage and the public growth stage; recommend one pulse, then read the actual receipt and fresh probes."]
    if chosen["emergency"]:
        reasons.append("Severe observed dryness permits early rescue despite the ordinary pre-pod water reserve or forecast-rain deferral.")
    if chosen["held_for_future_pod_seed_field_mm"]:
        reasons.append("Retain part of the original water allowance for later pod development and seed filling.")
    if rain_days == 0:
        reasons.append("The returned forecast supplies no valid near-term rain amount; this is uncertainty, not knowledge of future dry weather.")
    audit["post_execution"] = "Record the actual tool response/effect_ready_at and before/after public clocks. Refresh public quota, ridge state, forecast and probes; never assume the proposed water has already worked."
    return decision("irrigate", reasons, target={"start": chosen["start"], "end": chosen["end"]},
                    hours=chosen["hours"], mm=chosen["mm_per_ridge"], field_mm=chosen["field_equivalent_mm"])
