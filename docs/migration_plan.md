# 成绩分析助手架构迁移实施计划

> **面向后续实施人员：** 本计划应逐阶段执行。每个阶段都必须遵循 TDD，先增加失败测试，再进行最小实现，并在进入下一阶段前完成回归验证。不得把四个阶段合并为一次性重构。

**目标：** 将当前平铺的 `st.session_state` 和混合型 `current_exam_snapshot` 渐进迁移到 `ExamContext`、`ExamConfig`、`PageState`、`Result` 与独立 Report 状态，同时保持现有业务行为、成绩公式和 Excel 解析结果不变。

**架构策略：** 采用兼容式单向迁移。每个阶段只允许一个权威数据源，新旧结构不得双向同步。页面按“报告中心 → 学科分析 → 班级分析 → 年级总览”的顺序切换读取来源，最后统一删除旧状态。

**技术栈：** Python、dataclasses、Streamlit session state、pandas、现有成绩/图表/报告模块、unittest。

## 全局约束

- 不修改 `grade_logic.py` 中的成绩计算公式。
- 不修改 Excel 解析规则和表头识别行为。
- 不修改 `student_identity.py` 的身份规则。
- 逐行身份和成绩继续通过原始 DataFrame index 关联。
- 页面不得直接修改 `ExamContext`。
- Widget key 不得作为业务配置的唯一真值。
- 每个阶段必须可独立回归、可停止，不依赖后续阶段才能保持现有功能可用。
- 本计划不包含 Git 操作说明。

---

## 1. 当前核心状态分析

### 1.1 `current_exam_snapshot`

当前职责：

- 保存当前分析结果、优秀名单和待提升名单；
- 保存分布数据及多个 Plotly figure；
- 保存当前班级、科目、满分和优秀线；
- 保存姓名列、班级列、学号列和可用科目；
- 保存 `identity_records_by_index` 和 `subject_scores_by_index`；
- 保存报告名称和报告生成输入。

问题：

- 同时混合考试事实、配置、页面选择、Result 和 Report 输入；
- 任一页面配置变化都会使整个 snapshot 的有效性不明确；
- 学科、班级和报告页面依赖同一个大对象；
- 图表和名单均可从结构化 Result 派生，却长期保存在 session 中。

未来拆分：

| Snapshot 字段 | 未来归属 |
|---|---|
| `name_col`、`class_col`、`student_id_col`、`score_options` | `ExamContext.schema` |
| `identity_records_by_index`、`subject_scores_by_index` | `ExamContext` |
| `score_col`、`selected_class` | `PageState.grade_overview` |
| `full_score`、`excellent_percent`、`full_score_by_column` | `ExamConfig` |
| `analysis_result`、`distribution` | `Result` |
| `excellent_df`、`fail_df` | 由 Result 派生的展示/报告数据 |
| `distribution_figure`、`level_figure`、`subject_average_figure` | 展示缓存，不进入 ExamContext |
| `report_name` | Report draft |

最终处理：完成页面迁移后删除整个 `current_exam_snapshot`。

### 1.2 `full_score_by_context`

当前职责：按“文件指纹 + 工作表 + 清洗后的科目名称”保存年级总览满分。

问题：

- 与动态 Widget key、snapshot 满分、学科配置和班级满分重复；
- context 由技术实现细节组成，而不是稳定 `exam_id`；
- 无法明确学科、班级页面使用的是统一满分还是页面 override。

未来归属：

```text
ExamConfig.subjects[subject].full_score
```

如果产品确认页面允许独立口径，则保存为：

```text
ExamConfig.page_overrides[page_name][subject]
```

最终处理：Phase 3 完成配置迁移后兼容保留，Phase 4 删除。

### 1.3 `analysis_score_column`

当前职责：年级总览当前选择的成绩列。

它不是考试数据，也不是考试规则，属于用户在年级总览页面的选择。

未来归属：

```text
PageState.by_exam[exam_id].grade_overview.selected_subject
```

最终处理：年级总览完成 PageState 迁移后删除。

### 1.4 `analysis_excellent_percent`

当前职责：年级总览优秀线，全局平铺保存。

问题：没有考试命名空间，新考试可能继承上一场考试的优秀线。

未来归属：

```text
ExamConfig.rules.excellent_percent
```

如果年级总览使用独立口径，则归属：

```text
ExamConfig.page_overrides["grade_overview"]
```

最终处理：Phase 3 配置迁移期间兼容保留，Phase 4 删除。

### 1.5 `subject_analysis_score_column`

当前职责：学科分析当前选择的科目。

未来归属：

```text
PageState.by_exam[exam_id].subject_analysis.selected_subject
```

相关的满分和优秀线不属于 PageState，应迁移到 `ExamConfig` 的学科分析 override。

最终处理：学科分析完成 PageState 迁移后删除。

### 1.6 `class_analysis_score_column`

当前职责：班级分析当前选择的科目。

未来归属：

```text
PageState.by_exam[exam_id].class_analysis.selected_subject
```

相关状态同时迁移：

| 当前状态 | 未来归属 |
|---|---|
| `class_analysis_classes` | `PageState.class_analysis.selected_classes` |
| `class_analysis_full_score` | `ExamConfig` canonical 满分或 class override |
| `class_analysis_excellent_percent` | `ExamConfig.page_overrides.class_analysis` |

最终处理：班级分析完成迁移后删除平铺状态。

### 1.7 `word_report_*`

当前状态分为两类。

报告草稿：

- `word_report_school_name`
- `word_report_exam_name`

未来归属：

```text
PageState.by_exam[exam_id].report_center
```

或由独立 `ReportDraft` 封装。

报告缓存：

- `word_report_signature`
- `word_report_bytes`
- `word_report_filename`

未来归属：

```text
ReportCache[(exam_id, result_key, report_signature)]
```

问题：年级总览导出区和报告中心共用同名 key，但使用不同签名结构。

最终处理：报告中心迁移后先兼容保留旧缓存；年级总览报告入口迁移完成后统一删除旧 key。

### 1.8 `analysis_result`

当前状态：它不是独立的顶层 session key，而是年级流程中的局部变量，并复制进入 `current_exam_snapshot["analysis_result"]`。

未来归属：

```text
AnalysisResult(
    key=ResultKey(
        exam_id,
        config_version,
        analysis_type,
        request_signature,
    ),
    payload=...,
)
```

Result 只保存结构化、可验证的派生数据。Plotly figure 和 Word bytes 不放入 Result payload。

最终处理：保留现有局部计算流程直到年级总览迁移；删除 snapshot 中的副本。

## 2. 状态归属总表

| 当前状态 | 当前权威来源 | 未来归属 | 迁移期间策略 | 最终处理 |
|---|---|---|---|---|
| `current_exam_snapshot` | session snapshot | ExamContext + ExamConfig + Result + Report | Phase 2/3 只读兼容 | 删除 |
| `full_score_by_context` | 年级业务配置 | ExamConfig | 由配置 Adapter 单向读取 | 删除 |
| `analysis_score_column` | 年级 Widget/Page | PageState | 迁移年级页前保留 | 删除旧 key |
| `analysis_excellent_percent` | 年级 Widget/配置 | ExamConfig | 迁移配置前保留 | 删除旧 key |
| `subject_analysis_score_column` | 学科 Page | PageState | 学科页迁移前保留 | 删除旧 key |
| `class_analysis_score_column` | 班级 Page | PageState | 班级页迁移前保留 | 删除旧 key |
| `class_analysis_classes` | 班级 Page | PageState | 与科目同时迁移 | 删除旧 key |
| `class_analysis_full_score` | 班级 Widget/配置 | ExamConfig | 配置迁移前保留 | 删除旧 key |
| `class_analysis_excellent_percent` | 班级 Widget/配置 | ExamConfig | 配置迁移前保留 | 删除旧 key |
| `word_report_school_name` | 报告 Widget | Report draft/PageState | 两个入口统一后迁移 | 删除旧 key |
| `word_report_exam_name` | 报告 Widget + snapshot | Report draft/PageState | 暂时兼容旧报告名 | 删除重复字段 |
| `word_report_signature` | 报告缓存 | Report | 新旧缓存不可共用签名 | 删除旧 key |
| `word_report_bytes` | 报告缓存 | Report | 新缓存生效前保留 | 删除旧 key |
| `word_report_filename` | 报告缓存 | Report | 与 bytes 同步迁移 | 删除旧 key |
| snapshot 中 `analysis_result` | snapshot | Result | 使用 Result Adapter 对比 | 删除 snapshot 副本 |

## 3. 兼容迁移原则

### 3.1 禁止双向同步

每个阶段只能有一个权威来源：

- Phase 2：旧上传/分析流程是权威来源，新 ExamContext 是只读镜像；
- Phase 3 某页面迁移前：旧状态是该页面权威来源；
- Phase 3 某页面迁移后：新对象是该页面唯一权威来源，旧状态只允许 compatibility adapter 读取；
- Phase 4：删除 adapter 和旧状态。

不得出现：

```text
旧状态更新新对象
同时
新对象反向更新旧状态
```

这会造成 rerun 顺序依赖和循环覆盖。

### 3.2 兼容读取顺序

迁移页面建议使用集中式 Store/Adapter：

```text
读取新对象
    ↓ 不存在
由旧状态一次性构造新对象
    ↓
后续只读取新对象
```

页面内部不得散落 `new_state or legacy_state` 判断。

### 3.3 结果一致性

新旧 Result 并存期间必须比较：

- 学生数、有效成绩数；
- 平均分、最高分、最低分；
- 及格率、优秀率；
- 等级人数；
- 优秀和待提升学生 identity key；
- 班级汇总；
- 报告所引用的参数。

任何一项不一致都应阻止删除旧路径。

## 4. Phase 1：新增模型，不影响旧代码

### 当前状态

本阶段的数据模型骨架已经存在：

- `models/exam_context.py`
- `models/exam_config.py`
- `models/page_state.py`
- `models/result.py`
- `models/__init__.py`
- `test_models.py`

现有业务模块没有导入 `models`，因此当前行为不受影响。

### 后续修改范围

Phase 1 不再修改业务代码。进入 Phase 2 前只允许完善模型契约测试和文档，不接入 `app.py`。

### 风险

- dataclass 为浅层冻结，内部 Mapping 仍可能被调用方修改；
- 模型字段与当前 snapshot 字段可能出现命名偏差；
- 过早增加复杂校验会影响兼容数据导入。

### 验证方式

- `test_models.py` 验证默认容器不共享；
- 验证 `ExamContext` 不包含页面选择字段；
- 验证 PageState 按 exam_id 隔离；
- 验证不同 `config_version` 生成不同 ResultKey；
- 静态搜索确认现有业务模块没有导入 `models`。

### 阶段退出条件

- 模型公共接口固定；
- 架构设计和模型字段一致；
- 现有业务测试行为不变。

## 5. Phase 2：上传流程生成 ExamContext

### 目标

保留现有 Excel 解析、字段识别和身份生成流程，在分析成功后额外创建 ExamContext、初始 ExamConfig 和 PageState。此阶段任何页面仍可继续读取旧 snapshot。

### 预计修改文件

新增：

- `services/exam_context_factory.py`：从已确认字段和逐行映射创建 ExamContext；
- `services/exam_config_factory.py`：根据现有满分配置和默认规则创建 ExamConfig；
- `state/exam_store.py`：集中保存/读取 `current_exam_id`、contexts、configs 和 page state；
- `test_exam_context_factory.py`；
- `test_exam_store.py`。

修改：

- `app.py`：仅在现有分析完成、身份映射构造成功后调用 factory/store；
- `ui_exam_center.py`：新考试切换时初始化新 Store，不改变旧 snapshot 清理行为；
- `test_ui_exam_center.py`：验证上传后新旧结构同时存在且参数一致。

禁止修改：

- `grade_logic.py`；
- `chart_logic.py`；
- `student_identity.py`；
- `report_logic.py`；
- Excel 读取和字段识别函数。

### 推荐接口

```text
build_exam_context(
    exam_id,
    file_name,
    file_fingerprint,
    sheet_name,
    name_column,
    class_column,
    student_id_column,
    score_columns,
    identity_records_by_index,
    subject_scores_by_index,
) -> ExamContext

build_initial_exam_config(
    exam_context,
    legacy_full_scores,
    excellent_percent,
) -> ExamConfig

save_exam_bundle(
    session_state,
    context,
    config,
    page_state,
) -> None
```

### 单向数据流

```text
现有上传/分析流程
    ↓
现有身份与逐科成绩映射
    ↓
ExamContextFactory
    ↓
ExamStore

旧 snapshot 不读取新对象，也不由新对象反向更新。
```

### 风险

- 新旧结构身份行 index 不一致；
- exam_id 在 rerun 中不稳定，导致同一考试生成多个对象；
- 新文件没有正确切换 current_exam_id；
- 旧 snapshot 已生成但新 ExamContext 创建失败；
- 存储完整文件 bytes、Context 和 snapshot 造成阶段性内存增加。

### 验证方式

1. 同一文件、工作表和字段映射在 rerun 后得到相同 exam_id；
2. 新文件或新工作表得到不同 exam_id；
3. ExamContext 行 index 与 snapshot 身份/成绩映射完全一致；
4. 重复姓名、跨班同名、有学号同名测试通过；
5. 上传后自动滚动保持；
6. 年级总览结果与迁移前一致；
7. 报告、学科和班级页面仍可通过旧 snapshot 工作；
8. ExamContext 创建失败时显示明确错误，不覆盖已存在的有效 Context。

### 阶段退出条件

- 每次成功上传都生成稳定 ExamContext；
- ExamConfig 和 PageState 已按 exam_id 初始化；
- 所有现有页面行为不变；
- 新结构可由测试独立读取，但还没有成为页面权威来源。

## 6. Phase 3：页面逐步读取新结构

### 总体迁移顺序

```text
3A 报告中心
    ↓
3B 学科分析
    ↓
3C 班级分析
    ↓
3D 年级总览
```

先迁移只读或已隔离页面，最后迁移仍承担 Excel 和 snapshot 生产职责的年级总览。

### 3A：报告中心

预计修改文件：

- `app.py` 或未来独立的报告页面模块；
- `state/exam_store.py`；
- 新增 `state/report_store.py`；
- `test_ui_exam_center.py`；
- `test_report_logic.py` 只增加调用边界测试，不修改报告公式。

迁移动作：

- 从 ExamStore 读取当前 ExamContext；
- 从 ResultStore 读取被引用的 Result；
- 报告草稿迁移到 PageState/ReportDraft；
- 报告 bytes、filename、signature 迁移到 ReportStore；
- 保持 `build_score_report_bytes()` 不变。

风险：

- 新 Result 尚未包含报告所需的全部展示数据；
- 新旧报告签名不同导致错误复用缓存；
- 报告标题在两个入口之间继续共享。

验证方式：

- 报告中心不调用 `pd.read_excel()`、字段识别或 `analyze_scores()`；
- Word 输入参数与旧 snapshot 完全一致；
- 进入和离开报告中心不改变 ExamConfig/PageState 的年级配置；
- 相同签名复用缓存，不同 config version 强制重新生成。

### 3B：学科分析

预计修改文件：

- `app.py` 或未来独立的学科分析页面模块；
- `state/exam_store.py`；
- 新增 `state/result_store.py`；
- `test_ui_exam_center.py`；
- 新增学科 Result 对比测试。

迁移动作：

- 使用 `PageState.subject_analysis.selected_subject`；
- 使用 ExamContext 的 index 身份和逐科成绩；
- 使用 ExamConfig canonical 配置或 subject override；
- 将结构化分析输出包装为 AnalysisResult；
- 图表继续由现有图表函数生成，不放入 ExamContext。

风险：

- 旧学科 Widget key 覆盖新配置；
- 科目切换时读取错误 override；
- Result request signature 不包含科目或配置版本；
- 同名学生绑定出现回归。

验证方式：

- 页面不读取 Excel、不重新构建身份、不按姓名匹配；
- 数学/英语 PageState 和配置独立；
- 新旧学科指标、班级对比和等级结构一致；
- 页面切换不修改年级和班级状态。

### 3C：班级分析

预计修改文件：

- `app.py` 或未来独立的班级分析页面模块；
- `state/exam_store.py`；
- `state/result_store.py`；
- `test_ui_exam_center.py`；
- `test_class_comparison_logic.py` 只增加输入一致性测试。

迁移动作：

- 使用 `PageState.class_analysis` 保存科目和班级集合；
- 将满分和优秀线迁入 ExamConfig；
- 使用 ExamContext 按原始行 index 构造 DataFrame；
- 保持 `build_class_comparison()` 不变；
- 将比较结果登记到 ResultStore。

风险：

- 当前单一 `class_analysis_full_score` 不能正确映射到多个科目；
- 新考试继承旧班级集合；
- 班级名称相同但考试不同导致 PageState 混用。

验证方式：

- PageState 按 exam_id 隔离；
- 不同科目满分和优秀线独立；
- build_class_comparison 收到的新旧 DataFrame 和参数一致；
- 跨班同名、同班同名和有学号同名测试通过。

### 3D：年级总览

预计修改文件：

- `app.py`；
- 可新增 `pages/grade_overview.py`；
- `state/exam_store.py`；
- `state/result_store.py`；
- `test_ui_exam_center.py`；
- 新增完整年级总览 Result 对比测试。

迁移动作：

- 上传/字段确认与年级展示流程分离；
- 年级页面读取 ExamContext，不再在每次 rerun 调用 `pd.read_excel()`；
- 当前科目和班级迁入 PageState；
- 满分和优秀线迁入 ExamConfig；
- `analysis_result`、distribution 等迁入 ResultStore；
- 旧 snapshot 只由 compatibility adapter 提供给尚未删除的旧报告入口。

风险：

- 年级页面是当前主流程，改动范围最大；
- 上传后 `single_class → analysis_center` 的 rerun/滚动行为变化；
- 字段识别控件与只读考试上下文边界不清；
- Result 与展示 DataFrame 的排名、名称恢复不一致。

验证方式：

- 上传成功后只读取 Excel 一次；
- 年级页面 rerun 和页面切换不再读取 Excel；
- 字段、科目、班级、满分和优秀线迁移前后保持一致；
- 学生数、指标、分布、名单、图表和导出 Excel 一致；
- 上传后的自动滚动保持；
- 报告、学科、班级回归全部通过。

### Phase 3 配置迁移规则

页面迁移时必须同时明确配置的 canonical 来源：

| 规则 | 默认来源 | 页面独立需求 |
|---|---|---|
| 科目满分 | `ExamConfig.subjects[subject]` | 只有产品明确要求时使用 override |
| 及格线 | `ExamConfig.rules.pass_percent`，当前固定 60% | 页面不得创建独立 Widget 业务状态 |
| 默认优秀线 | `ExamConfig.rules.excellent_percent` | 学科/班级独立值进入对应 override |
| 等级规则 | `ExamConfig.rules.levels` | 第一阶段不提供页面修改入口 |

配置每次业务修改必须生成新版本 ExamConfig 或递增版本，并使相同 exam_id 的旧 Result 和 Report 缓存失效。

### Phase 3 阶段退出条件

- 四个页面都不再读取 `current_exam_snapshot`；
- 四个页面都通过 Store 获取对象；
- ResultKey 包含 exam_id、config_version、analysis_type 和请求签名；
- 新对象成为唯一业务真值；
- compatibility adapter 仅供 Phase 4 清理检查，不再参与正常页面路径。

## 7. Phase 4：删除旧 session_state

### 目标

删除兼容层、重复状态和动态业务镜像，使新架构成为唯一读写路径。

### 预计修改文件

- `app.py`；
- `ui_exam_center.py`；
- `state/exam_store.py`；
- `state/result_store.py`；
- `state/report_store.py`；
- 所有引用旧 key 的测试文件；
- `docs/architecture_design.md` 和本计划的完成状态说明。

### 可以删除的旧变量

确认所有页面完成迁移后删除：

- `current_exam_snapshot`；
- `full_score_by_context`；
- `analysis_score_column`；
- `analysis_excellent_percent`；
- `analysis_single_class`；
- `selected_class`；
- `subject_analysis_score_column`；
- `subject_analysis_full_score_by_context`；
- `subject_analysis_excellent_percent_by_context`；
- `class_analysis_score_column`；
- `class_analysis_full_score`；
- `class_analysis_excellent_percent`；
- `class_analysis_classes`；
- `word_report_school_name`；
- `word_report_exam_name`；
- `word_report_signature`；
- `word_report_bytes`；
- `word_report_filename`；
- 所有 `full_score::<context>::<subject>` 旧业务 Widget key；
- 所有 `subject_analysis::<...>` 旧业务 Widget key；
- 固定规则的 `analysis_pass_percent` session 值。

删除的是旧命名空间和重复真值，不是对应功能。新 PageState Widget 仍可拥有稳定 UI key，但不能承担业务持久化职责。

### 需要长期保留或迁移后保留的状态

| 状态 | 处理 |
|---|---|
| `analysis_mode` | 可临时保留，最终映射到 `PageState.route` |
| `analysis_center_scroll_pending` | 作为一次性 UI 状态保留 |
| `current_exam_file_bytes` | 在文件缓存方案确定前兼容保留，或迁移到外部缓存 |
| `current_exam_file_name` | 迁入 ExamContext 后删除旧顶层 key |
| `current_exam_id` | 新架构顶层入口，长期保留 |
| `exam_contexts` | 长期保留或替换为持久化仓库引用 |
| `exam_configs` | 长期保留 |
| `page_state` | 长期保留 |
| `result_store` | 长期保留或替换为缓存服务 |
| `report_cache` | 长期保留或替换为临时文件缓存 |
| `ui_state` | 只保存临时 UI 行为 |

### 风险

- 某个动态 Widget 仍隐式依赖旧 key；
- 当前会话中残留旧状态，升级后与新对象冲突；
- 测试只检查源码字符串，未覆盖真实 Streamlit widget 生命周期；
- 删除 snapshot 后报告或下载功能仍存在隐藏读取；
- 旧会话恢复时缺少新 `current_exam_id`。

### 验证方式

1. 全项目搜索所有旧 key，生产代码命中为零；
2. 新会话和包含旧状态的升级会话均能进入首页；
3. 完整链路通过：

   ```text
   上传 Excel
   → 完成字段确认
   → 年级总览
   → 学科分析
   → 班级分析
   → 报告中心生成 Word
   → 返回年级总览
   ```

4. 上述过程中科目、满分、优秀线和班级范围保持页面级隔离；
5. 新考试不会继承旧考试配置；
6. 页面切换不调用 `pd.read_excel()`；
7. 重复姓名、跨班同名、有学号同名测试通过；
8. Excel 导出和 Word 报告结果保持一致；
9. Result 和 Report cache 在 config version 变化后失效；
10. 真实 Streamlit rerun/widget 测试覆盖页面切换。

### 阶段退出条件

- 旧 key 在生产代码中完全消失；
- compatibility adapter 已删除；
- 所有页面只通过 Store 访问新模型；
- `current_exam_snapshot` 不再存在；
- 完整测试和真实页面链路通过。

## 8. 测试矩阵

| 场景 | Phase 2 | Phase 3 | Phase 4 |
|---|---:|---:|---:|
| ExamContext 与旧 snapshot 身份/成绩一致 | 必须 | 必须 | 不再比较旧结构 |
| 稳定 exam_id | 必须 | 必须 | 必须 |
| 年级结果一致 | 回归 | 新旧对比 | 新路径回归 |
| 学科配置隔离 | 回归 | 新旧对比 | 新路径回归 |
| 班级配置跨考试隔离 | 回归 | 新旧对比 | 新路径回归 |
| 报告状态隔离 | 回归 | 新旧对比 | 新路径回归 |
| 重复姓名身份 | 必须 | 必须 | 必须 |
| 自动滚动 | 必须 | 必须 | 必须 |
| 页面切换不读取 Excel | 暂不要求 | 已迁移页面必须 | 所有页面必须 |
| 旧会话升级 | 不要求 | 开始覆盖 | 必须 |
| 旧 key 静态搜索 | 允许 | 逐步减少 | 生产代码为零 |

## 9. 回滚边界

每个阶段必须具备明确回滚边界：

- Phase 1 回滚：删除未接线的模型骨架，不影响业务；
- Phase 2 回滚：停止创建新对象，旧 snapshot 页面继续工作；
- Phase 3 单页面回滚：该页面重新通过 compatibility adapter 读取旧状态，其他已迁移页面不回退；
- Phase 4 不应在删除前依赖回滚。只有所有旧读取均为零、完整链路通过后才允许删除旧状态。

禁止在 Phase 4 删除旧状态后，再通过散落的 fallback 恢复部分旧逻辑。若验证失败，应回退整个清理阶段，而不是重新建立双向同步。

## 10. 实施检查清单

- [ ] Phase 1 模型契约和现有文档一致。
- [ ] Phase 2 上传成功后生成稳定 ExamContext、ExamConfig 和 PageState。
- [ ] 新旧身份和逐科成绩按原始行 index 完全一致。
- [ ] 报告中心已迁移并保持只读。
- [ ] 学科分析已迁移，不读取 Excel、不重建身份。
- [ ] 班级分析已迁移，配置按考试和科目隔离。
- [ ] 年级总览已迁移，rerun 不重新读取 Excel。
- [ ] ResultKey 覆盖 exam_id、config_version、analysis_type 和请求签名。
- [ ] ReportCache 使用统一签名。
- [ ] 所有旧 session key 的生产读取已归零。
- [ ] 完整用户链路及身份回归通过。
- [ ] compatibility adapter 已删除。

本计划的实施终点不是“新模型已经存在”，而是所有页面只通过明确的 Store/API 读取 ExamContext、ExamConfig、PageState、Result 和 Report，且旧 session 状态不再承担任何业务真值职责。
