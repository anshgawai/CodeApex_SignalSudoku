from pathlib import Path
from io import BytesIO
import json
import pandas as pd
import streamlit as st
from core.allocation_engine import AllocationEngine
from core.input_validation import InputValidator
from core.rule_validator import RuleValidator
from core.report_generator import ReportGenerator
from core.tq_generator import TQGenerator, TechnicalQuery
from core.revision_comparator import RevisionComparator
from core.revision_workflow import RevisionWorkflow
from services.configuration_service import ConfigurationService
from services.excel_reader import ExcelReader
from services.excel_exporter import ExcelExporter

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title='Signal Sudoku', page_icon='', layout='wide')
st.title('Signal Sudoku')
st.caption(
    'Industrial I/O signal allocation • Engineering-assistance prototype • '
    'Generated allocations require review by a qualified engineer.'
)


@st.cache_data
def read_excel_bytes(data):
    return pd.read_excel(BytesIO(data), dtype=str).fillna('')


def frame_from_upload(upload):
    if upload is None:
        return None
    return pd.read_excel(BytesIO(upload.getvalue()), dtype=str).fillna('')


def build_tqs(input_findings, allocation_result):
    tqs = TQGenerator().generate_from_validation(input_findings)
    for idx, item in enumerate(allocation_result.tq_items, 1):
        tqs.append(TechnicalQuery(
            tq_id=f'TQ-ALLOC-{idx:04d}',
            affected_item=item['affected_item'],
            category=item['category'],
            description=item['description'],
            reason=item['reason'],
            information_needed='Confirm signal details, constraints, or available hardware.',
            suggested_action='Review the signal and project rules, then rerun allocation.',
            priority='High',
        ))
    return tqs


config = ConfigurationService(str(ROOT / 'config'))
rules = config.get_rules()
reader = ExcelReader()
reporter = ReportGenerator()
exporter = ExcelExporter()
workflow = RevisionWorkflow()
comparator = RevisionComparator()

with st.sidebar:
    st.header('Project rules')
    st.caption('Changes apply to this run. Save them to reuse them next time.')
    rules['charms_per_baseplate'] = st.number_input(
        'CHARMs per baseplate', min_value=1, max_value=64, value=int(rules['charms_per_baseplate'])
    )
    rules['baseplates_per_cioc'] = st.number_input(
        'Baseplates per CIOC', min_value=1, max_value=32, value=int(rules['baseplates_per_cioc'])
    )
    rules['ciocs_per_cabinet'] = st.number_input(
        'CIOCs per cabinet', min_value=1, max_value=16, value=int(rules['ciocs_per_cabinet'])
    )
    rules['keep_groups_together'] = st.checkbox(
        'Keep groups in same cabinet', value=rules['keep_groups_together']
    )
    rules['enforce_segregation'] = st.checkbox(
        'Keep segregation classes on separate CIOCs', value=rules['enforce_segregation']
    )
    rules['keep_cables_together'] = st.checkbox(
        'Keep cable signals on same baseplate where possible', value=rules['keep_cables_together']
    )
    rules['maintain_pair_order'] = st.checkbox(
        'Order signals by cable pair', value=rules['maintain_pair_order']
    )
    rules['reserve_spare_capacity'] = st.checkbox(
        'Reserve spare capacity', value=rules['reserve_spare_capacity']
    )
    if rules['reserve_spare_capacity']:
        rules['spare_percentage'] = st.slider(
            'Spare capacity (%)', 0.0, 50.0, float(rules.get('spare_percentage', 10.0)), step=1.0
        )
    rules['default_do_subtype'] = st.selectbox(
        'Default DO hardware',
        ['normal', 'solenoid', 'relay'],
        index=['normal', 'solenoid', 'relay'].index(rules.get('default_do_subtype', 'normal')),
    )
    if st.button('Save rules', use_container_width=True):
        errors = config.validate_rules(rules)
        if errors:
            st.error('\n'.join(errors))
        else:
            config.save_rules(rules)
            st.success('Rules saved.')
    if st.button('Reset defaults', use_container_width=True):
        config.reset_to_defaults()
        st.rerun()

left, right = st.columns([3, 2])
with left:
    st.subheader('1. Upload I/O MDB')
    uploaded = st.file_uploader('Choose an Excel file', type=['xlsx', 'xlsm', 'xls'])
    use_sample = st.checkbox('Use generated synthetic sample data instead', value=uploaded is None)
    sample_path = ROOT / 'sample_data' / 'sample_io_mdb_clean.xlsx'
    if use_sample:
        if not sample_path.exists():
            st.info('Sample file not generated yet. Run: python sample_data/create_sample_data.py')
            df = None
        else:
            df = pd.read_excel(sample_path, dtype=str).fillna('')
    else:
        df = frame_from_upload(uploaded)
with right:
    st.subheader('2. Input preview')
    if df is not None:
        st.metric('Input signals', len(df))
        st.dataframe(df.head(10), use_container_width=True, hide_index=True)

if df is not None:
    validator = InputValidator()
    normal = validator.normalize_dataframe(df)
    input_findings, fatal = validator.validate(normal)
    with st.expander(f'Input checks ({len(input_findings)} findings)', expanded=bool(fatal)):
        if input_findings:
            st.dataframe(
                pd.DataFrame([f.__dict__ for f in input_findings]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.success('No input validation findings.')
    if st.button('Allocate signals', type='primary', use_container_width=True):
        errors = config.validate_rules(rules)
        if errors:
            st.error('Fix rule settings first: ' + '; '.join(errors))
        else:
            try:
                result = AllocationEngine(rules).allocate(normal)
                findings = RuleValidator(rules).validate(result)
                tqs = build_tqs(input_findings, result)
                session = workflow.start_from_allocation(
                    df=normal,
                    rules=rules,
                    allocation_result=result,
                    validation_findings=findings,
                    input_findings=input_findings,
                    tqs=tqs,
                )
                st.session_state['allocation'] = {
                    'result': result,
                    'findings': findings,
                    'tqs': tqs,
                    'df': normal,
                    'rules': rules,
                    'input_findings': input_findings,
                }
                st.session_state['revision_session'] = session
                # Clear any prior proposed revision when reallocating from scratch.
                st.session_state.pop('proposed_revision', None)
            except Exception as exc:
                st.error(f'Allocation failed: {exc}')

if 'allocation' in st.session_state:
    saved = st.session_state['allocation']
    result = saved['result']
    findings = saved['findings']
    tqs = saved['tqs']
    rules_used = saved['rules']
    input_findings = saved.get('input_findings', [])
    session = st.session_state.get('revision_session')

    st.divider()
    st.subheader('3. Results')
    m = result.statistics
    cols = st.columns(5)
    for col, label, val in zip(
        cols,
        ['Signals', 'Allocated', 'Unallocated', 'Cabinets', 'CIOCs'],
        [m['total_signals'], m['allocated'], m['unallocated'], m['cabinets'], m['ciocs']],
    ):
        col.metric(label, val)

    if m['unallocated']:
        st.warning(
            f"{m['unallocated']} signal(s) could not be allocated. "
            'Each has a technical query; review before treating this as complete.'
        )
    else:
        st.success(
            'Every signal received a slot. Review validation findings before accepting the result.'
        )

    allocation_df = reporter.generate_allocation_table(result)
    validation_df = reporter.generate_validation_report(findings)
    tq_df = reporter.generate_tq_report(tqs)
    hardware_df = reporter.generate_hardware_summary(result)
    config_df = reporter.generate_configuration_report(rules_used)

    # ----- Detected conflicts -----
    if session and session.analysis:
        st.subheader('4. Detected conflicts')
        summary = session.analysis.summary
        c1, c2, c3, c4 = st.columns(4)
        c1.metric('Source data', summary.get('source_data', 0))
        c2.metric('Assignment', summary.get('assignment', 0))
        c3.metric('Configurable rule', summary.get('configurable_rule', 0))
        c4.metric('Hard constraint', summary.get('hard_constraint', 0))
        problems_df = reporter.generate_problems_report(session.analysis.problems)
        if problems_df.empty:
            st.success('No classified conflicts beyond a clean allocation.')
        else:
            st.dataframe(problems_df, use_container_width=True, hide_index=True)
            st.caption(
                'Source data must be corrected in the MDB. Hard constraints cannot be bypassed. '
                'Configurable preferences may be reviewed below.'
            )

    tabs = st.tabs([
        'Allocation',
        'Rule checks',
        'Technical queries',
        'Hardware summary',
        'Rule Change Suggestions',
        'Proposed revision',
        'Revision comparison',
    ])

    with tabs[0]:
        st.dataframe(allocation_df, use_container_width=True, hide_index=True)
    with tabs[1]:
        if validation_df.empty:
            st.success('No rule violations found by the current validator.')
        else:
            st.dataframe(validation_df, use_container_width=True, hide_index=True)
    with tabs[2]:
        if tq_df.empty:
            st.info('No technical queries generated.')
        else:
            st.dataframe(tq_df, use_container_width=True, hide_index=True)
    with tabs[3]:
        st.dataframe(hardware_df, use_container_width=True, hide_index=True)

    with tabs[4]:
        st.write(
            'Review permissible configurable preference changes. '
            'Hard constraints (segregation, CHARM mapping, physical capacity invariants) '
            'are never suggested for weakening. Selected changes are **not** applied until you approve.'
        )
        if not session:
            st.info('Allocate signals first to generate suggestions.')
        elif session.analysis and session.analysis.summary.get('fully_valid'):
            st.success('Allocation is already valid under current rules — no rule changes needed.')
        else:
            sug_result = session.suggestion_result
            if sug_result and sug_result.no_solution_reason and not session.suggestions:
                st.warning(sug_result.no_solution_reason)
                if sug_result.hard_blockers:
                    st.write('Hard constraint blockers:')
                    st.dataframe(
                        reporter.generate_problems_report(sug_result.hard_blockers),
                        use_container_width=True,
                        hide_index=True,
                    )
            if session.suggestions:
                sug_rows = []
                for s in session.suggestions:
                    sug_rows.append({
                        'ID': s.suggestion_id,
                        'Rule': s.rule_key,
                        'Current': str(s.current_value),
                        'Proposed': str(s.proposed_value),
                        'Conflict': s.conflict_resolved,
                        'Expected impact': s.expected_impact,
                        'Warnings': '; '.join(s.warnings),
                    })
                st.dataframe(pd.DataFrame(sug_rows), use_container_width=True, hide_index=True)

                selected = st.multiselect(
                    'Select suggestions to approve',
                    options=[s.suggestion_id for s in session.suggestions],
                    format_func=lambda sid: next(
                        (
                            f"{s.suggestion_id}: {s.rule_key} "
                            f"{s.current_value} → {s.proposed_value}"
                            for s in session.suggestions if s.suggestion_id == sid
                        ),
                        sid,
                    ),
                    key='selected_suggestions',
                )
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button(
                        'Approve selected & reallocate',
                        type='primary',
                        use_container_width=True,
                        disabled=not selected,
                    ):
                        try:
                            updated = workflow.approve_and_reallocate(
                                session, selected, input_findings=input_findings
                            )
                            st.session_state['revision_session'] = updated
                            # Build proposed export artefacts
                            rev_alloc_df = reporter.generate_allocation_table(updated.revised_result)
                            rev_val_df = reporter.generate_validation_report(updated.revised_findings)
                            rev_tq_df = reporter.generate_tq_report(updated.revised_tqs)
                            rev_hw_df = reporter.generate_hardware_summary(updated.revised_result)
                            rev_cfg_df = reporter.generate_configuration_report(updated.approved_rules)
                            rules_rows = workflow.rule_change_summary_rows(updated)
                            rules_df = reporter.generate_approved_rules_report(rules_rows)
                            summary_df = reporter.generate_change_summary_report(
                                workflow.change_summary_dict(updated)
                            )
                            cmp = comparator.compare_allocations(allocation_df, rev_alloc_df)
                            cmp_df = reporter.generate_allocation_comparison_report(cmp)
                            workbook = exporter.export_proposed_revision(
                                rev_alloc_df,
                                rev_val_df,
                                rev_tq_df,
                                rev_hw_df,
                                rev_cfg_df,
                                summary_df,
                                rules_df,
                                comparison_df=cmp_df,
                                is_fully_valid=updated.is_fully_valid,
                                is_diagnostic=not updated.is_fully_valid,
                            )
                            st.session_state['proposed_revision'] = {
                                'session': updated,
                                'allocation_df': rev_alloc_df,
                                'validation_df': rev_val_df,
                                'tq_df': rev_tq_df,
                                'hardware_df': rev_hw_df,
                                'config_df': rev_cfg_df,
                                'summary_df': summary_df,
                                'rules_df': rules_df,
                                'comparison': cmp,
                                'comparison_df': cmp_df,
                                'workbook': workbook.getvalue(),
                            }
                            st.rerun()
                        except Exception as exc:
                            st.error(f'Reallocation failed: {exc}')
                with col_b:
                    if st.button('Cancel (keep original rules)', use_container_width=True):
                        workflow.cancel(session)
                        st.session_state['revision_session'] = session
                        st.session_state.pop('proposed_revision', None)
                        st.info(
                            'Cancelled. Original rules and uploaded data are unchanged. '
                            'Sidebar project rules were not permanently overwritten.'
                        )

    with tabs[5]:
        proposed = st.session_state.get('proposed_revision')
        if not proposed:
            st.info(
                'Approve rule changes in **Rule Change Suggestions** to generate a proposed revision.'
            )
        else:
            upd = proposed['session']
            if upd.is_fully_valid:
                st.success(
                    'Proposed allocation satisfies hard constraints with no unallocated signals. '
                    'Still requires qualified engineering review.'
                )
            else:
                st.error(
                    'Proposed reallocation did not produce a fully valid result. '
                    'Remaining conflicts are shown below — reconsider suggestions or fix source data. '
                    'You may download a labelled diagnostic report (not a successful revision).'
                )

            rm = upd.revised_result.statistics
            rcols = st.columns(4)
            rcols[0].metric('Allocated', rm.get('allocated', 0))
            rcols[1].metric('Unallocated', rm.get('unallocated', 0))
            rcols[2].metric('Rule changes applied', len(upd.approved_suggestions))
            rcols[3].metric('Fully valid', 'Yes' if upd.is_fully_valid else 'No')

            st.write('Approved rule changes (session only — original config file unchanged):')
            st.dataframe(proposed['rules_df'], use_container_width=True, hide_index=True)
            st.write('Proposed allocation:')
            st.dataframe(proposed['allocation_df'], use_container_width=True, hide_index=True)
            if not proposed['validation_df'].empty:
                st.write('Remaining validation findings:')
                st.dataframe(proposed['validation_df'], use_container_width=True, hide_index=True)

            fname = (
                'signal_sudoku_proposed_revision.xlsx'
                if upd.is_fully_valid
                else 'signal_sudoku_diagnostic_report.xlsx'
            )
            st.download_button(
                'Download proposed revision workbook (.xlsx)'
                if upd.is_fully_valid
                else 'Download diagnostic report (.xlsx)',
                data=proposed['workbook'],
                file_name=fname,
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                type='primary',
            )

            st.write('Original vs proposed allocation comparison:')
            st.json(proposed['comparison'].summary)
            st.dataframe(proposed['comparison_df'], use_container_width=True, hide_index=True)
            cmp_book = exporter.export_revision_report(proposed['comparison_df'])
            st.download_button(
                'Download allocation comparison report (.xlsx)',
                data=cmp_book.getvalue(),
                file_name='signal_sudoku_allocation_comparison.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )

    with tabs[6]:
        st.write(
            'Upload a later revision to compare signal tags and source fields '
            '(existing MDB-vs-MDB workflow).'
        )
        proposed = st.session_state.get('proposed_revision')
        if proposed:
            st.info(
                'A proposed revision is available. Use the **Proposed revision** tab to compare '
                'the original allocation with the automatically generated revision, '
                'or upload a separate Revision B file below.'
            )
        rev_upload = st.file_uploader(
            'Revision B Excel file', type=['xlsx', 'xlsm', 'xls'], key='revision_b'
        )
        if rev_upload:
            rev_b = frame_from_upload(rev_upload)
            rev_result = RevisionComparator().compare(
                saved['df'], InputValidator().normalize_dataframe(rev_b)
            )
            rev_rows = []
            for kind, changes in [
                ('Added', rev_result.added),
                ('Deleted', rev_result.deleted),
                ('Modified', rev_result.modified),
                ('Unchanged', rev_result.unchanged),
            ]:
                for change in changes:
                    rev_rows.append({
                        'Tag': change.tag,
                        'Change': kind,
                        'Changed fields': json.dumps(change.changed_fields, ensure_ascii=False),
                    })
            st.json(rev_result.summary)
            st.dataframe(pd.DataFrame(rev_rows), use_container_width=True, hide_index=True)
            mdb_cmp_df = reporter.generate_allocation_comparison_report(rev_result)
            mdb_book = exporter.export_revision_report(mdb_cmp_df)
            st.download_button(
                'Download MDB revision comparison (.xlsx)',
                data=mdb_book.getvalue(),
                file_name='signal_sudoku_mdb_revision_comparison.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )

    workbook = exporter.export_allocation(
        allocation_df, validation_df, tq_df, hardware_df, config_df
    )
    st.download_button(
        'Download allocation workbook (.xlsx)',
        data=workbook.getvalue(),
        file_name='signal_sudoku_allocation.xlsx',
        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        type='primary',
    )
else:
    st.info('Upload an Excel file or select the synthetic sample, then click **Allocate signals**.')
