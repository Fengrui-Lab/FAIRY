# FAIRY 2.0 论文展示界面

记录日期：2026-10-29。

> **`visualization` 为阶段性实验分支，当前暂不合入主线；待 FAIRY 2.0 推进时，再评估整合与合入。**
> 本入口是可交互 UI prototype。截图中的轨迹、观测与生育帧均为编排的演示数据，不是运行记录、模型评测或农艺验证结果。

## 打开与复现

按照 [可视化使用说明](../README-visualization.md) 构建并运行现有后端后，打开：

- 原实验台：`http://127.0.0.1:8000/`
- 论文展示：`http://127.0.0.1:8000/showcase?preset=overview`
- 三场补充：`http://127.0.0.1:8000/showcase?preset=management&scene=three`

前端单独开发也可使用 `cd web && npm run dev`，打开 Vite 输出地址的 `/showcase`。展示入口不需要后端；原实验台使用既有 `/api` 代理。两套入口通过动态 import 分开加载，原实验台的公开 API、数据结构和业务行为未改变。

| Figure preset | 固定入口参数 | PNG（3840 × 2160） |
| --- | --- | --- |
| Platform overview | `?preset=overview` | [01-overview.png](figures/showcase/01-overview.png) |
| Agent trajectory | `?preset=trajectory` | [02-trajectory.png](figures/showcase/02-trajectory.png) |
| 3D soil moisture | `?preset=moisture` | [03-moisture.png](figures/showcase/03-moisture.png) |
| 2D pest investigation | `?preset=investigation` | [04-investigation.png](figures/showcase/04-investigation.png) |
| L4 crop management | `?preset=management` | [05-management.png](figures/showcase/05-management.png) |

五个预设均使用双场、固定相机与演示步骤，不依赖悬停。页面顶部的 Figure preset 可恢复这些状态。地址栏同步 `scene`、`view`、`layer`、`step`、`field`、`region`、`pip`；重新打开可恢复对应选择。用户手动旋转的相机和临时地图缩放不写入 URL；切换预设或重载恢复固定构图。

## 场景来源与边界

来源仓库 `Fengrui-Lab/FAIRY`，参考分支 `codex/wofost-management-cultivars-oracle-audit`，固定提交 **`4afdd742d1bef147a41680ab722ebda2bc53f22a`**：

- [原生 WOFOST 大豆＋玉米双场定义](https://github.com/Fengrui-Lab/FAIRY/blob/4afdd742d1bef147a41680ab722ebda2bc53f22a/fairy/scenarios/two_farm/scenario_two_farm_wofost_soybean_maize_full_season.py)。文件 blob `03b38d9b6ea82b67958c494706ef4f16267037ba`。
- [三场大豆全季定义](https://github.com/Fengrui-Lab/FAIRY/blob/4afdd742d1bef147a41680ab722ebda2bc53f22a/fairy/scenarios/three_farm/scenario_three_farm_full_season_hn84_normal.py)。文件 blob `641265f01e1d5d348ab023bd844ff2e5b7caa9b2`。

| 场景 / 田块 | 作物 | 几何 / 面积 | 固定设施 |
| --- | --- | --- | --- |
| 双场 `soybean_field` | Soybean / `SOYBEAN_901` | 64 垄 × 1.1 m × 268 m，2 行/垄；1.88672 ha | `Soybean_Sensor`、`Soybean_Irrigation` |
| 双场 `maize_field` | Maize / `MAIZE_201` | 64 垄 × 0.75 m × 268 m，1 行/垄；1.28640 ha | `Maize_Sensor`、`Maize_Irrigation` |
| 三场 `farm_a` / `farm_b` / `farm_c` | 均为 Soybean / `HEINONG84` | 各 64 垄 × 1.1 m × 268 m，2 行/垄；各 1.88672 ha | 对应 `FarmA/B/C_Sensor`、`FarmA/B/C_Irrigation` |

双场使用法国 Thionville 2019 场景元信息与 `Europe/Paris` 时区，共享 `Tractor`、`Drone`、`Robot`、`Warehouse`。三场使用哈尔滨 2026 场景元信息与 `Asia/Shanghai` 时区，共享 `Tractor`、`Mavic3M`、`Matrice4T`、`Robot0`、`Warehouse`。UI 的场景切换只切换配置与素材，不创建运行，也不把新双场场景注册到原实验台的后端目录。

实际来源用于田块 ID、作物/品种、几何、设施绑定及共享设备的设置。田块相对摆放、道路、树木、仓库外观、设备姿态和传感器图标坐标均为展示布局，不是实测地理位置或传感器覆盖定义。植株采用抽样、夸张的代表性几何，不能据其数量或高度推断真实密度与株高。三场参考定义并未声明本入口运行 WOFOST，因此三场模式不标记为原生 WOFOST 双作物运行。

## 已实现的交互

- **240 步轨迹**：六阶段各 40 步，支持展开、滚动、工具/田块/步号搜索、悬停详情、固定详情和全季总览定位。步骤指向稳定的田块、区域、展示帧和媒体 ID。
- **三维世界**：米制田块、64 条垄、实例化玉米茎叶/穗与大豆冠层、固定传感器、树木、道路、共享仓库和设备；可旋转、缩放和点击田块/区域。地面图层保留植株轮廓，选择用描边表示。
- **独立二维 SVG 地图**：拖拽平移、缩放、重置、田块/区域选择、设备与传感器标记、实际地图比例尺。与 3D 共享区域选择和图层数据。
- **Crop Management**：依据已知配置绘制作物分类掩膜，显示逐场面积与演示生育期；三场模式如实显示三块大豆，没有水稻或图像分割推断。
- **媒体联动**：点击大豆高严重度红区关联到该场的无人机演示步骤并打开画中画；缩略图和弹窗使用同一个媒体 ID。支持关闭、放大、固定到右侧详情。
- **图层语义**：作物使用分类配色；水分使用连续色带与 `m³/m³`；病虫害使用 Low / Moderate / High。玉米显示 Not modeled，不能解释为无病虫害。

`web/src/showcase/data.ts` 是独立的演示定义：每场 4 × 4 个展示区域，水分、严重度和六个生育帧固定生成。区域包含空间矩形与对应垄范围，但不声称区域边界是领域模型的管理单元或真实观测足迹。工具名称和步骤结构仅用于演示界面，不保证组成可执行的 Oracle 流程；收获、入库等结果不是模型计算值。

## 本地媒体来源

`web/public/showcase-media/` 包含五张航拍 PNG 与一张叶片 SVG：

- 航拍 PNG 通过隐藏浏览器中的正交俯视相机渲染同一 `FarmScene`，米制几何、代表性植株、设备和区域标记与展示场景一致。
- 叶片 SVG 为程序化的病斑外观示意，明确标有 `PROCEDURAL ILLUSTRATION`。玉米媒体不会复用大豆病斑近景。
- 病虫害热点为单独编排的大豆演示状态；原双场场景没有注入病虫草事件，原生玉米也未模拟这类动力学。航拍本身不构成病虫害诊断。
- 未调用外部模型、地图、图片服务或真实无人机视频。没有添加前端运行依赖。

## 截图与验收命令

前端检查及纯数据契约检查：

```bash
cd web
npm run typecheck
npm run build
node --test scripts/test-showcase-data.mjs
```

数据检查使用 Node.js 24 的原生 TypeScript 类型擦除，仅需要现有前端环境。浏览器脚本使用独立工具环境中的 Playwright 与 Chromium，不加入应用运行依赖；机器尚未配置时可在单独验收目录安装 Playwright，并把其模块路径传入。

运行 Vite 或已构建后端后：

```bash
# 可省略 PLAYWRIGHT_MODULE / CHROMIUM_PATH，使用已能解析的 Playwright 及其默认 Chromium。
# 下面路径为示例，替换成本机工具环境的绝对路径。
PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs \
CHROMIUM_PATH=/path/to/chromium \
SHOWCASE_URL=http://127.0.0.1:8000 \
node scripts/capture-showcase.mjs --verify
```

该命令用 **1920 × 1080 CSS 视口、deviceScaleFactor=2** 导出五张 **3840 × 2160** PNG，无浏览器工具栏；检查预设复现、图片加载、布局边界及交互。`--verify` 同时只读检查原实验台及 `/api/health`、`/api/catalog`，因此需要后端运行。只导出截图可省略该参数。

重新生成素材：先运行 Vite，再以 `SHOWCASE_URL` 指向 Vite，用 `--media --media-only`；素材会写入 `web/public/showcase-media/`。随后重新构建前端并截图。也可在 Vite 模式下一次执行 `--media --verify`。不要向静态生产服务生成新素材后直接期待旧 `dist` 自动更新。

脚本输出 [capture-report.json](figures/showcase/capture-report.json)，记录截图、实际通过检查、异常和展示页 API 请求。测试后端应使用临时 `--data-dir`，不操作当前运行中的实验；该验收不执行农事命令，也不声称完成真实全季实验验收。

## 本次验证结果（2026-10-29）

| 检查 | 实际结果 |
| --- | --- |
| TypeScript | `npm run typecheck` 通过 |
| 生产构建 | `npm run build` 通过；两个入口独立加载，无新增前端依赖 |
| 数据契约 | `node --test scripts/test-showcase-data.mjs`：4 项通过，0 失败 |
| Chromium 实际浏览器 | 针对 `http://127.0.0.1:8000` 的生产构建完成 38 项检查，全部通过 |
| 交互 | 3D 实际区域拾取、2D 平移缩放、跨视图选择保持、热点/轨迹媒体一致、三场设施与时区、240 步定位、悬停详情与 URL 恢复通过 |
| 五张截图 | 全部为 3840 × 2160 PNG；五个直接预设、图片解码和视口/PiP 边界检查通过，并人工查看渲染图 |
| 页面异常与数据边界 | 展示页面脚本异常 0、失败资源请求 0、农场 API 请求 0 |
| 原入口兼容 | 原实验台可显示场景选择器，健康与场景目录接口正常；验收未执行农事命令 |

验收后端使用 `/private/tmp/fairy-showcase-acceptance-20261029` 隔离目录，没有读取或改动既有 `farm-runs/` 实验。上述浏览器验证针对论文展示及原入口启动，不替代原实验台的完整业务端到端验证，也不声称已执行真实双场或三场全季仿真。

## 英文图注

1. **Platform overview.** FAIRY 2.0 UI prototype showing coordinated maize and soybean fields, a 240-step agent trajectory, and shared farm resources. Field configuration follows a pinned FAIRY scenario; displayed trajectories and observations are authored demonstration data.
2. **Agent trajectory inspection.** A canopy-survey step links its target field, simulation time, result summary, and a locally rendered aerial illustration. The image is a procedural UI asset, not a recorded drone observation.
3. **Three-dimensional soil-moisture view.** An illustrative volumetric water-content layer (m³/m³) overlays the field while retaining representative crop geometry. Colors and values are demonstration fixtures, not WOFOST measurements.
4. **Spatial evidence exploration.** Selecting an authored soybean hotspot links the map to an agent step and a picture-in-picture aerial illustration with a procedural leaf-detail inset. Severity is illustrative; native maize pest dynamics are not modeled.
5. **L4 crop management.** Crop masks derived from known field assignments distinguish maize and soybean and summarize field area and illustrative growth stages. Shared equipment serves both fields; an alternate preset contains three soybean farms.

## 后续范围

本轮完成论文界面的交互和截图，不实现真实运行附着、任意日志回放、田块/传感器配置编辑或新的农场业务行为。此前记录的时间对齐、检查点、多农场/多作物适配、真实位置与覆盖、路径与资产流程仍见 [路线图](farm-visualization-roadmap.md)。是否把这些展示组件整合到真实运行视图，待 FAIRY 2.0 推进时单独设计与验证；当前不创建合并 PR。
