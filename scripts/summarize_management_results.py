#!/usr/bin/env python3
"""Render recommended-management Markdown tables from an existing replay CSV.

This is a reporting step, not a replay or model runner. Metrics are read from
the CSV without recomputation; ledger identities are checked against its JSON
artifacts. No spreadsheets, model calls, or scene mutations are involved.
"""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import fmean


METRICS = [
    ("Tokens (M) ↓", "total_tokens_per_scenario", 1e6, 3),
    ("Calls ↓", "llm_calls_with_usage", 1, 1),
    ("Tools ↓", "agent_tool_calls", 1, 1),
    ("YL (%) ↓", "yield_loss(%)", 1, 2),
    ("RYL (%) ↓", "recovered_yield_loss(%)", 1, 2),
    ("KTC (%) ↑", "ktc(%)", 1, 2),
    ("Cov. (%) ↑", "coverage(%)", 1, 2),
    ("BFCL Succ. (%) ↑", "bfcl_success(%)", 1, 2),
    ("Core Path Corr. (%) ↑", "core_path_correctness(%)", 1, 2),
]
ECONOMICS = [
    ("ROCG (%) ↓", "relative_operating_cost_gap(%)", 1, 2),
    ("RNRG (%) ↑", "relative_net_operating_return_gap(%)", 1, 2),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def link(label, path):
    return f"[{label}](<{path.resolve()}>)"


def table(headers, rows):
    def line(values):
        return "| " + " | ".join(str(v).replace("|", "\\|") for v in values) + " |"
    return "\n".join([line(headers), line(["---"] * len(headers)), *map(line, rows)])


def value(row, key):
    result = float(row[key])
    if not math.isfinite(result):
        raise ValueError(f"Nonfinite {key}: {row['scenario']}")
    return result


def mean_columns(rows, specs):
    return [f"{fmean(value(r, key) for r in rows) / divisor:.{digits}f}"
            for _, key, divisor, digits in specs]


def verify_ledgers(rows, root):
    checks = []
    for row in rows:
        detail = root / row["management_metrics_path"]
        reference = root / row["oracle_reference_path"]
        agent = json.loads(detail.read_text())["agent"]
        oracle = json.loads(reference.read_text())
        if not oracle["task_success"]:
            raise ValueError(f"Invalid Oracle: {row['scenario']}")
        if agent["accounts"]["prices"] != oracle["accounts"]["prices"]:
            raise ValueError(f"Agent/Oracle price mismatch: {row['scenario']}")
        records = {}
        for name, snapshot in (("agent", agent), ("oracle", oracle)):
            account = snapshot["accounts"]
            cost = account["production_cost"]
            rounding = account.get("accounting_rounding", 0.0)
            cost_residual = cost - sum(account["cost_components"].values()) - rounding
            grain = account.get("stored_grain_value", account.get("grain_value", 0.0))
            revenue = grain + account.get("delivered_root_value", 0.0)
            subsidy = account.get("paid_subsidy", 0.0)
            margin = account["net_operating_margin"]
            margin_residual = margin - (revenue + subsidy - cost)
            if max(abs(cost_residual), abs(margin_residual)) > 1e-7:
                raise ValueError(f"Ledger identity failed: {row['scenario']} {name}")
            for column, expected in ((name + "_operating_cost_usd", cost),
                                     (name + "_net_operating_return_usd", margin)):
                if abs(value(row, column) - expected) > 1e-7:
                    raise ValueError(f"CSV/ledger mismatch: {row['scenario']} {column}")
            records[name] = {
                "price_book_id": account.get("price_book_id"),
                "production_cost": cost, "cost_components": account["cost_components"],
                "accounting_rounding": rounding, "crop_value": revenue,
                "paid_subsidy": subsidy, "net_operating_margin": margin,
                "cost_identity_residual": cost_residual,
                "return_identity_residual": margin_residual,
            }
        checks.append({"scenario": row["scenario"], "matched_prices": True,
                       "detail": str(detail.resolve()), "detail_sha256": sha(detail),
                       "oracle": str(reference.resolve()), "oracle_sha256": sha(reference),
                       **records})
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--groups", type=Path, default=Path(
        "fairy/scenarios/management_extensions/SCENARIO_GROUPS.json"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--label", default="DeepSeek Thinking")
    args = parser.parse_args()
    source = args.summary.resolve()
    out = (args.out or source.with_suffix(".md")).resolve()
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    grouping = json.loads(args.groups.read_text())
    by_id = {r["scenario"]: r for r in rows}
    expected = set(grouping["recommended_scenario_ids"])
    if len(by_id) != len(rows) or set(by_id) != expected:
        raise ValueError("Require exactly one row per recommended scenario; no silent exclusions")
    for row in rows:
        if row["status"] != "ok" or row["physical_replay_verified"].lower() != "true":
            raise ValueError(f"Unverified replay: {row['scenario']}")
        if row["original_run_status"] != "completed":
            raise ValueError(f"Incomplete model run: {row['scenario']}")
        for _, key, _, _ in METRICS + ECONOMICS:
            value(row, key)
        if value(row, "oracle_net_operating_return_usd") <= 0:
            raise ValueError("Positive Oracle margin required for the ↑ interpretation")
    checks = verify_ledgers(rows, source.parent)
    repo = Path(__file__).resolve().parents[1]
    methods = repo / "docs/management-extensions-methods.md"
    passed = sum(r["original_task_success"].lower() == "true" for r in rows)
    lines = [f"# {args.label}：管理拓展推荐 {len(rows)} 场汇总", "",
             f"{len(rows)} 场实际模型记录，任务通过 {passed}/{len(rows)}；物理回放 {len(rows)}/{len(rows)} 成功。"
             "这是既有历史批次的整理，不是重新调用模型的统一新实验。", "",
             "数据：" + link("回放 summary.csv", source) + "；方法：" + link("指标、经济核算及 WOFOST 参数证据", methods) + "。", "",
             "## 统计口径", "",
             "沿用 `summary_20_19_18.md` 的字段：Tokens 为每场总 token 的百万值，Calls 为 `llm_calls_with_usage`，"
             "Tools 为 `agent_tool_calls`；YL、KTC、Cov.、BFCL Succ.、Core Path Corr. 分别为 "
             "`yield_loss(%)`、`ktc(%)`、`coverage(%)`、`bfcl_success(%)`、`core_path_correctness(%)`。"
             "新增 RYL=`recovered_yield_loss(%)`，不使用成熟未收获保底的 v2 列。", "",
             "各指标先逐场取值，再在指定场景集合内等权平均；总计按所有场景等权，"
             "不对五个组均值再等权。平均的是 CSV 已导出的数值。任务失败但完成且回放有效的记录仍进入均值。"
             "本批只有一个模型／提示条件，没有可比基准，因此 Δ Tokens 记为不适用，不伪造节省率。", "",
             "KTC 和 Core 使用 v1；Cov. 使用数值容差比例为 2 的 v2。该组合是原表兼容口径，"
             "不是统一的 v2。BFCL 是本仓库的调用签名匹配分，不是官方榜单成绩。"
             "流程表示差异可能使 Oracle 自回放分数小于 100；见方法文档。", "",
             "## 分类均值", ""]
    aggregate = []
    for group in grouping["groups"]:
        selected = [by_id[s["id"]] for s in group["scenarios"]]
        success = sum(r["original_task_success"].lower() == "true" for r in selected)
        aggregate.append([group["label"], len(selected), f"{success}/{len(selected)}",
                          *mean_columns(selected, METRICS)])
    aggregate.append(["全部推荐场景", len(rows), f"{passed}/{len(rows)}", *mean_columns(rows, METRICS)])
    lines += [table(["类别", "N", "任务通过", *[s[0] for s in METRICS]], aggregate), "",
              "## 经营决策的成本与收益", "",
              "ROCG=100×(Agent 成本−Oracle 成本)/Oracle 成本；"
              "RNRG=100×(Agent 净运营收益−Oracle 净运营收益)/Oracle 净运营收益。"
              "这里的收益是已建模投入扣除后的收益，不是完整净利润。"
              "成本降低须结合 YL、RYL 和任务约束解释，不能把漏种、少收造成的低成本当成改进。", ""]
    econ_groups = []
    econ_scenes = []
    for group in grouping["groups"]:
        selected_scenes = [s for s in group["scenarios"] if s["objective_family"] in
                           {"net_operating_return", "yield_constrained_cost"}]
        if not selected_scenes:
            continue
        selected = [by_id[s["id"]] for s in selected_scenes]
        econ_groups.append([group["label"] + ("（仅高水价）" if group["key"] == "l3_sugarbeet" else ""),
                            len(selected), *mean_columns(selected, ECONOMICS)])
        econ_scenes.extend((group, s) for s in selected_scenes)
    if len(econ_scenes) != 26:
        raise ValueError("Expected the frozen 26-scene economic-objective reporting subset")
    lines += [table(["经营目标子集", "N", *[s[0] for s in ECONOMICS]], econ_groups), "",
              "上述四行互斥，共 26 场：22 场净运营收益目标、4 场产量约束下成本控制。"
              "两类 L3／L4 经营决策共 15 场；另补充 10 场小麦和 1 场甜菜高水价。"
              "其余 8 场经济值仍保留在 CSV，但不把它们的产量目标改称利润目标。", "",
              "下表为每个 episode 的 USD 总额，L4 为整个任务期累计，未年化、未贴现。"
              "场景面积与季数不同，不用这些绝对数跨场景比较单位面积效率。", ""]
    econ_details = []
    for group, scene in econ_scenes:
        row = by_id[scene["id"]]
        econ_details.append([scene["id"],
                             *[f"{value(row,k):.2f}" for k in ["agent_operating_cost_usd", "oracle_operating_cost_usd",
                                "agent_net_operating_return_usd", "oracle_net_operating_return_usd"]],
                             *mean_columns([row], ECONOMICS)])
    lines += [table(["场景 ID", "C_A (USD)", "C_O (USD)", "N_A (USD)", "N_O (USD)",
                     *[s[0] for s in ECONOMICS]], econ_details), "", "## 逐场指标", ""]
    for group in grouping["groups"]:
        lines += ["### " + group["label"], ""]
        details = []
        for scene in group["scenarios"]:
            row = by_id[scene["id"]]
            label = link(scene["title"], source.parent / row["original_report_path"])
            details.append([label, "通过" if row["original_task_success"].lower() == "true" else "未通过",
                            *mean_columns([row], METRICS)])
        lines += [table(["场景", "任务", *[s[0] for s in METRICS]], details), ""]
    lines += ["## 可复核性与适用范围", "",
              "- 原始工作流、报告及日志保留在 `runs/`，本步骤仅读 CSV 和回放 JSON；没有调用模型或重新模拟作物。",
              "- 三个历史来源批次的配置及来源见根目录 `manifest.json`；小麦 10 场均启用 `late_harvest=true`。",
              "- 分作物、分季产量见 `metrics/management_yields_by_crop.csv` 和 `metrics/management_yields_by_season.csv`。",
              "- 跨作物质量汇总只作旧表兼容，不能解释为等价值或等营养产出。",
              f"- 原始 {passed} 通过／{len(rows)-passed} 未通过与回放成功是不同判断；不删除失败样本提升成绩。",
              "- 科学证据边界：当前原生小麦／甜菜没有中国田间数据校准；甜菜价格和品质系数仍是显式假设。", "",
              f"源 CSV SHA-256：`{sha(source)}`。", "",
              "生成脚本：" + link("summarize_management_results.py", Path(__file__)) + "。", ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    audit = {"schema": "fairy.management-methods-report-audit.v1", "source": str(source),
             "source_sha256": sha(source), "groups_sha256": sha(args.groups),
             "row_count": len(rows), "task_success_count": passed,
             "aggregation": "macro_mean_of_exported_per_scenario_values",
             "metrics": METRICS + ECONOMICS, "new_model_calls": 0,
             "ledger_checks": checks, "markdown": str(out), "markdown_sha256": sha(out)}
    audit_path = out.with_name(out.stem + "_audit.json")
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {out}; checked {len(rows)} rows and {2*len(rows)} accounting snapshots")


if __name__ == "__main__":
    main()
