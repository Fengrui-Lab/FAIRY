"""Sweep backend selection must reach each cell without losing context options."""
import json

import pytest

from scripts.iclr_validation_runner import (
    CellSpec,
    _build_cell_command,
    _merge_detail_into_creation_kwargs,
    _parse_args,
)


def _required(tmp_path):
    return [
        "--phase", "l3_wofost",
        "--output-root", str(tmp_path / "outputs"),
        "--families", "farm_baseline_react",
        "--scenarios", "scenario_full_season_heinong84_staggered_planting",
    ]


def test_wofost_config_preserves_kwargs_and_reaches_subprocess(tmp_path):
    config_path = tmp_path / "wofost.json"
    native_options = {"cultivar_profile": "heilongjiang_heinong84_complete_v1"}
    config_path.write_text(json.dumps(native_options))
    args = _parse_args(_required(tmp_path) + [
        "--wofost-config", str(config_path),
        "--scenario-kwargs", '{"seed":17,"detailed_briefing":"library"}',
        "--detail", "false",
    ])
    kwargs, detail = _merge_detail_into_creation_kwargs(args.scenario_kwargs, args.detail)
    expected = {
        "seed": 17, "detailed_briefing": False,
        "crop_backend": "wofost", "crop_backend_options": native_options,
    }
    assert json.loads(kwargs) == expected
    assert detail is False
    command = _build_cell_command(
        CellSpec("farm_baseline_react", "scenario_full_season_example", 1),
        "example-model", "openai", tmp_path,
        scenario_creation_kwargs=kwargs,
    )
    forwarded = command[command.index("--scenario-kwargs") + 1]
    assert json.loads(forwarded) == expected
    # Cells receive resolved values and do not re-read the source config file.
    assert "--wofost-config" not in command


def test_explicit_backend_overrides_existing_kwargs_and_default_is_unchanged(tmp_path):
    plain = _parse_args(_required(tmp_path))
    assert plain.scenario_kwargs is None
    args = _parse_args(_required(tmp_path) + [
        "--crop-backend", "wofost",
        "--scenario-kwargs", '{"crop_backend":"legacy","seed":9}',
    ])
    assert json.loads(args.scenario_kwargs) == {"crop_backend": "wofost", "seed": 9}


def test_runner_config_supports_backend_fields_and_cli_override(tmp_path):
    native_path = tmp_path / "native.json"
    native_path.write_text('{"reference_density_plants_m2":23}')
    runner_path = tmp_path / "runner.json"
    runner_path.write_text(json.dumps({"iclr_validation_runner": {
        "phase": "l3_wofost", "output_root": str(tmp_path / "outputs"),
        "families": ["farm_baseline_react"], "scenarios": ["example"],
        "crop-backend": "wofost", "wofost-config": str(native_path),
        "scenario_kwargs": {"detailed_briefing": "library", "seed": 7},
    }}))
    args = _parse_args(["--config", str(runner_path)])
    assert json.loads(args.scenario_kwargs) == {
        "detailed_briefing": "library", "seed": 7,
        "crop_backend": "wofost",
        "crop_backend_options": {"reference_density_plants_m2": 23},
    }
    replacement = tmp_path / "replacement.json"
    replacement.write_text('{"external_biotic_coupling":false}')
    overridden = _parse_args([
        "--config", str(runner_path), "--wofost-config", str(replacement),
    ])
    assert json.loads(overridden.scenario_kwargs)["crop_backend_options"] == {
        "external_biotic_coupling": False,
    }


@pytest.mark.parametrize("selection", [
    ["--crop-backend", "legacy"],
    ["--scenario-kwargs", '{"crop_backend":"legacy"}'],
])
def test_legacy_and_wofost_config_conflict_before_dispatch(tmp_path, selection, capsys):
    native_path = tmp_path / "native.json"
    native_path.write_text("{}")
    with pytest.raises(SystemExit) as error:
        _parse_args(_required(tmp_path) + selection + ["--wofost-config", str(native_path)])
    assert error.value.code == 2
    assert "requires --crop-backend wofost" in capsys.readouterr().err
    assert not (tmp_path / "outputs").exists()


@pytest.mark.parametrize("contents", ["[]", "null", "{broken"])
def test_invalid_native_config_is_rejected_before_dispatch(tmp_path, contents, capsys):
    native_path = tmp_path / "native.json"
    native_path.write_text(contents)
    with pytest.raises(SystemExit) as error:
        _parse_args(_required(tmp_path) + ["--wofost-config", str(native_path)])
    assert error.value.code == 2
    assert "--wofost-config" in capsys.readouterr().err
    assert not (tmp_path / "outputs").exists()


def test_missing_native_config_is_rejected_before_dispatch(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        _parse_args(_required(tmp_path) + ["--wofost-config", str(tmp_path / "absent.json")])
    assert error.value.code == 2
    assert "Cannot read --wofost-config" in capsys.readouterr().err


def test_invalid_backend_from_runner_config_is_rejected(tmp_path, capsys):
    runner_path = tmp_path / "runner.json"
    runner_path.write_text('{"crop_backend":"typo"}')
    with pytest.raises(SystemExit) as error:
        _parse_args(_required(tmp_path) + ["--config", str(runner_path)])
    assert error.value.code == 2
    assert "--crop-backend must be one of" in capsys.readouterr().err
