"""Field-level extraction concordance, separate from patient disease analysis."""
import argparse
import html
import json
from pathlib import Path

import pandas as pd


def compare_fields(rows):
    compared = []
    keys = set()
    for item in rows:
        key = (item['doi'], item['record_key'], item['field'])
        if key in keys:
            raise ValueError('Duplicate comparison field: ' + str(key))
        keys.add(key)
        row = dict(item)
        manual, automated = row.get('human_value'), row.get('automated_value')
        if not row.get('comparable', True):
            row['agreement'] = 'not_comparable'
        elif manual is None or automated is None:
            row['agreement'] = 'unpaired'
        elif isinstance(manual, (int, float)) and isinstance(automated, (int, float)):
            tolerance = float(row.get('absolute_tolerance', 0))
            row['agreement'] = 'agree' if abs(manual - automated) <= tolerance + 1e-12 else 'disagree'
        else:
            row['agreement'] = 'agree' if str(manual).strip().lower() == str(automated).strip().lower() else 'disagree'
        compared.append(row)
    return pd.DataFrame(compared)


def export_comparison(input_path, output_dir):
    document = json.loads(Path(input_path).read_text())
    approval_path = Path(input_path).parent / 'pd_paper_review_approvals.json'
    approvals = json.loads(approval_path.read_text()) if approval_path.exists() else {}
    reviewed = {paper['doi']: paper for paper in approvals.get('papers', [])}
    frame = compare_fields(document['comparisons'])
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    frame.to_csv(folder / 'extraction_field_comparison.csv', index=False)
    summaries = []
    for paper in document['papers']:
        selected = frame.loc[frame.doi.eq(paper['doi'])]
        independent = selected.loc[selected.independent_pair.eq(True)] if len(selected) else selected
        paired = independent.loc[independent.agreement.isin(['agree', 'disagree'])]
        agree = int(paired.agreement.eq('agree').sum())
        review = reviewed.get(paper['doi'], {})
        summaries.append(dict(paper=paper['paper'], doi=paper['doi'],
            human_review_status=review.get('human_review_status', 'not_recorded_in_this_manifest'),
            data_use_status=review.get('data_use_status', 'not_recorded_in_this_manifest'),
            approval_basis=approvals.get('basis', '') if review else '',
            available_independent_pairs=len(paired), agreeing_fields=agree,
            disagreement_fields=int(paired.agreement.eq('disagree').sum()),
            agreement_percent=round(100 * agree / len(paired), 2) if len(paired) else None,
            non_independent_checks=int(selected.independent_pair.eq(False).sum()) if len(selected) else 0,
            agreement_status='partial_available_fields_only' if len(paired) else 'paired_field_values_not_available'))
    summary = pd.DataFrame(summaries)
    summary.to_csv(folder / 'paper_agreement_summary.csv', index=False)
    review_table = summary.loc[summary.human_review_status.eq('accepted'),
        ['paper', 'doi', 'human_review_status', 'data_use_status']]
    concordance_table = summary[['paper', 'available_independent_pairs', 'agreeing_fields',
        'disagreement_fields', 'agreement_percent', 'agreement_status']]
    notes = ''.join('<li>' + html.escape(note) + '</li>' for note in document['limitations'])
    text = ('<!doctype html><meta charset="utf-8"><title>Literature extraction comparison</title>'
            '<style>body{font:16px Georgia,serif;margin:24px}td,th{padding:8px;border-bottom:1px solid #ddd}'
            'table{border-collapse:collapse}section,details{overflow-x:auto}summary{cursor:pointer;padding:12px 0}</style>'
            '<h1>Human versus automated literature extraction</h1><p>Concordance = agreeing comparable fields / '
            'paired comparable fields. Missing and non-independent fields are not counted as agreements. '
            'Human review and research-use approval are recorded separately from computed concordance.</p><ul>' +
            notes + '</ul><h2>Human review and research-use approval</h2><section>' +
            review_table.to_html(index=False, escape=True) +
            '</section><h2>Computed field concordance (separate from approval)</h2><section>' +
            concordance_table.to_html(index=False, escape=True, na_rep='Not calculated') + '</section>' +
            '<details><summary>Full approval and concordance metadata</summary>' +
            summary.to_html(index=False, escape=True, na_rep='Not calculated') + '</details>' +
            '<h2>Disagreements and unpaired fields</h2>' +
            frame.loc[frame.agreement.ne('agree')].to_html(index=False, escape=True) +
            '<details><summary>All field comparisons</summary>' + frame.to_html(index=False, escape=True) + '</details>')
    (folder / 'LITERATURE_EXTRACTION_COMPARISON.html').write_text(text)
    (folder / 'agreement_summary.json').write_text(json.dumps(summaries, indent=2))
    return summaries


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('input')
    parser.add_argument('output')
    arguments = parser.parse_args()
    print(json.dumps(export_comparison(arguments.input, arguments.output), indent=2))
