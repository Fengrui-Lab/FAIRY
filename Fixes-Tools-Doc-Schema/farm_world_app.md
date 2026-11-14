# farm_world_app.py

源文件：[fairy/apps/farm_world/farm_world_app.py](/Users/hanlinyuan/Documents/Codex_Projects/FAIRY/fairy/apps/farm_world/farm_world_app.py)。共 8 个工具；以下为审阅稿。

## FarmWorldApp.get_farm_overview

能力边界：查看农场日期、管理阶段标签、基础库存及各垄的播种、收获、生育阶段和籽粒水分概况。管理阶段标签不等同于实时作物生育阶段。

```python
"""
Description:
    Return the recorded simulation date, farm phase, inventory, and each ridge's
    planting, harvest, growth-stage, and grain-moisture summary.

    Phase labels: prep = field preparation; planting = sowing; growing = crop growth;
    harvest = harvesting; full_season = whole season. These labels are not live crop
    stages.

    Stages: bare/BARE = no emerged standing crop; VE = emergence; V1-V8 = vegetative;
    R1-R8 = reproductive, with R7/R8 = beginning/full maturity.
"""
```

## FarmWorldApp.get_ridge_state

能力边界：查询一垄的作业与生长状态，不提供土壤读数或病虫害巡检结果。

```python
"""
Description:
    Return one ridge's operational state: planting, seed type, growth stage, grain
    moisture, and simulation days since planting or spraying.

    Stages: bare/BARE = no emerged standing crop; VE = emergence; V1-V8 = vegetative;
    R1-R8 = reproductive, with R7/R8 = beginning/full maturity.

    yield_potential = relative yield potential; stand_fraction = established plant
    fraction; ndvi_proxy = canopy greenness (-1 = unavailable).
    pesticide_applied_days_ago = -1 means no recorded spray.

Args:
    ridge_id: Zero-based ID of an existing ridge.
"""
```

## FarmWorldApp.get_ridge_range_state

能力边界：查询连续垄区间的作业与生长状态，字段与单垄查询一致，包含首尾垄。

```python
"""
Description:
    Return a contiguous ridge range's operational state: planting, seed type, growth
    stage, grain moisture, and simulation days since planting or spraying.

    Stages: bare/BARE = no emerged standing crop; VE = emergence; V1-V8 = vegetative;
    R1-R8 = reproductive, with R7/R8 = beginning/full maturity.

    yield_potential = relative yield potential; stand_fraction = established plant
    fraction; ndvi_proxy = canopy greenness (-1 = unavailable).
    pesticide_applied_days_ago = -1 means no recorded spray.

Args:
    start: Zero-based ID of the first existing ridge.
    end: Last existing ridge ID, inclusive; must be >= start.
"""
```

## FarmWorldApp.get_inventory

能力边界：查看仓库物资、拖车和仓储粮食、管理配额及使用量、烘干和仓储限制，不含拖拉机料箱余量。

```python
"""
Description:
    Return warehouse supplies, trailer and warehouse grain stocks,
    management limits/usage, and drying/storage requirements.
    Tractor onboard loads, including grain in the onboard bin, are excluded.
    harvest_grain_kg is trailer grain; warehouse_grain_kg is stored grain; null limits
    are unset.

    EARLY_COLD means early, cold-tolerant seed; HEIHE/HEINONG/HEIKE codes name
    cultivars. organic forbids chemical insecticide, fungicide, and herbicide;
    water_constrained labels water-saving management. Numeric quotas specify resource
    limits.
"""
```

## FarmWorldApp.commit_daily_physics

能力边界：启用土壤、作物等状态计算时推进一个仿真日并返回农场更新摘要；未启用时不操作。首次调用可能只完成初始化。

```python
"""
Description:
    Advance the simulation clock by one day and return the farm update summary. The
    first update may only initialize farm state, without a daily growth update. If soil/crop calculations are disabled, neither the clock nor farm state advances.
"""
```

## FarmWorldApp.apply_fertigation

能力边界：向连续垄施加养分和水，消耗仓库肥料及相应配额，返回用量，不额外推进仿真时间。未启用土壤、作物等状态计算时只扣除资源，不产生土壤或作物变化。

```python
"""
Description:
    Apply nutrients and carrier water to a ridge range using warehouse fertilizer and
    resource allowances; return treated ridges and resource use. Simulation time does
    not advance. If soil/crop calculations are disabled, resources are still consumed but soil
    and crops are unaffected.

Relation:
    Check get_inventory for available fertilizer and irrigation allowance.

Args:
    start_ridge: Zero-based ID of the first existing ridge.
    end_ridge: Last existing ridge ID, inclusive; must be >= start_ridge.
    nutrient_amount: Positive nutrient dose per ridge; 1.0 uses 30 kg of fertilizer per
        ridge.
    water_mm: Carrier-water depth per ridge in millimetres, >= 0. Quota use is this
        depth times the treated fraction of the field.
"""
```

## FarmWorldApp.dry_grain

能力边界：处理拖车中的整批粮食，受烘干容量限制；已符合安全入库水分时跳过，否则调至目标水分。不入库，也不推进仿真时间。

```python
"""
Description:
    Dry the whole trailer batch within drying capacity; skip if already safe for
    storage. Return batch details and target moisture or skipped status. Grain stays in
    the trailer; simulation time does not advance.

Relation:
    Check get_inventory for drying capacity and the storage moisture limit.
    Use TractorApp.unload_grain first if the grain to dry is still in the onboard bin.

Args:
    target_moisture_pct: Target grain moisture percentage, 11-16 inclusive and no higher
        than the storage limit; default 13.0.
"""
```

## FarmWorldApp.store_grain

能力边界：将拖车整批粮食转入仓库并清空拖车，受仓库容量限制；不烘干或推进仿真时间。未满足安全水分的粮食也可能入库并返回警告。

```python
"""
Description:
    Move the whole trailer batch into warehouse storage within capacity,
    emptying the trailer. Grain remaining in the tractor's onboard bin is not transferred.
    Return transferred mass, updated stocks, and batch moisture.
    No drying or simulation time advance occurs; unsafe grain may still
    be stored with a warning.

Relation:
    Use TractorApp.unload_grain first if the grain to store is still onboard.
    Use dry_grain first if the trailer batch needs drying for storage.
"""
```
