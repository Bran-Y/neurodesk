"""Published covariate associations, not a reconstructable patient prediction model."""
import hashlib
import html
import json
from pathlib import Path

DOI = '10.1016/j.neuroimage.2010.06.025'
FOLDER = 'workflow_sources/paper_reading_reviews/'
SOURCE = FOLDER + 'barnes_2010_covariate_reported_statistics.json'
MANIFEST = FOLDER + 'barnes_2010_covariate_fulltext_review.json'
PDF = FOLDER + 'raw/barnes_2010_covariate.pdf'
PDF_SHA = 'ea13d433c0850f669c18821b6544d911b7d6e0cfacbef5f2ede6b46a0b9db740'
FIELD_CHECK = FOLDER + 'barnes_2010_covariate_pdf_field_check.json'
FIELD_SHA = '98b3636df8a1aa5458eaec216d1f63ab977939f899cc9b0aff982e394a65e5c7'
SCOPE = ('Verified Table 2 covariate associations with 95% coefficient CI, not group volume means, '
         'SD or individual prediction intervals. TIV entries are log-log power coefficients, not percentages. '
         'Age effects are cross-sectional, not longitudinal atrophy rates. Published table/text conflicts '
         'are retained; intercept and residual prediction parameters are not reported in the inspected '
         'main paper. Modified FreeSurfer 4.1.0/MIDAS/SPM5 is not calibrated to current processing. '
         'Method context only; no patient numerical comparison or disease classification.')
COLUMNS = [
    ('age', 1, ['age', 'upgrade'], 'percent per 1-year age difference'),
    ('gender', 2, ['gender', 'upgrade'], 'percent male versus female'),
    ('log_tiv', 3, ['log_tiv', 'upgrade'], 'dimensionless log-log power coefficient'),
    ('age', 4, ['age', 'gender', 'log_tiv', 'upgrade'], 'percent per 1-year age difference'),
    ('gender', 4, ['age', 'gender', 'log_tiv', 'upgrade'], 'percent male versus female'),
    ('log_tiv', 4, ['age', 'gender', 'log_tiv', 'upgrade'], 'dimensionless log-log power coefficient'),
    ('upgrade', 4, ['age', 'gender', 'log_tiv', 'upgrade'], 'percent post versus pre scanner upgrade'),
]
# Each tuple retains estimate, coefficient CI, p expression, and semipartial R2.
TABLE = [
    ('Whole brain', [(-.25,-.40,-.10,'=0.002','0.121'),(7.59,3.68,11.64,'<0.001','0.169'),(.82,.68,.96,'<0.001','0.649'),(-.34,-.39,-.28,'<0.001','0.218'),(-3.53,-5.25,-1.79,'<0.001','0.024'),(1.02,.91,1.12,'<0.001','0.574'),(.89,-.58,2.39,'=0.233','0.002')]),
    ('Grey matter volume', [(-.32,-.46,-.17,'<0.001','0.184'),(6.20,2.23,10.32,'=0.002','0.105'),(.65,.47,.83,'<0.001','0.378'),(-.39,-.48,-.30,'<0.001','0.271'),(-2.53,-5.28,.29,'=0.078','0.011'),(.82,.66,.99,'<0.001','0.346'),(-4.66,-6.87,-2.40,'<0.001','0.057')]),
    ('White matter volume', [(-.14,-.34,.07,'=0.196','0.022'),(8.41,3.29,13.79,'=0.001','0.126'),(1.01,.82,1.19,'<0.001','0.601'),(-.24,-.35,-.13,'<0.001','0.068'),(-5.76,-9.17,-2.21,'=0.002','0.040'),(1.27,1.06,1.49,'<0.001','0.553'),(1.45,-1.58,4.57,'=0.347','0.004')]),
    ('Lateral ventricles', [(2.43,1.63,3.24,'<0.001','0.323'),(50.56,21.01,87.34,'<0.001','0.152'),(2.75,1.55,3.95,'<0.001','0.211'),(2.21,1.50,2.93,'<0.001','0.262'),(19.61,-4.44,49.72,'=0.116','0.017'),(1.66,.37,2.95,'=0.012','0.044'),(3.58,-13.83,24.51,'=0.704','0.001')]),
    ('Hippocampus (total: left plus right)', [(-.32,-.48,-.17,'<0.001','0.181'),(1.78,-2.50,6.24,'=0.416','0.009'),(.32,.08,.55,'=0.009','0.087'),(-.36,-.51,-.22,'<0.001','0.224'),(-3.32,-7.77,1.34,'=0.157','0.019'),(.51,.24,.78,'<0.001','0.130'),(-1.17,-4.91,2.71,'=0.544','0.003')]),
    ('Amygdala (total: left plus right)', [(-.13,-.34,.08,'=0.235','0.017'),(5.35,.10,10.88,'=0.046','0.047'),(.66,.40,.92,'<0.001','0.228'),(-.20,-.38,-.02,'=0.033','0.040'),(-3.90,-9.32,1.84,'=0.176','0.016'),(.84,.51,1.18,'<0.001','0.215'),(-5.49,-9.88,-.88,'=0.021','0.047')]),
    ('Caudate (total: left plus right)', [(-.12,-.34,.10,'=0.267','0.016'),(8.61,3.22,14.27,'=0.002','0.121'),(.68,.42,.95,'<0.001','0.255'),(-.19,-.38,-0.00,'=0.046','0.039'),(.73,-5.19,7.02,'=0.812','<0.001'),(.70,.35,1.04,'<0.001','0.150'),(.28,-4.58,5.39,'=0.910','<0.001')]),
    ('Putamen (total: left plus right)', [(-.30,-.49,-.10,'=0.003','0.109'),(5.33,.28,10.63,'=0.038','0.055'),(.45,.18,.72,'=0.001','0.124'),(-.35,-.52,-.17,'<0.001','0.147'),(.01,-5.56,5.91,'=0.996','<0.001'),(.51,.19,.84,'=0.003','0.094'),(2.68,-2.03,7.62,'=0.265','0.012')]),
]
CONFLICTS = [
    ('Table 1 p.1247', 'Female n printed as 4; total n=78 and male n=37. Female pre/post 25/16 sums to 41. Forty-one is an arithmetic inference, not a printed correction.'),
    ('Lateral ventricles / age, model 1', 'Table 2: 2.43 (1.63,3.24); Results Age: 2.45 (1.65,3.25).'),
    ('Lateral ventricles / gender, model 2', 'Table 2: 50.56 (21.01,87.34); Results Gender: 49.76 (20.06,86.81).'),
    ('Putamen / gender, model 2', 'Table 2: 5.33 (0.28,10.63), p=0.038; Results Gender says men have larger volumes in all structures except hippocampus and putamen. The putamen exception conflicts with the positive coefficient and nominal significance in Table 2; retain both statements.'),
    ('Lateral ventricles / age, model 4', 'Table 2: 2.21 (1.50,2.93); Results Age adjusted: 2.22 (1.52,2.93).'),
    ('Lateral ventricles / gender, model 4', 'Table 2: 19.61 (-4.44,49.72); Results Gender adjusted: 15.08 (-8.47,44.69).'),
    ('Whole brain / gender, model 4', 'Table 2: -3.53 (-5.25,-1.79); Results: 3.74 percent smaller (1.95,5.50 smaller).'),
    ('Grey matter / gender, model 4', 'Table 2: -2.53 (-5.28,0.29); Results: 2.78 percent smaller (-0.12,5.61 smaller).'),
    ('White matter / gender, model 4', 'Table 2: -5.76 (-9.17,-2.21); Results: 5.87 percent smaller (2.21,9.40 smaller).'),
    ('Hippocampus / gender, model 4', 'Table 2: -3.32 (-7.77,1.34), p=0.157; Results: 3.38 percent smaller (-1.44,7.97 smaller), p=0.16.'),
    ('Amygdala / gender, model 4', 'Table 2: -3.90 (-9.32,1.84), p=0.176; Results: 3.62 percent smaller (-2.34,9.23 smaller), p=0.22.'),
    ('Whole brain / log TIV, model 4', 'Table 2: 1.02 (0.91,1.12); Results TIV adjusted: 1.03 (0.92,1.14).'),
    ('White matter / log TIV, model 4', 'Table 2: b=1.27 (1.06,1.49); Results TIV adjusted describes a power less than one. Retain both; do not reverse b.'),
    ('Caudate / upgrade', 'Discussion includes caudate among independent upgrade effects; Table 2 model 4 has 0.28 (-4.58,5.39), p=0.910; Results identifies grey matter/amygdala only.'),
]


def records():
    rows = []
    for roi, cells in TABLE:
        for column, (effect, lower, upper, p, r2) in enumerate(cells):
            variable, model, covariates, unit = COLUMNS[column]
            rows.append(dict(record_id=f'ROI-008-TABLE2-{len(rows)+1:02d}', paper_code='ROI-008',
                doi=DOI, source_title='Head size, age and gender adjustment in MRI studies: a necessary nuisance?',
                source_url='https://doi.org/'+DOI, roi_name=roi.split(' (')[0].lower().replace(' volume',''), source_roi_label=roi,
                hemisphere='bilateral_total' if 'left plus right' in roi else 'not_stated_in_table',
                diagnosis='Healthy controls', cohort_sample_size=78, imaging_metric='covariate_volume_association',
                reported_value=effect, estimated_effect=effect, unit=unit,
                statistic_type='log_tiv_power_coefficient' if variable=='log_tiv' else 'back_transformed_percent_covariate_effect',
                covariate=variable, model_number=model, model_covariates=covariates,
                confidence_interval_lower=lower, confidence_interval_upper=upper,
                mean=None, standard_deviation=None, intercept=None, residual_standard_deviation=None,
                p_value=float(p[1:]), p_comparator=p[0], p_test='no association',
                multiplicity_correction='Not stated for Table 2 ROI tests; surface/VBM FDR not transferred',
                semipartial_r2=float(r2.lstrip('<')), semipartial_r2_comparator='<' if r2.startswith('<') else '=',
                raw_reported_text=f'{effect:.2f} ({lower:.2f}, {upper:.2f}); p{p}; semipartial R2 {r2}',
                source_location=f'Table 2 p.1248, column {column+1}; Methods pp.1246-1247',
                processing_method='Modified FreeSurfer 4.1.0, MIDAS whole brain/TIV, SPM5 GM/WM',
                source_check_status='primary_pdf_table_values_verified_with_published_conflicts_context_only',
                human_review_status='not_assigned_by_assistant', extraction_status='primary_pdf_table_values_verified',
                numeric_use=False, patient_numeric_use=False, comparison_compatible=False,
                direction_eligible=False, model_reconstruction_complete=False, applicability_note=SCOPE))
    return rows


def manifest():
    return dict(review_type='assistant_primary_source_check_not_human_signoff', source_pdf_sha256=PDF_SHA,
        field_check_sha256=FIELD_SHA, table_field_checks=392,
        source_scope='Complete user PDF pp.1244-1255, Methods, Tables 1-3, Results, Discussion and figure captions; Table 1/2/3 visually checked.',
        statistics_count=56, source_conflicts=[dict(location=a, finding=b) for a,b in CONFLICTS],
        permitted_use=SCOPE, findings={
            'models':'Natural log ROI volume; models 1-3 each include upgrade, model 4 includes age, gender, log TIV and upgrade. TIV slopes are b in vol=k*TIV^b, not percentage changes.',
            'reconstruction':'Table 2 supplies slopes/effects and coefficient CI, but no numerical intercept k, residual variance or full coefficient covariance for individual prediction. Do not build an absolute volume reference interval.',
            'cohort':'78 healthy controls aged 24-81 years from a single 1.5T GE Signa site; not an AD/PD classifier. Female printed n=4 is retained as a source typo, not silently replaced.',
            'methods':'MIDAS whole brain and TIV; FS4.1.0 subcortical segmentation and modified cortical stream with MIDAS brain mask, ventricle-informed WM mask and manual edits; SPM5/DARTEL GM/WM.',
            'correction':'Cortical surface FDR 0.05 separately over each hemisphere; VBM FDR 0.05. Neither establishes corrected status for Table 2 ROI tests. Tests of b=1 in prose differ from Table 2 tests of no association.',
            'age':'Cross-sectional age associations are not within-person annual atrophy rates; total bilateral hippocampus/amygdala/caudate/putamen effects are not separate hemisphere effects.',
            'recommendations':'Table 3: age Yes for ROI/thickness/VBM; gender Maybe/Yes/Yes; TIV Yes/Probably not/Yes; upgrade Maybe/Yes/Yes. Study-specific balance/confounding still matters; nonsignificance alone is not grounds to omit adjustment.',
            'conflicts':'Table values retained as printed, conflicting prose retained separately. No erratum is supplied; no assistant correction of cohort counts or effect values is applied.'},
        patient_comparison_enabled=False, human_signatures_changed=False, patient_qc_changed=False)


def verify(root=None):
    root=Path(root or Path(__file__).parent)
    if not (root/MANIFEST).exists():
        return None
    if json.loads((root/MANIFEST).read_text())!=manifest():
        raise ValueError('Covariate source manifest changed')
    if hashlib.sha256((root/PDF).read_bytes()).hexdigest()!=PDF_SHA:
        raise ValueError('Retained covariate primary PDF changed')
    if hashlib.sha256((root/FIELD_CHECK).read_bytes()).hexdigest()!=FIELD_SHA:
        raise ValueError('Source-bound covariate field review changed')
    if json.loads((root/SOURCE).read_text())!=records():
        raise ValueError('Covariate source extraction changed')
    return manifest()


def render(root=None):
    data=verify(root)
    if data is None:
        return ''
    out='<details><summary>ROI-008: verified covariate associations and published inconsistencies</summary><p>'+html.escape(SCOPE)+'</p>'
    out+=''.join('<p>'+html.escape(v)+'</p>' for v in data['findings'].values())
    out+='<details><summary>Published table/text differences (retained, not corrected)</summary><ul>'
    out+=''.join('<li>'+html.escape(a+': '+b)+'</li>' for a,b in CONFLICTS)+'</ul></details>'
    out+='<details><summary>Table 2: 56 covariate effects, not patient reference ranges</summary><table><tr>'
    out+=''.join('<th>'+v+'</th>' for v in ['ROI','Model / covariate','Estimate','Unit','95% coefficient CI','p','Semipartial R2'])+'</tr>'
    for row in records():
        values=[row['roi_name'],f"{row['model_number']} / {row['covariate']}",f"{row['estimated_effect']:.2f}",row['unit'],
                f"{row['confidence_interval_lower']:.2f} to {row['confidence_interval_upper']:.2f}",
                row['p_comparator']+str(row['p_value']),row['semipartial_r2_comparator']+str(row['semipartial_r2'])]
        out+='<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in values)+'</tr>'
    return out+'</table></details></details>'
