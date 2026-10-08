"""Source-bound longitudinal hippocampal statistics, not patient normal ranges."""
import hashlib
import html
import json
from pathlib import Path

FOLDER = 'workflow_sources/paper_reading_reviews/'
SOURCE = FOLDER + 'hippocampal_006_010_reported_statistics.json'
MANIFEST = FOLDER + 'hippocampal_006_010_fulltext_review.json'
RAW = {
    FOLDER+'raw/barnes_2007_fluid_registered.pdf': '0eb37a7d6b88e54220ce73b38a190bb85ab74f815654f6418902574ef178184b',
    FOLDER+'raw/morra_2009_pmc_article.txt': 'f7b29ca928dde023b60b687e2e96b2920574292c1d781658013cc045df982393',
}
DOIS = {'ROI-006':'10.1097/rct.0b013e31802f4139',
        'ROI-010':'10.1016/j.neuroimage.2008.10.043'}
SCOPES = {
    'ROI-006': ('Verified bilateral-averaged hippocampal annual atrophy rates, not separate left/right volumes. '
                'Log-scale analysis, back-transformed means and variance-transformed SD; manual MIDAS, '
                'fluid propagation with intensity thresholding, and Jacobian integration are separate methods. '
                'Serial MRI required; equivalence to current FreeSurfer processing is not validated. Context only.'),
    'ROI-010': ('Verified annual hippocampal volume-loss means and group-mean 95% confidence intervals, not SD '
                'or individual prediction intervals. Side-specific rates are graphed, but exact side values and '
                'the aggregation of the three quoted means are not specified in the inspected numerical text. '
                'AdaBoost/auto-context segmentation after 9-parameter ICBM alignment is not current FreeSurfer. '
                'Serial MRI required; context only, no individual diagnosis or numerical patient comparison.'),
}


def records():
    rows = []
    for method,control,ad in [('manual MIDAS',(1.31,2.00),(5.09,3.59)),
                              ('fluid propagation with intensity thresholding',(0.89,0.75),(5.34,3.43)),
                              ('Jacobian integration',(0.56,1.12),(3.55,2.70))]:
        for group,(mean,sd),n in [('Control',control,55),('AD',ad,32)]:
            rows.append(dict(paper_code='ROI-006',diagnosis=group,mean=mean,standard_deviation=sd,
                cohort_sample_size=n,hemisphere='bilateral_average_rate',processing_method=method,
                statistic_type='back_transformed_mean_and_transformed_sd',
                confidence_interval_lower=None,confidence_interval_upper=None,
                source_location='Table 3 p.584; Statistical Analysis p.583; Discussion p.586',
                raw_reported_text=f'{mean:.2f} ({sd:.2f})',interval_months=None))
    for group,mean,width,n in [('Control',.66,.96,148),('MCI',3.12,.79,245),('AD',5.59,1.44,97)]:
        rows.append(dict(paper_code='ROI-010',diagnosis=group,mean=mean,standard_deviation=None,
            cohort_sample_size=n,hemisphere='not_specified_for_quoted_group_summary',
            processing_method='AdaBoost cascade / auto-context model; 9-parameter ICBM-53 registration',
            statistic_type='mean_and_group_mean_95ci',confidence_interval_half_width=width,
            confidence_interval_lower=round(mean-width,2),confidence_interval_upper=round(mean+width,2),
            source_location='Results / Volumetric analyses, paragraph referring to Figure 3',
            raw_reported_text=f'{mean:.2f}%/year [95% CI: +/-{width:.2f}%]',interval_months=12))
    for i,row in enumerate(rows,1):
        code=row['paper_code']
        row.update(record_id=f'{code}-FULLTEXT-{i:02d}',doi=DOIS[code],roi_name='hippocampus',
            imaging_metric='hippocampal_annual_atrophy',unit='percent/year',reported_value=row['mean'],
            source_url='https://doi.org/'+DOIS[code],
            source_check_status='primary_fulltext_statistics_verified_context_only',
            human_review_status='not_assigned_by_assistant',extraction_status='fulltext_values_verified',
            numeric_use=False,patient_numeric_use=False,comparison_compatible=False,
            applicability_note=SCOPES[code])
    return rows


def manifest():
    return dict(review_type='assistant_primary_source_check_not_human_signoff',source_sha256=RAW,
        statistics_count=9,source_scope={
            'ROI-006': 'User PDF pp.581-587; Methods, Tables 1-3, Results, Figures 1-4 and Discussion.',
            'ROI-010': 'PMC main article: Methods, Results, Discussion, Tables 1-9 and figure captions. Exact plot coordinates not digitized.'},
        findings={
            'ROI-006': {
                'hemisphere': 'Discussion p.586 explicitly says left and right atrophy rates were averaged; Methods p.583 and Figure 2 say left/right together. Do not label as a bilateral total volume.',
                'analysis': 'log(follow-up volume/baseline volume)/interval; reported means back-transformed, SD via variance transformation. Exact reconstruction is not attempted.',
                'cohort': '32 probable AD: 14 familial, 18 sporadic; 55 controls. Twelve AD diagnoses confirmed (two postmortem, ten pathogenic familial mutations), not all 32.',
                'scan_interval': 'Table 2 reports AD 450 (305) days and controls 449 (275) days; rates are annualized, not fixed 12-month changes.',
                'processing': 'MIDAS brain masks; 9-df global and 6-df local registration; baseline manual hippocampi; fluid propagation with thresholding at 70% mean brain intensity; Jacobian integration is distinct.',
                'mean_definition': 'Do not silently treat reported back-transformed group means as ordinary arithmetic means for individual Gaussian reference intervals.',
                'validation': 'Reported sensitivities 56/84/72 percent at 91 percent specificity are study-sample discrimination, not calibrated individual probabilities or external validation.'},
            'ROI-010': {
                'dispersion': 'Results gives 95% CI half-widths 0.96/0.79/1.44 for Control/MCI/AD. These are not SD; no explicit numeric SD for these three means was found in inspected main article.',
                'intervals': 'Derived endpoint arithmetic only: Control -0.30 to 1.62; MCI 2.33 to 3.91; AD 4.15 to 7.03 percent/year. Do not truncate the negative confidence endpoint.',
                'table_scope': 'Tables 1-2 have demographic/cognitive SD, Tables 3-8 correlations and Table 9 permutation p values. None supplies numeric SD for the three quoted volume-loss means.',
                'metric_scope': 'Volume loss and surface radial-distance change are distinct; surface p maps are not whole-ROI volume distributions.',
                'correction_scope': 'Surface permutation correction and exploratory covariate Bonferroni correction cannot be transferred to the group-mean confidence intervals.',
                'cohort_method': '490 testing subjects (97 AD,245 MCI,148 controls), 980 baseline/follow-up scans at 1.5T. Separate training set 21 subjects / 42 scans. Not FreeSurfer.',
                'hemisphere': 'Do not infer that the unlabelled 0.66/3.12/5.59 summaries are unilateral values or a reproducible bilateral pooling formula.'}},
        scopes=SCOPES,duplicate_abstract_statistics_superseded=9,
        patient_comparison_enabled=False,human_signatures_changed=False,patient_qc_changed=False)


def verify(root=None):
    root=Path(root or Path(__file__).parent)
    if not (root/MANIFEST).exists():
        return None
    if json.loads((root/MANIFEST).read_text())!=manifest():
        raise ValueError('Hippocampal source manifest changed')
    for path,digest in RAW.items():
        if hashlib.sha256((root/path).read_bytes()).hexdigest()!=digest:
            raise ValueError('Retained hippocampal primary source changed: '+path)
    if json.loads((root/SOURCE).read_text())!=records():
        raise ValueError('Hippocampal source extraction changed')
    return manifest()


def render(root=None,code=None):
    data=verify(root)
    if data is None:
        return ''
    codes=[code] if code else list(DOIS)
    content=''
    for key in codes:
        content+='<details><summary>'+key+': verified longitudinal hippocampal statistics</summary>'
        content+='<p>'+html.escape(SCOPES[key])+'</p>'
        content+=''.join('<p>'+html.escape(v)+'</p>' for v in data['findings'][key].values())
        content+='<p><a href="https://doi.org/'+DOIS[key]+'">Primary paper</a></p>'
        content+='<table><tr><th>Group / n</th><th>Method</th><th>Reported statistic, %/year</th><th>95% CI endpoints</th></tr>'
        for row in records():
            if row['paper_code']!=key:
                continue
            ci='Not reported' if row['confidence_interval_lower'] is None else f"{row['confidence_interval_lower']:.2f} to {row['confidence_interval_upper']:.2f}"
            content+='<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in [
                row['diagnosis']+' / '+str(row['cohort_sample_size']),row['processing_method'],row['raw_reported_text'],ci])+'</tr>'
        content+='</table></details>'
    return content
