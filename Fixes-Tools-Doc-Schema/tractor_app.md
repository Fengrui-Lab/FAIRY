# tractor_app.py

源文件：[fairy/apps/farm_world/tractor_app.py](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/fairy/apps/farm_world/tractor_app.py)。共 23 个工具；以下为审阅稿。

## TractorApp.attach_implement

能力边界：挂接指定农具并返回名称；已有其他农具时须先卸下。

```python
"""
Description:
    Attach an implement and return its name. Use detach_implement first if a different
    implement is attached.

Args:
    implement: grader (levelling), furrower (furrowing), harvester (harvesting), sprayer
        (spraying), or cultivator (cultivation and weeding).
"""
```

## TractorApp.detach_implement

能力边界：卸下当前农具，返回卸下的农具名称。

```python
"""
Description:
    Detach the current tractor implement and return its name.
"""
```

## TractorApp.refuel

能力边界：为拖拉机补充作业燃油，从仓库转入车载容器并返回装载后余量；当前容量为 100 L，最多补至剩余空间允许的数量。实际装载量取请求量与剩余容量中的较小值。

```python
"""
Description:
    Replenish the tractor's fuel supply from warehouse stock for field work. Load the
    requested amount, capped by remaining capacity; return the updated load. Current
    fuel tank capacity: 100 L.

Args:
    liters: Requested fuel amount in litres; must be positive.
"""
```

## TractorApp.refill_pesticide_tank

能力边界：为拖拉机喷洒作业补充药液，从仓库转入车载容器并返回装载后余量；当前容量为 800 L，最多补至剩余空间允许的数量。实际装载量取请求量与剩余容量中的较小值。

```python
"""
Description:
    Replenish the tractor's pesticide supply from warehouse stock for field work. Load
    the requested amount, capped by remaining capacity; return the updated load. Current
    spray tank capacity: 800 L.

Args:
    liters: Requested pesticide amount in litres; must be positive.
"""
```

## TractorApp.load_fertilizer

能力边界：为拖拉机施肥作业装载肥料，从仓库转入车载容器并返回装载后余量；当前容量为 500 kg，最多补至剩余空间允许的数量。实际装载量取请求量与剩余容量中的较小值。

```python
"""
Description:
    Replenish the tractor's fertilizer supply from warehouse stock for field work. Load
    the requested amount, capped by remaining capacity; return the updated load. Current
    spreader capacity: 500 kg.

Args:
    kg: Requested fertilizer amount in kilograms; must be positive.
"""
```

## TractorApp.load_seeds

能力边界：为播种或补种准备种子，从仓库装载并设置整箱品种，返回品种和总量；当前总容量为 300000 粒，不分别保存不同品种。实际装载量取请求量与剩余容量中的较小值。

```python
"""
Description:
    Load warehouse seeds for sowing or replanting and set the whole hopper's seed type.
    Load the requested amount, capped by remaining capacity; return type and total load.
    Current hopper capacity: 300000 seeds.

Relation:
    Check FarmWorldApp.get_inventory for stock of the chosen seed type before loading.

Args:
    seed_type: STANDARD (standard), EARLY_COLD (early, cold-tolerant), HIGH_DENSITY
        (dense planting), STRESS_TOLERANT (stress-tolerant), or a named cultivar:
        HEIHE43, HEIHE50, HEINONG58, HEINONG60, HEINONG84, HEIKE71.
    count: Requested number of seeds; must be positive.
"""
```

## TractorApp.get_status

能力边界：查看拖拉机燃油、肥料、农药、种子、粮箱及农具状态；当前不返回独立杀菌剂箱余量。

```python
"""
Description:
    Return fuel, fertilizer, pesticide, seed and grain loads, grain-bin capacity, and
    attached/available implements. Fungicide level is omitted.

    grader = levelling attachment; EARLY_COLD = early, cold-tolerant seed;
    HEIHE/HEINONG/HEIKE codes name cultivars.
"""
```

## TractorApp.level

能力边界：完成播前全田平整准备，要求已挂接 grader 且地面可通行，消耗燃油和仿真时间，返回作业信息及剩余燃油。

```python
"""
Description:
    Prepare the whole field for planting by levelling with the attached grader on
    trafficable ground. Consume fuel and simulation time; return working width, duration
    in simulation minutes, and remaining fuel.

Relation:
    Use attach_implement to mount the grader if it is not already attached.
"""
```

## TractorApp.base_fertilize

能力边界：完成播前全田基肥准备，也是播种所需的准备项之一；当前消耗车载肥料 200 kg，并消耗燃油和仿真时间，返回用量及作业时长。

```python
"""
Description:
    Complete whole-field base fertilization required for planting, on trafficable
    ground. Currently uses 200 kg of onboard fertilizer, plus fuel and simulation time.
    Return fertilizer use, duration in simulation minutes, and remaining fuel.

Relation:
    Use load_fertilizer if the spreader lacks enough fertilizer for this operation.
"""
```

## TractorApp.form_ridges

能力边界：完成播前全田起垄准备，消耗燃油和仿真时间，返回垄宽、垄数和作业时长；会清除现有播种状态，但不改变垄数和编号。

```python
"""
Description:
    Prepare the whole field for sowing by forming ridges on trafficable ground. Clear
    existing planting records without changing ridge count. Consume fuel and simulation
    time; return ridge width, count, and duration in simulation minutes.

Args:
    ridge_width_m: Operating ridge width in metres; must be positive.
"""
```

## TractorApp.apply_fertilizer

能力边界：按目标垄和指定剂量施肥，要求地面可通行，消耗车载肥料、燃油和仿真时间，返回处理垄及用量；不能代替播前基肥准备项。

```python
"""
Description:
    Apply a chosen fertilizer dose to target ridges on trafficable ground. Consume
    onboard fertilizer, fuel, and simulation time; return treated ridges and fertilizer
    use. This does not complete the base-fertilization preparation required for
    planting.

Relation:
    Use load_fertilizer if onboard fertilizer is insufficient for the requested dose and
    range.

Args:
    start_ridge: Zero-based ID of the first existing ridge.
    end_ridge: Last existing ridge ID, inclusive; must be >= start_ridge; at most 10
        ridges.
    kg_per_ridge: Fertilizer mass per ridge in kilograms; must be positive.
"""
```

## TractorApp.plant_seeds

能力边界：用已装载种子播种空垄，须完成播前准备并处于允许播种窗口。当前按目标垄平均值判断：体积含水率 0.20—0.35（含边界）；EARLY_COLD 土温 ≥8°C，其他品种 >10°C。消耗种子、燃油和仿真时间，返回播种信息及用量。

```python
"""
Description:
    Sow loaded seeds on unplanted ridges after levelling, base fertilization, and ridge
    formation, within an allowed planting window. Current entry checks use target-ridge
    averages: VWC (volumetric water fraction) 0.20-0.35 inclusive; soil temperature >= 8°C for EARLY_COLD, > 10°C for other seeds. Consume seeds, fuel, and simulation time;
    return planted ridges, depth, spacing, and seed use.

Relation:
    Check soil sensors before deciding to sow.
    Use load_seeds if the chosen seed type or required quantity is not already loaded.

Args:
    start_ridge: Zero-based ID of the first existing ridge.
    end_ridge: Last existing ridge ID, inclusive; must be >= start_ridge; at most 4
        ridges.
    depth_cm: Sowing depth in centimetres, 3-5 inclusive.
    seed_spacing_cm: In-row seed spacing in centimetres; must be positive.
"""
```

## TractorApp.apply_pesticide

能力边界：以固定剂量进行目标垄杀虫处理，当前用量为每垄 8 L；消耗车载药液、燃油和仿真时间，受天气、通行和管理限制约束。

```python
"""
Description:
    Treat target ridges for insects with a fixed-dose spray when weather, ground, and
    management rules allow. Currently uses 8 L of onboard pesticide per ridge, plus fuel
    and simulation time. Return treated ridges and chemical use.

Relation:
    Use refill_pesticide_tank if the tank cannot supply the requested ridge range.

Args:
    start_ridge: Zero-based ID of the first existing ridge.
    end_ridge: Last existing ridge ID, inclusive; must be >= start_ridge; at most 10
        ridges.
"""
```

## TractorApp.load_pesticide

能力边界：为拖拉机喷洒作业补充药液，从仓库转入车载容器并返回装载后余量；当前容量为 800 L，最多补至剩余空间允许的数量。实际装载量取请求量与剩余容量中的较小值。

```python
"""
Description:
    Replenish the tractor's pesticide supply from warehouse stock for field work. Load
    the requested amount, capped by remaining capacity; return the updated load. Current
    spray tank capacity: 800 L. Equivalent to refill_pesticide_tank.

Args:
    liters: Requested pesticide amount in litres; must be positive.
"""
```

## TractorApp.spray_pesticide

能力边界：按指定剂量向最多 10 条连续垄喷杀虫剂，消耗车载药液、燃油和仿真时间，受天气、通行和管理限制约束。

```python
"""
Description:
    Spray insecticide when weather, ground, and management rules allow. Consume onboard
    pesticide, fuel, and simulation time; return treated ridges and chemical use.

Relation:
    Use load_pesticide if the tank cannot supply the chosen dose and ridge range.

Args:
    start_ridge: Zero-based ID of the first existing ridge.
    end_ridge: Last existing ridge ID, inclusive; must be >= start_ridge; at most 10
        ridges.
    liters_per_ridge: Insecticide volume per ridge in litres; must be positive. Default
        8.0.
"""
```

## TractorApp.load_fungicide

能力边界：为病害防治装载杀菌剂，从仓库共用农药库存转入独立药箱，返回装载后余量；当前容量为 800 L。实际装载量取请求量与剩余容量中的较小值。

```python
"""
Description:
    Load fungicide for disease treatment into its separate tank, using shared warehouse
    pesticide stock. Load the requested amount, capped by remaining capacity; return the
    updated load. Current tank capacity: 800 L.

Relation:
    Check FarmWorldApp.get_inventory for pesticide stock; fungicide loading uses this
    shared stock.

Args:
    liters: Requested fungicide volume in litres; must be positive.
"""
```

## TractorApp.apply_fungicide

能力边界：向最多 10 条连续垄喷杀菌剂，消耗独立杀菌剂箱药液、燃油和仿真时间，受天气、通行和管理限制约束。

```python
"""
Description:
    Spray fungicide when weather, ground, and management rules allow. Consume onboard
    fungicide, fuel, and simulation time; return treated ridges and fungicide use.

Relation:
    Use load_fungicide to replenish the separate fungicide tank if needed.

Args:
    start_ridge: Zero-based ID of the first existing ridge.
    end_ridge: Last existing ridge ID, inclusive; must be >= start_ridge; at most 10
        ridges.
    liters_per_ridge: Fungicide volume per ridge in litres; must be positive.
"""
```

## TractorApp.apply_herbicide

能力边界：向最多 10 条连续垄施用除草剂，使用普通农药箱，消耗燃油和仿真时间，受天气、通行和管理限制约束。

```python
"""
Description:
    Spray herbicide when weather, ground, and management rules allow. Consume onboard
    pesticide, fuel, and simulation time; return treated ridges and herbicide use.

Relation:
    Use load_pesticide to replenish the spray tank if needed.

Args:
    start_ridge: Zero-based ID of the first existing ridge.
    end_ridge: Last existing ridge ID, inclusive; must be >= start_ridge; at most 10
        ridges.
    liters_per_ridge: Herbicide volume per ridge in litres; must be positive.
"""
```

## TractorApp.mechanical_weed_control

能力边界：机械处理最多 10 条连续垄的杂草，消耗燃油和仿真时间，不消耗药剂；须满足地面通行、机械作业次数和处理垄数配额。

```python
"""
Description:
    Mechanically weed ridges on trafficable ground within machine-pass and treatment
    limits. Consume fuel and simulation time, without pesticide; return treated ridges
    and management usage.

Relation:
    Check FarmWorldApp.get_inventory for remaining management allowances.

Args:
    start_ridge: Zero-based ID of the first existing ridge.
    end_ridge: Last existing ridge ID, inclusive; must be >= start_ridge; at most 10
        ridges.
"""
```

## TractorApp.replant_seeds

能力边界：对缺苗或出苗失败的垄补苗或重新建植，消耗已装载种子、燃油和仿真时间；是否重置生育进程取决于当前出苗状态、模式及土壤作物计算是否启用。

```python
"""
Description:
    Repair poor or failed crop establishment by gap filling or re-sowing, using loaded
    seeds, fuel, and simulation time. With soil/crop calculations enabled, apply the
    requested gap-filling or restart behavior. Return seed use, before/after stand
    fractions (established plant fractions), and phenology_reset_ridges (ridges whose
    growth restarted).

Relation:
    Use RobotApp.inspect_emergence to assess the stand before replanting.

Args:
    start_ridge: Zero-based ID of the first existing ridge.
    end_ridge: Last existing ridge ID, inclusive; must be >= start_ridge; at most 4
        ridges.
    depth_cm: Sowing depth in centimetres, 3-5 inclusive.
    spacing_cm: In-row seed spacing in centimetres; must be positive.
    full_replant: True requests a fresh crop start. False fills gaps in emerged crops;
        unemerged crops may still restart. Default False.
"""
```

## TractorApp.incorporate_residue

能力边界：用于收获后的残茬还田管理，消耗燃油和仿真时间并返回处理垄号；当前不增加土壤碳或肥力指标，代码也未强制检查是否已经收获。

```python
"""
Description:
    Incorporate crop residue for post-harvest field management. Consume fuel and
    simulation time; return treated ridge IDs. This operation currently does not
    increase soil-carbon or fertility indicators.

Args:
    start_ridge: Zero-based ID of the first existing ridge.
    end_ridge: Last existing ridge ID, inclusive; must be >= start_ridge; at most 10
        ridges.
"""
```

## TractorApp.harvest

能力边界：收获成熟垄并将粮食收集到车载粮箱，消耗燃油和仿真时间；须满足成熟度、水分和作业条件，且粮箱有足够空间，当前容量为 2000 kg。

```python
"""
Description:
    Collect grain from mature ridges into the onboard bin. Requires R8 (full maturity),
    grain moisture <= 18%, no rain, trafficable ground, and sufficient bin space.
    Consume fuel and simulation time; return harvested ridges and collected grain mass.
    Current bin capacity: 2000 kg.

Relation:
    Check FarmWorldApp.get_ridge_range_state for maturity and grain moisture.
    Use unload_grain if the bin lacks space for the next harvest pass.

Args:
    start_ridge: Zero-based ID of the first existing ridge.
    end_ridge: Last existing ridge ID, inclusive; must be >= start_ridge; at most 4
        ridges.
"""
```

## TractorApp.unload_grain

能力边界：将已收获粮食从车载粮箱全部转运到拖车，清空粮箱以便继续收获或后续处理；当前耗时 8 个仿真分钟，不烘干或入库。

```python
"""
Description:
    Transfer all harvested grain from the onboard bin to the trailer, freeing the bin
    for further harvesting. Return unloaded mass and empty-bin status. Currently takes 8
    simulation minutes; no drying or warehouse storage occurs.
"""
```
