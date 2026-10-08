"""Replay independently captured Calc outputs; no patient data or AI requests."""
import hashlib
import json
import math
from pathlib import Path

FIXTURE_SHA256 = '5c84c9ac1475c5da412cd419fcb8e50670a971fa1688bcd9ad378890606e6c43'
RELATIVE_DIR = Path('workflow_sources/external_validators/potvin_subcortical')


def verify(root, models=None):
    from potvin_subcortical import extract, predict, MODELS, WORKBOOK_SHA256
    from validate_mmc2_calc import synthetic_cases
    root = Path(root)
    raw = (root / RELATIVE_DIR / 'calc_validation_fixture.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
        raise ValueError('Unverified mmc2 Calc fixture revision')
    fixture = json.loads(raw)
    if (fixture['workbook_sha256'] != WORKBOOK_SHA256 or
            fixture['source_workbook_macros_executed'] is not False or
            fixture['workbook_saved'] is not False or
            fixture['blank_age_guard_passed'] is not True or
            fixture['baseline_repeat_passed'] is not True or
            fixture['engine'] != 'LibreOffice Calc'):
        raise ValueError('Invalid Calc validation metadata')
    harness = root / 'validation_tools/mmc2_capture.bas'
    if hashlib.sha256(harness.read_bytes()).hexdigest() != fixture['harness_sha256']:
        raise ValueError('Calc harness differs from captured validation')
    models = extract(root / RELATIVE_DIR / 'mmc2.xlsm') if models is None else models
    if {m['name'] for m in models} != set(MODELS) or len(models) != 4:
        raise ValueError('Incomplete mmc2 model set')
    expected_cases = list(synthetic_cases())
    if len(fixture['cases']) != len(expected_cases):
        raise ValueError('Incomplete Calc input coverage')
    errors = []
    for i, (case, inputs) in enumerate(zip(fixture['cases'], expected_cases)):
        if case['case_id'] != f'synthetic_{i:03d}' or case['inputs'] != inputs:
            raise ValueError('Calc input coverage differs')
        if set(case['outputs']) != set(MODELS):
            raise ValueError('Incomplete Calc outputs')
        for model in models:
            for key, actual in zip(('expected', 'lower_95pi', 'upper_95pi'), predict(model, inputs)):
                expected = case['outputs'][model['name']][key]
                if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-7):
                    raise ValueError(f"Calc concordance failed: {case['case_id']} {model['name']} {key}")
                errors.append(abs(actual - expected))
    return dict(status='calc_formula_concordance_passed', engine=fixture['engine_version'],
                cases=len(expected_cases), numeric_comparisons=len(errors),
                max_absolute_error_mm3=max(errors), workbook_sha256=WORKBOOK_SHA256,
                fixture_sha256=FIXTURE_SHA256,
                native_excel_validated=False, clinically_validated=False)


if __name__ == '__main__':
    print(json.dumps(verify(Path(__file__).parent), indent=2))
