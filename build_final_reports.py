"""Publish clean patient reports without review-process pages or signatures."""
import hashlib
import html
import json
from pathlib import Path
import zipfile


def build(root, source_refresh=False):
    from user_pipeline import read_config, participants, status, analyze
    from report_quality import read_qc
    from review_pending_reports import compare_numeric, presentation
    root = Path(root).resolve()
    from research_report_release import audit_sources, assert_final_text
    source_dispositions = audit_sources(root)
    destination = root / 'outputs/final_reports_20261004'
    destination.mkdir(parents=True, exist_ok=True)
    records, artifacts, subjects = [], [], set()
    for config_path in sorted((root / 'cases').glob('*/config.json')):
        config = read_config(config_path)
        if config.get('modality', 'T1') != 'T1':
            continue
        checks = status(config)
        previous = {}
        for item in checks:
            candidates = list((root / 'outputs').glob('**/concise_reports/' +
                              item['subject_id'] + '_concise_report.html'))
            if item['complete'] and not candidates:
                raise ValueError('Existing report required: ' + item['subject_id'])
            previous[item['subject_id']] = max(candidates, key=lambda path: path.stat().st_mtime_ns) if candidates else None
        qc_info = dict(project_dir=root, fs_root=config['subjects_dir'])
        original_qc = {item['subject_id']: read_qc(qc_info, item['subject_id']) for item in checks}
        result = analyze(config, root) if all(item['complete'] for item in checks) else None
        for check in checks:
            sid = check['subject_id']
            if sid in subjects:
                raise ValueError('Duplicate patient: ' + sid)
            subjects.add(sid)
            print('FINAL', sid, flush=True)
            if result is None:
                records.append(dict(subject_id=sid, report=None, status='Processing incomplete'))
                continue
            path = Path(result['output_dir']).parent / 'concise_reports' / (sid + '_concise_report.html')
            if source_refresh:
                from source_resolution_exports import compare_source_refresh
                verified, updates = compare_source_refresh(previous[sid], path)
            else:
                verified, updates = compare_numeric(previous[sid], path)
            if updates and not source_refresh:
                raise ValueError('Final presentation changed comparison exports: ' + sid)
            content = path.read_text()
            assert_final_text(content)
            if 'Final research report' not in content:
                raise ValueError('Final research heading missing: ' + sid)
            for forbidden in ('Assistant visual review', 'Assistant image review',
                              'QC observations, evidence and outstanding checks',
                              'Reference applicability and source evidence', 'Generate AI report'):
                if forbidden in content:
                    raise ValueError('Process text remains: ' + forbidden)
            if original_qc[sid] != read_qc(qc_info, sid):
                raise ValueError('QC state changed: ' + sid)
            records.append(dict(subject_id=sid, report=str(path.relative_to(root)),
                status='Final research report; segmentation QC ' + original_qc[sid]['status'],
                verified_exports=len(verified), source_refresh=updates, presentation=presentation(content)))
            artifacts.extend(path.parent.glob('*'))
    rows = []
    for record in records:
        target = ('<a href="../../' + html.escape(record['report'], quote=True) + '">Open report</a>'
                  if record['report'] else 'Not available')
        rows.append('<tr><td>' + html.escape(record['subject_id']) + '</td><td>' +
                    html.escape(record['status']) + '</td><td>' + target + '</td></tr>')
    source_folder = root / 'workflow_sources/Disease/PD'
    excluded = sum(not row.get('direction_eligible', True)
                   for name in ('enigma_pd_group_statistics.json', 'enigma_pd_stage_statistics.json')
                   for row in json.loads((source_folder / name).read_text())['records'])
    page = ('<!doctype html><meta charset="utf-8"><title>Patient reports</title>'
        '<style>body{font:16px Georgia,serif;max-width:1000px;margin:32px auto;padding:0 20px}'
        'table{width:100%;border-collapse:collapse}td,th{padding:12px;text-align:left;border-bottom:1px solid #ddd}</style>'
        '<h1>Final research reports</h1><p>Segmentation QC remains incomplete '
        'where indicated; ' + str(excluded) + ' conflicting reference direction(s) remain excluded. No clinical diagnosis is assigned.</p>'
        '<table><tr><th>Subject</th><th>Status</th><th>Report</th></tr>' + ''.join(rows) + '</table>')
    index = destination / 'FINAL_REPORTS.html'
    index.write_text(page)
    # Verification is internal and deliberately excluded from the presentation package.
    (destination / 'verification.json').write_text(json.dumps(records, indent=2))
    (destination / 'source_dispositions.json').write_text(json.dumps(source_dispositions, indent=2))
    with zipfile.ZipFile(root / 'final_patient_reports_20261004.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set([index, *artifacts])):
            if path.is_file():
                archive.write(path, path.relative_to(root))
    print('FINAL REPORTS READY', sum(bool(row['report']) for row in records), flush=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-refresh', action='store_true')
    build(Path(__file__).parent, parser.parse_args().source_refresh)
