"""Excel export service for Signal Sudoku.

Generates formatted Excel workbooks from allocation results,
validation reports, and technical queries.
"""
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from io import BytesIO
from typing import Dict, Optional, List, Any

# ---------------------------------------------------------------------------
# Formatting constants
# ---------------------------------------------------------------------------
HEADER_FILL = PatternFill(start_color='1B2A4A', end_color='1B2A4A', fill_type='solid')
HEADER_FONT = Font(name='Calibri', bold=True, color='FFFFFF', size=11)
SUCCESS_FILL = PatternFill(start_color='E8F5E9', end_color='E8F5E9', fill_type='solid')
WARNING_FILL = PatternFill(start_color='FFF8E1', end_color='FFF8E1', fill_type='solid')
ERROR_FILL = PatternFill(start_color='FFEBEE', end_color='FFEBEE', fill_type='solid')
INFO_FILL = PatternFill(start_color='E3F2FD', end_color='E3F2FD', fill_type='solid')
TQ_FILL = PatternFill(start_color='F3E5F5', end_color='F3E5F5', fill_type='solid')
THIN_BORDER = Border(
    left=Side(style='thin', color='D0D0D0'),
    right=Side(style='thin', color='D0D0D0'),
    top=Side(style='thin', color='D0D0D0'),
    bottom=Side(style='thin', color='D0D0D0'),
)
BODY_FONT = Font(name='Calibri', size=11)
BODY_ALIGNMENT = Alignment(vertical='center', wrap_text=False)
HEADER_ALIGNMENT = Alignment(horizontal='center', vertical='center', wrap_text=True)

# Status colour lookup
_STATUS_FILLS: Dict[str, PatternFill] = {
    'allocated': SUCCESS_FILL,
    'unallocated': ERROR_FILL,
    'warning': WARNING_FILL,
}

# Severity colour lookup
_SEVERITY_FILLS: Dict[str, PatternFill] = {
    'error': ERROR_FILL,
    'warning': WARNING_FILL,
    'info': INFO_FILL,
    'tq_required': TQ_FILL,
}

MAX_COL_WIDTH = 40
MIN_COL_WIDTH = 10


class ExcelExporter:
    """Service that produces professionally-formatted Excel workbooks.

    All ``export_*`` methods return a :class:`~io.BytesIO` buffer that is
    ready for download (e.g. via ``st.download_button``).
    """

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _auto_fit_columns(ws: openpyxl.worksheet.worksheet.Worksheet) -> None:
        """Set column widths based on content, capped at MAX_COL_WIDTH."""
        for col_cells in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col_cells[0].column)
            for cell in col_cells:
                try:
                    cell_len = len(str(cell.value)) if cell.value is not None else 0
                    if cell_len > max_len:
                        max_len = cell_len
                except Exception:
                    pass
            adjusted = min(max(max_len + 3, MIN_COL_WIDTH), MAX_COL_WIDTH)
            ws.column_dimensions[col_letter].width = adjusted

    @staticmethod
    def _apply_header_style(ws: openpyxl.worksheet.worksheet.Worksheet) -> None:
        """Style the first row as a header and freeze it."""
        for cell in ws[1]:
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = HEADER_ALIGNMENT
            cell.border = THIN_BORDER
        ws.freeze_panes = 'A2'

    @staticmethod
    def _apply_body_borders(ws: openpyxl.worksheet.worksheet.Worksheet) -> None:
        """Apply thin borders and base font to all body rows."""
        for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=ws.max_column):
            for cell in row:
                cell.font = BODY_FONT
                cell.alignment = BODY_ALIGNMENT
                cell.border = THIN_BORDER

    @staticmethod
    def _add_auto_filter(ws: openpyxl.worksheet.worksheet.Worksheet) -> None:
        """Add auto-filter spanning all columns."""
        if ws.max_row and ws.max_column:
            last_col_letter = get_column_letter(ws.max_column)
            ws.auto_filter.ref = f'A1:{last_col_letter}{ws.max_row}'

    @staticmethod
    def _colour_status_column(ws: openpyxl.worksheet.worksheet.Worksheet, col_name: str, fill_map: Dict[str, PatternFill]) -> None:
        """Apply conditional fill to cells in *col_name* based on *fill_map*."""
        # Find the column index
        header_row = [cell.value for cell in ws[1]]
        if col_name not in header_row:
            return
        col_idx = header_row.index(col_name) + 1  # 1-based

        for row_idx in range(2, ws.max_row + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            val = str(cell.value).strip().lower() if cell.value is not None else ''
            if val in fill_map:
                # Apply fill to the entire row for status, or just the cell
                cell.fill = fill_map[val]

    @staticmethod
    def _format_numeric_columns(ws: openpyxl.worksheet.worksheet.Worksheet, numeric_keywords: Optional[List[str]] = None) -> None:
        """Set a number format on columns whose header contains numeric keywords."""
        if numeric_keywords is None:
            numeric_keywords = ['count', 'total', 'spare', 'used', 'capacity', '%', 'percentage', 'utilization']

        header_row = [str(cell.value).lower() if cell.value else '' for cell in ws[1]]
        numeric_cols: List[int] = []
        for idx, header in enumerate(header_row):
            for kw in numeric_keywords:
                if kw in header:
                    numeric_cols.append(idx + 1)
                    break

        for col_idx in numeric_cols:
            for row_idx in range(2, ws.max_row + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                if cell.value is not None:
                    try:
                        numeric_val = float(cell.value)
                        cell.value = numeric_val
                        if numeric_val == int(numeric_val):
                            cell.number_format = '#,##0'
                        else:
                            cell.number_format = '#,##0.0'
                    except (ValueError, TypeError):
                        pass

    def _write_df_to_sheet(
        self,
        wb: openpyxl.Workbook,
        df: pd.DataFrame,
        sheet_name: str,
        status_col: Optional[str] = None,
        status_map: Optional[Dict[str, PatternFill]] = None,
    ) -> openpyxl.worksheet.worksheet.Worksheet:
        """Write a DataFrame into a new sheet with full formatting.

        Args:
            wb: The target workbook.
            df: Data to write.
            sheet_name: Name for the new sheet.
            status_col: Optional column name whose cells should be colour-coded.
            status_map: Colour map to use with *status_col*.

        Returns:
            The newly created worksheet.
        """
        ws = wb.create_sheet(title=sheet_name)

        # Write header
        for col_idx, col_name in enumerate(df.columns, start=1):
            ws.cell(row=1, column=col_idx, value=col_name)

        # Write body
        for row_idx, (_, row) in enumerate(df.iterrows(), start=2):
            for col_idx, value in enumerate(row, start=1):
                cell = ws.cell(row=row_idx, column=col_idx)
                # Convert NaN/None to empty string for display
                if pd.isna(value):
                    cell.value = ''
                else:
                    cell.value = value

        # Apply formatting
        self._apply_header_style(ws)
        self._apply_body_borders(ws)
        self._auto_fit_columns(ws)
        self._add_auto_filter(ws)
        self._format_numeric_columns(ws)

        if status_col and status_map:
            self._colour_status_column(ws, status_col, status_map)

        return ws

    @staticmethod
    def _workbook_to_buffer(wb: openpyxl.Workbook) -> BytesIO:
        """Save workbook to a BytesIO buffer and rewind."""
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export_allocation(
        self,
        allocation_df: pd.DataFrame,
        validation_df: pd.DataFrame,
        tq_df: pd.DataFrame,
        hardware_df: pd.DataFrame,
        config_df: pd.DataFrame,
    ) -> BytesIO:
        """Create a multi-sheet allocation workbook.

        Sheets produced:
        1. **IO_Allocation** – main allocation table (Status column colour-coded)
        2. **Validation_Report** – validation findings (Severity colour-coded)
        3. **Technical_Queries** – TQ list (Severity colour-coded)
        4. **Hardware_Summary** – hardware utilisation
        5. **Configuration** – active rule settings

        Args:
            allocation_df: Allocation results.
            validation_df: Validation findings.
            tq_df: Technical queries.
            hardware_df: Hardware utilisation summary.
            config_df: Current rule configuration as a two-column DataFrame
                       (``Rule`` / ``Value``).

        Returns:
            A :class:`~io.BytesIO` buffer containing the .xlsx file.
        """
        wb = openpyxl.Workbook()
        # Remove the default sheet created by openpyxl
        wb.remove(wb.active)

        self._write_df_to_sheet(wb, allocation_df, 'IO_Allocation',
                                status_col='Status', status_map=_STATUS_FILLS)
        self._write_df_to_sheet(wb, validation_df, 'Validation_Report',
                                status_col='Severity', status_map=_SEVERITY_FILLS)
        self._write_df_to_sheet(wb, tq_df, 'Technical_Queries',
                                status_col='Severity', status_map=_SEVERITY_FILLS)
        self._write_df_to_sheet(wb, hardware_df, 'Hardware_Summary')
        self._write_df_to_sheet(wb, config_df, 'Configuration')

        return self._workbook_to_buffer(wb)

    def export_tq_report(self, tq_df: pd.DataFrame) -> BytesIO:
        """Export a standalone Technical Queries workbook.

        Args:
            tq_df: DataFrame of technical queries.

        Returns:
            BytesIO buffer with .xlsx content.
        """
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        self._write_df_to_sheet(wb, tq_df, 'Technical_Queries',
                                status_col='Severity', status_map=_SEVERITY_FILLS)
        return self._workbook_to_buffer(wb)

    def export_revision_report(self, revision_df: pd.DataFrame) -> BytesIO:
        """Export a revision comparison workbook.

        The *revision_df* is expected to contain a ``Change_Type`` column with
        values like ``added``, ``deleted``, ``modified``, ``unchanged``.

        Args:
            revision_df: DataFrame showing revision differences.

        Returns:
            BytesIO buffer with .xlsx content.
        """
        change_fills: Dict[str, PatternFill] = {
            'added': SUCCESS_FILL,
            'deleted': ERROR_FILL,
            'modified': WARNING_FILL,
            'unchanged': PatternFill(),  # no fill
        }

        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        self._write_df_to_sheet(wb, revision_df, 'Revision_Comparison',
                                status_col='Change_Type', status_map=change_fills)
        return self._workbook_to_buffer(wb)

    def export_proposed_revision(
        self,
        allocation_df: pd.DataFrame,
        validation_df: pd.DataFrame,
        tq_df: pd.DataFrame,
        hardware_df: pd.DataFrame,
        config_df: pd.DataFrame,
        change_summary_df: pd.DataFrame,
        approved_rules_df: pd.DataFrame,
        comparison_df: Optional[pd.DataFrame] = None,
        is_fully_valid: bool = False,
        is_diagnostic: bool = False,
    ) -> BytesIO:
        """Export a clearly labelled proposed-revision workbook.

        Never overwrites the original upload. Extends the standard allocation
        export with change summary, approved rule deltas, and optional
        allocation comparison.

        Args:
            allocation_df: Proposed hardware assignments.
            validation_df: Validation findings for the proposed allocation.
            tq_df: Technical queries / unresolved issues.
            hardware_df: Hardware utilisation summary.
            config_df: Approved (proposed) rule configuration.
            change_summary_df: High-level change summary rows.
            approved_rules_df: Old vs new values for approved rule changes.
            comparison_df: Optional original-vs-proposed allocation comparison.
            is_fully_valid: True when all hard constraints are satisfied.
            is_diagnostic: True when exporting a labelled diagnostic (not a
                successful revision).

        Returns:
            BytesIO buffer with .xlsx content.
        """
        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        banner_rows = [
            {
                'Field': 'Document_Type',
                'Value': (
                    'DIAGNOSTIC_REPORT'
                    if is_diagnostic
                    else 'PROPOSED_REVISION_REQUIRING_ENGINEERING_REVIEW'
                ),
            },
            {
                'Field': 'Allocation_Status',
                'Value': 'FULLY_VALID' if is_fully_valid else 'UNRESOLVED_ISSUES_REMAIN',
            },
            {
                'Field': 'Disclaimer',
                'Value': (
                    'This workbook is an engineering-assistance prototype output. '
                    'Generated allocations require review by a qualified engineer. '
                    'The original uploaded file was not modified.'
                ),
            },
        ]
        self._write_df_to_sheet(wb, pd.DataFrame(banner_rows), 'Revision_Banner')

        self._write_df_to_sheet(
            wb, allocation_df, 'IO_Allocation',
            status_col='Status', status_map=_STATUS_FILLS,
        )
        self._write_df_to_sheet(
            wb, validation_df, 'Validation_Report',
            status_col='Severity', status_map=_SEVERITY_FILLS,
        )
        self._write_df_to_sheet(
            wb, tq_df, 'Technical_Queries',
            status_col='Severity', status_map=_SEVERITY_FILLS,
        )
        self._write_df_to_sheet(wb, hardware_df, 'Hardware_Summary')
        self._write_df_to_sheet(wb, config_df, 'Approved_Configuration')
        self._write_df_to_sheet(wb, change_summary_df, 'Change_Summary')
        self._write_df_to_sheet(wb, approved_rules_df, 'Approved_Rule_Changes')
        if comparison_df is not None and not comparison_df.empty:
            change_fills: Dict[str, PatternFill] = {
                'added': SUCCESS_FILL,
                'deleted': ERROR_FILL,
                'modified': WARNING_FILL,
                'reassigned': WARNING_FILL,
                'unchanged': PatternFill(),
            }
            self._write_df_to_sheet(
                wb, comparison_df, 'Allocation_Comparison',
                status_col='Change_Type', status_map=change_fills,
            )

        return self._workbook_to_buffer(wb)
