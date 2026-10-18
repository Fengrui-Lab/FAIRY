# English task texts – review (APPROVED by the user)

Each block shows the Chinese task the LLM agent received (detailed briefing is on) and the English draft. Both agents will get the English text.

Rules followed:
- Translate faithfully. Do not add, remove or reword steps.
- Keep every number exactly as written. Numbers found in the English match the Chinese in all 15 files, except '30万' → 300000 (the same value).
- Typos are flagged below rather than silently fixed.

`scenario_farm_world_field_prep` was approved earlier and is included for completeness.

## scenario_farm_world_drone_survey

> **Flag:** Step 5: the original says "用 继续飞", 'use [missing word] to continue flying'. Translated as 'continue flying'.

**Chinese (original)**

```text
作物已进入V4生长阶段（播种后约42天），需要进行例行无人机巡查监测作物健康。
请按以下步骤操作：
1. 查看天气，确认无雨且风速<12m/s（无人机飞行条件）。
2. Mavic3M 检查无人机电量（当前约65%，不满）。
3. 飞行巡查全部64垄。飞到电量不足时会自动返航，返回部分结果。
4. 返航后，检查无人机状态，给无人机充电（约30分钟）。
5. 充电完成后用 继续飞剩余未覆盖的区域。
6. 全部飞完后，如果发现NDVI偏低的区域，然后派机器狗到异常垄做地面巡检确认病虫害，执行前先检查机器狗Robot0电量，。
7. 全部完成后立即结束任务向我汇报巡查结果。
```

**English (draft)**

```text
The crop has reached the V4 growth stage (about 42 days after sowing); a routine drone inspection is needed to monitor crop health.
Follow these steps:
1. Check the weather and confirm there is no rain and wind speed < 12m/s (drone flight conditions).
2. Mavic3M: check the drone's battery (currently about 65%, not full).
3. Fly an inspection survey over all 64 ridges. When the battery runs low, the drone returns automatically and gives partial results.
4. After it returns, check the drone's status and charge the drone (about 30 minutes).
5. After charging is complete, continue flying the remaining uncovered area.
6. When all flights are done, if areas with low NDVI are found, send the robot dog to the abnormal ridges for a ground inspection to confirm pests or disease; before doing so, first check robot dog Robot0's battery.
7. When everything is done, end the task immediately and report the inspection results to me.
```

## scenario_farm_world_drone_survey_plus

**Chinese (original)**

```text
作物已进入V4生长阶段（播种后约42天），需要进行例行无人机巡查监测作物健康。
请严格按以下步骤操作：
1. 查看天气，确认无雨且风速<12m/s（无人机飞行条件）。
2. 如果风速过大不能飞，查看近3天预报评估风速变化趋势，等待风速降低后再飞（大概3小时后风会变小）。
3. 收到风速变小的通知后，查看天气确认无雨且风速<12m/s，检查Mavic3M无人机电量。
4. 飞行巡查全部64垄。飞到电量不足时会自动返航，返回部分结果。
5. 返航后，检查无人机状态，给无人机充电（约30分钟）。
6. 充电完成后继续飞剩余未覆盖的区域。
7. 全部飞完后，如果发现NDVI偏低的区域，派机器狗到异常垄做地面巡检确认病虫害，执行前先检查机器狗Robot0电量。
8. 全部完成后立即结束任务向我汇报巡查结果。
```

**English (draft)**

```text
The crop has reached the V4 growth stage (about 42 days after sowing); a routine drone inspection is needed to monitor crop health.
Follow these steps strictly:
1. Check the weather and confirm there is no rain and wind speed < 12m/s (drone flight conditions).
2. If the wind is too strong to fly, check the forecast for the next 3 days to assess how the wind speed will change, and wait for the wind to drop before flying (the wind should ease in about 3 hours).
3. After receiving the notification that the wind has dropped, check the weather to confirm there is no rain and wind speed < 12m/s, and check the Mavic3M drone's battery.
4. Fly an inspection survey over all 64 ridges. When the battery runs low, the drone returns automatically and gives partial results.
5. After it returns, check the drone's status and charge the drone (about 30 minutes).
6. After charging is complete, continue flying the remaining uncovered area.
7. When all flights are done, if areas with low NDVI are found, send the robot dog to the abnormal ridges for a ground inspection to confirm pests or disease; before doing so, first check robot dog Robot0's battery.
8. When everything is done, end the task immediately and report the inspection results to me.
```

## scenario_farm_world_fertilizer

**Chinese (original)**

```text
作物已进入V3-V4生长阶段（播种后约35天），冠层传感器显示部分区域NDVI偏低，怀疑营养缺乏。
由于大豆固氮作用，氮肥需求较低，但磷钾平衡仍影响产量。
请按以下步骤操作：
1. 查看当前天气，确认适合下地作业（无雨）。
2. 查看未来3天预报，确认作业窗口。
3. 读取冠层传感器，找出NDVI偏低的区域。
4. 检查Mavic3M状态，飞行巡查异常区域确认缺肥情况。
5. 检查拖拉机状态（油量、施肥机）和仓库肥料库存。
6. 装载肥料100kg，对缺肥区（NDVI小于0.45）域追施肥料（每垄约10kg）。
7. 全部完成后立即结束任务向我汇报。
```

**English (draft)**

```text
The crop has reached the V3-V4 growth stage (about 35 days after sowing). The canopy sensors show low NDVI in some areas; a nutrient deficiency is suspected.
Because soybeans fix their own nitrogen, nitrogen demand is low, but the phosphorus-potassium balance still affects yield.
Follow these steps:
1. Check the current weather and confirm it is suitable for field work (no rain).
2. Check the forecast for the next 3 days to confirm the work window.
3. Read the canopy sensors and find the areas with low NDVI.
4. Check the Mavic3M status and fly a survey over the abnormal areas to confirm the nutrient deficiency.
5. Check the tractor status (fuel, fertilizer spreader) and the warehouse fertilizer stock.
6. Load 100kg of fertilizer and top-dress the deficient areas (NDVI less than 0.45) (about 10kg per ridge).
7. When everything is done, end the task immediately and report to me.
```

## scenario_farm_world_field_prep  (approved)

**Chinese (original)**

```text
农场进入种植前准备阶段，今天需要完成全部整地工作。
请按以下步骤操作：
1. 查看今天天气，确认无雨可以下地。
2. 查看 3 天天气预报（后天有雨 → 今天必须做完）。
3. 读取土壤传感器，确认土壤 VWC < 0.35（拖拉机可通行）。
4. 检查拖拉机油量和挂接状态。
5. 查看仓库库存，确认化肥和柴油充足。
6. 平整地面：先挂接平地机，然后旋耕平整全田（平地机宽 3m，速度 3 km/h），完成后卸下平地机。
7. 施基肥：从仓库装载 200 kg 化肥到施肥机，然后全田撒施（撒播机宽 6 m，速度 6 km/h）。
8. 起垄：挂接开沟机，起垄（垄宽 1.1 m，4 垄/趟，速度 4 km/h），做完后卸下开沟机。
9. 全部完成后立即结束任务向我汇报。
```

**English (draft)**

```text
The farm is entering the pre-planting preparation stage; all field preparation must be finished today. Follow these steps:
1. Check today's weather and confirm there is no rain, so the field can be worked.
2. Check the 3-day forecast (rain the day after tomorrow -> everything must be finished today).
3. Read the soil sensors and confirm soil VWC < 0.35 (the tractor can drive on it).
4. Check the tractor's fuel level and which implement is attached.
5. Check the warehouse inventory and confirm there is enough fertilizer and diesel.
6. Level the ground: first attach the grader, then rotary-till and level the whole field (grader width 3 m, speed 3 km/h); when finished, detach the grader.
7. Apply base fertilizer: load 200 kg of fertilizer from the warehouse into the spreader, then spread it over the whole field (spreader width 6 m, speed 6 km/h).
8. Form ridges: attach the furrower and form the ridges (ridge width 1.1 m, 4 ridges per pass, speed 4 km/h); when finished, detach the furrower.
9. When everything is done, end the task immediately and report to me.
```

## scenario_farm_world_field_prep_planting

> **Flag:** '30万株' = 300,000 plants → written as 300000 (no comma). Step 9: '建议加50.0油' has no unit in the original → 'adding 50.0 of fuel'.

**Chinese (original)**

```text
天气窗口只有今明两天（后天下雨），今天必须把整地和播种全部完成。
请按以下步骤操作：

【整地阶段】
1. 查看今天天气，确认无雨可以下地。
2. 查看3天天气预报。
3. 读取土壤传感器，确认VWC<0.35（拖拉机可通行）且土壤温度>10°C（适合播种）。
4. 检查拖拉机油量（当前60L）和挂接状态。
5. 查看仓库库存，确认化肥、种子和柴油充足。
6. 平整地面：挂接平地机→旋耕平整全田→卸下平地机。
7. 施基肥：装载200kg化肥→全田撒施。
8. 起垄：挂接开沟机→起垄（垄宽1.1m）→卸下开沟机。

【播种阶段】
9. 检查拖拉机油量，建议加50.0油。
10. 装载第一批种子（料斗最大30万株）。
11. 逐批播种，每次4条垄（0-3, 4-7, ...），播深4cm，株距5cm。
12. 种子不够了再装下一批。
13. 全部64垄播完后立即结束任务向我汇报。
```

**English (draft)**

```text
The weather window is only today and tomorrow (rain the day after tomorrow); field preparation and sowing must both be completed today.
Follow these steps:

[Field preparation stage]
1. Check today's weather and confirm there is no rain, so the field can be worked.
2. Check the 3-day weather forecast.
3. Read the soil sensors and confirm VWC<0.35 (the tractor can drive on it) and soil temperature >10°C (suitable for sowing).
4. Check the tractor's fuel level (currently 60L) and which implement is attached.
5. Check the warehouse inventory and confirm there is enough fertilizer, seed and diesel.
6. Level the ground: attach the grader -> rotary-till and level the whole field -> detach the grader.
7. Apply base fertilizer: load 200kg of fertilizer -> spread it over the whole field.
8. Form ridges: attach the furrower -> form the ridges (ridge width 1.1m) -> detach the furrower.

[Sowing stage]
9. Check the tractor's fuel level; adding 50.0 of fuel is recommended.
10. Load the first batch of seeds (hopper maximum 300000 plants).
11. Sow batch by batch, 4 ridges at a time (0-3, 4-7, ...), sowing depth 4cm, plant spacing 5cm.
12. When the seeds run out, load the next batch.
13. When all 64 ridges are sown, end the task immediately and report to me.
```

## scenario_farm_world_field_prep_plus

> **Flag:** Step 3: the original sentence is cut off: "请等待土壤传感器关于。" ('please wait for the soil sensor about.'). Fixed as the user decided: 'please wait for the soil sensor notification.'

**Chinese (original)**

```text
农场进入种植前准备阶段，今天需要完成全部整地工作。
请按以下步骤操作：
1. 查看今天天气，确认无雨可以下地。
2. 查看 3 天天气预报。
3. 读取土壤传感器，确认土壤 VWC < 0.35（拖拉机可通行）。如果土壤过湿，请等待土壤传感器关于。
4. 检查拖拉机油量和挂接状态。注意油量是否足够完成全部整地工作（平整8L+施肥8L+起垄8L=24L）。
5. 查看仓库库存，确认化肥和柴油充足。
6. 平整地面：先挂接平地机，然后旋耕平整全田，完成后卸下平地机。
7. 施基肥：从仓库装载 200 kg 化肥到施肥机，然后全田撒施。
8. 如果油量不足以完成起垄，先加油。
9. 起垄：挂接开沟机，起垄（垄宽 1.1 m），做完后卸下开沟机。
10. 全部完成后立即结束任务向我汇报。
```

**English (draft)**

```text
The farm is entering the pre-planting preparation stage; all field preparation must be finished today.
Follow these steps:
1. Check today's weather and confirm there is no rain, so the field can be worked.
2. Check the 3-day weather forecast.
3. Read the soil sensors and confirm soil VWC < 0.35 (the tractor can drive on it). If the soil is too wet, please wait for the soil sensor notification.
4. Check the tractor's fuel level and which implement is attached. Check whether there is enough fuel to finish all the field preparation (leveling 8L + fertilizing 8L + ridging 8L = 24L).
5. Check the warehouse inventory and confirm there is enough fertilizer and diesel.
6. Level the ground: first attach the grader, then rotary-till and level the whole field; when finished, detach the grader.
7. Apply base fertilizer: load 200 kg of fertilizer from the warehouse into the spreader, then spread it over the whole field.
8. If there is not enough fuel to form the ridges, refuel first.
9. Form ridges: attach the furrower and form the ridges (ridge width 1.1 m); when finished, detach the furrower.
10. When everything is done, end the task immediately and report to me.
```

## scenario_farm_world_harvest

> **Flag:** English words in the original (rainfall=0, fly_survey, refuel, unload_grain, inventory) kept as they are.

**Chinese (original)**

```text
大豆已成熟，进入收获阶段。请按真实农民流程操作：
1. 查看今天天气（rainfall=0，可收割）和 3 天预报
2. 读土壤传感器，确认 VWC<0.35、地面可通行。
3. 读冠层传感器，看 NDVI 是否全田枯黄（R8 应该偏低）。
4. 确认所有 64 条垄都到 R8 且籽粒含水 13-18%。
5. 用 Mavic3M 飞一圈（fly_survey 0-63）验证均匀成熟。
6. 检查拖拉机状态：先挂接收割机,油只有 20 L → 再refuel 到 100 L。
7. 一趟 4 垄，共 16 趟，从 0-3 开始到 60-63。
   每趟约 980 kg 粮食进入储罐（容量 2000 kg），
   所以每 2 趟就要 unload_grain 一次把粮食卸到仓库。
8. 全部收割完 + 卸完粮后，卸载收割机，看 inventory 汇报总产量。
9. 全部完成后立即结束任务向我汇报。
```

**English (draft)**

```text
The soybeans are mature and the harvest stage has begun. Please follow a real farmer's workflow:
1. Check today's weather (rainfall=0, harvesting possible) and the 3-day forecast
2. Read the soil sensors and confirm VWC<0.35, so the ground can be driven on.
3. Read the canopy sensors and see whether NDVI shows the whole field has turned yellow (at R8 it should be low).
4. Confirm that all 64 ridges have reached R8 and the grain moisture is 13-18%.
5. Fly the Mavic3M over the field once (fly_survey 0-63) to verify even ripening.
6. Check the tractor status: first attach the harvester; the fuel is only 20 L -> then refuel to 100 L.
7. 4 ridges per pass, 16 passes in total, starting from 0-3 up to 60-63.
   Each pass puts about 980 kg of grain into the grain tank (capacity 2000 kg),
   so every 2 passes you must unload_grain once to unload the grain into the warehouse.
8. After everything is harvested and all grain is unloaded, detach the harvester, check the inventory and report the total yield.
9. When everything is done, end the task immediately and report to me.
```

## scenario_farm_world_irrigation

**Chinese (original)**

```text
作物已进入V2生长阶段（播种后约22天），最近持续干旱无雨。
请按以下步骤操作：
1. 查看今天天气。
2. 查看未来3天预报，如果近期有雨就不用灌溉了，让天然降雨补充水分。
3. 读取6个土壤传感器，找出VWC < 0.20的干旱区域（正常应在0.20-0.30之间）。
4. 对干旱区域灌溉1.5小时。灌溉会使土壤VWC增加约0.08。
5. 灌溉后等待系统在约2小时后发送通知，再次读取传感器，确认土壤湿度已恢复到正常范围。
6. 全部完成后立即结束任务向我汇报灌溉完成情况。
```

**English (draft)**

```text
The crop has reached the V2 growth stage (about 22 days after sowing), and there has been a long dry spell with no rain recently.
Follow these steps:
1. Check today's weather.
2. Check the forecast for the next 3 days; if rain is coming soon, there is no need to irrigate, let natural rainfall replenish the moisture.
3. Read the 6 soil sensors and find the dry areas with VWC < 0.20 (normal is between 0.20-0.30).
4. Irrigate the dry areas for 1.5 hours. Irrigation increases soil VWC by about 0.08.
5. After irrigating, wait for the system to send a notification in about 2 hours, then read the sensors again to confirm soil moisture has returned to the normal range.
6. When everything is done, end the task immediately and report to me on the irrigation.
```

## scenario_farm_world_pesticide

**Chinese (original)**

```text
昨天 Mavic3M 巡查发现 ridges 15-25 区域 NDVI 偏低，怀疑蚜虫爆发。
今天请按如下流程处理：
1. 查看当前天气，确认风速<5 m/s、无雨（喷药条件）。
2. 看 3 天预报，确认今天和明天的喷药窗口。
3. 读冠层传感器，再看一下 NDVI 分布。
4. 先使用Mavic3M核查异常区，使用前先检查机器状态。
5. 读土壤传感器，确认 VWC<0.35（机器狗可下地）。
6. 再使用Robot0地面复核Mavic3M报告的异常区域，使用前先检查机器状态。
7. 人工对异常点施药。
8. 全部完成立即结束任务后汇报。
```

**English (draft)**

```text
Yesterday the Mavic3M survey found low NDVI in the ridges 15-25 area; an aphid outbreak is suspected.
Today please handle it with the following process:
1. Check the current weather and confirm wind speed <5 m/s and no rain (spraying conditions).
2. Check the 3-day forecast to confirm the spraying window for today and tomorrow.
3. Read the canopy sensors and look at the NDVI distribution again.
4. First use the Mavic3M to check the abnormal area; check the machine's status before using it.
5. Read the soil sensors and confirm VWC<0.35 (the robot dog can go into the field).
6. Then use Robot0 to re-check on the ground the abnormal areas reported by the Mavic3M; check the machine's status before using it.
7. Apply pesticide manually to the abnormal spots.
8. When everything is done, end the task immediately and then report.
```

## scenario_farm_world_pesticide_outbreak

**Chinese (original)**

```text
作物已进入V4-V5生长阶段（播种后约45天），固定传感器显示多个区域NDVI异常偏低，怀疑大面积蚜虫爆发。
请按以下步骤操作：
1. 查看当前天气，确认风速<5m/s、无雨（喷药条件）。
2. 查看未来3天预报，确认喷药窗口（后天有雨，今天必须喷）。
3. 读取冠层传感器，找出NDVI偏低的区域。
4. 检查Mavic3M状态，飞行巡查异常区域确认虫害范围。
5. 读取土壤传感器，确认VWC<0.35（拖拉机可下地）。
6. 检查Robot0状态，派机器狗到虫害中心区域地面复核确认蚜虫。
7. 检查拖拉机状态和仓库库存。
8. 给拖拉机装载喷药器、 加80.0L油、装250.0L药。
9. 用拖拉机喷杆分多趟喷药（每趟最多10垄），覆盖全部虫害区域。
10. 全部完成后卸载喷药器、立即结束任务向我汇报。
```

**English (draft)**

```text
The crop has reached the V4-V5 growth stage (about 45 days after sowing). The fixed sensors show abnormally low NDVI in several areas; a large-scale aphid outbreak is suspected.
Follow these steps:
1. Check the current weather and confirm wind speed <5m/s and no rain (spraying conditions).
2. Check the forecast for the next 3 days to confirm the spraying window (rain the day after tomorrow, so spraying must be done today).
3. Read the canopy sensors and find the areas with low NDVI.
4. Check the Mavic3M status and fly a survey over the abnormal areas to confirm the extent of the pest damage.
5. Read the soil sensors and confirm VWC<0.35 (the tractor can go into the field).
6. Check Robot0's status and send the robot dog to the centre of the infested area for a ground re-check to confirm aphids.
7. Check the tractor status and the warehouse inventory.
8. Fit the sprayer to the tractor, add 80.0L of fuel, and load 250.0L of pesticide.
9. Spray with the tractor's boom in several passes (at most 10 ridges per pass), covering all infested areas.
10. When everything is done, detach the sprayer, end the task immediately and report to me.
```

## scenario_farm_world_pesticide_outbreak_plus

> **Flag:** Step 6: "剩余未区域" is missing a word ('remaining un- areas') → 'remaining areas not yet re-checked'. Step 9: "按喷药" is garbled ('according to spraying') → left out: 'Spray with the tractor's boom (at most 10 ridges per pass)'.

**Chinese (original)**

```text
作物已进入V4-V5生长阶段（播种后约45天），固定传感器显示多个区域NDVI异常偏低，怀疑大面积蚜虫爆发。
在今天完成巡查、复核和喷药处理。
请按以下步骤操作：
1. 查看当前天气，确认风速<5m/s、无雨（喷药条件）。
2. 查看未来3天预报，确认喷药窗口。
3. 读取冠层传感器，找出NDVI偏低的区域。
4. 检查Mavic3M状态，对冠层传感器提示的异常带进行航测，确认虫害范围；如果因电量不足中途返航，给无人机充电（约30分钟）。
   充电完成后继续飞剩余未覆盖的区域。
5. 读取土壤传感器，确认VWC<0.35（拖拉机可下地）。
6. 检查Robot0状态，用Robot0沿无人机确认的连续虫害带做6个地面复核点：从低垄号到高垄号按约5垄间距抽样，避开未见虫的缓冲垄，并在中心热点附近加密，确认是否为蚜虫；
    如果电量不足，给Robot0充电（约60分钟）。充电完成后继续复核剩余未区域。
7. 检查拖拉机状态和仓库库存。
8. 给拖拉机挂接喷药器，加80.0L油，再向喷药箱装250.0L药。
9. 用拖拉机喷杆按喷药（每趟最多10垄），覆盖全部虫害区域。
10. 全部完成后卸载喷药器、立即结束任务向我汇报。
```

**English (draft)**

```text
The crop has reached the V4-V5 growth stage (about 45 days after sowing). The fixed sensors show abnormally low NDVI in several areas; a large-scale aphid outbreak is suspected.
Complete the inspection, re-check and spraying today.
Follow these steps:
1. Check the current weather and confirm wind speed <5m/s and no rain (spraying conditions).
2. Check the forecast for the next 3 days to confirm the spraying window.
3. Read the canopy sensors and find the areas with low NDVI.
4. Check the Mavic3M status and fly an aerial survey over the abnormal strip indicated by the canopy sensors to confirm the extent of the pest damage; if it returns early because of low battery, charge the drone (about 30 minutes).
   After charging is complete, continue flying the remaining uncovered area.
5. Read the soil sensors and confirm VWC<0.35 (the tractor can go into the field).
6. Check Robot0's status and use Robot0 to make 6 ground re-check points along the continuous infested strip confirmed by the drone: sample from low to high ridge numbers at a spacing of about 5 ridges, avoid the buffer ridges where no pests were seen, and sample more densely near the central hotspot, to confirm whether it is aphids;
    if the battery is low, charge Robot0 (about 60 minutes). After charging is complete, continue re-checking the remaining areas not yet re-checked.
7. Check the tractor status and the warehouse inventory.
8. Attach the sprayer to the tractor, add 80.0L of fuel, then load 250.0L of pesticide into the spray tank.
9. Spray with the tractor's boom (at most 10 ridges per pass), covering all infested areas.
10. When everything is done, detach the sprayer, end the task immediately and report to me.
```

## scenario_farm_world_planting

> **Flag:** '30万株' = 300,000 plants → written as 300000 (no comma).

**Chinese (original)**

```text
整地已完成（平整、施基肥、起垄），今天开始播种大豆。
请按以下步骤操作：
1. 查看今天天气，确认无雨；
2. 读取土壤传感器，确认VWC在0.20-0.30之间、土壤温度>10°C（适合播种）。
3. 检查拖拉机油量（当前80L，不满）和料斗状态。
4. 查看仓库种子库存。
5. 装载第一批种子（料斗最大30万株）。
6. 逐批播种，每次4条垄（如0-3, 4-7, ...）。播深4cm，株距5cm。。
7. 种子不够了，再装下一批。
8. 全部64垄播完后立即结束任务向我汇报。
```

**English (draft)**

```text
Field preparation is complete (leveling, base fertilizer, ridging); sowing soybeans starts today.
Follow these steps:
1. Check today's weather and confirm there is no rain;
2. Read the soil sensors and confirm VWC is between 0.20-0.30 and soil temperature >10°C (suitable for sowing).
3. Check the tractor's fuel level (currently 80L, not full) and the hopper status.
4. Check the warehouse seed stock.
5. Load the first batch of seeds (hopper maximum 300000 plants).
6. Sow batch by batch, 4 ridges at a time (e.g. 0-3, 4-7, ...). Sowing depth 4cm, plant spacing 5cm.
7. When the seeds run out, load the next batch.
8. When all 64 ridges are sown, end the task immediately and report to me.
```

## scenario_farm_world_planting_plus

> **Flag:** '30万株' = 300,000 plants → written as 300000 (no comma).

**Chinese (original)**

```text
整地已完成（平整、施基肥、起垄），今天开始播种大豆。
请按以下步骤操作：
1. 查看今天天气，确认是否适合播种；
2. 如果当前天气不适合（比如下雨 影响拖拉机作业），查看未来3天天气预报，评估天气趋势；
3. 等待天气好转后继续。
4. 读取土壤传感器，确认VWC在0.20-0.30之间、土壤温度>10°C（适合播种）。
5. 条件合适后，检查拖拉机油量和料斗状态。
6. 查看仓库种子库存。
7. 装载第一批种子（料斗最大30万株）。
8. 逐批播种，每次4条垄（如0-3, 4-7, ...）。播深4cm，株距5cm。
9. 种子不够了，再装下一批。
10. 全部64垄播完后立即结束任务向我汇报。
```

**English (draft)**

```text
Field preparation is complete (leveling, base fertilizer, ridging); sowing soybeans starts today.
Follow these steps:
1. Check today's weather and confirm whether it is suitable for sowing;
2. If the current weather is not suitable (for example rain affecting tractor work), check the 3-day weather forecast to assess the weather trend;
3. Wait for the weather to improve, then continue.
4. Read the soil sensors and confirm VWC is between 0.20-0.30 and soil temperature >10°C (suitable for sowing).
5. Once conditions are suitable, check the tractor's fuel level and the hopper status.
6. Check the warehouse seed stock.
7. Load the first batch of seeds (hopper maximum 300000 plants).
8. Sow batch by batch, 4 ridges at a time (e.g. 0-3, 4-7, ...). Sowing depth 4cm, plant spacing 5cm.
9. When the seeds run out, load the next batch.
10. When all 64 ridges are sown, end the task immediately and report to me.
```

## scenario_farm_world_survey_fertilizer_irrigation

**Chinese (original)**

```text
作物已进入V3生长阶段（播种后约35天），今天需要完成例行巡查，并处理发现的问题。
请按以下步骤操作：

【固定传感器监测阶段】
1. 查看今天天气，确认无雨且风速<12m/s（无人机飞行条件）。
2. 读取冠层传感器（6个固定传感器持续监测），发现C3和C5区域NDVI偏低。
3. 读取土壤传感器（6个固定传感器），发现S5区域VWC偏低（<0.20）。

【无人机航空巡查阶段】
4. 检查Mavic3M无人机电量（当前约65%，不满）。
5. 飞行巡查全部64垄，定位异常区域范围。飞到电量不足时会自动返航，返回部分结果。
6. 返航后，检查无人机状态，给无人机充电（约30分钟）。
7. 充电完成后继续飞剩余未覆盖的区域。
8. 分析巡查结果，确认两个问题：
   - ridges 22-27区域NDVI偏低（0.40-0.48），怀疑营养缺乏
   - ridges 40-50区域NDVI也偏低但不严重，可能是缺水

【地面确认阶段】
9. 检查Robot0状态，派机器狗到ridge 25做地面巡检，确认是营养问题不是虫害。

【追肥阶段】
10. 检查拖拉机状态（油量、施肥机）和仓库肥料库存。
11. 装载肥料100kg，对ridges 22-27追施肥料（每垄约10kg）。

【灌溉阶段】
12. 查看未来3天预报，如果近期无雨就需要灌溉。
13. 对ridges 40-50灌溉1.5小时。灌溉会使土壤VWC增加约0.08。
14. 灌溉后等待系统在约2小时后发送通知，再次读取传感器，确认土壤湿度已恢复到正常范围。
15. 全部完成后立即结束任务向我汇报。
```

**English (draft)**

```text
The crop has reached the V3 growth stage (about 35 days after sowing). Today a routine inspection must be completed, and any problems found must be dealt with.
Follow these steps:

[Fixed-sensor monitoring stage]
1. Check today's weather and confirm there is no rain and wind speed <12m/s (drone flight conditions).
2. Read the canopy sensors (6 fixed sensors monitor continuously); NDVI is found to be low in the C3 and C5 areas.
3. Read the soil sensors (6 fixed sensors); VWC is found to be low in the S5 area (<0.20).

[Drone aerial inspection stage]
4. Check the Mavic3M drone's battery (currently about 65%, not full).
5. Fly an inspection survey over all 64 ridges to locate the extent of the abnormal areas. When the battery runs low, the drone returns automatically and gives partial results.
6. After it returns, check the drone's status and charge the drone (about 30 minutes).
7. After charging is complete, continue flying the remaining uncovered area.
8. Analyse the survey results and confirm two problems:
   - NDVI is low in the ridges 22-27 area (0.40-0.48); a nutrient deficiency is suspected
   - NDVI is also low in the ridges 40-50 area but not severely; it may be a lack of water

[Ground confirmation stage]
9. Check Robot0's status and send the robot dog to ridge 25 for a ground inspection to confirm it is a nutrient problem, not pests.

[Top-dressing stage]
10. Check the tractor status (fuel, fertilizer spreader) and the warehouse fertilizer stock.
11. Load 100kg of fertilizer and top-dress ridges 22-27 (about 10kg per ridge).

[Irrigation stage]
12. Check the forecast for the next 3 days; if no rain is coming soon, irrigation is needed.
13. Irrigate ridges 40-50 for 1.5 hours. Irrigation increases soil VWC by about 0.08.
14. After irrigating, wait for the system to send a notification in about 2 hours, then read the sensors again to confirm soil moisture has returned to the normal range.
15. When everything is done, end the task immediately and report to me.
```

## scenario_farm_world_survey_pesticide_irrigation

> **Flag:** Step 3: typo "NDVIen e" → 'NDVI'.

**Chinese (original)**

```text
作物已进入V4生长阶段（播种后约42天），传感器报警NDVI异常，同时最近持续干旱。
今天需要完成诊断、喷药和灌溉。后天有雨，喷药必须今天完成（雨会冲掉药效）。
请按以下步骤操作：

【固定传感器监测阶段】
1. 查看当前天气，确认风速<5m/s、无雨（喷药条件）。
2. 查看3天预报（后天有雨→今天必须喷药）。
3. 读取冠层传感器（6个固定传感器），发现C3/C4区域NDVIen e偏低，怀疑虫害。
4. 读取土壤传感器（6个固定传感器），确认VWC<0.35（拖拉机可下地），同时发现S5/S6区域ridges 50-58干旱。

【无人机航空巡查阶段】
5. 检查Mavic3M状态（电量约90%），飞行巡查异常区域ridges 15-40，定位虫害范围。

【地面确认阶段】
6. 检查Robot0状态，派机器狗到ridge 27做地面复核确认蚜虫。

【喷药阶段】
7. 检查拖拉机状态（油量15L不够）和仓库库存。
8. 挂接喷药器，加油80L，装药200L。
9. 用拖拉机喷杆分2趟喷药（20-29, 30-35），覆盖全部虫害区域。
10. 卸载喷药器。

【灌溉阶段】
11. 对ridges 50-58灌溉1.5小时。
12. 灌溉后等待系统在约2小时后发送通知，再次读取传感器确认土壤湿度恢复。
13. 全部完成后立即结束任务向我汇报。
```

**English (draft)**

```text
The crop has reached the V4 growth stage (about 42 days after sowing). The sensors are raising an alarm about abnormal NDVI, and there has also been a long dry spell recently.
Today diagnosis, spraying and irrigation must be completed. Rain is coming the day after tomorrow, so spraying must be finished today (rain would wash the pesticide off).
Follow these steps:

[Fixed-sensor monitoring stage]
1. Check the current weather and confirm wind speed <5m/s and no rain (spraying conditions).
2. Check the 3-day forecast (rain the day after tomorrow -> spraying must be done today).
3. Read the canopy sensors (6 fixed sensors); NDVI is found to be low in the C3/C4 areas; pests are suspected.
4. Read the soil sensors (6 fixed sensors) and confirm VWC<0.35 (the tractor can go into the field); also, ridges 50-58 in the S5/S6 area are found to be dry.

[Drone aerial inspection stage]
5. Check the Mavic3M status (battery about 90%) and fly a survey over the abnormal area ridges 15-40 to locate the extent of the pest damage.

[Ground confirmation stage]
6. Check Robot0's status and send the robot dog to ridge 27 for a ground re-check to confirm aphids.

[Spraying stage]
7. Check the tractor status (fuel 15L, not enough) and the warehouse inventory.
8. Attach the sprayer, add 80L of fuel, load 200L of pesticide.
9. Spray with the tractor's boom in 2 passes (20-29, 30-35), covering all infested areas.
10. Detach the sprayer.

[Irrigation stage]
11. Irrigate ridges 50-58 for 1.5 hours.
12. After irrigating, wait for the system to send a notification in about 2 hours, then read the sensors again to confirm soil moisture has recovered.
13. When everything is done, end the task immediately and report to me.
```
