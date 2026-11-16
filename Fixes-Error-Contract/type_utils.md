# type_utils.py 错误与校验审阅

源文件：[fairy/utils/type_utils.py](../fairy/utils/type_utils.py)

共享校验支撑文件，无直接 @app_tool；影响多数 FarmWorld/System/场景工具。各工具报告中的具体问题是此根因的落点，不应重复计算成不同根因。

类型①：已有错误提示不清晰或不准确。类型②：缺少应在执行前完成的校验。P1：可能破坏状态；P2：影响行为或纠错；P3：提示可读性。

## 1. 【类型② / P1】type_check 没有执行任何检查

- 位置：[7-12](../fairy/utils/type_utils.py#L7)。
- 现状/触发：wrapper 只 return func(*args, **kwargs)。工具的 Python 注解和对外 JSON schema 不会在执行端自动保证类型；已实测浮点垄号扣电后才报错、NaN 污染库存。
- 建议：实现集中输入验证或在工具边界共用验证器：解析注解、绑定参数，区分 bool/int，拒绝非有限 float，并返回非空 error 原因。业务阈值仍由具体工具校验；避免默默 int()/float() 改写 Agent 意图。

## 验收重点

对上述触发输入确认返回非空字符串 `error`；拒绝发生在扣减资源、修改作物或推进时间之前。提示改动应与实际阈值一致，并覆盖修正后的合法调用。没有写明“实测”的项目为静态路径审阅结论。
