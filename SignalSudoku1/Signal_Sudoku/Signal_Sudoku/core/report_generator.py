"""Report generation utilities for Signal Sudoku.

Prepares structured data for display and Excel export.
"""
import pandas as pd
from typing import List, Dict, Optional


class ReportGenerator:
    """Produces pandas DataFrames suitable for display or Excel export.

    All public methods return :class:`~pandas.DataFrame` objects whose columns
    are named consistently with the Signal Sudoku data model.
    """

    # ------------------------------------------------------------------
    # Allocation table
    # ------------------------------------------------------------------

    def generate_allocation_table(self, allocation_result) -> pd.DataFrame:
        """Create a flat allocation table from an AllocationResult.

        Each row represents a signal – both allocated and unallocated signals
        are included.

        Columns:
            Tag, IO, Cable, Pair, Group, Segregation, Cabinet, Controller,
            Marshalling, CIOC, Baseplate, CHARM, CHARM_Type, Terminal_Block,
            Status, Validation_Status, Notes

        Args:
            allocation_result: An
                :class:`~core.allocation_engine.AllocationResult`.

        Returns:
            A :class:`~pandas.DataFrame`.
        """
        rows: list[dict] = []

        # Allocated signals
        for entry in allocation_result.allocated_signals:
            sig = entry['signal']
            slot = entry['charm_slot']
            rows.append({
                'Tag': sig.tag,
                'IO': sig.io_type,
                'Cable': sig.cable,
                'Pair': sig.pair,
                'Group': sig.group,
                'Segregation': sig.segregation,
                'Cabinet': slot.cabinet_id,
                'Controller': self._controller_for_cabinet(
                    allocation_result.cabinets, slot.cabinet_id
                ),
                'Marshalling': self._marshalling_for_cabinet(
                    allocation_result.cabinets, slot.cabinet_id
                ),
                'CIOC': slot.cioc_id,
                'Baseplate': slot.baseplate_id,
                'CHARM': slot.charm_id,
                'CHARM_Type': sig.charm_type,
                'Terminal_Block': sig.terminal_block,
                'Status': 'Allocated',
                'Validation_Status': sig.classification_confidence,
                'Notes': sig.classification_notes,
            })

        # Unallocated signals
        for sig in allocation_result.unallocated_signals:
            rows.append({
                'Tag': sig.tag,
                'IO': sig.io_type,
                'Cable': sig.cable,
                'Pair': sig.pair,
                'Group': sig.group,
                'Segregation': sig.segregation,
                'Cabinet': '',
                'Controller': '',
                'Marshalling': '',
                'CIOC': '',
                'Baseplate': '',
                'CHARM': '',
                'CHARM_Type': sig.charm_type,
                'Terminal_Block': sig.terminal_block,
                'Status': 'Unallocated',
                'Validation_Status': sig.classification_confidence,
                'Notes': sig.classification_notes,
            })

        if not rows:
            return pd.DataFrame(columns=[
                'Tag', 'IO', 'Cable', 'Pair', 'Group', 'Segregation',
                'Cabinet', 'Controller', 'Marshalling', 'CIOC', 'Baseplate',
                'CHARM', 'CHARM_Type', 'Terminal_Block', 'Status',
                'Validation_Status', 'Notes',
            ])

        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Validation report
    # ------------------------------------------------------------------

    def generate_validation_report(self, findings: list) -> pd.DataFrame:
        """Create a flat table of validation findings.

        Args:
            findings: A list of objects with attributes ``finding_id``,
                ``severity``, ``category``, ``row``, ``field``, ``tag``,
                ``message``, ``suggestion``.

        Returns:
            A :class:`~pandas.DataFrame`.
        """
        rows: list[dict] = []
        for f in findings:
            rows.append({
                'Finding_ID': getattr(f, 'finding_id', ''),
                'Severity': getattr(f, 'severity', ''),
                'Category': getattr(f, 'category', getattr(f, 'rule_name', '')),
                'Row': getattr(f, 'row', None),
                'Field': getattr(f, 'field', getattr(f, 'affected_item', '')),
                'Tag': getattr(f, 'tag', ''),
                'Message': getattr(f, 'message', getattr(f, 'explanation', '')),
                'Suggestion': getattr(f, 'suggestion', getattr(f, 'suggested_action', '')),
            })

        if not rows:
            return pd.DataFrame(columns=[
                'Finding_ID', 'Severity', 'Category', 'Row', 'Field',
                'Tag', 'Message', 'Suggestion',
            ])

        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # TQ report
    # ------------------------------------------------------------------

    def generate_tq_report(self, tqs: list) -> pd.DataFrame:
        """Create a flat table of Technical Queries.

        Args:
            tqs: A list of :class:`~core.tq_generator.TechnicalQuery` objects.

        Returns:
            A :class:`~pandas.DataFrame`.
        """
        rows: list[dict] = []
        for tq in tqs:
            rows.append({
                'TQ_ID': tq.tq_id,
                'Affected_Item': tq.affected_item,
                'Category': tq.category,
                'Description': tq.description,
                'Reason': tq.reason,
                'Information_Needed': tq.information_needed,
                'Suggested_Action': tq.suggested_action,
                'Status': tq.status,
                'Priority': tq.priority,
                'Created_Date': tq.created_date,
            })

        if not rows:
            return pd.DataFrame(columns=[
                'TQ_ID', 'Affected_Item', 'Category', 'Description',
                'Reason', 'Information_Needed', 'Suggested_Action',
                'Status', 'Priority', 'Created_Date',
            ])

        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Hardware summary
    # ------------------------------------------------------------------

    def generate_hardware_summary(self, allocation_result) -> pd.DataFrame:
        """Create a hardware utilisation summary table.

        Each row represents one piece of hardware (cabinet, CIOC, or
        baseplate).

        Columns:
            Hardware_ID, Type, Parent, Capacity, Used, Available, Spare,
            Utilization_%

        Args:
            allocation_result: An
                :class:`~core.allocation_engine.AllocationResult`.

        Returns:
            A :class:`~pandas.DataFrame`.
        """
        rows: list[dict] = []

        for cab in allocation_result.cabinets:
            cab_capacity = cab.total_capacity
            cab_used = cab.used_slots
            rows.append({
                'Hardware_ID': cab.cabinet_id,
                'Type': 'Cabinet',
                'Parent': '',
                'Capacity': cab_capacity,
                'Used': cab_used,
                'Available': cab_capacity - cab_used,
                'Spare': 0,
                'Utilization_%': round(cab.utilization, 1),
            })

            for cioc in cab.ciocs:
                cioc_capacity = cioc.total_capacity
                cioc_used = cioc.used_slots
                rows.append({
                    'Hardware_ID': cioc.cioc_id,
                    'Type': 'CIOC',
                    'Parent': cab.cabinet_id,
                    'Capacity': cioc_capacity,
                    'Used': cioc_used,
                    'Available': cioc_capacity - cioc_used,
                    'Spare': 0,
                    'Utilization_%': round(cioc.utilization, 1),
                })

                for bp in cioc.baseplates:
                    spare_count = sum(1 for c in bp.charms if c.is_spare)
                    rows.append({
                        'Hardware_ID': bp.baseplate_id,
                        'Type': 'Baseplate (spare)' if bp.is_spare else 'Baseplate',
                        'Parent': cioc.cioc_id,
                        'Capacity': bp.capacity,
                        'Used': bp.used_slots,
                        'Available': bp.available_slots,
                        'Spare': spare_count,
                        'Utilization_%': round(bp.utilization, 1),
                    })

        if not rows:
            return pd.DataFrame(columns=[
                'Hardware_ID', 'Type', 'Parent', 'Capacity', 'Used',
                'Available', 'Spare', 'Utilization_%',
            ])

        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Configuration report
    # ------------------------------------------------------------------

    def generate_configuration_report(self, rules: dict) -> pd.DataFrame:
        """Create a table of current configuration / rule settings.

        Args:
            rules: The rules dict used for allocation.

        Returns:
            A :class:`~pandas.DataFrame` with columns ``Setting`` and
            ``Value``.
        """
        rows: list[dict] = []
        for key in sorted(rules.keys()):
            val = rules[key]
            # Represent NamingConfig objects as a readable string
            if hasattr(val, '__dataclass_fields__'):
                val_str = '; '.join(
                    f'{f}={getattr(val, f)}' for f in val.__dataclass_fields__
                )
            else:
                val_str = str(val)
            rows.append({'Setting': key, 'Value': val_str})

        if not rows:
            return pd.DataFrame(columns=['Setting', 'Value'])

        return pd.DataFrame(rows)

    def generate_allocation_comparison_report(self, revision_result) -> pd.DataFrame:
        """Flatten an allocation/MDB revision comparison into a DataFrame.

        Distinguishes source-data vs hardware changes via ``Change_Kind``.
        """
        rows: list[dict] = []
        source_fields = set(
            (revision_result.summary or {}).get(
                'source_fields', ['IO', 'Cable', 'Pair', 'Group', 'Segregation', 'Grp', 'Seg']
            )
        )
        hardware_fields = set(
            (revision_result.summary or {}).get(
                'hardware_fields',
                ['Cabinet', 'CIOC', 'Baseplate', 'CHARM', 'Status'],
            )
        )

        for kind, changes in [
            ('added', revision_result.added),
            ('deleted', revision_result.deleted),
            ('modified', revision_result.modified),
            ('unchanged', revision_result.unchanged),
        ]:
            for change in changes:
                changed = getattr(change, 'changed_fields', {}) or {}
                source_changed = {k: v for k, v in changed.items() if k in source_fields}
                hardware_changed = {k: v for k, v in changed.items() if k in hardware_fields}
                if kind == 'modified':
                    if source_changed and hardware_changed:
                        change_kind = 'source_and_hardware'
                    elif source_changed:
                        change_kind = 'source_data'
                    elif hardware_changed:
                        change_kind = 'hardware_reassignment'
                    else:
                        change_kind = 'modified'
                else:
                    change_kind = kind

                if changed:
                    for field_name, (old_v, new_v) in changed.items():
                        rows.append({
                            'Tag': change.tag,
                            'Change_Type': kind,
                            'Change_Kind': change_kind,
                            'Field': field_name,
                            'Original_Value': old_v,
                            'Proposed_Value': new_v,
                            'Reason': getattr(change, 'move_reason', ''),
                        })
                else:
                    rows.append({
                        'Tag': change.tag,
                        'Change_Type': kind,
                        'Change_Kind': change_kind,
                        'Field': '',
                        'Original_Value': '',
                        'Proposed_Value': '',
                        'Reason': getattr(change, 'move_reason', ''),
                    })

        if not rows:
            return pd.DataFrame(columns=[
                'Tag', 'Change_Type', 'Change_Kind', 'Field',
                'Original_Value', 'Proposed_Value', 'Reason',
            ])
        return pd.DataFrame(rows)

    def generate_change_summary_report(self, summary: dict) -> pd.DataFrame:
        """Two-column summary table from a dict."""
        rows = [{'Field': str(k), 'Value': str(v)} for k, v in summary.items()]
        if not rows:
            return pd.DataFrame(columns=['Field', 'Value'])
        return pd.DataFrame(rows)

    def generate_approved_rules_report(self, rows: list) -> pd.DataFrame:
        """Approved rule-change table from workflow row dicts."""
        if not rows:
            return pd.DataFrame(columns=[
                'Rule', 'Original_Value', 'Approved_Value',
                'Conflict_Resolved', 'Expected_Impact', 'Warnings',
            ])
        return pd.DataFrame(rows)

    def generate_problems_report(self, problems: list) -> pd.DataFrame:
        """Flatten detected problems for UI display."""
        rows = []
        for p in problems:
            rows.append({
                'Problem_ID': getattr(p, 'problem_id', ''),
                'Severity': getattr(p, 'severity', ''),
                'Classification': getattr(p, 'classification', ''),
                'Category': getattr(p, 'category', ''),
                'Affected_Item': getattr(p, 'affected_item', ''),
                'Explanation': getattr(p, 'explanation', ''),
                'Suggested_Action': getattr(p, 'suggested_action', ''),
                'Related_Rule': getattr(p, 'related_rule', ''),
                'Can_Suggest_Rule_Change': getattr(p, 'can_suggest_rule_change', False),
            })
        if not rows:
            return pd.DataFrame(columns=[
                'Problem_ID', 'Severity', 'Classification', 'Category',
                'Affected_Item', 'Explanation', 'Suggested_Action',
                'Related_Rule', 'Can_Suggest_Rule_Change',
            ])
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _controller_for_cabinet(cabinets: list, cabinet_id: str) -> str:
        """Look up the controller ID for a given cabinet."""
        for cab in cabinets:
            if cab.cabinet_id == cabinet_id:
                return cab.controller_id
        return ''

    @staticmethod
    def _marshalling_for_cabinet(cabinets: list, cabinet_id: str) -> str:
        """Look up the marshalling ID for a given cabinet."""
        for cab in cabinets:
            if cab.cabinet_id == cabinet_id:
                return cab.marshalling_id
        return ''
