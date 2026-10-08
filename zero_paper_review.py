"""Source-by-source audit; deliberately does not change patient evidence or QC."""
import html
import json
import os
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from literature_audit import build_literature_audit, normalize_doi

# Scope describes only the source sections actually inspected, not full-paper approval.
# Each entry: inspected source, location/scope, finding, action, primary URL.
REVIEWS = {
    'DIS-001': ('Full-text search', 'Diagnostic framework and imaging-supported criteria', 'PPA classification requires a language phenotype; diagnostic criteria are not regional normal ranges.', 'Retain clinical context; do not convert language-disorder subtypes into AD/PD volume classifications.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC3059138/'),
    'DIS-002': ('Full-text search', 'Abstract, introduction and revised criteria', 'Possible/probable bvFTD classifications combine clinical, functional and imaging findings, not a single MRI metric.', 'Retain diagnostic-criteria context; zero matches do not mean the paper has no value.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC3170532/'),
    'DIS-003': ('Official data page', 'OASIS dataset documentation', 'A data portal is not a group-mean database; OASIS-3 and this project\'s OASIS-1 are different cohorts.', 'Use for data provenance only; do not label this project\'s OAS1 cases as OASIS-3.', 'https://sites.wustl.edu/oasisbrains/'),
    'DIS-004': ('Full-text search', 'Abstract and introduction', 'Structural covariance/network scores are not single-gyrus volume or thickness abnormalities.', 'Retain network context; reproduce the network method before comparing equivalent metrics.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC3776065/'),
    'DIS-005': ('Full-text search', 'Methods and discussion', 'The cholinergic basal forebrain has a dedicated anatomical definition; standard aseg has no fully equivalent label.', 'Requires a dedicated basal-forebrain atlas and longitudinal data; do not directly map to standard subcortical ROIs.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC4058576/'),
    'DIS-006': ('Abstract', 'PubMed abstract', 'APOE-stratified AD cortical thinning is reported, but abstract statistics are insufficient for individual regional reference intervals.', 'Qualitative context is usable; obtain full-text regional tables and check APOE groups, correction and hemispheres before integration.', 'https://pubmed.ncbi.nlm.nih.gov/19940480/'),
    'DIS-007': ('Full-text and table search', 'Results, Table 1 and statistical methods', 'Previously unextracted; 20 group mean/SD records were added by method and follow-up interval. Metrics are annual global gray-matter/whole-brain atrophy rates.', 'Usable for longitudinal study comparisons, not single-scan gyrus volumes. Trial sample-size CIs differ between the abstract and Table 1 and were not mixed into extracted values.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC3657171/'),
    'DIS-008': ('Abstract and existing-extraction check', 'PubMed abstract and 6 saved statistics', 'Hippocampal asymmetry and annual atrophy data were extracted; the asymmetry definition/interval cannot directly equal the current left-right volume difference.', 'Retain 6 statistics; do not invent SDs or single-scan individual probabilities.', 'https://pubmed.ncbi.nlm.nih.gov/15785035/'),
    'DIS-009': ('Abstract and publisher preview', 'Results/Discussion; Table 2 values not obtained', 'Table 2 contains hippocampal atrophy-rate data; the paper must not be described as having no data. Complete verifiable table values are not currently available.', 'After obtaining Table 2, extract left/right/total hippocampal values, 6/12-month intervals and SDs; repeated scans are still required.', 'https://pubmed.ncbi.nlm.nih.gov/17368654/'),
    'DIS-010': ('Full-text search', 'Abstract, dataset overview and demographic table', 'MIRIAD publishes repeated MRI data for 46 AD cases and 23 controls, not calibrated FreeSurfer regional reference distributions.', 'Retain data/method provenance; cited previous findings must not be counted again as an independent new cohort.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC3809512/'),
    'DIS-011': ('Full-text search', 'Abstract and statistical analysis', 'A methods-only record does not mean regional findings are absent; the paper reports SemD/PNFA cortical thinning and FDR analysis.', 'Check normalization, phenotype and spatial level before extracting full-text regional/lobar tables; not a general AD/PD criterion.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC2827264/'),
    'DIS-012': ('Abstract and full-text table search', 'Abstract and Table 3', 'Deep/periventricular WMH visual ratings and FLAIR metrics differ from T1 aseg white-matter abnormality volumes; the study compares VaD and AD.', 'Retain vascular differential context; comparisons require matched FLAIR/rating workflows.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC4754499/'),
    'PD-ENIGMA-2021': ('Full text and existing independent-database check', 'Abstract, Methods and PD table data', 'The main-catalog zero reflects storage location; all-PD and stage-specific references are already in independent PD databases.', 'Continue using compatible regional group effects; catalog zero does not mean absent integration, and group effects are not individual probabilities.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC8595579/'),
    'PD-PPMI-2011': ('Abstract and full-text search', 'Cohort design', 'PPMI describes observational-study design and data provenance; planned enrollment counts are not observed MRI group means.', 'Use for PPMI provenance/design, not this project\'s volume comparison table.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC9014725/'),
    'QREF-001': ('Existing extraction and abstract check', 'Reviewed quantitative tables and abstract', 'Quantitative distributions and paired features are connected; extraction is not missing. Matching depends on analysis scope and metric definitions.', 'Retain existing applicability gates; do not force AD references into PD-only analyses.', 'https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0279574'),
    'QREF-002': ('Full text and existing-record check', 'Methods, Table 1 and 3 saved records', 'The 3 records describe whole-cortex mean thickness, not fractal dimension. Table 1 confirms AD/FTD/control values of 2.50 +/- 0.14, 2.50 +/- 0.12 and 2.64 +/- 0.10 mm. Whole-cortex means differ from single-gyrus metrics, and the method is CAT12. The AD-pathology group includes 18 AD and 14 amyloid-positive MCI cases.', 'Do not assign whole-cortex means to every DK gyrus; match whole-cortex definitions, processing and groups. Fractal dimension is a separate metric.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC7338220/'),
    'QREF-003': ('Full text and existing-record check', 'Methods 2.5-2.7 and 2 saved means', 'BrainGPS uses a 286-label multi-atlas approach with normalized brain size and Level 5 statistics. Existing means lack SDs; processing/normalization differs from raw aseg volumes.', 'Continue excluding direct numeric inference; check Table 2 normalization and units before use. A shared hippocampus name is insufficient.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC8788517/'),
    'QREF-004': ('Full text and existing-record check', 'Table 2, Discussion and 3 saved records', 'Visual MTA, cortical atrophy/white-matter hyperintensity ratings and cognitive correlations are not regional mm3 distributions.', 'Retain rating/cognition context; do not convert to raw-volume normal intervals.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC3166967/'),
    'READ-DESIKAN-2009': ('Existing extraction and full-text search', 'Abstract, introduction and saved regional evidence', 'Structural MRI classification and regional information are present; classification AUC is not this individual\'s disease probability.', 'Continue using applicable regional evidence; do not reimport because other columns are zero.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC2714061/'),
    'READ-DU-2007': ('Abstract and existing Table 2 check', '9 saved lobar-thickness records', 'Lobar mean thickness is not DK single-gyrus thickness; spatial levels differ.', 'Compare only after reconstructing identically defined lobar metrics; do not copy lobar means to each gyrus.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC1853284/'),
    'ROI-001': ('Official data page', 'ADNI data-access documentation', 'The data-access portal itself has no directly linkable group ROI means/SDs.', 'Use for provenance and data access, not as an extracted patient reference.', 'https://adni.loni.usc.edu/data-samples/adni-data/'),
    'ROI-002': ('Abstract', 'PubMed abstract', 'Jacobian and BSI validate repeated-scan measurements, not single-scan regional normal ranges.', 'Use for longitudinal method selection; full-text numeric data still need obtaining. Do not claim the full text has no data.', 'https://pubmed.ncbi.nlm.nih.gov/16675272/'),
    'ROI-003': ('Publisher preview', 'Abstract, introduction and methods preview', 'Thresholded VBM masks may miss severely atrophied regions; this is a masking-method issue.', 'Retain as methods/QC context; it supplies neither regional group means nor patient disease votes.', 'https://doi.org/10.1016/j.neuroimage.2008.08.045'),
    'ROI-004': ('Abstract and author-institution entry', 'Methods abstract and bibliographic information', 'MAP/PV cortical segmentation and thickness methods; additional DOI checked: 10.1007/978-3-642-04271-3_54. Not a reference for raw FreeSurfer metrics.', 'Retain methods context and DOI verification; similar atlas names do not establish processing equivalence.', 'https://pubmed.ncbi.nlm.nih.gov/20426142/'),
    'ROI-005': ('Abstract and publisher preview', 'Abstract; Results identify total left + right hippocampus', '6 method-stratified annual hippocampal volume-loss mean/SD records were added in mm3/year.', 'Usable for longitudinal comparisons with matched processing; do not compare without repeated scans.', 'https://pubmed.ncbi.nlm.nih.gov/16934913/'),
    'ROI-006': ('Abstract', 'PubMed Results', '6 method-stratified annual hippocampal percentage-atrophy mean/SD records were added; the abstract does not specify the hemisphere definition.', 'Use as longitudinal methods context; check full-text hemisphere definitions and algorithms before patient comparison.', 'https://pubmed.ncbi.nlm.nih.gov/17882036/'),
    'ROI-007': ('Abstract', 'PubMed abstract', '4 method-validation statistics were added: overlap similarity and atrophy-rate differences relative to manual measurement, not actual group volumes or atrophy rates.', 'Use only for method error/agreement; not a normal atrophy-rate distribution.', 'https://pubmed.ncbi.nlm.nih.gov/18353687/'),
    'ROI-008': ('Abstract', 'PubMed abstract', 'Head-size, age and sex adjustment methods emphasize that simply dividing by ICV may be insufficient.', 'Use for covariate design; the abstract cannot reconstruct prediction-model coefficients.', 'https://pubmed.ncbi.nlm.nih.gov/20600995/'),
    'ROI-009': ('Full text and existing-record check', 'Abstract, Discussion and 6 saved records', 'MAPS/HBSI includes baseline and annual-change statistics; data are present, but its algorithm has not been calibrated to the current FreeSurfer hippocampal definition.', 'Do not dismiss all baseline data because the study is longitudinal; verify segmentation protocols and cross-pipeline calibration before use.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC2873209/'),
    'ROI-010': ('Abstract and existing-method record check', 'Abstract', '3 HC/MCI/AD annual hippocampal atrophy rates were added; the abstract provides no corresponding SDs.', 'Use for longitudinal direction context; means cannot reconstruct individual intervals or single-scan diagnoses.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC2733354/'),
    '10.1371/journal.pone.0295069': ('Full text and independent PD-table check', 'Methods, Tables 1-7 and integrated tables', '85 quantitative records are present, with longitudinal FS7.1.1 processing and multiple-comparison thresholds. FALSE means the corrected threshold was not reached, not extraction failure.', 'Retain negative findings; do not derive single-scan changes without follow-up/version matching.', 'https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0295069'),
    '10.1093/brain/awu036': ('Abstract and existing-table/source-issue check', 'Abstract, 44 integrated records and existing source issues', 'Data are in an independent PD database; longitudinal changes and vertex clusters are not single-ROI baseline means. Existing sign ambiguities are not automatically resolved by this check.', 'Respect follow-up/metric definitions; previously excluded source conflicts remain excluded.', 'https://pubmed.ncbi.nlm.nih.gov/24613932/'),
    '10.1093/brain/awv211': ('Full text and independent PD-table check', 'Methods, Results and 84 integrated records', '42 baseline and 42 change statistics are in an independent database; compatible raw subcortical baseline values support descriptive group comparisons.', 'Distinguish baseline from follow-up; without change data, retain only compatible baseline descriptions.', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC4671477/'),
    '10.1371/journal.pone.0148852': ('Full text and independent PD-table check', 'Tables 2-4 and Methods', '25 records are present; ventricles use log-volume, right inferior frontal surface area uses a pial definition, and vertex clusters are not complete ROIs.', 'Retain context; do not calculate current raw-volume differences without calibration of transformations/surface-area definitions.', 'https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0148852'),
}


def review_for(paper):
    doi = normalize_doi(paper.get('doi'))
    codes = str(paper.get('legacy_codes', '')).split(' | ')
    key = next((code for code in codes if code in REVIEWS), doi)
    value = REVIEWS.get(key)
    if value is None:
        raise ValueError('Unreviewed catalog source: ' + str(paper))
    if key == 'DIS-008':
        from barnes_fulltext_review import verify
        if verify() is not None:
            value = ('Full-text methods, Table 2 and discussion check', 'User-provided full text, pp.339-343; Table 2 p.340',
                     'Confirmed manual MIDAS segmentation, the R/L definition and geometric-mean 95% CIs. Added 12 contextual statistics; 4 annual atrophy rates agree with existing records and are not counted twice.',
                     'Full-text check complete; literature context only. Manual segmentation has not been validated as equivalent to FreeSurfer; CIs are not individual normal ranges, and annual changes require repeated MRI.',
                     'https://doi.org/10.1159/000084560')
    if key == 'DIS-009':
        from dis009_fulltext_review import verify
        if verify() is not None:
            value = ('Full-text methods, Tables 1/2 and discussion check', 'User-provided full text, pp.1199-1203; Table 2 p.1201',
                     'Integrated 12 left/right/total hippocampal annualized atrophy mean/SD records at 6/12 months; AD n=36, control n=20. Six between-group tests are not 12 independent results.',
                     'Full-text check complete; longitudinal MRI and matched manual MIDAS processing are required. Retain original table values, excluding discussion direction statements that conflict with control values; not for single-scan MRI diagnosis.',
                     'https://doi.org/10.1016/j.neurobiolaging.2007.02.011')
    if key == 'DIS-006':
        from dis006_fulltext_review import verify
        if verify() is not None:
            value = ('Full-text methods, Tables 1-3 and Figures 1-2 check', 'User-provided full text, pp.476-485; Table 2 p.481, Table 3 p.482',
                     'Integrated 168 cortical-thickness mean/subgroup-difference and 95% CI records, plus 24 adjusted-volume mean/SD records. Final AD n=38 (9/23/6), control n=23; two short-interval scans were averaged, not used as follow-up atrophy rates.',
                     'Literature context only. CIs are not SDs; Control-AD differences are not AD means. APOE strata, modified FS4.0.2 processing, composite regions and adjusted volumes cannot directly define current patient reference intervals; atlas patterns cannot infer genotype or disease.',
                     'https://doi.org/10.1159/000258100')
    if key == 'DIS-011':
        from dis011_fulltext_review import verify
        if verify() is not None:
            value = ('Full-text methods, lobar table, Results and Discussion check', 'PMC full text; Table: Comparison of disease groups by naming score and cortical thickness in each lobe',
                     'Added 42 left/right frontal, temporal and parietal thickness mean/SD records. Full cohorts: SemD 44, PNFA 32, control 29; naming-stratified analyses each use 28 patients. Retain the existing methods record without recounting it as numeric data.',
                     'Cross-sectional FTLD language-subtype context, not AD/PD criteria or longitudinal stages. Table asterisks specify only p<0.05; vertex FDR 0.05 and normalized ROI analysis do not transfer to the lobar table. Modified FS4.0.3 processing and lobar aggregation are not established as equivalent to current DK single-gyrus metrics.',
                     'https://pmc.ncbi.nlm.nih.gov/articles/PMC2827264/')
    if key in ('ROI-006','ROI-010'):
        from hippocampal_fulltext_review import DOIS, verify
        if verify() is not None:
            if key == 'ROI-006':
                value = ('Full-text methods, Table 3 and discussion check', 'User PDF pp.581-587; statistics p.583, Table 3 p.584, discussion p.586',
                         'Six means/SDs agree with the abstract; the full text explicitly averages left/right hippocampal atrophy rates. Means are back-transformed after log analysis and SDs are variance-transformed; these are neither unilateral volumes nor bilateral volume sums.',
                         'Integrated into the main catalog, replacing separate abstract extractions to avoid double counting. Longitudinal methods context only; the three methods are not interchangeable and require calibration before comparison with current single-scan FreeSurfer data.',
                         'https://doi.org/'+DOIS[key])
            else:
                value = ('Full-text methods, Results, Tables 1-9 and discussion check', 'PMC full text; Results / Volumetric analyses and Figure 3 paragraphs',
                         'Confirmed Control/MCI/AD means of 0.66/3.12/5.59 %/year and 95% CI half-widths of 0.96/0.79/1.44, not SDs. No numeric SDs for these three means were found in the main text; cognitive-score SDs cannot substitute.',
                         'Integrated three means and group-mean CIs; do not reverse-engineer SDs or construct individual intervals. Do not guess the hemispheric aggregation formula; AdaBoost/ACM is not equivalent to current FreeSurfer, and single MRI scans cannot yield atrophy rates.',
                         'https://doi.org/'+DOIS[key])
    if key == 'ROI-008':
        from covariate_fulltext_review import verify
        if verify() is not None:
            value = ('Full-text methods, Tables 1-3 and discussion check', 'User PDF pp.1244-1255; Table 1 p.1247, Table 2 p.1248, Table 3 p.1253',
                     'Integrated 56 covariate effects and 95% CIs as printed. The TIV column gives power exponents, and age effects are cross-sectional associations. The PDF prints a female count of 4 and contains some table/text conflicts; original values are retained with separate notes.',
                     'Adjustment-method context only, not an individual prediction model. Complete intercepts, residuals and prediction parameters are missing; CIs are not SDs or normal ranges, and modified FS4.1.0 processing requires calibration before transfer. Do not silently correct source issues or use them for disease classification.',
                     'https://doi.org/10.1016/j.neuroimage.2010.06.025')
    return dict(review_key=key, source_review_scope=value[0], source_location=value[1],
                finding=value[2], permitted_use=value[3], reviewed_source_url=value[4],
                review_type='assistant_source_check_not_human_signoff')


def new_statistics():
    """Explicitly typed supplementary extractions, never patient-link candidates."""
    rows = []
    dois = {'DIS-007':'10.1016/j.neurobiolaging.2010.11.001',
            'ROI-005':'10.1016/j.neurobiolaging.2006.07.008',
            'ROI-006':'10.1097/rct.0b013e31802f4139',
            'ROI-007':'10.1016/j.neuroimage.2008.01.012',
            'ROI-010':'10.1016/j.neuroimage.2008.10.043'}

    def add(code, group, metric, method, mean, sd, unit, n, location, interval=None, side=None):
        rows.append(dict(record_id=f'{code}-{len(rows)+1:02d}', review_key=code,
            diagnosis=group, imaging_metric=metric, measurement_method=method,
            mean=mean, standard_deviation=sd, unit=unit, sample_size=n,
            source_location=location, interval_months=interval, hemisphere=side,
            source_url=REVIEWS[code][4], doi=dois[code], source_check_status='source_value_verified',
            human_review_status='not_assigned_by_assistant', comparison_compatible=False,
            patient_numeric_use=False, confidence_interval_lower=None, confidence_interval_upper=None))

    for interval, values in [(6, [(0.86,4.24,2.20,2.66),(-0.01,1.97,2.31,2.60),
                                  (0.42,0.47,1.77,1.37),(0.51,0.57,1.67,1.26),(0.34,0.89,2.03,1.63)]),
                              (12, [(0.92,2.21,2.37,2.86),(0.49,1.19,2.76,1.64),
                                   (0.46,0.27,2.01,0.96),(0.64,0.44,1.99,0.91),(0.67,0.82,2.72,1.25)])]:
        methods = ['SPM5 segmentation/subtraction all subjects', 'SPM5 segmentation/subtraction excluding outliers',
                   'Jacobian integration', 'BBSI', 'SIENA']
        for i, (method, pair) in enumerate(zip(methods, values)):
            metric = 'global_gray_matter_annual_atrophy' if i < 3 else 'whole_brain_annual_atrophy'
            for group, mean, sd, n in [('Control',pair[0],pair[1],18 if i == 1 else 19),
                                       ('AD',pair[2],pair[3],36 if i == 1 else 37)]:
                add('DIS-007',group,metric,method,mean,sd,'percent/year',n,'Table 1',interval)
    for method, control, ad in [('manual',(18.1,53.5),(174.6,106.5)),
                                ('semi-automated HBSI',(15.3,50.2),(159.4,101.2)),
                                ('automated HBSI',(11.3,50.4),(172.1,123.1))]:
        for group, pair, n in [('Control',control,19),('AD',ad,36)]:
            add('ROI-005',group,'hippocampal_annual_volume_loss',method,*pair,'mm3/year',n,
                'Abstract; publisher Results identifies total left + right',side='bilateral_total')
    for method, control, ad in [('manual',(1.31,2.00),(5.09,3.59)),
                                ('fluid propagation',(0.89,0.75),(5.34,3.43)),
                                ('Jacobian',(0.56,1.12),(3.55,2.70))]:
        for group, pair, n in [('Control',control,55),('AD',ad,32)]:
            add('ROI-006',group,'hippocampal_annual_atrophy',method,*pair,'percent/year',n,'Abstract Results')
    for group, n, sim, diff in [('Control',19,(0.69,0.05),(0.03,1.29)),('AD',36,(0.72,0.06),(0.48,2.44))]:
        add('ROI-007',group,'voxel_similarity','automated vs manual',*sim,'unitless',n,'Abstract')
        add('ROI-007',group,'atrophy_rate_difference_from_manual','BSI vs manual',*diff,'percent',n,'Abstract; not a group atrophy rate')
    for group, mean, n in [('Control',0.66,148),('MCI',3.12,245),('AD',5.59,97)]:
        add('ROI-010',group,'hippocampal_annual_atrophy','automated AdaBoost mapping',mean,None,'percent/year',n,'Abstract',12)
    from hippocampal_fulltext_review import verify
    if verify() is not None:
        rows = [r for r in rows if r['review_key'] not in ('ROI-006','ROI-010')]
    return rows


def catalog(root, baseline=None):
    root = Path(root)
    papers = build_literature_audit(root)['papers'].to_dict('records')
    extra = json.loads((root / 'workflow_sources/Disease/PD/reviewed_pd_quantitative_tables.json').read_text())
    for source in extra['sources']:
        papers.append(dict(source_title=source.get('paper', source.get('source_title', '')),
                           doi=source['doi'], legacy_codes='', unique_evidence_rows=0,
                           additional_quantitative_records=len(source['records'])))
    if baseline:
        previous = json.loads(Path(baseline).read_text())
        def identity(p):
            doi = normalize_doi(p.get('doi'))
            return doi if doi.startswith('10.') else p.get('paper_id')
        by_id = {identity(p): p for p in previous}
        if len(by_id) != len(previous):
            raise ValueError('Duplicate source identity in patient baseline')
        for paper in papers:
            key = identity(paper)
            if key in by_id:
                paper.update(by_id[key])
    stats = new_statistics()
    fields = ['matched_group_effect_features','matched_stage_features','used_for_subject_qualitative',
              'paired_features_exploratory','additional_descriptive_comparisons']
    for paper in papers:
        paper.update(review_for(paper))
        paper['new_source_verified_statistics'] = sum(s['review_key'] == paper['review_key'] for s in stats)
        paper['patient_match_total'] = sum(float(paper.get(f, 0) or 0) for f in fields) if baseline else None
        paper['baseline_subject'] = 'OAS1_0003_MR1' if baseline else 'No patient baseline loaded'
    if len(papers) != len(REVIEWS) or len({p['review_key'] for p in papers}) != len(papers):
        raise ValueError('Review inventory has missing or duplicate papers')
    return papers, stats


def review_html(paper):
    review = review_for(paper)
    escape = html.escape
    content = ('<p><b>Source check scope:</b> ' + escape(review['source_review_scope'] + ' / ' + review['source_location']) +
            '</p><p>' + escape(review['finding']) + '</p><p>' + escape(review['permitted_use']) +
            '</p><p><a target="_blank" rel="noopener" href="' + escape(review['reviewed_source_url'], quote=True) +
            '">Checked source</a>. Source check is not a human signoff.</p>')
    if review['review_key'] == 'DIS-008':
        from barnes_fulltext_review import render
        content += render()
    if review['review_key'] == 'DIS-009':
        from dis009_fulltext_review import render
        content += render()
    if review['review_key'] == 'DIS-006':
        from dis006_fulltext_review import render
        content += render()
    if review['review_key'] == 'DIS-011':
        from dis011_fulltext_review import render
        content += render()
    if review['review_key'] in ('ROI-006','ROI-010'):
        from hippocampal_fulltext_review import render
        content += render(code=review['review_key'])
    if review['review_key'] == 'ROI-008':
        from covariate_fulltext_review import render
        content += render()
    return content


def notebook_review_url(project_dir):
    prefix = os.environ.get('JUPYTERHUB_SERVICE_PREFIX')
    path = Path('outputs/literature_zero_review_20261004/ZERO_PAPER_REVIEW.html')
    if prefix:
        relative = Path(project_dir).resolve().relative_to(Path.home()) / path
        return prefix.rstrip('/') + '/files/' + quote(relative.as_posix())
    return path.as_posix()


def patient_match_inventory(root):
    """Read existing exports only; no processing or disease inference is run."""
    rows = []
    columns = ['matched_group_effect_features','matched_stage_features','used_for_subject_qualitative',
               'paired_features_exploratory','additional_descriptive_comparisons']
    for case in sorted((Path(root) / 'cases').glob('*/config.json')):
        sid = case.parent.name
        reports = list((Path(root) / 'outputs' / sid).glob('*/concise_reports/' + sid + '_source_coverage.csv'))
        if not reports:
            rows.append(dict(subject_id=sid, source_title='', match_total=None,
                             zero_reason='No saved coverage report; not a zero evidence finding'))
            continue
        report = max(reports, key=lambda p:p.stat().st_mtime_ns)
        for paper in pd.read_csv(report).fillna('').to_dict('records'):
            review = review_for(paper)
            total = sum(float(paper.get(k,0) or 0) for k in columns)
            rows.append(dict(subject_id=sid, source_title=paper['source_title'], doi=paper.get('doi',''),
                match_total=total, zero_reason=review['finding'] if total == 0 else '',
                permitted_use=review['permitted_use'], saved_coverage_file=str(report.relative_to(root))))
    return rows


def publish(root, baseline=None):
    root = Path(root)
    papers, stats = catalog(root, baseline)
    out = root / 'outputs/literature_zero_review_20261004'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'paper_reviews.json').write_text(json.dumps(papers, ensure_ascii=False, indent=2))
    (out / 'new_reported_statistics.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2))
    pd.DataFrame(papers).to_csv(out / 'paper_reviews.csv', index=False)
    pd.DataFrame(stats).to_csv(out / 'new_reported_statistics.csv', index=False)
    matches = patient_match_inventory(root)
    pd.DataFrame(matches).to_csv(out / 'patient_source_matches.csv', index=False)
    zero_extracted = sum(not p.get('unique_evidence_rows',0) for p in papers)
    zero_matches = sum(p['patient_match_total'] == 0 for p in papers) if baseline else None
    cards = []
    for i, p in enumerate(papers, 1):
        esc = lambda value: html.escape(str(value), quote=True)
        counts = ('Main-catalog records: ' + str(p.get('unique_evidence_rows',0)) + '; All-PD independent database: ' +
                  str(p.get('connected_group_effect_records',0)) + '; Stage-specific PD database: ' +
                  str(p.get('stage_reference_records',0)) + '; Other independent PD database: ' +
                  str(p.get('additional_quantitative_records',0)) + '; Supplementary extractions: ' + str(p['new_source_verified_statistics']))
        selected = [s for s in stats if s['review_key'] == p['review_key']]
        cols = ['diagnosis','imaging_metric','measurement_method','mean','standard_deviation','unit',
                'sample_size','interval_months','hemisphere','source_location']
        table = pd.DataFrame(selected)[cols].to_html(index=False, escape=True, na_rep='Not reported') if selected else ''
        if p['review_key'] == 'DIS-008':
            from barnes_fulltext_review import render
            table += render(root)
        if p['review_key'] == 'DIS-009':
            from dis009_fulltext_review import render
            table += render(root)
        if p['review_key'] == 'DIS-006':
            from dis006_fulltext_review import render
            table += render(root)
        if p['review_key'] == 'DIS-011':
            from dis011_fulltext_review import render
            table += render(root)
        if p['review_key'] in ('ROI-006','ROI-010'):
            from hippocampal_fulltext_review import render
            table += render(root, p['review_key'])
        if p['review_key'] == 'ROI-008':
            from covariate_fulltext_review import render
            table += render(root)
        cards.append('<article><h2>' + str(i) + '. ' + esc(p['source_title']) + '</h2><p>' + esc(counts) +
                     '</p><p>Baseline patient matches: ' + esc(p['patient_match_total']) + ' (' + esc(p['baseline_subject']) +
                     ')</p><p><b>Source check scope: </b>' + esc(p['source_review_scope'] + ' / ' + p['source_location']) +
                     '</p><p><b>Review finding: </b>' + esc(p['finding']) + '</p><p><b>Permitted use: </b>' +
                     esc(p['permitted_use']) + '</p><p><a target="_blank" rel="noopener" href="' +
                     esc(p['reviewed_source_url']) + '">Checked source</a> · ' + esc(p.get('doi') or p['review_key']) +
                     '</p><div class="scroll">' + table + '</div></article>')
    page = ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Zero-count literature review</title>'
            '<style>body{font:17px Georgia,serif;max-width:1100px;margin:32px auto;padding:0 20px;background:#f6f5f0;color:#202e33}'
            'article{background:white;border-top:3px solid #34616e;padding:20px;margin:24px 0}h2{font-size:21px}p{line-height:1.7}'
            '.scroll{overflow:auto}table{border-collapse:collapse;font-size:13px}td,th{padding:8px;border:1px solid #ddd}'
            'a{color:#175969}</style><h1>Zero-count literature review</h1><p>Reviewed ' + str(len(papers)) +
            ' sources; ' + str(zero_extracted) + ' have zero main-catalog extractions (including sources in independent PD databases). ' +
            (('OAS1_0003_MR1 baseline sources with zero matches: ' + str(zero_matches) + '. ') if baseline else '') +
            'Added ' + str(len(stats)) + ' supplementary statistics, saved separately and not automatically used for patient inference.</p>'
            '<p>Interpret zero together with the column name: main-catalog records, PD-database records and patient matches are different counts. '
            'A zero in a PD column for a non-PD paper does not mean data are absent. Database counts are not independent diagnostic votes. '
            'This is an assistant source check, not human sign-off; abstract-only checks cannot be described as full-text approval.</p>'
            '<p><a href="paper_reviews.csv">Paper-by-paper review CSV</a> · <a href="new_reported_statistics.csv">Supplementary statistics CSV</a> · '
            '<a href="patient_source_matches.csv">Saved patient matches and zero-count reasons CSV</a></p>' +
            ''.join(cards) + '</html>')
    path = out / 'ZERO_PAPER_REVIEW.html'
    path.write_text(page, encoding='utf-8')
    print(json.dumps(dict(papers=len(papers), zero_registry=zero_extracted,
                         baseline_zero_matches=zero_matches, new_statistics=len(stats),
                         saved_patient_sources=len(matches), path=str(path)), ensure_ascii=False))
    return path


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline')
    args = parser.parse_args()
    publish(Path(__file__).resolve().parent, args.baseline)
