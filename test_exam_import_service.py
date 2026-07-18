import ast
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import unittest

import pandas as pd
from openpyxl import Workbook

import services
from models import ExamContext
from services.exam_import_service import (
    ColumnMappingError,
    EmptyExamFileError,
    ExamColumnMapping,
    ExamImportService,
    SheetNotFoundError,
)


PROJECT_ROOT = Path(__file__).resolve().parent
SERVICE_PATH = PROJECT_ROOT / "services" / "exam_import_service.py"


def build_workbook_bytes() -> bytes:
    workbook = Workbook()
    score_sheet = workbook.active
    score_sheet.title = "成绩表"
    score_sheet.append(["2026 年期中考试"])
    score_sheet.append(["学号", "姓名", "班级", "数学", "英语"])
    score_sheet.append(["1001", "张三", "2401", 118, 145])
    score_sheet.append(["1002", "张三", "2402", 109, 138])
    score_sheet.append(["1003", "李四", "2401", None, 130])

    chinese_sheet = workbook.create_sheet("语文表")
    chinese_sheet.append(["姓名", "班级", "语文"])
    chinese_sheet.append(["王五", "2403", 110])

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


class ExamImportServiceTest(unittest.TestCase):
    def setUp(self):
        self.service = ExamImportService()
        self.file_content = build_workbook_bytes()

    def prepare_score_sheet(self):
        return self.service.prepare_sheet(
            self.file_content,
            "期中考试.xlsx",
            "成绩表",
            None,
        )

    def test_service_contract_is_exported_from_services_package(self):
        self.assertIs(services.ExamImportService, ExamImportService)
        self.assertIs(services.ExamColumnMapping, ExamColumnMapping)
        self.assertIs(services.ExamImportError, EmptyExamFileError.__base__)

    def test_same_input_generates_stable_context(self):
        first_draft = self.prepare_score_sheet()
        second_draft = self.prepare_score_sheet()

        first = self.service.build_context(
            first_draft,
            first_draft.suggested_mapping,
            exam_name="2026 年期中考试",
        )
        second = self.service.build_context(
            second_draft,
            second_draft.suggested_mapping,
            exam_name="2026 年期中考试",
        )

        self.assertIsInstance(first, ExamContext)
        self.assertEqual(first, second)
        self.assertEqual(first.exam_id, second.exam_id)
        self.assertEqual(first.metadata.file_name, "期中考试.xlsx")
        self.assertEqual(first.metadata.sheet_name, "成绩表")

    def test_multiple_sheets_are_isolated(self):
        inspection = self.service.inspect_workbook(
            self.file_content,
            "期中考试.xlsx",
        )
        score_draft = self.prepare_score_sheet()
        chinese_draft = self.service.prepare_sheet(
            self.file_content,
            "期中考试.xlsx",
            "语文表",
            None,
        )

        score_context = self.service.build_context(
            score_draft,
            score_draft.suggested_mapping,
        )
        chinese_context = self.service.build_context(
            chinese_draft,
            chinese_draft.suggested_mapping,
        )

        self.assertEqual(inspection.sheet_names, ("成绩表", "语文表"))
        self.assertNotEqual(score_context.exam_id, chinese_context.exam_id)
        self.assertEqual(score_context.schema.score_columns, ("数学", "英语"))
        self.assertEqual(chinese_context.schema.score_columns, ("语文",))

    def test_context_contains_complete_student_roster(self):
        draft = self.prepare_score_sheet()

        context = self.service.build_context(draft, draft.suggested_mapping)

        self.assertEqual(len(context.identity_records_by_index), 3)
        self.assertEqual(
            context.identity_records_by_index[2]["identity_key"],
            ("student_id", "1003"),
        )
        self.assertTrue(pd.isna(context.subject_scores_by_index[2]["数学"]))
        self.assertEqual(context.subject_scores_by_index[2]["英语"], 130)

    def test_scores_are_saved_by_stable_post_header_index(self):
        draft = self.prepare_score_sheet()

        context = self.service.build_context(draft, draft.suggested_mapping)

        self.assertEqual(set(context.identity_records_by_index), {0, 1, 2})
        self.assertEqual(set(context.subject_scores_by_index), {0, 1, 2})
        self.assertEqual(context.subject_scores_by_index[0]["数学"], 118)
        self.assertEqual(context.subject_scores_by_index[1]["英语"], 138)

    def test_same_name_students_do_not_overwrite_each_other(self):
        draft = self.prepare_score_sheet()

        context = self.service.build_context(draft, draft.suggested_mapping)

        first = context.identity_records_by_index[0]
        second = context.identity_records_by_index[1]
        self.assertEqual(first["姓名"], "张三")
        self.assertEqual(second["姓名"], "张三")
        self.assertNotEqual(first["identity_key"], second["identity_key"])
        self.assertEqual(len(context.identity_records_by_index), 3)

    def test_service_does_not_depend_on_streamlit_or_analysis_layers(self):
        source = SERVICE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_modules.append(node.module or "")

        self.assertFalse(
            any(module == "streamlit" or module.startswith("streamlit.") for module in imported_modules)
        )
        for forbidden_text in (
            "session_state",
            "st.stop",
            "st.rerun",
            "analyze_scores",
            "chart_logic",
            "report_logic",
        ):
            self.assertNotIn(forbidden_text, source)

    def test_service_does_not_modify_inputs_or_store_draft_in_context(self):
        original_bytes = bytes(self.file_content)
        draft = self.prepare_score_sheet()
        original_dataframe = draft.dataframe.copy(deep=True)
        mapping = deepcopy(draft.suggested_mapping)

        context = self.service.build_context(draft, mapping)

        self.assertEqual(self.file_content, original_bytes)
        pd.testing.assert_frame_equal(draft.dataframe, original_dataframe)
        self.assertEqual(mapping, draft.suggested_mapping)
        self.assertFalse(hasattr(context, "dataframe"))
        self.assertFalse(hasattr(context, "file_content"))

    def test_empty_file_raises_clear_error(self):
        with self.assertRaises(EmptyExamFileError):
            self.service.inspect_workbook(b"", "空文件.xlsx")

        with self.assertRaises(EmptyExamFileError):
            self.service.prepare_sheet(b"", "空文件.xlsx", "成绩表", None)

    def test_unknown_sheet_raises_clear_error(self):
        with self.assertRaises(SheetNotFoundError):
            self.service.prepare_sheet(
                self.file_content,
                "期中考试.xlsx",
                "不存在的工作表",
                None,
            )

    def test_invalid_column_mapping_raises_clear_error(self):
        draft = self.prepare_score_sheet()
        invalid_mapping = ExamColumnMapping(
            name_column="不存在的姓名列",
            class_column="班级",
            student_id_column="学号",
            score_columns=("数学",),
        )

        with self.assertRaises(ColumnMappingError):
            self.service.build_context(draft, invalid_mapping)


if __name__ == "__main__":
    unittest.main()
