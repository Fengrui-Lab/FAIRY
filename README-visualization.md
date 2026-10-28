# FAIRY 农场可视化实验台

> **`visualization` 为阶段性实验分支，当前暂不合入主线；待 FAIRY 2.0 推进时，再评估整合与合入。**
> [当前状态、验证边界与后续方向（2026-10-28）](docs/farm-visualization-roadmap.md)

本地单用户 Three.js 实验台，连接 FAIRY 原有场景、App 工具和 WOFOST。支持人工与 Agent 操作、公开观测、模型诊断、已保存运行回看、基础对照以及视觉布局保存。实验记录默认在项目同级 `farm-runs/`。同级 `farm-tools/` 中的桥接、验收脚本与来源记录属于本地配套资料，本分支不包含这些辅助工具，也不包含虚拟环境、运行数据库、依赖副本或构建产物；本文相关章节仅供持有本地配套资料时参考。

## 启动

在项目根目录使用 Python 3.10 或以上版本安装依赖；本次本地验证使用 Python 3.11.15。下列命令会在项目外创建虚拟环境，无需预先取得辅助脚本：

```bash
python -m venv ../farm-tools/venv
../farm-tools/venv/bin/python -m pip install -e '.[wofost]' -r requirements-visualization.txt
```

安装与构建前端，然后启动服务：

```bash
cd web
npm ci
npm run typecheck
npm run build
cd ..
../farm-tools/venv/bin/python -m fairy.visualization --host 127.0.0.1 --port 8000 --data-dir ../farm-runs
```

浏览器打开 `http://127.0.0.1:8000`。分支已包含真实安装生成的 `package-lock.json`，使用 `npm ci` 安装锁定的前端依赖。服务启动时读取已构建的 `web/dist`；开发时可使用 Vite 的 `/api` 代理。不要运行多个后端 worker 指向同一个数据目录。

CLI 在场景导入前固定 `PYTHONHASHSEED=0`，因为上游 App 随机初始化使用 Python hash。首版只支持原场景固定种子 0，保持原工具序列语义，不额外重新初始化随机流。

## 当前场景与数据来源

源码基线：`Fengrui-Lab/FAIRY` 分支 `codex/wofost-management-cultivars-oracle-audit`，提交 `5a5dca63ff07cef145b1b42ef6ae27e42f5babf0`。

首版支持 `scenario_full_season_hb_base_hn84_std_normal_V2`。实际配置为法国里尔 2019 年、SOYBEAN_901、64 垄、268 米长、1.1 米垄宽。地点、品种和时区取自实际配置，场景 ID 中的历史名称不作为元数据依据。PCSE 固定为 6.0.13。

最初的本地源码包通过 GitHub connector 获取并逐文件核对 Git blob SHA，取得 998 个源码、配置、测试及文档文件；未复制其他场景的预制检查点和 Oracle 计划大文件。本次分支发布以以上真实上游提交为父提交，增量加入可视化实现并保留上游树中的其他文件，不把源码包中未取得的文件视为删除。当前正常季场景从源码构建，所需原生作物与天气数据已包含。本地源码包的获取范围另记录在配套资料 `farm-tools/source-provenance.json` 中，该文件不随本分支提交。

## 使用方式

1. 创建实验，点击田垄；Shift 点击选择连续范围。
2. 通过原工具表单显式测量或执行农事，查看业务回执。HTTP 接受命令不代表作业成功。
3. 使用 `SystemApp__advance_time` 等原工具推进时间。工具自身耗时只结算一次，页面空闲或动画不推进世界。
4. 切换模型诊断查看内部指标；访问被记录，后续人工干预标记为 `audit_assisted`。
5. 回看已保存版本，点击返回实时后继续操作。历史界面不执行农事。
6. 创建另一次实验会将原实验归档；可以从已保存列表回看和比较。活动操作或自动控制期间不能替换实验。

公开视图只使用公开业务状态和实际获取的观测。刷新、缩放、历史查询和诊断读取不会重新采样。观测保留覆盖范围、测量时间和缺失状态；没有观测的区域保持未知。历史曲线只连接已记录测量，不补造每日数据。

模型诊断是仿真内部状态，不是现实田间真值。DVS 到大豆阶段的映射、株形等表达有模型近似；WOFOST 根区水分与复用它的表层视图不能解释为独立土层测量。原生籽粒干物质与实际安全入库量分别看待。诊断接口不返回完整检查点、RNG、未来强迫输入或未执行 Oracle 计划。

灌溉等操作可能已完成资源扣减，但原生效果到下一当地日界才结算。按回执的 `effect_ready_at` 判断复测时间，不能把点击成功当成已观察到水分改善。

当前上游原生 WOFOST 路径在此期间仍接受新的灌溉命令并累计水量，未沿用 legacy 路径的 `irrigation_pending` 拦截。工作台保留这一行为；同一 `command_id` 重试不会重复执行，不同 ID 表示新的作业。日界后的水分变化还受到天气和其他模型过程影响，不能全部归因为灌溉。

## Agent 与外部决策脚本

可选模型接管在服务端配置：

```bash
export FARM_LLM_MODEL='your-model'
export FARM_LLM_API_KEY='your-key'
export FARM_LLM_BASE_URL='https://your-compatible-provider/v1'
```

也支持 `OPENAI_API_KEY`。密钥只留在服务端。FAIRY Agent 复用当前实验，不重新 setup；其工具调用经过同一命令队列，系统自动生成的上下文只有公开快照。缺少 SDK 或配置时显示不可用原因。停止请求在安全工具边界生效，不撤销已经发生的资源变化。

同级 `farm-tools/farm_session.py` 提供 JSONL 桥，附着已存在的实验，让外部控制者逐轮获取公开观测和发出工具调用。桥自身不调用模型 API，也不读取模型诊断。参阅其 `--help` 和 `farm-tools/README.md`。外部会话取得控制令牌；令牌不进入公开快照和报告。

## 视觉布局与 GLB

田块的物理尺寸固定。可编辑展示位置、方向、标签；不提供改变物理面积的自由缩放。传感器图标移动不改变实际覆盖。设备与传感器支持 GLB 外观替换，田块保留可按垄选择的程序几何体。GLB 放在 `web/public/models/`，使用 `/models/name.glb` 引用并重新构建前端；加载失败回退程序模型。模型替换保留业务绑定。

植株为实例化的代表性视觉元素，不是一株一个物理模型。农机轨迹仅作作业示意；当前世界未提供真实连续位姿和跨场行驶过程，动画不额外结算耗时或燃油。

## 持久化和接口

SQLite 保存运行描述、命令、成对公开及诊断快照、观测、审计访问和布局。进程重启后旧实验仅供回看；未完成命令标记中断或结果不确定，不自动重放。历史快照不能替代完整 WOFOST 检查点恢复。

首版审计查看者统一记为 `local_user`，同时记录访问墙钟时间、目标版本及目标仿真时间；这是本地单用户记录，不提供多人身份认证。原生诊断映射版本为 `wofost-native-v1`，三维示意映射版本为 `visual-v1`。

主要接口：

| 接口 | 用途 |
| --- | --- |
| `GET /api/catalog` | 场景与模型接管可用性 |
| `GET/POST /api/runs` | 列表与新实验 |
| `GET /api/runs/current` | 当前运行或 null |
| `GET /api/runs/{id}/snapshot` | 最新公开快照 |
| `GET /api/runs/{id}/tools` | 原工具参数与说明 |
| `POST /api/runs/{id}/commands` | 带唯一 command_id 的异步命令 |
| `GET /api/runs/{id}/commands/{command_id}` | 查询原命令结果，超时后先查再决定 |
| `GET /api/runs/{id}/history` | 已记录版本列表 |
| `GET /api/runs/{id}/history/{revision}` | 历史公开快照 |
| `GET /api/runs/{id}/observations?revision=N` | 截至该版本的真实公开测量记录 |
| `GET /api/runs/{id}/audit?revision=N` | 模型诊断并记录访问 |
| `WS /api/runs/{id}/stream` | 公开快照更新 |
| `POST /api/runs/{id}/controller` | 外部或模型接管 |
| `POST /api/runs/{id}/stop` | 安全边界停止 |
| `GET/PUT /api/runs/{id}/layout` | 视觉布局 |
| `GET /api/compare?left=A&right=B` | 条件检查与公开指标对照 |

同 ID 同参数只执行一次，同 ID 换参数拒绝。客户端拒绝旧运行和较低版本的消息。对照展示场景、天气、品种、参数和随机初始化差异，不把不匹配条件的结果直接归因为策略优劣。

## 验证

以下两组测试位于本分支内；真实适配器测试需另外安装 `pytest`，并使用固定的 Python hash 种子：

```bash
python -m unittest discover -s tests -p 'test_visualization_runner.py' -v
PYTHONHASHSEED=0 python -m pytest tests/test_visualization_adapter.py -q
```

以下额外验收命令依赖本地配套资料，本分支不提供对应脚本：

```bash
python ../farm-tools/check_http_boundary.py --selector-timer
python ../farm-tools/browser_acceptance.py --help
```

管理与 HTTP 边界测试的可控领域替身用于检验并发、幂等、审计与存储语义，不能代替真实 WOFOST 测试。真实适配测试调用原 PCSE 和 App 工具；浏览器测试另行验证构建、Canvas、控件与网络链路。`--selector-timer` 仅为限制 socketpair 唤醒的测试环境提供周期唤醒，不属于生产运行方式。

实际执行结果与未执行项写入同级 `farm-tools/runs/`。不要把语法转换、接口测试或未运行的浏览器用例宣称为生产构建和端到端通过。
