from copy import deepcopy
import unittest

from models import ExamContext
from services.exam_context_builder import build_exam_context


class ExamContextBuilderTest(unittest.TestCase):
    def setUp(self):
        self.snapshot_data = {
            "identity_records_by_index": {
                3: {
                    "identity_key": ("student_id", "1001"),
                    "姓名": "张三",
                    "班级": "1班",
                    "学号": "1001",
                },
                8: {
                    "identity_key": ("student_id", "1002"),
                    "姓名": "李四",
                    "班级": "2班",
                    "学号": "1002",
                },
            },
            "subject_scores_by_index": {
                3: {"数学": 118, "英语": 145},
                8: {"数学": 109, "英语": 138},
            },
        }

    def build_context(self, **overrides):
        arguments = {
            "file_content": b"same workbook bytes",
            "file_name": "期中考试.xlsx",
            "sheet_name": "成绩表",
            "exam_name": "2026年期中考试",
            "name_column": "姓名",
            "class_column": "班级",
            "student_id_column": "学号",
            "score_columns": ("数学", "英语"),
            **self.snapshot_data,
        }
        arguments.update(overrides)
        return build_exam_context(**arguments)

    def test_same_exam_input_generates_stable_exam_id(self):
        first = self.build_context()
        second = self.build_context()

        self.assertEqual(first.exam_id, second.exam_id)
        self.assertTrue(first.exam_id.startswith("exam-"))

    def test_context_contains_students_subjects_and_score_indexes(self):
        context = self.build_context()

        self.assertIsInstance(context, ExamContext)
        self.assertEqual(len(context.identity_records_by_index), 2)
        self.assertEqual(context.schema.score_columns, ("数学", "英语"))
        self.assertEqual(set(context.subject_scores_by_index), {3, 8})
        self.assertEqual(context.subject_scores_by_index[3]["数学"], 118)
        self.assertEqual(context.metadata.exam_name, "2026年期中考试")
        self.assertEqual(context.metadata.file_name, "期中考试.xlsx")

    def test_builder_does_not_modify_or_alias_snapshot_data(self):
        original = deepcopy(self.snapshot_data)

        context = self.build_context()
        context.identity_records_by_index[3]["姓名"] = "修改后的姓名"
        context.subject_scores_by_index[3]["数学"] = 1

        self.assertEqual(self.snapshot_data, original)
        self.assertIsNot(
            context.identity_records_by_index,
            self.snapshot_data["identity_records_by_index"],
        )
        self.assertIsNot(
            context.subject_scores_by_index,
            self.snapshot_data["subject_scores_by_index"],
        )

    def test_schema_change_generates_a_different_exam_id(self):
        original = self.build_context()
        changed = self.build_context(score_columns=("英语", "数学"))

        self.assertNotEqual(original.exam_id, changed.exam_id)


if __name__ == "__main__":
    unittest.main()
