"""FOS must load generated baselines from this repository's actual root."""
from fairy.scenarios.fos import evaluation


def test_default_baseline_directory_is_inside_repository(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    module = repo / "fairy/scenarios/fos/evaluation.py"
    module.parent.mkdir(parents=True)
    expected = repo / "oracle_baselines"
    expected.mkdir()
    # A stale sibling directory must never win over the repository default.
    (tmp_path / "oracle_baselines").mkdir()
    monkeypatch.setattr(evaluation, "__file__", str(module))
    monkeypatch.delenv("FOS_ORACLE_BASELINE_DIR", raising=False)
    assert evaluation._resolve_oracle_baseline_dir(None) == expected


def test_explicit_and_environment_baselines_keep_priority(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit"
    configured = tmp_path / "configured"
    explicit.mkdir()
    configured.mkdir()
    monkeypatch.setenv("FOS_ORACLE_BASELINE_DIR", str(configured))
    assert evaluation._resolve_oracle_baseline_dir(explicit) == explicit
    assert evaluation._resolve_oracle_baseline_dir(None) == configured
    assert evaluation._resolve_oracle_baseline_dir(tmp_path / "missing") == configured
