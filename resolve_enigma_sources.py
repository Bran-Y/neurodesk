"""Apply visually checked primary-source corrections, never human QC approval."""
import copy
import hashlib
import json
from pathlib import Path

PDF_SHA = '076e783485824d61d168958060e9d4188d68393d615e4275b03c38b5fea4a2a1'
PREFIX = 'PD-ENIGMA-2021:CortSurf:'
CORRECTIONS = {
    PREFIX + 'L_posteriorcingulate': ('n_patients', 239, 2309, 9),
    PREFIX + 'R_caudalanteriorcingulate': ('regression_ci_lower', -7.17, -7.71, 8),
    PREFIX + 'R_isthmuscingulate': ('regression_ci_upper', 25.0, 25.90, 8),
    PREFIX + 'R_lateralorbitofrontal': ('effect_size', -0.053, 0.053, 8),
    PREFIX + 'R_postcentral': ('effect_size', 0.003, -0.003, 9),
    PREFIX + 'R_superiorparietal': ('regression_ci_lower', 48.78, -48.78, 9),
}
CONFLICT_ID = 'PD-ENIGMA-2021:Subvol:LLatVent:HY4-5'
CONFLICT_NOTE = ('Confirmed published sign conflict: S3c (page 11) d=-0.357; '
                 'S4l (page 25) d=+0.357, b=2761.46. Direction excluded; author clarification required.')


def apply_resolutions(whole, stage, sha):
    if sha != PDF_SHA:
        raise ValueError('Primary PDF changed; these resolutions no longer apply')
    records = {r['evidence_id']: r for r in whole['records']}
    for eid, (field, old, value, page) in CORRECTIONS.items():
        row = records[eid]
        if (row['supplement_sha256'] != sha or row['source_table'] != 'S2b'
                or row['source_page'] != page or row[field] not in (old, value)
                or row.get('supplement_discrepancies') !=
                {field: {'existing': old, 'supplement': value}}):
            raise ValueError('Correction does not match stored source: ' + eid)
        row[field] = value
        row['direction_eligible'] = True
        row['source_warning'] = 'Canonical values from published supplementary Table S2b.'
        row['primary_source_resolution'] = dict(status='resolved_to_primary_pdf',
            reviewer_role='assistant', reviewed_at='2026-10-04', pdf_sha256=sha,
            table='S2b', page=page, field=field, repository_value=old,
            canonical_value=value, human_approval_inferred=False)
    conflict = next(r for r in stage['records'] if r['evidence_id'] == CONFLICT_ID)
    if (conflict['supplement_sha256'] != sha or conflict['effect_size'] != .357
            or conflict['regression_coefficient'] != 2761.46):
        raise ValueError('Published conflict row changed')
    conflict['direction_eligible'] = False
    conflict['source_warning'] = CONFLICT_NOTE
    conflict['primary_source_resolution'] = dict(status='confirmed_published_conflict_excluded',
        reviewer_role='assistant', reviewed_at='2026-10-04', pdf_sha256=sha,
        summary_effect=-.357, detailed_effect=.357, human_approval_inferred=False)


def resolve(root):
    from import_pd_supplement import extract
    folder = Path(root) / 'workflow_sources/Disease/PD'
    pdf = folder / 'raw/mds28706-sup-0001-supinfo.pdf'
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    whole = json.loads((folder / 'enigma_pd_group_statistics.json').read_text())
    stage = json.loads((folder / 'enigma_pd_stage_statistics.json').read_text())
    before = copy.deepcopy(whole), copy.deepcopy(stage)
    apply_resolutions(whole, stage, sha)
    lookup = {(r['source_table'], r['source_structure']): r for r in extract(pdf)}
    fields = ('p_value_as_reported', 'effect_size', 'regression_coefficient',
              'regression_standard_error', 'regression_ci_lower', 'regression_ci_upper',
              'percent_difference', 'n_patients', 'n_controls')
    for data, original in zip((whole, stage), before):
        for row, old in zip(data['records'], original['records']):
            source = lookup[row['source_table'], row['source_structure']]
            if any(row[k] != source[k] for k in fields):
                raise ValueError('Canonical fields disagree with PDF: ' + row['evidence_id'])
            for key in ('human_review_status', 'raw_columns', 'supplement_discrepancies'):
                if row.get(key) != old.get(key):
                    raise ValueError('Source history or human status changed')
    for name, data in [('enigma_pd_group_statistics.json', whole),
                       ('enigma_pd_stage_statistics.json', stage)]:
        (folder / name).write_text(json.dumps(data, indent=2) + '\n')
    from review_enigma_source import review
    result = review(root, pdf)
    print('SOURCE RESOLUTION', result['current_structured_field_difference_rows'],
          'canonical mismatches;', result['direction_withheld_rows'], 'direction excluded', flush=True)


if __name__ == '__main__':
    resolve(Path(__file__).parent)
