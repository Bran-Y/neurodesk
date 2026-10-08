"""Recompute case evidence without AI calls after a registry/model change."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from pd_evidence import compare_result
from potvin_subcortical import preview
from user_pipeline import analyze, read_config


def verify(root, sid):
    config = read_config(root / 'cases' / sid / 'config.json')
    if config['reference_focus'] != 'PD':
        raise ValueError('This acceptance check requires a PD-scoped case')
    result = analyze(config, root)
    normative = result['normative'].loc[result['normative'].subject_id.eq(sid)]
    counts = normative.range_status.where(normative.calculation_status.eq('calculated'),
                                         'not_calculated').value_counts().to_dict()
    assert sum(counts.values()) == len(normative)
    rows = compare_result(result, sid)
    assert len(rows) == 152
    assert sum(r['match_status'] == 'matched_for_context' for r in rows) == 152
    thalamus = [r for r in rows if 'Thalamus-Proper' in str(r.get('roi_name', ''))]
    # The PD export uses the native source structure rather than roi_name on some releases.
    if not thalamus:
        thalamus = [r for r in rows if r.get('source_structure') in ('Lthal', 'Rthal')]
    assert len(thalamus) == 2
    assert all(r['context'] == 'Not directionally assessed' for r in thalamus)
    subcortical = preview(result, sid)
    assert len(subcortical) == 4
    assert subcortical.status.eq('calculated').all()
    assert subcortical.validation_status.eq('calc_formula_concordance_passed').all()
    assert subcortical.expected.notna().all()
    included = normative.loc[normative.source_doi.eq('10.1016/j.neuroimage.2016.05.016')]
    assert len(included) == 4 and included.calculation_status.eq('calculated').all()
    assert included.range_status.value_counts().to_dict() == subcortical.range_status.value_counts().to_dict()
    return dict(subject_id=sid, pd_reference_count=len(rows), pd_matched=152,
                feature_count=len(normative), normative_counts=counts,
                thalamus_direction='Not directionally assessed',
                subcortical_preview_count=len(subcortical),
                subcortical_formula_validation='LibreOffice Calc concordance passed',
                subcortical_native_excel_validation='not performed',
                run_manifest=result['run_manifest'], passed=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('subjects', nargs='+')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    records = [verify(root, sid) for sid in args.subjects]
    target = root/'outputs'/('reference_update_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    with os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as stream:
        json.dump(dict(records=records, ai_calls=0,
                       scope='Technical acceptance, not clinical validation.'), stream, indent=2, default=str)
    for record in records:
        print(json.dumps({k: v for k, v in record.items() if k != 'run_manifest'}))
    print('Audit saved:', target)


if __name__ == '__main__':
    main()
