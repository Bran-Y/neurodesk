"""Recompute real-case comparisons and exports without sending data to an AI service."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from unittest.mock import patch

from ai_evidence_assistant import build_payload, outbound_payload, serialise, PROMPT_VERSION
from concise_case_report import export_concise_report
from pd_evidence import compare_result, compare_stage_result
from user_pipeline import analyze, read_config


def verify(root, sid, destination):
    config = read_config(root / 'cases' / sid / 'config.json')
    if config.get('reference_focus') != 'PD':
        raise ValueError('Expected a PD-scoped case, not a known diagnosis input')
    with patch('ai_evidence_assistant.explain', side_effect=AssertionError('AI call forbidden')):
        result = analyze(config, root)
        whole = compare_result(result, sid)
        stage = compare_stage_result(result, sid)
        payload = build_payload(result, sid)
        wire = outbound_payload(payload)
        report = export_concise_report(result, sid, destination / sid)
    assert len(whole) == 152 and len(stage) == 608
    assert all(r['match_status'] == 'matched_for_context' for r in whole + stage)
    assert sum(not r['direction_eligible'] for r in whole) == 6
    assert sum(not r['direction_eligible'] for r in stage) == 1
    assert wire['pd_stage_context'] == payload['pd_stage_context']
    assert sid not in serialise(wire)
    assert wire['pd_stage_context']['patient_stage'] == 'not_assigned'
    assert sum(r['source'] == 'ENIGMA_PD' for r in payload['evidence']) == 152
    assert not any(r['source'] == 'Zheng_AD_Control' for r in payload['evidence'])
    assert 'PD supplementary comparisons by published HY stage' in report.read_text()
    norms = result['normative'].loc[result['normative'].subject_id.eq(sid)]
    counts = norms.range_status.where(norms.calculation_status.eq('calculated'),
                                    'not_calculated').value_counts().to_dict()
    assert sum(counts.values()) == len(norms)
    return dict(subject_id=sid, passed=True, whole_reference_rows=len(whole),
                stage_reference_rows=len(stage), whole_source_discrepancies=6,
                stage_source_discrepancies=1, normative_counts=counts,
                stage_outlier_context_rows=len(wire['pd_stage_context']['comparisons']),
                report=str(report.relative_to(root)), prompt_version=PROMPT_VERSION,
                scope='Technical integration check, not clinical validation.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('subjects', nargs='+')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    destination = root / 'outputs' / ('pd_supplement_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    destination.mkdir(parents=True, mode=0o700)
    records = [verify(root, sid, destination) for sid in args.subjects]
    target = destination / 'verification.json'
    with os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as stream:
        json.dump(dict(records=records, ai_calls=0), stream, indent=2)
    print(json.dumps(dict(records=records, ai_calls=0, audit=str(target)), indent=2))


if __name__ == '__main__':
    main()
