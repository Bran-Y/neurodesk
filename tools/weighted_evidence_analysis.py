"""Internal, non-reporting review of proposed PD evidence channel weights."""

import csv
import json
from pathlib import Path


PROPOSED_WEIGHTS = {
    'potvin': 20,
    'enigma_pd': 35,
    'other_quantitative': 25,
    'qualitative': 20,
}


def _rows(path):
    with path.open(newline='', encoding='utf-8') as source:
        return list(csv.DictReader(source))


def _count(rows, field, value):
    return sum(row.get(field) == value for row in rows)


def _integer(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def analyze_case(folder, subject_id):
    """Return evidence-channel facts in memory, without scoring or writing files."""
    folder = Path(folder)
    if Path(subject_id).name != subject_id:
        raise ValueError('Invalid subject ID')
    if sum(PROPOSED_WEIGHTS.values()) != 100:
        raise ValueError('Evidence weights must total 100')

    prefix = subject_id + '_'
    interpretation_path = folder / (prefix + 'interpretation.json')
    if not interpretation_path.exists():
        raise ValueError('Interpretation source not found for requested subject')
    interpretation = json.loads(interpretation_path.read_text(encoding='utf-8'))
    if interpretation.get('subject_id') != subject_id:
        raise ValueError('Interpretation subject does not match the requested subject')
    if interpretation.get('reference_focus') != 'PD':
        raise ValueError('Analysis requires a PD-reference case')

    potvin = _rows(folder / (prefix + 'all_potvin_measurements.csv'))
    enigma = _rows(folder / (prefix + 'pd_source_comparisons.csv'))
    additional = _rows(folder / (prefix + 'additional_pd_comparisons.csv'))
    coverage = _rows(folder / (prefix + 'source_coverage.csv'))
    pd_evidence = interpretation['possible_disease_interpretation']['pd']
    profile = pd_evidence['directional_profile']
    aligned = profile['aligned']
    opposed = profile['opposed']
    at_expected = profile['at_expected']
    assessed = profile['assessed']
    if assessed != len(aligned) + len(opposed) + len(at_expected):
        raise ValueError('ENIGMA directional profile counts are inconsistent')

    descriptive = [row for row in additional
                   if row.get('comparison_status') == 'descriptive_difference']
    return {
        'subject_id': subject_id,
        'proposed_weights_percent': dict(PROPOSED_WEIGHTS),
        'weights_validated': False,
        'measurement_qc_status': interpretation.get('measurement_qc_status'),
        'potvin': {
            'calculated': _count(potvin, 'calculation_status', 'calculated'),
            'total': len(potvin),
            'below_95pi': _count(potvin, 'range_status', 'below_95pi'),
            'above_95pi': _count(potvin, 'range_status', 'above_95pi'),
        },
        'enigma_pd': {
            'matched': _count(enigma, 'match_status', 'matched_for_context'),
            'total': len(enigma),
            'directionally_assessed': assessed,
            'aligned': len(aligned),
            'opposed': len(opposed),
            'at_expected': len(at_expected),
            'aligned_outside_95pi': sum(
                row.get('normative_status') in ('below_95pi', 'above_95pi')
                for row in aligned
            ),
        },
        'other_quantitative': {
            'descriptive_group_mean_rows': len(descriptive),
            'source_papers': sorted({row['paper'] for row in descriptive if row.get('paper')}),
        },
        'qualitative': {
            'patient_specific_reviewed_links': sum(
                _integer(row.get('used_for_subject_qualitative')) for row in coverage
            ),
        },
        'weighted_total': None,
        'disease_probability': None,
        'assigned_diagnosis': None,
        'research_tendency': 'indeterminate',
        'known_diagnosis_used_as_input': False,
    }
