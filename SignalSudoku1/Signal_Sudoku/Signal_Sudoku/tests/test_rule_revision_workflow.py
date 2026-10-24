"""Tests for rule suggestions, approval, reallocation, export, and comparison."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path

import openpyxl
import pandas as pd

from core.allocation_engine import AllocationEngine
from core.input_validation import InputValidator
from core.problem_analysis import ProblemAnalyzer
from core.report_generator import ReportGenerator
from core.revision_comparator import RevisionComparator
from core.revision_workflow import RevisionWorkflow
from core.rule_suggestion import RuleSuggestionEngine
from core.rule_validator import RuleValidator
from core.tq_generator import TQGenerator
from services.configuration_service import DEFAULT_RULES
from services.excel_exporter import ExcelExporter

ROOT = Path(__file__).resolve().parents[1]
reporter = ReportGenerator()
exporter = ExcelExporter()
workflow = RevisionWorkflow()
suggester = RuleSuggestionEngine()
analyzer = ProblemAnalyzer()
comparator = RevisionComparator()


def _tiny_capacity_rules(**overrides):
    rules = deepcopy(DEFAULT_RULES)
    rules.update(
        charms_per_baseplate=2,
        baseplates_per_cioc=1,
        ciocs_per_cabinet=1,
        keep_groups_together=True,
        keep_cables_together=False,
        enforce_segregation=False,
        reserve_spare_capacity=False,
    )
    rules.update(overrides)
    return rules


def _group_overflow_df():
    return pd.DataFrame([
        {'Tag': f'T{i}', 'IO': 'AI', 'Cable': '', 'Pair': str(i), 'Grp': 'SAME', 'Seg': ''}
        for i in range(3)
    ])


def _run_alloc(df, rules):
    result = AllocationEngine(rules).allocate(df)
    findings = RuleValidator(rules).validate(result)
    return result, findings


# ---------------------------------------------------------------------------
# 1. Valid allocation → no unnecessary rule changes
# ---------------------------------------------------------------------------

def test_valid_allocation_produces_no_rule_suggestions():
    df = pd.read_excel(ROOT / 'sample_data' / 'sample_io_mdb_clean.xlsx', dtype=str).fillna('')
    rules = deepcopy(DEFAULT_RULES)
    result, findings = _run_alloc(df, rules)
    assert not result.unallocated_signals
    session = workflow.start_from_allocation(df, rules, result, findings)
    assert session.analysis.summary['fully_valid']
    assert session.suggestions == []
    assert 'no rule changes' in (session.suggestion_result.no_solution_reason or '').lower()


def test_valid_allocation_does_not_reassign_when_rerun_same_rules():
    df = pd.DataFrame([
        {'Tag': 'A-1', 'IO': 'AI', 'Cable': 'C1', 'Pair': '1', 'Grp': 'G1', 'Seg': 'A'},
        {'Tag': 'A-2', 'IO': 'AI', 'Cable': 'C1', 'Pair': '2', 'Grp': 'G1', 'Seg': 'A'},
    ])
    rules = deepcopy(DEFAULT_RULES)
    first, _ = _run_alloc(df, rules)
    slots1 = {e['signal'].tag: e['charm_slot'].charm_id for e in first.allocated_signals}
    preferred = dict(slots1)
    second = AllocationEngine(rules).allocate(df, preferred_slots=preferred)
    slots2 = {e['signal'].tag: e['charm_slot'].charm_id for e in second.allocated_signals}
    assert slots1 == slots2


# ---------------------------------------------------------------------------
# 2. Configurable preference blocks preferred packing; another solution exists
# ---------------------------------------------------------------------------

def test_group_preference_blocks_allocation_but_relaxation_allows_solution():
    rules = _tiny_capacity_rules(keep_groups_together=True)
    df = _group_overflow_df()
    result, findings = _run_alloc(df, rules)
    assert len(result.unallocated_signals) == 1

    session = workflow.start_from_allocation(df, rules, result, findings)
    assert any(s.rule_key == 'keep_groups_together' for s in session.suggestions)

    updated = workflow.approve_and_reallocate(
        session, [s.suggestion_id for s in session.suggestions if s.rule_key == 'keep_groups_together']
    )
    assert updated.approved_rules['keep_groups_together'] is False
    assert session.original_rules['keep_groups_together'] is True  # original preserved
    assert not updated.revised_result.unallocated_signals
    assert updated.is_fully_valid


# ---------------------------------------------------------------------------
# 3. Capacity limit must not be bypassed
# ---------------------------------------------------------------------------

def test_capacity_limit_not_bypassed_when_no_preference_helps():
    # One cabinet of 2 slots, three signals, groups preference already off.
    rules = _tiny_capacity_rules(keep_groups_together=False)
    df = _group_overflow_df()
    # Different groups so allocator can open new cabinets — use same tags but
    # force a single-cabinet physical limit by also capping... wait: with
    # keep_groups_together=False the engine creates new cabinets freely.
    # True hard capacity: more signals than one cabinet AND keep_groups True
    # already tested. Here: incompatible expansion when segregation + tiny
    # hardware still respects per-baseplate charm count.
    result, findings = _run_alloc(df, rules)
    # With groups free, all 3 should allocate across cabinets (new cab allowed).
    assert len(result.allocated_signals) == 3

    # Hard capacity on a single baseplate: verify no baseplate exceeds charms_per_baseplate.
    for cab in result.cabinets:
        for cioc in cab.ciocs:
            for bp in cioc.baseplates:
                assert len(bp.charms) <= rules['charms_per_baseplate']
                assert bp.used_slots <= rules['charms_per_baseplate']


def test_hard_capacity_with_locked_group_does_not_invent_extra_charms():
    rules = _tiny_capacity_rules(keep_groups_together=True)
    df = _group_overflow_df()
    result, _ = _run_alloc(df, rules)
    assert len(result.allocated_signals) == 2
    assert len(result.unallocated_signals) == 1
    for cab in result.cabinets:
        for cioc in cab.ciocs:
            for bp in cioc.baseplates:
                assert len(bp.charms) <= 2


# ---------------------------------------------------------------------------
# 4. Incompatible signal must not be assigned to incompatible hardware
# ---------------------------------------------------------------------------

def test_unknown_io_never_assigned_even_after_rule_suggestions():
    df = pd.DataFrame([
        {'Tag': 'X-1', 'IO': 'MYSTERY', 'Cable': '', 'Pair': '', 'Grp': '', 'Seg': ''},
        {'Tag': 'Y-1', 'IO': 'AI', 'Cable': '', 'Pair': '1', 'Grp': '', 'Seg': ''},
    ])
    rules = deepcopy(DEFAULT_RULES)
    result, findings = _run_alloc(df, rules)
    assert any(s.tag == 'X-1' for s in result.unallocated_signals)
    assert any(e['signal'].tag == 'Y-1' for e in result.allocated_signals)

    session = workflow.start_from_allocation(df, rules, result, findings)
    # Mapping failures are hard constraints — no suggestion invents MYSTERY hardware.
    assert not any(s.rule_key == 'signal_charm_mapping' for s in session.suggestions)
    for sug in session.suggestions:
        assert not sug.is_hard_constraint

    analysis = analyzer.analyse(
        allocation_result=result, validation_findings=findings, rules=rules
    )
    hard = [p for p in analysis.hard_constraint_issues if p.affected_item == 'X-1']
    assert hard
    assert all(not p.can_suggest_rule_change for p in hard)


# ---------------------------------------------------------------------------
# 5. Approved permissible change resolves conflict
# ---------------------------------------------------------------------------

def test_approved_rule_change_resolves_group_overflow():
    rules = _tiny_capacity_rules()
    df = _group_overflow_df()
    result, findings = _run_alloc(df, rules)
    session = workflow.start_from_allocation(df, rules, result, findings)
    ids = [s.suggestion_id for s in session.suggestions if s.rule_key == 'keep_groups_together']
    assert ids
    updated = workflow.approve_and_reallocate(session, ids)
    assert updated.is_fully_valid
    assert updated.revised_result.statistics['allocated'] == 3
    # Actual allocation must change: previously unallocated tag now has a slot.
    unalloc_tags = {s.tag for s in result.unallocated_signals}
    newly = {
        e['signal'].tag
        for e in updated.revised_result.allocated_signals
        if e['signal'].tag in unalloc_tags
    }
    assert newly == unalloc_tags


# ---------------------------------------------------------------------------
# 6. Approved change fails to resolve → remaining problem reported
# ---------------------------------------------------------------------------

def test_approved_change_that_cannot_fix_reports_remaining_problems():
    # Duplicate tag is source data — relaxing groups cannot fix it.
    rules = _tiny_capacity_rules(keep_groups_together=True)
    df = pd.DataFrame([
        {'Tag': 'DUP', 'IO': 'AI', 'Cable': '', 'Pair': '1', 'Grp': 'G', 'Seg': ''},
        {'Tag': 'DUP', 'IO': 'AI', 'Cable': '', 'Pair': '2', 'Grp': 'G', 'Seg': ''},
        {'Tag': 'T2', 'IO': 'AI', 'Cable': '', 'Pair': '3', 'Grp': 'G', 'Seg': ''},
        {'Tag': 'T3', 'IO': 'AI', 'Cable': '', 'Pair': '4', 'Grp': 'G', 'Seg': ''},
    ])
    result, findings = _run_alloc(df, rules)
    session = workflow.start_from_allocation(df, rules, result, findings)
    # Even if we approve a group suggestion (if present), duplicate remains unallocated.
    ids = [s.suggestion_id for s in session.suggestions]
    if ids:
        updated = workflow.approve_and_reallocate(session, ids)
        assert not updated.is_fully_valid
        assert updated.revised_result.unallocated_signals
        assert updated.revised_analysis.summary.get('errors', 0) >= 1 or \
            len(updated.revised_result.unallocated_signals) >= 1
    else:
        # No configurable fix available — session must explain that.
        assert session.suggestion_result.no_solution_reason


# ---------------------------------------------------------------------------
# 7. Engineer rejects suggestions → original unchanged
# ---------------------------------------------------------------------------

def test_reject_suggestions_leaves_original_rules_and_data_unchanged():
    rules = _tiny_capacity_rules()
    df = _group_overflow_df()
    result, findings = _run_alloc(df, rules)
    session = workflow.start_from_allocation(df, rules, result, findings)
    original_rules_snapshot = deepcopy(session.original_rules)
    original_unalloc = len(result.unallocated_signals)

    workflow.cancel(session)
    assert session.cancelled
    assert session.approved_rules is None
    assert session.revised_result is None
    assert session.original_rules == original_rules_snapshot
    assert session.original_rules['keep_groups_together'] is True
    assert len(session.original_result.unallocated_signals) == original_unalloc


# ---------------------------------------------------------------------------
# 8. Proposed Excel contains real revised allocation and change summary
# ---------------------------------------------------------------------------

def test_proposed_excel_contains_revised_assignments_and_rule_summary():
    rules = _tiny_capacity_rules()
    df = _group_overflow_df()
    result, findings = _run_alloc(df, rules)
    session = workflow.start_from_allocation(df, rules, result, findings)
    ids = [s.suggestion_id for s in session.suggestions if s.rule_key == 'keep_groups_together']
    updated = workflow.approve_and_reallocate(session, ids)

    alloc_df = reporter.generate_allocation_table(updated.revised_result)
    val_df = reporter.generate_validation_report(updated.revised_findings)
    tq_df = reporter.generate_tq_report(updated.revised_tqs)
    hw_df = reporter.generate_hardware_summary(updated.revised_result)
    cfg_df = reporter.generate_configuration_report(updated.approved_rules)
    rules_df = reporter.generate_approved_rules_report(workflow.rule_change_summary_rows(updated))
    summary_df = reporter.generate_change_summary_report(workflow.change_summary_dict(updated))
    orig_df = reporter.generate_allocation_table(result)
    cmp = comparator.compare_allocations(orig_df, alloc_df)
    cmp_df = reporter.generate_allocation_comparison_report(cmp)

    buf = exporter.export_proposed_revision(
        alloc_df, val_df, tq_df, hw_df, cfg_df, summary_df, rules_df,
        comparison_df=cmp_df, is_fully_valid=updated.is_fully_valid,
    )
    wb = openpyxl.load_workbook(BytesIO(buf.getvalue()))
    assert 'IO_Allocation' in wb.sheetnames
    assert 'Change_Summary' in wb.sheetnames
    assert 'Approved_Rule_Changes' in wb.sheetnames
    assert 'Revision_Banner' in wb.sheetnames

    io_sheet = wb['IO_Allocation']
    headers = [c.value for c in io_sheet[1]]
    tag_idx = headers.index('Tag') + 1
    charm_idx = headers.index('CHARM') + 1
    status_idx = headers.index('Status') + 1
    exported = {}
    for row in io_sheet.iter_rows(min_row=2, max_row=io_sheet.max_row):
        tag = row[tag_idx - 1].value
        exported[tag] = {
            'CHARM': row[charm_idx - 1].value,
            'Status': row[status_idx - 1].value,
        }
    # Real assignments: every signal Allocated with a non-empty CHARM.
    for tag in ['T0', 'T1', 'T2']:
        assert exported[tag]['Status'] == 'Allocated'
        assert exported[tag]['CHARM']

    rules_sheet = wb['Approved_Rule_Changes']
    rules_text = ' '.join(
        str(c.value) for row in rules_sheet.iter_rows() for c in row if c.value
    )
    assert 'keep_groups_together' in rules_text


# ---------------------------------------------------------------------------
# 9. Comparison distinguishes source data vs hardware reassignment
# ---------------------------------------------------------------------------

def test_comparison_distinguishes_source_data_from_hardware_changes():
    orig = pd.DataFrame([
        {
            'Tag': 'S1', 'IO': 'AI', 'Cable': 'C1', 'Pair': '1', 'Group': 'G1',
            'Segregation': 'A', 'Cabinet': 'CAB-1', 'CIOC': 'CIOC-1',
            'Baseplate': 'BP-1', 'CHARM': 'BP-1-CH-01', 'Status': 'Allocated',
        },
        {
            'Tag': 'S2', 'IO': 'DI', 'Cable': 'C2', 'Pair': '1', 'Group': 'G1',
            'Segregation': 'A', 'Cabinet': 'CAB-1', 'CIOC': 'CIOC-1',
            'Baseplate': 'BP-1', 'CHARM': 'BP-1-CH-02', 'Status': 'Allocated',
        },
    ])
    proposed = pd.DataFrame([
        {
            'Tag': 'S1', 'IO': 'AI', 'Cable': 'C1', 'Pair': '1', 'Group': 'G1',
            'Segregation': 'A', 'Cabinet': 'CAB-2', 'CIOC': 'CIOC-2',
            'Baseplate': 'BP-9', 'CHARM': 'BP-9-CH-01', 'Status': 'Allocated',
        },
        {
            'Tag': 'S2', 'IO': 'DO', 'Cable': 'C2', 'Pair': '1', 'Group': 'G1',
            'Segregation': 'A', 'Cabinet': 'CAB-1', 'CIOC': 'CIOC-1',
            'Baseplate': 'BP-1', 'CHARM': 'BP-1-CH-02', 'Status': 'Allocated',
        },
    ])
    result = comparator.compare_allocations(orig, proposed)
    by_tag = {c.tag: c for c in result.modified}
    assert 'S1' in by_tag
    assert 'IO' not in by_tag['S1'].changed_fields
    assert 'CHARM' in by_tag['S1'].changed_fields
    assert 'hardware' in by_tag['S1'].move_reason.lower()

    assert 'S2' in by_tag
    assert 'IO' in by_tag['S2'].changed_fields
    assert by_tag['S2'].changed_fields['IO'] == ('DI', 'DO')
    assert result.summary['hardware_reassigned'] >= 1
    assert result.summary['source_data_modified'] >= 1


# ---------------------------------------------------------------------------
# 10. Existing functionality continues to work
# ---------------------------------------------------------------------------

def test_existing_allocation_validation_tq_export_and_mdb_revision_still_work():
    df = pd.read_excel(ROOT / 'sample_data' / 'sample_io_mdb_clean.xlsx', dtype=str).fillna('')
    rules = deepcopy(DEFAULT_RULES)
    result, findings = _run_alloc(df, rules)
    assert not result.unallocated_signals
    assert not [f for f in findings if f.severity == 'error']

    tqs = TQGenerator().generate_from_validation([])
    alloc_df = reporter.generate_allocation_table(result)
    val_df = reporter.generate_validation_report(findings)
    tq_df = reporter.generate_tq_report(tqs)
    hw_df = reporter.generate_hardware_summary(result)
    cfg_df = reporter.generate_configuration_report(rules)
    buf = exporter.export_allocation(alloc_df, val_df, tq_df, hw_df, cfg_df)
    wb = openpyxl.load_workbook(BytesIO(buf.getvalue()))
    assert 'IO_Allocation' in wb.sheetnames

    # MDB revision compare still works
    rev_b_path = ROOT / 'sample_data' / 'sample_revision_b.xlsx'
    if rev_b_path.exists():
        rev_b = pd.read_excel(rev_b_path, dtype=str).fillna('')
        normal_a = InputValidator().normalize_dataframe(df)
        normal_b = InputValidator().normalize_dataframe(rev_b)
        rev = RevisionComparator().compare(normal_a, normal_b)
        assert 'added' in rev.summary
        assert rev.summary['total_rev_a'] > 0


def test_segregation_still_enforced_as_hard_constraint():
    df = pd.DataFrame([
        {'Tag': 'A-1', 'IO': 'AI', 'Cable': 'C1', 'Pair': '1', 'Grp': 'G1', 'Seg': 'A'},
        {'Tag': 'B-1', 'IO': 'AI', 'Cable': 'C2', 'Pair': '1', 'Grp': 'G2', 'Seg': 'B'},
    ])
    result = AllocationEngine(deepcopy(DEFAULT_RULES)).allocate(df)
    ciocs = {e['signal'].tag: e['charm_slot'].cioc_id for e in result.allocated_signals}
    assert ciocs['A-1'] != ciocs['B-1']
    # Suggestions must never propose disabling enforce_segregation.
    findings = RuleValidator(deepcopy(DEFAULT_RULES)).validate(result)
    session = workflow.start_from_allocation(df, deepcopy(DEFAULT_RULES), result, findings)
    assert not any(s.rule_key == 'enforce_segregation' for s in session.suggestions)


# ---------------------------------------------------------------------------
# 11. Duplicate tags and unallocated signals follow existing policy
# ---------------------------------------------------------------------------

def test_duplicate_tags_unallocated_with_naming_tq():
    df = pd.DataFrame([
        {'Tag': 'SAME', 'IO': 'AI', 'Cable': '', 'Pair': '1', 'Grp': '', 'Seg': ''},
        {'Tag': 'SAME', 'IO': 'AI', 'Cable': '', 'Pair': '2', 'Grp': '', 'Seg': ''},
    ])
    result = AllocationEngine(deepcopy(DEFAULT_RULES)).allocate(df)
    assert len(result.allocated_signals) == 1
    assert len(result.unallocated_signals) == 1
    assert result.tq_items[0]['category'] == 'naming'

    findings = RuleValidator(deepcopy(DEFAULT_RULES)).validate(result)
    analysis = analyzer.analyse(
        allocation_result=result, validation_findings=findings, rules=deepcopy(DEFAULT_RULES)
    )
    assert any(p.classification == 'source_data' for p in analysis.problems)


def test_apply_approved_changes_never_weakens_hard_keys():
    rules = deepcopy(DEFAULT_RULES)
    from core.rule_suggestion import RuleChangeSuggestion
    fake = RuleChangeSuggestion(
        suggestion_id='BAD',
        rule_key='enforce_segregation',
        current_value=True,
        proposed_value=False,
        conflict_resolved='should not apply',
        expected_impact='none',
        is_hard_constraint=True,
    )
    # Even if somehow passed, apply_approved_changes skips hard + non-configurable.
    revised = suggester.apply_approved_changes(rules, [fake])
    assert revised['enforce_segregation'] is True
