"""Add a separately labeled no-QC sensitivity result to saved PD reports."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from datetime import datetime, timezone
from zipfile import ZipFile


PREVIEW = re.compile(r'<section class="qc-unfiltered-research-preview">.*?</section>', re.S)
NEXT_SECTION = '<h4>Quantitative / Potvin: highlighted deviations</h4>'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(root):
    import pandas as pd
    from concise_case_report import exploratory_qc_held_summary

    root = root.resolve()
    index = root / 'outputs/final_reports_20261004'
    inventory = json.loads((index / 'verification.json').read_text())
    selected = {root / item['report'] for item in inventory if item.get('report')}
    for case in (root / 'cases').glob('*/config.json'):
        paths = sorted((root / 'outputs' / case.parent.name).glob('**/concise_reports/*_concise_report.html'))
        if paths:
            selected.add(paths[-1])

    protected = list(root.glob('outputs/**/atlas_translation_audit.csv'))
    protected += list(root.glob('outputs/**/normative_roi_results.csv'))
    protected += list(root.glob('outputs/segmentation_qc/**/*.json'))
    protected += list(root.glob('outputs/segmentation_holds/**/*.json'))
    hashes = {p: digest(p) for p in protected}
    changes, audit = {}, []
    for report in sorted(selected):
        sid = report.name.removesuffix('_concise_report.html')
        parent = report.parent.parent
        if not (parent / 'atlas_translation_audit.csv').is_file():
            parent /= 'analysis'
        features = pd.read_csv(parent / 'atlas_translation_audit.csv')
        if set(features.subject_id) != {sid}:
            raise ValueError('Subject identity mismatch: ' + str(report))
        record = json.loads((report.parent / (sid + '_interpretation.json')).read_text())
        scope = record['possible_disease_interpretation']['reference_focus']
        preview = exploratory_qc_held_summary(dict(project_dir=root, reference_focus=scope,
                                                    comparison_features=features), sid)
        previous = report.read_text()
        clean = PREVIEW.sub('', previous)
        if preview:
            clean = re.sub(
                r'(<h4>Summary</h4>\s*<p>)(\d+/\d+ features assessed:)',
                r'\1QC-eligible assessment: \2', clean, count=1,
            )
            clean = re.sub(
                r'(<h4>PD study references: published group-effect context</h4>\s*<p>)(\d+/\d+ reference features matched;)',
                r'\1QC-eligible comparison: \2', clean, count=1,
            )
        if clean.count(NEXT_SECTION) != 1:
            raise ValueError('Expected one quantitative section: ' + str(report))
        updated = clean.replace(NEXT_SECTION, preview + NEXT_SECTION, 1)
        if updated != previous:
            changes[report] = updated
        audit.append(dict(subject_id=sid, report=str(report.relative_to(root)),
                          exploratory_preview=bool(preview), changed=updated != previous))

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = root / 'maintenance/qc_unfiltered_summary_20261007' / stamp
    backup.mkdir(parents=True, exist_ok=False)
    for target, payload in changes.items():
        dest = backup / target.relative_to(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, dest)
        temporary = target.with_name(target.name + '.qc-preview-tmp')
        temporary.write_text(payload)
        os.replace(temporary, target)

    package = root / 'final_patient_reports_20261004.zip'
    if package.is_file() and changes:
        shutil.copy2(package, backup / package.name)
        replacements = {str(path.relative_to(root)): text.encode() for path, text in changes.items()}
        temporary = package.with_name(package.name + '.qc-preview-tmp')
        with ZipFile(package) as original, ZipFile(temporary, 'w') as updated:
            for member in original.infolist():
                updated.writestr(member, replacements.get(member.filename, original.read(member)))
        os.replace(temporary, package)

    if any(digest(path) != value for path, value in hashes.items()):
        raise RuntimeError('Protected measurements or QC records changed')
    payload = dict(reports=audit, changed_reports=len(changes),
                   protected_inputs_unchanged=True, backup=str(backup))
    (backup / 'audit.json').write_text(json.dumps(payload, indent=2) + '\n')
    print(json.dumps(payload, indent=2))


if __name__ == '__main__':
    run(Path('.'))
