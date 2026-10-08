"""Report-first notebook interface with optional research details."""
import html
from pathlib import Path
import pandas as pd
import ipywidgets as widgets
from IPython.display import display
from concise_case_report import build_concise_report, export_concise_report
from literature_audit import audit_html
from mri_viewer import SubjectMRIViewer
from report_table_display import table_html


def table(frame):
    from research_report_release import final_frame
    frame = final_frame(frame)
    return '<div style="overflow:auto;max-height:650px">' + table_html(frame) + '</div>'


class ReportPanel:
    def __init__(self, result):
        self.closed = False
        self.result = result
        self.subject = widgets.Dropdown(options=list(result['run_manifest']['subject_ids']), description='Subject:')
        self.report = widgets.HTML()
        self.detail = widgets.HTML()
        self.status = widgets.HTML()
        self.section = widgets.Dropdown(description='Data:', options=[
            'Inputs and sources', 'Demographics', 'Atlas audit', 'All measurements',
            'Outside 95% PI', 'Within 95% PI', 'Not calculated', 'Coverage gaps', 'Literature', 'Quality checks',
            'Evidence worklist', 'Source dispositions', 'Compatibility', 'Reference comparison summary', 'Patient source evidence', 'Subcortical reference preview'])
        self.roi = widgets.Text(description='ROI:', placeholder='Filter ROI name')
        self.paper = widgets.Dropdown(description='Paper:', options=[('All paper summaries', '')] +
            [(str(p.source_title), p.paper_id) for _, p in result['papers'].iterrows()])
        self.details = widgets.Accordion(children=[widgets.VBox([self.section, self.roi, self.paper, self.detail])],
                                         titles=('Research details (Stages 1-7)',), selected_index=None)
        self.mri = SubjectMRIViewer(result['fs_root'], Path(result['output_dir']) / 'mri_cache', 'brain.mgz')
        self.mri_button = widgets.Button(description='Open interactive MRI')
        self.mri_button.on_click(self.open_mri)
        self.mri.hide()
        if self.mri.viewer is not None:
            self.mri.viewer.close()
            self.mri.viewer = None
        from report_quality import QCPanel
        self.qc = QCPanel(result, self.subject, self.refresh)
        self.box = widgets.VBox([self.subject, self.qc.box, self.status, self.report, self.mri_button,
                                self.mri.box, self.details])
        self.subject.observe(self.refresh, names='value')
        self.section.observe(self.refresh_details, names='value')
        self.roi.observe(self.refresh_details, names='value')
        self.paper.observe(self.refresh_details, names='value')
        self.refresh()

    def refresh(self, change=None):
        if self.closed:
            return
        sid = self.subject.value
        self.mri.hide()
        if self.mri.viewer is not None:
            self.mri.viewer.close()
            self.mri.viewer = None
        self.mri.box.children = (self.mri.status,)
        self.mri.subject_id = None
        self.report.value = '<p>Loading ' + html.escape(sid) + '...</p>'
        self.status.value = ''
        try:
            self.report.value = build_concise_report(self.result, sid)
            saved = export_concise_report(self.result, sid, self.result['output_dir'])
            from report_quality import saved_report_link
            self.status.value = saved_report_link(saved, sid)
        except Exception as exc:
            self.report.value = '<p>Report unavailable for ' + html.escape(sid) + ': ' + html.escape(str(exc)) + '</p>'
            raise
        self.refresh_details()

    def refresh_details(self, change=None):
        if self.closed:
            return
        r, sid, view = self.result, self.subject.value, self.section.value
        self.paper.layout.display = '' if view == 'Inputs and sources' else 'none'
        self.roi.disabled = view in ('Inputs and sources', 'Demographics', 'Quality checks', 'Evidence worklist', 'Reference comparison summary')
        if view == 'Coverage gaps':
            from report_quality import coverage_html
            self.roi.disabled = True
            self.detail.value = coverage_html(r, sid)
            return
        if view == 'Subcortical reference preview':
            from potvin_subcortical import preview
            try:
                frame = preview(r, sid)
                if self.roi.value:
                    frame = frame.loc[frame.roi_name.str.contains(self.roi.value, case=False, regex=False)]
                self.detail.value = '<h4>Potvin mmc2 reference audit | ' + html.escape(sid) + '</h4><p>Eligible four-model comparisons are included in main counts. Calc formula validation is not clinical validation; segmentation QC remains required.</p>' + table(frame)
            except (OSError, ValueError, ImportError) as exc:
                self.detail.value = '<p>Subcortical reference unavailable: ' + html.escape(str(exc)) + '</p>'
            return
        if view == 'Patient source evidence':
            from patient_evidence_ledger import ledger
            frame = ledger(r, sid)
            if self.roi.value:
                frame = frame.loc[frame.roi_name.astype(str).str.contains(self.roi.value, case=False, regex=False)]
            self.detail.value = '<h4>Patient source evidence | ' + html.escape(sid) + '</h4>' + table(frame)
            return
        if view in ('Evidence worklist', 'Source dispositions', 'Compatibility', 'Reference comparison summary'):
            from evidence_readiness import worklist, review_queue, reference_checks, differential
            frame = {'Evidence worklist': lambda: worklist(r), 'Source dispositions': lambda: review_queue(r),
                     'Compatibility': lambda: reference_checks(r, sid), 'Reference comparison summary': lambda: differential(r, sid)}[view]()
            if 'roi_name' in frame and self.roi.value and not self.roi.disabled:
                frame = frame.loc[frame.roi_name.astype(str).str.contains(self.roi.value, case=False, regex=False)]
            self.detail.value = '<h4>' + html.escape(view + ' | ' + sid) + '</h4>' + table(frame)
            return
        if view == 'Inputs and sources':
            papers = r['papers'].copy()
            links = r['links']
            used = links.loc[links.subject_id.eq(sid)].groupby('paper_id').evidence_id.nunique() if not links.empty else pd.Series(dtype=int)
            papers['used_for_subject_qualitative'] = papers.paper_id.map(used).fillna(0).astype(int)
            from zheng_exploratory import compare
            import json
            path = Path(r['project_dir']) / 'workflow_sources/paper_reading_reviews/zheng_2023_supplement_statistics.json'
            from comparison_atlas import comparison_features
            from reference_focus import pd_only
            comparison = compare(comparison_features(r).to_dict('records'), json.loads(path.read_text()), sid) if path.exists() and not pd_only(r) else {'features': []}
            papers['paired_features_exploratory'] = papers.doi.map({'10.1371/journal.pone.0279574': len(comparison['features'])}).fillna(0).astype(int)
            columns = ['source_title', 'doi', 'unique_evidence_rows', 'quantitative_records', 'reported_statistic_records', 'qualitative_records',
                       'method_records', 'human_accepted_rows', 'used_for_subject_qualitative',
                       'paired_features_exploratory', 'zero_evidence_reason']
            detail = audit_html(r['literature_audit'], self.paper.value) if self.paper.value else '<p>Select a paper to inspect its extracted records and source provenance.</p>'
            pd_source = ''
            from reference_focus import pd_table
            from workflow_audit import source_coverage
            comparisons = pd_table(r, sid)
            papers = source_coverage(r, sid)
            columns += ['connected_group_effect_records', 'matched_group_effect_features',
                            'stage_reference_records', 'matched_stage_features', 'zero_match_reason']
            columns += ['additional_quantitative_records', 'additional_descriptive_comparisons']
            columns = [column for column in columns if column in papers]
            from zero_paper_review import notebook_review_url, review_html
            selected_review = papers.loc[papers.paper_id.eq(self.paper.value)]
            if len(selected_review):
                detail = review_html(selected_review.iloc[0].to_dict()) + detail
            if not comparisons.empty:
                pd_source = ('<p>Selected comparison source: <a href="https://doi.org/10.1002/mds.28706">'
                             'Laansma et al. / ENIGMA PD</a>: ' + str(len(comparisons)) +
                             ' group-effect reference rows checked; Potvin supplies normative baselines. '
                             'Group effects are counted separately from general registry extractions.</p>')
                selected = papers.loc[papers.paper_id.eq(self.paper.value)]
                if len(selected) and selected.iloc[0].doi == '10.1002/mds.28706':
                    detail = ('<h4>Connected PD group-effect evidence and provenance</h4>' +
                              table(comparisons) + '<details><summary>General literature registry '
                              '(separate record store)</summary>' + detail + '</details>')
            review_link = ('<p><a target="_blank" href="' + html.escape(notebook_review_url(r['project_dir']), quote=True) + '">'
                           'Review zero-count papers individually</a></p>')
            self.detail.value = '<h4>Inputs</h4>' + table(r['preflight']) + '<h4>Source catalog and evidence contribution</h4>' + review_link + pd_source + table(papers[columns]) + '<p>unique_evidence_rows counts the general literature registry only; connected_group_effect_records counts the separate ENIGMA PD reference store; additional_quantitative_records counts the other PD table store. A zero in a PD-specific column does not mean an AD/method paper has no data. Patient match counts are different from extraction counts. These are not independent votes. Approval does not create missing evidence.</p>' + detail
            return
        key = {'Demographics': 'features', 'Atlas audit': 'translated', 'Literature': 'links', 'Quality checks': 'checks'}.get(view, 'normative')
        frame = r[key].copy()
        if 'subject_id' in frame:
            frame = frame.loc[frame.subject_id.eq(sid)]
        if view == 'Demographics':
            cols = [c for c in ['subject_id', 'age', 'sex', 'estimated_total_intracranial_volume', 'scanner_field_strength', 'scanner_manufacturer'] if c in frame]
            frame = frame[cols].drop_duplicates()
        if view in ('Outside 95% PI', 'Within 95% PI', 'Not calculated'):
            if view == 'Not calculated':
                frame = frame.loc[frame.calculation_status.ne('calculated')]
            else:
                statuses = ['within_95pi'] if view == 'Within 95% PI' else ['below_95pi', 'above_95pi']
                frame = frame.loc[frame.calculation_status.eq('calculated') & frame.range_status.isin(statuses)]
        field = next((c for c in ('roi_name', 'source_roi_name') if c in frame), None)
        if field and self.roi.value and not self.roi.disabled:
            frame = frame.loc[frame[field].astype(str).str.contains(self.roi.value, case=False, regex=False)]
        self.detail.value = '<h4>' + html.escape(view + ' | ' + sid) + '</h4><p>' + str(len(frame)) + ' rows. Measurement counts use ROI x hemisphere x metric.</p>' + table(frame)

    def show(self):
        display(self.box)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.qc.close()
        self.subject.unobserve(self.refresh, names='value')
        for widget in (self.section, self.roi, self.paper):
            widget.unobserve(self.refresh_details, names='value')
        self.mri_button.on_click(self.open_mri, remove=True)
        self.mri_button.disabled = True
        self.mri.hide()
        if self.mri.viewer is not None:
            self.mri.viewer.close()
            self.mri.viewer = None
        self.report.value = self.detail.value = ''
        self.status.value = '<p>This panel is inactive. Run the entry cell again.</p>'
        self.box.close()

    def open_mri(self, _=None):
        if not self.closed:
            self.mri.show(self.subject.value)
