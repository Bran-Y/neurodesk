"""Check the PD-scoped reports and their actual per-patient quantitative joins."""
from workflow_paths import project_root
import csv
import hashlib
import html
import json
import math
from pathlib import Path

SUBJECTS = ('PPMI_41282', 'PPMI_41289', 'PPMI_41293')


def read_csv(path):
    with Path(path).open() as stream:
        return list(csv.DictReader(stream))


def audit_case(sid, report):
    from pd_evidence import nominal_significance
    report = Path(report)
    text = report.read_text()
    interpretation = json.loads(report.with_name(sid + '_interpretation.json').read_text())
    if ('Subject: ' + sid not in text or interpretation['subject_id'] != sid or
            interpretation['reference_focus'] != 'PD' or interpretation['assigned_diagnosis'] is not None):
        raise ValueError('Patient identity, scope or individual classification is inconsistent')
    if 'Exploratory Zheng AD / Control comparison:' in text or 'AD remains a candidate' in text:
        raise ValueError('AD interpretation leaked into a PD-only report')
    normative = read_csv(report.with_name(sid + '_all_potvin_measurements.csv'))
    index = {(r['roi_name'], r['hemisphere'], r['imaging_metric']): r for r in normative}
    if len(index) != len(normative):
        raise ValueError('Duplicate normative measurements')
    outside = [r for r in normative if r['range_status'] in ('below_95pi', 'above_95pi')]
    whole = read_csv(report.with_name(sid + '_pd_source_comparisons.csv'))
    stages = read_csv(report.with_name(sid + '_pd_stage_comparisons.csv'))
    extra = read_csv(report.with_name(sid + '_additional_pd_comparisons.csv'))
    checked = 0
    for r in whole + stages:
        if r['subject_id'] != sid:
            raise ValueError('Another patient appeared in a comparison row')
        if r['match_status'] != 'matched_for_context':
            continue
        n = index[(r['patient_roi_name'], r['hemisphere'], r['metric'])]
        if not math.isclose(float(n['observed_value']), float(r['measured']), rel_tol=1e-10):
            raise ValueError('PD comparison uses a different measurement than the normative export')
        if r['patient_atlas'] != r['reference_atlas'] or r['patient_processing_version'] != r['reference_processing_version']:
            raise ValueError('Atlas or processing release mismatch was not withheld')
        if (nominal_significance(r['p_as_reported']) is False and r['normative_status'] in ('below_95pi', 'above_95pi')
                and r['direction_eligible'] == 'True' and 'Not disease support' not in r['context']):
            raise ValueError('A non-significant group finding is presented as directional disease support')
        checked += 1
    baseline = [r for r in extra if r['comparison_status'] == 'descriptive_difference']
    for r in baseline:
        n = index[(r['patient_roi_name'], r['hemisphere'], 'roi_volume')]
        converted = float(n['observed_value']) / 1000
        if not math.isclose(converted, float(r['measured']), rel_tol=1e-10) or not math.isclose(
                converted - float(r['reference_mean']), float(r['difference_from_group_mean']), abs_tol=1e-10):
            raise ValueError('Baseline group-mean comparison or mm3-to-ml conversion is incorrect')
    if len(whole) != 152 or len(stages) != 608 or len(extra) != 238 or len(baseline) != 42:
        raise ValueError('Expected PD reference coverage is incomplete')
    pd_outside = [r for r in whole if r['normative_status'] in ('below_95pi', 'above_95pi')]
    return dict(subject_id=sid, known_group='user-confirmed PD; evaluation only',
        report_path=str(report), report_sha256=hashlib.sha256(report.read_bytes()).hexdigest(),
        check_status='passed', reference_focus='PD', assigned_diagnosis=None,
        AD_candidate=False, Control_assignment=False, classification_status='not_estimated',
        total_measurements=len(normative), below=sum(r['range_status'] == 'below_95pi' for r in normative),
        within=sum(r['range_status'] == 'within_95pi' for r in normative),
        above=sum(r['range_status'] == 'above_95pi' for r in normative),
        not_assessed=sum(r['calculation_status'] != 'calculated' for r in normative),
        pd_reference_rows=len(whole), pd_stage_rows=len(stages),
        quantitative_join_checks=checked, additional_pd_records=len(extra), baseline_comparisons=len(baseline),
        nominally_nonsignificant_outside_rows=sum(nominal_significance(r['p_as_reported']) is False for r in pd_outside),
        normative_outside=outside, pd_outside=pd_outside,
        limitations='No individual PD classifier, no corrected significance inferred from raw p, '
                    'no HY stage assigned; human segmentation QC remains separate and pending.')


def run(root):
    from user_pipeline import read_config, analyze
    root = Path(root)
    folder = root / 'outputs/pd_report_check_20261003'
    folder.mkdir(parents=True, exist_ok=True)
    cases = []
    for sid in SUBJECTS:
        print('PD_CHECK_START', sid, flush=True)
        config = read_config(root / 'cases' / sid / 'config.json')
        if config['reference_focus'] != 'PD':
            raise ValueError('PD case is not configured to the explicit PD reference scope')
        result = analyze(config, root)
        report = Path(result['output_dir']).parent / 'concise_reports' / (sid + '_concise_report.html')
        cases.append(audit_case(sid, report))
        print('PD_CHECK_PASSED', sid, flush=True)
    (folder / 'PD_REPORT_CHECK.json').write_text(json.dumps(dict(cases=cases,
        diagnostic_accuracy=None, note='Output and reference-join integrity, not PD diagnostic accuracy.'), indent=2))
    fields = ['subject_id', 'check_status', 'reference_focus', 'below', 'within', 'above', 'not_assessed',
              'pd_reference_rows', 'pd_stage_rows', 'baseline_comparisons', 'nominally_nonsignificant_outside_rows',
              'assigned_diagnosis', 'AD_candidate', 'Control_assignment']
    table = '<table><tr>' + ''.join('<th>' + k + '</th>' for k in fields) + '</tr>'
    for case in cases:
        table += '<tr>' + ''.join('<td>' + html.escape(str(case[k])) + '</td>' for k in fields) + '</tr>'
    details = []
    for case in cases:
        details.append('<h2>' + case['subject_id'] + '</h2><p>' + html.escape(case['limitations']) + '</p>')
        for r in case['pd_outside']:
            details.append('<p>' + html.escape(' | '.join(str(r[k]) for k in
                ('source_structure', 'metric', 'measured', 'p_as_reported', 'context'))) + '</p>')
    (folder / 'PD_REPORT_CHECK.html').write_text('<!doctype html><meta charset="utf-8">'
        '<style>body{font:16px Georgia,serif;margin:24px}td,th{padding:8px;border-bottom:1px solid #ddd}</style>'
        '<h1>PD patient report checks</h1><p>Known PD cohort membership is not inferred from MRI. '
        'Reports do not assign AD or Control. Reference group effects are not an individual PD classifier.</p>'
        + table + '</table>' + ''.join(details))
    import zipfile
    with zipfile.ZipFile(root / 'pd_report_check_results_20261003.zip', 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in folder.iterdir():
            bundle.write(path, path.relative_to(root))
        for case in cases:
            report = Path(case['report_path'])
            for suffix in ('_concise_report.html', '_interpretation.json', '_all_potvin_measurements.csv',
                           '_pd_source_comparisons.csv', '_pd_stage_comparisons.csv', '_additional_pd_comparisons.csv'):
                path = report.parent / (case['subject_id'] + suffix)
                bundle.write(path, path.relative_to(root))
        bundle.write(root / 'pd_report_check_tests.log', 'pd_report_check_tests.log')
    print('PD_REPORT_CHECK_RESULTS_READY', flush=True)


if __name__ == '__main__':
    run(project_root())
