"""Refresh presentation from saved features; preserve measurements and QC files."""
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
from datetime import datetime, timezone
import zipfile


def clean(v):
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [clean(x) for x in v]
    return None if isinstance(v, float) and not math.isfinite(v) else v


def run(root):
    import pandas as pd
    from pd_evidence import compare_result
    from pd_pattern_profile import render
    from possible_disease_interpretation import summarize, merge_summary_html
    root = root.resolve()
    index = root / 'outputs/final_reports_20261004'
    inventory = json.loads((index / 'verification.json').read_text())
    selected = {root / item['report'] for item in inventory if item.get('report')}
    for case in (root / 'cases').glob('*/config.json'):
        paths = sorted((root / 'outputs' / case.parent.name).glob('**/concise_reports/*_concise_report.html'))
        if paths:
            selected.add(paths[-1])
    protected = list(root.glob('outputs/**/concise_reports/*.csv'))
    protected += list(root.glob('outputs/**/atlas_translation_audit.csv'))
    protected += list(root.glob('outputs/**/normative_roi_results.csv'))
    protected += list(root.glob('outputs/segmentation_qc/**/*.json'))
    protected += list(root.glob('outputs/segmentation_holds/**/*.json'))
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    plans, audit = [], []
    for report in sorted(selected):
        sid = report.name.removesuffix('_concise_report.html')
        parent = report.parent.parent
        if not (parent / 'atlas_translation_audit.csv').exists():
            parent = parent / 'analysis'
        features = pd.read_csv(parent / 'atlas_translation_audit.csv')
        norms = pd.read_csv(parent / 'normative_roi_results.csv')
        assert set(features.subject_id) == {sid} and set(norms.subject_id) == {sid}
        rows = compare_result(dict(project_dir=root, comparison_features=features, normative=norms), sid)
        record_path = report.parent / (sid + '_interpretation.json')
        record = json.loads(record_path.read_text())
        old = record['possible_disease_interpretation']
        comparison = dict(features=old['ad']['reasons'], warnings=old['ad']['warnings'])
        summary = clean(summarize(comparison, rows, old['reference_focus']))
        assert summary['ad']['candidate'] == old['ad']['candidate'], 'AD rule changed'
        previous = report.read_text()
        if old['pd'].get('directional_profile'):
            previous = previous.replace(render(old['pd']['directional_profile']), '')
        content = merge_summary_html(previous, summary)
        # Update the separate ENIGMA context without altering its numerical tables.
        marker = '<h4>PD study references: published group-effect context</h4>'
        if marker in content:
            match = re.search(re.escape(marker) + r'\s*<p>.*?</p>', content, re.S)
            assert match is not None
            content = content[:match.end()] + render(summary['pd']['directional_profile']) + content[match.end():]
        updated = dict(record, possible_disease_interpretation=summary)
        plans.extend(((report, content), (record_path, json.dumps(updated, indent=2, allow_nan=False))))
        profile = summary['pd']['directional_profile']
        audit.append(dict(subject_id=sid, report=str(report.relative_to(root)),
                          matched=sum(r['match_status'] == 'matched_for_context' for r in rows),
                          assessed=profile['assessed'], aligned=len(profile['aligned']), opposed=len(profile['opposed']),
                          at_expected=len(profile['at_expected']), outside_pi_matches=len(summary['pd']['reasons']),
                          assigned_diagnosis=None, known_diagnosis_used_as_input=False))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = root / 'maintenance/pd_pattern_profile_20261007' / stamp
    backup.mkdir(parents=True, exist_ok=False)
    for target, payload in plans:
        dest = backup / target.relative_to(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, dest)
        temporary = target.with_name(target.name + '.pattern-tmp')
        temporary.write_text(payload)
        os.replace(temporary, target)
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in hashes.items()), 'Protected inputs changed'
    package = root / 'final_patient_reports_20261004.zip'
    if package.exists():
        shutil.copy2(package, backup / package.name)
        files = {index / 'FINAL_REPORTS.html'}
        for item in inventory:
            if item.get('report'):
                files.update((root / item['report']).parent.glob('*'))
        temporary = package.with_name(package.name + '.pattern-tmp')
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(files):
                if path.is_file():
                    archive.write(path, path.relative_to(root))
        os.replace(temporary, package)
    (backup / 'audit.json').write_text(json.dumps(dict(reports=audit, protected_inputs_unchanged=True), indent=2))
    print(json.dumps(dict(reports=audit, protected_inputs_unchanged=True), indent=2), flush=True)


if __name__ == '__main__':
    run(Path('.'))
