"""从 Excel 字节建立考试事实档案的纯服务层。"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO

import pandas as pd

from grade_logic import (
    CLASS_COLUMN_ALIASES,
    NAME_COLUMN_ALIASES,
    build_dataframe_from_header,
    build_score_column_options,
    detect_header_row,
    find_first_matching_column,
    find_first_matching_score_column,
    has_analyzable_columns,
)
from models import ExamContext
from student_identity import (
    build_student_identity_records,
    find_student_id_column,
)

from .exam_context_builder import build_exam_context as build_exam_context_model


class ExamImportError(ValueError):
    """考试导入领域错误基类。"""


class EmptyExamFileError(ExamImportError):
    """上传文件没有可读取内容。"""


class WorkbookReadError(ExamImportError):
    """工作簿无法打开或解析。"""


class SheetNotFoundError(ExamImportError):
    """指定工作表不存在。"""


class EmptySheetError(ExamImportError):
    """工作表不包含可建立考试档案的数据。"""


class HeaderRowError(ExamImportError):
    """表头行无法识别或超出工作表范围。"""


class ColumnMappingError(ExamImportError):
    """字段映射不完整、冲突或引用了不存在的列。"""


class IdentityBuildError(ExamImportError):
    """学生身份记录无法建立。"""


@dataclass(frozen=True)
class WorkbookInspection:
    """不包含工作表数据的工作簿检查结果。"""

    file_name: str
    file_fingerprint: str
    sheet_names: tuple[str, ...]


@dataclass(frozen=True)
class ExamColumnMapping:
    """用户确认后的考试字段映射。"""

    name_column: str
    class_column: str | None
    student_id_column: str | None
    score_columns: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "score_columns",
            tuple(self.score_columns),
        )


@dataclass(frozen=True)
class ExamImportDraft:
    """字段确认前的临时工作表数据，不应作为长期考试状态保存。"""

    file_content: bytes = field(repr=False)
    file_name: str
    file_fingerprint: str
    sheet_names: tuple[str, ...]
    selected_sheet: str
    detected_header_row: int | None
    header_row_index: int
    dataframe: pd.DataFrame = field(repr=False, compare=False)
    suggested_mapping: ExamColumnMapping


def _require_file_content(file_content: bytes) -> bytes:
    if not isinstance(file_content, bytes):
        raise TypeError("file_content 必须是 bytes。")
    if not file_content:
        raise EmptyExamFileError("Excel 文件内容为空。")
    return file_content


def _normalize_roster_names(values: pd.Series) -> pd.Series:
    names = values.copy().fillna("").astype(str)
    return names.str.replace("\u3000", "", regex=False).str.strip()


def _require_unique_column(columns: list[object], column: str, role: str) -> None:
    if columns.count(column) == 0:
        raise ColumnMappingError(f"{role}不存在：{column}。")
    if columns.count(column) > 1:
        raise ColumnMappingError(f"{role}存在重复列名：{column}。")


class ExamImportService:
    """分阶段检查工作簿、准备工作表并构建 ExamContext。"""

    def inspect_workbook(
        self,
        file_content: bytes,
        file_name: str,
    ) -> WorkbookInspection:
        content = _require_file_content(file_content)
        try:
            with pd.ExcelFile(BytesIO(content)) as workbook:
                sheet_names = tuple(str(name) for name in workbook.sheet_names)
        except Exception as exc:
            raise WorkbookReadError(f"读取 Excel 工作簿失败：{exc}") from exc
        if not sheet_names:
            raise WorkbookReadError("Excel 工作簿不包含工作表。")
        return WorkbookInspection(
            file_name=str(file_name),
            file_fingerprint=sha256(content).hexdigest(),
            sheet_names=sheet_names,
        )

    def prepare_sheet(
        self,
        file_content: bytes,
        file_name: str,
        sheet_name: str,
        header_row_index: int | None,
    ) -> ExamImportDraft:
        inspection = self.inspect_workbook(file_content, file_name)
        selected_sheet = str(sheet_name)
        if selected_sheet not in inspection.sheet_names:
            raise SheetNotFoundError(f"工作表不存在：{selected_sheet}。")

        try:
            raw_dataframe = pd.read_excel(
                BytesIO(file_content),
                sheet_name=selected_sheet,
                header=None,
            )
        except Exception as exc:
            raise WorkbookReadError(
                f"读取工作表失败：{selected_sheet}：{exc}"
            ) from exc
        if raw_dataframe.empty:
            raise EmptySheetError(f"工作表没有数据：{selected_sheet}。")

        detected_header_row = detect_header_row(raw_dataframe)
        resolved_header_row = (
            detected_header_row
            if header_row_index is None
            else header_row_index
        )
        if resolved_header_row is None:
            raise HeaderRowError("未自动识别到表头，请明确提供 header_row_index。")
        if (
            isinstance(resolved_header_row, bool)
            or not isinstance(resolved_header_row, int)
            or not 0 <= resolved_header_row < len(raw_dataframe)
        ):
            raise HeaderRowError("header_row_index 超出工作表范围。")

        dataframe = build_dataframe_from_header(
            raw_dataframe,
            resolved_header_row,
        )
        if dataframe.empty:
            raise EmptySheetError("表头下方没有考试数据。")
        if len(dataframe.columns) < 2 or not has_analyzable_columns(
            dataframe.columns
        ):
            raise ColumnMappingError("当前工作表未识别到姓名列和成绩列。")

        columns = dataframe.columns.tolist()
        name_column = find_first_matching_column(
            columns,
            NAME_COLUMN_ALIASES,
        )
        class_column = find_first_matching_column(
            columns,
            CLASS_COLUMN_ALIASES,
        )
        student_id_column = find_student_id_column(columns)
        matched_score_column = find_first_matching_score_column(columns)
        score_columns = tuple(
            build_score_column_options(
                columns,
                excluded_columns=(
                    name_column,
                    class_column,
                    student_id_column,
                ),
            )
        )
        if name_column is None or matched_score_column not in score_columns:
            raise ColumnMappingError("当前工作表未识别到有效字段映射。")
        if not score_columns:
            raise ColumnMappingError("当前工作表没有可用科目列。")

        return ExamImportDraft(
            file_content=file_content,
            file_name=inspection.file_name,
            file_fingerprint=inspection.file_fingerprint,
            sheet_names=inspection.sheet_names,
            selected_sheet=selected_sheet,
            detected_header_row=detected_header_row,
            header_row_index=resolved_header_row,
            dataframe=dataframe.copy(deep=True),
            suggested_mapping=ExamColumnMapping(
                name_column=name_column,
                class_column=class_column,
                student_id_column=student_id_column,
                score_columns=score_columns,
            ),
        )

    def build_context(
        self,
        draft: ExamImportDraft,
        column_mapping: ExamColumnMapping,
        exam_name: str | None = None,
    ) -> ExamContext:
        if not isinstance(draft, ExamImportDraft):
            raise TypeError("draft 必须是 ExamImportDraft。")
        if not isinstance(column_mapping, ExamColumnMapping):
            raise TypeError("column_mapping 必须是 ExamColumnMapping。")

        dataframe = draft.dataframe
        if not dataframe.index.is_unique:
            raise IdentityBuildError("成绩数据行索引不唯一。")
        columns = dataframe.columns.tolist()
        _require_unique_column(
            columns,
            column_mapping.name_column,
            "姓名列",
        )
        role_columns = [column_mapping.name_column]
        for role, column in (
            ("班级列", column_mapping.class_column),
            ("学号列", column_mapping.student_id_column),
        ):
            if column is None:
                continue
            _require_unique_column(columns, column, role)
            role_columns.append(column)
        if len(set(role_columns)) != len(role_columns):
            raise ColumnMappingError("姓名、班级和学号列不能重复。")

        if not column_mapping.score_columns:
            raise ColumnMappingError("至少需要一个成绩列。")
        if len(set(column_mapping.score_columns)) != len(
            column_mapping.score_columns
        ):
            raise ColumnMappingError("成绩列不能重复。")
        available_score_columns = set(
            build_score_column_options(
                columns,
                excluded_columns=tuple(role_columns),
            )
        )
        for score_column in column_mapping.score_columns:
            _require_unique_column(columns, score_column, "成绩列")
            if score_column not in available_score_columns:
                raise ColumnMappingError(
                    f"字段不能作为成绩列：{score_column}。"
                )

        identity_columns = list(role_columns)
        identity_rows = dataframe[identity_columns].copy()
        normalized_names = _normalize_roster_names(
            dataframe[column_mapping.name_column]
        )
        valid_name_mask = (
            (normalized_names != "")
            & (normalized_names.str.lower() != "nan")
        )
        identity_rows["姓名"] = normalized_names
        identity_rows["分数"] = 0.0
        valid_identity_rows = identity_rows[valid_name_mask].copy()
        if valid_identity_rows.empty:
            raise IdentityBuildError("工作表没有可建立身份的学生姓名。")

        try:
            identity_records = build_student_identity_records(
                valid_identity_rows,
                class_column=column_mapping.class_column,
                student_id_column=column_mapping.student_id_column,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityBuildError(f"建立学生身份失败：{exc}") from exc
        identity_records_by_index = dict(
            zip(valid_identity_rows.index, identity_records)
        )
        subject_scores_by_index = {
            row_index: {
                score_column: dataframe.at[row_index, score_column]
                for score_column in column_mapping.score_columns
            }
            for row_index in identity_records_by_index
        }

        return build_exam_context_model(
            file_content=draft.file_content,
            file_name=draft.file_name,
            sheet_name=draft.selected_sheet,
            exam_name=exam_name,
            name_column=column_mapping.name_column,
            class_column=column_mapping.class_column,
            student_id_column=column_mapping.student_id_column,
            score_columns=column_mapping.score_columns,
            identity_records_by_index=identity_records_by_index,
            subject_scores_by_index=subject_scores_by_index,
        )
