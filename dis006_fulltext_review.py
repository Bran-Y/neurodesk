"""Verified APOE-stratified context, separate from patient normative comparisons."""
import hashlib
import html
import json
from pathlib import Path

DOI = '10.1159/000258100'
TITLE = "Patterns of cortical thickness according to APOE genotype in Alzheimer's disease"
FOLDER = 'workflow_sources/paper_reading_reviews/'
SOURCE = FOLDER + 'gutierrez_galve_2009_reported_statistics.json'
MANIFEST = FOLDER + 'gutierrez_galve_2009_fulltext_review.json'
PDF = FOLDER + 'raw/gutierrez_galve_2009_000258100.pdf'
PDF_SHA = '8a042ae3c1ea93b22dd0c868097e5e5a1ec746c1c2c00c63ac0948f72284c5d6'
SCOPE = ('Verified APOE-stratified cross-sectional statistics. Table 2 contains unadjusted '
         'control thickness means and Control-minus-AD differences with 95% CI, not SD or '
         'individual prediction intervals. Table 3 volumes are adjusted to a female at mean '
         'age/head size, not raw FreeSurfer volumes. FreeSurfer 4.0.2 with modified masks '
         'and manual editing is not calibrated to this workflow; genotype cannot be inferred '
         'from MRI. Context only; no patient numerical comparison or diagnosis.')
GROUPS = [('Control',23,None),('AD_APOE4_noncarrier',9,0),
          ('AD_APOE4_heterozygote',23,1),('AD_APOE4_homozygote',6,2)]
COMPOSITES = {
    'Middle frontal': ['caudal middle frontal','rostral middle frontal'],
    'Inferior frontal': ['pars opercularis','pars orbitalis','pars triangularis'],
    'Orbitofrontal': ['lateral orbitofrontal','medial orbitofrontal'],
    'Posterior parietal': ['inferior parietal','superior parietal'],
    'Anterior cingulated gyrus': ['caudal anterior cingulate','rostral anterior cingulate'],
}
# Each Table 2 line preserves the four printed mean/lower/upper triples, including -0.00.
THICKNESS = '''lh|Superior frontal|2.24 2.17 2.30|0.19 0.07 0.31|0.13 0.05 0.22|0.23 0.10 0.36
lh|Middle frontal|2.09 2.03 2.15|0.25 0.13 0.36|0.17 0.08 0.25|0.21 0.08 0.34
lh|Inferior frontal|2.12 2.06 2.18|0.20 0.08 0.32|0.12 0.04 0.20|0.17 0.04 0.30
lh|Frontal pole|2.31 2.20 2.42|0.11 -0.08 0.29|0.08 -0.06 0.22|0.33 0.07 0.60
lh|Orbitofrontal|2.20 2.13 2.26|0.20 0.08 0.31|0.13 0.05 0.22|0.13 -0.00 0.26
rh|Superior frontal|2.21 2.16 2.26|0.13 0.02 0.23|0.10 0.02 0.19|0.27 0.17 0.38
rh|Middle frontal|2.05 2.00 2.10|0.18 0.08 0.29|0.12 0.05 0.20|0.16 0.06 0.27
rh|Inferior frontal|2.14 2.06 2.21|0.11 -0.03 0.26|0.10 -0.00 0.21|0.11 -0.04 0.25
rh|Frontal pole|2.26 2.18 2.33|0.09 -0.05 0.24|0.08 -0.03 0.20|0.12 -0.07 0.32
rh|Orbitofrontal|2.22 2.16 2.28|0.20 0.09 0.30|0.13 0.05 0.22|0.18 0.06 0.30
lh|Transverse temporal gyrus|1.86 1.77 1.96|0.16 -0.01 0.33|0.16 0.04 0.28|0.17 -0.03 0.37
lh|Superior temporal gyrus|2.17 2.12 2.23|0.33 0.22 0.43|0.27 0.19 0.36|0.32 0.17 0.46
lh|Middle temporal gyrus|2.36 2.28 2.43|0.41 0.28 0.54|0.35 0.23 0.47|0.35 0.19 0.52
lh|Inferior temporal gyrus|2.31 2.24 2.38|0.48 0.36 0.60|0.40 0.29 0.51|0.41 0.26 0.55
lh|Temporal pole|2.90 2.78 3.02|0.32 0.10 0.54|0.35 0.17 0.53|0.55 0.27 0.83
lh|Fusiform gyrus|2.26 2.21 2.31|0.38 0.28 0.49|0.32 0.23 0.40|0.32 0.20 0.44
lh|Entorhinal cortex|2.74 2.61 2.88|0.73 0.46 1.01|0.70 0.50 0.91|0.91 0.63 1.18
lh|Parahippocampal gyrus|2.00 1.90 2.10|0.24 0.05 0.42|0.19 0.05 0.32|0.24 0.03 0.45
rh|Transverse temporal gyrus|1.83 1.72 1.93|0.04 -0.13 0.22|0.02 -0.12 0.15|0.14 -0.08 0.35
rh|Superior temporal gyrus|2.14 2.07 2.20|0.19 0.07 0.31|0.18 0.09 0.27|0.25 0.10 0.40
rh|Middle temporal gyrus|2.36 2.30 2.42|0.29 0.17 0.41|0.25 0.13 0.36|0.30 0.17 0.43
rh|Inferior temporal gyrus|2.33 2.27 2.39|0.35 0.23 0.47|0.27 0.17 0.38|0.35 0.23 0.47
rh|Temporal pole|3.02 2.87 3.16|0.62 0.31 0.93|0.33 0.10 0.56|0.62 0.30 0.95
rh|Fusiform gyrus|2.28 2.21 2.35|0.37 0.25 0.50|0.27 0.18 0.37|0.33 0.19 0.48
rh|Entorhinal cortex|2.73 2.62 2.83|0.77 0.51 1.03|0.71 0.51 0.91|0.91 0.68 1.14
rh|Parahippocampal gyrus|2.11 2.01 2.21|0.32 0.13 0.51|0.25 0.12 0.38|0.34 0.12 0.56
lh|Posterior parietal|1.89 1.82 1.96|0.34 0.19 0.49|0.20 0.10 0.31|0.23 0.07 0.39
lh|Precuneus|2.01 1.94 2.07|0.28 0.12 0.44|0.21 0.10 0.32|0.20 0.06 0.35
rh|Posterior parietal|1.87 1.81 1.94|0.28 0.14 0.41|0.12 0.02 0.22|0.17 0.05 0.30
rh|Precuneus|1.99 1.94 2.05|0.26 0.09 0.42|0.19 0.09 0.28|0.18 0.07 0.29
lh|Lateral occipital|1.91 1.84 1.99|0.35 0.20 0.50|0.22 0.11 0.33|0.19 0.03 0.36
lh|Cuneus|1.68 1.62 1.73|0.27 0.17 0.37|0.14 0.03 0.24|0.18 0.07 0.30
lh|Lingual gyrus|1.82 1.76 1.88|0.30 0.18 0.42|0.15 0.06 0.24|0.17 0.05 0.29
rh|Lateral occipital|1.91 1.86 1.97|0.28 0.17 0.39|0.14 0.04 0.23|0.12 0.01 0.24
rh|Cuneus|1.67 1.60 1.74|0.21 0.09 0.34|0.09 -0.01 0.19|0.13 -0.01 0.27
rh|Lingual gyrus|1.82 1.77 1.87|0.22 0.12 0.32|0.11 0.03 0.18|0.08 -0.02 0.19
lh|Anterior cingulated gyrus|2.33 2.25 2.41|0.04 -0.10 0.18|0.05 -0.08 0.17|0.04 -0.13 0.21
lh|Posterior cingulate gyrus|2.25 2.18 2.31|0.22 0.10 0.35|0.16 0.06 0.25|0.11 -0.03 0.25
lh|Isthmus cingulate gyrus|2.34 2.25 2.42|0.45 0.30 0.59|0.35 0.23 0.48|0.26 0.09 0.43
rh|Anterior cingulated gyrus|2.33 2.25 2.42|-0.02 -0.19 0.16|0.05 -0.08 0.19|0.01 -0.18 0.20
rh|Posterior cingulate gyrus|2.23 2.17 2.29|0.21 0.08 0.33|0.14 0.06 0.23|0.16 0.02 0.30
rh|Isthmus cingulate gyrus|2.34 2.28 2.40|0.41 0.27 0.54|0.35 0.22 0.48|0.28 0.13 0.42'''
VOLUMES = [('whole_brain','not_lateralized','ml',[(1109,31),(987,55),(1006,76),(1000,69)]),
           ('lateral_ventricles','not_lateralized','ml',[(23,10),(43,16),(42,19),(40,9)]),
           ('hippocampus','lh','mm3',[(2708,277),(2086,435),(2052,348),(1833,268)]),
           ('hippocampus','rh','mm3',[(2776,269),(2241,374),(2118,386),(1936,197)]),
           ('isthmus_cingulate','lh','mm3',[(1841,249),(1395,240),(1488,282),(1690,382)]),
           ('isthmus_cingulate','rh','mm3',[(1711,185),(1331,287),(1378,270),(1454,296)])]


def records():
    rows = []
    def base(table, row, region, side, group, n, dose):
        return dict(record_id=f'DIS006-T{table}-{row:02d}-{group}',paper_code='DIS-006',
            source_title=TITLE,doi=DOI,year=2009,source_url='https://doi.org/'+DOI,
            source_location=f'Table {table}, journal p.{479+table}; n from Table 1 p.480',
            source_check_status='primary_fulltext_statistics_verified_context_only',
            extraction_status='fulltext_tables_verified',human_review_status='not_assigned_by_assistant',
            extraction_method='Primary PDF text transcribed and cross-checked against rendered tables and footnotes',
            roi_name=region,hemisphere=side,diagnosis='Control' if group=='Control' else 'AD',
            cohort_group=group,cohort_sample_size=n,apoe4_dose=dose,
            numeric_use=False,patient_numeric_use=False,comparison_compatible=False,applicability_note=SCOPE)
    for index,line in enumerate(THICKNESS.splitlines(),1):
        side,region,*triples = line.split('|')
        for (group,n,dose),triple in zip(GROUPS,triples):
            mean,lo,hi = map(float,triple.split())
            row = base(2,index,region,side,group,n,dose)
            row.update(reported_value=mean,confidence_interval_lower=lo,confidence_interval_upper=hi,
                confidence_level=.95,standard_deviation=None,unit='mm',adjustment='unadjusted',
                imaging_metric='cortical_thickness' if dose is None else 'control_minus_ad_cortical_thickness_difference',
                statistic_kind='control_mean' if dose is None else 'mean_group_difference',
                reported_text=triple,positive_difference_means='Lower cortical thickness in AD',
                measurement_method='FreeSurfer 4.0.2; modified masks; manual editing; 20 mm smoothing for vertex maps',
                composite_components=COMPOSITES.get(region,[]),composite_weights=None,
                p_value=None,corrected_significance_status='Not assigned per ROI; Table 2 CI is not Figure 1 vertex FDR status')
            rows.append(row)
    for index,(region,side,unit,pairs) in enumerate(VOLUMES,1):
        for (group,n,dose),(mean,sd) in zip(GROUPS,pairs):
            star = dose is not None and not (region=='isthmus_cingulate' and dose==2)
            row = base(3,index,region,side,group,n,dose)
            row.update(reported_value=mean,standard_deviation=sd,unit=unit,
                imaging_metric='covariate_adjusted_roi_volume',statistic_kind='adjusted_mean_and_standard_deviation',
                adjustment='Female standardized to mean age and head size; volume regression on log scale',
                measurement_method='FreeSurfer 4.0.2 isthmus label' if region=='isthmus_cingulate' else 'Manual/semi-automated MIDAS',
                confidence_interval_lower=None,confidence_interval_upper=None,
                paper_significance_marker='*' if star else '',p_value=.01 if star else None,
                p_value_relation='<' if star else None,
                p_value_comparison='APOE AD subgroup versus Control' if dose is not None else None,
                corrected_significance_status='No multiplicity correction specified for Table 3; do not transfer vertex FDR',
                exact_p_from_results=(.4 if side=='lh' else .05) if region=='isthmus_cingulate' and dose==2 else None)
            rows.append(row)
    return rows


def manifest():
    return dict(doi=DOI,source_pdf=PDF,source_pdf_sha256=PDF_SHA,verification_status='completed',
        patient_numeric_use=False,patient_qc_changed=False,human_signatures_changed=False,
        permitted_use=SCOPE,statistic_records=192,table2_estimates=168,table3_estimates=24,
        table2_control_means=42,table2_group_differences=126,
        cohort=dict(initial_AD=39,excluded_AD=1,final_AD=38,Control=23,
                    AD_APOE4_noncarrier=9,AD_APOE4_heterozygote=23,AD_APOE4_homozygote=6),
        scan_design='62 initial subjects; 58 had two back-to-back same-day scans, remaining four within two weeks; scans registered and averaged for signal-to-noise improvement. Not a longitudinal atrophy analysis.',
        processing='FreeSurfer 4.0.2, semi-automated brain mask and ventricular-mask modification; all segmentations manually edited and re-run on average three times. One noncarrier excluded for motion/poor contrast.',
        figure1='Vertex ANCOVA adjusted for age and gender, FDR 0.05; AD subgroup contrasts additionally adjusted for disease duration. Figure 1 p maps are not Table 2 ROI p values.',
        figure2='Descriptive percent-difference maps between AD APOE subgroups; between-subgroup vertex differences did not reach significance.',
        table2='Table 2 p.481: unadjusted control means and Control-minus-AD differences, 95% CI, mm. Positive differences mean thinner AD cortex. No printed SD or ROI p values.',
        source_text_discrepancy='Methods p.478 describes regional thickness with SD; Table 2 explicitly labels 95% CI. Preserve Table 2 as CI; do not infer SD or individual normal ranges.',
        table3='Table 3 p.482: adjusted mean/SD; whole brain and ventricles in ml, hippocampus and isthmus in mm3. Standardized to female at mean age/head size, not raw patient volumes.',
        volume_analysis='MIDAS whole brain, hippocampus, lateral ventricles and TIV; FreeSurfer isthmus cingulate. Head-size model plus age/gender adjustment; log-volume regression with robust SE, adding duration for AD subgroup comparisons. Full prediction coefficients not printed.',
        table3_significance='Stars mean p<0.01 versus controls. Homozygote isthmus unstarred: left p=0.4, right p=0.05 in Results. Vertex FDR cannot be transferred to volume stars.',
        atlas='Table 2 composite regions average named parcels (footnotes a-e). No averaging weights or vertex-to-ROI corrected-status table supplied; do not duplicate composite means across constituent DK parcels.',
        pooling_policy='One APOE-stratified MIRIAD cohort with shared controls. Do not pool subgroup differences or repeat controls as independent AD diagnoses; do not infer patient APOE status.',
        supplemental_scope='Online supplementary figures 1 and 2 were not supplied; only the main-text statement about excluding two epsilon2/epsilon4 subjects is retained, not independent verification of those figures.',
        publication_pages='User-supplied primary PDF prints pp.476-485; retain printed Table 2 p.481 and Table 3 p.482 rather than publisher URL page numbering.')


def verify(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    if not (root/MANIFEST).exists():
        return None
    data = json.loads((root/MANIFEST).read_text())
    if data != manifest():
        raise ValueError('DIS-006 scope or numeric/QC/signature exclusion changed')
    pdf = root/PDF
    if not pdf.is_file() or hashlib.sha256(pdf.read_bytes()).hexdigest()!=PDF_SHA:
        raise ValueError('DIS-006 primary PDF changed or is missing')
    if json.loads((root/SOURCE).read_text())!=records():
        raise ValueError('DIS-006 table values, interval kind, subgroup or exclusion changed')
    return data


def render(root=None):
    data = verify(root)
    if data is None:
        return ''
    esc = html.escape
    body = ['<details><summary>DIS-006: verified APOE-stratified tables (192 estimates)</summary>',
            '<p>'+esc(SCOPE)+'</p>']
    for key in ('scan_design','processing','table2','source_text_discrepancy','table3','figure1',
                'figure2','table3_significance','atlas','pooling_policy','supplemental_scope','publication_pages'):
        body.append('<p>'+esc(data[key])+'</p>')
    for table,grouped in [(2,records()[:168]),(3,records()[168:])]:
        body.append(f'<details><summary>Table {table}: all reported statistics</summary><div style="overflow:auto"><table><tr><th>ROI / side</th><th>Group / n</th><th>Value / unit</th><th>95% CI or SD</th><th>Statistic</th></tr>')
        for row in grouped:
            interval = (f"95% CI {row['confidence_interval_lower']:g} to {row['confidence_interval_upper']:g}"
                        if table==2 else f"SD {row['standard_deviation']:g}"+row['paper_significance_marker'])
            values = [row['roi_name']+' / '+row['hemisphere'],f"{row['cohort_group']} / {row['cohort_sample_size']}",
                      f"{row['reported_value']:g} {row['unit']}",interval,row['statistic_kind']]
            body.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in values)+'</tr>')
        body.append('</table></div></details>')
    body.append('</details>')
    return ''.join(body)
