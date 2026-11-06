"""Join replay-generated metrics and original-run metadata; never invoke models."""

import argparse
from pathlib import Path
from collections import Counter
from statistics import fmean
import csv
import json
import hashlib
import math
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo

R = Path(__file__).resolve().parents[1]
MODELS = {
    "deepseek_thinking": "DeepSeek Thinking",
    "qwen_nothinking": "Qwen3.6-35B-A3B-FP8 NoThinking",
    "gpt6_luna": "GPT-6-Luna (reasoning=medium)",
}
SPECS = [
    ("Tokens (M)", "total_tokens_per_scenario", 1e6),
    ("Calls", "llm_calls_with_usage", 1),
    ("Tools", "agent_tool_calls", 1),
    ("YL (%)", "yield_loss(%)", 1),
    ("RYL (%)", "recovered_yield_loss(%)", 1),
    ("KTC (%)", "ktc(%)", 1),
    ("Cov. (%)", "coverage(%)", 1),
    ("BFCL Succ. (%)", "bfcl_success(%)", 1),
    ("Core Path Corr. (%)", "core_path_correctness(%)", 1),
    ("ROCG (%)", "relative_operating_cost_gap(%)", 1),
    ("RNRG (%)", "relative_net_operating_return_gap(%)", 1),
]
PATHCOLS = [
    "cell_dir",
    "fos_path",
    "management_metrics_path",
    "oracle_reference_path",
    "original_report_path",
    "original_agent_workflow_path",
    "original_runtime_log_path",
    "original_progress_log_path",
]


def sha(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for x in iter(lambda: f.read(1024 * 1024), b""):
            h.update(x)
    return h.hexdigest()


def readcsv(p):
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def writecsv(p, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def writejson(p, d):
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2, default=str) + "\n")


def numeric(r, k):
    v = float(r[k])
    assert math.isfinite(v), (r["scenario"], k)
    return v


def good(v):
    return str(v).lower() == "true"


def relpath(p, base):
    p = Path(p)
    if not p.is_absolute() and (base / p).exists():
        return str(p)
    # Replay CSVs can retain the original checkout prefix after collection.
    # Resolve their model-qualified suffix against the collected artifacts.
    for index in reversed(range(len(p.parts))):
        if p.parts[index] == base.name:
            suffix = Path(*p.parts[index + 1 :])
            if (base / suffix).exists():
                return str(suffix)
    p = p if p.is_absolute() else R / p
    return str(p.relative_to(base)) if p.is_relative_to(base) else str(p)


def table(head, rows):
    def line(vs):
        return "| " + " | ".join(str(v).replace("|", "\\|") for v in vs) + " |"

    return "\n".join(
        [line(head), line(["---"] * len(head)), *[line(row) for row in rows]]
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Collected three-model directory with manifests, runs and replay CSVs",
    )
    args = parser.parse_args(argv)
    OUT = args.root.resolve()
    G = json.loads((OUT / "provenance/SCENARIO_GROUPS.json").read_text())
    IDS = G["recommended_scenario_ids"]
    SC = {s["id"]: (g, s) for g in G["groups"] for s in g["scenarios"]}
    allrows = []
    audit = {
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "expected_scenarios_per_model": 34,
        "new_model_calls": 0,
        "models": {},
        "oracle_comparisons": [],
    }
    baseline_by = {}
    for model, label in MODELS.items():
        D = OUT / model
        if model == "deepseek_thinking":
            rows = readcsv(D / "summary.csv")
        else:
            raw = readcsv(D / "metrics/summary.csv")
            by = {r["scenario"]: r for r in raw}
            manifest = json.loads((D / "manifest.json").read_text())
            entries = {e["scenario"]: e for e in manifest["records"]}
            rows = []
            assert set(by) == set(IDS) and len(raw) == 34
            recovered = []
            for sid in IDS:
                row = dict(by[sid])
                entry = entries[sid]
                cell = D / entry["collected_cell_dir"]
                rp = cell / (sid + ".run_report.json")
                progress = cell / (sid + ".progress.jsonl")
                d = json.loads(rp.read_text()) if rp.exists() else {}
                v = d.get("evaluation", {}).get("validation", {})
                acct = v.get("metadata") or {}
                row.update(
                    original_run_status=d.get(
                        "status", "report_missing_after_evaluation_error"
                    ),
                    original_task_success=v.get("success"),
                    original_validation_message=v.get("message", ""),
                    original_created_at=d.get("created_at"),
                    original_seed=d.get("seed", 0),
                    source_original_report=str(
                        Path(entry["source_cell_dir"]) / (sid + ".run_report.json")
                    )
                    if rp.exists()
                    else "",
                    original_report_path=str(rp.relative_to(D)) if rp.exists() else "",
                    original_agent_workflow_path=str(
                        (cell / (sid + ".agent_workflow.json")).relative_to(D)
                    ),
                    original_progress_log_path=str(progress.relative_to(D)),
                    original_runtime_log_path=str(
                        (cell / (sid + ".runtime_log.jsonl")).relative_to(D)
                    ),
                    source_process_status="completed"
                    if rp.exists()
                    else "post_run_evaluation_error",
                    original_agent_finished=d.get("stop_reason") == "agent_finished",
                    usage_source="original_run_report",
                    original_report_present=rp.exists(),
                )
                config = d.get("llm_config") or {}
                if not rp.exists():
                    events = [json.loads(x) for x in progress.read_text().splitlines()]
                    ends = [x for x in events if x["record_type"] == "llm_call_end"]
                    end = events[-1]
                    assert (
                        end["record_type"] == "agent_run_end"
                        and end["stopped_reason"] == "agent_finished"
                    )
                    config = next(
                        x["llm_config"] for x in events if x.get("llm_config")
                    )
                    totals = {
                        k: sum(int((e.get("tokens") or {}).get(k) or 0) for e in ends)
                        for k in [
                            "total_tokens",
                            "prompt_tokens",
                            "completion_tokens",
                            "cached_tokens",
                        ]
                    }
                    calls = len(ends)
                    assert calls == end["llm_turn_count"]
                    duration = sum(float(e.get("wall_time_seconds") or 0) for e in ends)
                    row.update(
                        llm_calls_with_usage=calls,
                        total_tokens_per_scenario=f"{totals['total_tokens']:.2f}",
                        avg_total_tokens_per_agent_call=f"{totals['total_tokens'] / calls:.2f}",
                        avg_input_tokens_per_agent_call=f"{totals['prompt_tokens'] / calls:.2f}",
                        avg_output_tokens_per_agent_call=f"{totals['completion_tokens'] / calls:.2f}",
                        avg_cached_tokens_per_agent_call=f"{totals['cached_tokens'] / calls:.2f}",
                        avg_runtime_s_per_agent_call=f"{duration / calls:.2f}",
                        runtime_s_per_scenario=end["wall_time_seconds"],
                        model_type_size=config["model"],
                        llm_model="vLLM",
                        usage_source="original_progress_llm_call_end_tokens",
                        original_agent_finished=True,
                        original_created_at=events[0]["wall_timestamp"],
                    )
                    cd = json.loads((D / "cells" / (sid + ".json")).read_text())
                    d = {
                        "scenario_kwargs": json.loads(cd["scenario_kwargs"]),
                        "init_kwargs": {},
                        "limits": {
                            "max_output_tokens": cd["max_output_tokens"],
                            **{
                                k: next(
                                    x[k]
                                    for x in events
                                    if x["record_type"] == "agent_run_start"
                                )
                                for k in ["max_tool_calls", "timeout_seconds"]
                            },
                        },
                    }
                    recovered.append(
                        {
                            "scenario": sid,
                            "calls": calls,
                            "tokens": totals,
                            "original_agent_finished": True,
                            "final_evaluation_exception_preserved": True,
                            "progress_sha256": sha(progress),
                        }
                    )
                row.update(
                    source_scenario_kwargs_json=json.dumps(
                        d.get("scenario_kwargs") or {},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    source_init_kwargs_json=json.dumps(
                        d.get("init_kwargs") or {}, ensure_ascii=False, sort_keys=True
                    ),
                    original_model=config.get("model"),
                    original_provider=config.get("provider"),
                    enable_thinking_override=config.get("enable_thinking_override"),
                    parallel_tool_calls=config.get("parallel_tool_calls"),
                    reasoning_effort=config.get("reasoning_effort"),
                    max_output_tokens=config.get("max_output_tokens"),
                    temperature=config.get("temperature"),
                    max_tool_calls=d.get("limits", {}).get("max_tool_calls"),
                    timeout_seconds=d.get("limits", {}).get("timeout_seconds"),
                )
                for col in [
                    "cell_dir",
                    "fos_path",
                    "management_metrics_path",
                    "oracle_reference_path",
                ]:
                    if row.get(col):
                        row[col] = relpath(row[col], D)
                if acct:
                    row["original_operating_cost_usd"] = acct.get("production_cost")
                    row["original_net_operating_return_usd"] = acct.get(
                        "net_operating_margin"
                    )
                    for col, src in [
                        ("replayed_minus_original_cost_usd", "production_cost"),
                        ("replayed_minus_original_return_usd", "net_operating_margin"),
                    ]:
                        key = (
                            "agent_operating_cost_usd"
                            if src == "production_cost"
                            else "agent_net_operating_return_usd"
                        )
                        row[col] = (
                            numeric(row, key) - acct[src]
                            if acct.get(src) is not None
                            else ""
                        )
                rows.append(row)
            writejson(D / "progress_usage_recovery.json", recovered)
        # All metrics remain replay outputs; only original-run metadata/usage is joined.
        assert len(rows) == 34 and {r["scenario"] for r in rows} == set(IDS)
        validations = []
        baselines = []
        for row in rows:
            sid = row["scenario"]
            group, scene = SC[sid]
            row.update(
                model_condition=model,
                model_label=label,
                group_key=group["key"],
                group=group["label"],
                scenario_title=scene["title"],
                objective_family=scene["objective_family"],
            )
            assert row["status"] == "ok" and good(row["physical_replay_verified"]), (
                model,
                sid,
                row.get("error"),
            )
            for _, key, _ in SPECS:
                numeric(row, key)
            detail = json.loads((D / row["management_metrics_path"]).read_text())
            a = detail["agent"]
            refpath = D / row["oracle_reference_path"]
            ref = json.loads(refpath.read_text())
            o = ref
            assert (
                ref["task_success"]
                and a["accounts"]["prices"] == o["accounts"]["prices"]
            )
            for side, snapshot in [("agent", a), ("oracle", o)]:
                ac = snapshot["accounts"]
                cost = ac["production_cost"]
                margin = ac["net_operating_margin"]
                rr = (
                    ac.get("stored_grain_value", ac.get("grain_value", 0))
                    + ac.get("delivered_root_value", 0)
                    + ac.get("paid_subsidy", 0)
                )
                assert (
                    abs(
                        cost
                        - sum(ac["cost_components"].values())
                        - ac.get("accounting_rounding", 0)
                    )
                    < 1e-7
                )
                assert abs(margin - (rr - cost)) < 1e-7
                assert (
                    abs(numeric(row, side + "_operating_cost_usd") - cost) < 1e-7
                    and abs(numeric(row, side + "_net_operating_return_usd") - margin)
                    < 1e-7
                )
            baseline_by[(model, sid)] = {
                k: ref[k] for k in ["biological_kg", "recovered_kg"]
            }
            baseline_by[(model, sid)].update(
                {
                    k: ref["accounts"][k]
                    for k in ["production_cost", "net_operating_margin"]
                }
            )
            baselines.append(
                {
                    "scenario": sid,
                    "path": row["oracle_reference_path"],
                    "sha256": sha(refpath),
                    "context": ref["context"],
                    "task_success": True,
                }
            )
            # Enrich DeepSeek with the same original-run settings without altering values.
            rp = (
                D / row["original_report_path"]
                if row.get("original_report_path")
                else None
            )
            if rp and rp.exists():
                report = json.loads(rp.read_text())
                c = report["llm_config"]
                row.update(
                    original_report_present=True,
                    original_agent_finished=report.get("stop_reason")
                    == "agent_finished",
                    original_model=c["model"],
                    original_provider=c["provider"],
                    enable_thinking_override=c.get("enable_thinking_override"),
                    parallel_tool_calls=c.get("parallel_tool_calls"),
                    reasoning_effort=c.get("reasoning_effort"),
                    max_output_tokens=c.get("max_output_tokens"),
                    temperature=c.get("temperature"),
                    max_tool_calls=report.get("limits", {}).get("max_tool_calls"),
                    timeout_seconds=report.get("limits", {}).get("timeout_seconds"),
                    usage_source="original_run_report",
                    source_process_status="completed",
                )
            assert row["original_agent_finished"] is True
            assert row["parallel_tool_calls"] is False
            if model == "qwen_nothinking":
                assert row["enable_thinking_override"] is False
            if model == "deepseek_thinking":
                assert row["enable_thinking_override"] is True
            # Explicitly check all four percentages against the underlying ledger masses.
            for key, aa, oo, loss in [
                ("yield_loss(%)", a["biological_kg"], o["biological_kg"], True),
                ("recovered_yield_loss(%)", a["recovered_kg"], o["recovered_kg"], True),
                (
                    "relative_operating_cost_gap(%)",
                    a["accounts"]["production_cost"],
                    o["accounts"]["production_cost"],
                    False,
                ),
                (
                    "relative_net_operating_return_gap(%)",
                    a["accounts"]["net_operating_margin"],
                    o["accounts"]["net_operating_margin"],
                    False,
                ),
            ]:
                expected = 100 * (1 - aa / oo) if loss else 100 * (aa - oo) / oo
                assert abs(numeric(row, key) - expected) < 0.0050001, (model, sid, key)
            validations.append(
                {
                    "scenario": sid,
                    "source_report_present": bool(row["original_report_present"]),
                    "original_agent_finished": True,
                    "physical_replay_verified": True,
                    "oracle_valid": True,
                    "matched_prices": True,
                    "ledger_identities_verified": True,
                }
            )
        if model != "deepseek_thinking":
            writecsv(D / "summary.csv", rows)
            writejson(
                D / "oracle_baseline_catalog.json",
                {"count": 34, "baselines": baselines},
            )
        counts = {
            "rows": 34,
            "physical_replay_ok": 34,
            "finite_core_metrics": {key: 34 for _, key, _ in SPECS},
            "task_success": sum(good(r["task_success"]) for r in rows),
            "source_reports_present": sum(
                good(r["original_report_present"]) for r in rows
            ),
            "source_agent_finished": 34,
            "source_status_counts": dict(
                Counter(r["original_run_status"] for r in rows)
            ),
            "configuration_variations": {
                k: dict(Counter(str(r.get(k)) for r in rows))
                for k in [
                    "original_model",
                    "enable_thinking_override",
                    "reasoning_effort",
                    "max_tool_calls",
                    "max_output_tokens",
                    "timeout_seconds",
                ]
            },
            "summary_sha256": sha(D / "summary.csv"),
            "checks": validations,
        }
        writejson(D / "comparison_validation.json", counts)
        audit["models"][model] = counts
        for row in rows:
            r = dict(row)
            for key in PATHCOLS:
                if r.get(key) and not Path(r[key]).is_absolute():
                    r[key] = model + "/" + r[key]
            allrows.append(r)
    # Cross-model reference equality is reported, never silently assumed.
    for sid in IDS:
        vals = {m: baseline_by[(m, sid)] for m in MODELS}
        anchor = vals["deepseek_thinking"]
        diffs = {m: {k: v - anchor[k] for k, v in d.items()} for m, d in vals.items()}
        same = all(abs(v) <= 1e-7 for d in diffs.values() for v in d.values())
        audit["oracle_comparisons"].append(
            {
                "scenario": sid,
                "numeric_baselines_equal": same,
                "differences_from_deepseek": diffs,
            }
        )
    writecsv(OUT / "summary.csv", allrows)
    wide = []
    for sid in IDS:
        gr, sc = SC[sid]
        r = {
            "scenario": sid,
            "scenario_title": sc["title"],
            "group": gr["label"],
            "objective_family": sc["objective_family"],
        }
        for m in MODELS:
            ar = next(
                x for x in allrows if x["scenario"] == sid and x["model_condition"] == m
            )
            for k in [
                "task_success",
                *[x[1] for x in SPECS],
                "agent_operating_cost_usd",
                "oracle_operating_cost_usd",
                "agent_net_operating_return_usd",
                "oracle_net_operating_return_usd",
            ]:
                r[m + "__" + k] = ar[k]
        wide.append(r)
    writecsv(OUT / "comparison_wide.csv", wide)
    aggregates = []
    for m, label in MODELS.items():
        for key, name in [(g["key"], g["label"]) for g in G["groups"]] + [
            ("all_recommended34", "全部推荐 34 场")
        ]:
            rr = [
                r
                for r in allrows
                if r["model_condition"] == m
                and (key == "all_recommended34" or r["group_key"] == key)
            ]
            a = {
                "model_condition": m,
                "model_label": label,
                "group_key": key,
                "group": name,
                "n": len(rr),
                "task_success_n": sum(good(r["task_success"]) for r in rr),
            }
            a.update(
                {field: fmean(numeric(r, field) for r in rr) for _, field, _ in SPECS}
            )
            aggregates.append(a)
    writecsv(OUT / "group_summary.csv", aggregates)
    lines = [
        "# 管理拓展推荐 34 场：三模型完整结果",
        "",
        "每模型 34 场，共 102 条实际模型轨迹。DeepSeek Thinking、Qwen NoThinking、GPT-6-Luna（reasoning=medium）均使用专家级提示和单工具调用设置。原始文件按字节保留；任务失败保留在统计中。",
        "",
        "## 文件入口",
        "",
        "- `summary.csv`：102 行长表，含模型、分组、原始状态及完整回放指标。",
        "- `comparison_wide.csv`：34 行，逐场并排比较三个模型。",
        "- `group_summary.csv`：18 行，三个模型×五组及总体均值。",
        "- 各模型子目录 `summary.csv`：34 行，`metrics/summary.csv` 为回放脚本原始输出。",
        "- `runs/`：原始报告、工作流和日志；`oracle_baseline_catalog.json`：逐场实际基线。",
        "",
        "## 全部 34 场等权均值",
        "",
    ]
    head = ["Model", "N", "任务通过", *[s[0] for s in SPECS]]

    def display(ag):
        return [
            ag["model_label"],
            ag["n"],
            str(ag["task_success_n"]) + "/" + str(ag["n"]),
            *[f"{ag[k] / div:.{3 if div == 1e6 else 2}f}" for _, k, div in SPECS],
        ]

    lines += [
        table(
            head,
            [display(a) for a in aggregates if a["group_key"] == "all_recommended34"],
        ),
        "",
        "## 五类场景",
        "",
    ]
    for g in G["groups"]:
        lines += [
            "### " + g["label"],
            "",
            table(head, [display(a) for a in aggregates if a["group_key"] == g["key"]]),
            "",
        ]
    lines += [
        "## 核算与实验边界",
        "",
        "Tokens、Calls、Tools、YL、KTC、Cov.、BFCL、Core 的字段沿用 summary_20_19_18.md；增加实际 RYL、相对运营成本差额 ROCG、相对净运营收益差额 RNRG。先逐场计算，再等权平均；总计不平均五个组均值。完整公式及成本、价格和校准证据见 [Methods](<"
        + str(R / "docs/management-extensions-methods.md")
        + ">)。",
        "",
        "这些是历史不同批次的整理，工具预算、输出 token 上限和运行日期存在差别；每条 CSV 均保留实际设置，不能声称是完全相同预算下的新受控实验。Qwen 历史记录中两场在 Agent 正常结束后最终评价报错，缺 run_report；保留原错误和完整轨迹，以严格物理回放恢复产量及账目，以原 progress 的 llm_call_end.tokens 恢复 usage。未伪造原始 run_report，也未将过程错误改成原始任务通过。回放后的 task_success 单独报告。",
        "",
        "没有按产量或任务成功选择记录。Qwen 同配置的历史重复记录按创建时间选择最新；GPT 使用首批完成记录和连接故障后补跑的唯一完成记录；DeepSeek 沿用已整理的 34 场。原始配置和 SHA 见各模型 manifest 与 provenance。",
        "",
        "完整代表覆盖与指标有效，不代表所有任务通过。模型正常结束且管理失败的案例不为提高分数而重跑。所有工具回放使用既有 replay_management_metrics.py；本次模型 API 调用为 0。",
        "",
        "所有成本与净运营收益均是场景定义的已建模范围，甜菜价格及品质系数为假设，小麦／甜菜未完成中国田间校准。",
        "",
    ]
    neq = [
        v["scenario"]
        for v in audit["oracle_comparisons"]
        if not v["numeric_baselines_equal"]
    ]
    lines += [
        "跨模型数值 Oracle 基线相同："
        + str(34 - len(neq))
        + "/34；不同的场景："
        + (", ".join(neq) if neq else "无")
        + "。详见 validation.json，未通过改写指标强行统一。",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines))
    audit.update(
        total_rows=len(allrows),
        unique_model_scenario_pairs=len(
            {(r["model_condition"], r["scenario"]) for r in allrows}
        ),
        group_summary_rows=len(aggregates),
        numeric_baselines_equal_count=34 - len(neq),
        summary_sha256=sha(OUT / "summary.csv"),
        all_metrics_complete=True,
    )
    writejson(OUT / "validation.json", audit)
    source_script = Path(__file__).resolve()
    script_copy = OUT / "provenance" / source_script.name
    if source_script != script_copy.resolve():
        shutil.copy2(source_script, script_copy)
    print(
        json.dumps(
            {
                "output": str(OUT),
                "rows": len(allrows),
                "models": {
                    m: {
                        k: v[k]
                        for k in ["rows", "task_success", "source_reports_present"]
                    }
                    for m, v in audit["models"].items()
                },
                "baseline_equal": audit["numeric_baselines_equal_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
