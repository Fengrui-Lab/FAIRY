# Main 分支复用 L3 PathSim Same 上下文

基础版本：origin/main `a7654d87ee6f4e0ade1c3f74a6014cd4c9ac127c`。独立工作目录：`/Users/quao/.codex/worktrees/l3-pathsim-main/FAIRY`。

## 文件放置

- 上下文：`validation_runs/inputs/l3_pathsim_same_context.json`，与原实验的 No-thinking 匹配结果逐字节一致，SHA256 `7bb1261a84ff74859b129ecbd527c95727a1d1f71d4dd51fa2f70a47128c653f`。
- 场景清单：`scripts/fullseason/l3_mini_20_scenario_ids.txt`，main 已有，未改动。
- 原始运行结果：`validation_runs/l3_mini_qwen35b_l3_pathsim_same_main_20261105`。每场有 console.log、progress.jsonl、runtime_log.jsonl、agent_workflow.json、run_report.json。
- 批次日志：`validation_runs/l3_mini_qwen35b_l3_pathsim_same_main_20261105/batch.log`；失败清单：`failed_scenarios.tsv`；循环结束标记：`batch.finished`。

## 改动及原因

1. `fairy/cli.py`：接通 --enable-thinking、--retrieved-context-path、--request-timeout-seconds。支持直接指定上下文和关闭 thinking，不需要手动 export。
2. `fairy/apps/system.py`：仅将 advance_time 描述与当前 ARE 对齐版本一致，保留 main 的执行逻辑。
3. `fairy/apps/farm_world/farm_world_app.py`：仅将 commit_daily_physics 标记为 READ，保留执行逻辑和描述。
4. `tests/test_pathsim_context_cli.py`：验证实际参数传递及无效上下文在模型请求前被拒绝。

未迁移启动脚本、候选日志索引、时间转换或检索生成代码；这里直接使用已经选好的上下文。

## 检查

相关 7 项测试通过。模型服务器已确认可达。单次请求上限 600 秒；整场运行预算 3600 秒；300 次工具调用；关闭 thinking；一场失败继续后续。

## 实际运行命令

下面循环已在独立后台进程执行，不应在已有输出目录上重复启动。命令内容仅记录在本文，没有生成启动脚本。启动时为子进程配置了模型私网地址直连，不改变其他任务的环境。

```bash
cd /Users/quao/.codex/worktrees/l3-pathsim-main/FAIRY

bash <<'BASH'
set -uo pipefail
printf 'scenario\texit_code\n' > validation_runs/l3_mini_qwen35b_l3_pathsim_same_main_20261105/failed_scenarios.tsv
while IFS= read -r scenario || [ -n "$scenario" ]; do
  case "$scenario" in
    ""|\#*) continue ;;
  esac
  mkdir -p "validation_runs/l3_mini_qwen35b_l3_pathsim_same_main_20261105/$scenario"
  echo "Running: $scenario"
  if uv run --offline python -m fairy.cli \
    -s "$scenario" \
    --agent \
    --controller farm_baseline_react \
    --provider vllm \
    --model Qwen3.6-35B-A3B-FP8 \
    --endpoint http://100.115.106.71:8000/v1 \
    --enable-thinking false \
    --scenario-kwargs '{"detailed_briefing":"l3_pathsim_same"}' \
    --retrieved-context-path validation_runs/inputs/l3_pathsim_same_context.json \
    --a2a false \
    --system-prompt-mode fairy \
    --parallel-tool-calls false \
    --max-output-tokens 8192 \
    --max-tool-calls 300 \
    --request-timeout-seconds 600 \
    --timeout-seconds 3600 \
    --output-dir "validation_runs/l3_mini_qwen35b_l3_pathsim_same_main_20261105/$scenario" \
    </dev/null 2>&1 | tee "validation_runs/l3_mini_qwen35b_l3_pathsim_same_main_20261105/$scenario/console.log"; then
    echo "Finished: $scenario"
  else
    rc=$?
    printf '%s\t%s\n' "$scenario" "$rc" >> validation_runs/l3_mini_qwen35b_l3_pathsim_same_main_20261105/failed_scenarios.tsv
    echo "Failed: $scenario (exit $rc); continuing."
  fi
done < scripts/fullseason/l3_mini_20_scenario_ids.txt
date -u '+%Y-%m-%dT%H:%M:%SZ' > validation_runs/l3_mini_qwen35b_l3_pathsim_same_main_20261105/batch.finished
echo 'Batch finished.'
BASH
```

查看日志：

```bash
tail -n 30 /Users/quao/.codex/worktrees/l3-pathsim-main/FAIRY/validation_runs/l3_mini_qwen35b_l3_pathsim_same_main_20261105/batch.log
```

## 相对 main 的完整代码差异

以下为实际运行版本的逐行改动，可按文件和位置对照修改。测试文件仅用于验证，不影响启动方式。

```diff
diff --git a/fairy/apps/farm_world/farm_world_app.py b/fairy/apps/farm_world/farm_world_app.py
index e7205e2..71f40fe 100644
--- a/fairy/apps/farm_world/farm_world_app.py
+++ b/fairy/apps/farm_world/farm_world_app.py
@@ -827,7 +827,7 @@ class FarmWorldApp(App):

     @type_check
     @app_tool()
-    @event_registered(operation_type=OperationType.WRITE)
+    @event_registered(operation_type=OperationType.READ)
     def commit_daily_physics(self) -> dict[str, Any]:
         """
         Force a full daily physics tick at the current simulation time.
diff --git a/fairy/apps/system.py b/fairy/apps/system.py
index ef70b4e..6926312 100644
--- a/fairy/apps/system.py
+++ b/fairy/apps/system.py
@@ -69,19 +69,19 @@ class SystemApp(App):
         """
         Advance the simulation clock by a specified amount of time.

-        Use this fast-forward tool when waiting for biological or physical
-        processes to play out, such as crop growth, soil drying, treatment
-        residual decay, irrigation effects, or post-harvest drying. After time
-        advances, subsequent state reads reflect the evolved world.
+        This is the canonical "fast-forward" tool. Use it when waiting for
+        biological or physical processes (crop growth, soil drying, treatment
+        residual decay, post-harvest drying) to play out. After the time
+        advances, any subsequent state read will reflect the evolved world.

         Args:
             seconds: Seconds to advance.
             minutes: Minutes to advance.
-            hours: Hours to advance.
-            days: Days to advance.
+            hours:   Hours to advance.
+            days:    Days to advance.

         Returns:
-            A dictionary containing the new current time.
+            A dict containing the new current time.
         """
         total_seconds = (
             int(seconds) + int(minutes) * 60 + int(hours) * 3600 + int(days) * 86400
diff --git a/fairy/cli.py b/fairy/cli.py
index 21dd226..3a505af 100644
--- a/fairy/cli.py
+++ b/fairy/cli.py
@@ -2,6 +2,7 @@ from __future__ import annotations

 import argparse
 import json
+import os
 import shutil
 import time
 from pathlib import Path
@@ -147,6 +148,12 @@ def main() -> None:
         help="Maximum completion tokens per LLM call",
     )
     parser.add_argument("--endpoint", default=None, help="OpenAI-compatible base URL for --agent provider")
+    parser.add_argument("--enable-thinking", type=_str_to_bool, default=None,
+                        help="Thinking override for the main model; omitted uses server default")
+    parser.add_argument("--request-timeout-seconds", type=float, default=None,
+                        help="Timeout for each LLM request")
+    parser.add_argument("--retrieved-context-path", type=Path, default=None,
+                        help="JSON context map for the retrieved L3 briefing")
     parser.add_argument("--parallel-tool-calls", type=_str_to_bool, default=True, help="Allow the model to return multiple tool calls in one LLM turn")
     parser.add_argument("--max-tool-calls", type=int, default=300, help="Maximum tool calls for --agent")
     parser.add_argument("--timeout-seconds", type=float, default=1200.0, help="Wall-time limit for --agent")
@@ -179,10 +186,24 @@ def main() -> None:
         return
     if args.max_output_tokens <= 0:
         parser.error("--max-output-tokens must be a positive integer")
+    if args.request_timeout_seconds is not None and args.request_timeout_seconds <= 0:
+        parser.error("--request-timeout-seconds must be positive")
     if not args.scenario:
         parser.error("--scenario is required unless --list is used")
     scenario_class = get_scenario_class(args.scenario)
     scenario_kwargs = _json_object_arg(args.scenario_kwargs, "--scenario-kwargs")
+    if args.retrieved_context_path is not None:
+        context_path = args.retrieved_context_path.expanduser().resolve()
+        try:
+            payload = json.loads(context_path.read_text(encoding="utf-8"))
+        except (OSError, ValueError) as exc:
+            parser.error(f"Invalid --retrieved-context-path: {exc}")
+        contexts = payload.get("contexts") if isinstance(payload, dict) else None
+        if not isinstance(contexts, dict) or not isinstance(contexts.get(args.scenario), str) or not contexts[args.scenario].strip():
+            parser.error(f"Retrieved context has no nonempty text for {args.scenario}")
+        if payload.get("mode") not in (None, scenario_kwargs.get("detailed_briefing")):
+            parser.error("Retrieved context mode differs from detailed_briefing")
+        os.environ["FARM_FAIRY_RETRIEVED_CONTEXT_PATH"] = str(context_path)
     init_kwargs = _json_object_arg(args.init_kwargs, "--init-kwargs")
     output_dir = Path(args.output_dir)
     workflow_path = Path(args.workflow) if args.workflow else output_dir / f"{args.scenario}.oracle.json"
@@ -280,6 +301,8 @@ def main() -> None:
                 "temperature": args.temperature,
                 "max_output_tokens": args.max_output_tokens,
                 "parallel_tool_calls": args.parallel_tool_calls,
+                "enable_thinking": args.enable_thinking,
+                **({"timeout": args.request_timeout_seconds} if args.request_timeout_seconds is not None else {}),
                 **({"base_url": args.endpoint} if args.endpoint else {}),
             }
         )
```
