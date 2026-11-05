# 阶段2：四条开发预检已执行

2026-11-03，W01/N01共四条各执行一次，无LLM请求、无自动重跑或扩矩阵，FAIRY原生产源码/参数/既有评分未改。

完整报告：[REPORT.md](../../../../integration/maize-l3-phase2-20261103/REPORT.md)

|处理|成熟TWSO kg DM/ha|14%实际入库kg|结论|
|---|---:|---:|---|
|W01阈值补灌/N120|2347.0097|3405.36|收储完成；150mm毛水→138mm有效水已由原生TOTIRR核实|
|W01不补灌/N120|0.0000|0.00|未完成：0产量后空粮箱卸粮拒绝，未收完64垄|
|N01 N60/0灌水|1616.5018|2345.44|收储完成|
|N01 N120/0灌水|2002.5293|2905.60|收储完成；相对N60成熟TWSO+23.88%|

必须保留的边界：常规网格实际使用原生起点07:00，冻结说明写08:00，前置检查漏项。两臂初态和共同日期天气一致，但**本轮不能宣布预定协议全部通过或正式场景准入**。W01配对因控制组不闭环标invalid/incomplete；N01配对内部有效，同时标记时序协议偏差。

记录器曾将仅外部径流模式累计的私有字段误作通用有效水，原始summary保留；更正和原生恢复证据另存在analysis-v1，不改原轨迹，不重新运行四条处理。

[配对W01](../../../../integration/maize-l3-phase2-20261103/analysis-v1/MZ-W01-comparison.json) · [配对N01](../../../../integration/maize-l3-phase2-20261103/analysis-v1/MZ-N01-comparison.json) · [原始结果](../../../../integration/maize-l3-phase2-20261103/runs/all_results.json) · [独立审查结果](../../../../integration/maize-l3-phase2-20261103/analysis-v1/reviewed_results.json)
