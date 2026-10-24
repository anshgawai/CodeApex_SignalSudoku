"""Classify allocation and validation problems for Signal Sudoku.

Separates invalid source data, assignment issues, configurable-rule
conflicts, and hard engineering constraints that must never be bypassed.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Problems that require fixing the input MDB (not rule changes).
SOURCE_DATA_CATEGORIES = frozenset({
    'missing_data',
    'duplicate',
    'invalid_value',
    'malformed',
    'naming',
})

# Hard engineering constraints — never suggest weakening these.
HARD_CONSTRAINT_RULES = frozenset({
    'enforce_segregation',
    'signal_accounting',
    'duplicate_allocation',
    'double_booked_slot',
    'charm_type_mapping',
    'naming_uniqueness',
    'baseplate_capacity',
    'cioc_capacity',
    'cabinet_capacity',
    'segregation',
})

# Configurable preferences that may be relaxed with engineer approval.
CONFIGURABLE_PREFERENCE_KEYS = frozenset({
    'keep_groups_together',
    'keep_cables_together',
    'maintain_pair_order',
    'reserve_spare_capacity',
})


@dataclass
class DetectedProblem:
    """A single classified problem from input validation or allocation."""

    problem_id: str
    severity: str  # error | warning | info
    classification: str  # source_data | assignment | configurable_rule | hard_constraint
    category: str
    affected_item: str
    explanation: str
    suggested_action: str
    related_rule: str = ''
    can_suggest_rule_change: bool = False


@dataclass
class ProblemAnalysis:
    """Aggregated problem analysis for an allocation attempt."""

    problems: List[DetectedProblem] = field(default_factory=list)
    source_data_issues: List[DetectedProblem] = field(default_factory=list)
    assignment_issues: List[DetectedProblem] = field(default_factory=list)
    configurable_rule_issues: List[DetectedProblem] = field(default_factory=list)
    hard_constraint_issues: List[DetectedProblem] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)


class ProblemAnalyzer:
    """Analyse input findings, allocation TQs, and validator results."""

    def analyse(
        self,
        input_findings: Optional[list] = None,
        allocation_result=None,
        validation_findings: Optional[list] = None,
        rules: Optional[dict] = None,
    ) -> ProblemAnalysis:
        """Build a classified problem list from available evidence.

        Args:
            input_findings: Findings from :class:`InputValidator`.
            allocation_result: Result from :class:`AllocationEngine`.
            validation_findings: Findings from :class:`RuleValidator`.
            rules: Active rules dict (used to classify capacity vs preference).

        Returns:
            A :class:`ProblemAnalysis` with problems split by classification.
        """
        rules = rules or {}
        problems: List[DetectedProblem] = []
        seq = 1

        def next_id() -> str:
            nonlocal seq
            pid = f'PROB-{seq:04d}'
            seq += 1
            return pid

        for finding in input_findings or []:
            severity = getattr(finding, 'severity', 'info')
            if severity == 'info':
                continue
            category = getattr(finding, 'category', 'missing_data')
            classification = 'source_data'
            problems.append(DetectedProblem(
                problem_id=next_id(),
                severity=severity,
                classification=classification,
                category=category,
                affected_item=getattr(finding, 'tag', '') or getattr(finding, 'affected_item', ''),
                explanation=getattr(finding, 'message', str(finding)),
                suggested_action=getattr(finding, 'suggestion', 'Correct the source I/O MDB.'),
                can_suggest_rule_change=False,
            ))

        if allocation_result is not None:
            for item in getattr(allocation_result, 'tq_items', []) or []:
                category = item.get('category', 'capacity')
                reason = item.get('reason', '')
                description = item.get('description', '')
                affected = item.get('affected_item', '')
                classification, related_rule, can_suggest = self._classify_alloc_failure(
                    category, reason, description, rules, allocation_result
                )
                problems.append(DetectedProblem(
                    problem_id=next_id(),
                    severity='error',
                    classification=classification,
                    category=category,
                    affected_item=affected,
                    explanation=description or reason,
                    suggested_action=self._action_for(classification, related_rule),
                    related_rule=related_rule,
                    can_suggest_rule_change=can_suggest,
                ))

        for finding in validation_findings or []:
            severity = getattr(finding, 'severity', 'info')
            if severity == 'info':
                continue
            rule_name = getattr(finding, 'rule_name', getattr(finding, 'category', ''))
            classification = self._classify_validation_rule(rule_name, rules)
            can_suggest = (
                classification == 'configurable_rule'
                and rule_name in ('cable_grouping', 'spare_capacity')
            )
            related = ''
            if rule_name == 'cable_grouping':
                related = 'keep_cables_together'
            elif rule_name == 'spare_capacity':
                related = 'reserve_spare_capacity'
            elif rule_name == 'segregation':
                related = 'enforce_segregation'
            problems.append(DetectedProblem(
                problem_id=next_id(),
                severity=severity,
                classification=classification,
                category=rule_name,
                affected_item=getattr(finding, 'affected_item', ''),
                explanation=getattr(finding, 'explanation', ''),
                suggested_action=getattr(finding, 'suggested_action', ''),
                related_rule=related,
                can_suggest_rule_change=can_suggest,
            ))

        analysis = ProblemAnalysis(problems=problems)
        for p in problems:
            if p.classification == 'source_data':
                analysis.source_data_issues.append(p)
            elif p.classification == 'assignment':
                analysis.assignment_issues.append(p)
            elif p.classification == 'configurable_rule':
                analysis.configurable_rule_issues.append(p)
            else:
                analysis.hard_constraint_issues.append(p)

        analysis.summary = {
            'total': len(problems),
            'source_data': len(analysis.source_data_issues),
            'assignment': len(analysis.assignment_issues),
            'configurable_rule': len(analysis.configurable_rule_issues),
            'hard_constraint': len(analysis.hard_constraint_issues),
            'errors': sum(1 for p in problems if p.severity == 'error'),
            'warnings': sum(1 for p in problems if p.severity == 'warning'),
            'has_unallocated': bool(
                allocation_result and getattr(allocation_result, 'unallocated_signals', None)
            ),
            'fully_valid': (
                sum(1 for p in problems if p.severity == 'error') == 0
                and not (allocation_result and allocation_result.unallocated_signals)
            ),
        }
        return analysis

    def _classify_alloc_failure(
        self,
        category: str,
        reason: str,
        description: str,
        rules: dict,
        allocation_result,
    ) -> tuple:
        """Return (classification, related_rule, can_suggest_rule_change)."""
        text = f'{reason} {description}'.lower()

        if category == 'naming' or 'duplicate' in text:
            return 'source_data', '', False

        if category == 'mapping' or 'unknown' in text or 'classification' in text:
            return 'hard_constraint', 'signal_charm_mapping', False

        if category == 'segregation':
            return 'hard_constraint', 'enforce_segregation', False

        if category == 'capacity' or 'no available slot' in text or 'no feasible' in text:
            # Group overflow under keep_groups_together is a configurable preference.
            if rules.get('keep_groups_together', True) and self._looks_like_group_overflow(
                allocation_result, reason
            ):
                return 'configurable_rule', 'keep_groups_together', True
            if rules.get('reserve_spare_capacity', False):
                return 'configurable_rule', 'reserve_spare_capacity', True
            if rules.get('keep_cables_together', True) and 'cable' in text:
                return 'configurable_rule', 'keep_cables_together', True
            # True physical capacity / hard packing failure.
            return 'hard_constraint', 'capacity_limits', False

        return 'assignment', '', False

    @staticmethod
    def _looks_like_group_overflow(allocation_result, reason: str) -> bool:
        """Heuristic: capacity failure while a group already occupies a cabinet."""
        if allocation_result is None:
            return False
        # Prefer explicit TQ wording from the engine.
        if 'constraint' in (reason or '').lower() or 'no available' in (reason or '').lower():
            # If any allocated signal shares a group with an unallocated one, likely group lock.
            unalloc_groups = {
                s.group for s in allocation_result.unallocated_signals if getattr(s, 'group', '')
            }
            if not unalloc_groups:
                return False
            alloc_groups = {
                e['signal'].group
                for e in allocation_result.allocated_signals
                if getattr(e['signal'], 'group', '')
            }
            return bool(unalloc_groups & alloc_groups)
        return False

    @staticmethod
    def _classify_validation_rule(rule_name: str, rules: dict) -> str:
        if rule_name in HARD_CONSTRAINT_RULES or rule_name == 'segregation':
            return 'hard_constraint'
        if rule_name == 'cable_grouping' and rules.get('keep_cables_together', True):
            return 'configurable_rule'
        if rule_name == 'spare_capacity' and rules.get('reserve_spare_capacity', False):
            return 'configurable_rule'
        if rule_name in ('terminal_block_mapping',):
            return 'assignment'
        return 'hard_constraint'

    @staticmethod
    def _action_for(classification: str, related_rule: str) -> str:
        if classification == 'source_data':
            return 'Correct the source I/O MDB (tags, duplicates, required fields).'
        if classification == 'configurable_rule' and related_rule:
            return (
                f"Consider reviewing configurable preference '{related_rule}' "
                'under Rule Change Suggestions (requires engineer approval).'
            )
        if classification == 'hard_constraint':
            return (
                'Hard engineering constraint — cannot be bypassed by rule changes. '
                'Correct source data, provision additional approved hardware, or raise a TQ.'
            )
        return 'Review the assignment and re-run allocation.'
