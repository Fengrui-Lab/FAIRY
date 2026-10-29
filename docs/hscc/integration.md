# HSCC Jev / Hybrid 接口整合

基底是 Fengrui-Lab/FAIRY `codex/wofost-management-cultivars-oracle-audit` 的 `4afdd742d1bef147a41680ab722ebda2bc53f22a`。移植来源是 Synkrasis-Labs/fairy-jev 的 `a667e6f` 加原 manos 已测试的未提交接口改动。来源快照、补丁和文件清单位于 HSCC 的 `integration/`。

## 兼容处理

- 保留目标分支场景、应用、物理和 oracle 实现。Jev 与 Hybrid 通过独立菜单决策客户端接入；原生 ReAct 保留目标分支提示词路由与重试行为。
- `fairy-run` 继续使用原入口；新增 `fairy-cli capabilities --json`、`describe-scenario --job`、`check-service --job`、`probe-request --job`、`score --job` 及兼容运行参数，JSON 契约版本为 1。完整参数以 `fairy-cli --help` 和管线适配器为准。
- `agent_task_override` 由执行边界设置，不传入新版 Scenario 构造器，不修改场景源码。
- 新版 `base_fertilize(total_kg: float | None = None)` 支持数值菜单和显式默认 null，保留目标运行时按面积计算默认用量的语义。
- 保留新版多农场 outcome 结构及 `_physics` 惰性读取；补充只读完成事实及按实际农场面积计算的终态生物产量。没有物理历史的字段保持未知，不强行初始化物理引擎。
- 版本指纹覆盖 FAIRY Python 文件、整个 package 中的场景/物理/作物数据文件、依赖锁及 pcse/jsonschema 等安装版本。WOFOST 品种文件变化会产生新协议。
- oracle 命令调用当前 Engine 和当前场景；重放为显式独立评分，禁止借用无身份的旧基线。

## 安装与验证

```sh
uv sync --frozen --extra wofost --extra test
.venv/bin/fairy-cli capabilities --json
.venv/bin/python -m pytest -q tests/test_jev_agent.py tests/test_decision_services.py tests/test_public_cli_contract.py tests/test_request_probe.py tests/test_hscc_integration_contract.py
```

只使用 system-one-compatible/OpenAI-compatible 服务时无需安装 TypeSafe SDK；如需要 TypeSafe provider，显式增加 `--extra jev`。

六个迁移试点均完成初始化和菜单构造检查；444 个注册场景不等于全部已完成 Jev 全季验证。新增多农场/多作物工具应先做控制器适配检查，未知菜单参数明确失败，不自动退回旧场景。公共 API 的请求级限流和纯 Jev 无效动作循环不是本次整合修复范围。
