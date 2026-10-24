"""Excel file reading service for Signal Sudoku.

Reads I/O MDB workbooks, handles column mapping,
and prepares data for validation and allocation.
"""
import pandas as pd
import openpyxl
from typing import List, Dict, Optional, Tuple, Any, Union
from pathlib import Path
from io import BytesIO


# Known column aliases: canonical_name -> list of acceptable aliases (lowercase, stripped)
KNOWN_COLUMNS: Dict[str, List[str]] = {
    'Tag': ['tag', 'tag number', 'tag_number', 'tagno', 'tag no', 'instrument tag'],
    'IO': ['io', 'i/o', 'io_type', 'signal type', 'signal_type', 'iotype', 'io type'],
    'Cable': ['cable', 'cable no', 'cable_no', 'cable_id', 'cable number', 'cable_number', 'cableno'],
    'Pair': ['pair', 'pair no', 'pair_no', 'pair number', 'pair_number', 'pairno'],
    'Grp': ['grp', 'group', 'logical group', 'logical_group', 'process group', 'grp_id'],
    'Seg': ['seg', 'segregation', 'seg class', 'seg_class', 'segregation class', 'segregation_class'],
}


class ExcelReader:
    """Service for reading and parsing I/O MDB Excel workbooks.

    Handles file path and BytesIO inputs, auto-detects column mappings,
    and provides preview/statistics for the Streamlit UI.
    """

    def get_sheet_names(self, file_path_or_buffer: Union[str, Path, BytesIO]) -> List[str]:
        """Return a list of sheet names in the workbook.

        Args:
            file_path_or_buffer: Path to the Excel file or a BytesIO buffer
                                 (e.g. from a Streamlit file uploader).

        Returns:
            List of sheet name strings.
        """
        if isinstance(file_path_or_buffer, BytesIO):
            file_path_or_buffer.seek(0)
        xl = pd.ExcelFile(file_path_or_buffer, engine='openpyxl')
        return xl.sheet_names

    def read_sheet(
        self,
        file_path_or_buffer: Union[str, Path, BytesIO],
        sheet_name: Optional[str] = None,
    ) -> pd.DataFrame:
        """Read the specified sheet (or the first sheet) into a DataFrame.

        Args:
            file_path_or_buffer: Path to the Excel file or a BytesIO buffer.
            sheet_name: Name of the sheet to read.  ``None`` reads the first
                        sheet.

        Returns:
            A pandas DataFrame with the sheet data.
        """
        if isinstance(file_path_or_buffer, BytesIO):
            file_path_or_buffer.seek(0)

        kwargs: Dict[str, Any] = {
            'engine': 'openpyxl',
            'dtype': str,  # read everything as strings initially to avoid data loss
        }
        if sheet_name is not None:
            kwargs['sheet_name'] = sheet_name
        else:
            kwargs['sheet_name'] = 0  # first sheet

        df = pd.read_excel(file_path_or_buffer, **kwargs)
        # Strip whitespace from column headers
        df.columns = [str(c).strip() for c in df.columns]
        return df

    def detect_columns(self, df: pd.DataFrame) -> Dict[str, str]:
        """Auto-detect column mapping by matching known column names.

        Matching is case-insensitive and whitespace-tolerant.

        Args:
            df: DataFrame whose columns should be inspected.

        Returns:
            Mapping of canonical column name → actual column name found in *df*.
            Only columns that were successfully matched are included.
        """
        mapping: Dict[str, str] = {}
        actual_columns = list(df.columns)

        for canonical, aliases in KNOWN_COLUMNS.items():
            for actual in actual_columns:
                normalised = actual.strip().lower().replace('_', ' ').replace('-', ' ')
                # Also try collapsing multiple spaces
                normalised_compact = ' '.join(normalised.split())
                for alias in aliases:
                    alias_norm = alias.strip().lower().replace('_', ' ').replace('-', ' ')
                    alias_compact = ' '.join(alias_norm.split())
                    if normalised_compact == alias_compact:
                        mapping[canonical] = actual
                        break
                if canonical in mapping:
                    break

        return mapping

    def apply_column_mapping(self, df: pd.DataFrame, mapping: Dict[str, str]) -> pd.DataFrame:
        """Rename columns based on a mapping dict, returning a new DataFrame.

        Args:
            df: Source DataFrame.
            mapping: ``{canonical_name: actual_column_name}`` as produced by
                     :py:meth:`detect_columns`.

        Returns:
            A *copy* of *df* with matched columns renamed to their canonical
            names.
        """
        # Build the inverse: actual -> canonical
        rename_map = {actual: canonical for canonical, actual in mapping.items()}
        return df.rename(columns=rename_map).copy()

    def get_preview(self, df: pd.DataFrame, n_rows: int = 20) -> pd.DataFrame:
        """Return the first *n_rows* of the DataFrame for UI preview.

        Args:
            df: Source DataFrame.
            n_rows: Number of rows to include (default 20).

        Returns:
            A DataFrame with at most *n_rows* rows.
        """
        return df.head(n_rows).copy()

    def get_statistics(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Compute summary statistics about the I/O data.

        Expects a DataFrame with canonical column names (i.e. after
        :py:meth:`apply_column_mapping` has been applied).

        Args:
            df: Source DataFrame with standardised column names.

        Returns:
            Dictionary with keys:
            - ``total_rows``: total number of rows
            - ``unique_tags``: number of unique non-null Tag values
            - ``signal_types``: dict mapping each IO type to its count
            - ``cables``: number of unique non-null Cable values
            - ``groups``: number of unique non-null Grp values
        """
        stats: Dict[str, Any] = {
            'total_rows': len(df),
            'unique_tags': 0,
            'signal_types': {},
            'cables': 0,
            'groups': 0,
        }

        if 'Tag' in df.columns:
            stats['unique_tags'] = int(df['Tag'].dropna().nunique())

        if 'IO' in df.columns:
            counts = df['IO'].dropna().value_counts()
            stats['signal_types'] = {str(k): int(v) for k, v in counts.items()}

        if 'Cable' in df.columns:
            stats['cables'] = int(df['Cable'].dropna().nunique())

        if 'Grp' in df.columns:
            stats['groups'] = int(df['Grp'].dropna().nunique())

        return stats
