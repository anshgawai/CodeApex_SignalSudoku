"""Orchestrate rule-suggestion approval, reallocation, and proposed revisions.

Keeps original rules and proposed rules distinguishable. Never silently
applies suggestions or bypasses hard constraints.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from core.allocation_engine import AllocationEngine
from core.problem_analysis import ProblemAnalysis, ProblemAnalyzer
from core.rule_suggestion import (
    RuleChangeSuggestion,
    RuleSuggestionEngine,
    RuleSuggestionResult,
)
from core.rule_validator import RuleValidator
from core.tq_generator import TQGenerator, TechnicalQuery


@dataclass
class RevisionSession:
    """In-memory state for one proposed-revision workflow."""

    original_df: Any = None
    original_rules: dict = field(default_factory=dict)
    original_result: Any = None
    original_findings: list = field(default_factory=list)
    original_tqs: list = field(default_factory=list)
    analysis: Optional[ProblemAnalysis] = None
    suggestions: List[RuleChangeSuggestion] = field(default_factory=list)
    suggestion_result: Optional[RuleSuggestionResult] = None
    approved_suggestions: List[RuleChangeSuggestion] = field(default_factory=list)
    approved_rules: Optional[dict] = None
    revised_result: Any = None
    revised_findings: list = field(default_factory=list)
    revised_tqs: list = field(default_factory=list)
    revised_analysis: Optional[ProblemAnalysis] = None
    is_fully_valid: bool = False
    cancelled: bool = False


class RevisionWorkflow:
    """End-to-end proposed revision workflow (logic only; UI stays in app)."""

    def __init__(self) -> None:
        self._analyzer = ProblemAnalyzer()
        self._suggester = RuleSuggestionEngine()

    def start_from_allocation(
        self,
        df: pd.DataFrame,
        rules: dict,
        allocation_result,
        validation_findings: list,
        input_findings: Optional[list] = None,
        tqs: Optional[list] = None,
    ) -> RevisionSession:
        """Build a session from an existing allocation attempt."""
        analysis = self._analyzer.analyse(
            input_findings=input_findings or [],
            allocation_result=allocation_result,
            validation_findings=validation_findings,
            rules=rules,
        )
        suggestion_result = self._suggester.suggest(analysis, rules, allocation_result)
        return RevisionSession(
            original_df=df.copy(),
            original_rules=deepcopy(rules),
            original_result=allocation_result,
            original_findings=list(validation_findings),
            original_tqs=list(tqs or []),
            analysis=analysis,
            suggestions=list(suggestion_result.suggestions),
            suggestion_result=suggestion_result,
        )

    def cancel(self, session: RevisionSession) -> RevisionSession:
        """Cancel without mutating original rules or data."""
        session.cancelled = True
        session.approved_suggestions = []
        session.approved_rules = None
        session.revised_result = None
        session.revised_findings = []
        session.revised_tqs = []
        session.revised_analysis = None
        session.is_fully_valid = False
        return session

    def approve_and_reallocate(
        self,
        session: RevisionSession,
        selected_suggestion_ids: List[str],
        input_findings: Optional[list] = None,
    ) -> RevisionSession:
        """Apply selected suggestions, reallocate with preserve, and revalidate.

        Original rules on the session are never overwritten. Approved rules are
        stored separately on ``session.approved_rules``.
        """
        session.cancelled = False
        approved = [
            s for s in session.suggestions
            if s.suggestion_id in selected_suggestion_ids and not s.is_hard_constraint
        ]
        session.approved_suggestions = approved
        session.approved_rules = self._suggester.apply_approved_changes(
            session.original_rules, approved
        )

        preferred = self._preferred_slot_map(session.original_result)
        engine = AllocationEngine(session.approved_rules)
        revised = engine.allocate(session.original_df, preferred_slots=preferred)
        findings = RuleValidator(session.approved_rules).validate(revised)

        tqs = TQGenerator().generate_from_validation(input_findings or [])
        for idx, item in enumerate(revised.tq_items, 1):
            tqs.append(TechnicalQuery(
                tq_id=f'TQ-ALLOC-{idx:04d}',
                affected_item=item['affected_item'],
                category=item['category'],
                description=item['description'],
                reason=item['reason'],
                information_needed='Confirm signal details, constraints, or available hardware.',
                suggested_action='Review the signal and approved rule changes, then reconsider.',
                priority='High',
            ))

        revised_analysis = self._analyzer.analyse(
            input_findings=input_findings or [],
            allocation_result=revised,
            validation_findings=findings,
            rules=session.approved_rules,
        )

        session.revised_result = revised
        session.revised_findings = findings
        session.revised_tqs = tqs
        session.revised_analysis = revised_analysis
        error_findings = [f for f in findings if f.severity == 'error']
        session.is_fully_valid = (
            not revised.unallocated_signals
            and not error_findings
            and revised_analysis.summary.get('errors', 0) == 0
        )
        return session

    @staticmethod
    def _preferred_slot_map(allocation_result) -> Dict[str, str]:
        """Build tag -> charm_id map from a prior allocation."""
        preferred: Dict[str, str] = {}
        if allocation_result is None:
            return preferred
        for entry in allocation_result.allocated_signals:
            sig = entry['signal']
            slot = entry['charm_slot']
            if sig.tag and slot.charm_id:
                preferred[sig.tag] = slot.charm_id
        return preferred

    @staticmethod
    def rule_change_summary_rows(session: RevisionSession) -> List[dict]:
        """Rows describing approved rule changes (old vs new)."""
        rows = []
        for sug in session.approved_suggestions:
            rows.append({
                'Rule': sug.rule_key,
                'Original_Value': sug.current_value,
                'Approved_Value': sug.proposed_value,
                'Conflict_Resolved': sug.conflict_resolved,
                'Expected_Impact': sug.expected_impact,
                'Warnings': '; '.join(sug.warnings),
            })
        return rows

    @staticmethod
    def change_summary_dict(session: RevisionSession) -> dict:
        """High-level summary for UI and export."""
        orig = session.original_result
        rev = session.revised_result
        return {
            'document_type': 'PROPOSED_REVISION',
            'requires_engineering_review': True,
            'original_allocated': orig.statistics.get('allocated', 0) if orig else 0,
            'original_unallocated': orig.statistics.get('unallocated', 0) if orig else 0,
            'revised_allocated': rev.statistics.get('allocated', 0) if rev else 0,
            'revised_unallocated': rev.statistics.get('unallocated', 0) if rev else 0,
            'approved_rule_changes': len(session.approved_suggestions),
            'is_fully_valid': session.is_fully_valid,
            'remaining_errors': (
                session.revised_analysis.summary.get('errors', 0)
                if session.revised_analysis else 0
            ),
        }
