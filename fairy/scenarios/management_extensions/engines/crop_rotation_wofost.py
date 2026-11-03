"""Explicit cross-crop succession on unchanged native WOFOST soil.

Crop coefficients are the checksum-verified upstream WUR files. Rotation records
carry each crop's complete configuration so replay never reconstructs an early
crop with the final crop's coefficients. No residue or fixed-N soil bonus exists.
"""

from copy import deepcopy
from dataclasses import asdict

from fairy.physics.wofost_backend import WofostBackend

from .continuous_wofost import ContinuousSeasonBackend


class CropRotationBackend(ContinuousSeasonBackend):
    # Crop identity, planting density and explicit seed-to-official-variety
    # assignments can change; climate, soils and nutrient accounting cannot.
    _CROP_FIELDS = frozenset(
        {
            "crop_name",
            "variety_name",
            "cultivar_map",
            "require_explicit_cultivar_parameters",
            "reference_density_plants_m2",
        }
    )

    @staticmethod
    def _check_official_crop(config):
        if (
            config.cultivar_profile
            or config.cultivar_profiles
            or config.parameter_overrides
        ):
            raise ValueError(
                "Rotation reference requires unmodified official crop parameters"
            )
        if config.external_biotic_coupling:
            raise ValueError(
                "Official native rotation reference does not include external biotic coupling"
            )

    def __init__(self, configuration=None):
        super().__init__(configuration)
        self._check_official_crop(self.config)
        self._rotation_environment = {
            k: deepcopy(v)
            for k, v in asdict(self.config).items()
            if k not in self._CROP_FIELDS
        }

    def _validate_configuration(self, configuration):
        checked = WofostBackend(configuration)
        self._check_official_crop(checked.config)
        environment = {
            k: deepcopy(v)
            for k, v in asdict(checked.config).items()
            if k not in self._CROP_FIELDS
        }
        if environment != self._rotation_environment:
            changed = sorted(
                k
                for k in environment
                if environment[k] != self._rotation_environment[k]
            )
            raise ValueError(
                f"Crop rotation cannot change soil/site/accounting configuration: {changed}"
            )
        return checked

    def _activate_configuration(self, configuration):
        checked = self._validate_configuration(configuration)
        if asdict(self.config) == asdict(checked.config):
            return
        for name in (
            "config",
            "_cultivar_profile",
            "_cultivar_profiles",
            "_data_provenance",
            "_varieties",
        ):
            setattr(self, name, deepcopy(getattr(checked, name)))

    def authorize_next_crop(self, physics, ridge_ids, planting_day, configuration):
        # All checks occur before a pending transition is created.
        checked = self._validate_configuration(configuration)
        self.authorize_next_season(physics, ridge_ids, planting_day)
        self._activate_configuration(asdict(checked.config))

    def _specification(self, *args, **kwargs):
        specification = super()._specification(*args, **kwargs)
        specification["rotation_configuration"] = asdict(self.config)
        return specification

    def _create_run(self, specification, *args, **kwargs):
        self._activate_configuration(specification["rotation_configuration"])
        return super()._create_run(specification, *args, **kwargs)

    def _advance_native(self, run, entry, *, soil_nitrogen_preapplied=False):
        # During live execution the pending transition is attached by the parent;
        # during reconstruction it is already recorded in this journal entry.
        specification = entry.get("season_start")
        if specification is not None:
            self._activate_configuration(specification["rotation_configuration"])
        super()._advance_native(
            run, entry, soil_nitrogen_preapplied=soil_nitrogen_preapplied
        )

    def snapshot(self):
        result = super().snapshot()
        sequence = []
        if self._runs:
            rid = min(self._runs)
            run = self._runs[rid]
            initial = self._initial_specifications.get(rid, run.specification)
            specifications = [initial] + [
                entry["season_start"]
                for entry in run.journal
                if "season_start" in entry
            ]
            for specification in specifications:
                config = specification["rotation_configuration"]
                checked = self._validate_configuration(config)
                sequence.append(
                    {
                        "crop_name": config["crop_name"],
                        "variety_name": specification["variety"],
                        "planting_date": specification["planting_date"],
                        "official_data": deepcopy(checked._data_provenance),
                    }
                )
        result["provenance"]["season_adapter"] = {
            "name": "management_extensions.engines.crop_rotation_wofost.CropRotationBackend",
            "version": 1,
            "checkpoint_schema": 1,
            "crop_sequence": sequence,
            "soil_continuity": "unchanged native model and soil components; crop identity recorded per season",
            "residue_n_bonus": False,
        }
        return result

    def export_state(self):
        state = super().export_state()
        state["crop_rotation"] = {"schema": 1}
        return state

    @classmethod
    def from_state(cls, payload):
        if payload.get("crop_rotation", {}).get("schema") != 1:
            raise ValueError("Crop-rotation checkpoint marker is required")
        backend = super().from_state(payload)
        # The last journalled crop may be the previous crop: a checkpoint can
        # fall after opening the next crop but before its first native day.
        # Restore the declared current configuration after replaying history.
        backend._activate_configuration(deepcopy(payload["config"]))
        return backend
