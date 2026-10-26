"""Summarize actual native Oracle results and distinguish failure from review flags.

This reads existing evidence only. No scenario or crop state is changed, and no
agronomic threshold is inferred from an event's name alone.
"""

from __future__ import annotations
import argparse
from collections import Counter
import csv
import json
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path


def load(path):
    return json.loads(path.read_text())


def error_kind(message):
    text = str(message).lower()
    if "explicit cultivar" in text:
        return "native_cultivar_parameters_missing"
    if "rotations/replanting" in text or "new native season" in text:
        return "native_replanting_unsupported"
    if "out of range" in text and ("parameter" in text or "notinf" in text):
        return "native_parameter_mapping_invalid"
    if "not mature" in text:
        return "harvest_before_maturity"
    if "moisture too high" in text:
        return "harvest_above_moisture_limit"
    if "grain bin is already empty" in text:
        return "unload_without_harvested_grain"
    if "rain" in text or "weather" in text or "wind" in text:
        return "weather_gate_rejected"
    if "battery" in text:
        return "battery_gate_rejected"
    if "fuel" in text:
        return "fuel_gate_rejected"
    if "quota" in text or "budget" in text or "limit" in text:
        return "management_limit_rejected"
    if "stock" in text or "insufficient" in text or "hopper" in text or "tank" in text:
        return "material_or_machine_payload_rejected"
    if "vwc" in text or "traffic" in text:
        return "soil_gate_rejected"
    return "other_tool_or_runtime_error"


def mechanism_coverage(plan, flags):
    """Map declared scenario mechanisms to the verified native implementation.

    This is a capability review, independent of whether the original workflow
    happened to harvest. Flags use explicit ScenarioSpec histories/actions or
    the preserved original migration review, never a tool-success shortcut.
    """
    spec = plan.get("declared_spec") or {}
    rows = []

    def add(key, status, meaning, basis, proof):
        rows.append(
            {
                "mechanism": key,
                "status": status,
                "meaning": meaning,
                "declared_basis": basis,
                "model_contract_reference": proof,
            }
        )

    add(
        "native_carbon_water_nitrogen_phenology",
        "implemented_uncalibrated",
        "Wofost81_NWLP_CWB_CNB计算碳、水、N与物候；不等于任何场景特定损伤机制已被实现或田间校准。",
        {"scenario_source": plan.get("source_path"), "formal_soybean_scene": True},
        "native_model",
    )
    history = spec.get("prior_histories", [])
    custom = spec.get("custom_histories", [])
    if "named_native_cultivar_parameters_needed_beyond_complete_heinong84" in flags:
        add(
            "original_named_cultivar_parameters",
            "missing_in_original_selected_config",
            "原配置仅完整HN84；后续新增四个参考品种不是本例旧品种缺参问题的替代证据。",
            {
                "primary_seed": spec.get("primary_seed"),
                "planting_zones": spec.get("planting_zones"),
            },
            "cultivar_guard",
        )
    if "density_currently_scales_initial_tdwi_only" in flags:
        add(
            "density_and_canopy_geometry",
            "partial_tdwi_initialization_only",
            "密度只缩放初始TDWI；没有逐株竞争、行距冠层几何或密度特异病害因果参数。",
            {
                "density_target_plants_m2": spec.get("density_target_plants_m2"),
                "planting_zones": spec.get("planting_zones"),
            },
            "density",
        )
    if "current_native_adapter_rejects_second_planting" in flags:
        add(
            "replanting",
            "unsupported_native_season_restart",
            "已有原生季后再次播种需要新原生季；工具即使因stand足够而无操作返回也不能证明补种机制有效。",
            {
                "actions": [
                    a for a in spec.get("actions", []) if a.get("kind") == "replant"
                ]
            },
            "replant",
        )
    if "legacy_cold_wet_stand_loss_not_equivalent_in_native_branch" in flags:
        add(
            "cold_wet_stand_mortality",
            "partial_temperature_window_no_legacy_postplant_mortality",
            "播前温度/水分窗口和原生温度物候存在；旧冷湿后播缺苗损失钩子位于legacy分支，不能声称原生已验证冷湿死苗/补苗收益。",
            {
                "description": spec.get("description"),
                "custom_histories": custom,
                "prior_histories": history,
            },
            "cold_stand",
        )
    if "legacy_drainage_rates_not_direct_native_cwb_parameters" in flags:
        add(
            "declared_soil_hydraulic_modifiers",
            "partial_native_cwb_parameter_mapping",
            "根深/田持/饱和/入渗映射到CWB；旧top/root drainage_rate并非CWB同名过程，需逐修饰量核对。NOTINF范围错误另按实际阻断记录。",
            {"hydraulic_modifiers": spec.get("hydraulic_modifiers")},
            "soil",
        )
    if (
        "prior_history_effects_need_native_parameter_or_retained_coupling_review"
        in flags
    ):
        add(
            "prior_management_history",
            "mixed_auxiliary_and_native_semantics_require_review",
            "历史可改变辅助初态/经验病虫草压力；单一legacy nutrient_index_delta不是原生N池/固氮参数，不等于相同历史因果效应。",
            {"prior_histories": history, "custom_histories": custom},
            "nutrient_projection",
        )
    custom_names = [
        item[0].get("name", "")
        for item in custom
        if isinstance(item, list) and isinstance(item[0], dict)
    ]
    if any("micronutrient" in name or "potassium" in name for name in custom_names):
        add(
            "non_nitrogen_element_deficiency",
            "unsupported_element_specific_native_mechanism",
            "声明缺K/微量元素，但NWLP_CWB_CNB及桥接动作只维护N供给；nutrient_index proxy不提供K/微量元素池、胁迫或施用反应。该例即使收完也未证明元素特定因果。",
            {"custom_histories": custom, "description": spec.get("description")},
            "native_model_and_n_input",
        )
    if any("nodulation" in name for name in custom_names):
        add(
            "rhizobia_nodulation_failure",
            "unsupported_spatial_nfix_mechanism",
            "声明根瘤失败只写legacy营养proxy；未将目标区映射到NFIX_FR等原生固氮参数，不能把N追肥工具可用当作根瘤失败机制已实现。",
            {"custom_histories": custom, "description": spec.get("description")},
            "nfix",
        )
    if any("residue" in str(item).lower() for item in history + custom):
        add(
            "residue_carbon_nitrogen_cycling",
            "unsupported_soc_and_residue_n_partial_auxiliary_seedbed",
            "残茬辅助土温/初态历史可存在；原生桥明确没有残茬碳库/残茬N矿化。incorporation审计记录不能证明残茬C/N收益。",
            {"prior_histories": history, "custom_histories": custom},
            "residue",
        )
    intent = str(spec.get("description", "")) + " " + str(spec.get("zones", []))
    if "叶面积损伤" in intent or "leaf_feeder" in intent or "虫食" in intent:
        add(
            "leaf_feeder_defoliation",
            "empirical_pgass_only_no_direct_native_lai_loss",
            "虫害通过经验压力缩放原生PGASS；没有单独直接删除原生LAI/叶干物质的食叶损伤过程。可验证压力/产量代理，不能宣称验证真实食叶LAI损伤恢复。",
            {"description": spec.get("description"), "zones": spec.get("zones")},
            "biotic",
        )
    if "legacy_seed_growth_overrides_do_not_override_native_crop_parameters" in flags:
        add(
            "legacy_seed_growth_override",
            "unsupported_as_native_crop_parameter_override",
            "旧grow倍率不等于原生品种参数；必须用显式原生品种profile并另列校准边界。",
            {"seed_growth_overrides": spec.get("seed_growth_overrides")},
            "cultivar_guard",
        )
    return rows


def inspect_case(directory, plan, capability_flags=None):
    sid = directory.name
    summary = load(directory / "summary.json")
    path = directory / "runtime_log.jsonl"
    trace = (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )
    findings = []
    actions = []
    native_config = summary.get("crop_backend_provenance", {}).get("config", {})
    declared = []
    spec = plan.get("declared_spec") or {}
    for window in ("emergence", "r1", "mid", "r5"):
        for index, action in enumerate(
            item for item in spec.get("actions", []) if item["window"] == window
        ):
            prefix = (
                f"o_{window}_{action['kind']}_{index}_{action['start']}_{action['end']}"
            )
            declared.append((prefix, action))

    def finding(kind, record=None, **details):
        findings.append(
            {
                "kind": kind,
                "step": record.get("step_name") if record else None,
                "tool": record.get("tool_name") if record else None,
                **details,
            }
        )

    exception = summary.get("replay_exception") or {}
    message = exception.get("message") or summary.get("setup_exception")
    model_block = None
    if message:
        kind = error_kind(message)
        if kind.startswith("native_"):
            model_block = kind
        finding(kind, message=message)
    if "worker_exit" in summary:
        finding("audit_worker_failed", worker_exit=summary["worker_exit"])
    statuses = Counter()
    coverage = 0
    confidence = 0
    for record in trace:
        tool = record["tool_name"]
        method = tool.rsplit("__", 1)[-1]
        result = record.get("content")
        before = record.get("audit_before") or {}
        args = record.get("tool_args") or {}
        if isinstance(result, dict):
            statuses[str(result.get("status", "no_status"))] += 1
            if result.get("error"):
                finding(
                    error_kind(result["error"]),
                    record,
                    message=result["error"],
                    arguments=args,
                    stage_counts=before.get("stage_counts"),
                    native_dvs_range=before.get("native_dvs_range"),
                    weather=before.get("weather"),
                )
            if result.get("status") == "partial":
                finding(
                    "tool_partial_completion", record, arguments=args, response=result
                )
            if result.get("warning"):
                finding("tool_warning", record, warning=result["warning"])
            covered = result.get("covered_ridges", result.get("surveyed_ridges"))
            requested = before.get("target_ridges")
            if isinstance(covered, list) and requested:
                missing = sorted(set(requested) - set(covered))
                if missing:
                    coverage += 1
                    finding(
                        "requested_observation_coverage_incomplete",
                        record,
                        requested_ridges=requested,
                        covered_ridges=covered,
                        missing_ridges=missing,
                        status=result.get("status"),
                    )
            observations = result.get("observations")
            if isinstance(observations, dict):
                zero = []
                for rid, item in observations.items():
                    if not isinstance(item, dict):
                        continue
                    values = [
                        float(value)
                        for key, value in item.items()
                        if key.endswith("_confidence") or key == "confidence"
                    ]
                    if values and max(values) == 0:
                        zero.append(int(rid))
                if zero:
                    confidence += 1
                    finding(
                        "observation_rows_without_positive_confidence",
                        record,
                        ridge_ids=zero,
                    )
        if method in {
            "base_fertilize",
            "apply_fertilizer",
            "apply_fertigation",
            "apply_fungicide",
            "spray_pesticide",
            "apply_herbicide",
            "mechanical_weed_control",
            "replant_seeds",
            "irrigate",
            "irrigate_range",
            "irrigate_single_ridge",
            "harvest",
            "plant_seeds",
        }:
            row = {
                "step": record.get("step_name"),
                "tool": tool,
                "arguments": args,
                "sim_timestamp_before": record.get("sim_timestamp_before"),
                "sim_timestamp_after": record.get("sim_timestamp_after"),
                "stage_counts": before.get("stage_counts"),
                "native_dvs_range": before.get("native_dvs_range"),
                "root_vwc_range": before.get("root_vwc_range"),
                "weather": before.get("weather"),
                "inventory_before": before.get("inventory"),
                "management_regime_before": before.get("management_regime"),
                "actual_response": result,
            }
            row["declared_action"] = next(
                (
                    action
                    for prefix, action in declared
                    if str(record.get("step_name") or "").startswith(prefix)
                ),
                None,
            )
            declaration = row["declared_action"]
            stages = list(before.get("stage_counts") or {})
            if declaration and declaration.get("kind") != "replant":
                window = declaration.get("window")
                expected = {"r1": ("R1", "R2"), "r5": ("R5", "R6")}.get(window)
                if (
                    expected
                    and stages
                    and any(not stage.startswith(expected) for stage in stages)
                ):
                    finding(
                        "declared_phase_differs_from_actual_native_stage",
                        record,
                        declared_window=window,
                        actual_stage_counts=before.get("stage_counts"),
                        native_dvs_range=before.get("native_dvs_range"),
                        arguments=args,
                        interpretation="Observed phase alignment differs; application may still be agronomically reasonable earlier/later. Needs management review, not automatically an illegal action.",
                    )
            if (
                method == "apply_fertigation"
                and isinstance(result, dict)
                and result.get("fertilizer_kg_used") is not None
            ):
                kg = float(result["fertilizer_kg_used"])
                area = float(
                    summary.get("metrics", {}).get("ridge_area_m2", 268 * 1.1)
                ) * (int(args["end_ridge"]) - int(args["start_ridge"]) + 1)
                row["actual_product_kg_per_ha"] = kg / area * 10000
                row["native_gross_n_kg_per_ha"] = row[
                    "actual_product_kg_per_ha"
                ] * float(native_config.get("fertilizer_n_fraction", 0.46))
                row["native_recovered_n_kg_per_ha"] = row[
                    "native_gross_n_kg_per_ha"
                ] * float(native_config.get("fertilizer_n_recovery", 0.7))
                row["n_conversion_note"] = (
                    "Resolved native config and ridge area from this run provenance; product mass from the actual tool receipt."
                )
            actions.append(row)
    status_rows = [
        record
        for record in trace
        if record["tool_name"].endswith("__get_status")
        and isinstance(record.get("content"), dict)
    ]
    if status_rows and float(status_rows[0]["content"].get("fuel_tank_l", 0)) > 100:
        finding(
            "initial_tractor_fuel_above_declared_100_l_tank",
            status_rows[0],
            fuel_liters=status_rows[0]["content"]["fuel_tank_l"],
        )
    findings_count = Counter(row["kind"] for row in findings)
    mechanism_rows = mechanism_coverage(plan, list(capability_flags or []))
    mechanism_gaps = [
        item["mechanism"]
        for item in mechanism_rows
        if item["status"].startswith("unsupported")
    ]
    partial_mechanisms = [
        item["mechanism"]
        for item in mechanism_rows
        if item["status"].startswith(("partial", "mixed"))
    ]
    mechanism_status = (
        "known_unsupported_declared_mechanism"
        if mechanism_gaps
        else (
            "partial_mapping_requires_review"
            if partial_mechanisms
            else "uncalibrated_reference_not_scenario_causally_validated"
        )
    )
    row = {
        "scenario_id": sid,
        "structure": plan.get("kind"),
        "model_block": model_block,
        "capability_review_flags": list(capability_flags or []),
        "mechanism_coverage": mechanism_rows,
        "original_intended_mechanism_status": mechanism_status,
        "known_unsupported_mechanisms": mechanism_gaps,
        "partial_mechanisms_requiring_review": partial_mechanisms,
        "strict_success": bool(summary.get("strict_success")),
        "strict_checks": summary.get("strict_checks", {}),
        "raw_workflow_sha256": summary.get("canonical_workflow_sha256"),
        "scenario_source_sha256": summary.get("scenario_source_sha256"),
        "source_path": summary.get("scenario_source_path"),
        "evidence_directory": str(directory),
        "actual_tool_calls": len(trace),
        "native_engines": summary.get("counts", {}).get("native_engines"),
        "harvested_ridges": summary.get("counts", {}).get("harvested"),
        "stored_ridges": summary.get("counts", {}).get("safely_stored_ridges"),
        "actual_tool_errors": sum(record.get("status") != "ok" for record in trace),
        "incomplete_observation_calls": coverage,
        "zero_confidence_observation_calls": confidence,
        "finding_counts": dict(findings_count),
        "findings": findings,
        "management_actions": actions,
    }
    return row


def write_markdown(root, report):
    names = {
        "native_cultivar_parameters_missing": "原配置缺少该品种的显式参数",
        "native_replanting_unsupported": "原生后端拒绝再次播种",
        "native_parameter_mapping_invalid": "原土壤映射生成非法 NOTINF 参数",
        "harvest_before_maturity": "未成熟即收割",
        "harvest_above_moisture_limit": "籽粒水分超过机收限制",
        "unload_without_harvested_grain": "收割失败后继续空仓卸粮",
        "requested_observation_coverage_incomplete": "请求范围未完整观察",
        "observation_rows_without_positive_confidence": "部分观察行没有正置信度",
        "initial_tractor_fuel_above_declared_100_l_tank": "初始油量超过100 L油箱声明",
        "material_or_machine_payload_rejected": "库存或机器载荷拒绝",
        "soil_gate_rejected": "土壤作业门槛拒绝",
        "tool_partial_completion": "工具部分完成",
        "tool_warning": "工具返回警告",
        "declared_phase_differs_from_actual_native_stage": "声明窗口与实际原生阶段不一致（需农艺审核）",
        "other_tool_or_runtime_error": "其他工具/运行错误",
    }

    def cell(v):
        return str(v).replace("|", r"\|").replace("\n", " ")

    def status(r):
        return (
            names.get(r["model_block"])
            if r["model_block"]
            else (
                "原严格完成检查通过；仍需管理审核"
                if r["strict_success"]
                else "原流程完成检查失败；需按实际观测修订"
            )
        )

    lines = [
        "# 原始90场景 WOFOST Oracle 逐例审计",
        "",
        "这是原分支 `5d6bda7` 加原 stash `a25682a` 的冻结原始代码实际运行。没有将后续物理修复、新品种参考参数或修订 Oracle 的结果混入这90例。",
        "",
        f"90例全部有原始工作流、逐工具运行记录、日记录文件和最终快照。遇到模型阻断时按真实错误停止，不冒充已经跑完整季。原严格完成检查通过 {report['strict_success_count']} 例；24例被原配置品种参数缺失阻断，1例被再次播种限制阻断，1例生成非法原生土壤参数，其余54例原流程完成检查失败。",
        "",
        "静态声明有25例涉及HN84以外的旧品种，但实际只有24例触发缺参阻断：wet_june_ab_zoned_disease换种时种斗未清空，HEINONG60装种被拒，后续仍误用残余HN84并有24垄未播，遮蔽了缺参问题。该例必须先修正物料切换和失败响应处理，不能把25与24混为漏审。",
        "",
        "严格完成通过也不等于农艺合理、观察完整或最高产。继承的 validate() 返回 None 可能显示 success，所以以下只使用额外的播种、R8、收割、安全入库、无工具错误检查。",
        "",
        "不能把工具失败数当作独立根因：一次未成熟收割会跟随一次空仓卸粮；同一模型异常可能同时出现在工具响应和终止摘要。JSON同时提供 finding_event_counts 与 scenarios_with_finding_counts。",
        "",
        "## 核验文件",
        "",
        "- `manifest.json`：90个ID、冻结源码哈希、原配置、解释器和固定墙钟。",
        "- `original_management_audit.json`：每ID源码/工作流哈希、全部问题、每次管理操作的参数/实际原生阶段/DVS/天气/资源/工具回执。",
        "- `original_management_audit.csv`：完整90行矩阵。",
        "- `native_mechanism_contract.json`：模型定义/桥接/分支的源码定位与SHA256；每ID机制覆盖结果独立于工具完成检查。",
        "- `cases/<ID>.md`：每例可读管理清单与修订方向。",
        "- `baseline/<ID>/canonical_workflow.json`、`runtime_log.jsonl`、`daily.csv`、`summary.json`、`final_state.json`：不可替代的原始证据。",
        "",
        "## 逐例结果",
        "",
        "| ID | 原始结果 | 实际工具调用 | 收割/64 | 错误/异常记录 | 观察缺覆盖调用 | 修订/能力边界 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for r in report["rows"]:
        sid = r["scenario_id"]
        finds = r["finding_counts"]
        notes = []
        if finds.get("harvest_before_maturity"):
            notes.append("收割改为逐区公开R8门控")
        if finds.get("harvest_above_moisture_limit"):
            notes.append("收割改为公开籽粒水分/天气门控")
        if r["incomplete_observation_calls"]:
            notes.append("机器人按真实4垄能力拆分并验覆盖")
        if r["model_block"]:
            notes.insert(0, "先处理显式模型能力阻断")
        notes.append("剂量/必要性仍待因果删减试验")
        lines.append(
            f"| [{sid}](cases/{sid}.md) | {status(r)} | {r['actual_tool_calls']} | {r['harvested_ridges']} | {r['actual_tool_errors']} | {r['incomplete_observation_calls']} | {'；'.join(notes)} |"
        )
        case = [
            "# " + sid,
            "",
            status(r),
            "",
            f"原始工作流 SHA256：`{r['raw_workflow_sha256']}`",
            "",
            f"场景源码 SHA256：`{r['scenario_source_sha256']}`",
            "",
            "原始回放保持原来的时间、库存与物理实现。模型差异和缺失不自动归咎于 Oracle。",
            "",
            "## 完成检查",
            "",
            "```json",
            json.dumps(r["strict_checks"], ensure_ascii=False, indent=2),
            "```",
            "",
            "## 已证实的问题",
            "",
        ]
        case += [f"- {names.get(k,k)}：{v}条证据记录。" for k, v in finds.items()]
        case += ["", "## 静态机制审核标记", ""]
        case += ["- " + flag for flag in r["capability_review_flags"]]
        case += ["", "## 声明机制在原生后端中的覆盖", ""]
        case += [
            f"- **{item['mechanism']}** — `{item['status']}`：{item['meaning']} 证据合同：{item['model_contract_reference']}；声明依据：`{json.dumps(item['declared_basis'],ensure_ascii=False)}`。"
            for item in r["mechanism_coverage"]
        ]
        case += [
            "",
            "静态标记表示必须检查该机制在原生模型中的语义，不能用它声称此例已经运行失败。原配置缺少品种参数与后来增加的工程参考品种参数分开记录。",
            "",
            "## 每次实际管理操作",
            "",
            "| 步骤 | 北京时间操作前 | 参数 | 实际阶段 / DVS | 土壤根区VWC | 天气 | 实际回执 |",
            "|---|---|---|---|---|---|---|",
        ]
        for a in r["management_actions"]:
            ts = a.get("sim_timestamp_before")
            clock = (
                datetime.fromtimestamp(ts, ZoneInfo("Asia/Shanghai")).isoformat()
                if ts
                else ""
            )
            stage = str(a.get("stage_counts")) + " / " + str(a.get("native_dvs_range"))
            response = a.get("actual_response")
            response = (
                {
                    k: v
                    for k, v in response.items()
                    if k
                    in {
                        "status",
                        "error",
                        "warning",
                        "fertilizer_kg_used",
                        "pesticide_liters_used",
                        "liters_used",
                        "water_mm",
                        "hours",
                        "harvested_kg",
                        "grain_kg",
                        "total_kg",
                        "seed_type",
                        "planted_ridges",
                        "treated_ridges",
                        "irrigated_ridges",
                    }
                }
                if isinstance(response, dict)
                else response
            )
            case.append(
                "| "
                + " | ".join(
                    cell(x)
                    for x in [
                        a["step"],
                        clock,
                        json.dumps(a["arguments"], ensure_ascii=False),
                        stage,
                        a.get("root_vwc_range"),
                        json.dumps(a.get("weather"), ensure_ascii=False),
                        json.dumps(response, ensure_ascii=False),
                    ]
                )
                + " |"
            )
        case += ["", "施肥产品量与N量换算："]
        case += [
            f"- {a['step']}：产品 {a['actual_product_kg_per_ha']:.3f} kg/ha，总N {a['native_gross_n_kg_per_ha']:.3f} kg N/ha，回收N {a['native_recovered_n_kg_per_ha']:.3f} kg N/ha。仅核对单位，尚未证明必要/冗余。"
            for a in r["management_actions"]
            if a.get("actual_product_kg_per_ha") is not None
        ]
        case += ["", "## 修订方向和不能宣称的结论", ""]
        case += ["- " + note + "。" for note in notes]
        case += [
            "- 每次病虫草诊断应读取实际覆盖和置信度；不能把 status=ok 当作全田已观察。",
            "- 施药、施肥、灌溉需用实际观察确定分区、阶段、资源和作业窗口。原流程的剂量原样记录，尚未逐项证明必要性。",
            "- 不能读取未来天气或隐藏原生DVS决定管理；审计DVS只用于事后核验。",
            "- 原生补种、非N营养/结瘤、低温缺苗、前茬和密度等机制若仍未对应，必须标注能力限制，不能换通用品种或改天气来制造通过。",
            "- 原始证据：" + str(Path("../baseline") / sid) + "。",
            "",
        ]
        destination = root / "cases" / f"{sid}.md"
        destination.parent.mkdir(exist_ok=True)
        destination.write_text("\n".join(case) + "\n")
    lines += [
        "",
        "## 参数和冗余审查的界限",
        "",
        "管理动作逐条保留原始参数和实际生效阶段。名称含“R1”“轻量”不自动说明时机/剂量正确或错误。例如普通HN84原流程的R1水肥实际在DVS1.1218/R1执行，时机并非一概错误；但0.24 kg/垄对应约244.233 kg产品/ha（112.347 kg N/ha总N，78.643 kg N/ha回收N），必须显式检查单位和必要性。",
        "",
        "确认某项冗余至少需要相同初态、相同天气、相同其余绝对操作时刻的实际动作删减对照，并同时比较最终生物量、实收、安全入库、成熟/收割时间及资源。当前90例原始审计没有这项证据，所以不宣称“已经找齐所有冗余操作”或“最高产Oracle”。",
        "",
        "后续公开观测编译器导出原始/修订工作流、公开工具决策轨迹及新场景完整回放哈希。其通过只证明操作可行和回放一致，不能替代上述农艺因果检查。",
        "",
    ]
    (root / "REPORT.md").write_text("\n".join(lines))


def write_mechanism_contract(root, original_source, current_source=None):
    refs = {
        "native_model": [("fairy/physics/wofost_backend.py", "_MODEL =")],
        "cultivar_guard": [
            ("fairy/physics/wofost_backend.py", "def _variety_for_seed"),
            ("fairy/physics/wofost_backend.py", "require_explicit_cultivar_parameters"),
        ],
        "density": [("fairy/physics/wofost_backend.py", 'crop["TDWI"] *=')],
        "replant": [
            ("fairy/physics/wofost_backend.py", "rotations/replanting"),
            ("fairy/physics/wofost_backend.py", "Replanting and rotation"),
        ],
        "cold_stand": [
            (
                "fairy/apps/farm_world/physics_orchestrator.py",
                "_apply_post_planting_cold_stand_penalty(physics, weather)",
            )
        ],
        "soil": [
            ("fairy/physics/wofost_backend.py", 'soil = {"SMW"'),
            ("fairy/physics/wofost_backend.py", "NOTINF=1 -"),
        ],
        "nutrient_projection": [
            ("fairy/physics/wofost_backend.py", "management.nutrient_index =")
        ],
        "native_model_and_n_input": [
            ("fairy/physics/wofost_backend.py", "_MODEL ="),
            ("fairy/physics/wofost_backend.py", 'delta["n_kg_ha"]'),
        ],
        "nfix": [
            ("fairy/physics/wofost_backend.py", "def queue_actions"),
            (
                "fairy/physics/data/wofost/profiles/heilongjiang_heinong84_complete_v1.json",
                '"NFIX_FR"',
            ),
        ],
        "residue": [
            (
                "fairy/physics/wofost_backend.py",
                "Residue incorporation is an audit action",
            ),
            ("fairy/physics/wofost_backend.py", "def queue_actions"),
        ],
        "biotic": [
            (
                "fairy/physics/wofost_backend.py",
                "return super().__call__(day, drv) * self.external_factor",
            ),
            ("fairy/physics/wofost_backend.py", "PGASS_BEFORE_BIOTICS"),
            (
                "fairy/physics/wofost_backend.py",
                "Biotic treatment has no separate direct native LAI deletion",
            ),
        ],
    }
    sources = {"frozen_original": Path(original_source)}
    if current_source:
        sources["current_restored"] = current_source
    result = {
        "scope": "Verified model-definition source references, independent of workflow completion. Missing patterns are recorded, never treated as positive evidence.",
        "source_roots": {k: str(v) for k, v in sources.items()},
        "groups": {},
    }
    for group, pairs in refs.items():
        result["groups"][group] = {}
        for label, source in sources.items():
            records = []
            for file, needle in pairs:
                p = source / file
                if not p.exists():
                    records.append({"path": file, "search": needle, "missing": True})
                    continue
                lines = p.read_text().splitlines()
                matches = [i for i, line in enumerate(lines) if needle in line]
                for i in matches[:3]:
                    context = 65 if group == "cold_stand" else 8
                    records.append(
                        {
                            "path": file,
                            "line": i + 1,
                            "file_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                            "search": needle,
                            "excerpt_start_line": max(1, i - context + 1),
                            "excerpt": "\n".join(
                                lines[max(0, i - context) : min(len(lines), i + 10)]
                            ),
                        }
                    )
                if not matches:
                    records.append(
                        {"path": file, "search": needle, "pattern_not_found": True}
                    )
            result["groups"][group][label] = records
    (root / "native_mechanism_contract.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--current-source-root", type=Path)
    args = parser.parse_args()
    root = args.evidence_root.resolve()
    manifest = load(root / "manifest.json")
    ids = manifest["scenario_ids"]
    plans = {
        row["scenario_id"]: row
        for row in load(root / "original_plan_inventory.json")["rows"]
    }
    missing = [
        sid for sid in ids if not (root / "baseline" / sid / "summary.json").exists()
    ]
    if missing and not args.allow_partial:
        raise RuntimeError(f"{len(missing)} scenario results still missing")
    capability_file = root / "original_migration_inventory.json"
    capabilities = (
        {
            row["scenario_id"]: row.get("migration_review_flags", [])
            for row in load(capability_file).get("scenarios", [])
        }
        if capability_file.exists()
        else {}
    )
    rows = [
        inspect_case(root / "baseline" / sid, plans[sid], capabilities.get(sid))
        for sid in ids
        if sid not in missing
    ]
    report = {
        "scope": "Actual original native WOFOST Oracle audit; no adapted-management success claim",
        "expected_scenarios": len(ids),
        "completed_evidence_rows": len(rows),
        "missing": missing,
        "capability_scope": "Original restored source and original explicit HEINONG84 config only; newly added cultivar reference profiles are assessed separately, not counted as old missing-parameter failures.",
        "strict_success_count": sum(row["strict_success"] for row in rows),
        "model_block_counts": dict(
            Counter(row["model_block"] for row in rows if row["model_block"])
        ),
        "static_capability_review_counts": dict(
            Counter(flag for row in rows for flag in row["capability_review_flags"])
        ),
        "mechanism_coverage_counts": dict(
            Counter(
                item["mechanism"] for row in rows for item in row["mechanism_coverage"]
            )
        ),
        "finding_event_counts": dict(
            Counter(
                kind
                for row in rows
                for kind, count in row["finding_counts"].items()
                for _ in range(count)
            )
        ),
        "scenarios_with_finding_counts": dict(
            Counter(kind for row in rows for kind in row["finding_counts"])
        ),
        "review_limits": [
            "Named phase vs actual native stage is recorded, not automatically classified as wrong.",
            "Missing/unsupported crop mechanisms are distinct from Oracle errors.",
            "An action is not declared redundant without an actual intervention ablation.",
            "Incomplete physical progress after an early model error is not treated as zero attainable yield.",
            "This baseline retains known original model/time/resource behavior; source is frozen.",
        ],
        "rows": rows,
    }
    (root / "original_management_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    columns = (
        "scenario_id",
        "structure",
        "model_block",
        "original_intended_mechanism_status",
        "known_unsupported_mechanisms",
        "partial_mechanisms_requiring_review",
        "raw_workflow_sha256",
        "strict_success",
        "actual_tool_calls",
        "native_engines",
        "harvested_ridges",
        "stored_ridges",
        "actual_tool_errors",
        "incomplete_observation_calls",
        "zero_confidence_observation_calls",
    )
    with (root / "original_management_audit.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    write_mechanism_contract(root, manifest["baseline_root"], args.current_source_root)
    write_markdown(root, report)
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key not in {"rows", "review_limits", "missing"}
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
