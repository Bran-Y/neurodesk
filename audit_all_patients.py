"""Sequential checks and fresh numeric outputs for every configured patient."""
import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import traceback

import pandas as pd


def processing_failure_detail(subject):
    log = Path(subject) / 'scripts/recon-all.log'
    if not log.exists():
        return 'No recon-all log available'
    lines = log.read_text(errors='replace').splitlines()[-120:]
    markers = ('error', 'no such file', 'normal vector', 'has 0 face', 'mris_fix_topology')
    errors = [line.strip() for line in lines if any(marker in line.lower() for marker in markers)]
    return '\n'.join(errors[-12:]) or 'No explicit error in recent log; inspect processing status and full log'


def audit_all(root, output_dir=None):
    import numpy as np
    from user_pipeline import read_config, participants, status, analyze, completed
    from report_quality import read_qc
    from pd_evidence import compare_result, compare_stage_result
    from segmentation_viewer import overlay_data, save_overlay_montage, prepare_surface_overlays
    root = Path(root).resolve()
    folder = Path(output_dir or root / 'outputs' / ('patient_audit_' +
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')))
    folder.mkdir(parents=True, exist_ok=True)
    records, known, subject_roots = [], set(), set()
    for path in sorted((root / 'cases').glob('*/config.json')):
        row = dict(config=str(path.relative_to(root)), output_status='failed', qc_status='not_checked')
        try:
            config = read_config(path)
            subject_roots.add(config['subjects_dir'])
            frame = participants(config)
            if len(frame) != 1:
                raise ValueError('Expected a single-patient case configuration')
            sid = str(frame.iloc[0].subject_id)
            known.add((config['subjects_dir'], sid))
            row.update(subject_id=sid, reference_focus=config['reference_focus'], age=float(frame.iloc[0].age),
                       sex=frame.iloc[0].sex)
            print('CHECK_START', sid, flush=True)
            checks = status(config)
            row.update(processing_complete=all(item['complete'] for item in checks),
                       processing_detail=' | '.join(item['detail'] for item in checks))
            if not row['processing_complete']:
                row['output_status'] = 'processing_incomplete'
                row['processing_failure_detail'] = processing_failure_detail(config['subjects_dir'] / sid)
                row['next_action'] = 'Inspect and repair failed FreeSurfer stage; no quantitative report until successful completion'
                records.append(row)
                continue
            result = analyze(config, root)
            values = result['normative']
            calculated = values.calculation_status.eq('calculated')
            numeric = values.loc[calculated, ['observed_value', 'expected_value', 'lower_95pi', 'upper_95pi', 'zop']].to_numpy(dtype=float)
            if not np.isfinite(numeric).all():
                raise ValueError('Calculated values contain NaN or infinity')
            if (values.loc[calculated, 'lower_95pi'] > values.loc[calculated, 'upper_95pi']).any():
                raise ValueError('Prediction interval bounds are reversed')
            counts = values.loc[calculated].range_status.value_counts()
            if sum(counts.get(key, 0) for key in ('below_95pi', 'within_95pi', 'above_95pi')) != int(calculated.sum()):
                raise ValueError('Classification totals do not reconcile')
            row.update(measurements=len(values), assessed=int(calculated.sum()),
                       below=int(counts.get('below_95pi', 0)), within=int(counts.get('within_95pi', 0)),
                       above=int(counts.get('above_95pi', 0)), not_assessed=int((~calculated).sum()),
                       dk_thickness_features=int(result['features'].imaging_metric.eq('cortical_thickness').sum()))
            if row['dk_thickness_features'] != 68:
                raise ValueError('Expected 68 DK cortical thickness features')
            row['qc_status'] = read_qc(result, sid)['status']
            row['overlay_geometry'] = 'not_checked'
            try:
                overlay_data(config['subjects_dir'], sid)
                montage, provenance = save_overlay_montage(config['subjects_dir'], sid,
                    root / 'outputs/segmentation_overlay_cache')
                prepare_surface_overlays(config['subjects_dir'], sid, montage.parent)
                row.update(overlay_geometry='verified', overlay_image=str(montage),
                           surfaces='finite_vertices_valid_faces_scanner_RAS_conversion_verified')
            except Exception as exc:
                row.update(overlay_geometry='failed', overlay_error=str(exc))
            whole, stages = pd.DataFrame(compare_result(result, sid)), pd.DataFrame(compare_stage_result(result, sid))
            from pd_reviewed_comparison import coverage as additional_coverage
            extra = additional_coverage(result, sid)
            row.update(additional_pd_papers=len(extra), additional_pd_records=int(extra.reference_records.sum()),
                additional_pd_descriptive_comparisons=int(extra.descriptive_comparisons.sum()),
                additional_pd_followup_required=int(extra.followup_required.sum()))
            row.update(pd_reference_rows=len(whole), pd_matched=int(whole.match_status.eq('matched_for_context').sum()) if len(whole) else 0,
                       pd_stage_rows=len(stages), pd_stage_matched=int(stages.match_status.eq('matched_for_context').sum()) if len(stages) else 0)
            report = Path(result['output_dir']).parent / 'concise_reports' / (sid + '_concise_report.html')
            text = report.read_text()
            if 'All Potvin measurements (' + str(len(values)) + ' rows)' not in text:
                raise ValueError('Full measurement table missing from report')
            if 'AI-assisted disease' in text or 'Generate AI report' in text or '_ai_report.html' in text:
                raise ValueError('AI report is still connected')
            if config['reference_focus'] == 'PD' and 'AD/Control distribution context' in text:
                raise ValueError('AD comparison appeared in a PD-scoped report')
            csv = report.with_name(sid + '_all_potvin_measurements.csv')
            if len(pd.read_csv(csv)) != len(values):
                raise ValueError('Exported measurement rows are missing')
            row.update(output_status='passed' if row['overlay_geometry'] == 'verified' else 'overlay_attention_required',
                       report_path=str(report), report_state='reviewed' if row['qc_status'] == 'accepted' else 'research_draft',
                       numeric_integrity='passed', ai_report='removed', report_bytes=report.stat().st_size)
            print('CHECK_DONE', sid, row['output_status'], row['assessed'], row['below'], row['within'], row['above'], flush=True)
        except Exception as exc:
            row['error'] = type(exc).__name__ + ': ' + str(exc)
            print('CHECK_FAILED', row.get('subject_id', path.parent.name), row['error'], flush=True)
            traceback.print_exc()
        records.append(row)
    # Processed folders without a case configuration remain visible in the audit.
    for directory in sorted(subject_roots):
        for subject in sorted(directory.iterdir()):
            if not subject.is_dir() or not (subject / 'scripts').is_dir() or (directory, subject.name) in known:
                continue
            ok, detail = completed(subject)
            records.append(dict(subject_id=subject.name, config='', processing_complete=ok,
                processing_detail=detail, output_status='no_case_configuration',
                error='No registered case/participant metadata; quantitative report was not fabricated'))
    write_audit(records, root, folder)
    print('AUDIT_SAVED', folder, flush=True)
    return records


def write_audit(records, root, folder):
    root, folder = Path(root), Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(records)
    frame.to_csv(folder / 'patient_output_checks.csv', index=False)
    (folder / 'patient_output_checks.json').write_text(json.dumps(records, indent=2, default=str))
    public = frame.drop(columns=['report_path', 'overlay_image'], errors='ignore')
    links = []
    for row in records:
        if row.get('report_path'):
            relative = Path(row['report_path']).relative_to(root)
            links.append('<li><a href="../../' + html.escape(relative.as_posix(), quote=True) + '">' +
                         html.escape(row['subject_id']) + ' report</a> | ' + html.escape(row['report_state']) + '</li>')
    passed = sum(row.get('output_status') == 'passed' for row in records)
    attention = [row for row in records if row.get('output_status') != 'passed']
    failure_notes = ''.join('<li><b>' + html.escape(row.get('subject_id', 'Unknown')) + '</b>: ' +
        html.escape(row.get('output_status', 'failed')) + '<pre>' +
        html.escape(row.get('processing_failure_detail', row.get('error', row.get('processing_detail', '')))) +
        '</pre>' + html.escape(row.get('next_action', 'Inspect the failed check')) + '</li>' for row in attention)
    content = ('<!doctype html><meta charset="utf-8"><title>Patient output checks</title>'
        '<style>body{font:16px Georgia,serif;margin:24px}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}table{border-collapse:collapse}</style>'
        '<h1>Patient output checks</h1><p>Numeric, source coverage and MRI geometry checked sequentially. '
        'Visual segmentation acceptance is recorded separately; automated checks do not approve QC.</p>' +
        '<p><b>' + str(passed) + '/' + str(len(records)) + ' passed automated output checks.</b></p>' +
        '<h2>Items requiring attention</h2><ul>' + failure_notes + '</ul><h2>Patient reports</h2><ul>' +
        ''.join(links) + '</ul><div style="overflow:auto">' + public.to_html(index=False, escape=True) + '</div>')
    (folder / 'PATIENT_OUTPUT_CHECKS.html').write_text(content)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default=str(Path(__file__).parent))
    parser.add_argument('--output-dir')
    args = parser.parse_args()
    audit_all(args.root, args.output_dir)
