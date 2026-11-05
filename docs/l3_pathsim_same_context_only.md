# L3 PathSim Same：复用现成上下文的完整执行说明

本文只说明现成上下文的接入与执行。命令未列出的参数使用 CLI 或服务端默认值，不涉及其他开关和请求时限的接线。仅编写本说明，不修改当前运行代码、不重新启动实验。

## 1. 这次需要什么

必需材料只有：

1. 已支持 `l3_pathsim_same` 的 FAIRY/main 项目。
2. 已生成的 `retrieved_context.json`，其中有全部 20 个场景的上下文。
3. CLI 增加读取该文件的参数及处理逻辑。

现成上下文已经包含每场选中的 4 条参考工作流。直接加载它，不需要迁移候选日志、转换时间、建立候选索引、重新匹配 oracle，也不需要新增启动脚本。

当前已准备好的项目目录：

```text
/Users/quao/.codex/worktrees/l3-pathsim-main/FAIRY
```

后续命令在项目根目录执行：

```bash
cd /Users/quao/.codex/worktrees/l3-pathsim-main/FAIRY
```

如果换成其他项目，先进入那个项目根目录，后续相对路径保持一致。

## 2. 把上下文放在哪里

统一放在项目下：

```text
validation_runs/inputs/l3_pathsim_same_context.json
```

当前项目已放好。其他项目缺少该文件时，可直接复制这次生成的原文件；下面命令不会覆盖已有文件：

```bash
mkdir -p validation_runs/inputs
if [ ! -f validation_runs/inputs/l3_pathsim_same_context.json ]; then
  cp /Users/quao/.codex/worktrees/wofost-management-audit/FAIRY/validation_runs/l3_mini_qwen35b_l3_pathsim_same_rematch_20261105/retrieved_context.json validation_runs/inputs/l3_pathsim_same_context.json
fi
```

JSON 的结构如下。这里只展示结构，不要用这个示意内容覆盖真实文件：

```json
{
  "mode": "l3_pathsim_same",
  "contexts": {
    "scenario_full_season_hb_organic_residue_weed_establishment": "该场景的完整参考工作流文本",
    "其他场景ID": "对应的参考工作流文本"
  }
}
```

## 3. 只为接入上下文，需要怎样改代码

只需要修改 `fairy/cli.py`。当前新项目已经完成这三处修改；以下供其他 main 项目照着迁移，已有的代码不必重复添加。

### 3.1 文件顶部增加导入

```python
import os
```

main 原来已有 `import json` 和 `from pathlib import Path`，继续复用。

### 3.2 在 parser.parse_args() 之前注册参数

与其他 `parser.add_argument(...)` 放在一起：

```python
parser.add_argument(
    "--retrieved-context-path",
    type=Path,
    default=None,
    help="JSON context map for the retrieved L3 briefing",
)
```

这一步只是接收路径，单独加这一段还不会加载上下文。

### 3.3 在创建场景之前，验证文件并交给已有加载器

找到 main 原有的这一行：

```python
scenario_kwargs = _json_object_arg(args.scenario_kwargs, "--scenario-kwargs")
```

紧接着插入下面整段，必须在 `scenario_class(**scenario_kwargs)` 以及 `scenario.setup()` 之前执行：

```python
if args.retrieved_context_path is not None:
    context_path = args.retrieved_context_path.expanduser().resolve()
    try:
        payload = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        parser.error(f"Invalid --retrieved-context-path: {exc}")

    contexts = payload.get("contexts") if isinstance(payload, dict) else None
    if not isinstance(contexts, dict):
        parser.error("Retrieved context JSON must contain a contexts object")
    text = contexts.get(args.scenario)
    if not isinstance(text, str) or not text.strip():
        parser.error(f"Retrieved context has no nonempty text for {args.scenario}")
    if payload.get("mode") not in (None, scenario_kwargs.get("detailed_briefing")):
        parser.error("Retrieved context mode differs from detailed_briefing")

    os.environ["FARM_FAIRY_RETRIEVED_CONTEXT_PATH"] = str(context_path)
```

最后一行在本次 CLI 进程内把路径交给 main 已有的加载器，用户运行命令时不需要手写 export。

main 的 `harbin_l3_context_briefings.py` 已有 `_load_retrieved_context`，会按当前 `scenario_id` 取出文本；因此不必再次修改该加载器。

接入过程是：

```text
--retrieved-context-path 指定 JSON
→ CLI 验证文件和场景
→ 创建场景
→ detailed_briefing=l3_pathsim_same
→ 已有加载器读取 contexts[当前场景ID]
→ 拼入任务 briefing
→ Agent 开始执行
```

## 4. 执行前检查

安装项目依赖并查看 CLI 帮助：

```bash
uv sync
uv run python -m fairy.cli --help
```

帮助中应包含 `--retrieved-context-path`。检查真实上下文和现有 L3-mini 名单相互匹配：

```bash
uv run python - <<'PY'
from pathlib import Path
import json

context_path = Path("validation_runs/inputs/l3_pathsim_same_context.json")
manifest_path = Path("scripts/fullseason/l3_mini_20_scenario_ids.txt")
payload = json.loads(context_path.read_text(encoding="utf-8"))
scenarios = [s.strip() for s in manifest_path.read_text().splitlines()
             if s.strip() and not s.lstrip().startswith("#")]
assert payload["mode"] == "l3_pathsim_same"
assert len(scenarios) == len(set(scenarios)) == 20
assert set(payload["contexts"]) == set(scenarios)
assert all(isinstance(text, str) and text.strip()
           for text in payload["contexts"].values())
assert all(text.count("## Retrieved L3:") == 4
           for text in payload["contexts"].values())
print("检查通过：20 场都有上下文，每场 4 条参考。")
PY
```

## 5. 先跑一场

这个命令使用单独的新输出目录，不覆盖当前正在运行的批次。如果该示例目录已有实验材料，换一个新名字再运行。

```bash
uv run python -m fairy.cli \
  -s scenario_full_season_hb_organic_residue_weed_establishment \
  --agent \
  --controller farm_baseline_react \
  --provider vllm \
  --model Qwen3.6-35B-A3B-FP8 \
  --endpoint http://100.115.106.71:8000/v1 \
  --scenario-kwargs '{"detailed_briefing":"l3_pathsim_same"}' \
  --retrieved-context-path validation_runs/inputs/l3_pathsim_same_context.json \
  --a2a false \
  --system-prompt-mode fairy \
  --parallel-tool-calls false \
  --max-output-tokens 8192 \
  --max-tool-calls 300 \
  --output-dir validation_runs/l3_pathsim_same_context_example_one/scenario_full_season_hb_organic_residue_weed_establishment
```

两个参数分别负责：

- `--scenario-kwargs`：选择使用 L3 PathSim Same briefing 模式。
- `--retrieved-context-path`：指出该模式具体使用哪个上下文文件。

模型部署在 `100.115.106.71:8000`，FAIRY 在本地执行。终端需要能直连这个私网地址。

## 6. 确认上下文实际进入任务

出现 `progress.jsonl` 后，在另一个终端执行：

```bash
uv run python - <<'PY'
from pathlib import Path
import json

p = Path("validation_runs/l3_pathsim_same_context_example_one/scenario_full_season_hb_organic_residue_weed_establishment/scenario_full_season_hb_organic_residue_weed_establishment.progress.jsonl")
if not p.is_file():
    raise SystemExit("还没有 progress 日志，先确认运行已开始。")
with p.open(encoding="utf-8") as handle:
    for line in handle:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("record_type") == "agent_task_source":
            text = record.get("content_preview", "")
            print(text)
            assert "L3_PATHSIM_SAME" in text
            print("已确认 L3 PathSim Same 上下文进入任务。")
            break
    else:
        raise SystemExit("尚未找到 agent_task_source，稍后再次检查。")
PY
```

应看到 `Retrieved workflow context`、`L3_PATHSIM_SAME` 和 `Retrieved L3` 等内容。

## 7. 跑 L3-mini 20 场，单场失败继续

这是一次性终端命令，不保存为新的启动脚本。输出目录已存在时会停止，防止覆盖。单场示例与此批次互相独立；只需要批量运行时可以直接执行本节。

```bash
bash <<'BASH'
set -uo pipefail
if [ -e validation_runs/l3_pathsim_same_context_example_20 ]; then
  echo "输出目录已存在，请换新目录后再运行。"
  exit 1
fi
mkdir -p validation_runs/l3_pathsim_same_context_example_20
printf 'scenario\texit_code\n' > validation_runs/l3_pathsim_same_context_example_20/failed_scenarios.tsv
while IFS= read -r scenario || [ -n "$scenario" ]; do
  case "$scenario" in
    ""|\#*) continue ;;
  esac
  mkdir -p "validation_runs/l3_pathsim_same_context_example_20/$scenario"
  echo "Running: $scenario"
  if uv run python -m fairy.cli \
    -s "$scenario" \
    --agent \
    --controller farm_baseline_react \
    --provider vllm \
    --model Qwen3.6-35B-A3B-FP8 \
    --endpoint http://100.115.106.71:8000/v1 \
    --scenario-kwargs '{"detailed_briefing":"l3_pathsim_same"}' \
    --retrieved-context-path validation_runs/inputs/l3_pathsim_same_context.json \
    --a2a false \
    --system-prompt-mode fairy \
    --parallel-tool-calls false \
    --max-output-tokens 8192 \
    --max-tool-calls 300 \
    --output-dir "validation_runs/l3_pathsim_same_context_example_20/$scenario" \
    </dev/null 2>&1 | tee "validation_runs/l3_pathsim_same_context_example_20/$scenario/console.log"; then
    echo "Finished: $scenario"
  else
    rc=$?
    printf '%s\t%s\n' "$scenario" "$rc" >> validation_runs/l3_pathsim_same_context_example_20/failed_scenarios.tsv
    echo "Failed: $scenario，已记录，继续下一场。"
  fi
done < scripts/fullseason/l3_mini_20_scenario_ids.txt
date -u '+%Y-%m-%dT%H:%M:%SZ' > validation_runs/l3_pathsim_same_context_example_20/batch.finished
BASH
```

scenario、rc 只是 Shell 循环变量；模型地址、上下文、结果目录等参数已经直接写明，不需要预先设置配置环境变量。

## 8. 结果在哪里，怎样看进度

每场原始文件在：

```text
validation_runs/l3_pathsim_same_context_example_20/<场景ID>/
  console.log
  <场景ID>.progress.jsonl
  <场景ID>.runtime_log.jsonl
  <场景ID>.agent_workflow.json
  <场景ID>.run_report.json
```

查看已写出的报告和失败清单：

```bash
uv run python - <<'PY'
from pathlib import Path
import json

root = Path("validation_runs/l3_pathsim_same_context_example_20")
reports = sorted(root.glob("scenario_*/*.run_report.json"))
print(f"报告：{len(reports)}/20")
for p in reports:
    r = json.loads(p.read_text())
    print(r.get("scenario_id"), r.get("status"), r.get("stop_reason"), r.get("error"))
failed = root / "failed_scenarios.tsv"
if failed.exists():
    print(failed.read_text())
print("循环已结束：", (root / "batch.finished").exists())
PY
```

报告数量表示已写出报告的场景数；成功与否还要看 status、stop_reason、error。batch.finished 表示循环结束，不代表全部成功。上述命令产生原始日志，YL 需要后续按相同 oracle 基线另行回放评分。

## 9. 工具口径对齐，与文件加载分开处理

若希望与当前实验采用相同工具提示，还应对齐两处已有定义；它们不属于上下文文件加载的必要步骤：

1. `fairy/apps/farm_world/farm_world_app.py`：只把 commit_daily_physics 的装饰器改为 READ：

```diff
- @event_registered(operation_type=OperationType.WRITE)
+ @event_registered(operation_type=OperationType.READ)
  def commit_daily_physics(self):
```

2. `fairy/apps/system.py`：advance_time 的文档说明采用当前 ARE 对齐文案，函数执行逻辑保留目标分支原实现。核心段落如下：

```text
This is the canonical "fast-forward" tool. Use it when waiting for
biological or physical processes (crop growth, soil drying, treatment
residual decay, post-harvest drying) to play out. After the time
advances, any subsequent state read will reflect the evolved world.
```

当前独立 main 项目已经完成这两处对齐。复用现成上下文时，无需再改 workflow_validation.py、重新排序工作流或重新生成检索结果。

## 10. 需要 YL 时：回放评分

整批运行结束后执行。下面复用现有大表的 oracle 产量缓存，不重新生成检索上下文。

```bash
uv run python -m scripts.rebatch_fos_from_traces \
  --root validation_runs/l3_pathsim_same_context_example_20 \
  --out-root validation_runs/l3_pathsim_same_context_example_20/.yield_loss_details \
  --oracle-baselines /Users/quao/.codex/worktrees/wofost-management-audit/FAIRY/validation_runs/l3_mini_qwen35b_grouped_thinking_20261104_232041/yield_loss_oracle_baselines \
  --extrapolate \
  --extrapolation-max-days 180 \
  --workers 4

cp validation_runs/l3_pathsim_same_context_example_20/.yield_loss_details/summary_v2.csv validation_runs/l3_pathsim_same_context_example_20/summary_v2.csv
```

最终 CSV 在批次根目录，原始日志继续留在各场景目录中。换电脑时还需要携带上述 oracle 产量缓存；只有上下文 JSON 就足以执行 Agent，但不足以使用这份缓存进行 YL 评分。
