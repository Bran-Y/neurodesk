"""Extract auditable S2/S4 group contrasts from the supplied Laansma supplement."""
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'workflow_sources/Disease/PD'
PDF_NAME = 'mds28706-sup-0001-supinfo.pdf'
NUMBER = r'[<>]?-?\d+(?:[.,]\d+)?'
ROW = re.compile(r'^([LR]) (.+?)\s+(' + NUMBER + r'(?:\s+' + NUMBER + r'){8})$')
HEADER = re.compile(r'Supplementary\s+table\s+(\d+[a-z]?)\s*:', re.I)
SUB = {'Amygdala': 'amyg', 'Caudate nucleus': 'caud', 'Globus pallidus': 'pal',
       'Hippocampus': 'hippo', 'Lateral ventricle': 'LatVent',
       'Nucleus accumbens': 'accumb', 'Putamen': 'put', 'Thalamus': 'thal'}
TABLES = {'2a': ('cortical_thickness', 'whole_sample'),
          '2b': ('surface_area', 'whole_sample'), '2c': ('roi_volume', 'whole_sample')}
for letters, metric in [('abcd', 'cortical_thickness'), ('efgh', 'surface_area'), ('ijkl', 'roi_volume')]:
    for letter, stage in zip(letters, ['HY1', 'HY2', 'HY3', 'HY4-5']):
        TABLES['4' + letter] = (metric, stage)


def identity(side, name, metric):
    if metric == 'roi_volume':
        return side + SUB[name]
    label = 'bankssts' if name == 'Banks STS' else name.lower().replace(' ', '')
    return side + '_' + label


def reported_number(value):
    return value if value.startswith(('<', '>')) else float(value.replace(',', '.'))


def extract(path):
    import pdfplumber
    rows, current = [], None
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages[:26], 1):
            text = page.extract_text() or ''
            # Page 12 wraps the L Insula b value across lines; visually verified.
            if page_no == 12:
                text = text.replace('<0.00\nL Insula\n0.987 0.001 1 0.011 -0.022 0.022 0.006 430 840',
                                    'L Insula 0.987 0.001 <0.001 0.011 -0.022 0.022 0.006 430 840')
            if page_no == 13:
                text = text.replace('<0.00\nR Transverse temporal\n0.975 0.001 1 0.015 -0.029 0.030 0.021 435 845',
                                    'R Transverse temporal 0.975 0.001 <0.001 0.015 -0.029 0.030 0.021 435 845')
            for line in text.splitlines():
                header = HEADER.search(line)
                if header:
                    current = header[1].lower()
                if current not in TABLES:
                    continue
                match = ROW.fullmatch(line.strip())
                if not match:
                    if re.match(r'^[LR] [A-Z]', line):
                        raise ValueError(f'Unparsed ROI row on page {page_no}: {line}')
                    continue
                side, name, values = match.groups()
                fields = values.split()
                metric, stage = TABLES[current]
                rows.append(dict(source_table='S' + current, source_page=page_no,
                    source_row_text=line, source_roi_label=side + ' ' + name,
                    source_structure=identity(side, name, metric), imaging_metric=metric,
                    comparison_group=stage, p_value_as_reported=fields[0],
                    effect_size=reported_number(fields[1]), regression_coefficient=reported_number(fields[2]),
                    regression_standard_error=reported_number(fields[3]),
                    regression_ci_lower=reported_number(fields[4]), regression_ci_upper=reported_number(fields[5]),
                    percent_difference=reported_number(fields[6]), n_patients=int(fields[7]), n_controls=int(fields[8])))
    counts = Counter(r['source_table'] for r in rows)
    expected = {'S' + k: 16 if v[0] == 'roi_volume' else 68 for k, v in TABLES.items()}
    if dict(counts) != expected:
        raise ValueError(f'Incomplete tables: {counts}; expected {expected}')
    if len({(r['source_table'], r['source_structure']) for r in rows}) != len(rows):
        raise ValueError('Duplicate ROI in source table')
    return rows


def build(pdf_path):
    rows = extract(pdf_path)
    original = json.loads((DATA / 'enigma_pd_group_statistics.json').read_text())
    lookup = {(r['imaging_metric'], r['source_structure']): r for r in original['records']}
    audit, staged = [], []
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    for row in rows:
        key = row['imaging_metric'], row['source_structure']
        base = lookup[key]
        if row['comparison_group'] == 'whole_sample':
            differences = {}
            pairs = [('effect_size', reported_number(base['raw_columns']['d_icv'])),
                     ('n_patients', reported_number(base['raw_columns']['n_patients'])),
                     ('n_controls', reported_number(base['raw_columns']['n_controls'])),
                     ('p_value_as_reported', base['raw_columns']['pobs']),
                     ('regression_standard_error', reported_number(base['raw_columns']['se_icv'])),
                     ('regression_ci_lower', reported_number(base['raw_columns']['low_ci_icv'])),
                     ('regression_ci_upper', reported_number(base['raw_columns']['up_ci_icv'])),
                     ('percent_difference', reported_number(base['raw_columns']['%diff']))]
            for field, old in pairs:
                if old != row[field]:
                    differences[field] = {'existing': old, 'supplement': row[field]}
            audit.append(dict(evidence_id=base['evidence_id'], source_page=row['source_page'],
                              fields_checked=len(pairs), differences=differences))
            # Preserve the existing values when a source discrepancy needs review.
            dest = base
            if differences:
                dest['supplement_discrepancies'] = differences
        else:
            dest = copy.deepcopy(base)
            dest.update(row)
            dest['evidence_id'] = base['evidence_id'] + ':' + row['comparison_group']
            dest.pop('raw_columns', None)
            dest.pop('supplement_discrepancies', None)
            dest.pop('source_line', None)
            dest.pop('primary_source_resolution', None)
            dest['source_data_url'] = 'https://doi.org/10.1002/mds.28706'
            dest['source_sha256'] = digest
            staged.append(dest)
        for field in ('source_table', 'source_page', 'source_row_text', 'source_roi_label',
                      'comparison_group', 'regression_coefficient', 'regression_standard_error',
                      'regression_ci_lower', 'regression_ci_upper', 'percent_difference'):
            dest[field] = row[field]
        dest['supplement_file'] = 'workflow_sources/Disease/PD/raw/' + PDF_NAME
        dest['supplement_sha256'] = digest
        dest['regression_ci_target'] = 'adjusted_group_difference_b'
        dest['automated_source_check'] = 'extracted_from_pdf; not independent human review'
        dest['dependence_group'] = 'Laansma_2021_ENIGMA_PD'
        dest['direction_eligible'] = not bool(dest.get('supplement_discrepancies'))
        dest['source_warning'] = ''
        if row['comparison_group'] == 'HY4-5' and row['source_structure'] == 'LLatVent':
            dest['source_warning'] = 'S3c reports negative d; S4l reports positive d and b. Direction withheld pending source review.'
            dest['direction_eligible'] = False
        dest['adjustment'] = ('Whole sample: age, sex; cohort random intercept.' if row['comparison_group'] == 'whole_sample'
                              else 'Stage vs age/sex-matched controls; cohort random intercept.')
        if row['imaging_metric'] != 'cortical_thickness':
            dest['adjustment'] += ' ICV adjusted.'
    staged_data = dict(schema_version=1, paper_doi=original['paper_doi'],
        source_pdf_sha256=digest, records=staged,
        interpretation='Stage-stratified sensitivity context; no patient HY stage is inferred. Same study, overlapping controls; do not aggregate as independent votes.',
        source_issues=['S3c left lateral ventricle HY4-5 d sign conflicts with S4l; direction withheld.',
                       'S3 summary sample totals differ from main text HY totals; retain per-ROI NPD/NHC from S4.',
                       'Rounded/censored p values cannot always determine Bonferroni significance; no significance classifier implemented.'])
    original['supplementary_stage_file'] = 'enigma_pd_stage_statistics.json'
    original['supplement_source_file'] = 'raw/' + PDF_NAME
    # Reimports must not undo source-bound resolutions already checked against this PDF.
    if any(r.get('primary_source_resolution') for r in original['records']):
        from resolve_enigma_sources import apply_resolutions
        apply_resolutions(original, staged_data, digest)
    DATA.joinpath('raw').mkdir(exist_ok=True)
    destination = DATA / 'raw' / PDF_NAME
    if destination.resolve() != pdf_path.resolve():
        shutil.copyfile(pdf_path, destination)
    for filename, data in [('enigma_pd_group_statistics.json', original),
                           ('enigma_pd_stage_statistics.json', staged_data),
                           ('enigma_pd_supplement_audit.json', dict(source_pdf_sha256=digest,
                            tables=dict(Counter(r['source_table'] for r in rows)),
                            audit_type='automated_field_comparison', human_review_status='pending_human_review',
                            full_sample_checks=audit))]:
        (DATA / filename).write_text(json.dumps(data, indent=2) + '\n')
    print(json.dumps(dict(extracted=len(rows), new_stage_rows=len(staged),
                         audited=len(audit), mismatched_rows=sum(bool(a['differences']) for a in audit))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    build(parser.parse_args().pdf)
