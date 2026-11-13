# Tool doc 与 schema 约定

本目录按工具定义源文件保存审阅稿：每个源文件对应一个 Markdown，每个工具包含一段简短的**中文能力边界说明**和一份**英文 docstring**。当前覆盖 11 个源文件、59 个 `app_tool`；这些草稿尚未替换源码中的 doc。

## Doc 结构

固定顺序为 `Description` → `Relation` → `Args`，标题独占一行，正文缩进四个空格。

| 字段 | 内容                               | 是否必需 |
| --- |----------------------------------| --- |
| `Description` | 工具能做什么、能力边界，以及正常情况下返回什么。         | 必需 |
| `Relation` | 调用该工具前的必要建议或相关工具的配合方式，一步以内。      | 有实际帮助时保留，无需凑写 |
| `Args` | 按参数说明含义、单位、范围、默认值和枚举选项，参数名与函数签名一致。 | 有输入参数时必需，无输入时省略 |

不单设 `Return` / `Returns`；正常返回说明并入 `Description`，无需罗列异常分支或完整返回字典。硬性前置条件与能力限制放在 `Description` 或对应 `Args`，不能仅放在可关闭的 `Relation` 中。

## 表述约束

- 面向要操作、管理农场的 Agent，写工具使用说明，保持简洁清晰，避免系统实现讲解和重复表述。
- 以实际执行逻辑为准，不夸大或缩窄能力；说明必要的作用对象、范围、资源消耗和时间行为。
- 精简 doc 时，必须保留 Args 中适用的单位、取值范围（含边界是否包含）、默认值和枚举选项，并与实际执行逻辑及函数签名一致。不得仅将这些信息放在中文审阅说明或 Relation 中，也不得因 schema 已包含 `type` 或 `required` 而省略；不适用的约束或不存在的默认值无需补写。
- 除时间统一使用 `simulation time/seconds/minutes/hours/days/period` 等表达外，农场、作物和设备均按真实对象描述。
- 对影响理解的自定义缩写、状态字符串或特殊数值，简短解释其含义；例如 `prep = field preparation`、`-1 = unavailable`。
- 本轮只处理 doc 和 schema 构建，不改工具内部执行逻辑；中文能力边界说明用于人工审阅，不进入 schema。

## Schema 映射与约束

采用 function-calling 结构：外层 `type: "function"`，内部为 `function`；参数容器为 `function.parameters`，类型为 `object`。

| 来源 | Schema 位置 |
| --- | --- |
| 应用名与工具名 | `function.name = <app_name>__<tool_name>` |
| `Description` | `function.description` |
| `Relation`（开关打开时） | 以 `Relation:` 标题追加到 `function.description` |
| 每个参数的 `Args` 说明 | `function.parameters.properties.<参数名>.description` |
| 参数类型注解 | 对应参数的 `type` |
| 无默认值的参数 | `function.parameters.required` |

CLI 使用 `--tool-relations on|off`，默认 `on`，同时作用于主 Agent 和 A2A 专家 Agent。关闭时仅省略 Relation，Description 和参数说明保持不变；不新增独立的 relation 或 return schema 字段。

当前基本类型映射为 `str → string`、`int → integer`、`float → number`、`bool → boolean`。Args 中的范围、枚举、默认值等文字说明不会自动转成 `minimum`、`enum`、`default` 等结构化约束，也不会新增运行时校验。

工具 schema 在 Agent 初始化时构建并保存在内存中，后续 LLM 调用复用；修改源码 doc 后需重新构建 Agent 才能采用新说明。本目录 Markdown 不会被运行时自动加载。
