import ast
import sys
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd
from openpyxl import Workbook


if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = ModuleType("streamlit")

import ui_exam_center
from grade_logic import (
    analyze_scores,
    clean_column_name,
    get_full_score_suggestion,
    resolve_column_selection,
)
from models import (
    ExamConfig,
    ExamContext,
    ExamMetadata,
    ExamSchema,
    PageState,
    SubjectConfig,
)
from services import (
    ExamColumnMapping,
    ExamImportDraft,
    ExamImportError,
    ExamImportService,
    build_exam_config,
    build_grade_overview_dataframe,
    effective_config,
)
from student_identity import build_student_identity_records, build_student_score_mapping


def load_app_function(function_name, extra_namespace=None):
    source = Path("app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function_node = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        ),
        None,
    )
    if function_node is None:
        raise AssertionError(f"app.py 缺少函数：{function_name}")
    module = ast.Module(body=[function_node], type_ignores=[])
    namespace = {"build_student_score_mapping": build_student_score_mapping}
    namespace.update(extra_namespace or {})
    exec(compile(module, "app.py", "exec"), namespace)
    return namespace[function_name]


class UiExamCenterTest(unittest.TestCase):
    def test_center_renders_exam_context_without_analysis_view_copy(self):
        streamlit = MagicMock()

        with patch.object(ui_exam_center, "st", streamlit):
            ui_exam_center.render_exam_analysis_center(
                exam_name="2026期中考试",
                exam_time="2026-05-12",
                student_count=45,
                class_count=3,
                subject="数学",
                data_status="已就绪",
            )

        rendered_html = "\n".join(
            call.args[0] for call in streamlit.markdown.call_args_list
        )
        for expected in (
            "考试分析中心",
            "2026期中考试",
            "2026-05-12",
            "45",
            "3",
            "数学",
            "已就绪",
        ):
            self.assertIn(expected, rendered_html)
        for removed_copy in (
            "分析视角",
            "选择你想查看的分析视角",
            "查看整体成绩水平、成绩分布、等级结构和核心指标。",
            "从任课教师角度查看负责学科和班级表现。",
        ):
            self.assertNotIn(removed_copy, rendered_html)

    def test_center_does_not_render_analysis_view_buttons_or_grid(self):
        streamlit = MagicMock()

        with patch.object(ui_exam_center, "st", streamlit):
            ui_exam_center.render_exam_analysis_center(
                exam_name="本次考试",
                exam_time="未设置",
                student_count=2,
                class_count=1,
                subject="数学",
                data_status="已就绪",
            )

        streamlit.columns.assert_not_called()
        streamlit.button.assert_not_called()

    def test_teacher_view_is_an_independent_planning_placeholder(self):
        streamlit = MagicMock()

        with patch.object(ui_exam_center, "st", streamlit):
            ui_exam_center.render_teacher_view_placeholder()

        rendered = "\n".join(
            call.args[0] for call in streamlit.markdown.call_args_list
        )
        for expected in (
            "教师视角（规划中）",
            "所教学科整体表现",
            "不同班级教学效果",
            "学生薄弱知识点分析",
            "该功能将在后续版本开放。",
        ):
            self.assertIn(expected, rendered)

    def test_exam_comparison_is_an_extension_placeholder(self):
        streamlit = MagicMock()

        with patch.object(ui_exam_center, "st", streamlit):
            ui_exam_center.render_exam_comparison_placeholder()

        rendered_html = "\n".join(
            call.args[0] for call in streamlit.markdown.call_args_list
        )
        self.assertIn("选择另一场考试后，查看学生进步、下降和成长趋势。", rendered_html)
        self.assertIn("后续扩展", rendered_html)

    def test_teacher_view_route_stops_before_score_workflow(self):
        source = Path("app.py").read_text(encoding="utf-8")
        teacher_gate = source.index('if analysis_mode == "teacher_view":')
        workflow_mapping = source.index("workflow_mode =")
        block = source[teacher_gate:workflow_mapping]

        self.assertIn("render_teacher_view_placeholder()", block)
        self.assertIn("st.stop()", block)
        self.assertNotIn("analyze_scores", block)

    def test_analysis_views_resolve_to_existing_workflows(self):
        self.assertEqual(
            ui_exam_center.resolve_exam_workflow_mode("analysis_center"),
            "single_class",
        )
        self.assertEqual(
            ui_exam_center.resolve_exam_workflow_mode("subject_analysis"),
            "subject_analysis",
        )
        self.assertEqual(
            ui_exam_center.resolve_exam_workflow_mode("report_center"),
            "report_center",
        )
        self.assertEqual(
            ui_exam_center.resolve_exam_workflow_mode("class_comparison"),
            "class_comparison",
        )

    def test_app_uses_independent_analysis_center_state_after_analysis(self):
        source = Path("app.py").read_text(encoding="utf-8")
        analysis_position = source.index("identity_analysis_result = analyze_scores")
        transition_position = source.index(
            "activate_analysis_center(st.session_state)",
            analysis_position,
        )
        center_position = source.index("render_exam_analysis_center(")
        overview_position = source.index('render_anchor("section-overview")')

        self.assertIn("resolve_exam_workflow_mode(analysis_mode)", source)
        self.assertLess(analysis_position, transition_position)
        self.assertLess(transition_position, center_position)
        self.assertLess(center_position, overview_position)
        self.assertIn("st.rerun()", source[transition_position:center_position])

    def test_single_class_remains_upload_initialization_state(self):
        source = Path("app.py").read_text(encoding="utf-8")
        upload_position = source.index("st.file_uploader(")
        analysis_position = source.index("identity_analysis_result = analyze_scores")
        transition_position = source.index(
            "activate_analysis_center(st.session_state)",
            analysis_position,
        )

        self.assertLess(upload_position, analysis_position)
        self.assertLess(analysis_position, transition_position)
        self.assertIn('if analysis_mode == "single_class":', source)

    def test_excel_upload_only_accepts_xlsx_with_explicit_guidance(self):
        source = Path("app.py").read_text(encoding="utf-8")
        upload_start = source.index("st.file_uploader(")
        upload_end = source.index("st.download_button(", upload_start)
        upload_block = source[upload_start:upload_end]

        self.assertIn('type=["xlsx"]', upload_block)
        self.assertNotIn('"xls"', upload_block)
        self.assertIn("请上传 .xlsx 格式 Excel 文件。", upload_block)

    def test_analysis_center_without_exam_context_returns_to_upload(self):
        source = Path("app.py").read_text(encoding="utf-8")
        guard = source.index(
            'if analysis_mode == "analysis_center" and not st.session_state.get('
        )
        workflow_mapping = source.index("workflow_mode =")

        self.assertLess(guard, workflow_mapping)
        guard_block = source[guard:workflow_mapping]
        self.assertIn(
            'st.session_state["analysis_mode"] = "single_class"',
            guard_block,
        )
        self.assertIn("st.rerun()", guard_block)

    def test_exam_class_count_excludes_all_students_scope(self):
        self.assertEqual(
            ui_exam_center.count_exam_classes(
                ["全部学生", "2501", "2502", "2503"],
                has_class_column=True,
            ),
            3,
        )

    def test_exam_student_count_uses_roster_not_valid_subject_scores(self):
        dataframe = pd.DataFrame(
            {
                "姓名": ["张三", "李四", "王五", "张三", "", None],
                "班级": ["2501", "2501", "2501", "2502", "2501", "2501"],
                "数学": [90, None, 150, 80, 70, 60],
            }
        )

        self.assertEqual(
            ui_exam_center.count_exam_students(
                dataframe,
                name_column="姓名",
                class_column="班级",
            ),
            4,
        )

    def test_exam_student_count_uses_student_id_before_class_and_name(self):
        dataframe = pd.DataFrame(
            {
                "学号": ["S1", "S2"],
                "姓名": ["张三", "张三"],
                "班级": ["2401", "2401"],
                "数学": [90, 60],
            }
        )

        self.assertEqual(
            ui_exam_center.count_exam_students(
                dataframe,
                name_column="姓名",
                class_column="班级",
                student_id_column="学号",
            ),
            2,
        )

    def test_student_growth_route_stops_before_score_workflow(self):
        source = Path("app.py").read_text(encoding="utf-8")
        growth_gate = source.index('if analysis_mode == "exam_comparison":')
        teacher_gate = source.index('if analysis_mode == "teacher_view":')
        block = source[growth_gate:teacher_gate]

        self.assertIn("render_exam_comparison_placeholder()", block)
        self.assertIn("st.stop()", block)
        self.assertNotIn("analyze_scores", block)

    def test_subject_analysis_uses_subject_specific_workflow_copy(self):
        source = Path("app.py").read_text(encoding="utf-8")

        self.assertIn(
            '("选择科目", "查看指标", "班级对比", "等级结构")',
            source,
        )
        self.assertEqual(
            ui_exam_center.count_exam_classes([], has_class_column=False),
            1,
        )

    def test_subject_analysis_uses_snapshot_and_stops_before_excel_workflow(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("def render_subject_analysis_page(", source)
        subject_function = source.index("def render_subject_analysis_page(")
        subject_route = source.index(
            'if analysis_mode == "subject_analysis":', subject_function
        )
        excel_workflow = source.index("uploaded_file = None", subject_route)
        route_block = source[subject_route:excel_workflow]

        self.assertIn('st.session_state.get("current_exam_snapshot")', route_block)
        self.assertIn("render_subject_analysis_page(snapshot)", route_block)
        self.assertIn("st.stop()", route_block)
        for forbidden_call in (
            "restore_current_exam_file(",
            "pd.ExcelFile(",
            "pd.read_excel(",
            'key="analysis_score_column"',
            "set_column_full_score(",
        ):
            self.assertNotIn(forbidden_call, route_block)

    def test_subject_analysis_uses_independent_state_and_first_version_outputs(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("def render_subject_analysis_page(", source)
        subject_function = source.index("def render_subject_analysis_page(")
        subject_route = source.index(
            'if analysis_mode == "subject_analysis":', subject_function
        )
        function_block = source[subject_function:subject_route]

        self.assertIn('key="subject_analysis_score_column"', function_block)
        self.assertIn("render_metric_grid(subject_analysis_result)", function_block)
        self.assertIn("build_average_rate_figure(comparison.summary)", function_block)
        self.assertIn("build_level_structure_figure(comparison.levels)", function_block)
        self.assertNotIn('key="analysis_score_column"', function_block)
        self.assertNotIn("build_comparison_conclusion(", function_block)
        self.assertNotIn("build_score_report_bytes(", function_block)
        self.assertNotIn("build_display_student_list(", function_block)

    def test_subject_analysis_uses_independent_parameter_state_and_settings_card(self):
        source = Path("app.py").read_text(encoding="utf-8")
        subject_function = source.index("def render_subject_analysis_page(")
        subject_end = source.index("def render_class_analysis_page(", subject_function)
        function_block = source[subject_function:subject_end]

        self.assertIn('"学科分析设置"', function_block)
        self.assertIn('key="subject_analysis_score_column"', function_block)
        self.assertIn('"subject_analysis_full_score_by_context"', source)
        self.assertIn('"subject_analysis_excellent_percent_by_context"', source)
        self.assertIn("subject_analysis::full_score::", function_block)
        self.assertIn("subject_analysis::excellent_percent::", function_block)
        self.assertIn('st.metric("及格线", "60%"', function_block)
        for forbidden_state in (
            '"analysis_score_column"',
            '"analysis_excellent_percent"',
            '"full_score_by_context"',
            '"selected_class"',
        ):
            self.assertNotIn(forbidden_state, function_block)

    def test_subject_analysis_parameters_are_isolated_by_subject_and_grade_state(self):
        initialize_parameters = load_app_function(
            "initialize_subject_analysis_parameters",
            {
                "clean_column_name": clean_column_name,
                "get_full_score_suggestion": get_full_score_suggestion,
            },
        )
        session_state = {
            "analysis_score_column": "语文",
            "analysis_excellent_percent": 82.0,
            "full_score_by_context": {"exam-sheet": {"语文": 120.0}},
            "selected_class": "全部学生",
        }
        watched = deepcopy(session_state)
        snapshot = {
            "score_context_key": "exam-sheet",
            "full_score_by_column": {"数学": 120.0, "英语": 150.0},
        }

        math_full, math_excellent = initialize_parameters(
            session_state,
            snapshot,
            "数学",
        )
        session_state["subject_analysis_full_score_by_context"]["exam-sheet"]["数学"] = 130.0
        session_state["subject_analysis_excellent_percent_by_context"]["exam-sheet"]["数学"] = 88.0
        english_full, english_excellent = initialize_parameters(
            session_state,
            snapshot,
            "英语",
        )

        self.assertEqual(math_full, 120.0)
        self.assertEqual(math_excellent, 90.0)
        self.assertEqual(english_full, 150.0)
        self.assertEqual(english_excellent, 90.0)
        self.assertEqual(
            session_state["subject_analysis_full_score_by_context"]["exam-sheet"]["数学"],
            130.0,
        )
        self.assertEqual(
            session_state["subject_analysis_excellent_percent_by_context"]["exam-sheet"]["数学"],
            88.0,
        )
        self.assertEqual(
            {key: session_state[key] for key in watched},
            watched,
        )

    def test_subject_analysis_passes_local_parameters_to_class_comparison(self):
        comparison_builder = MagicMock(return_value="subject-comparison")
        build_comparison = load_app_function(
            "build_subject_analysis_comparison",
            {"build_class_comparison": comparison_builder},
        )
        dataframe = pd.DataFrame(
            {
                "班级": ["2401", "2402"],
                "姓名": ["张三", "张三"],
                "数学": [91.0, 87.0],
            },
            index=[7, 9],
        )

        result = build_comparison(
            dataframe,
            class_col="班级",
            name_col="姓名",
            score_col="数学",
            selected_classes=["2401", "2402"],
            full_score=130.0,
            excellent_percent=88.0,
        )

        self.assertEqual(result, "subject-comparison")
        call = comparison_builder.call_args
        pd.testing.assert_frame_equal(call.args[0], dataframe)
        self.assertEqual(call.kwargs["score_column"], "数学")
        self.assertEqual(call.kwargs["full_score"], 130.0)
        self.assertEqual(call.kwargs["excellent_percent"], 88.0)
        self.assertEqual(call.kwargs["selected_classes"], ["2401", "2402"])

    def test_subject_analysis_does_not_rebuild_or_match_student_identity(self):
        source = Path("app.py").read_text(encoding="utf-8")
        subject_function = source.index("def render_subject_analysis_page(")
        subject_route = source.index(
            'if analysis_mode == "subject_analysis":', subject_function
        )
        function_block = source[subject_function:subject_route]

        self.assertNotIn("build_student_identity_records(", function_block)
        self.assertNotIn("reset_index(drop=True)", function_block)
        self.assertIn('snapshot.get("identity_records_by_index")', function_block)
        self.assertIn("valid_scores.index", function_block)

    def test_subject_analysis_shows_error_when_identity_snapshot_is_missing(self):
        source = Path("app.py").read_text(encoding="utf-8")
        subject_function = source.index("def render_subject_analysis_page(")
        subject_route = source.index(
            'if analysis_mode == "subject_analysis":', subject_function
        )
        function_block = source[subject_function:subject_route]

        self.assertIn('st.error("当前考试快照缺少学生身份映射', function_block)

    def test_class_analysis_uses_snapshot_and_stops_before_excel_workflow(self):
        source = Path("app.py").read_text(encoding="utf-8")
        class_function = source.find("def render_class_analysis_page(")
        self.assertNotEqual(class_function, -1, "缺少独立班级分析页面")
        class_route = source.index(
            'if analysis_mode == "class_comparison":', class_function
        )
        excel_workflow = source.index("uploaded_file = None", class_route)
        route_block = source[class_route:excel_workflow]

        self.assertIn('st.session_state.get("current_exam_snapshot")', route_block)
        self.assertIn("render_class_analysis_page(snapshot)", route_block)
        self.assertIn("st.stop()", route_block)
        for forbidden_call in (
            "restore_current_exam_file(",
            "pd.ExcelFile(",
            "pd.read_excel(",
            "detect_header_row(",
            "build_dataframe_from_header(",
        ):
            self.assertNotIn(forbidden_call, route_block)

    def test_class_analysis_uses_only_independent_control_state(self):
        source = Path("app.py").read_text(encoding="utf-8")
        class_function = source.find("def render_class_analysis_page(")
        self.assertNotEqual(class_function, -1, "缺少独立班级分析页面")
        class_route = source.index(
            'if analysis_mode == "class_comparison":', class_function
        )
        function_block = source[class_function:class_route]

        for state_key in (
            'key="class_analysis_score_column"',
            'key="class_analysis_full_score"',
            'key="class_analysis_excellent_percent"',
            'key="class_analysis_classes"',
        ):
            self.assertIn(state_key, function_block)
        for forbidden_state in (
            '"analysis_score_column"',
            '"analysis_excellent_percent"',
            '"full_score_by_context"',
            '"selected_class"',
            '"analysis_single_class"',
            '"analysis_sheet"',
            '"analysis_name_column"',
            '"analysis_class_column"',
        ):
            self.assertNotIn(forbidden_state, function_block)
        self.assertNotIn("reset_index(drop=True)", function_block)
        self.assertNotIn("build_student_identity_records(", function_block)

    def test_class_analysis_initialization_does_not_change_grade_state(self):
        initialize_state = load_app_function(
            "initialize_class_analysis_state",
            {
                "clean_column_name": clean_column_name,
                "get_full_score_suggestion": get_full_score_suggestion,
                "resolve_column_selection": resolve_column_selection,
            },
        )
        session_state = {
            "analysis_score_column": "语文",
            "analysis_excellent_percent": 85.0,
            "full_score_by_context": {"exam-sheet": {"语文": 120.0}},
            "selected_class": "2401",
        }
        watched = deepcopy(session_state)
        snapshot = {
            "score_options": ["语文", "数学"],
            "score_col": "数学",
            "full_score_by_column": {"数学": 120.0},
            "excellent_percent": 90.0,
        }

        initialize_state(session_state, snapshot)

        self.assertEqual(
            {key: session_state[key] for key in watched},
            watched,
        )
        self.assertEqual(session_state["class_analysis_score_column"], "数学")
        self.assertEqual(session_state["class_analysis_full_score"], 120.0)
        self.assertEqual(session_state["class_analysis_excellent_percent"], 90.0)

    def test_class_analysis_dataframe_preserves_original_index_and_duplicate_names(self):
        build_dataframe = load_app_function(
            "build_class_analysis_dataframe",
            {"pd": pd},
        )
        snapshot = {
            "name_col": "姓名",
            "class_col": "班级",
            "identity_records_by_index": {
                7: {"identity_key": ("class_name", "2401", "张三"), "姓名": "张三", "班级": "2401", "学号": ""},
                9: {"identity_key": ("class_name", "2402", "张三"), "姓名": "张三", "班级": "2402", "学号": ""},
                11: {"identity_key": ("student_id", "S001"), "姓名": "李四", "班级": "2401", "学号": "S001"},
                12: {"identity_key": ("student_id", "S002"), "姓名": "李四", "班级": "2401", "学号": "S002"},
            },
            "subject_scores_by_index": {
                7: {"数学": 91.0},
                9: {"数学": 87.0},
                11: {"数学": 83.0},
                12: {"数学": 79.0},
            },
        }

        dataframe = build_dataframe(snapshot, "数学")

        self.assertEqual(dataframe.index.tolist(), [7, 9, 11, 12])
        self.assertEqual(dataframe["姓名"].tolist(), ["张三", "张三", "李四", "李四"])
        self.assertEqual(dataframe["班级"].tolist(), ["2401", "2402", "2401", "2401"])
        self.assertEqual(dataframe["数学"].tolist(), [91.0, 87.0, 83.0, 79.0])

    def test_class_analysis_passes_snapshot_data_and_local_parameters_to_comparison(self):
        build_dataframe = load_app_function(
            "build_class_analysis_dataframe",
            {"pd": pd},
        )
        comparison_builder = MagicMock(return_value="comparison-result")
        build_comparison = load_app_function(
            "build_class_analysis_comparison",
            {
                "build_class_analysis_dataframe": build_dataframe,
                "build_class_comparison": comparison_builder,
            },
        )
        snapshot = {
            "name_col": "姓名",
            "class_col": "班级",
            "identity_records_by_index": {
                7: {"identity_key": ("class_name", "2401", "张三"), "姓名": "张三", "班级": "2401", "学号": ""},
                9: {"identity_key": ("class_name", "2402", "张三"), "姓名": "张三", "班级": "2402", "学号": ""},
            },
            "subject_scores_by_index": {
                7: {"数学": 91.0},
                9: {"数学": 87.0},
            },
        }

        dataframe, result = build_comparison(
            snapshot,
            score_col="数学",
            selected_classes=["2401", "2402"],
            full_score=120.0,
            excellent_percent=85.0,
        )

        self.assertEqual(result, "comparison-result")
        self.assertEqual(dataframe.index.tolist(), [7, 9])
        call = comparison_builder.call_args
        pd.testing.assert_frame_equal(call.args[0], dataframe)
        self.assertEqual(
            call.kwargs,
            {
                "class_column": "班级",
                "name_column": "姓名",
                "score_column": "数学",
                "selected_classes": ["2401", "2402"],
                "full_score": 120.0,
                "excellent_percent": 85.0,
            },
        )

    def test_class_analysis_shows_clear_error_without_snapshot(self):
        source = Path("app.py").read_text(encoding="utf-8")
        class_function = source.find("def render_class_analysis_page(")
        self.assertNotEqual(class_function, -1, "缺少独立班级分析页面")
        class_route = source.index(
            'if analysis_mode == "class_comparison":', class_function
        )
        route_block = source[class_route:source.index("uploaded_file = None", class_route)]

        self.assertIn("请先上传成绩表并完成年级总览，再进入班级分析。", route_block)

    def test_subject_score_binding_rejects_duplicate_name_identity_without_overwrite(self):
        bind_scores = load_app_function("bind_subject_scores_by_row_index")
        valid_scores = pd.DataFrame(
            {"分数": [91.0, 87.0]},
            index=[7, 9],
        )
        identities = {
            7: {"identity_key": ("name", "张三"), "姓名": "张三", "班级": "", "学号": "", "分数": 0.0},
            9: {"identity_key": ("name", "张三"), "姓名": "张三", "班级": "", "学号": "", "分数": 0.0},
        }

        with self.assertRaises(ValueError):
            bind_scores(valid_scores, identities)

    def test_subject_score_binding_keeps_same_name_students_across_classes(self):
        bind_scores = load_app_function("bind_subject_scores_by_row_index")
        valid_scores = pd.DataFrame(
            {"分数": [91.0, 87.0]},
            index=[7, 9],
        )
        identities = {
            7: {"identity_key": ("class_name", "2401", "张三"), "姓名": "张三", "班级": "2401", "学号": "", "分数": 0.0},
            9: {"identity_key": ("class_name", "2402", "张三"), "姓名": "张三", "班级": "2402", "学号": "", "分数": 0.0},
        }

        scores = bind_scores(valid_scores, identities)

        self.assertEqual(len(scores), 2)
        self.assertEqual(scores[("class_name", "2401", "张三")], 91.0)
        self.assertEqual(scores[("class_name", "2402", "张三")], 87.0)

    def test_subject_score_binding_keeps_same_name_students_by_student_id(self):
        bind_scores = load_app_function("bind_subject_scores_by_row_index")
        valid_scores = pd.DataFrame(
            {"分数": [91.0, 87.0]},
            index=[7, 9],
        )
        identities = {
            7: {"identity_key": ("student_id", "S001"), "姓名": "张三", "班级": "2401", "学号": "S001", "分数": 0.0},
            9: {"identity_key": ("student_id", "S002"), "姓名": "张三", "班级": "2401", "学号": "S002", "分数": 0.0},
        }

        scores = bind_scores(valid_scores, identities)

        self.assertEqual(len(scores), 2)
        self.assertEqual(scores[("student_id", "S001")], 91.0)
        self.assertEqual(scores[("student_id", "S002")], 87.0)

    def test_current_exam_snapshot_contains_subject_analysis_source_data(self):
        source = Path("app.py").read_text(encoding="utf-8")
        cache_start = source.index("cache_current_exam_snapshot(")
        cache_end = source.index('render_anchor("section-details")', cache_start)
        cache_block = source[cache_start:cache_end]

        for snapshot_key in (
            '"name_col"',
            '"class_col"',
            '"student_id_col"',
            '"score_options"',
            '"full_score_by_column"',
            '"identity_records_by_index"',
            '"subject_scores_by_index"',
        ):
            self.assertIn(snapshot_key, cache_block)
        self.assertNotIn('"dataframe": df.copy()', cache_block)

    def test_new_exam_cache_clears_previous_report_name(self):
        session_state = {
            "current_exam_file_bytes": b"old",
            "current_exam_file_name": "期中.xlsx",
            "word_report_exam_name": "期中考试",
            "current_exam_snapshot": {"analysis_result": {"student_count": 2}},
        }
        uploaded_file = BytesIO(b"new")
        uploaded_file.name = "期末.xlsx"

        ui_exam_center.cache_current_exam(session_state, uploaded_file)

        self.assertEqual(session_state["current_exam_file_bytes"], b"new")
        self.assertEqual(session_state["current_exam_file_name"], "期末.xlsx")
        self.assertNotIn("word_report_exam_name", session_state)
        self.assertNotIn("current_exam_snapshot", session_state)

    def test_same_exam_cache_keeps_current_exam_snapshot(self):
        snapshot = {"analysis_result": {"student_count": 2}}
        session_state = {
            "current_exam_file_bytes": b"same",
            "current_exam_file_name": "期中.xlsx",
            "current_exam_snapshot": snapshot,
        }
        uploaded_file = BytesIO(b"same")
        uploaded_file.name = "期中.xlsx"

        ui_exam_center.cache_current_exam(session_state, uploaded_file)

        self.assertIs(session_state["current_exam_snapshot"], snapshot)

    def test_current_exam_snapshot_preserves_analysis_parameters_across_report_navigation(self):
        cache_snapshot = getattr(ui_exam_center, "cache_current_exam_snapshot", None)
        self.assertTrue(callable(cache_snapshot), "缺少当前考试分析结果快照缓存")
        session_state = {
            "analysis_mode": "analysis_center",
            "analysis_score_column": "数学",
            "full_score_by_context": {"exam-sheet": {"数学": 120.0}},
            "full_score::exam-sheet::数学": 120.0,
            "analysis_excellent_percent": 85.0,
            "selected_class": "全部学生",
        }
        watched_keys = (
            "analysis_score_column",
            "full_score_by_context",
            "full_score::exam-sheet::数学",
            "analysis_excellent_percent",
            "selected_class",
        )
        original_parameters = {
            key: deepcopy(session_state[key]) for key in watched_keys
        }
        snapshot = {
            "analysis_result": {"student_count": 2},
            "score_col": "数学",
            "full_score": 120.0,
            "excellent_percent": 85.0,
            "selected_class": "全部学生",
        }

        cache_snapshot(session_state, snapshot)
        session_state["analysis_mode"] = "report_center"
        report_snapshot = session_state["current_exam_snapshot"]
        session_state["analysis_mode"] = "analysis_center"

        self.assertIs(report_snapshot, snapshot)
        self.assertEqual(
            {key: session_state[key] for key in watched_keys},
            original_parameters,
        )

    def test_report_center_stops_before_excel_and_single_class_workflow(self):
        source = Path("app.py").read_text(encoding="utf-8")
        report_start = source.index('if analysis_mode == "report_center":')
        next_route = source.index(
            'elif analysis_mode == "subject_analysis":', report_start
        )
        report_block = source[report_start:next_route]

        self.assertIn('st.session_state.get("current_exam_snapshot")', report_block)
        self.assertIn('st.session_state.get("current_exam_context")', report_block)
        self.assertIn('st.session_state.get("current_exam_config")', report_block)
        self.assertIn('st.session_state.get("current_page_state")', report_block)
        self.assertIn("report_page_state = replace(", report_block)
        self.assertIn("build_analysis_request(", report_block)
        self.assertIn("get_or_build_report_result(", report_block)
        self.assertIn("analysis_result_to_legacy_dict(", report_block)
        self.assertIn("build_score_report_bytes(", report_block)
        self.assertIn("st.stop()", report_block)
        self.assertIn("analysis_result=report_analysis_result", report_block)
        self.assertIn('fallback=snapshot["analysis_result"]', report_block)
        self.assertIn('score_col=snapshot["score_col"]', report_block)
        self.assertIn('full_score=snapshot["full_score"]', report_block)
        self.assertIn('selected_class=snapshot["selected_class"]', report_block)
        self.assertNotIn("current_page_state.page_name =", report_block)
        for protected_key in (
            "analysis_score_column",
            "analysis_excellent_percent",
            "selected_class",
        ):
            self.assertNotIn(
                f'st.session_state["{protected_key}"] =',
                report_block,
            )
        for forbidden_call in (
            "restore_current_exam_file(",
            "pd.read_excel(",
            "st.selectbox(",
            "st.number_input(",
            "analyze_scores(",
        ):
            self.assertNotIn(forbidden_call, report_block)

    def test_cached_exam_restores_upload_compatible_file(self):
        restored = ui_exam_center.restore_current_exam_file(
            {
                "current_exam_file_bytes": b"excel bytes",
                "current_exam_file_name": "考试.xlsx",
            }
        )

        self.assertEqual(restored.getvalue(), b"excel bytes")
        self.assertEqual(restored.name, "考试.xlsx")

    def test_analysis_center_activation_updates_session_state(self):
        session_state = {"analysis_mode": "single_class"}

        ui_exam_center.activate_analysis_center(session_state)

        self.assertEqual(session_state["analysis_mode"], "analysis_center")
        self.assertIs(session_state.get("analysis_center_scroll_pending"), True)

    def test_analysis_center_top_scrolls_smoothly_once_with_finite_retries(self):
        render_top = getattr(ui_exam_center, "render_analysis_center_top", None)
        self.assertIsNotNone(render_top, "缺少分析中心顶部定位组件")
        session_state = {"analysis_center_scroll_pending": True}
        streamlit = MagicMock()

        with (
            patch.object(ui_exam_center, "st", streamlit),
            patch.object(ui_exam_center, "_render_scroll_component") as render_script,
        ):
            render_top(session_state)
            render_top(session_state)

        anchor_html = streamlit.markdown.call_args_list[0].args[0]
        self.assertIn('id="analysis-top"', anchor_html)
        self.assertEqual(render_script.call_count, 1)
        script = render_script.call_args.args[0]
        self.assertIn("scrollIntoView", script)
        self.assertIn("behavior: 'smooth'", script)
        self.assertIn("maxAttempts", script)
        self.assertIn("attempts < maxAttempts", script)
        self.assertNotIn("setInterval", script)
        self.assertNotIn("analysis_center_scroll_pending", session_state)

    def test_analysis_center_renders_top_target_before_center_content(self):
        source = Path("app.py").read_text(encoding="utf-8")
        center_block_start = source.index('if analysis_mode == "analysis_center":')
        center_render = source.index("render_exam_analysis_center(", center_block_start)
        self.assertIn("render_analysis_center_top(", source[center_block_start:center_render])
        top_render = source.index("render_analysis_center_top(", center_block_start)

        self.assertLess(top_render, center_render)

    def test_exam_cache_is_committed_only_after_successful_analysis(self):
        source = Path("app.py").read_text(encoding="utf-8")
        analysis_position = source.index("identity_analysis_result = analyze_scores")
        cache_position = source.index("cache_current_exam(st.session_state, uploaded_file)")
        activate_position = source.index("activate_analysis_center(st.session_state)")

        self.assertLess(analysis_position, cache_position)
        self.assertLess(cache_position, activate_position)

    def test_exam_context_is_saved_after_field_confirmation_before_first_rerun(self):
        source = Path("app.py").read_text(encoding="utf-8")
        score_options_position = source.index("score_options = build_score_column_options(")
        early_context_position = source.index(
            "ensure_current_exam_context(",
            score_options_position,
        )
        analysis_position = source.index("identity_analysis_result = analyze_scores")
        rerun_position = source.index("st.rerun()", analysis_position)
        snapshot_position = source.index("cache_current_exam_snapshot(")

        self.assertLess(score_options_position, early_context_position)
        self.assertLess(early_context_position, analysis_position)
        self.assertLess(analysis_position, rerun_position)
        self.assertLess(rerun_position, snapshot_position)

    def test_grade_overview_field_mapping_restores_from_exam_context_first(self):
        source = Path("app.py").read_text(encoding="utf-8")

        self.assertIn("def resolve_grade_overview_field_columns(", source)
        self.assertIn("def mark_grade_overview_field_mapping_changed(", source)
        self.assertIn(
            'st.error("姓名列和班级列不能相同。")',
            source,
        )
        self.assertIn(
            'st.session_state["grade_overview_field_mapping_changed"] = False',
            source,
        )

        resolve_fields = load_app_function(
            "resolve_grade_overview_field_columns",
            {"ExamContext": ExamContext},
        )
        context = ExamContext(
            exam_id="exam-1",
            metadata=ExamMetadata(
                file_name="期中.xlsx",
                file_fingerprint="fingerprint-1",
                sheet_name="成绩表",
            ),
            schema=ExamSchema(
                name_column="姓名",
                class_column="班级",
                score_columns=("数学",),
            ),
        )
        original_context = deepcopy(context)

        name_column, class_column = resolve_fields(
            ["班级", "姓名", "数学"],
            context,
            file_fingerprint="fingerprint-1",
            sheet_name="成绩表",
            widget_name_column="班级",
            widget_class_column="班级",
            matched_name_column="姓名",
            matched_class_column="班级",
            widget_mapping_changed=False,
        )

        self.assertEqual((name_column, class_column), ("姓名", "班级"))
        self.assertEqual(context, original_context)
        prepared_scores = pd.DataFrame(
            {
                "姓名": ["张三", "李四"],
                "班级": ["2401", "2401"],
                "分数": [90.0, 80.0],
            }
        )
        identities = build_student_identity_records(
            prepared_scores,
            class_column=class_column,
        )
        self.assertEqual(len(build_student_score_mapping(identities)), 2)

    def test_user_field_change_can_rebuild_exam_context_schema(self):
        resolve_fields = load_app_function(
            "resolve_grade_overview_field_columns",
            {"ExamContext": ExamContext},
        )
        context = ExamContext(
            exam_id="exam-1",
            metadata=ExamMetadata(
                file_name="期中.xlsx",
                file_fingerprint="fingerprint-1",
                sheet_name="成绩表",
            ),
            schema=ExamSchema(
                name_column="姓名",
                class_column="班级",
                score_columns=("数学",),
            ),
        )

        name_column, class_column = resolve_fields(
            ["班级", "姓名", "学生姓名", "数学"],
            context,
            file_fingerprint="fingerprint-1",
            sheet_name="成绩表",
            widget_name_column="学生姓名",
            widget_class_column="班级",
            matched_name_column="姓名",
            matched_class_column="班级",
            widget_mapping_changed=True,
        )

        self.assertEqual((name_column, class_column), ("学生姓名", "班级"))

    def test_confirmed_field_change_updates_current_exam_context_schema(self):
        ensure_context = load_app_function(
            "ensure_current_exam_context",
            {
                "sha256": sha256,
                "ExamContext": ExamContext,
                "ExamImportDraft": ExamImportDraft,
                "ExamImportError": ExamImportError,
            },
        )
        file_content = b"same exam with confirmed field change"
        fingerprint = sha256(file_content).hexdigest()
        old_context = ExamContext(
            exam_id="exam-old-mapping",
            metadata=ExamMetadata(
                file_name="期中.xlsx",
                file_fingerprint=fingerprint,
                sheet_name="成绩表",
            ),
            schema=ExamSchema(
                name_column="姓名",
                class_column="班级",
                score_columns=("数学",),
            ),
        )
        updated_context = ExamContext(
            exam_id="exam-updated-mapping",
            metadata=old_context.metadata,
            schema=ExamSchema(
                name_column="学生姓名",
                class_column="班级",
                score_columns=("数学",),
            ),
        )
        session_state = {"current_exam_context": old_context}
        service = MagicMock()
        service.build_context.return_value = updated_context

        result = ensure_context(
            session_state,
            service=service,
            file_content=file_content,
            file_name="期中.xlsx",
            sheet_names=("成绩表",),
            sheet_name="成绩表",
            detected_header_row=0,
            header_row_index=0,
            dataframe=pd.DataFrame(
                {
                    "班级": ["2401"],
                    "姓名": ["旧姓名"],
                    "学生姓名": ["张三"],
                    "数学": [90],
                }
            ),
            column_mapping=ExamColumnMapping(
                name_column="学生姓名",
                class_column="班级",
                student_id_column=None,
                score_columns=("数学",),
            ),
            exam_name="期中",
        )

        self.assertIs(result, updated_context)
        self.assertIs(session_state["current_exam_context"], updated_context)
        self.assertEqual(
            session_state["current_exam_context"].schema.name_column,
            "学生姓名",
        )
        service.build_context.assert_called_once()

    def test_matching_exam_context_is_reused_without_rebuild(self):
        ensure_context = load_app_function(
            "ensure_current_exam_context",
            {
                "sha256": sha256,
                "ExamContext": ExamContext,
                "ExamImportDraft": ExamImportDraft,
                "ExamImportError": ExamImportError,
            },
        )
        file_content = b"stable workbook bytes"
        context = ExamContext(
            exam_id="exam-existing",
            metadata=ExamMetadata(
                file_name="期中考试.xlsx",
                file_fingerprint=sha256(file_content).hexdigest(),
                sheet_name="成绩表",
            ),
            schema=ExamSchema(
                name_column="姓名",
                class_column="班级",
                student_id_column="学号",
                score_columns=("数学", "英语"),
            ),
        )
        session_state = {"current_exam_context": context}
        service = MagicMock()
        mapping = ExamColumnMapping(
            name_column="姓名",
            class_column="班级",
            student_id_column="学号",
            score_columns=("数学", "英语"),
        )

        result = ensure_context(
            session_state,
            service=service,
            file_content=file_content,
            file_name="期中考试.xlsx",
            sheet_names=("成绩表",),
            sheet_name="成绩表",
            detected_header_row=1,
            header_row_index=1,
            dataframe=pd.DataFrame({"姓名": ["张三"]}),
            column_mapping=mapping,
            exam_name="期中考试",
        )

        self.assertIs(result, context)
        service.build_context.assert_not_called()

    def test_new_exam_context_is_built_and_saved_once(self):
        ensure_context = load_app_function(
            "ensure_current_exam_context",
            {
                "sha256": sha256,
                "ExamContext": ExamContext,
                "ExamImportDraft": ExamImportDraft,
                "ExamImportError": ExamImportError,
            },
        )
        file_content = b"new workbook bytes"
        mapping = ExamColumnMapping(
            name_column="姓名",
            class_column="班级",
            student_id_column=None,
            score_columns=("数学",),
        )
        context = ExamContext(
            exam_id="exam-new",
            metadata=ExamMetadata(
                file_name="新考试.xlsx",
                file_fingerprint=sha256(file_content).hexdigest(),
                sheet_name="成绩表",
            ),
            schema=ExamSchema(
                name_column="姓名",
                class_column="班级",
                score_columns=("数学",),
            ),
        )
        service = MagicMock()
        service.build_context.return_value = context
        session_state = {}

        result = ensure_context(
            session_state,
            service=service,
            file_content=file_content,
            file_name="新考试.xlsx",
            sheet_names=("成绩表",),
            sheet_name="成绩表",
            detected_header_row=0,
            header_row_index=0,
            dataframe=pd.DataFrame({"姓名": ["张三"], "班级": ["2401"], "数学": [90]}),
            column_mapping=mapping,
            exam_name="新考试",
        )

        self.assertIs(result, context)
        self.assertIs(session_state["current_exam_context"], context)
        service.build_context.assert_called_once()

    def test_early_context_failure_preserves_cause_for_page_layer(self):
        ensure_context = load_app_function(
            "ensure_current_exam_context",
            {
                "sha256": sha256,
                "ExamContext": ExamContext,
                "ExamImportDraft": ExamImportDraft,
                "ExamImportError": ExamImportError,
            },
        )
        service = MagicMock()
        original_error = ExamImportError("导入失败")
        service.build_context.side_effect = original_error
        session_state = {}
        mapping = ExamColumnMapping(
            name_column="姓名",
            class_column=None,
            student_id_column=None,
            score_columns=("数学",),
        )

        with self.assertRaises(ExamImportError) as raised:
            ensure_context(
                session_state,
                service=service,
                file_content=b"broken for early builder only",
                file_name="考试.xlsx",
                sheet_names=("成绩表",),
                sheet_name="成绩表",
                detected_header_row=0,
                header_row_index=0,
                dataframe=pd.DataFrame({"姓名": ["张三"], "数学": [90]}),
                column_mapping=mapping,
                exam_name="考试",
            )

        self.assertIn("导入失败", str(raised.exception))
        self.assertIs(raised.exception.__cause__, original_error)
        self.assertNotIn("current_exam_context", session_state)

    def test_early_context_generation_does_not_change_snapshot_payload(self):
        source = Path("app.py").read_text(encoding="utf-8")
        snapshot_position = source.index("cache_current_exam_snapshot(")
        snapshot_end = source.index(
            "if current_exam_context is None:",
            snapshot_position,
        )
        snapshot_block = source[snapshot_position:snapshot_end]

        for expected_field in (
            '"analysis_result"',
            '"distribution"',
            '"selected_class"',
            '"score_col"',
            '"full_score"',
            '"excellent_percent"',
            '"identity_records_by_index"',
            '"subject_scores_by_index"',
            '"full_score_by_column"',
        ):
            self.assertIn(expected_field, snapshot_block)
        self.assertNotIn("ExamImportDraft", snapshot_block)
        self.assertNotIn("current_exam_context", snapshot_block)

    def test_exam_config_is_saved_after_context_as_parallel_state(self):
        source = Path("app.py").read_text(encoding="utf-8")
        snapshot_position = source.index("cache_current_exam_snapshot(")
        context_save_position = source.index(
            'st.session_state["current_exam_context"]',
            snapshot_position,
        )
        config_build_position = source.index(
            "build_exam_config(",
            context_save_position,
        )
        config_save_position = source.index(
            'st.session_state["current_exam_config"]',
            config_build_position,
        )
        detail_position = source.index(
            'render_anchor("section-details")',
            config_save_position,
        )

        self.assertLess(snapshot_position, context_save_position)
        self.assertLess(context_save_position, config_build_position)
        self.assertLess(config_build_position, config_save_position)
        self.assertLess(config_save_position, detail_position)
        config_block = source[context_save_position:detail_position]
        self.assertIn("except (TypeError, ValueError):", config_block)
        self.assertIn("st.session_state.get(", config_block)
        self.assertIn('"current_exam_config"', config_block)

    def test_pages_read_but_do_not_write_current_exam_config(self):
        source = Path("app.py").read_text(encoding="utf-8")
        for function_name, end_marker in (
            ("def render_structured_subject_analysis_page(", "def render_class_analysis_page("),
            ("def render_structured_class_analysis_page(", 'if analysis_mode == "subject_analysis":'),
        ):
            start = source.index(function_name)
            end = source.index(end_marker, start)
            page_block = source[start:end]
            self.assertIn("exam_config", page_block)
            self.assertNotIn(
                'st.session_state["current_exam_config"] =',
                page_block,
            )

    def test_page_state_is_saved_after_config_as_parallel_state(self):
        source = Path("app.py").read_text(encoding="utf-8")
        snapshot_position = source.index("cache_current_exam_snapshot(")
        context_save_position = source.index(
            'st.session_state["current_exam_context"]',
            snapshot_position,
        )
        config_save_position = source.index(
            'st.session_state["current_exam_config"]',
            context_save_position,
        )
        page_state_build_position = source.index(
            "PageState(",
            config_save_position,
        )
        page_state_save_position = source.index(
            'st.session_state["current_page_state"]',
            page_state_build_position,
        )
        detail_position = source.index(
            'render_anchor("section-details")',
            page_state_save_position,
        )

        self.assertLess(snapshot_position, context_save_position)
        self.assertLess(context_save_position, config_save_position)
        self.assertLess(config_save_position, page_state_build_position)
        self.assertLess(page_state_build_position, page_state_save_position)
        self.assertLess(page_state_save_position, detail_position)
        page_state_block = source[page_state_build_position:page_state_save_position]
        self.assertIn('page_name="grade_overview"', page_state_block)
        self.assertIn("exam_id=current_exam_context.exam_id", page_state_block)

    def test_subject_analysis_uses_page_state_and_effective_config(self):
        source = Path("app.py").read_text(encoding="utf-8")
        structured_start = source.index(
            "def render_structured_subject_analysis_page("
        )
        structured_end = source.index(
            "def render_class_analysis_page(", structured_start
        )
        structured_block = source[structured_start:structured_end]

        self.assertGreaterEqual(
            structured_block.count("resolve_namespaced_subject_config("),
            2,
        )
        self.assertIn("get_or_build_subject_result(", structured_block)
        self.assertIn('st.session_state["current_page_state"]', structured_block)
        self.assertIn("apply_page_config_widget_event", structured_block)
        self.assertIn("final_subject_config", structured_block)
        for forbidden_state in (
            'st.session_state["analysis_score_column"]',
            'st.session_state["analysis_excellent_percent"]',
            'st.session_state["full_score_by_context"]',
            'st.session_state["selected_class"]',
            'st.session_state["analysis_single_class"]',
            'st.session_state["current_exam_config"]',
        ):
            self.assertNotIn(forbidden_state, structured_block)

    def test_structured_subject_calculation_reads_exam_context_data(self):
        source = Path("app.py").read_text(encoding="utf-8")
        calculation_start = source.index(
            "def calculate_subject_analysis_payload("
        )
        calculation_end = source.index(
            "def render_structured_subject_result(", calculation_start
        )
        calculation_block = source[calculation_start:calculation_end]

        self.assertIn(
            "exam_context.identity_records_by_index", calculation_block
        )
        self.assertIn(
            "exam_context.subject_scores_by_index", calculation_block
        )
        self.assertIn("exam_context.schema.name_column", calculation_block)
        self.assertNotIn(
            'snapshot.get("identity_records_by_index")', calculation_block
        )
        self.assertNotIn(
            'snapshot.get("subject_scores_by_index")', calculation_block
        )

    def test_report_subject_and_class_pages_use_new_result_services(self):
        source = Path("app.py").read_text(encoding="utf-8")
        report_start = source.index('if analysis_mode == "report_center":')
        subject_route = source.index(
            'elif analysis_mode == "subject_analysis":',
            report_start,
        )
        report_block = source[report_start:subject_route]
        subject_function = source.index(
            "def render_structured_subject_analysis_page("
        )
        class_function = source.index(
            "def render_class_analysis_page(", subject_function
        )
        subject_block = source[subject_function:class_function]
        class_function = source.index(
            "def render_structured_class_analysis_page("
        )
        class_route = source.index(
            'if analysis_mode == "class_comparison":', class_function
        )
        class_block = source[class_function:class_route]
        excel_workflow = source.index("uploaded_file = None", class_route)
        grade_block = source[excel_workflow:]

        self.assertIn("build_analysis_request(", report_block)
        self.assertIn("get_or_build_report_result(", report_block)
        self.assertIn("get_or_build_subject_result(", subject_block)
        self.assertIn("get_or_build_class_result(", class_block)
        self.assertNotIn("get_or_build_subject_result(", report_block)
        self.assertNotIn("get_or_build_report_result(", subject_block)
        self.assertNotIn("get_or_build_class_result(", report_block)
        self.assertNotIn("get_or_build_class_result(", subject_block)
        self.assertNotIn("build_analysis_request(", grade_block)
        self.assertNotIn("get_or_build_class_result(", grade_block)
        self.assertNotIn("current_analysis_request", source)

    def test_subject_route_prefers_new_architecture_and_keeps_legacy_fallback(self):
        source = Path("app.py").read_text(encoding="utf-8")
        class_function = source.index("def render_class_analysis_page(")
        subject_route = source.index(
            'if analysis_mode == "subject_analysis":', class_function
        )
        class_route = source.index(
            'if analysis_mode == "class_comparison":', subject_route
        )
        route_block = source[subject_route:class_route]

        self.assertIn('st.session_state.get("current_exam_context")', route_block)
        self.assertIn('st.session_state.get("current_exam_config")', route_block)
        self.assertIn('st.session_state.get("current_page_state")', route_block)
        self.assertIn('st.session_state.get("result_store")', route_block)
        self.assertIn("render_structured_subject_analysis_page(", route_block)
        self.assertIn("render_subject_analysis_page(snapshot)", route_block)
        self.assertIn("st.stop()", route_block)

    def test_structured_class_analysis_uses_page_state_without_old_business_state(self):
        source = Path("app.py").read_text(encoding="utf-8")
        structured_start = source.index(
            "def render_structured_class_analysis_page("
        )
        structured_end = source.index(
            'if analysis_mode == "subject_analysis":', structured_start
        )
        structured_block = source[structured_start:structured_end]

        self.assertGreaterEqual(
            structured_block.count("resolve_namespaced_subject_config("),
            2,
        )
        self.assertIn("get_or_build_class_result(", structured_block)
        self.assertIn('st.session_state["current_page_state"]', structured_block)
        self.assertIn("apply_page_config_widget_event", structured_block)
        self.assertIn("final_class_config", structured_block)
        for forbidden_state in (
            'st.session_state["class_analysis_full_score"]',
            'st.session_state["class_analysis_excellent_percent"]',
            'st.session_state["analysis_score_column"]',
            'st.session_state["analysis_single_class"]',
            'st.session_state["selected_class"]',
            'st.session_state["full_score_by_context"]',
            'st.session_state["current_exam_config"]',
        ):
            self.assertNotIn(forbidden_state, structured_block)

    def test_class_page_override_namespace_is_not_visible_to_subject_page(self):
        read_namespaced = load_app_function(
            "read_namespaced_page_overrides",
            {"PageState": PageState, "deepcopy": deepcopy},
        )
        read_overrides = load_app_function(
            "read_class_analysis_overrides",
            {
                "CLASS_ANALYSIS_OVERRIDE_NAMESPACE": "__class_analysis__",
                "read_namespaced_page_overrides": read_namespaced,
            },
        )
        stored_page_state = PageState(
            exam_id="exam-1",
            page_name="class_comparison",
            selected_subject="数学",
            config_overrides={
                "__class_analysis__": {
                    "数学": {
                        "full_score": 130.0,
                        "excellent_percent": 88.0,
                    }
                }
            },
        )
        exam_config = ExamConfig(
            exam_id="exam-1",
            subjects={
                "数学": SubjectConfig(
                    full_score=120.0,
                    excellent_percent=90.0,
                )
            },
        )

        class_overrides = read_overrides(stored_page_state, "exam-1")
        subject_config = effective_config(
            exam_config,
            stored_page_state,
            "数学",
            SubjectConfig(full_score=100.0, excellent_percent=90.0),
        )

        self.assertEqual(class_overrides["数学"]["full_score"], 130.0)
        self.assertEqual(class_overrides["数学"]["excellent_percent"], 88.0)
        self.assertEqual(subject_config.full_score, 120.0)
        self.assertEqual(subject_config.excellent_percent, 90.0)

    def test_structured_class_calculation_reads_exam_context_by_original_index(self):
        source = Path("app.py").read_text(encoding="utf-8")
        calculation_start = source.index(
            "def calculate_class_analysis_payload("
        )
        calculation_end = source.index(
            "def render_structured_class_analysis_page(", calculation_start
        )
        calculation_block = source[calculation_start:calculation_end]

        self.assertIn(
            "exam_context.identity_records_by_index", calculation_block
        )
        self.assertIn(
            "exam_context.subject_scores_by_index", calculation_block
        )
        self.assertIn("pd.DataFrame(row_records, index=row_indexes)", calculation_block)
        self.assertNotIn("reset_index(drop=True)", calculation_block)
        self.assertNotIn("build_student_identity_records(", calculation_block)

    def test_class_route_prefers_new_architecture_and_keeps_legacy_fallback(self):
        source = Path("app.py").read_text(encoding="utf-8")
        class_function = source.index("def render_class_analysis_page(")
        class_route = source.index(
            'if analysis_mode == "class_comparison":', class_function
        )
        excel_workflow = source.index("uploaded_file = None", class_route)
        route_block = source[class_route:excel_workflow]

        self.assertIn('st.session_state.get("current_exam_context")', route_block)
        self.assertIn('st.session_state.get("current_exam_config")', route_block)
        self.assertIn('st.session_state.get("current_page_state")', route_block)
        self.assertIn('st.session_state.get("result_store")', route_block)
        self.assertIn("render_structured_class_analysis_page(", route_block)
        self.assertIn("render_class_analysis_page(snapshot)", route_block)
        self.assertIn("st.stop()", route_block)

    def test_grade_overview_context_source_ignores_invalid_excel_rows(self):
        legacy_dataframe = pd.DataFrame(
            {"姓名": ["张三", "", None, "李四"]},
            index=[0, 1, 2, 3],
        )
        context_dataframe = pd.DataFrame(
            {"姓名": ["张三", "李四"]},
            index=[0, 3],
        )
        context = MagicMock()
        context.schema.name_column = "姓名"
        build_context_dataframe = MagicMock(return_value=context_dataframe)
        resolver = load_app_function(
            "resolve_grade_overview_fact_source",
            {
                "build_grade_overview_dataframe": build_context_dataframe,
                "GradeOverviewContextError": ValueError,
            },
        )

        resolved_dataframe, resolved_context = resolver(
            legacy_dataframe,
            context,
        )

        self.assertIs(resolved_dataframe, context_dataframe)
        self.assertIs(resolved_context, context)

    def test_grade_overview_context_path_never_calls_legacy_identity_builder(self):
        context = object()
        valid_scores = pd.DataFrame({"分数": [118.0]}, index=[7])
        context_builder = MagicMock(return_value=[{"identity_key": ("id", "7")}])
        legacy_builder = MagicMock(side_effect=AssertionError("禁止重建身份"))
        prepare_records = load_app_function(
            "prepare_grade_overview_identity_records",
            {
                "build_grade_overview_identity_records": context_builder,
                "build_student_identity_records": legacy_builder,
            },
        )

        records = prepare_records(
            context,
            valid_scores,
            score_col="数学",
            class_col="班级",
            student_id_col="学号",
        )

        self.assertEqual(records, [{"identity_key": ("id", "7")}])
        context_builder.assert_called_once_with(context, "数学", valid_scores.index)
        legacy_builder.assert_not_called()

    def test_grade_overview_uses_one_fact_source_and_keeps_snapshot_shape(self):
        source = Path("app.py").read_text(encoding="utf-8")
        excel_workflow = source.index("uploaded_file = None")
        grade_block = source[excel_workflow:]
        identity_start = grade_block.index(
            "identity_records = prepare_grade_overview_identity_records("
        )
        analysis_start = grade_block.index("identity_analysis_result = analyze_scores(")
        identity_block = grade_block[identity_start:analysis_start]
        snapshot_start = grade_block.index("cache_current_exam_snapshot(")
        snapshot_end = grade_block.index(
            'st.session_state["current_exam_context"]', snapshot_start
        )
        snapshot_block = grade_block[snapshot_start:snapshot_end]

        self.assertIn("resolve_grade_overview_fact_source(", grade_block)
        self.assertIn("grade_overview_dataframe", grade_block)
        self.assertNotIn("build_student_identity_records(", identity_block)
        for snapshot_key in (
            '"analysis_result"',
            '"excellent_df"',
            '"fail_df"',
            '"distribution"',
            '"distribution_figure"',
            '"level_figure"',
            '"subject_average_figure"',
            '"selected_class"',
            '"score_col"',
            '"full_score"',
            '"excellent_percent"',
            '"report_name"',
            '"score_context_key"',
            '"name_col"',
            '"class_col"',
            '"student_id_col"',
            '"score_options"',
            '"identity_records_by_index"',
            '"subject_scores_by_index"',
            '"full_score_by_column"',
        ):
            self.assertIn(snapshot_key, snapshot_block)

    def _load_grade_rule_helpers(self):
        read_namespaced = load_app_function(
            "read_namespaced_page_overrides",
            {"PageState": PageState, "deepcopy": deepcopy},
        )
        read_overrides = load_app_function(
            "read_grade_overview_overrides",
            {
                "GRADE_OVERVIEW_OVERRIDE_NAMESPACE": "__grade_overview__",
                "read_namespaced_page_overrides": read_namespaced,
            },
        )
        resolve_namespaced = load_app_function(
            "resolve_namespaced_subject_config",
            {
                "PageState": PageState,
                "SubjectConfig": SubjectConfig,
                "deepcopy": deepcopy,
                "replace": __import__("dataclasses").replace,
                "effective_config": effective_config,
                "read_namespaced_page_overrides": read_namespaced,
            },
        )
        resolve_rules = load_app_function(
            "resolve_grade_overview_rule_source",
            {
                "GRADE_OVERVIEW_OVERRIDE_NAMESPACE": "__grade_overview__",
                "PageState": PageState,
                "read_grade_overview_overrides": read_overrides,
                "resolve_namespaced_subject_config": resolve_namespaced,
            },
        )
        return read_overrides, resolve_rules

    def test_grade_overview_reads_exam_config_without_override(self):
        _, resolve_rules = self._load_grade_rule_helpers()
        context = MagicMock(exam_id="exam-1")
        exam_config = ExamConfig(
            exam_id="exam-1",
            subjects={
                "数学": SubjectConfig(
                    full_score=120.0,
                    pass_percent=60.0,
                    excellent_percent=90.0,
                )
            },
        )
        page_state = PageState(exam_id="exam-1", page_name="grade_overview")

        rule_source = resolve_rules(
            context,
            exam_config,
            page_state,
            "数学",
            "全部学生",
            SubjectConfig(full_score=100.0, pass_percent=60.0, excellent_percent=90.0),
        )

        _, resolved, _, overrides, _ = rule_source
        self.assertEqual(resolved.full_score, 120.0)
        self.assertEqual(resolved.pass_percent, 60.0)
        self.assertEqual(resolved.excellent_percent, 90.0)
        self.assertEqual(overrides, {})

    def test_first_grade_overview_edit_survives_bootstrap_and_class_switch(self):
        ensure_config_state = load_app_function(
            "ensure_grade_overview_config_state",
            {
                "PageState": PageState,
                "build_exam_config": None,
                "deepcopy": deepcopy,
                "replace": __import__("dataclasses").replace,
            },
        )
        resolve_config, apply_event, sync_widgets = (
            self._load_unified_page_config_helpers()
        )
        exam_context = MagicMock(exam_id="exam-1")
        exam_config = ExamConfig(
            exam_id="exam-1",
            subjects={
                "数学": SubjectConfig(
                    full_score=120.0,
                    pass_percent=60.0,
                    excellent_percent=90.0,
                )
            },
        )
        build_calls = []

        def build_config(**kwargs):
            build_calls.append(kwargs)
            return exam_config

        session_state = {}
        current_config, current_page_state = ensure_config_state(
            session_state,
            exam_context,
            snapshot={},
            full_score_by_subject={},
            excellent_percent_by_subject={},
            selected_subject="数学",
            selected_class="全部学生",
            config_builder=build_config,
        )
        base_config, initial_config, _, _ = resolve_config(
            current_config,
            current_page_state,
            namespace="__grade_overview__",
            page_name="grade_overview",
            subject="数学",
            selected_classes=(),
            system_default=SubjectConfig(
                full_score=100.0,
                pass_percent=60.0,
                excellent_percent=90.0,
            ),
        )
        sync_widgets(
            session_state,
            initial_config,
            full_score_key="grade-full",
            excellent_percent_key="grade-excellent",
        )
        session_state["grade-full"] = 150.0
        session_state["grade-excellent"] = 80.0
        self.assertTrue(
            apply_event(
                session_state,
                namespace="__grade_overview__",
                page_name="grade_overview",
                exam_id="exam-1",
                subject="数学",
                selected_classes=(),
                full_score_key="grade-full",
                excellent_percent_key="grade-excellent",
                base_config=base_config,
            )
        )

        _, class_page_state = ensure_config_state(
            session_state,
            exam_context,
            snapshot={},
            full_score_by_subject={},
            excellent_percent_by_subject={},
            selected_subject="数学",
            selected_class="2401",
            config_builder=build_config,
        )
        final_config = resolve_config(
            current_config,
            class_page_state,
            namespace="__grade_overview__",
            page_name="grade_overview",
            subject="数学",
            selected_classes=("2401",),
            system_default=SubjectConfig(
                full_score=100.0,
                pass_percent=60.0,
                excellent_percent=90.0,
            ),
        )[1]
        result = analyze_scores(
            {"学生A": 125.0},
            full_score=final_config.full_score,
            excellent_percent=final_config.excellent_percent,
        )

        self.assertEqual(len(build_calls), 1)
        self.assertEqual(final_config.full_score, 150.0)
        self.assertEqual(final_config.excellent_percent, 80.0)
        self.assertEqual(
            session_state["current_page_state"].config_overrides[
                "__grade_overview__"
            ]["数学"],
            {"full_score": 150.0, "excellent_percent": 80.0},
        )
        self.assertEqual(result["full_score"], 150.0)
        self.assertEqual(result["excellent_percent"], 80.0)
        self.assertIs(session_state["current_exam_config"], exam_config)

    def test_real_xlsx_builds_context_before_grade_config_and_keeps_user_rules(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "成绩表"
        worksheet.append(["2026年期中考试"])
        worksheet.append(["姓名", "班级", "数学"])
        worksheet.append(["张三", "2401", 118])
        worksheet.append([None, "说明", None])
        worksheet.append(["李四", "2402", 109])
        output = BytesIO()
        workbook.save(output)
        file_content = output.getvalue()

        service = ExamImportService()
        draft = service.prepare_sheet(
            file_content,
            "期中考试.xlsx",
            "成绩表",
            None,
        )
        exam_context = service.build_context(
            draft,
            draft.suggested_mapping,
            exam_name="2026年期中考试",
        )
        resolve_fact_source = load_app_function(
            "resolve_grade_overview_fact_source",
            {
                "GradeOverviewContextError": ValueError,
                "build_grade_overview_dataframe": build_grade_overview_dataframe,
            },
        )
        grade_dataframe, grade_context = resolve_fact_source(
            draft.dataframe,
            exam_context,
        )

        self.assertIs(grade_context, exam_context)
        self.assertEqual(list(grade_dataframe.index), [0, 2])

        ensure_config_state = load_app_function(
            "ensure_grade_overview_config_state",
            {
                "PageState": PageState,
                "build_exam_config": build_exam_config,
                "deepcopy": deepcopy,
                "replace": __import__("dataclasses").replace,
            },
        )
        resolve_config, apply_event, sync_widgets = (
            self._load_unified_page_config_helpers()
        )
        session_state = {"current_exam_context": exam_context}
        exam_config, page_state = ensure_config_state(
            session_state,
            exam_context,
            snapshot={},
            full_score_by_subject={},
            excellent_percent_by_subject={},
            selected_subject="数学",
            selected_class="全部学生",
        )
        system_default = SubjectConfig(
            full_score=100.0,
            pass_percent=60.0,
            excellent_percent=90.0,
        )
        base_config, initial_config, _, _ = resolve_config(
            exam_config,
            page_state,
            namespace="__grade_overview__",
            page_name="grade_overview",
            subject="数学",
            selected_classes=(),
            system_default=system_default,
        )
        sync_widgets(
            session_state,
            initial_config,
            full_score_key="grade-full",
            excellent_percent_key="grade-excellent",
        )
        session_state["grade-full"] = 150.0
        session_state["grade-excellent"] = 80.0
        self.assertTrue(
            apply_event(
                session_state,
                namespace="__grade_overview__",
                page_name="grade_overview",
                exam_id=exam_context.exam_id,
                subject="数学",
                selected_classes=(),
                full_score_key="grade-full",
                excellent_percent_key="grade-excellent",
                base_config=base_config,
            )
        )

        for selected_class in ("2401", "全部学生"):
            exam_config, page_state = ensure_config_state(
                session_state,
                exam_context,
                snapshot={},
                full_score_by_subject={},
                excellent_percent_by_subject={},
                selected_subject="数学",
                selected_class=selected_class,
            )
        final_config = resolve_config(
            exam_config,
            page_state,
            namespace="__grade_overview__",
            page_name="grade_overview",
            subject="数学",
            selected_classes=(),
            system_default=system_default,
        )[1]
        result = analyze_scores(
            {"张三": 118.0, "李四": 109.0},
            full_score=final_config.full_score,
            excellent_percent=final_config.excellent_percent,
        )

        self.assertIs(session_state["current_exam_context"], exam_context)
        self.assertIs(session_state["current_exam_config"], exam_config)
        self.assertIsInstance(session_state["current_page_state"], PageState)
        self.assertEqual(final_config.full_score, 150.0)
        self.assertEqual(final_config.excellent_percent, 80.0)
        self.assertEqual(result["full_score"], 150.0)
        self.assertEqual(result["excellent_percent"], 80.0)

    def test_grade_overview_override_falls_back_field_by_field(self):
        _, resolve_rules = self._load_grade_rule_helpers()
        context = MagicMock(exam_id="exam-1")
        exam_config = ExamConfig(
            exam_id="exam-1",
            subjects={
                "数学": SubjectConfig(
                    full_score=120.0,
                    pass_percent=60.0,
                    excellent_percent=90.0,
                )
            },
        )
        page_state = PageState(
            exam_id="exam-1",
            page_name="grade_overview",
            selected_subject="数学",
            config_overrides={
                "__grade_overview__": {"数学": {"excellent_percent": 85.0}}
            },
        )

        _, resolved, _, _, _ = resolve_rules(
            context,
            exam_config,
            page_state,
            "数学",
            "全部学生",
            SubjectConfig(full_score=100.0, pass_percent=60.0, excellent_percent=90.0),
        )

        self.assertEqual(resolved.full_score, 120.0)
        self.assertEqual(resolved.pass_percent, 60.0)
        self.assertEqual(resolved.excellent_percent, 85.0)

    def test_grade_overview_subject_overrides_are_isolated(self):
        _, resolve_rules = self._load_grade_rule_helpers()
        context = MagicMock(exam_id="exam-1")
        exam_config = ExamConfig(
            exam_id="exam-1",
            subjects={
                "数学": SubjectConfig(full_score=120.0, excellent_percent=90.0),
                "英语": SubjectConfig(full_score=150.0, excellent_percent=90.0),
            },
        )
        page_state = PageState(
            exam_id="exam-1",
            page_name="grade_overview",
            selected_subject="数学",
            config_overrides={
                "__grade_overview__": {
                    "数学": {"full_score": 100.0, "excellent_percent": 85.0}
                }
            },
        )
        default = SubjectConfig(full_score=100.0, excellent_percent=90.0)

        math_rules = resolve_rules(
            context, exam_config, page_state, "数学", "全部学生", default
        )[1]
        english_rules = resolve_rules(
            context, exam_config, page_state, "英语", "全部学生", default
        )[1]
        math_again = resolve_rules(
            context, exam_config, page_state, "数学", "全部学生", default
        )[1]

        self.assertEqual((math_rules.full_score, math_rules.excellent_percent), (100.0, 85.0))
        self.assertEqual((english_rules.full_score, english_rules.excellent_percent), (150.0, 90.0))
        self.assertEqual(math_again, math_rules)

    def test_grade_overview_namespace_is_invisible_to_other_pages(self):
        page_state = PageState(
            exam_id="exam-1",
            page_name="subject_analysis",
            selected_subject="数学",
            config_overrides={
                "__grade_overview__": {
                    "数学": {"full_score": 100.0, "excellent_percent": 85.0}
                }
            },
        )
        exam_config = ExamConfig(
            exam_id="exam-1",
            subjects={"数学": SubjectConfig(full_score=120.0, excellent_percent=90.0)},
        )

        resolved = effective_config(
            exam_config,
            page_state,
            "数学",
            SubjectConfig(full_score=100.0, excellent_percent=90.0),
        )

        self.assertEqual(resolved.full_score, 120.0)
        self.assertEqual(resolved.excellent_percent, 90.0)

    def _load_unified_page_config_helpers(self):
        read_overrides = load_app_function(
            "read_namespaced_page_overrides",
            {"PageState": PageState, "deepcopy": deepcopy},
        )
        merge_overrides = load_app_function(
            "merge_page_config_overrides",
            {"PageState": PageState, "deepcopy": deepcopy},
        )
        resolve_config = load_app_function(
            "resolve_namespaced_subject_config",
            {
                "PageState": PageState,
                "SubjectConfig": SubjectConfig,
                "deepcopy": deepcopy,
                "replace": __import__("dataclasses").replace,
                "effective_config": effective_config,
                "read_namespaced_page_overrides": read_overrides,
            },
        )
        apply_event = load_app_function(
            "apply_page_config_widget_event",
            {
                "PageState": PageState,
                "SubjectConfig": SubjectConfig,
                "clean_column_name": clean_column_name,
                "deepcopy": deepcopy,
                "replace": __import__("dataclasses").replace,
                "merge_page_config_overrides": merge_overrides,
                "read_namespaced_page_overrides": read_overrides,
                "normalize_excellent_percent": lambda value: max(float(value), 60.0),
            },
        )
        sync_widgets = load_app_function(
            "synchronize_page_config_widgets",
            {},
        )
        return resolve_config, apply_event, sync_widgets

    @staticmethod
    def _unified_exam_config():
        return ExamConfig(
            exam_id="exam-1",
            subjects={
                "Math": SubjectConfig(
                    full_score=120.0,
                    pass_percent=60.0,
                    excellent_percent=80.0,
                ),
                "English": SubjectConfig(
                    full_score=150.0,
                    pass_percent=60.0,
                    excellent_percent=90.0,
                ),
            },
        )

    def test_stale_widget_values_have_no_business_authority(self):
        resolve_config, _, sync_widgets = self._load_unified_page_config_helpers()
        exam_config = self._unified_exam_config()
        page_state = PageState(exam_id="exam-1", page_name="grade_overview")
        original_page_state = deepcopy(page_state)
        default = SubjectConfig(full_score=100.0, excellent_percent=90.0)

        for stale_value in (1.0, 10.0, 20.0, float("nan"), float("inf")):
            session_state = {
                "full-score-widget": stale_value,
                "excellent-widget": stale_value,
            }
            _, first_config, _, _ = resolve_config(
                exam_config,
                page_state,
                namespace="__grade_overview__",
                page_name="grade_overview",
                subject="Math",
                selected_classes=(),
                system_default=default,
            )
            sync_widgets(
                session_state,
                first_config,
                full_score_key="full-score-widget",
                excellent_percent_key="excellent-widget",
            )
            _, final_config, _, _ = resolve_config(
                exam_config,
                page_state,
                namespace="__grade_overview__",
                page_name="grade_overview",
                subject="Math",
                selected_classes=(),
                system_default=default,
            )

            self.assertEqual(final_config.full_score, 120.0)
            self.assertEqual(final_config.pass_percent, 60.0)
            self.assertEqual(final_config.excellent_percent, 80.0)
            self.assertEqual(session_state["full-score-widget"], 120.0)
            self.assertEqual(session_state["excellent-widget"], 80.0)
            self.assertEqual(page_state, original_page_state)

    def test_explicit_widget_event_persists_only_in_grade_page_state(self):
        resolve_config, apply_event, sync_widgets = self._load_unified_page_config_helpers()
        exam_config = self._unified_exam_config()
        original_exam_config = deepcopy(exam_config)
        session_state = {
            "current_page_state": PageState(
                exam_id="exam-1",
                page_name="grade_overview",
            )
        }
        default = SubjectConfig(full_score=100.0, excellent_percent=90.0)
        base_config, first_config, _, _ = resolve_config(
            exam_config,
            session_state["current_page_state"],
            namespace="__grade_overview__",
            page_name="grade_overview",
            subject="Math",
            selected_classes=("2401",),
            system_default=default,
        )
        sync_widgets(
            session_state,
            first_config,
            full_score_key="full-score-widget",
            excellent_percent_key="excellent-widget",
        )
        session_state["full-score-widget"] = 150.0
        session_state["excellent-widget"] = 85.0

        changed = apply_event(
            session_state,
            namespace="__grade_overview__",
            page_name="grade_overview",
            exam_id="exam-1",
            subject="Math",
            selected_classes=("2401",),
            full_score_key="full-score-widget",
            excellent_percent_key="excellent-widget",
            base_config=base_config,
        )
        _, final_config, _, _ = resolve_config(
            exam_config,
            session_state["current_page_state"],
            namespace="__grade_overview__",
            page_name="grade_overview",
            subject="Math",
            selected_classes=(),
            system_default=default,
        )

        self.assertTrue(changed)
        self.assertEqual(final_config.full_score, 150.0)
        self.assertEqual(final_config.excellent_percent, 85.0)
        self.assertEqual(
            session_state["current_page_state"].config_overrides[
                "__grade_overview__"
            ]["Math"],
            {"full_score": 150.0, "excellent_percent": 85.0},
        )
        self.assertEqual(exam_config, original_exam_config)

    def test_all_analysis_pages_use_the_same_namespaced_config_flow(self):
        resolve_config, apply_event, sync_widgets = self._load_unified_page_config_helpers()
        exam_config = self._unified_exam_config()
        original_exam_config = deepcopy(exam_config)
        session_state = {
            "current_page_state": PageState(exam_id="exam-1")
        }
        default = SubjectConfig(full_score=100.0, excellent_percent=90.0)
        page_cases = (
            ("__grade_overview__", "grade_overview", 130.0),
            ("__class_analysis__", "class_comparison", 140.0),
            ("__subject_analysis__", "subject_analysis", 150.0),
        )

        for namespace, page_name, requested_full_score in page_cases:
            base_config, first_config, _, _ = resolve_config(
                exam_config,
                session_state["current_page_state"],
                namespace=namespace,
                page_name=page_name,
                subject="Math",
                selected_classes=("2401", "2402"),
                system_default=default,
            )
            full_key = f"{page_name}-full"
            excellent_key = f"{page_name}-excellent"
            sync_widgets(
                session_state,
                first_config,
                full_score_key=full_key,
                excellent_percent_key=excellent_key,
            )
            session_state[full_key] = requested_full_score
            session_state[excellent_key] = 85.0
            self.assertTrue(
                apply_event(
                    session_state,
                    namespace=namespace,
                    page_name=page_name,
                    exam_id="exam-1",
                    subject="Math",
                    selected_classes=("2401", "2402"),
                    full_score_key=full_key,
                    excellent_percent_key=excellent_key,
                    base_config=base_config,
                )
            )
            _, final_config, _, _ = resolve_config(
                exam_config,
                session_state["current_page_state"],
                namespace=namespace,
                page_name=page_name,
                subject="Math",
                selected_classes=("2401", "2402"),
                system_default=default,
            )
            self.assertEqual(final_config.full_score, requested_full_score)
            self.assertEqual(final_config.excellent_percent, 85.0)

        self.assertEqual(
            set(session_state["current_page_state"].config_overrides),
            {
                "__grade_overview__",
                "__class_analysis__",
                "__subject_analysis__",
            },
        )
        self.assertEqual(exam_config, original_exam_config)

    def test_navigation_without_grade_edit_preserves_grade_defaults(self):
        resolve_config, apply_event, sync_widgets = self._load_unified_page_config_helpers()
        exam_config = self._unified_exam_config()
        original_exam_config = deepcopy(exam_config)
        session_state = {
            "current_page_state": PageState(exam_id="exam-1")
        }
        default = SubjectConfig(full_score=100.0, excellent_percent=90.0)

        for selected_classes, subject in (
            (("2401",), "Math"),
            ((), "Math"),
            (("2402",), "Math"),
            ((), "English"),
            ((), "Math"),
        ):
            base, initial, _, stored = resolve_config(
                exam_config,
                session_state["current_page_state"],
                namespace="__grade_overview__",
                page_name="grade_overview",
                subject=subject,
                selected_classes=selected_classes,
                system_default=default,
            )
            session_state["current_page_state"] = stored
            sync_widgets(
                session_state,
                initial,
                full_score_key="grade-full",
                excellent_percent_key="grade-excellent",
            )
            self.assertTrue(
                apply_event(
                    session_state,
                    namespace="__grade_overview__",
                    page_name="grade_overview",
                    exam_id="exam-1",
                    subject=subject,
                    selected_classes=selected_classes,
                    full_score_key="grade-full",
                    excellent_percent_key="grade-excellent",
                    base_config=base,
                )
            )

        for namespace, page_name, full_score in (
            ("__class_analysis__", "class_comparison", 100.0),
            ("__subject_analysis__", "subject_analysis", 110.0),
        ):
            base, initial, _, stored = resolve_config(
                exam_config,
                session_state["current_page_state"],
                namespace=namespace,
                page_name=page_name,
                subject="Math",
                selected_classes=("2401", "2402"),
                system_default=default,
            )
            session_state["current_page_state"] = stored
            sync_widgets(
                session_state,
                initial,
                full_score_key=f"{page_name}-full",
                excellent_percent_key=f"{page_name}-excellent",
            )
            session_state[f"{page_name}-full"] = full_score
            session_state[f"{page_name}-excellent"] = 85.0
            self.assertTrue(
                apply_event(
                    session_state,
                    namespace=namespace,
                    page_name=page_name,
                    exam_id="exam-1",
                    subject="Math",
                    selected_classes=("2401", "2402"),
                    full_score_key=f"{page_name}-full",
                    excellent_percent_key=f"{page_name}-excellent",
                    base_config=base,
                )
            )

        session_state["current_page_state"] = __import__("dataclasses").replace(
            session_state["current_page_state"],
            page_name="teacher_view",
        )
        session_state["current_page_state"] = __import__("dataclasses").replace(
            session_state["current_page_state"],
            page_name="student_growth",
        )
        _, final_config, _, final_state = resolve_config(
            exam_config,
            session_state["current_page_state"],
            namespace="__grade_overview__",
            page_name="grade_overview",
            subject="Math",
            selected_classes=(),
            system_default=default,
        )

        self.assertEqual(
            (
                final_config.full_score,
                final_config.pass_percent,
                final_config.excellent_percent,
            ),
            (120.0, 60.0, 80.0),
        )
        self.assertEqual(
            set(final_state.config_overrides),
            {
                "__grade_overview__",
                "__class_analysis__",
                "__subject_analysis__",
            },
        )
        self.assertEqual(exam_config, original_exam_config)

    def test_invalid_explicit_widget_event_does_not_modify_page_state(self):
        _, apply_event, _ = self._load_unified_page_config_helpers()
        base_config = SubjectConfig(full_score=120.0, excellent_percent=80.0)
        for invalid_value in (None, float("nan"), float("inf")):
            initial_state = PageState(exam_id="exam-1", page_name="grade_overview")
            session_state = {
                "current_page_state": initial_state,
                "full": invalid_value,
                "excellent": 80.0,
            }
            self.assertFalse(
                apply_event(
                    session_state,
                    namespace="__grade_overview__",
                    page_name="grade_overview",
                    exam_id="exam-1",
                    subject="Math",
                    selected_classes=(),
                    full_score_key="full",
                    excellent_percent_key="excellent",
                    base_config=base_config,
                )
            )
            self.assertIs(session_state["current_page_state"], initial_state)

    def test_page_config_overrides_are_saved_incrementally_by_namespace(self):
        source = Path("app.py").read_text(encoding="utf-8")

        self.assertIn(
            'SUBJECT_ANALYSIS_OVERRIDE_NAMESPACE = "__subject_analysis__"',
            source,
        )
        self.assertIn("def merge_page_config_overrides(", source)

        subject_start = source.index(
            "def render_structured_subject_analysis_page("
        )
        subject_end = source.index("def render_class_analysis_page(", subject_start)
        subject_block = source[subject_start:subject_end]
        self.assertIn("resolve_namespaced_subject_config(", subject_block)
        self.assertIn("apply_page_config_widget_event", subject_block)

        class_start = source.index(
            "def render_structured_class_analysis_page("
        )
        class_end = source.index(
            'if analysis_mode == "subject_analysis":', class_start
        )
        class_block = source[class_start:class_end]
        self.assertIn("resolve_namespaced_subject_config(", class_block)
        self.assertIn("apply_page_config_widget_event", class_block)

    def test_grade_class_subject_grade_navigation_preserves_namespaces(self):
        merge_overrides = load_app_function(
            "merge_page_config_overrides",
            {"PageState": PageState, "deepcopy": deepcopy},
        )
        replace = __import__("dataclasses").replace
        exam_config = ExamConfig(
            exam_id="exam-1",
            subjects={
                "数学": SubjectConfig(
                    full_score=120.0,
                    pass_percent=60.0,
                    excellent_percent=90.0,
                )
            },
        )
        original_exam_config = deepcopy(exam_config)
        grade_state = PageState(
            exam_id="exam-1",
            page_name="grade_overview",
            selected_subject="数学",
            config_overrides={"__grade_overview__": {}},
        )
        class_state = replace(
            grade_state,
            page_name="class_comparison",
            config_overrides=merge_overrides(
                grade_state,
                "__class_analysis__",
                {"数学": {"full_score": 100.0, "excellent_percent": 80.0}},
                exam_id="exam-1",
            ),
        )
        subject_state = replace(
            class_state,
            page_name="subject_analysis",
            config_overrides=merge_overrides(
                class_state,
                "__subject_analysis__",
                {"数学": {"full_score": 110.0, "excellent_percent": 85.0}},
                exam_id="exam-1",
            ),
        )

        self.assertEqual(
            set(subject_state.config_overrides),
            {"__grade_overview__", "__class_analysis__", "__subject_analysis__"},
        )
        self.assertEqual(
            subject_state.config_overrides["__class_analysis__"]["数学"][
                "full_score"
            ],
            100.0,
        )
        self.assertEqual(
            subject_state.config_overrides["__subject_analysis__"]["数学"][
                "excellent_percent"
            ],
            85.0,
        )

        _, resolve_rules = self._load_grade_rule_helpers()
        _, resolved, returned_grade_state, _, _ = resolve_rules(
            MagicMock(exam_id="exam-1"),
            exam_config,
            subject_state,
            "数学",
            "全部学生",
            SubjectConfig(full_score=100.0, pass_percent=60.0, excellent_percent=90.0),
        )
        self.assertEqual(resolved.pass_percent, 60.0)
        self.assertEqual(resolved.excellent_percent, 90.0)
        self.assertEqual(
            set(returned_grade_state.config_overrides),
            {"__grade_overview__", "__class_analysis__", "__subject_analysis__"},
        )
        self.assertEqual(exam_config, original_exam_config)

    def test_grade_overview_rules_keep_legacy_analysis_result_when_values_match(self):
        _, resolve_rules = self._load_grade_rule_helpers()
        context = MagicMock(exam_id="exam-1")
        exam_config = ExamConfig(
            exam_id="exam-1",
            subjects={"数学": SubjectConfig(full_score=120.0, excellent_percent=90.0)},
        )
        rule_source = resolve_rules(
            context,
            exam_config,
            PageState(exam_id="exam-1", page_name="grade_overview"),
            "数学",
            "全部学生",
            SubjectConfig(full_score=100.0, excellent_percent=90.0),
        )
        resolved = rule_source[1]
        scores = {("student_id", "1"): 118.0, ("student_id", "2"): 70.0}

        legacy_result = analyze_scores(
            scores,
            full_score=120.0,
            excellent_percent=90.0,
            current_class="全部学生",
            current_subject="数学",
        )
        migrated_result = analyze_scores(
            scores,
            full_score=resolved.full_score,
            excellent_percent=resolved.excellent_percent,
            current_class="全部学生",
            current_subject="数学",
        )

        for key in (
            "student_count",
            "average_score",
            "highest_score",
            "lowest_score",
            "pass_rate",
            "excellent_rate",
            "excellent_count",
            "good_count",
            "pass_count",
            "fail_count",
            "excellent_students",
            "fail_students",
        ):
            self.assertEqual(migrated_result[key], legacy_result[key])

    def test_grade_overview_rule_source_falls_back_when_new_objects_are_missing(self):
        _, resolve_rules = self._load_grade_rule_helpers()
        context = MagicMock(exam_id="exam-1")
        config = ExamConfig(exam_id="exam-1")
        page_state = PageState(exam_id="exam-1", page_name="grade_overview")
        default = SubjectConfig(full_score=100.0, excellent_percent=90.0)

        self.assertIsNone(
            resolve_rules(context, None, page_state, "数学", "全部学生", default)
        )
        self.assertIsNone(
            resolve_rules(context, config, None, "数学", "全部学生", default)
        )
        self.assertIsNone(
            resolve_rules(
                context,
                ExamConfig(exam_id="exam-2"),
                PageState(exam_id="exam-2", page_name="grade_overview"),
                "数学",
                "全部学生",
                default,
            )
        )

    def test_grade_overview_route_uses_effective_config_without_result_store(self):
        source = Path("app.py").read_text(encoding="utf-8")
        grade_start = source.index("uploaded_file = None")
        grade_block = source[grade_start:]

        self.assertIn("resolve_grade_overview_rule_source(", grade_block)
        self.assertIn("effective_config(", source)
        self.assertIn("GRADE_OVERVIEW_OVERRIDE_NAMESPACE", source)
        self.assertNotIn("build_analysis_request(", grade_block)
        self.assertNotIn("get_or_build_subject_result(", grade_block)
        self.assertNotIn("get_or_build_class_result(", grade_block)


if __name__ == "__main__":
    unittest.main()
