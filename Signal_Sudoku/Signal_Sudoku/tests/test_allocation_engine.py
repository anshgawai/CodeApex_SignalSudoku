from copy import deepcopy
from pathlib import Path
import pandas as pd
from core.allocation_engine import AllocationEngine
from core.rule_validator import RuleValidator
from services.configuration_service import DEFAULT_RULES

ROOT=Path(__file__).resolve().parents[1]

def test_clean_synthetic_data_allocates_every_signal_and_exports_compatible_model():
    df=pd.read_excel(ROOT/'sample_data'/'sample_io_mdb_clean.xlsx',dtype=str).fillna('')
    rules=deepcopy(DEFAULT_RULES)
    result=AllocationEngine(rules).allocate(df)
    assert result.statistics['total_signals']==len(df)
    assert len(result.allocated_signals)+len(result.unallocated_signals)==len(df)
    assert not result.unallocated_signals
    findings=RuleValidator(rules).validate(result)
    assert not [f for f in findings if f.severity=='error']

def test_a_and_b_segregation_are_not_put_on_same_cioc():
    df=pd.DataFrame([
        {'Tag':'A-1','IO':'AI','Cable':'C1','Pair':'1','Grp':'G1','Seg':'A'},
        {'Tag':'B-1','IO':'AI','Cable':'C2','Pair':'1','Grp':'G2','Seg':'B'},
    ])
    result=AllocationEngine(deepcopy(DEFAULT_RULES)).allocate(df)
    assert len(result.allocated_signals)==2
    cioc_by_tag={e['signal'].tag:e['charm_slot'].cioc_id for e in result.allocated_signals}
    assert cioc_by_tag['A-1'] != cioc_by_tag['B-1']

def test_group_that_exceeds_one_cabinet_is_flagged_not_silently_moved():
    rules=deepcopy(DEFAULT_RULES)
    rules.update(charms_per_baseplate=2,baseplates_per_cioc=1,ciocs_per_cabinet=1,keep_groups_together=True,keep_cables_together=False,enforce_segregation=False)
    df=pd.DataFrame([{'Tag':f'T{i}','IO':'AI','Cable':'','Pair':str(i),'Grp':'SAME','Seg':''} for i in range(3)])
    result=AllocationEngine(rules).allocate(df)
    assert len(result.allocated_signals)==2
    assert len(result.unallocated_signals)==1
    assert result.tq_items and result.tq_items[0]['category']=='capacity'

def test_unknown_io_type_is_unallocated_with_tq():
    df=pd.DataFrame([{'Tag':'X-1','IO':'MYSTERY','Cable':'','Pair':'','Grp':'','Seg':''}])
    result=AllocationEngine(deepcopy(DEFAULT_RULES)).allocate(df)
    assert len(result.unallocated_signals)==1
    assert result.tq_items[0]['category']=='mapping'
