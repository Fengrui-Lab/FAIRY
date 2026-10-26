# 四类大豆的 WOFOST 工程参考档案

新增四个真实品种标识，均属于大豆；它们不代表新增四个物种。每个档案完整列出 78 个原生参数，并明确区分论文事实、通用模型参数和工程假设。当前状态均为 `unvalidated`，没有声称完成田间校准。

| 标识 | 文献支持的对照 | 档案 |
|---|---|---|
| `SUINONG42` | 绥农42，苗期耐低温对照 | `soybean_suinong42_cold_reference_v1` |
| `KENDOU40` | 垦豆40，苗期低温敏感对照 | `soybean_kendou40_cold_reference_v1` |
| `HEINONG44` | 黑农44，耐旱对照 | `soybean_heinong44_drought_reference_v1` |
| `HEINONG65` | 黑农65，干旱敏感对照 | `soybean_heinong65_drought_reference_v1` |

## 原始依据和参数映射

[Wang 等（2023）](https://www.mdpi.com/2073-4395/13/7/1716)在首片复叶展开后进行了 72 小时、4℃低温处理，正常对照为25℃，恢复处理为25℃三天。表4中绥农42、垦豆40的综合评价分数 D 分别为0.7546、0.2025。原文没有提供对应的 WOFOST 光合作用系数，也指出萌发期与苗期的低温响应不相关。

工程档案以 `factor(4℃) = 0.2 + 0.6 × D` 定义两个对照，结果分别为0.65276、0.3215；0℃端点为0，12℃端点为1。中间线性插值，端点之外保持端点值。公式中的0.2、0.6和两个端点是明确的工程假设，并非论文拟合结果。

这张表写入原生 `TMNFTB`。PCSE 6实际使用最近最多七天的日最低气温均值计算该因子，然后进入原生碳同化过程。[原生实现](https://pcse.readthedocs.io/en/stable/_modules/pcse/crop/assimilation.html)说明了输入含义。档案不降低播种温度门槛、不改变萌发积温，也不提供霜冻存活模型。原生参数会影响所有生育阶段，因此把苗期证据延伸到全季的部分同样属于未验证假设。

[Wang 等（2022）](https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2021.809692/full)使用黑农44与黑农65进行始花期盆栽水分梯度实验，作为耐旱、干旱敏感对照。档案分别指定原生 `DEPNR=5`、`DEPNR=2`。[PCSE 的 SWEAF 定义](https://pcse.readthedocs.io/en/stable/_modules/pcse/crop/evapotranspiration.html)将1至5定义为干旱敏感至耐旱作物组；具体的5与2是工程分组，不能解释为该论文标定出的品种参数。土壤水量平衡、临界含水量和蒸腾胁迫仍由原生模型计算。

两个原始数据包位于 `fairy/physics/data/wofost/observations/`，保存出处、实验设置、实测评价分数和不确定性。干旱论文的方法文字与表头对第3、4天含水量的顺序有冲突；数据包保留表头顺序并登记冲突，没有自动修正。盆栽持水量不会替换场景土壤参数。

所有其他参数均逐项复制自已有、固定版本的 `Soybean_901`，包含热时间、根系、氮素和碳分配。它们保持共同基线，没有额外乘产量、强制成熟或绕过收获条件。因此档案提供的是“有原始品种对照依据的可执行工程参考”，不能用于宣称本地实际产量预测精度。

## 配置与查询

```python
from fairy.physics.wofost_profiles import REFERENCE_CULTIVAR_PROFILES

farm.configure_crop_backend(
    "wofost",
    cultivar_profiles=dict(REFERENCE_CULTIVAR_PROFILES),
    require_explicit_cultivar_parameters=True,
)
```

`cultivar_profiles`按种子标识选择独立档案；每个原生地块状态保存自己实际使用的参数和来源指纹。`get_seed_trait_reference(seed_type)`提供证据、有效范围和原生响应设置，但不会替场景自动选择模型。库存必须显式配置新种子数量；原有默认库存不额外产生四种物料。

旧简化引擎只为这四个标识保留原 `STANDARD` 数值作为兼容接口，不能重现这里的原生耐性对照。场景要获得上述差异，必须显式选择 WOFOST 和相应档案。

## 可重现的原生对照

```bash
uv run --extra wofost python scripts/audit_wofost_soybean_traits.py \
  --output-dir validation_runs/wofost_trait_references_20261024
```

脚本固定土壤、播期、密度与非目标参数，执行十条160天原生轨迹，输出逐日状态与参数指纹。四种品种在温暖、供水正常条件下得到完全相同的原生干物质产量；低温对照和干旱对照产生差异，两种干旱档案对相同补水均有响应。

低温基准采用低夜温，和论文恒定4℃培养箱不是同一实验。低温也会延长原生生育期，因此最终产量不保证低于温暖对照，不能把“耐性更强”解释为所有环境下产量都更高。这些轨迹验证参数确实进入模型，不构成田间验证或自主 Agent 测试。
