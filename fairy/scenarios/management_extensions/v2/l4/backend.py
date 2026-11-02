"""Continuous native soil across explicit crop cycles, isolated from legacy scenes.

Only a harvested/finalized crop may be replaced. The existing PCSE model, CWB,
CNB, daily clock and cumulative management accounts remain alive. Crop-start
records are stored in the native forcing journal so checkpoint reconstruction
replays the same seasons rather than importing a fresh soil initial condition.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from typing import Any

from fairy.physics.wofost_backend import WofostBackend


class ContinuousSeasonBackend(WofostBackend):
    """Same-crop annual succession; cross-species parameter changes are not enabled."""

    def __init__(self, config=None):
        super().__init__(config)
        self._initial_specifications: dict[int, dict[str, Any]] = {}
        self._next_seasons: dict[int, dict[str, Any]] = {}
        self.season_history: list[dict[str, Any]] = []

    def authorize_next_season(self, physics, ridge_ids, planting_day: date) -> None:
        """Approve explicit new sowing after harvest; do not advance or reset soil."""
        ids = list(ridge_ids)
        for rid in ids:
            run = self._runs.get(rid)
            if (
                run is None
                or run.model.crop is not None
                or physics.phenology.states[rid].planted
            ):
                raise ValueError(
                    "Next season requires a harvested and finalized native crop"
                )
            if planting_day <= date.fromisoformat(run.specification["planting_date"]):
                raise ValueError("Next planting date must follow the preceding crop")
            if run.model.day != planting_day:
                raise ValueError(
                    "Advance every intervening soil/weather day before opening a season"
                )
        for rid in ids:
            self._next_seasons[rid] = {"authorized_day": planting_day.isoformat()}

    def queue_actions(self, actions_by_ridge, ridge_area_m2):
        # A PLANTING action only marks sowing; water and actual fertilizer stay
        # in the ordinary queue and are applied exactly once by the parent.
        filtered = {}
        for rid, actions in actions_by_ridge.items():
            filtered[rid] = []
            for action in actions:
                kind = str(getattr(action.action_type, "value", action.action_type))
                if kind == "PLANTING" and int(rid) in self._runs:
                    if int(rid) not in self._next_seasons:
                        raise ValueError(
                            "Open the next season before sowing an occupied native ridge"
                        )
                else:
                    filtered[rid].append(action)
        super().queue_actions(filtered, ridge_area_m2)

    def advance_day(
        self,
        physics,
        day,
        weather,
        actions_by_ridge=None,
        density_by_ridge=None,
        ridge_area_m2=1.0,
        humidity_pct=None,
    ):
        for rid, authorization in list(self._next_seasons.items()):
            phen = physics.phenology.states[rid]
            if not phen.planted:
                continue
            if (
                not date.fromisoformat(authorization["authorized_day"])
                <= phen.planting_date
                <= date.fromisoformat(authorization["authorized_day"])
                + timedelta(days=7)
            ):
                raise ValueError("Sowing date does not match the opened crop cycle")
            run = self._runs[rid]
            self._initial_specifications.setdefault(rid, deepcopy(run.specification))
            spec = self._specification(
                physics,
                rid,
                day,
                (density_by_ridge or {}).get(
                    rid, self.config.reference_density_plants_m2
                ),
            )
            spec["preplant_inputs"] = self._empty_inputs()
            authorization["specification"] = spec
            # Parent validates planting identity before calling _advance_native.
            run.specification = deepcopy(spec)
        result = super().advance_day(
            physics,
            day,
            weather,
            actions_by_ridge,
            density_by_ridge,
            ridge_area_m2,
            humidity_pct,
        )
        for rid in list(self._next_seasons):
            if "specification" in self._next_seasons[rid]:
                del self._next_seasons[rid]
        return result

    def _advance_native(self, run, entry, *, soil_nitrogen_preapplied=False):
        entry = deepcopy(entry)
        if "season_start" not in entry:
            for rid, queued in self._next_seasons.items():
                if self._runs.get(rid) is run and "specification" in queued:
                    entry["season_start"] = deepcopy(queued["specification"])
                    break
        if "season_start" in entry:
            spec = entry["season_start"]
            model = run.model
            if model.crop is not None:
                raise ValueError("Cannot replace a live native crop")
            if model.day.isoformat() != entry["day"]:
                raise ValueError(
                    "Crop transition is not on the continuous native clock"
                )
            soil = model.soil
            before = self._soil_pools(model)
            # Updating crop coefficients does not reconstruct the ParameterProvider
            # or either native soil component. This first version keeps one species.
            model.parameterprovider._cropdata.clear()
            model.parameterprovider._cropdata.update(deepcopy(spec["crop_parameters"]))
            model._send_signal(
                signal=self._runtime["signals"].crop_start,
                day=model.day,
                crop_name=self.config.crop_name,
                variety_name=spec["variety"],
                crop_start_type="sowing",
                crop_end_type="maturity",
            )
            model.crop.assim = self._runtime["Assimilation"](
                model.day, model.kiosk, model.parameterprovider
            )
            run.specification = deepcopy(spec)
            run.maturity_snapshot = None
            assert model.soil is soil
            after = self._soil_pools(model)
            if before != after:
                raise RuntimeError(
                    "Crop-start signal changed soil pools before daily integration"
                )
            self.season_history.append(
                {
                    "day": entry["day"],
                    "soil_before": before,
                    "soil_after": after,
                    "planting_date": spec["planting_date"],
                }
            )
        super()._advance_native(
            run, entry, soil_nitrogen_preapplied=soil_nitrogen_preapplied
        )

    @staticmethod
    def _soil_pools(model):
        water, nitrogen = (
            model.soil.waterbalance.states,
            model.soil.nutrientbalance.states,
        )
        return {
            **{key: float(getattr(water, key)) for key in ("W", "WLOW", "SS")},
            **{key: float(getattr(nitrogen, key)) for key in ("NAVAIL", "NSOIL")},
        }

    def snapshot(self):
        result = super().snapshot()
        result["provenance"]["season_adapter"] = {
            "name": "management_extensions.v2.l4.ContinuousSeasonBackend",
            "version": 1,
            "soil_continuity": "same_native_instance",
        }
        return result

    def export_state(self):
        state = super().export_state()
        for rid, spec in self._initial_specifications.items():
            state["runs"][str(rid)]["specification"] = deepcopy(spec)
        state["continuous_seasons"] = {
            "schema": 1,
            "pending": deepcopy(self._next_seasons),
        }
        return state

    @classmethod
    def from_state(cls, payload):
        if payload.get("continuous_seasons", {}).get("schema") != 1:
            raise ValueError("Continuous-season checkpoint marker is required")
        backend = super().from_state(payload)
        backend._initial_specifications = {
            int(rid): deepcopy(saved["specification"])
            for rid, saved in payload["runs"].items()
        }
        backend._next_seasons = {
            int(rid): deepcopy(value)
            for rid, value in payload["continuous_seasons"].get("pending", {}).items()
        }
        return backend
