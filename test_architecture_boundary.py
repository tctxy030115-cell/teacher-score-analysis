import ast
from copy import deepcopy
from pathlib import Path
import unittest

from models import (
    AnalysisRequest,
    ExamConfig,
    ExamContext,
    ExamMetadata,
    ExamSchema,
    PageState,
    SubjectConfig,
)
from services import ResultStore, build_analysis_request
from services.class_analysis_service import get_or_build_class_result
from services.report_result_service import get_or_build_report_result
from services.subject_analysis_service import get_or_build_subject_result


PROJECT_ROOT = Path(__file__).resolve().parent
APP_PATH = PROJECT_ROOT / "app.py"
SERVICES_PATH = PROJECT_ROOT / "services"
FREEZE_DOCUMENT_PATH = PROJECT_ROOT / "docs" / "architecture_freeze_v1.md"


def _make_context() -> ExamContext:
    return ExamContext(
        exam_id="exam-freeze-v1",
        metadata=ExamMetadata(
            file_name="期中考试.xlsx",
            file_fingerprint="stable-fingerprint",
            sheet_name="成绩表",
        ),
        schema=ExamSchema(
            name_column="姓名",
            class_column="班级",
            score_columns=("数学",),
        ),
    )


def _make_config() -> ExamConfig:
    return ExamConfig(
        exam_id="exam-freeze-v1",
        subjects={
            "数学": SubjectConfig(
                full_score=120.0,
                excellent_percent=90.0,
            )
        },
    )


def _make_page_state(page_name: str) -> PageState:
    return PageState(
        exam_id="exam-freeze-v1",
        page_name=page_name,
        selected_subject="数学",
        selected_classes=("2401", "2402"),
        config_overrides={"数学": {"excellent_percent": 85.0}},
    )


def _make_payload() -> dict:
    return {
        "summary": {
            "current_subject": "数学",
            "selected_classes": ("2401", "2402"),
        },
        "metrics": {"average_score": 88.0},
        "tables": {"class_comparison": [{"班级": "2401"}]},
        "charts": {"distribution_data": [{"level": "优秀", "count": 1}]},
        "extra": {},
    }


def _condition_mentions_mode(node: ast.If, mode: str) -> bool:
    return mode in ast.unparse(node.test)


def _session_state_store_keys(node: ast.AST) -> set[str]:
    keys: set[str] = set()
    for child in ast.walk(node):
        targets = []
        if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = (
                child.targets
                if isinstance(child, ast.Assign)
                else [child.target]
            )
        for target in targets:
            if not isinstance(target, ast.Subscript):
                continue
            if ast.unparse(target.value) != "st.session_state":
                continue
            if isinstance(target.slice, ast.Constant) and isinstance(
                target.slice.value,
                str,
            ):
                keys.add(target.slice.value)
    return keys


def _contains_figure_like_object(value) -> bool:
    value_type = type(value)
    if value_type.__module__.startswith("plotly") or value_type.__name__ == "Figure":
        return True
    if isinstance(value, dict):
        return any(
            _contains_figure_like_object(key)
            or _contains_figure_like_object(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_figure_like_object(item) for item in value)
    if hasattr(value, "summary") and hasattr(value, "metrics"):
        return any(
            _contains_figure_like_object(getattr(value, field_name))
            for field_name in ("summary", "metrics", "tables", "charts", "extra")
        )
    if hasattr(value, "payload"):
        return _contains_figure_like_object(value.payload)
    return False


class ArchitectureBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = APP_PATH.read_text(encoding="utf-8")
        cls.app_tree = ast.parse(cls.app_source)

    def test_architecture_freeze_document_records_required_baseline(self):
        self.assertTrue(FREEZE_DOCUMENT_PATH.exists())
        content = FREEZE_DOCUMENT_PATH.read_text(encoding="utf-8")
        for required_text in (
            "Report Center",
            "Subject Analysis",
            "Class Analysis",
            "Grade Overview",
            "ExamContext",
            "ExamConfig",
            "PageState",
            "AnalysisRequest",
            "ResultKey",
            "ResultStore",
            "AnalysisResult",
            "fallback",
            "Phase 3.3",
            "Phase 4",
        ):
            self.assertIn(required_text, content)

    def test_migrated_page_routes_do_not_write_current_exam_config(self):
        for mode in ("report_center", "subject_analysis", "class_comparison"):
            matching_routes = [
                node
                for node in ast.walk(self.app_tree)
                if isinstance(node, ast.If) and _condition_mentions_mode(node, mode)
            ]
            self.assertTrue(matching_routes, f"未找到 {mode} 页面路由")
            for route in matching_routes:
                self.assertNotIn(
                    "current_exam_config",
                    _session_state_store_keys(route),
                    f"{mode} 页面不得写入 ExamConfig",
                )

    def test_migrated_services_do_not_modify_exam_config(self):
        context = _make_context()
        config = _make_config()
        original = deepcopy(config)

        get_or_build_subject_result(
            context,
            config,
            _make_page_state("subject_analysis"),
            ResultStore(),
            _make_payload,
        )
        get_or_build_class_result(
            context,
            config,
            _make_page_state("class_comparison"),
            ResultStore(),
            _make_payload,
        )

        self.assertEqual(config, original)

    def test_migrated_results_saved_to_store_contain_data_not_figures(self):
        context = _make_context()
        config = _make_config()
        for service, page_name in (
            (get_or_build_subject_result, "subject_analysis"),
            (get_or_build_class_result, "class_comparison"),
        ):
            store = ResultStore()
            result = service(
                context,
                config,
                _make_page_state(page_name),
                store,
                _make_payload,
            )
            stored = store.get(result.result_key)
            self.assertFalse(_contains_figure_like_object(stored))

    def test_service_layer_does_not_depend_on_streamlit(self):
        violations = []
        for service_path in SERVICES_PATH.glob("*.py"):
            tree = ast.parse(service_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imported_names = [node.module or ""]
                else:
                    continue
                if any(name == "streamlit" or name.startswith("streamlit.") for name in imported_names):
                    violations.append(service_path.name)
        self.assertEqual(violations, [])

    def test_analysis_request_builder_does_not_modify_inputs(self):
        context = _make_context()
        config = _make_config()
        page_state = _make_page_state("subject_analysis")
        originals = deepcopy((context, config, page_state))

        request = build_analysis_request(context, config, page_state)

        self.assertIsInstance(request, AnalysisRequest)
        self.assertEqual((context, config, page_state), originals)

    def test_legacy_fallback_paths_remain_available(self):
        callback_calls = []
        subject_fallback = get_or_build_subject_result(
            None,
            _make_config(),
            _make_page_state("subject_analysis"),
            ResultStore(),
            lambda: callback_calls.append("subject"),
        )
        class_fallback = get_or_build_class_result(
            None,
            _make_config(),
            _make_page_state("class_comparison"),
            ResultStore(),
            lambda: callback_calls.append("class"),
        )
        report_fallback = get_or_build_report_result(None, None, _make_payload())

        self.assertIsNone(subject_fallback)
        self.assertIsNone(class_fallback)
        self.assertIsNone(report_fallback)
        self.assertEqual(callback_calls, [])
        self.assertIn("render_subject_analysis_page(snapshot)", self.app_source)
        self.assertIn("render_class_analysis_page(snapshot)", self.app_source)
        self.assertIn("fallback=snapshot[\"analysis_result\"]", self.app_source)


if __name__ == "__main__":
    unittest.main()
