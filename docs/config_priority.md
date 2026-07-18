# 成绩分析助手配置与状态优先级规范

本文档定义成绩分析助手中 `ExamContext`、`ExamConfig`、`PageState` 与
`Result` 的职责边界，以及分析参数的覆盖、保存和读取规则。它用于回答未来页面迁移
时的核心问题：一个参数是考试规则、页面临时状态，还是计算结果，以及最终应当从哪里
读取。

本文档是架构判定规范，不改变当前页面行为，也不要求当前阶段立即迁移旧
`st.session_state`。

## 1. 配置职责划分

四个核心对象的基本定义如下：

```text
ExamContext
= 这场考试有什么数据

ExamConfig
= 这场考试默认如何评价

PageState
= 用户当前怎么看、临时怎么调整

Result
= 计算后的结果
```

### 1.1 ExamContext：考试事实

`ExamContext` 保存一场考试已经确认的事实数据，包括文件信息、字段映射、学生身份、
科目列表，以及按原始行 index 关联的成绩数据。创建完成后，应将其视为只读对象。

`ExamContext` 不保存满分、优秀比例等可调整评价规则，不保存当前页面或用户选择，
也不保存图表和分析结论。

### 1.2 ExamConfig：考试评价规则

`ExamConfig` 保存一场考试默认采用的、可版本化的评价规则，包括：

- 各科考试默认满分；
- 默认及格比例；
- 默认优秀比例；
- 等级划分规则；
- 按科目定义的评价标准。

`ExamConfig` 是考试级业务配置的权威来源。同一 `exam_id` 在同一配置版本下应具有
唯一、确定的考试标准。规则被明确保存后，应产生新的配置版本或递增
`config_version`，并使依赖旧版本的 Result 和报告缓存失效。

`ExamConfig` 禁止保存：

- 当前页面；
- 当前选择科目；
- 当前班级或对比班级；
- 当前用户的临时查看参数；
- 页面筛选条件；
- 控件展开、选中、滚动等图表或 UI 状态。

已有模型中的任何 `page_overrides` 概念，都不能被解释为页面临时状态的存储位置。
页面临时调整统一归属 `PageState`。只有经过明确“保存为考试规则”的操作后，相关值
才可以转化为新的 `ExamConfig` 版本。

### 1.3 PageState：页面选择与临时覆盖

`PageState` 保存用户在某个考试、某个页面中的当前操作状态。它必须至少按
`exam_id + page_name` 隔离，包括：

- 页面当前选择的科目；
- 页面当前选择或比较的班级；
- 页面筛选条件；
- 尚未保存为考试规则的临时满分、优秀比例等 override。

例如，学科分析页面可以保存“当前选择数学”“当前比较一班和二班”“本次临时按
85% 计算优秀率”。这些状态只影响该考试的学科分析页面，不得改变年级分析、班级
分析或报告中心的默认规则。

`PageState` 禁止保存：

- 原始成绩；
- 学生身份记录；
- 原始考试文件或字段事实；
- 考试规则的唯一业务真值；
- 已计算完成的结构化分析结果。

Streamlit widget key 和散落的 `st.session_state` 控件镜像属于 UI 实现细节，不是
`PageState` 的业务真值。未来页面应由 PageState 生成控件初始值，再将经过校验的用户
操作写回 PageState，而不能把 widget 状态直接当作配置。

### 1.4 Result：派生结果

`Result` 保存基于 ExamContext、最终生效配置和分析请求计算出的派生结果，包括：

- 指标与统计结果；
- 等级结构和图表所需结构化数据；
- 班级或科目比较结果；
- 自动分析结论。

Result 必须能够追溯到 `exam_id`、`config_version`、分析类型、页面请求和有效 override
签名。不同的临时 override 必须生成不同的 ResultKey，不能错误复用旧结果。

`Result` 禁止反向修改：

- `ExamContext`；
- `ExamConfig`；
- `PageState` 中的用户选择。

图表对象、Word bytes 等展示或导出产物应从 Result 派生或放入独立缓存，不应反向成为
评价规则来源。

## 2. 配置优先级规则

最终生效配置的固定优先级为：

```text
PageState Override

        ↓

ExamConfig

        ↓

System Default
```

可表达为：

```text
effective_config =
    page_override（该页面明确存在且有效）
    否则 exam_config（该考试、该科目的标准配置）
    否则 system_default（系统安全默认值）
```

这里的选择依据是“配置是否明确存在”，不是 Python 的真假值判断。解析层必须校验
满分、百分比和等级规则是否合法，非法 PageState override 不得覆盖有效 ExamConfig。

优先级规则包含以下不变量：

1. 页面临时调整优先用于当前页面的显示与计算。
2. 页面临时调整默认不修改 ExamConfig，也不递增考试配置版本。
3. 只有用户执行明确的“保存为考试规则”行为，经过校验后才允许创建或更新
   ExamConfig。
4. ExamConfig 缺少某科规则时，才允许使用 System Default；系统默认值不能覆盖已有
   ExamConfig。
5. widget 或临时 `session_state` 值不能直接参与业务优先级判断，必须先转换为经过校验
   的 PageState。
6. 计算函数接收的是已解析的 effective config，而不是自行读取三层状态。

## 3. 修改行为定义

### 3.1 情况 A：老师修改数学满分

老师在某个分析页面把数学满分由 120 临时改为 150 时，默认行为是：

- 将 150 保存为该考试、该页面、数学科目的 PageState override；
- 立即使用 150 重新计算当前页面；
- ExamConfig 中数学默认满分仍为 120；
- 其他页面继续按自己的 override 或 ExamConfig 计算。

只有当页面提供独立、明确的“保存为考试规则”操作，且用户主动确认后，才执行：

1. 校验新规则；
2. 将数学满分 150 写入新的 ExamConfig 版本；
3. 清理或重新确认与新标准冲突的页面 override；
4. 使旧 config version 对应的 Result 和报告缓存失效。

控件失焦、页面切换、Streamlit rerun 或生成报告都不能被视为“保存为考试规则”。

### 3.2 情况 B：报告中心生成报告

报告生成只能读取：

- ExamContext 中的考试事实；
- ExamConfig 中的考试标准规则；
- 用户为本次报告明确确认的 PageState override；
- 与上述输入一致的 Result。

报告不得读取：

- Streamlit widget 状态；
- 未校验的 `st.session_state` 控件值；
- 滚动、展开、按钮等临时 UI 状态；
- 其他页面尚未确认的临时 override。

“已确认的 PageState override”是指用户明确选择将某个临时分析口径用于本次报告，
并将该选择作为报告请求的一部分冻结。它只影响本次报告，不等于保存为考试规则，
也不得修改 ExamConfig。报告签名必须包含 ExamConfig 版本和已确认 override 的规范化
签名。

### 3.3 情况 C：学科分析临时调整优秀率

学科分析把数学优秀率临时调整为 85% 时：

- 只更新 `PageState.subject_analysis` 中数学的临时 override；
- 只重新生成学科分析对应的 Result；
- 不改变班级分析的配置和结果；
- 不改变年级分析的配置和结果；
- 不改变报告中心默认使用的 ExamConfig；
- 不改变其他科目的优秀率。

若用户离开学科分析页面，是否保留该临时值由 PageState 生命周期策略决定，但无论
是否保留，都不能提升为 ExamConfig 的业务真值。

## 4. 页面迁移规则

年级分析、班级分析、学科分析和报告中心必须采用同一条数据流：

```text
ExamContext
     +
ExamConfig
     +
PageState
     ↓
解析 effective config 与 AnalysisRequest
     ↓
计算
     ↓
Result
     ↓
页面展示或报告生成
```

页面迁移时必须遵守：

1. 页面不能重新读取 Excel，也不能把 Excel 解析作为 rerun 的一部分。
2. 页面不能直接修改 ExamContext，不能重建或覆盖学生身份与成绩映射。
3. 页面不能创建新的、未归属的规则状态；所有临时调整必须进入该页面的 PageState
   override。
4. 页面不能直接修改 ExamConfig；永久规则修改必须通过明确的配置服务和确认动作。
5. 页面不能直接从 widget key 构造业务配置。
6. 分析服务只接收 ExamContext、解析后的 effective config 和规范化请求，并生成
   Result。
7. 页面切换只能改变 PageState 路由或当前页面选择，不能隐式改变考试规则。

各页面的主要 PageState 内容如下：

| 页面 | PageState 内容 | 默认规则来源 |
|---|---|---|
| 年级分析 | 当前科目、班级范围、临时分析口径 | ExamConfig |
| 班级分析 | 当前科目、对比班级、页面临时规则 | ExamConfig |
| 学科分析 | 当前科目、比较班级、页面临时规则 | ExamConfig |
| 报告中心 | 报告草稿、引用 Result、明确确认的报告 override | ExamConfig |

## 5. 当前旧状态映射

Phase 1.8 只定义迁移目标，不删除或替换下列旧状态。迁移期间继续保留旧状态，是为了
维持现有页面行为；但新旧状态只能单向转换，禁止双向同步形成两个业务真值。

| 旧状态 | 当前职责 | 当前保留方式 | 未来归属 | 删除条件 |
|---|---|---|---|---|
| `analysis_score_column` | 年级分析当前科目 | 旧年级页面继续读取 | `PageState.grade_analysis.selected_subject` | 年级页面只读 PageState，页面切换和回归测试通过 |
| `analysis_excellent_percent` | 年级优秀率，混合控件值和业务配置 | 旧流程兼容保留，不作为新配置来源 | 默认标准进入 `ExamConfig`；临时值进入 `PageState.grade_analysis.override` | 配置服务成为唯一规则写入口，旧控件不再承担业务持久化 |
| `full_score_by_context` | 按文件、工作表和科目保存满分 | 旧分析流程继续使用 | 已确认的考试科目满分进入 `ExamConfig.subjects` | 所有页面和报告只读 ExamConfig，旧上下文键完成一致性验证 |
| `subject_analysis_score_column` | 学科分析当前科目 | 学科页面迁移前保留 | `PageState.subject_analysis.selected_subject` | 学科页面完全切换到 PageState |
| `subject_analysis_full_score_by_context` | 学科页面独立满分 | 旧学科页面兼容保留 | 默认按临时 override 迁入 `PageState.subject_analysis`；明确保存后才进入 `ExamConfig` | 学科页、ResultKey 和报告口径迁移完成 |
| `subject_analysis_excellent_percent_by_context` | 学科页面独立优秀率 | 旧学科页面兼容保留 | 默认进入 `PageState.subject_analysis.override`；明确保存后才进入 `ExamConfig` | 学科页面不再读取旧 key，跨页面隔离回归通过 |
| `subject_analysis::<...>` | 学科分析 widget 镜像 | 仅作为当前 UI 实现保留 | 临时 UI 状态，不进入业务模型 | widget 由 PageState 驱动且不再承担持久化职责 |
| `class_analysis_score_column` | 班级分析当前科目 | 班级页面迁移前保留 | `PageState.class_analysis.selected_subject` | 班级页面完全切换到 PageState |
| `class_analysis_classes` | 当前对比班级集合 | 班级页面迁移前保留 | `PageState.class_analysis.selected_classes` | 班级页面完全切换到 PageState |
| `class_analysis_full_score` | 班级页面临时满分 | 旧班级页面兼容保留 | 默认进入 `PageState.class_analysis.override`；明确保存后才进入 `ExamConfig` | 班级页按考试和科目隔离，旧值不再被读取 |
| `class_analysis_excellent_percent` | 班级页面临时优秀率 | 旧班级页面兼容保留 | 默认进入 `PageState.class_analysis.override`；明确保存后才进入 `ExamConfig` | 班级页及相关 Result 完成新旧一致性验证 |
| `class_analysis::<...>` | 班级分析 widget 镜像 | 仅作为当前 UI 实现保留 | 临时 UI 状态，不进入业务模型 | widget 由 PageState 驱动且不再承担持久化职责 |

迁移期间，如果旧变量同时混合了“默认考试规则”和“页面临时值”，必须在迁移适配器
中按明确语义拆分，不能把整个旧字典原样复制到 ExamConfig。任何无法确定是否已由用户
保存的旧临时值，默认按 PageState override 处理，不能擅自提升为考试标准。

## 6. 文档关系

三份文档分别回答不同问题：

```text
architecture_design.md
        ↓
整体架构设计：系统未来由哪些对象和服务组成

migration_plan.md
        ↓
迁移路线：按什么阶段从旧 session_state 迁移到新结构

config_priority.md
        ↓
配置与状态判定规范：参数归属哪里、如何覆盖、何时允许保存
```

`architecture_design.md` 定义总体目标，`migration_plan.md` 定义实施顺序，本文档则是页面
迁移和代码评审时的配置裁决依据。当旧文档中的“page override”表述可能被理解为
ExamConfig 中的页面临时状态时，以本文档的职责边界为准：临时 override 属于
PageState，只有明确保存的考试规则属于 ExamConfig。

本文档不覆盖 Excel 解析、学生身份、成绩计算公式和报告内容设计；这些能力继续遵守
总体架构和迁移计划中的既有约束。

## 7. 迁移验收标准

未来页面迁移完成后，必须同时满足：

- 页面之间不会因共享配置 key 而互相污染；
- 修改某个页面的临时参数不会影响其他页面；
- 同一考试、同一配置版本具有唯一的考试标准配置；
- 临时查看和 Streamlit rerun 不会修改考试标准；
- widget 和临时 session_state 不再作为业务真值；
- 报告只使用 ExamContext、ExamConfig、已确认 override 和匹配的 Result；
- Result 不反向修改 ExamContext、ExamConfig 或 PageState；
- 不同 override 或配置版本不会错误复用同一 Result；
- 所有新功能，包括 AI 分析、学生成长和考试趋势，都遵守本文件定义的职责边界和配置
  优先级；
- 删除旧状态前，所有相关页面、报告和完整用户链路均已完成新旧结果一致性验证。
