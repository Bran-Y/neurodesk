"""Repeat the PDF numeric extraction; keep human approval and discrepancies separate."""
from collections import Counter
import hashlib
import json
from pathlib import Path


def review(root, pdf):
    from import_pd_supplement import extract, reported_number
    source = Path(root) / 'workflow_sources/Disease/PD'
    pdf = Path(pdf)
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if sha != '076e783485824d61d168958060e9d4188d68393d615e4275b03c38b5fea4a2a1':
        raise ValueError('Different source PDF')
    extracted = extract(pdf)
    lookup = {(row['source_table'], row['source_structure']): row for row in extracted}
    fields = ('p_value_as_reported', 'effect_size', 'regression_coefficient',
              'regression_standard_error', 'regression_ci_lower', 'regression_ci_upper',
              'percent_difference', 'n_patients', 'n_controls')
    rows = []
    for name in ('enigma_pd_group_statistics.json', 'enigma_pd_stage_statistics.json'):
        for record in json.loads((source / name).read_text())['records']:
            row = lookup.pop((record['source_table'], record['source_structure']))
            differences = {field: dict(stored=record[field], pdf=row[field])
                           for field in fields if record[field] != row[field]}
            repository_differences = {}
            if 'raw_columns' in record:
                raw = record['raw_columns']
                mapping = dict(effect_size='d_icv', n_patients='n_patients', n_controls='n_controls',
                    p_value_as_reported='pobs', regression_standard_error='se_icv',
                    regression_ci_lower='low_ci_icv', regression_ci_upper='up_ci_icv',
                    percent_difference='%diff')
                for field, column in mapping.items():
                    original = raw[column] if field == 'p_value_as_reported' else reported_number(raw[column])
                    if original != row[field]:
                        repository_differences[field] = dict(existing=original, supplement=row[field])
                if repository_differences != record.get('supplement_discrepancies', {}):
                    raise ValueError('Repository/PDF difference no longer matches the recorded hold: ' + record['evidence_id'])
            if differences and (name != 'enigma_pd_group_statistics.json' or record['direction_eligible']):
                raise ValueError('Unexpected/unwithheld source discrepancy: ' + record['evidence_id'])
            rows.append(dict(evidence_id=record['evidence_id'], source_table=row['source_table'],
                source_page=row['source_page'], fields_checked=len(fields), differences=differences,
                repository_vs_pdf_differences=repository_differences,
                stored_human_review_status=record['human_review_status'],
                direction_eligible=record['direction_eligible'],
                technical_status='source_difference_retained_and_withheld' if differences else 'stored_fields_match_reextracted_pdf',
                source_row=row['source_row_text']))
    if lookup or len(rows) != 760:
        raise ValueError('Incomplete source review')
    result = dict(reviewed_at='2026-10-04', reviewer_role='assistant', source_pdf_sha256=sha,
        source_store_sha256={name: hashlib.sha256((source / name).read_bytes()).hexdigest()
            for name in ('enigma_pd_group_statistics.json', 'enigma_pd_stage_statistics.json')},
        method='Same extraction parser rerun on original PDF; not independent manual extraction.',
        visually_checked_pdf_pages=[8, 9, 11, 25], total_rows=len(rows),
        field_difference_rows=sum(bool(row['repository_vs_pdf_differences']) for row in rows),
        current_structured_field_difference_rows=sum(bool(row['differences']) for row in rows),
        direction_withheld_rows=sum(not row['direction_eligible'] for row in rows),
        raw_human_status_counts=dict(Counter(row['stored_human_review_status'] for row in rows)),
        human_approval_inferred=False, records=rows)
    out = Path(root) / 'outputs/pending_review_20261004'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'enigma_source_technical_review.json').write_text(json.dumps(result, indent=2))
    return result
