"""Suggest permissible configurable rule changes for Signal Sudoku.

Only preferences supported by the existing configuration and allocation
engine are proposed. Hard constraints are never suggested for weakening.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from core.problem_analysis import (
    CONFIGURABLE_PREFERENCE_KEYS,
    DetectedProblem,
    ProblemAnalysis,
)


@dataclass
class RuleChangeSuggestion:
    """A single proposed change to a configurable preference."""

    suggestion_id: str
    rule_key: str
    current_value: Any
    proposed_value: Any
    conflict_resolved: str
    expected_impact: str
    warnings: List[str] = field(default_factory=list)
    affected_items: List[str] = field(default_factory=list)
    is_hard_constraint: bool = False


@dataclass
class RuleSuggestionResult:
    """Bundle of suggestions plus an explanation when none are possible."""

    suggestions: List[RuleChangeSuggestion] = field(default_factory=list)
    no_solution_reason: str = ''
    hard_blockers: List[DetectedProblem] = field(default_factory=list)


# Preference metadata: only these may appear in suggestions.
_PREFERENCE_PROPOSALS: Dict[str, Dict[str, Any]] = {
    'keep_groups_together': {
        'proposed_when_true': False,
        'conflict': 'Group locked to a single cabinet that is at capacity',
        'impact': (
            'Signals in the same group may be placed in different cabinets. '
            'Existing valid slots are preserved where still feasible.'
        ),
        'warnings': [
            'Group co-location preference will be relaxed for this proposed revision only.',
            'Does not change physical cabinet capacity limits.',
        ],
    },
    'keep_cables_together': {
        'proposed_when_true': False,
        'conflict': 'Cable co-location preference blocks or splits placement',
        'impact': (
            'Signals sharing a cable may be placed on different baseplates '
            'when a single baseplate cannot hold them.'
        ),
        'warnings': [
            'Cable grouping preference will be relaxed for this proposed revision only.',
        ],
    },
    'reserve_spare_capacity': {
        'proposed_when_true': False,
        'conflict': 'Reserved spare capacity reduces usable slots below demand',
        'impact': (
            'Previously reserved spare baseplate capacity becomes available '
            'for signal allocation in the proposed revision.'
        ),
        'warnings': [
            'Spare-capacity reservation will be disabled for this proposed revision only.',
            'Confirm with the project that releasing spare is acceptable.',
        ],
    },
    'maintain_pair_order': {
        'proposed_when_true': False,
        'conflict': 'Pair ordering preference may contribute to packing inefficiency',
        'impact': 'Allocation sort order will no longer prioritise cable pair sequence.',
        'warnings': [
            'Pair order preference will be relaxed for this proposed revision only.',
            'Usually insufficient alone to resolve hard capacity failures.',
        ],
    },
}


class RuleSuggestionEngine:
    """Derive permissible rule-change suggestions from analysed problems."""

    def suggest(
        self,
        analysis: ProblemAnalysis,
        current_rules: dict,
        allocation_result=None,
    ) -> RuleSuggestionResult:
        """Produce suggestions for configurable conflicts only.

        Never proposes disabling segregation, inventing CHARM compatibility,
        or exceeding structural capacity invariants.
        """
        rules = current_rules or {}
        result = RuleSuggestionResult(
            hard_blockers=list(analysis.hard_constraint_issues),
        )

        if analysis.summary.get('fully_valid'):
            result.no_solution_reason = (
                'Allocation already satisfies hard constraints with no unallocated '
                'signals; no rule changes are required.'
            )
            return result

        # Source-data errors cannot be fixed by rule changes.
        fatal_source = [p for p in analysis.source_data_issues if p.severity == 'error']
        if fatal_source and not analysis.configurable_rule_issues:
            # Still allow suggestions if there are also configurable issues,
            # but note source blockers.
            only_source = not analysis.configurable_rule_issues and not [
                p for p in analysis.hard_constraint_issues
                if p.category == 'capacity' and p.can_suggest_rule_change
            ]
            if only_source and not any(p.can_suggest_rule_change for p in analysis.problems):
                result.no_solution_reason = (
                    'Unresolved source-data errors must be corrected in the I/O MDB '
                    'before rule changes can help. Examples: '
                    + '; '.join(p.explanation for p in fatal_source[:3])
                )
                return result

        suggested_keys: Set[str] = set()
        suggestions: List[RuleChangeSuggestion] = []
        seq = 1

        candidates = [
            p for p in analysis.problems
            if p.can_suggest_rule_change and p.related_rule in CONFIGURABLE_PREFERENCE_KEYS
        ]

        # Also scan unallocated capacity failures for group/spare preferences.
        if allocation_result and allocation_result.unallocated_signals:
            for key in ('keep_groups_together', 'reserve_spare_capacity', 'keep_cables_together'):
                if key in suggested_keys:
                    continue
                if not rules.get(key, False if key == 'reserve_spare_capacity' else True):
                    continue
                if key == 'keep_groups_together' and not self._group_overflow_present(
                    allocation_result
                ):
                    continue
                if key == 'reserve_spare_capacity' and not rules.get('reserve_spare_capacity'):
                    continue
                if key == 'keep_cables_together' and not self._cable_preference_blocking(
                    analysis, allocation_result
                ):
                    continue
                # Avoid duplicate if already in candidates
                if any(p.related_rule == key for p in candidates):
                    continue
                candidates.append(DetectedProblem(
                    problem_id=f'AUTO-{key}',
                    severity='error',
                    classification='configurable_rule',
                    category='capacity',
                    affected_item=', '.join(
                        s.tag for s in allocation_result.unallocated_signals[:5]
                    ),
                    explanation='Unallocated signals under active preference constraints.',
                    suggested_action='',
                    related_rule=key,
                    can_suggest_rule_change=True,
                ))

        for problem in candidates:
            key = problem.related_rule
            if key in suggested_keys or key not in _PREFERENCE_PROPOSALS:
                continue
            meta = _PREFERENCE_PROPOSALS[key]
            current = rules.get(key)
            proposed = meta['proposed_when_true']
            if current == proposed:
                continue
            # Only suggest flipping True→False preferences in this prototype.
            if current is not True:
                continue

            affected = [problem.affected_item] if problem.affected_item else []
            suggestions.append(RuleChangeSuggestion(
                suggestion_id=f'SUG-{seq:04d}',
                rule_key=key,
                current_value=current,
                proposed_value=proposed,
                conflict_resolved=meta['conflict'] + f' ({problem.explanation})',
                expected_impact=meta['impact'],
                warnings=list(meta['warnings']),
                affected_items=affected,
                is_hard_constraint=False,
            ))
            suggested_keys.add(key)
            seq += 1

        result.suggestions = suggestions

        if not suggestions:
            hard = analysis.hard_constraint_issues
            source = [p for p in analysis.source_data_issues if p.severity == 'error']
            parts = []
            if hard:
                parts.append(
                    'Hard constraints remain (e.g. incompatible I/O mapping, '
                    'segregation, or physical capacity). These cannot be bypassed.'
                )
            if source:
                parts.append('Source-data errors must be fixed in the I/O MDB.')
            if not parts:
                parts.append(
                    'No permissible configurable preference change is available '
                    'for the detected conflicts.'
                )
            result.no_solution_reason = ' '.join(parts)

        return result

    def apply_approved_changes(
        self,
        base_rules: dict,
        approved_suggestions: List[RuleChangeSuggestion],
    ) -> dict:
        """Return a new rules dict with approved preference changes applied.

        Does not mutate *base_rules*. Refuses to apply any suggestion marked
        as a hard constraint.
        """
        revised = deepcopy(base_rules)
        for sug in approved_suggestions:
            if sug.is_hard_constraint:
                continue
            if sug.rule_key not in CONFIGURABLE_PREFERENCE_KEYS:
                continue
            revised[sug.rule_key] = sug.proposed_value
            # Keep enabled_rules mirror in sync when present.
            enabled = revised.get('enabled_rules')
            if isinstance(enabled, dict):
                mirror = {
                    'keep_groups_together': 'group_together',
                    'keep_cables_together': 'cable_grouping',
                    'maintain_pair_order': 'pair_ordering',
                    'reserve_spare_capacity': 'spare_capacity',
                }
                mirror_key = mirror.get(sug.rule_key)
                if mirror_key and mirror_key in enabled:
                    enabled[mirror_key] = bool(sug.proposed_value)
        return revised

    @staticmethod
    def _group_overflow_present(allocation_result) -> bool:
        unalloc_groups = {
            s.group for s in allocation_result.unallocated_signals if s.group
        }
        if not unalloc_groups:
            return False
        alloc_groups = {
            e['signal'].group
            for e in allocation_result.allocated_signals
            if e['signal'].group
        }
        return bool(unalloc_groups & alloc_groups)

    @staticmethod
    def _cable_preference_blocking(analysis: ProblemAnalysis, allocation_result) -> bool:
        if any(p.related_rule == 'keep_cables_together' for p in analysis.problems):
            return True
        # Capacity failures with shared cables among allocated+unallocated.
        unalloc_cables = {
            s.cable for s in allocation_result.unallocated_signals if s.cable
        }
        alloc_cables = {
            e['signal'].cable
            for e in allocation_result.allocated_signals
            if e['signal'].cable
        }
        return bool(unalloc_cables & alloc_cables)
