"""Input validation for Signal Sudoku.

Validates uploaded I/O MDB data for completeness, correctness,
and consistency before allocation.
"""
import pandas as pd
from dataclasses import dataclass
from typing import List, Optional, Tuple
import re


@dataclass
class ValidationFinding:
    """A single validation finding describing an issue in the input data.

    Attributes:
        finding_id: Unique identifier in the form ``INP-XXXX``.
        severity: One of ``'error'``, ``'warning'``, ``'info'``.
        category: Classification such as ``'missing_data'``, ``'duplicate'``,
            ``'invalid_value'``, ``'malformed'``, ``'completeness'``.
        row: 0-based row index in the input DataFrame, or *None* for global issues.
        field: The column / field name this finding relates to.
        tag: The signal tag associated with this finding.
        message: Human-readable description.
        suggestion: Optional recommended corrective action.
    """
    finding_id: str
    severity: str
    category: str
    row: Optional[int]
    field: str
    tag: str
    message: str
    suggestion: str = ''


class InputValidator:
    """Validates a raw I/O MDB DataFrame before allocation.

    Checks for missing required fields, duplicates, invalid values, and
    optional-but-recommended fields.
    """

    VALID_IO_TYPES = {'AI', 'AO', 'DI', 'DO'}
    REQUIRED_FIELDS = ['Tag', 'IO']
    OPTIONAL_FIELDS = ['Cable', 'Pair', 'Grp', 'Seg']

    # A pair value is considered well-formed if it is a positive integer,
    # or a short alphanumeric label.
    _PAIR_RE = re.compile(r'^[A-Za-z0-9]+$')

    def __init__(self) -> None:
        """Initialise the validator with a fresh finding counter."""
        self._finding_seq: int = 1

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_id(self) -> str:
        """Generate the next finding ID and advance the counter."""
        fid = f'INP-{self._finding_seq:04d}'
        self._finding_seq += 1
        return fid

    @staticmethod
    def _is_empty(value) -> bool:
        """Return *True* if a cell value is missing or blank."""
        if value is None:
            return True
        if isinstance(value, float) and pd.isna(value):
            return True
        if isinstance(value, str) and value.strip() == '':
            return True
        return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, df: pd.DataFrame) -> Tuple[List[ValidationFinding], bool]:
        """Run all validation checks on the input DataFrame.

        Args:
            df: The raw I/O MDB data.  Expected columns include at least
                ``Tag`` and ``IO``.  Column names are matched after
                normalisation (strip + title-case) so ``'tag'`` and ``' IO '``
                are accepted.

        Returns:
            A 2-tuple ``(findings, has_fatal_errors)`` where *findings* is the
            full list of :class:`ValidationFinding` objects and
            *has_fatal_errors* is ``True`` when at least one finding has
            severity ``'error'``.
        """
        # Reset counter for this validation run
        self._finding_seq = 1
        findings: List[ValidationFinding] = []

        if df is None or df.empty:
            findings.append(ValidationFinding(
                finding_id=self._make_id(),
                severity='error',
                category='missing_data',
                row=None,
                field='(all)',
                tag='',
                message='Input data is empty or None.',
                suggestion='Upload a valid I/O MDB file with at least one signal row.',
            ))
            return findings, True

        # Work on a normalised copy so we don't mutate the caller's frame
        ndf = self.normalize_dataframe(df.copy())

        # --- Check required columns exist ---
        for col in self.REQUIRED_FIELDS:
            if col not in ndf.columns:
                findings.append(ValidationFinding(
                    finding_id=self._make_id(),
                    severity='error',
                    category='missing_data',
                    row=None,
                    field=col,
                    tag='',
                    message=f"Required column '{col}' is missing from the input data.",
                    suggestion=f"Ensure the input file contains a '{col}' column.",
                ))

        # If critical columns are missing, we cannot proceed
        if any(f.severity == 'error' and f.category == 'missing_data' and f.row is None for f in findings):
            return findings, True

        # --- Row-level checks ---
        tags_seen: dict[str, int] = {}  # tag -> first row index

        for idx in range(len(ndf)):
            tag_val = ndf.at[idx, 'Tag'] if 'Tag' in ndf.columns else ''
            tag_str = '' if self._is_empty(tag_val) else str(tag_val).strip()

            # 1. Missing Tag (ERROR)
            if tag_str == '':
                findings.append(ValidationFinding(
                    finding_id=self._make_id(),
                    severity='error',
                    category='missing_data',
                    row=idx,
                    field='Tag',
                    tag='',
                    message=f'Row {idx}: Tag value is missing.',
                    suggestion='Every signal must have a unique Tag identifier.',
                ))
                # Use a placeholder for remaining checks on this row
                tag_str = f'<row {idx}>'
            else:
                # 2. Duplicate Tag (ERROR)
                if tag_str in tags_seen:
                    findings.append(ValidationFinding(
                        finding_id=self._make_id(),
                        severity='error',
                        category='duplicate',
                        row=idx,
                        field='Tag',
                        tag=tag_str,
                        message=f"Duplicate tag '{tag_str}' found at row {idx} (first seen at row {tags_seen[tag_str]}).",
                        suggestion='Remove or rename the duplicate tag.',
                    ))
                else:
                    tags_seen[tag_str] = idx

            # 3. Missing IO type (ERROR)
            io_val = ndf.at[idx, 'IO'] if 'IO' in ndf.columns else ''
            io_str = '' if self._is_empty(io_val) else str(io_val).strip().upper()

            if io_str == '':
                findings.append(ValidationFinding(
                    finding_id=self._make_id(),
                    severity='error',
                    category='missing_data',
                    row=idx,
                    field='IO',
                    tag=tag_str,
                    message=f"Row {idx}: IO type is missing for tag '{tag_str}'.",
                    suggestion="Provide the IO type (AI, AO, DI, or DO).",
                ))
            else:
                # 4. Invalid IO type (WARNING)
                base_io = io_str.split('_')[0] if '_' in io_str else io_str
                if base_io not in self.VALID_IO_TYPES:
                    findings.append(ValidationFinding(
                        finding_id=self._make_id(),
                        severity='warning',
                        category='invalid_value',
                        row=idx,
                        field='IO',
                        tag=tag_str,
                        message=f"Row {idx}: Unknown IO type '{io_str}' for tag '{tag_str}'.",
                        suggestion=f"Expected one of {sorted(self.VALID_IO_TYPES)}.",
                    ))

            # 5. Missing Cable (INFO)
            cable_val = ndf.at[idx, 'Cable'] if 'Cable' in ndf.columns else ''
            cable_str = '' if self._is_empty(cable_val) else str(cable_val).strip()

            if cable_str == '':
                findings.append(ValidationFinding(
                    finding_id=self._make_id(),
                    severity='info',
                    category='completeness',
                    row=idx,
                    field='Cable',
                    tag=tag_str,
                    message=f"Row {idx}: Cable value is missing for tag '{tag_str}'.",
                    suggestion='Providing cable information improves allocation grouping.',
                ))
            else:
                # 6. Missing Pair when Cable exists (INFO)
                pair_val = ndf.at[idx, 'Pair'] if 'Pair' in ndf.columns else ''
                pair_str = '' if self._is_empty(pair_val) else str(pair_val).strip()

                if pair_str == '':
                    findings.append(ValidationFinding(
                        finding_id=self._make_id(),
                        severity='info',
                        category='completeness',
                        row=idx,
                        field='Pair',
                        tag=tag_str,
                        message=f"Row {idx}: Pair value is missing for tag '{tag_str}' (cable '{cable_str}' specified).",
                        suggestion='Providing pair numbers helps maintain cable-pair ordering.',
                    ))
                else:
                    # 7. Malformed Pair number (WARNING)
                    if not self._PAIR_RE.match(pair_str):
                        findings.append(ValidationFinding(
                            finding_id=self._make_id(),
                            severity='warning',
                            category='malformed',
                            row=idx,
                            field='Pair',
                            tag=tag_str,
                            message=f"Row {idx}: Pair value '{pair_str}' for tag '{tag_str}' looks malformed.",
                            suggestion='Pair should be an alphanumeric value (e.g. 1, 2, A1).',
                        ))

            # 8. Missing Group (INFO)
            grp_val = ndf.at[idx, 'Grp'] if 'Grp' in ndf.columns else ''
            grp_str = '' if self._is_empty(grp_val) else str(grp_val).strip()

            if grp_str == '':
                findings.append(ValidationFinding(
                    finding_id=self._make_id(),
                    severity='info',
                    category='completeness',
                    row=idx,
                    field='Grp',
                    tag=tag_str,
                    message=f"Row {idx}: Group value is missing for tag '{tag_str}'.",
                    suggestion='Providing group information helps keep related signals together.',
                ))

            # 9. Missing Segregation (INFO)
            seg_val = ndf.at[idx, 'Seg'] if 'Seg' in ndf.columns else ''
            seg_str = '' if self._is_empty(seg_val) else str(seg_val).strip()

            if seg_str == '':
                findings.append(ValidationFinding(
                    finding_id=self._make_id(),
                    severity='info',
                    category='completeness',
                    row=idx,
                    field='Seg',
                    tag=tag_str,
                    message=f"Row {idx}: Segregation value is missing for tag '{tag_str}'.",
                    suggestion='Providing segregation class (A/B) is important when segregation is enforced.',
                ))

        has_fatal = any(f.severity == 'error' for f in findings)
        return findings, has_fatal

    def normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalise column names and cell values for consistent processing.

        * Column names are stripped of whitespace and title-cased, then mapped
          to the canonical short names (``Tag``, ``IO``, ``Cable``, ``Pair``,
          ``Grp``, ``Seg``).
        * String cell values are stripped of leading/trailing whitespace.
        * IO type values are upper-cased.

        Args:
            df: The raw DataFrame (will **not** be mutated; a copy is returned).

        Returns:
            A normalised copy of the DataFrame.
        """
        ndf = df.copy()

        # Normalise column names
        col_map = {}
        for col in ndf.columns:
            stripped = str(col).strip()
            upper = stripped.upper()
            # Map common variants
            if upper in ('TAG', 'TAGNAME', 'TAG_NAME', 'SIGNAL_TAG', 'SIGNALTAG'):
                col_map[col] = 'Tag'
            elif upper in ('IO', 'I/O', 'IO_TYPE', 'IOTYPE', 'TYPE'):
                col_map[col] = 'IO'
            elif upper in ('CABLE', 'CABLE_NO', 'CABLENO'):
                col_map[col] = 'Cable'
            elif upper in ('PAIR', 'PAIR_NO', 'PAIRNO'):
                col_map[col] = 'Pair'
            elif upper in ('GRP', 'GROUP', 'GRP_NO'):
                col_map[col] = 'Grp'
            elif upper in ('SEG', 'SEGREGATION', 'SEGREGATION_CLASS', 'SEG_CLASS'):
                col_map[col] = 'Seg'
            else:
                # Keep as title-cased stripped version
                col_map[col] = stripped.title() if stripped else col

        ndf.rename(columns=col_map, inplace=True)

        # Strip whitespace from string columns
        for col in ndf.columns:
            if ndf[col].dtype == object:
                ndf[col] = ndf[col].apply(
                    lambda v: v.strip() if isinstance(v, str) else v
                )

        # Upper-case IO values
        if 'IO' in ndf.columns:
            ndf['IO'] = ndf['IO'].apply(
                lambda v: v.upper() if isinstance(v, str) else v
            )

        # Ensure optional columns exist (fill with empty string)
        for col in self.OPTIONAL_FIELDS:
            if col not in ndf.columns:
                ndf[col] = ''

        # Reset index for consistent row numbering
        ndf.reset_index(drop=True, inplace=True)

        return ndf

    def generate_report(self, findings: List[ValidationFinding]) -> dict:
        """Produce a summary report from a list of validation findings.

        Args:
            findings: The findings to summarise.

        Returns:
            A dict with keys:

            - ``total``: total finding count
            - ``by_severity``: dict mapping severity to count
            - ``by_category``: dict mapping category to count
            - ``has_errors``: ``True`` if any error-severity findings exist
            - ``has_warnings``: ``True`` if any warning-severity findings exist
        """
        by_severity: dict[str, int] = {}
        by_category: dict[str, int] = {}

        for f in findings:
            by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
            by_category[f.category] = by_category.get(f.category, 0) + 1

        return {
            'total': len(findings),
            'by_severity': by_severity,
            'by_category': by_category,
            'has_errors': by_severity.get('error', 0) > 0,
            'has_warnings': by_severity.get('warning', 0) > 0,
        }
