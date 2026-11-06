import argparse
from pathlib import Path
import csv
import json
import hashlib
import math


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify all three-model metrics and original artifact hashes"
    )
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args(argv)
    ROOT = args.root.resolve()
    checks = []
    for model in ["deepseek_thinking", "qwen_nothinking", "gpt6_luna"]:
        d = ROOT / model
        manifest = json.loads((d / "manifest.json").read_text())
        records = manifest.get("records", manifest.get("scenarios"))
        files = 0
        size = 0
        for r in records:
            cell = d / r["collected_cell_dir"]
            for f in r["files"]:
                p = cell / f["name"]
                assert p.stat().st_size == f["bytes"]
                assert sha(p) == f["sha256"], p
                files += 1
                size += f["bytes"]
        checks.append(
            {
                "model": model,
                "original_file_count": files,
                "bytes": size,
                "original_files_match_collection_manifest": True,
            }
        )
    with (ROOT / "summary.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert (
        len(rows) == len({(r["model_condition"], r["scenario"]) for r in rows}) == 102
    )
    metrics = [
        "total_tokens_per_scenario",
        "llm_calls_with_usage",
        "agent_tool_calls",
        "yield_loss(%)",
        "recovered_yield_loss(%)",
        "ktc(%)",
        "coverage(%)",
        "bfcl_success(%)",
        "core_path_correctness(%)",
        "relative_operating_cost_gap(%)",
        "relative_net_operating_return_gap(%)",
    ]
    for r in rows:
        for key in metrics:
            assert math.isfinite(float(r[key])), (
                r["model_condition"],
                r["scenario"],
                key,
            )
        for key in [
            "cell_dir",
            "fos_path",
            "management_metrics_path",
            "oracle_reference_path",
            "original_agent_workflow_path",
            "original_runtime_log_path",
            "original_progress_log_path",
        ]:
            p = Path(r[key])
            p = p if p.is_absolute() else ROOT / p
            assert p.exists(), (key, p)
    summary = {
        "model_scenario_pairs": 102,
        "finite_metrics_per_pair": len(metrics),
        "all_artifact_links_valid": True,
        "original_files": checks,
        "summary_sha256": sha(ROOT / "summary.csv"),
        "new_model_calls": 0,
    }
    (ROOT / "original_files_verification.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
