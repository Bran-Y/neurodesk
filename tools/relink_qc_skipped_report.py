"""Point the saved patient index at a QC-skipped exploratory report."""
from workflow_paths import project_root
import argparse
import html
import json
import os
from pathlib import Path
import tempfile
import zipfile


def _row(record):
    target = ('<a href="../../' + html.escape(record['report'], quote=True) + '">Open report</a>'
              if record['report'] else 'Not available')
    return ('<tr><td>' + html.escape(record['subject_id']) + '</td><td>' +
            html.escape(record['status']) + '</td><td>' + target + '</td></tr>')


def relink(root, subject_id, report_path):
    root = Path(root).resolve()
    report = Path(report_path).resolve()
    relative = report.relative_to(root)
    if not relative.parts[:2] == ('outputs', subject_id) or not report.is_file():
        raise ValueError('Report must exist under the selected subject output directory')
    text = report.read_text()
    if (f'Subject: {subject_id}' not in text or
            'Exploratory research report (QC skipped; measurements unverified)' not in text or
            'Exploratory assessment (QC skipped):' not in text):
        raise ValueError('Selected report is not a matching QC-skipped research report')

    folder = root / 'outputs/final_reports_20261004'
    index = folder / 'FINAL_REPORTS.html'
    verification = folder / 'verification.json'
    records = json.loads(verification.read_text())
    selected = [record for record in records if record['subject_id'] == subject_id]
    if len(selected) != 1 or not selected[0]['report']:
        raise ValueError('Expected exactly one existing patient index record')
    original = selected[0].copy()
    selected[0]['report'] = relative.as_posix()
    selected[0]['status'] = 'Exploratory research report; QC skipped; measurements unverified'
    selected[0]['report_mode'] = 'qc_skipped_exploratory'
    page = index.read_text()
    if page.count(_row(original)) != 1:
        raise ValueError('Patient index row does not match its verification record')
    page = page.replace(_row(original), _row(selected[0]))
    page = page.replace('<h1>Final research reports</h1>', '<h1>Patient research reports</h1>')

    archive = root / 'final_patient_reports_20261004.zip'
    paths = {index}
    for record in records:
        if record['report']:
            paths.update((root / record['report']).parent.glob('*'))
    fd, name = tempfile.mkstemp(prefix='patient-reports-', suffix='.zip', dir=archive.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        index.write_text(page)
        verification.write_text(json.dumps(records, indent=2))
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as package:
            for path in sorted(paths):
                if path.is_file():
                    package.write(path, path.relative_to(root))
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    return relative


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('subject_id')
    parser.add_argument('report')
    parser.add_argument('--root', default=project_root(), type=Path)
    args = parser.parse_args()
    print(relink(args.root, args.subject_id, args.report))
