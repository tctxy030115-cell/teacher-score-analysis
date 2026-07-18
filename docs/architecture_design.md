# 成绩分析助手未来架构设计

本文档描述成绩分析助手从当前平铺 `st.session_state` 架构迁移到考试上下文架构的目标方向。本文不是立即重构计划，不改变现有成绩公式、Excel 解析、学生身份规则或页面功能；后续实现应采用兼容式、分阶段迁移。

## 1. 当前架构问题分析

### 1.1 `current_exam_snapshot` 职责过重

`current_exam_snapshot` 当前同时保存以下内容：

- 考试字段信息：姓名列、班级列、学号列、成绩列；
- 逐行身份与各科成绩；
- 当前页面选择：成绩列、班级范围；
- 分析规则：满分、优秀线；
- 计算结果：汇总指标、优秀名单、待提升名单、成绩分布；
- 展示产物：Plotly 图表对象；
- 报告信息：报告名称和 Word 报告所需输入。

这使 snapshot 同时扮演考试数据模型、页面状态、配置对象、结果缓存和报告数据源。其主要问题是：

1. 任一页面参数变化都可能使整份 snapshot 过期；
2. 页面难以判断自己读取的是考试事实、用户配置还是派生结果；
3. snapshot 只能表示一场“当前考试”，不适合考试历史、学生成长和趋势分析；
4. DataFrame、图表和可重新派生的名单被重复保存，增加内存和一致性成本；
5. 后续如果只把 snapshot 改名为 `ExamContext`，会保留原有问题并形成新的全能对象。

因此，目标架构不会原样迁移 `current_exam_snapshot`，而是将其拆分为考试数据、考试规则、页面状态和派生结果。

### 1.2 `session_state` 混合多种生命周期

当前 `session_state` 同时包含：

- 考试数据：`current_exam_file_bytes`、`current_exam_snapshot`；
- 字段和规则配置：`analysis_sheet`、`full_score_by_context`、`analysis_excellent_percent`；
- 页面选择：`analysis_score_column`、`subject_analysis_score_column`；
- Widget 镜像：`full_score::<context>::<subject>`；
- 全局路由：`analysis_mode`；
- 报告缓存：`word_report_bytes`、`word_report_signature`；
- 临时 UI 信号：`analysis_center_scroll_pending`。

这些状态的生命周期不同：

- 考试数据应在一场考试的整个生命周期内稳定；
- 分析配置应按考试和科目保存；
- 页面状态应允许页面独立变化；
- Widget 状态只应服务当前控件；
- 报告缓存应由输入签名决定是否有效；
- 临时 UI 状态应消费后立即清理。

目前它们平铺在同一命名空间中，代码只能依靠 key 名称约定判断归属，缺少统一的读写边界和失效规则。

### 1.3 页面状态污染的原因

页面污染不是单个变量错误，而是以下结构性原因叠加：

1. 页面曾复用通用 `single_class` 流程，导致进入页面时重新渲染并修改年级分析控件；
2. 同一业务值同时保存在配置字典、Widget key 和 snapshot 中；
3. 部分状态没有考试命名空间，例如 `analysis_excellent_percent`、`class_analysis_full_score`；
4. 页面直接读写 `st.session_state`，没有统一入口验证状态归属和有效性；
5. 新考试只清理部分旧状态，同名科目或班级可能继承上一场考试的配置；
6. 派生结果没有统一版本号，页面无法可靠判断结果是否与当前配置匹配。

目标架构需要同时解决“归属、读写权限、命名空间、结果失效”四个问题。

## 2. 目标架构设计

目标架构由三个核心对象和一个派生结果对象组成：

```text
ExamContext  ──描述──> 一场考试的事实数据
ExamConfig   ──描述──> 该考试采用的分析规则
PageState    ──描述──> 用户当前页面的交互选择

ExamContext + ExamConfig + AnalysisRequest
                    ↓
                  Result
```

### 2.1 ExamContext

`ExamContext` 负责一场考试本身的数据。它在 Excel 导入和字段确认完成后创建，创建成功后应视为只读。

建议结构：

```python
ExamContext = {
    "exam_id": str,
    "metadata": {
        "file_name": str,
        "file_fingerprint": str,
        "sheet_name": str,
        "exam_name": str | None,
        "exam_time": str | None,
    },
    "schema": {
        "name_column": str,
        "class_column": str | None,
        "student_id_column": str | None,
        "score_columns": list[str],
    },
    "identity_records_by_index": dict,
    "subject_scores_by_index": dict,
}
```

职责：

- 提供稳定 `exam_id`；
- 保存文件指纹和考试元数据；
- 保存确认后的字段映射；
- 保存原始 DataFrame index 到学生身份的稳定关联；
- 保存原始 DataFrame index 到各科成绩的关联；
- 提供班级和科目列表等只读派生信息。

不属于 `ExamContext` 的内容：

- 当前页面选择的科目和班级；
- 满分、优秀线等可修改规则；
- Plotly 图表；
- Word 二进制；
- Widget key；
- 当前路由；
- 当前页面的展开、滚动和按钮状态。

核心约束：

1. 不保存完整 DataFrame 副本作为页面共享状态；
2. 身份和成绩必须继续通过原始行 index 关联；
3. 页面不得修改身份映射或成绩数据；
4. 需要更换工作表或字段映射时，应创建新的 ExamContext 版本，而不是原地修改。

### 2.2 ExamConfig

`ExamConfig` 负责一场考试的分析规则。它与 `ExamContext` 通过 `exam_id` 关联，但生命周期和写权限独立。

建议结构：

```python
ExamConfig = {
    "exam_id": str,
    "version": int,
    "subjects": {
        "数学": {
            "full_score": 120.0,
        },
        "英语": {
            "full_score": 150.0,
        },
    },
    "rules": {
        "pass_percent": 60.0,
        "excellent_percent": 90.0,
        "levels": {
            "excellent": 90.0,
            "good": 80.0,
            "pass": 60.0,
        },
    },
    "page_overrides": {
        "subject_analysis": {},
        "class_analysis": {},
    },
}
```

职责：

- 保存各科满分；
- 保存优秀线、及格规则和等级规则；
- 为需要独立分析口径的页面保存显式 override；
- 每次规则变化递增 `version`，用于使旧 Result 和报告缓存失效。

规则归属原则：

- 如果“数学满分 120”是整场考试的统一事实，只保存到 `subjects["数学"]`；
- 如果某页面允许使用独立分析口径，应放在 `page_overrides`，不得覆盖考试的 canonical 配置；
- 固定 60% 的及格规则应是规则值或常量，不需要 Widget session key 作为业务真值；
- 页面修改配置必须通过统一 Config API，不得直接修改嵌套字典。

### 2.3 PageState

`PageState` 负责用户当前页面行为。它必须按 `exam_id` 和页面命名空间保存。

建议结构：

```python
PageState = {
    "route": "analysis_center",
    "by_exam": {
        "<exam_id>": {
            "grade_overview": {
                "selected_subject": "数学",
                "selected_class": "全部学生",
            },
            "subject_analysis": {
                "selected_subject": "数学",
            },
            "class_analysis": {
                "selected_subject": "数学",
                "selected_classes": ["1班", "2班"],
            },
            "report_center": {
                "school_name": "",
                "report_title": "期中考试分析",
            },
        }
    },
}
```

职责：

- 当前分析模式；
- 当前页面选择的科目；
- 当前页面选择的班级或班级集合；
- 报告表单草稿；
- 其他不改变考试事实和分析规则的交互状态。

PageState 可以变化，但变化不应修改 `ExamContext`。只有当页面明确提供分析规则设置时，才通过 Config API 修改 `ExamConfig`。

### 2.4 Result

虽然 Result 不是本次要求的核心状态对象，但必须独立定义，否则计算结果会再次被塞入 ExamContext。

建议标识：

```text
ResultKey = exam_id + config_version + analysis_type + normalized_request
```

Result 可以包含：

- 核心指标；
- 分布和等级结构数据；
- 优秀和待提升学生身份键；
- 班级比较结果；
- 自动分析结论。

Plotly figure、展示 DataFrame 和 Word bytes 应从 Result 派生或单独缓存，不作为 ExamContext 的组成部分。

## 3. 数据流设计

### 3.1 总体数据流

```text
上传 Excel
    ↓
读取工作表和识别字段
    ↓
用户确认字段映射
    ↓
创建只读 ExamContext
    ↓
根据科目建议生成 ExamConfig
    ↓
初始化该 exam_id 对应的 PageState
    ↓
页面构造 AnalysisRequest
    ↓
AnalysisService 生成 Result
    ↓
页面展示 / 报告生成
```

建议的职责分工：

- `ExamImportService`：读取 Excel、识别表头和字段、创建 ExamContext；
- `ExamConfigService`：创建和更新 ExamConfig；
- `AnalysisService`：读取 Context、Config 和 Request，调用现有纯计算函数；
- `ResultStore`：按 ResultKey 缓存结果；
- 页面：读取对象、创建请求、展示结果；
- `ReportService`：读取 Result 和报告草稿，生成 Word。

### 3.2 年级总览

输入：

- `ExamContext`
- `ExamConfig`
- `PageState.grade_overview`

流程：

1. 从 PageState 读取当前科目和班级范围；
2. 从 ExamConfig 读取当前科目满分和评价规则；
3. 从 ExamContext 按原始行 index 读取身份和成绩；
4. 构造 `GradeOverviewRequest`；
5. 调用 AnalysisService 生成或读取 Result；
6. 页面只负责渲染。

年级总览不再每次 rerun 执行 `pd.read_excel()`，也不再负责重建 ExamContext。

### 3.3 班级分析

输入：

- `ExamContext`
- `ExamConfig` 或班级分析 override
- `PageState.class_analysis`

流程：

1. 读取当前科目和对比班级；
2. 通过原始行 index 构造班级比较输入；
3. 调用现有 `build_class_comparison()`；
4. 将结果保存到 ResultStore；
5. 渲染平均得分率、及格率、优秀率、等级结构和结论。

切换班级或科目只更新 PageState。修改满分或优秀线必须通过 ExamConfigService，并触发 config version 变化。

### 3.4 学科分析

输入：

- `ExamContext`
- `ExamConfig` 或学科分析 override
- `PageState.subject_analysis`

流程：

1. 从 PageState 读取当前学科；
2. 从 ExamConfig 读取该学科规则；
3. 从 ExamContext 按原始行 index 绑定身份和成绩；
4. 生成学科指标和班级对比 Result；
5. 页面渲染指标、班级对比和等级结构。

学科分析不得读取 Excel，不得重新生成学生身份，不得根据姓名匹配成绩。

### 3.5 报告中心

输入：

- `ExamContext.metadata`
- 已生成的 Result
- `PageState.report_center`
- ReportCache

流程：

1. 用户选择报告所引用的分析 Result；
2. 根据 `exam_id + ResultKey + report draft` 计算报告签名；
3. 缓存命中则直接下载；
4. 缓存未命中则调用 `build_score_report_bytes()`；
5. 将 Word bytes、文件名和签名写入 ReportCache。

报告中心只能读取 ExamContext、ExamConfig 和 Result，不得修改成绩列、满分、优秀线、班级范围或身份数据。

## 4. 状态读写规则

### 4.1 写权限矩阵

| 模块 | ExamContext | ExamConfig | PageState | Result/Report Cache |
|---|---|---|---|---|
| ExamImportService | 创建新对象 | 初始化默认配置 | 初始化 | 不写 |
| ExamContextStore | 保存/切换/删除 | 不写 | 不写 | 不写 |
| ExamConfigService | 只读 | 唯一业务写入口 | 不写 | 使相关缓存失效 |
| 年级总览页面 | 只读 | 通过服务修改 | 写本页状态 | 请求结果 |
| 班级分析页面 | 只读 | 通过服务修改 | 写本页状态 | 请求结果 |
| 学科分析页面 | 只读 | 通过服务修改 | 写本页状态 | 请求结果 |
| 报告中心 | 只读 | 只读 | 写报告草稿 | 写报告缓存 |
| AnalysisService | 只读 | 只读 | 不读或只读 Request | 写 ResultStore |
| ReportService | 只读 | 只读 | 读取报告草稿 | 生成报告产物 |

### 4.2 强制规则

1. 页面不能直接修改 ExamContext；
2. 页面不能直接修改学生身份和成绩字典；
3. ExamConfig 只能通过统一服务修改；
4. Widget key 不得作为业务配置的唯一真值；
5. PageState 必须按 `exam_id + page_name` 命名空间化；
6. Result 必须携带或隐含 `exam_id` 和 `config_version`；
7. 配置版本变化后，旧 Result 和报告缓存必须失效；
8. 新考试不能继承上一场考试的页面状态，除非产品明确提供“复制配置”；
9. 报告页面不得触发 Excel 解析和成绩重新计算；
10. 所有学生成绩绑定继续使用原始行 index 或稳定 identity key，禁止姓名覆盖。

### 4.3 Session State 的目标形态

迁移完成后，顶层 session state 建议只保留少量入口：

```python
st.session_state["current_exam_id"]
st.session_state["exam_contexts"]
st.session_state["exam_configs"]
st.session_state["page_state"]
st.session_state["result_store"]
st.session_state["report_cache"]
st.session_state["ui_state"]
```

这不意味着所有数据必须永久保存在 session 中。较大的 Excel bytes、图表和 Word bytes 可以迁移到缓存或持久化仓库；session 只保存引用和当前选择。

## 5. 迁移路线

### Phase 1：引入新结构，不改变业务

目标：建立类型和访问边界，现有页面仍使用旧状态。

修改范围：

- 新增 ExamContext、ExamConfig、PageState、ResultKey 的结构定义；
- 新增只负责读写结构的 Store/Adapter；
- 上传成功后，从现有状态构造新结构的镜像；
- 现有 `current_exam_snapshot` 和旧 session key 暂时保留。

风险：

- 新旧结构出现值不一致；
- 双写顺序不正确；
- 结构命名过度设计。

验证方式：

- 同一考试的新旧结构字段逐项一致；
- 上传、自动滚动和年级总览行为不变；
- 现有测试全部继续通过；
- 增加 Adapter 契约测试，不改变计算结果。

### Phase 2：迁移 `current_exam_snapshot`

目标：页面改为读取 ExamContext 和 Result，不再把混合 snapshot 作为数据源。

修改范围：

- 身份、成绩、字段映射迁入 ExamContext；
- 分析指标和分布迁入 ResultStore；
- 图表改为根据 Result 构造或独立缓存；
- 学科分析、班级分析、报告中心依次切换到新读取接口；
- 保留 snapshot compatibility adapter，供尚未迁移页面使用。

风险：

- 同名学生或跨班同名学生绑定错误；
- 图表和报告输入与原有 Result 不一致；
- snapshot 与新 Result 的失效时机不同。

验证方式：

- 重复姓名、跨班同名、有学号同名测试；
- 年级、学科、班级指标逐项对比；
- 报告内容与迁移前一致；
- 确认迁移页面不调用 `pd.read_excel()` 和身份重建函数。

### Phase 3：迁移满分和优秀线配置

目标：建立单一配置真值和明确的页面 override。

修改范围：

- 将 `full_score_by_context` 迁入 ExamConfig；
- 将年级、学科、班级优秀线迁入对应配置；
- 明确三个页面是否共享 canonical 满分；
- Widget key 仅做临时输入镜像；
- 配置更新时递增 `config_version` 并使旧 Result 失效。

风险：

- 页面原有独立配置被意外合并；
- 切换科目时错误继承上一科参数；
- 旧 Widget 状态覆盖新配置；
- Result 缓存未正确失效。

验证方式：

- 数学、英语配置独立测试；
- 跨考试配置隔离测试；
- 页面之间互不污染测试；
- 异常满分不能覆盖业务配置；
- 配置变化后所有相关指标、图表和报告重新生成。

### Phase 4：清理旧 `session_state`

目标：删除兼容层和重复状态，完成单一读写路径。

修改范围：

- 删除 `current_exam_snapshot`；
- 删除旧 `full_score_by_context`；
- 合并 `analysis_single_class` 与 `selected_class`；
- 删除固定的 `analysis_pass_percent` session 值；
- 删除平铺的学科、班级配置 key；
- 分离并统一报告草稿与报告缓存；
- 清理旧动态 Widget key。

风险：

- 遗漏隐式读取旧 key 的代码；
- 当前用户会话升级时旧状态残留；
- 页面路由仍依赖旧名称。

验证方式：

- 全项目静态搜索旧 key，结果应为零或仅兼容迁移代码；
- 新旧会话升级测试；
- 完整链路测试：上传、年级、学科、班级、报告、返回年级；
- 性能验证：页面切换不再重复读取 Excel；
- 内存验证：不再同时长期保存重复图表和派生 DataFrame。

## 6. 当前代码对应关系

| 当前变量 | 当前职责 | 未来归属 | 最终处理 |
|---|---|---|---|
| `current_exam_snapshot` | 考试数据、配置、结果、图表和报告输入的混合快照 | 拆分到 ExamContext、ExamConfig、ResultStore、ReportDraft | 拆分后删除 |
| `current_exam_file_bytes` | 当前 Excel 文件 | ExamContext source 或外部文件缓存 | session 只保留引用或单考试缓存 |
| `current_exam_file_name` | 文件名 | `ExamContext.metadata.file_name` | 迁移 |
| `analysis_sheet` | 当前工作表 | `ExamContext.metadata/schema.sheet_name` | 迁移 |
| `analysis_name_column` | 姓名列映射 | `ExamContext.schema.name_column` | 迁移 |
| `analysis_class_column` | 班级列映射 | `ExamContext.schema.class_column` | 迁移 |
| `analysis_score_column` | 年级总览当前科目 | `PageState.by_exam[exam_id].grade_overview.selected_subject` | 迁移 |
| `analysis_single_class` | 年级班级 Widget 值 | 与 grade overview 的 selected class 合并 | 删除重复状态 |
| `selected_class` | 年级总览当前班级范围 | `PageState.by_exam[exam_id].grade_overview.selected_class` | 迁移为唯一状态 |
| `analysis_excellent_percent` | 年级优秀线 | `ExamConfig.rules` 或 grade overview override | 按考试迁移 |
| `analysis_pass_percent` | 固定 60% 及格线 | `ExamConfig.rules.pass_percent` 或代码常量 | 删除 Widget 业务状态 |
| `full_score_by_context` | 各文件、工作表、科目满分 | `ExamConfig.subjects[subject].full_score` | 迁移后删除 |
| `full_score::<context>::<subject>` | 年级满分 Widget 镜像 | UI state | 不作为业务真值 |
| `subject_analysis_score_column` | 学科页当前科目 | `PageState.by_exam[exam_id].subject_analysis.selected_subject` | 迁移 |
| `subject_analysis_full_score_by_context` | 学科页独立满分 | ExamConfig subject canonical 值或 subject override | 明确语义后迁移 |
| `subject_analysis_excellent_percent_by_context` | 学科页独立优秀线 | `ExamConfig.page_overrides.subject_analysis` | 迁移 |
| `class_analysis_score_column` | 班级页当前科目 | `PageState.by_exam[exam_id].class_analysis.selected_subject` | 迁移 |
| `class_analysis_full_score` | 班级页单一满分 | ExamConfig subject canonical 值或 class override | 改为按考试、科目保存 |
| `class_analysis_excellent_percent` | 班级页优秀线 | `ExamConfig.page_overrides.class_analysis` | 迁移 |
| `class_analysis_classes` | 对比班级 | `PageState.by_exam[exam_id].class_analysis.selected_classes` | 迁移 |
| `analysis_mode` | 当前路由 | `PageState.route` 或顶层 AppState | 保留，不进入 ExamContext |
| `word_report_school_name` | 报告学校名称 | `PageState.report_center` 或 ReportDraft | 迁移 |
| `word_report_exam_name` | 报告标题 | ReportDraft | 删除 snapshot 中重复 report name |
| `word_report_signature` | 报告缓存签名 | ReportCache | 统一两个报告入口的签名规则 |
| `word_report_bytes` | Word 文件 | ReportCache 或外部临时缓存 | 不进入 ExamContext |
| `word_report_filename` | 下载文件名 | ReportCache | 与 Word bytes 一起管理 |
| `analysis_center_scroll_pending` | 一次性滚动信号 | `ui_state` | 保留临时状态，消费后删除 |

## 7. 架构不变量与完成标准

后续迁移完成后，应满足以下不变量：

1. 页面切换不会修改 ExamContext；
2. 年级、学科、班级和报告页面不重新读取 Excel；
3. 同一学生的身份规则在所有页面和考试比较中一致；
4. 一场考试的配置不会污染另一场考试；
5. 一个页面的当前科目和班级选择不会改变其他页面；
6. 满分和优秀线只有一个明确的业务真值或显式 override；
7. Widget 状态丢失不会改变业务配置；
8. 配置版本变化后旧 Result 和报告缓存自动失效；
9. 报告中心只读取考试、配置和结果；
10. `app.py` 最终只负责初始化、路由和页面分发。

本文档确定的是迁移方向和边界。每个 Phase 开始前仍需单独制定实现计划、回归范围和兼容策略，不应一次性重构整个状态系统。
