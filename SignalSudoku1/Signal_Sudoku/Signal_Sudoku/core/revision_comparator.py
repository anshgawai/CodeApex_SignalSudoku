"""Revision comparison for Signal Sudoku.

Compares two revisions of an I/O MDB to identify changes
and preserve existing allocations where feasible.
"""
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import copy


@dataclass
class SignalChange:
    """Describes what happened to a single signal between two revisions.

    Attributes:
        tag: The signal tag.
        change_type: One of ``'added'``, ``'deleted'``, ``'modified'``,
            ``'unchanged'``.
        changed_fields: For ``'modified'`` signals, a dict mapping field names
            to ``(old_value, new_value)`` tuples.
        previous_allocation: Hardware assignment dict from revision A, if
            available.
        allocation_preserved: ``True`` when the previous allocation is still
            valid in the new revision.
        move_reason: Explanation when a previous allocation cannot be preserved.
    """
    tag: str
    change_type: str
    changed_fields: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    previous_allocation: Optional[dict] = None
    allocation_preserved: bool = False
    move_reason: str = ''


@dataclass
class RevisionResult:
    """Aggregated result of comparing two I/O MDB revisions.

    Attributes:
        added: Signals present only in rev B.
        deleted: Signals present only in rev A.
        modified: Signals present in both but with field changes.
        unchanged: Signals identical in both revisions.
        summary: High-level statistics dict.
    """
    added: List[SignalChange]
    deleted: List[SignalChange]
    modified: List[SignalChange]
    unchanged: List[SignalChange]
    summary: dict


class RevisionComparator:
    """Compares two revisions of an I/O MDB and optionally preserves allocations.

    The comparator matches signals across revisions using the ``Tag`` column
    and then compares a configurable set of fields.
    """

    # Default set of fields to compare between revisions
    DEFAULT_COMPARE_FIELDS = ['IO', 'Cable', 'Pair', 'Grp', 'Seg']

    # Fields whose change invalidates an existing allocation
    _ALLOCATION_BREAKING_FIELDS = {'IO', 'Seg'}

    def compare(
        self,
        rev_a: pd.DataFrame,
        rev_b: pd.DataFrame,
        compare_fields: Optional[list] = None,
    ) -> RevisionResult:
        """Compare two I/O MDB revisions.

        Signals are matched by their ``Tag`` column.  For each tag present in
        either revision the comparator determines whether the signal was added,
        deleted, modified, or left unchanged.

        Args:
            rev_a: The earlier revision DataFrame.
            rev_b: The later revision DataFrame.
            compare_fields: Optional list of column names to compare.  Defaults
                to :attr:`DEFAULT_COMPARE_FIELDS`.

        Returns:
            A :class:`RevisionResult` containing categorised changes and a
            summary dict.
        """
        if compare_fields is None:
            compare_fields = list(self.DEFAULT_COMPARE_FIELDS)

        # Normalise inputs
        a = self._normalise(rev_a)
        b = self._normalise(rev_b)

        # Build tag-indexed dicts
        a_dict = self._df_to_tag_dict(a, compare_fields)
        b_dict = self._df_to_tag_dict(b, compare_fields)

        a_tags = set(a_dict.keys())
        b_tags = set(b_dict.keys())

        added: List[SignalChange] = []
        deleted: List[SignalChange] = []
        modified: List[SignalChange] = []
        unchanged: List[SignalChange] = []

        # Added signals (in B but not in A)
        for tag in sorted(b_tags - a_tags):
            added.append(SignalChange(tag=tag, change_type='added'))

        # Deleted signals (in A but not in B)
        for tag in sorted(a_tags - b_tags):
            deleted.append(SignalChange(tag=tag, change_type='deleted'))

        # Common signals – check for modifications
        for tag in sorted(a_tags & b_tags):
            changes: Dict[str, Tuple[str, str]] = {}
            for fld in compare_fields:
                old_val = str(a_dict[tag].get(fld, ''))
                new_val = str(b_dict[tag].get(fld, ''))
                if old_val != new_val:
                    changes[fld] = (old_val, new_val)

            if changes:
                modified.append(SignalChange(
                    tag=tag,
                    change_type='modified',
                    changed_fields=changes,
                ))
            else:
                unchanged.append(SignalChange(
                    tag=tag,
                    change_type='unchanged',
                ))

        summary = {
            'total_rev_a': len(a_tags),
            'total_rev_b': len(b_tags),
            'added': len(added),
            'deleted': len(deleted),
            'modified': len(modified),
            'unchanged': len(unchanged),
            'compare_fields': compare_fields,
        }

        return RevisionResult(
            added=added,
            deleted=deleted,
            modified=modified,
            unchanged=unchanged,
            summary=summary,
        )

    def compare_allocations(
        self,
        original_allocation_df: pd.DataFrame,
        proposed_allocation_df: pd.DataFrame,
        source_fields: Optional[list] = None,
        hardware_fields: Optional[list] = None,
    ) -> RevisionResult:
        """Compare original vs proposed allocation tables.

        Distinguishes:
        - **source_data** changes (IO/Cable/Pair/Grp/Seg) from
        - **hardware_assignment** changes (Cabinet/CIOC/Baseplate/CHARM/Status)

        A signal whose source fields are identical but whose CHARM slot moved
        is reported as ``modified`` with only hardware fields in
        ``changed_fields`` (never mislabelled as source-data change).

        Args:
            original_allocation_df: Allocation table from the first run.
            proposed_allocation_df: Allocation table from the proposed revision.
            source_fields: Signal property columns to compare.
            hardware_fields: Hardware assignment columns to compare.

        Returns:
            A :class:`RevisionResult` with field-level deltas.
        """
        if source_fields is None:
            source_fields = ['IO', 'Cable', 'Pair', 'Group', 'Segregation']
        if hardware_fields is None:
            hardware_fields = ['Cabinet', 'CIOC', 'Baseplate', 'CHARM', 'Status']

        compare_fields = list(source_fields) + list(hardware_fields)
        a = self._normalise_allocation_df(original_allocation_df)
        b = self._normalise_allocation_df(proposed_allocation_df)
        a_dict = self._df_to_tag_dict(a, compare_fields)
        b_dict = self._df_to_tag_dict(b, compare_fields)

        a_tags = set(a_dict.keys())
        b_tags = set(b_dict.keys())

        added: List[SignalChange] = []
        deleted: List[SignalChange] = []
        modified: List[SignalChange] = []
        unchanged: List[SignalChange] = []

        for tag in sorted(b_tags - a_tags):
            added.append(SignalChange(tag=tag, change_type='added'))

        for tag in sorted(a_tags - b_tags):
            deleted.append(SignalChange(tag=tag, change_type='deleted'))

        reassigned = 0
        source_modified = 0

        for tag in sorted(a_tags & b_tags):
            changes: Dict[str, Tuple[str, str]] = {}
            for fld in compare_fields:
                old_val = str(a_dict[tag].get(fld, ''))
                new_val = str(b_dict[tag].get(fld, ''))
                if old_val != new_val:
                    changes[fld] = (old_val, new_val)

            if not changes:
                unchanged.append(SignalChange(tag=tag, change_type='unchanged'))
                continue

            source_changed = {k: v for k, v in changes.items() if k in source_fields}
            hardware_changed = {k: v for k, v in changes.items() if k in hardware_fields}
            if source_changed:
                source_modified += 1
            if hardware_changed and not source_changed:
                reassigned += 1
            elif hardware_changed:
                reassigned += 1

            reason_parts = []
            if source_changed:
                reason_parts.append(
                    'Source data changed: ' + ', '.join(sorted(source_changed))
                )
            if hardware_changed:
                reason_parts.append(
                    'Hardware assignment changed: ' + ', '.join(sorted(hardware_changed))
                )

            modified.append(SignalChange(
                tag=tag,
                change_type='modified',
                changed_fields=changes,
                move_reason='; '.join(reason_parts),
            ))

        summary = {
            'total_original': len(a_tags),
            'total_proposed': len(b_tags),
            'added': len(added),
            'deleted': len(deleted),
            'modified': len(modified),
            'unchanged': len(unchanged),
            'source_data_modified': source_modified,
            'hardware_reassigned': reassigned,
            'source_fields': source_fields,
            'hardware_fields': hardware_fields,
            'compare_kind': 'allocation',
        }

        return RevisionResult(
            added=added,
            deleted=deleted,
            modified=modified,
            unchanged=unchanged,
            summary=summary,
        )

    @staticmethod
    def _normalise_allocation_df(df: pd.DataFrame) -> pd.DataFrame:
        """Normalise allocation-table column aliases."""
        ndf = df.copy()
        col_map = {}
        for col in ndf.columns:
            stripped = str(col).strip()
            upper = stripped.upper()
            if upper in ('TAG', 'TAGNAME', 'TAG_NAME'):
                col_map[col] = 'Tag'
            elif upper in ('IO', 'I/O', 'IO_TYPE', 'IOTYPE', 'TYPE'):
                col_map[col] = 'IO'
            elif upper in ('CABLE', 'CABLE_NO'):
                col_map[col] = 'Cable'
            elif upper in ('PAIR', 'PAIR_NO'):
                col_map[col] = 'Pair'
            elif upper in ('GRP', 'GROUP'):
                col_map[col] = 'Group'
            elif upper in ('SEG', 'SEGREGATION', 'SEGREGATION_CLASS'):
                col_map[col] = 'Segregation'
            elif upper == 'CABINET':
                col_map[col] = 'Cabinet'
            elif upper == 'CIOC':
                col_map[col] = 'CIOC'
            elif upper == 'BASEPLATE':
                col_map[col] = 'Baseplate'
            elif upper in ('CHARM', 'CHARM_ID', 'CHARM SLOT'):
                col_map[col] = 'CHARM'
            elif upper == 'STATUS':
                col_map[col] = 'Status'
            else:
                col_map[col] = stripped
        ndf.rename(columns=col_map, inplace=True)
        for col in ndf.columns:
            if ndf[col].dtype == object:
                ndf[col] = ndf[col].apply(
                    lambda v: v.strip() if isinstance(v, str) else v
                )
        return ndf

    def preserve_allocations(
        self,
        revision_result: RevisionResult,
        previous_allocation: dict,
    ) -> RevisionResult:
        """Attempt to carry forward hardware allocations from the previous revision.

        For each signal in *revision_result*, the method checks whether the
        signal's previous hardware assignment (stored in *previous_allocation*)
        can be preserved.

        - **Unchanged** signals: allocation is always preserved.
        - **Modified** signals: allocation is preserved only if the changed
          fields do not include IO type or segregation class (fields in
          :attr:`_ALLOCATION_BREAKING_FIELDS`).
        - **Added** signals: no previous allocation exists.
        - **Deleted** signals: previous allocation is recorded but flagged as
          not preserved.

        Args:
            revision_result: The comparison result from :meth:`compare`.
            previous_allocation: A dict mapping signal tags to their hardware
                assignment dicts (e.g.
                ``{'TAG-001': {'cabinet': '...', 'cioc': '...', ...}}``).

        Returns:
            A new :class:`RevisionResult` with allocation preservation
            information filled in.  The original object is not mutated.
        """
        result = copy.deepcopy(revision_result)

        # Unchanged – always preserve
        for sc in result.unchanged:
            alloc = previous_allocation.get(sc.tag)
            if alloc is not None:
                sc.previous_allocation = copy.deepcopy(alloc)
                sc.allocation_preserved = True
            else:
                sc.allocation_preserved = False
                sc.move_reason = 'No previous allocation found.'

        # Modified – preserve only if changes are non-breaking
        for sc in result.modified:
            alloc = previous_allocation.get(sc.tag)
            if alloc is None:
                sc.allocation_preserved = False
                sc.move_reason = 'No previous allocation found.'
                continue

            sc.previous_allocation = copy.deepcopy(alloc)
            breaking = set(sc.changed_fields.keys()) & self._ALLOCATION_BREAKING_FIELDS
            if breaking:
                sc.allocation_preserved = False
                sc.move_reason = (
                    f"Allocation-breaking field(s) changed: {', '.join(sorted(breaking))}. "
                    f"Signal must be re-allocated."
                )
            else:
                sc.allocation_preserved = True

        # Deleted – record previous allocation but mark as not preserved
        for sc in result.deleted:
            alloc = previous_allocation.get(sc.tag)
            if alloc is not None:
                sc.previous_allocation = copy.deepcopy(alloc)
            sc.allocation_preserved = False
            sc.move_reason = 'Signal deleted in new revision.'

        # Added – no previous allocation
        for sc in result.added:
            sc.allocation_preserved = False
            sc.move_reason = 'New signal; no previous allocation.'

        # Update summary
        preserved_count = sum(
            1 for sc in (result.unchanged + result.modified) if sc.allocation_preserved
        )
        needs_realloc = sum(
            1 for sc in (result.unchanged + result.modified) if not sc.allocation_preserved
        )
        result.summary['allocations_preserved'] = preserved_count
        result.summary['allocations_need_reassignment'] = needs_realloc + len(result.added)
        result.summary['allocations_freed'] = len(result.deleted)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise(df: pd.DataFrame) -> pd.DataFrame:
        """Return a lightly normalised copy of the DataFrame."""
        ndf = df.copy()

        # Normalise column names
        col_map = {}
        for col in ndf.columns:
            stripped = str(col).strip()
            upper = stripped.upper()
            if upper in ('TAG', 'TAGNAME', 'TAG_NAME'):
                col_map[col] = 'Tag'
            elif upper in ('IO', 'I/O', 'IO_TYPE', 'IOTYPE', 'TYPE'):
                col_map[col] = 'IO'
            elif upper in ('CABLE', 'CABLE_NO'):
                col_map[col] = 'Cable'
            elif upper in ('PAIR', 'PAIR_NO'):
                col_map[col] = 'Pair'
            elif upper in ('GRP', 'GROUP'):
                col_map[col] = 'Grp'
            elif upper in ('SEG', 'SEGREGATION', 'SEGREGATION_CLASS'):
                col_map[col] = 'Seg'
            else:
                col_map[col] = stripped
        ndf.rename(columns=col_map, inplace=True)

        # Strip whitespace from string columns
        for col in ndf.columns:
            if ndf[col].dtype == object:
                ndf[col] = ndf[col].apply(lambda v: v.strip() if isinstance(v, str) else v)

        # Upper-case IO
        if 'IO' in ndf.columns:
            ndf['IO'] = ndf['IO'].apply(lambda v: v.upper() if isinstance(v, str) else v)

        return ndf

    @staticmethod
    def _df_to_tag_dict(df: pd.DataFrame, fields: list) -> dict:
        """Convert a DataFrame into a dict keyed by Tag.

        Each value is a dict of field -> value for the specified *fields*.
        If duplicate tags exist, the last row wins.
        """
        result: dict = {}
        if 'Tag' not in df.columns:
            return result

        for idx in range(len(df)):
            tag_val = df.at[idx, 'Tag']
            if pd.isna(tag_val) or str(tag_val).strip() == '':
                continue
            tag = str(tag_val).strip()
            row_data: dict = {}
            for fld in fields:
                if fld in df.columns:
                    val = df.at[idx, fld]
                    row_data[fld] = '' if pd.isna(val) else str(val).strip()
                else:
                    row_data[fld] = ''
            result[tag] = row_data

        return result
