"""Post-allocation rule validation engine.

Validates a completed allocation against all enabled rules,
independently of the allocation algorithm.
"""
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class RuleValidationFinding:
    """A finding produced by the post-allocation rule validator.

    Attributes:
        finding_id: Unique identifier in the form ``VAL-XXXX``.
        severity: One of ``'error'``, ``'warning'``, ``'info'``.
        rule_name: Short name of the rule that was violated.
        affected_item: The signal tag, hardware ID, or descriptive label.
        explanation: Human-readable description of the violation.
        suggested_action: Recommended fix.
    """
    finding_id: str
    severity: str
    rule_name: str
    affected_item: str
    explanation: str
    suggested_action: str


class RuleValidator:
    """Validates a completed :class:`AllocationResult` against all enabled rules.

    The validator is independent of the allocation algorithm and can be used
    as a post-hoc audit.
    """

    def __init__(self, rules: dict) -> None:
        """Initialise the validator with the allocation rule set.

        Args:
            rules: The same rules dict used by the
                :class:`~core.allocation_engine.AllocationEngine`.  Expected
                keys include ``charms_per_baseplate``, ``baseplates_per_cioc``,
                ``ciocs_per_cabinet``, ``enforce_segregation``,
                ``keep_cables_together``, ``reserve_spare_capacity``,
                ``spare_baseplates_per_cioc``, ``spare_percentage``.
        """
        self._rules = dict(rules)
        self._finding_seq: int = 1

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_id(self) -> str:
        fid = f'VAL-{self._finding_seq:04d}'
        self._finding_seq += 1
        return fid

    def _add(
        self,
        findings: list,
        severity: str,
        rule_name: str,
        affected_item: str,
        explanation: str,
        suggested_action: str,
    ) -> None:
        findings.append(RuleValidationFinding(
            finding_id=self._make_id(),
            severity=severity,
            rule_name=rule_name,
            affected_item=affected_item,
            explanation=explanation,
            suggested_action=suggested_action,
        ))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, allocation_result) -> List[RuleValidationFinding]:
        """Run ALL validation checks against a completed allocation result.

        The *allocation_result* object is expected to expose the attributes
        defined by :class:`~core.allocation_engine.AllocationResult`:
        ``signals``, ``allocated_signals``, ``unallocated_signals``,
        ``cabinets``, ``tq_items``, ``warnings``, ``statistics``.

        Returns:
            A list of :class:`RuleValidationFinding` objects.
        """
        self._finding_seq = 1
        findings: List[RuleValidationFinding] = []

        ar = allocation_result

        self._check_all_signals_accounted(findings, ar)
        self._check_no_duplicate_allocations(findings, ar)
        self._check_no_double_booked_slots(findings, ar)
        self._check_baseplate_capacity(findings, ar)
        self._check_cioc_capacity(findings, ar)
        self._check_cabinet_capacity(findings, ar)
        self._check_segregation(findings, ar)
        self._check_charm_type_mapping(findings, ar)
        self._check_terminal_block_mapping(findings, ar)
        self._check_naming_uniqueness(findings, ar)
        self._check_cable_grouping(findings, ar)
        self._check_spare_capacity(findings, ar)

        return findings

    def generate_summary(self, findings: List[RuleValidationFinding]) -> dict:
        """Produce a summary of findings grouped by severity.

        Args:
            findings: The list of findings to summarise.

        Returns:
            A dict with ``total``, ``by_severity``, and ``by_rule`` counts.
        """
        by_severity: dict[str, int] = {}
        by_rule: dict[str, int] = {}

        for f in findings:
            by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
            by_rule[f.rule_name] = by_rule.get(f.rule_name, 0) + 1

        return {
            'total': len(findings),
            'by_severity': by_severity,
            'by_rule': by_rule,
            'pass': by_severity.get('error', 0) == 0,
        }

    # ------------------------------------------------------------------
    # Individual rule checks
    # ------------------------------------------------------------------

    def _check_all_signals_accounted(self, findings: list, ar) -> None:
        """Rule 1: Every input signal must be in allocated OR unallocated."""
        input_tags = {s.tag for s in ar.signals}
        allocated_tags = {entry['signal'].tag for entry in ar.allocated_signals}
        unallocated_tags = {s.tag for s in ar.unallocated_signals}
        accounted = allocated_tags | unallocated_tags

        missing = input_tags - accounted
        for tag in sorted(missing):
            self._add(findings, 'error', 'signal_accounting',
                      tag,
                      f"Signal '{tag}' is neither allocated nor unallocated – it was silently dropped.",
                      'Review the allocation algorithm to ensure every signal is tracked.')

    def _check_no_duplicate_allocations(self, findings: list, ar) -> None:
        """Rule 2: No signal tag should appear twice in allocated list."""
        seen: dict[str, int] = {}
        for i, entry in enumerate(ar.allocated_signals):
            tag = entry['signal'].tag
            if tag in seen:
                self._add(findings, 'error', 'duplicate_allocation',
                          tag,
                          f"Signal '{tag}' allocated more than once (indices {seen[tag]} and {i}).",
                          'Ensure each signal is placed in exactly one CHARM slot.')
            else:
                seen[tag] = i

    def _check_no_double_booked_slots(self, findings: list, ar) -> None:
        """Rule 3: No CHARM slot should hold more than one signal."""
        slot_signals: dict[str, list[str]] = {}
        for entry in ar.allocated_signals:
            slot_id = entry['charm_slot'].charm_id
            tag = entry['signal'].tag
            slot_signals.setdefault(slot_id, []).append(tag)

        for slot_id, tags in slot_signals.items():
            if len(tags) > 1:
                self._add(findings, 'error', 'double_booked_slot',
                          slot_id,
                          f"CHARM slot '{slot_id}' has {len(tags)} signals: {tags}.",
                          'Each CHARM slot may hold only one signal.')

    def _check_baseplate_capacity(self, findings: list, ar) -> None:
        """Rule 4: No baseplate may exceed its CHARM capacity."""
        max_charms = self._rules.get('charms_per_baseplate', 12)
        for cab in ar.cabinets:
            for cioc in cab.ciocs:
                for bp in cioc.baseplates:
                    if len(bp.charms) > max_charms:
                        self._add(findings, 'error', 'baseplate_capacity',
                                  bp.baseplate_id,
                                  f"Baseplate '{bp.baseplate_id}' has {len(bp.charms)} CHARMs "
                                  f"(max {max_charms}).",
                                  'Reduce CHARM count or add another baseplate.')

    def _check_cioc_capacity(self, findings: list, ar) -> None:
        """Rule 5: No CIOC may exceed its baseplate capacity."""
        max_bp = self._rules.get('baseplates_per_cioc', 8)
        for cab in ar.cabinets:
            for cioc in cab.ciocs:
                if len(cioc.baseplates) > max_bp:
                    self._add(findings, 'error', 'cioc_capacity',
                              cioc.cioc_id,
                              f"CIOC '{cioc.cioc_id}' has {len(cioc.baseplates)} baseplates "
                              f"(max {max_bp}).",
                              'Reduce baseplate count or add another CIOC.')

    def _check_cabinet_capacity(self, findings: list, ar) -> None:
        """Rule 6: No cabinet may exceed its CIOC capacity."""
        max_ciocs = self._rules.get('ciocs_per_cabinet', 4)
        for cab in ar.cabinets:
            if len(cab.ciocs) > max_ciocs:
                self._add(findings, 'error', 'cabinet_capacity',
                          cab.cabinet_id,
                          f"Cabinet '{cab.cabinet_id}' has {len(cab.ciocs)} CIOCs "
                          f"(max {max_ciocs}).",
                          'Reduce CIOC count or add another cabinet.')

    def _check_segregation(self, findings: list, ar) -> None:
        """Rule 7: When segregation is enabled, A and B must be on different CIOCs."""
        if not self._rules.get('enforce_segregation', True):
            return

        for cab in ar.cabinets:
            for cioc in cab.ciocs:
                seg_classes_in_cioc: set[str] = set()
                for bp in cioc.baseplates:
                    for charm in bp.charms:
                        if charm.signal is not None:
                            seg = charm.signal.segregation.strip().upper()
                            if seg:
                                seg_classes_in_cioc.add(seg)
                if len(seg_classes_in_cioc) > 1:
                    self._add(findings, 'error', 'segregation',
                              cioc.cioc_id,
                              f"CIOC '{cioc.cioc_id}' contains signals from multiple "
                              f"segregation classes: {sorted(seg_classes_in_cioc)}.",
                              'Segregation A and B signals must be placed on separate CIOCs.')

    def _check_charm_type_mapping(self, findings: list, ar) -> None:
        """Rule 8: Signal IO type must be compatible with assigned CHARM type."""
        # Build a rough expected-CHARM lookup
        expected = {
            'AI': 'AI CHARM',
            'AO': 'AO CHARM',
            'DI': 'DI CHARM',
            'DO': 'DO CHARM',
        }
        for entry in ar.allocated_signals:
            sig = entry['signal']
            charm_slot = entry['charm_slot']
            io_base = sig.io_type.strip().upper().split('_')[0] if sig.io_type else ''
            expected_prefix = expected.get(io_base, '')
            if expected_prefix and expected_prefix not in sig.charm_type:
                self._add(findings, 'error', 'charm_type_mapping',
                          sig.tag,
                          f"Signal '{sig.tag}' (IO={sig.io_type}) is classified as "
                          f"'{sig.charm_type}' which does not match expected '{expected_prefix}'.",
                          'Review the signal classification mapping.')

    def _check_terminal_block_mapping(self, findings: list, ar) -> None:
        """Rule 9: Terminal block assignment should be plausible."""
        valid_tbs = {'Standard', 'Fused-injected-power', 'Relay output'}
        for entry in ar.allocated_signals:
            sig = entry['signal']
            tb = sig.terminal_block.strip() if sig.terminal_block else ''
            if tb and tb not in valid_tbs:
                self._add(findings, 'warning', 'terminal_block_mapping',
                          sig.tag,
                          f"Signal '{sig.tag}' has terminal block '{tb}' "
                          f"which is not in the standard set: {sorted(valid_tbs)}.",
                          'Verify the terminal block classification.')

    def _check_naming_uniqueness(self, findings: list, ar) -> None:
        """Rule 10: All hardware IDs must be unique."""
        all_ids: dict[str, str] = {}  # id -> type

        for cab in ar.cabinets:
            for label, name in [
                ('cabinet', cab.cabinet_id),
                ('controller', cab.controller_id),
                ('marshalling', cab.marshalling_id),
            ]:
                if name:
                    if name in all_ids:
                        self._add(findings, 'error', 'naming_uniqueness',
                                  name,
                                  f"Duplicate hardware ID '{name}' (type={label}, "
                                  f"conflicts with {all_ids[name]}).",
                                  'Ensure all hardware identifiers are unique.')
                    else:
                        all_ids[name] = label

            for cioc in cab.ciocs:
                if cioc.cioc_id in all_ids:
                    self._add(findings, 'error', 'naming_uniqueness',
                              cioc.cioc_id,
                              f"Duplicate CIOC ID '{cioc.cioc_id}'.",
                              'Ensure all CIOC IDs are unique.')
                else:
                    all_ids[cioc.cioc_id] = 'cioc'

                for bp in cioc.baseplates:
                    if bp.baseplate_id in all_ids:
                        self._add(findings, 'error', 'naming_uniqueness',
                                  bp.baseplate_id,
                                  f"Duplicate baseplate ID '{bp.baseplate_id}'.",
                                  'Ensure all baseplate IDs are unique.')
                    else:
                        all_ids[bp.baseplate_id] = 'baseplate'

                    for charm in bp.charms:
                        if charm.charm_id in all_ids:
                            self._add(findings, 'error', 'naming_uniqueness',
                                      charm.charm_id,
                                      f"Duplicate CHARM ID '{charm.charm_id}'.",
                                      'Ensure all CHARM IDs are unique.')
                        else:
                            all_ids[charm.charm_id] = 'charm'

    def _check_cable_grouping(self, findings: list, ar) -> None:
        """Rule 11: When enabled, signals from the same cable should be on the same baseplate."""
        if not self._rules.get('keep_cables_together', True):
            return

        # Build cable -> set of baseplate IDs
        cable_baseplates: dict[str, set[str]] = {}
        for entry in ar.allocated_signals:
            sig = entry['signal']
            cable = sig.cable.strip() if sig.cable else ''
            if not cable:
                continue
            bp_id = entry['charm_slot'].baseplate_id
            cable_baseplates.setdefault(cable, set()).add(bp_id)

        for cable, bps in cable_baseplates.items():
            if len(bps) > 1:
                # This is a warning, not an error – large cables may legitimately
                # span baseplates.
                self._add(findings, 'warning', 'cable_grouping',
                          cable,
                          f"Cable '{cable}' is spread across {len(bps)} baseplates: "
                          f"{sorted(bps)}.",
                          'Consider rearranging to keep cable signals together where possible.')

    def _check_spare_capacity(self, findings: list, ar) -> None:
        """Rule 12: When spare capacity is enabled, verify spare slots exist."""
        if not self._rules.get('reserve_spare_capacity', False):
            return

        spare_pct = self._rules.get('spare_percentage', 0.0)
        spare_bp_per_cioc = self._rules.get('spare_baseplates_per_cioc', 0)

        for cab in ar.cabinets:
            for cioc in cab.ciocs:
                # Check spare baseplates
                spare_bps = sum(1 for bp in cioc.baseplates if bp.is_spare)
                if spare_bps < spare_bp_per_cioc:
                    self._add(findings, 'warning', 'spare_capacity',
                              cioc.cioc_id,
                              f"CIOC '{cioc.cioc_id}' has {spare_bps} spare baseplates "
                              f"(expected {spare_bp_per_cioc}).",
                              'Add spare baseplates to meet the spare capacity rule.')

                # Check spare percentage on non-spare baseplates
                if spare_pct > 0:
                    for bp in cioc.baseplates:
                        if bp.is_spare:
                            continue
                        total = len(bp.charms)
                        if total == 0:
                            continue
                        spare_count = sum(1 for c in bp.charms if c.is_spare)
                        actual_pct = (spare_count / total) * 100
                        if actual_pct < spare_pct - 0.01:  # small tolerance
                            self._add(
                                findings, 'warning', 'spare_capacity',
                                bp.baseplate_id,
                                f"Baseplate '{bp.baseplate_id}' has {actual_pct:.1f}% spare "
                                f"capacity (target {spare_pct:.1f}%).",
                                'Mark additional CHARM slots as spare.',
                            )
