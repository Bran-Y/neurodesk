"""Audit generated PD reports against saved measurements; never call the AI API."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path

import pandas as pd
import ai_evidence_assistant as ai
from user_pipeline import read_config, status


def same_number(left, right):
    if left is None:
        return pd.isna(right)
    return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-8)


def roi_key(row):
    return tuple(None if pd.isna(row.get(k)) else row.get(k)
                 for k in ('roi_name', 'hemisphere', 'imaging_metric'))


def current_request(records, sid, payload):
    """Historical requests are valid snapshots, but not evidence for a new run."""
    digest = ai.payload_hash(payload)
    matching = [r for r in records if r.get('local_subject_id') == sid
                and r.get('prompt_version') == ai.PROMPT_VERSION
                and r.get('payload_sha256') == digest]
    if len(matching) != 1:
        raise ValueError('No unique AI request for current evidence; historical drafts are not reused')
    record = matching[0]
    if record.get('status') != 'complete':
        raise ValueError('Current-evidence AI request has not completed successfully')
    if ai.payload_hash(record['evidence_payload']) != digest:
        raise ValueError('Cached evidence does not match its hash')
    return record


def verify(root, sid):
    config = read_config(root/'cases'/sid/'config.json')
    assert config['reference_focus'] == 'PD', 'Case scope is not saved as PD'
    checks = status(config)
    assert len(checks) == 1 and checks[0]['subject_id'] == sid and checks[0]['complete']
    manifests = list(config['output_dir'].glob('*/analysis/workflow_run_manifest.json'))
    assert manifests, 'No generated analysis'
    manifest_path = max(manifests, key=lambda p: p.stat().st_mtime_ns)
    analysis = manifest_path.parent
    manifest = json.loads(manifest_path.read_text())
    assert manifest['subject_ids'] == [sid] and manifest['reference_focus'] == 'PD'
    features = pd.read_csv(analysis/'subject_features_with_covariates.csv', float_precision='round_trip')
    norms = pd.read_csv(analysis/'normative_roi_results.csv', float_precision='round_trip')
    pd_rows = pd.read_csv(analysis/'concise_reports'/f'{sid}_pd_source_comparisons.csv', float_precision='round_trip')
    for frame in (features, norms, pd_rows):
        assert set(frame.subject_id) == {sid}, 'Mixed-subject output'
    assert not norms.duplicated(['roi_name', 'hemisphere', 'imaging_metric']).any()
    counts = norms.range_status.where(norms.calculation_status.eq('calculated'), 'not_calculated').value_counts().to_dict()
    assert sum(counts.values()) == len(features) == len(norms)
    html = (analysis/'concise_reports'/f'{sid}_concise_report.html').read_text()
    assert 'Reference focus: PD + Potvin' in html and 'Zheng' not in html
    records = [json.loads(p.read_text()) for p in (root/'outputs/.ai_report_cache').glob('*.json')]
    from comparison_atlas import prepare_features
    payload = ai.build_payload(dict(project_dir=root, reference_focus='PD', normative=norms,
        comparison_features=prepare_features(features, manifest['atlas_translation_registry'])), sid)
    record = current_request(records, sid, payload)
    assert payload['reference_focus'] == 'PD' and payload['allowed_conditions'] == ['PD']
    expected_sources = {'Potvin', 'ENIGMA_PD'}
    subcortical_count = int(norms.source_doi.eq('10.1016/j.neuroimage.2016.05.016').sum())
    if subcortical_count:
        expected_sources.add('Potvin_subcortical')
    assert set(payload['sources']) == expected_sources
    assert payload['measurement_counts'] == counts
    assert record['payload_sha256'] == ai.payload_hash(payload)
    ai.validate_answer(record['response']['answer'], payload)
    normative_index = {roi_key(r._asdict()): r for r in norms.itertuples()}
    pd_index = {r.evidence_id: r for r in pd_rows.itertuples()}
    for row in payload['evidence']:
        if row['source'] in ('Potvin', 'Potvin_subcortical'):
            measured = normative_index[roi_key(row)]
            assert same_number(row['observed_value'], measured.observed_value)
            for field in ('expected_value', 'lower_95pi', 'upper_95pi'):
                assert same_number(row[field], getattr(measured, field))
        elif row['source'] == 'ENIGMA_PD':
            measured = pd_index[row['original_evidence_id']]
            assert same_number(row['measured'], measured.measured)
            assert same_number(row['pd_minus_control_cohen_d'], measured.pd_minus_control_cohen_d)
        else:
            raise AssertionError('Out-of-scope AI source')
    source_counts = dict(Counter(r['source'] for r in payload['evidence']))
    expected_counts = {'Potvin': len(norms)-subcortical_count, 'ENIGMA_PD': len(pd_rows)}
    if subcortical_count:
        expected_counts['Potvin_subcortical'] = subcortical_count
    assert source_counts == expected_counts
    directions = Counter(ai.candidate_context_direction(r, 'PD') or 'neutral_or_unavailable'
                         for r in payload['evidence'] if r['source'] == 'ENIGMA_PD')
    return dict(subject_id=sid, fs_complete=True, feature_count=len(features), normative_counts=counts,
                pd_reference_count=len(pd_rows), pd_matched=int(pd_rows.match_status.eq('matched_for_context').sum()),
                ai_source_counts=source_counts, ad_rows=0, pd_directions=dict(directions),
                ai_candidate=record['response']['answer']['candidate_discussion'],
                ai_summary=record['response']['answer']['summary'],
                ai_current_evidence_request_count=1, report=str(analysis/'concise_reports'/f'{sid}_concise_report.html'),
                config_scope='PD', passed=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('subjects', nargs='+')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    reports = [verify(root, sid) for sid in args.subjects]
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = root/'outputs'/f'pd_case_verification_{stamp}.json'
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(dict(reports=reports, network_calls=0,
                       limitation='Technical audit only; no clinical validation or visual segmentation QC.'), stream, indent=2)
    for report in reports:
        print(json.dumps(report))
    print('Audit saved:', target)
    print('API calls made by this verifier: 0')
