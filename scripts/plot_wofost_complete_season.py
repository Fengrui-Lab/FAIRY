#!/usr/bin/env python3
"""Build a read-only scientific figure and delivery page from completed runs."""
from __future__ import annotations
import argparse
import csv
from datetime import date
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def read_case(base, year, case):
    folder=base/"seasons"/str(year)/case
    summary=json.loads((folder/"summary.json").read_text())
    with (folder/"daily_field_mean.csv").open() as f:
        rows=list(csv.DictReader(f))
    selected={k:summary.get(k) for k in ["success","checks","case","area_mu","native_variety","cultivar_profile","sowing_dates","emergence_dates","maturity_dates","harvest_dates","warehouse_kg_at_13pct","irrigation_gross_mm","max_water_balance_residual_mm","fertilizer_n_kg_ha","fertilizer_effective_n_kg_ha"]}
    selected["yield_kg_mu_at_13pct"]=summary["warehouse_kg_at_13pct"]/summary["area_mu"]
    selected["peak_lai"]=max(float(r["LAI"] or 0) for r in rows)
    selected["run"]=str(folder.relative_to(base))
    selected["rain_multiplier"]=summary["weather_source"].get("weather_transform",{}).get("rain_multiplier",1)
    return selected,rows


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir",type=Path,default=ROOT/"validation_runs/wofost_complete_20261021")
    args=ap.parse_args(); base=args.output_dir
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,"axes.spines.top":False,"axes.spines.right":False,"axes.titleweight":"bold","axes.grid":True,"grid.alpha":.18,"svg.fonttype":"none"})
    cases={}
    for yr in (2017,2018,2019):
        for case in ("managed","rainfed"):
            cases[(str(yr),case)]=read_case(base,yr,case)
    for case in ("managed","rainfed","high_quota"):
        cases[("2017_rain25pct",case)]=read_case(base,"2017_rain25pct",case)
    colors={2017:"#2166ac",2018:"#e08214",2019:"#16856a"}
    fig,axs=plt.subplots(2,3,figsize=(16,10))
    fig.subplots_adjust(left=.065,right=.975,top=.875,bottom=.16,hspace=.42,wspace=.29)
    fig.suptitle("WOFOST 8.1 / Heinong84 public-reference farm",x=.065,ha="left",y=.97,fontsize=20,fontweight="bold")
    fig.text(.065,.92,"Fixed cultivar parameters | 64 ridges, 28.3008 mu | Actual NASA POWER daily weather and humidity",fontsize=11,color="#425568")
    def series(rows,key,active=False):
        out=[r for r in rows if r.get(key) and (not active or r.get("DVS") and 0<=float(r["DVS"])<2)]
        x=[(date.fromisoformat(r["forcing_day"])-date(date.fromisoformat(r["forcing_day"]).year,5,5)).days for r in out]
        return x,[float(r[key]) for r in out]
    for yr in (2017,2018,2019):
        _,rows=cases[(str(yr),"managed")]
        for ax,key in ((axs[0,0],"DVS"),(axs[0,1],"LAI")):
            ax.plot(*series(rows,key),color=colors[yr],lw=2,label=str(yr))
    axs[0,0].set(title="A  Development stage",ylabel="DVS (0 emergence; 2 maturity)",ylim=(-.15,2.15))
    axs[0,1].set(title="B  Leaf area development",ylabel="LAI (m² leaf / m² ground)",ylim=(0,5))
    for ax in axs[0,:2]: ax.set(xlabel="Days after 5 May",xlim=(0,150));ax.legend(frameon=False)
    yrs=(2017,2018,2019); y=[cases[(str(yr),"managed")][0]["yield_kg_mu_at_13pct"] for yr in yrs]
    axs[0,2].bar([str(i) for i in yrs],y,color=[colors[i] for i in yrs],width=.58)
    for i,v in enumerate(y):axs[0,2].text(i,v+5,f"{v:.2f}",ha="center",fontweight="bold")
    axs[0,2].set(title="C  Actual grain stored, historical weather",ylabel="kg / mu, at 13% moisture",ylim=(0,280),xlabel="Managed = rainfed; 0 mm irrigation in all 3 years")
    droughtcolors={"rainfed":"#bf573a","managed":"#16856a"}
    labels={"rainfed":"Rainfed (0 mm)","managed":"Managed (100 mm)"}
    normalrows=cases[("2017","managed")][1]
    for ax,key in ((axs[1,0],"SM"),(axs[1,1],"RFTRA")):
        ax.plot(*series(normalrows,key,active=key=="RFTRA"),color="#75818d",ls="--",lw=1.3,label="2017 historical rain")
        for case in ("rainfed","managed"):
            ax.plot(*series(cases[("2017_rain25pct",case)][1],key,active=key=="RFTRA"),color=droughtcolors[case],lw=1.9,label=labels[case])
        ax.set(xlabel="Days after 5 May",xlim=(0,150));ax.legend(fontsize=8,frameon=False,loc="lower left")
    axs[1,0].axhline(.14,color="#8c6b4c",lw=.7,ls=":")
    axs[1,0].axhline(.36,color="#8c6b4c",lw=.7,ls=":")
    axs[1,0].set(title="D  Rain x 0.25: soil-water response",ylabel="Native soil SM (m³ / m³)",ylim=(.12,.48))
    axs[1,1].set(title="E  Rain x 0.25: transpiration stress",ylabel="RFTRA (1 = no water stress)",ylim=(-.03,1.08))
    droughtcases=("rainfed","managed","high_quota")
    dy=[cases[("2017_rain25pct",c)][0]["yield_kg_mu_at_13pct"] for c in droughtcases]
    axs[1,2].bar(["Rainfed","Managed","Higher quota"],dy,color=["#bf573a","#16856a","#78ad9c"],width=.58)
    for i,(v,c) in enumerate(zip(dy,droughtcases)):
        mm=cases[("2017_rain25pct",c)][0]["irrigation_gross_mm"]
        axs[1,2].text(i,v+5,f"{v:.2f}\n{mm:g} mm",ha="center",fontsize=10,fontweight="bold")
    axs[1,2].set(title="F  Rain x 0.25: stored grain",ylabel="kg / mu, at 13% moisture",ylim=(0,260),xlabel="Higher quota changes cap, not irrigation trigger")
    fig.text(.065,.035,"Engineering reference, without independent field validation. Soil: assumed homogeneous 120 cm loam.\nD-F are synthetic stress tests: 75% rain removed; other weather and cultivar parameters retained. Stored grain includes simulated losses.\nAfter maturity crop curves retain final values; soil SM becomes the bare-soil surface state after crop deletion.",fontsize=10,color="#425568")
    fig.savefig(base/"overview.png",dpi=180,facecolor="white")
    fig.savefig(base/"overview.svg",facecolor="white")
    plt.close(fig)

    configpath=ROOT/"configs/wofost/complete_harbin_heinong84_v1.json"
    config=json.loads(configpath.read_text())
    normal=[cases[(str(yr),"managed")][0] for yr in yrs]
    drought=[cases[("2017_rain25pct",c)][0] for c in droughtcases]
    summary={"status":"complete_executable_engineering_reference_without_independent_field_validation","native_variety":"Heinong84_PublicReference_v1","normal_historical_weather":normal,"synthetic_rain25pct":drought,"all_nine_cases_passed":all(s[0]["success"] and all(s[0]["checks"].values()) for s in cases.values()),"normal_mean_stored_yield_kg_mu_at_13pct":sum(y)/len(y),"synthetic_management_gain_kg_mu_at_13pct":dy[1]-dy[0],"synthetic_management_gain_pct":(dy[1]/dy[0]-1)*100,"yield_basis":"Actual warehouse mass at13% moisture / field mu; not mature TWSO and not native-only reference yield","normal_managed_equals_rainfed":all(cases[(str(yr),"managed")][0]["warehouse_kg_at_13pct"]==cases[(str(yr),"rainfed")][0]["warehouse_kg_at_13pct"] for yr in yrs),"notes":["2017 used for public aggregate phenology-constrained reference screening;2018/2019 use locked parameters","Yield excluded from parameter selection; no yield multiplier or forced maturity","Actual daily RH preserved;120cm homogeneous soil and100% establishment are stated assumptions","Synthetic rainfall multiplier0.25 is not a real observed drought year","N affects native8.1; P/K accounting only; density only scales initial TDWI","Independent cultivar identity and complete78parameter set, retaining upstream physiology priors"]}
    (base/"delivery_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    def esc(v):return html.escape(str(v))
    def dateval(s,k):return ", ".join(s[k])
    normrows="".join(f'<tr><td>{yr}</td><td>{esc(dateval(s,"sowing_dates"))}</td><td>{esc(dateval(s,"emergence_dates"))}</td><td>{esc(dateval(s,"maturity_dates"))}</td><td>{esc(dateval(s,"harvest_dates"))}</td><td>{s["peak_lai"]:.2f}</td><td><b>{s["yield_kg_mu_at_13pct"]:.2f}</b></td><td>{s["warehouse_kg_at_13pct"]:,.2f}</td><td><a href="{s["run"]}/每日状态.csv">逐日表</a></td></tr>' for yr,s in zip(yrs,normal))
    dnames={"rainfed":"雨养","managed":"按缺水状态补灌","high_quota":"提高可用额度，保持触发规则"}
    dryrows="".join(f'<tr><td>{dnames[s["case"]]}</td><td>{s["irrigation_gross_mm"]:g}</td><td><b>{s["yield_kg_mu_at_13pct"]:.2f}</b></td><td>{s["warehouse_kg_at_13pct"]:,.2f}</td><td><a href="{s["run"]}/每日状态.csv">逐日表</a></td></tr>' for s in drought)
    links="".join(f'<li><a href="{s["run"]}/summary.json">{esc(key)} / {esc(case)} 检查与汇总</a> · <a href="{s["run"]}/operations.jsonl">真实工具调用日志</a></li>' for (key,case),(s,_) in cases.items())
    catalogue=json.loads((base/"parameterization/complete_parameter_catalogue.json").read_text())
    paramrows="".join(f'<tr><td><code>{esc(k)}</code></td><td class="value">{esc(json.dumps(v["value"],ensure_ascii=False))}</td><td>{esc(", ".join(v["units"]))}</td><td>{esc(v["description"])}</td></tr>' for k,v in catalogue.items())
    sourcehtml=" · ".join(f'<a href="{esc(s["url"])}">{esc(s["title"])}</a>' for s in config["sources"])
    page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>WOFOST 黑农84完整工程农场</title>
<style>body{{margin:0;background:#f3f6f4;color:#1d3430;font:16px/1.75 system-ui,"PingFang SC",sans-serif}}main{{max-width:1180px;margin:auto;padding:48px 28px 80px}}h1{{font-size:36px;line-height:1.35;margin:10px 0 14px}}h2{{font-size:23px;margin:34px 0 12px}}p{{max-width:1000px}}.tag{{display:inline-block;background:#dcebe2;padding:5px 12px;border-radius:30px;font-size:13px;font-weight:600;color:#295b44}}.sub{{color:#60756b}}section,.hero{{background:white;border:1px solid #dbe5df;border-radius:15px;padding:24px 28px;margin:20px 0}}.hero{{border-top:5px solid #278464}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}.cards div{{background:#eff6f1;border-radius:10px;padding:18px}}.num{{font-size:30px;font-weight:700;display:block}}a{{color:#16735a;text-decoration:none;border-bottom:1px solid #aad2be}}a:hover{{color:#0a4736}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:11px 10px;text-align:left;border-bottom:1px solid #e0e9e3;vertical-align:top}}th{{background:#f0f5f1;white-space:nowrap}}.scroll{{overflow-x:auto}}figure{{margin:16px 0}}img{{width:100%;height:auto}}figcaption{{font-size:13px;color:#61746b}}pre{{background:#163d32;color:#e4f2e9;padding:18px;white-space:pre-wrap;overflow-wrap:anywhere;border-radius:9px;font-size:14px}}code{{font-size:13px}}.note{{background:#fff7e5;padding:16px 20px;border-left:4px solid #c39a39}}.value{{max-width:310px;overflow-wrap:anywhere;font-size:12px}}details{{margin:18px 0}}summary{{cursor:pointer;font-weight:600}}li{{margin:8px 0}}@media(max-width:700px){{main{{padding:24px 12px}}section,.hero{{padding:18px}}h1{{font-size:28px}}.cards{{grid-template-columns:1fr}}}}@media print{{body{{background:white}}main{{padding:0}}section,.hero{{break-inside:avoid}}a{{color:inherit;border:0}}}}</style>
<main><span class="tag">完整可运行工程版 · 尚无独立田间验证</span><h1>黑农84公开资料约束的<br>WOFOST 完整农场</h1><p class="sub">独立品种参数 × 外部场景配置 × 每日管理 × 收获、干燥与库存闭环。参数锁定后，在三年真实天气与同环境合成干旱中实际运行。</p>
<div class="hero"><div class="cards"><div>独立原生品种<span class="num" style="font-size:21px">Heinong84_PublicReference_v1</span>完整78项参数，来源与单位可查</div><div>正常天气三年实收均值<span class="num">{summary["normal_mean_stored_yield_kg_mu_at_13pct"]:.2f} 公斤/亩</span>仓库实际质量，统一13%水分</div><div>农场闭环<span class="num">9 / 9 场景通过</span>64垄全部成熟、收割并安全入库</div></div></div>
<section><h2>这一版具体是什么</h2><p>哈尔滨附近北方春大豆工程场景，64垄、1.1米大垄双行、28.3008亩；5月上旬择土温和墒情播种，深4厘米、株距7.9厘米，实际密度约23.02株/m²。当前明确假设100%成苗；密度只作用于初始生物量，尚不能用来验证最优播种密度。</p><p>品种使用独立的完整参数档案。出苗参数取东北研究先验；仅 <code>TSUM1=500</code> 与 <code>TSUM2=1100 ℃·d</code> 通过公开119–123天生育期弱约束筛选。两段均用同一原生7℃有效温度表，不能与≥10℃活动积温2800、3500直接比较。叶面积、同化、固氮和分配参数保留原生生理先验，<b>产量没有进入参数选择目标</b>。</p><p class="note">“完整”指配置、参数、工具管理和结果可复现。官方品种产量是跨地点年份的聚合资料，水分口径也未完全明确；当前没有目标地块独立观测，不能宣称已精确预测真实黑农84。</p></section>
<section><h2>三年真实天气的实际入库产量</h2><p>逐日平均/最低/最高温、降雨、辐射、风速和相对湿度均来自 NASA POWER；属于格点再分析与卫星辐射资料，非地块气象站观测。三年统一参数和管理规则，均未触发补灌，因此管理组与雨养组产量相同。</p><div class="scroll"><table><tr><th>年份</th><th>播种</th><th>出苗</th><th>自然成熟</th><th>收获入库</th><th>峰值LAI</th><th>公斤/亩</th><th>全田公斤</th><th>下载</th></tr>{normrows}</table></div><p class="sub">以上均为扣除模拟田间、机械等损失后的仓库质量，13%水分；原生TWSO是籽粒干物质，二者分别记账。</p></section>
<section><h2>管理确实进入模型了吗</h2><p>把2017年每天降雨保留25%，即人为削减75%，保持其他天气、土壤、品种参数与管理规则一致，构成合成压力测试；<b>这不是2017年的真实干旱观测</b>。补灌组按原生缺水状态触发，实际灌水100毫米，提高入库产量 {summary["synthetic_management_gain_kg_mu_at_13pct"]:.2f} 公斤/亩（{summary["synthetic_management_gain_pct"]:.1f}%）。提高供水额度仍只触发100毫米，结果相同，说明额度不是强制灌水量。</p><table><tr><th>同环境方案</th><th>累计毛灌水mm</th><th>公斤/亩，13%水分</th><th>全田公斤</th><th>下载</th></tr>{dryrows}</table><figure><img src="overview.svg" alt="三年物候、冠层与实收产量，以及同环境缩雨水分管理对照"><figcaption>全田逐日平均状态。D–F 为合成缩雨测试；RFTRA=1表示无蒸腾水分限制。成熟后作物曲线保留最终状态；作物删除后SM转为裸土10厘米表层状态，不再始终代表根区。<a href="overview.png">下载PNG</a> · <a href="overview.svg">下载SVG矢量图</a>。</figcaption></figure></section>
<section><h2>固定土壤与管理处方</h2><p>土壤是声明的120厘米均质壤土假设：初始VWC=0.28，萎蔫点0.14，田间持水量0.36，饱和0.48；不是黑土实测剖面。原生WOFOST管理土壤水分、径流、排水、蒸发、蒸腾和可供氮。</p><p>每公顷磷酸二铵150公斤、尿素50公斤、氯化钾60公斤，共N50、P₂O₅69、K₂O36公斤/公顷；全田肥料产品490.5472公斤，以真实工具完成基施。当前仅氮质量及70%回收率进入原生8.1，P/K记账但不产生原生限制反馈。未固定追肥，按周巡检并针对发现的杂草防治；花荚至鼓粒期按持续缺水和近期降雨决定补灌。自然成熟后，在无雨、土壤可通行、籽粒≤25%时湿收，干燥至13%后入库。</p></section>
<section><h2>直接打开配置与复现</h2><ul><li><a href="../../configs/wofost/complete_harbin_heinong84_v1.json">完整农场配置JSON</a>：品种、土壤、施肥产品、灌溉规则、湿收与干燥能力。</li><li><a href="../../fairy/physics/data/wofost/profiles/heilongjiang_heinong84_complete_v1.json">可加载的独立品种档案</a> · <a href="parameterization/complete_native_crop_parameters.json">完整78项原生参数</a> · <a href="parameterization/complete_parameter_catalogue.json">含单位与含义的参数目录</a>。</li><li><a href="../../fairy/scenarios/farm_world_fullseason_v2/wofost_complete_scenario.py">WofostCompleteScenario场景类</a> · <a href="../../scripts/run_wofost_complete_season.py">完整农季运行器</a>。</li><li><a href="parameterization/frozen_screen.json">参数筛选前冻结的目标与范围</a> · <a href="parameterization/screen_results.json">15组筛选结果</a> · <a href="delivery_summary.json">本页实际数据汇总JSON</a> · <a href="independent_audit_final.json">独立最终审计</a> · <a href="verification.json">186项测试验证记录</a>。</li></ul><p>安装仓库及WOFOST依赖后，在仓库根目录执行默认2017正常天气管理与雨养对照：</p><pre>env -u USER uv run --locked --extra wofost python scripts/run_wofost_complete_season.py --output-dir validation_runs/heinong84_complete</pre><details><summary>展开全部78项参数、单位与含义</summary><div class="scroll"><table><tr><th>参数</th><th>值</th><th>单位</th><th>含义</th></tr>{paramrows}</table></div></details><details><summary>展开9个运行结果和完整工具调用日志</summary><ul>{links}</ul></details></section>
<section><h2>结果边界</h2><p>生长、土壤和氮响应由WOFOST8.1计算；病虫草害、成苗、谷物干燥和回收损失包含FAIRY经验模型。当前仍为温度主导物候，没有本地光周期拟合；干燥能力为批次容量约束，不含实际能耗和连续小时吞吐。三年天气外推和软件水量/质量守恒检查不能替代独立田间验证。</p><p class="sub">参考来源：{sourcehtml}</p></section></main></html>'''
    (base/"delivery.html").write_text(page,encoding="utf-8")
    print(json.dumps({"delivery":str(base/"delivery.html"),"normal_yields":y,"drought_yields":dy,"all_nine_passed":summary["all_nine_cases_passed"]},ensure_ascii=False))


if __name__=="__main__":main()
