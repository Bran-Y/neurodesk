"""Verify a report refresh allows only the six approved reference corrections."""
import json
from pathlib import Path
import pandas as pd
from resolve_enigma_sources import CORRECTIONS, CONFLICT_ID, CONFLICT_NOTE
from pd_evidence import reported_direction_context


def compare_source_refresh(old, new):
    checked, changes = [], []
    for previous in sorted(Path(old).parent.glob('*')):
        if previous.suffix not in ('.csv', '.json'):
            continue
        current = Path(new).parent / previous.name
        if not current.is_file():
            raise ValueError('Missing export: ' + previous.name)
        if previous.suffix == '.json':
            if json.loads(previous.read_text()) != json.loads(current.read_text()):
                raise ValueError('Patient interpretation changed')
        else:
            before, after = pd.read_csv(previous), pd.read_csv(current)
            expected = before.copy(deep=True)
            if previous.name.endswith('_pd_source_comparisons.csv'):
                for eid, (field, old_value, value, page) in CORRECTIONS.items():
                    hits = expected.index[expected.evidence_id.eq(eid)]
                    if len(hits) != 1:
                        raise ValueError('Missing/duplicate correction row')
                    index = hits[0]
                    column = {'effect_size': 'pd_minus_control_cohen_d', 'n_patients': 'n_pd'}.get(field, field)
                    previous_value = expected.at[index, column]
                    if float(previous_value) not in (old_value, value):
                        raise ValueError('Unexpected previous reference value: ' + eid + ' / ' + column)
                    # A censored CI in another row makes this whole CSV column text.
                    expected.at[index, column] = str(value) if isinstance(previous_value, str) else value
                    expected.at[index, 'direction_eligible'] = True
                    expected.at[index, 'source_warning'] = 'Canonical values from published supplementary Table S2b.'
                    if expected.at[index, 'match_status'] == 'matched_for_context':
                        expected.at[index, 'context'] = reported_direction_context(
                            expected.at[index, 'normative_status'], expected.at[index, 'pd_minus_control_cohen_d'],
                            expected.at[index, 'p_as_reported'])
                    changes.append(dict(file=previous.name, evidence_id=eid, field=field, value=value))
            elif previous.name.endswith('_pd_stage_comparisons.csv'):
                hits = expected.index[expected.evidence_id.eq(CONFLICT_ID)]
                if len(hits) != 1 or bool(expected.at[hits[0], 'direction_eligible']):
                    raise ValueError('Stage conflict was not excluded')
                expected.at[hits[0], 'source_warning'] = CONFLICT_NOTE
            elif previous.name.endswith('_atlas_comparisons.csv'):
                # The atlas export duplicates the primary comparison's context text.
                # Its inputs are checked strictly in the companion source export below.
                primary = pd.read_csv(current.with_name(previous.name.replace(
                    '_atlas_comparisons.csv', '_pd_source_comparisons.csv')))
                for eid in CORRECTIONS:
                    hits = expected.index[expected.evidence_id.eq(eid)]
                    source_rows = primary.loc[primary.evidence_id.eq(eid)]
                    if len(hits) != 1 or len(source_rows) != 1:
                        raise ValueError('Missing/duplicate atlas correction row')
                    index, source = hits[0], source_rows.iloc[0]
                    if expected.at[index, 'match_status'] == 'matched_for_context':
                        expected.at[index, 'context'] = reported_direction_context(
                            source.normative_status, source.pd_minus_control_cohen_d, source.p_as_reported)
            try:
                pd.testing.assert_frame_equal(expected, after, check_exact=True, check_dtype=False)
            except AssertionError as exc:
                raise AssertionError('Unapproved export change: ' + previous.name + '\n' + str(exc)) from exc
        checked.append(previous.name)
    if not checked:
        raise ValueError('No baseline exports')
    return checked, changes
