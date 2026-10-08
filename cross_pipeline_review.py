"""Method metadata review, not permission to transfer measurements between pipelines."""
import html
import json
from pathlib import Path

import pandas as pd

from processing_compatibility import all_versions_match
from reference_focus import pd_only, ADDITIONAL_PD_DOIS


# These profiles describe the audited source methods; they are not model inputs.
PROFILES = [
    ('DIS-008', '10.1159/000084560', 'MIDAS manual hippocampal formation',
     'Right/left volume ratio; longitudinal annual atrophy',
     'Ratio definition and bilateral aggregation differ from individual FreeSurfer aseg volumes; no individual SD.'),
    ('DIS-009', '10.1016/j.neurobiolaging.2007.02.011', 'MIDAS manual segmentation',
     'Bilateral total volume; annualized longitudinal loss',
     'Repeat scans and the source annualization are required; single-scan volumes cannot supply atrophy rates.'),
    ('DIS-006', '10.1159/000258100', 'Modified FreeSurfer 4.0.2 plus MIDAS',
     'Regional thickness; adjusted and unadjusted group volumes',
     'Version, edited masks and covariate adjustment differ; composite aggregation weights are unavailable.'),
    ('DIS-011', '10.1212/wnl.0b013e3181a4124e', 'Modified FreeSurfer 4.0.3',
     'Lobar means, normalized regional thickness and vertex results',
     'Different spatial scales and normalization; SemD/PNFA group effects are not AD/PD individual intervals.'),
    ('ROI-006', '10.1097/rct.0b013e31802f4139', 'MIDAS manual / fluid propagation / Jacobian methods',
     'Average of left/right longitudinal atrophy rates',
     'These methods and rate aggregation are distinct; neither raw bilateral volume nor a single-scan rate is equivalent.'),
    ('ROI-010', '10.1016/j.neuroimage.2008.10.043', 'AdaBoost auto-context; ICBM registration',
     'Longitudinal annual volume loss; confidence intervals of group means',
     'Segmentation/registration differ; a mean confidence interval cannot be used as an individual reference interval or SD.'),
    ('ROI-008', '10.1016/j.neuroimage.2010.06.025', 'Modified FreeSurfer 4.1.0; MIDAS TIV; SPM5/DARTEL',
     'Log-scale covariate associations across multiple measurement families',
     'Missing intercept and residual prediction parameters; coefficients do not reconstruct a normative model.'),
    ('ROI-009', '10.1016/j.neuroimage.2010.03.018', 'MAPS/STAPLE and MAPS-HBSI',
     'Bilateral baseline volume and longitudinal annual atrophy',
     'Source baseline and longitudinal algorithms must remain separate; identical mm3 units do not harmonize boundaries.'),
    ('QREF-001', '10.1371/journal.pone.0279574', 'FreeSurfer; exact release unreported',
     'Unadjusted AD/Control group volumes',
     'The allowed exploratory similarity comparison is retained, but version, covariate and external calibration are unverified.'),
    ('QREF-002', '10.3233/JAD-200246', 'CAT12 / SPM12; exact CAT12 release unreported',
     'Projection-based whole-brain thickness and cortical complexity',
     'A whole-brain projection-based mean is not a native FreeSurfer parcel mean; DK names do not establish equivalence.'),
    ('QREF-003', '10.3390/tomography8010018', 'BrainGPS; multi-atlas segmentation',
     '286-label volumetry; Methods 2.5 specifies brain-size-normalized statistical volumes',
     'Raw, brain-size-normalized and MNI-normalized outputs are distinct; raw aseg mm3 and normalized statistics cannot be interchanged.'),
    ('PD additional', '10.1371/journal.pone.0295069', 'FreeSurfer 7.1.1',
     'Cross-sectional regional group statistics',
     'The reference version differs from the current 5.3.0 subjects; group effects are descriptive, not individual intervals.'),
    ('PD additional', '10.1093/brain/awu036', 'FreeSurfer 5.3.0',
     'Longitudinal change and vertex clusters',
     'Version identity alone does not supply repeat scans or map a vertex cluster to an entire DK parcel; per-ROI correction is not established.'),
    ('PD additional', '10.1093/brain/awv211', 'FreeSurfer 5.3.0; longitudinal study',
     'Baseline regional volume and longitudinal cortical/subcortical change',
     'Baseline descriptive differences are retained only where eligible; longitudinal rates require repeat scans and matching processing mode.'),
    ('PD additional', '10.1371/journal.pone.0148852', 'FreeSurfer 5.3.0',
     'Log-volume, pial area and vertex group results',
     'Unreported log base, pial versus white surface area and vertex-to-parcel differences prevent direct numeric transfer.'),
]


def profiles():
    return pd.DataFrame([dict(source_code=code, doi=doi, reference_method=method,
                             measurement_definition=definition, limitation=limitation,
                             calibration_status='not_validated', calibrated_numeric_transfer=False)
                         for code, doi, method, definition, limitation in PROFILES])


def _values(frame, column):
    if column not in frame or frame.empty:
        return 'Not recorded'
    values = {str(v).strip() if pd.notna(v) and str(v).strip() else 'Not recorded'
              for v in frame[column]}
    return ' | '.join(sorted(values))


def patient_metadata(result, subject_id):
    from comparison_atlas import comparison_features
    features = comparison_features(result)
    patient = features.loc[features.subject_id.eq(subject_id)]
    if patient.empty:
        raise ValueError('Patient metadata missing: ' + subject_id)
    columns = ('source_pipeline', 'processing_software_version', 'comparison_atlas_code',
               'hemisphere', 'unit', 'statistic_type')
    metadata = {column: _values(patient, column) for column in columns}
    metadata['subject_id'] = subject_id
    metadata['recorded_features'] = len(patient)
    metadata['all_recorded_versions_fs53'] = (
        'processing_software_version' in patient and
        all_versions_match(patient.processing_software_version, '5.3.0'))
    metadata['processing_mode'] = 'Not verified by version metadata; cross-sectional/base/longitudinal must be checked separately'
    return metadata


def subject_audit(result, subject_id):
    table = profiles()
    if pd_only(result):
        table = table.loc[table.doi.isin(ADDITIONAL_PD_DOIS)].copy()
    elif isinstance(result.get('papers'), pd.DataFrame) and 'doi' in result['papers']:
        table = table.loc[table.doi.isin(result['papers'].doi)].copy()
    metadata = patient_metadata(result, subject_id)
    for key, value in metadata.items():
        table['patient_' + key if key != 'subject_id' else key] = value
    return table


def render(result, subject_id):
    table = subject_audit(result, subject_id)
    metadata = patient_metadata(result, subject_id)
    label = ('FreeSurfer 5.3.0 recorded for all features' if metadata['all_recorded_versions_fs53']
             else 'Missing or mixed processing versions; numeric eligibility must be checked per measurement')
    return ('<details><summary>Cross-pipeline applicability</summary><p>' + html.escape(label) +
            '. Matching version or atlas labels alone does not validate numerical transfer. '
            'Exploratory group comparisons are not calibrated diagnosis.</p>' +
            '<div style="overflow:auto">' + table[['source_code', 'doi', 'reference_method',
            'measurement_definition', 'limitation']].to_html(index=False, escape=True, border=0) +
            '</div></details>')


def publish(root):
    root = Path(root)
    verification = json.loads((root / 'outputs/final_reports_20261004/verification.json').read_text())
    patients, tables = [], []
    for item in verification:
        if item['report']:
            path = root / item['report'].replace('_concise_report.html', '_cross_pipeline_review.csv')
            table = pd.read_csv(path)
            tables.append(table)
            patients.append(dict(subject_id=item['subject_id'], status='Report metadata checked',
                                 exported_method_rows=len(table)))
        else:
            patients.append(dict(subject_id=item['subject_id'], status='Processing incomplete; not audited as a finished report',
                                 exported_method_rows=0))
    out = root / 'outputs/cross_pipeline_review_20261005'
    out.mkdir(parents=True, exist_ok=True)
    combined = pd.concat(tables, ignore_index=True)
    combined.to_csv(out / 'patient_method_audit.csv', index=False)
    metadata_columns = [c for c in combined if c.startswith('patient_')]
    patient_table = combined[['subject_id', *metadata_columns]].drop_duplicates()
    if patient_table.subject_id.duplicated().any():
        raise ValueError('Inconsistent subject metadata in method audit')
    data = dict(review_scope='Source-method metadata and report version gates; no paired-pipeline calibration performed',
                patients=patients, source_profiles=profiles().to_dict('records'),
                cross_pipeline_calibration_complete=False, human_segmentation_qc_modified=False)
    (out / 'method_review.json').write_text(json.dumps(data, indent=2))
    page = ('<!doctype html><meta charset="utf-8"><title>Processing compatibility</title>'
            '<style>body{font:16px Georgia,serif;margin:32px auto;max-width:1200px;padding:0 20px}'
            'p{line-height:1.6}table{border-collapse:collapse}td,th{padding:10px;text-align:left;'
            'border-bottom:1px solid #ddd;vertical-align:top}.scroll{overflow:auto}</style>'
            '<h1>Processing compatibility: completed metadata review</h1>'
            '<p>Patient software metadata and the listed source measurement definitions have been checked. '
            'No paired-pipeline equivalence or diagnostic calibration is claimed. Existing eligible native '
            'Potvin calculations and permitted exploratory comparisons remain separate from that validation.</p>'
            '<h2>Patient output coverage</h2>' + pd.DataFrame(patients).to_html(index=False, escape=True) +
            '<details><summary>Recorded patient method metadata</summary><div class="scroll">' +
            patient_table.to_html(index=False, escape=True) + '</div></details>'
            '<h2>Reference method definitions</h2><div class="scroll">' +
            profiles().to_html(index=False, escape=True) + '</div>'
            '<h2>Required for numerical calibration</h2><ol>'
            '<li>Process the same MRI scans with both precisely identified pipelines, retaining versions, '
            'options, edited masks and processing mode. Longitudinal measures require the same timepoints.</li>'
            '<li>Review segmentation in both outputs and align ROI boundaries, hemisphere, units, '
            'normalization and aggregation; label matching is not spatial equivalence.</li>'
            '<li>Estimate systematic bias and agreement with uncertainty using paired outputs; '
            'define acceptance limits for the intended research use before validation.</li>'
            '<li>Validate any correction on held-out subjects. Do not tune it to known AD, PD or control labels '
            'to force agreement. This metadata review cannot substitute for those data.</li></ol>'
            '<p>Human segmentation decisions remain separate and unchanged. Another paper PDF alone does '
            'not establish equivalence for this dataset.</p>'
            '<p>Primary methods: <a href="https://surfer.nmr.mgh.harvard.edu/fswiki/LongitudinalProcessing">'
            'FreeSurfer longitudinal processing</a>; '
            '<a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC7338220/">CAT12 study methods</a>; '
            '<a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC8788517/">BrainGPS Methods 2.5</a>.</p>')
    (out / 'CROSS_PIPELINE_REVIEW.html').write_text(page)
    return data
