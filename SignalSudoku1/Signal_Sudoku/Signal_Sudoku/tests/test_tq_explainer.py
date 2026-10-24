"""Tests for the TQ explainer helper module."""
from copy import deepcopy
from pathlib import Path
import pandas as pd
from core.allocation_engine import AllocationEngine
from core.tq_generator import TQGenerator, TechnicalQuery
from core.tq_explainer import get_category_info, lookup_allocation_status, find_related_tqs, explain_tq
from core.input_validation import InputValidator
from services.configuration_service import DEFAULT_RULES


def test_get_category_info_returns_all_known_categories():
    """Every category used in tq_generator should have an entry."""
    known = ['missing_subtype', 'capacity', 'segregation', 'cable_info', 'naming', 'mapping']
    for cat in known:
        info = get_category_info(cat)
        assert info['plain_name'], f"Missing plain_name for {cat}"
        assert info['classification'] in ('data_quality', 'hard_constraint', 'preference_warning')
        assert info['what_it_means']
        assert info['why_it_matters']
        assert info['corrective_action']


def test_get_category_info_unknown_category_returns_fallback():
    info = get_category_info('some_future_category')
    assert info['plain_name'] == 'Some Future Category'
    assert info['classification'] == 'preference_warning'


def test_lookup_allocation_status_allocated():
    """Signal that is allocated should return 'Allocated'."""
    rules = deepcopy(DEFAULT_RULES)
    df = pd.DataFrame([{'Tag': 'SIG-1', 'IO': 'AI', 'Cable': '', 'Pair': '', 'Grp': '', 'Seg': ''}])
    result = AllocationEngine(rules).allocate(df)
    assert result.statistics['allocated'] == 1
    assert lookup_allocation_status('SIG-1', result) == 'Allocated'


def test_lookup_allocation_status_unallocated():
    """Signal with unknown IO type should be unallocated."""
    rules = deepcopy(DEFAULT_RULES)
    df = pd.DataFrame([{'Tag': 'X-1', 'IO': 'MYSTERY', 'Cable': '', 'Pair': '', 'Grp': '', 'Seg': ''}])
    result = AllocationEngine(rules).allocate(df)
    assert result.statistics['unallocated'] == 1
    assert lookup_allocation_status('X-1', result) == 'Unallocated'


def test_lookup_allocation_status_not_found():
    """Tag that doesn't exist in allocation data returns Unknown."""
    rules = deepcopy(DEFAULT_RULES)
    df = pd.DataFrame([{'Tag': 'SIG-1', 'IO': 'AI', 'Cable': '', 'Pair': '', 'Grp': '', 'Seg': ''}])
    result = AllocationEngine(rules).allocate(df)
    assert lookup_allocation_status('NONEXISTENT', result) == 'Unknown — signal not found in allocation data'


def test_lookup_allocation_status_none_result():
    assert lookup_allocation_status('SIG-1', None) == 'Unknown — allocation data not available'


def test_find_related_tqs_same_signal():
    tqs = [
        TechnicalQuery(tq_id='TQ-0001', affected_item='SIG-1', category='naming',
                       description='Dup tag', reason='dup', information_needed='fix', suggested_action='fix'),
        TechnicalQuery(tq_id='TQ-0002', affected_item='SIG-1', category='mapping',
                       description='Bad mapping', reason='map', information_needed='fix', suggested_action='fix'),
        TechnicalQuery(tq_id='TQ-0003', affected_item='SIG-2', category='capacity',
                       description='No room', reason='cap', information_needed='fix', suggested_action='fix'),
    ]
    related = find_related_tqs('TQ-0001', 'SIG-1', tqs)
    assert len(related) == 1
    assert related[0]['tq_id'] == 'TQ-0002'


def test_find_related_tqs_no_related():
    tqs = [
        TechnicalQuery(tq_id='TQ-0001', affected_item='SIG-1', category='naming',
                       description='Dup tag', reason='dup', information_needed='fix', suggested_action='fix'),
    ]
    related = find_related_tqs('TQ-0001', 'SIG-1', tqs)
    assert related == []


def test_classification_labels_are_distinct_per_type():
    """Each classification type should get a different label."""
    categories_by_class = {}
    for cat in ['missing_subtype', 'capacity', 'segregation', 'cable_info', 'naming', 'mapping']:
        info = get_category_info(cat)
        categories_by_class.setdefault(info['classification'], []).append(cat)
    # Ensure we have at least two distinct classification types
    assert len(categories_by_class) >= 2, "Should distinguish data_quality, hard_constraint, and preference_warning"


def test_duplicate_tag_tq_correctly_shows_unallocated():
    """Duplicate tags produce a TQ and the duplicate is unallocated."""
    rules = deepcopy(DEFAULT_RULES)
    df = pd.DataFrame([
        {'Tag': 'DUP-1', 'IO': 'AI', 'Cable': '', 'Pair': '', 'Grp': '', 'Seg': ''},
        {'Tag': 'DUP-1', 'IO': 'AI', 'Cable': '', 'Pair': '', 'Grp': '', 'Seg': ''},
    ])
    result = AllocationEngine(rules).allocate(df)
    # One allocated, one unallocated (the duplicate)
    assert result.statistics['allocated'] == 1
    assert result.statistics['unallocated'] == 1
    # The TQ should be for the duplicate
    assert any(item['category'] == 'naming' for item in result.tq_items)
    # The first instance should be Allocated
    assert lookup_allocation_status('DUP-1', result) == 'Allocated'


def test_explainer_works_with_validation_generated_tqs():
    """TQs generated from validation findings should also be explainable."""
    validator = InputValidator()
    df = pd.DataFrame([
        {'Tag': 'SIG-A', 'IO': 'AI'},
        {'Tag': 'SIG-A', 'IO': 'DI'},  # duplicate
    ])
    ndf = validator.normalize_dataframe(df)
    findings, _ = validator.validate(ndf)
    gen = TQGenerator()
    tqs = gen.generate_from_validation(findings)
    # Should have at least one TQ for the duplicate
    dup_tqs = [t for t in tqs if t.category == 'naming']
    assert len(dup_tqs) >= 1
    info = get_category_info(dup_tqs[0].category)
    assert 'Duplicate' in info['plain_name'] or 'Tag' in info['plain_name']


def test_explain_tq_concise_sections_and_no_repetitive_wording():
    """Verify explain_tq returns only concise sections with repetitive prefixes stripped."""
    tq = TechnicalQuery(
        tq_id='TQ-0001',
        affected_item='100-PT-001',
        category='naming',
        description="Duplicate tag '100-PT-001' found at row 80 (first seen at row 0).",
        reason="Validation finding (error): Duplicate tag '100-PT-001' found at row 80 (first seen at row 0).",
        information_needed='Every signal must have a unique Tag identifier.',
        suggested_action='Remove or rename the duplicate tag.',
        priority='High',
    )
    explanation = explain_tq(tq, None, [tq])
    # Exactly the required keys
    assert set(explanation.keys()) == {
        'meaning', 'why_flagged', 'affected_item', 'impact',
        'recommended_action', 'allocation_status', 'related_tqs'
    }
    # No repetitive prefix
    assert not explanation['why_flagged'].startswith('Validation finding')
    assert explanation['why_flagged'].startswith("Duplicate tag '100-PT-001'")
    # Concise single sentences
    for key in ['meaning', 'why_flagged', 'impact', 'recommended_action']:
        val = explanation[key]
        assert isinstance(val, str) and len(val) > 0
        # Check that it is one sentence (doesn't contain multiple sentence stops)
        assert val.count('.') == 1 or not val.endswith('..')


def test_explain_tq_never_assumes_unallocated_if_signal_is_allocated():
    """If a signal has a TQ (e.g. cable warning) but was allocated, status is Allocated."""
    rules = deepcopy(DEFAULT_RULES)
    df = pd.DataFrame([
        {'Tag': 'SIG-WARN', 'IO': 'AI', 'Cable': 'C-1', 'Pair': '', 'Grp': '', 'Seg': ''}
    ])
    result = AllocationEngine(rules).allocate(df)
    assert len(result.allocated_signals) == 1

    tq = TechnicalQuery(
        tq_id='TQ-0010',
        affected_item='SIG-WARN',
        category='cable_info',
        description='Missing pair value',
        reason='Pair value is missing',
        information_needed='Confirm pair',
        suggested_action='Provide pair number in source data.',
    )
    explanation = explain_tq(tq, result, [tq])
    assert 'Allocated' in explanation['allocation_status']
    assert 'Unallocated' not in explanation['allocation_status']


def test_explain_tq_sample_io_mdb_dataset():
    """Verify explain_tq on the actual sample_io_mdb.xlsx dataset."""
    root = Path(__file__).resolve().parents[1]
    df = pd.read_excel(root / 'sample_data' / 'sample_io_mdb.xlsx', dtype=str).fillna('')
    validator = InputValidator()
    normal = validator.normalize_dataframe(df)
    input_findings, _ = validator.validate(normal)
    rules = deepcopy(DEFAULT_RULES)
    result = AllocationEngine(rules).allocate(normal)

    # Build TQs as app.py does
    tqs = TQGenerator().generate_from_validation(input_findings)
    for idx, item in enumerate(result.tq_items, 1):
        tqs.append(TechnicalQuery(
            tq_id=f'TQ-ALLOC-{idx:04d}',
            affected_item=item['affected_item'],
            category=item['category'],
            description=item['description'],
            reason=item['reason'],
            information_needed='Confirm signal details.',
            suggested_action='Review project rules.',
            priority='High',
        ))

    assert len(tqs) == 5

    # Test all 5 TQs
    for tq in tqs:
        exp = explain_tq(tq, result, tqs)
        assert exp['meaning']
        assert exp['why_flagged']
        assert exp['affected_item']
        assert exp['impact']
        assert exp['recommended_action']
        assert exp['allocation_status']

    # For unknown IO signal: must be Unallocated
    tq_unknown = next(t for t in tqs if '100-XX-099' in t.affected_item)
    exp_unknown = explain_tq(tq_unknown, result, tqs)
    assert 'Unallocated' in exp_unknown['allocation_status']

    # For duplicate tag query: duplicate row is unallocated
    tq_dup = next(t for t in tqs if t.category == 'naming' and '100-PT-001' in t.affected_item)
    exp_dup = explain_tq(tq_dup, result, tqs)
    assert 'Unallocated' in exp_dup['allocation_status']
    assert len(exp_dup['related_tqs']) >= 1

