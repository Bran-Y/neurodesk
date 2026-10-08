"""Capture source mmc2 formulas using a separate LibreOffice Calc process.

Requires LibreOffice. Uses an isolated temporary profile and an auditable
StarBasic harness. Source workbook macros are disabled. No workbook saves,
patient data, listener sockets or AI requests.
"""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import subprocess
import tempfile
from xml.sax.saxutils import escape

WORKBOOK_SHA256 = 'c8a8c9e08d5703923a45eefe2d29ef6dc9c553fc12771f2f35df0af872bfc19f'
MODELS = {'Left_Hippocampus': 18, 'Right_Hippocampus': 19,
          'Left_Amygdala': 13, 'Right_Amygdala': 14}


def synthetic_cases():
    baseline = dict(age=60., sex='Male', scanner_field_strength=3.,
                    scanner_manufacturer='Siemens', estimated_total_intracranial_volume=1500000.)
    yield baseline.copy()
    for age, sex, field, manufacturer, etiv in itertools.product(
            (18., 40., 60., 94.), ('Male', 'Female'), (1.5, 3.),
            ('GE', 'Philips', 'Siemens'), (1200000., 1500000., 1800000.)):
        yield dict(age=age, sex=sex, scanner_field_strength=field,
                   scanner_manufacturer=manufacturer, estimated_total_intracranial_volume=etiv)
    yield baseline.copy()


def collect(workbook, soffice):
    workbook = Path(workbook).resolve()
    if hashlib.sha256(workbook.read_bytes()).hexdigest() != WORKBOOK_SHA256:
        raise ValueError('Unexpected workbook revision')
    cases = list(synthetic_cases())
    with tempfile.TemporaryDirectory(prefix='mmc2-calc-') as temp:
        folder = Path(temp)
        encoded = []
        for i, case in enumerate(cases):
            encoded.append(','.join(map(str, (i, case['age'], 1 if case['sex'] == 'Male' else 0,
                1 if case['scanner_field_strength'] == 1.5 else 0,
                {'GE': 1, 'Philips': 2, 'Siemens': 3}[case['scanner_manufacturer']],
                case['estimated_total_intracranial_volume']))))
        (folder/'inputs.csv').write_text('\n'.join(encoded))
        profile = folder/'profile'
        subprocess.run([str(soffice), '-env:UserInstallation='+profile.as_uri(),
                        '--headless', '--terminate_after_init'], check=True,
                       capture_output=True, text=True, timeout=60)
        library = profile/'user/basic/Standard'
        library.mkdir(parents=True, exist_ok=True)
        namespace = 'http://openoffice.org/2000/library'
        (library.parent/'script.xlc').write_text(f'<library:libraries xmlns:library="{namespace}"><library:library library:name="Standard" library:link="false"/></library:libraries>')
        (library/'script.xlb').write_text(f'<library:library xmlns:library="{namespace}" library:name="Standard" library:readonly="false" library:passwordprotected="false"><library:element library:name="Module1"/></library:library>')
        source = Path(__file__).parent/'validation_tools/mmc2_capture.bas'
        harness = source.read_text()
        for token, path in (('@WORKBOOK@', workbook), ('@INPUT@', folder/'inputs.csv'), ('@OUTPUT@', folder/'capture.csv')):
            harness = harness.replace(token, '"'+str(path).replace('"', '""')+'"')
        (library/'Module1.xba').write_text('<script:module xmlns:script="http://openoffice.org/2000/script" script:name="Module1" script:language="StarBasic">'+escape(harness)+'</script:module>')
        version = subprocess.run([str(soffice), '--headless', '--version'], check=True,
                                 capture_output=True, text=True, timeout=60).stdout.strip()
        try:
            subprocess.run([str(soffice), '-env:UserInstallation='+profile.as_uri(),
                '--headless', '--norestore', 'macro:///Standard.Module1.Main()'],
                check=True, capture_output=True, text=True, timeout=600)
            capture = (folder/'capture.csv').read_text()
        finally:
            if hashlib.sha256(workbook.read_bytes()).hexdigest() != WORKBOOK_SHA256:
                raise RuntimeError('Original workbook changed unexpectedly')
    captures = [dict(case_id=f'synthetic_{i:03d}', inputs=c, outputs={}) for i, c in enumerate(cases)]
    metadata = {}
    for line in capture.splitlines():
        if line.startswith('#'):
            key, value = line[1:].split('=', 1)
            metadata[key] = value
            continue
        i, name, *numbers = line.split(',')
        if name not in MODELS or len(numbers) != 3:
            raise ValueError('Unexpected Calc output')
        output = captures[int(i)]['outputs']
        if name in output:
            raise ValueError('Duplicate Calc output')
        mean, lower, upper = map(float, numbers)
        if not all(math.isfinite(v) for v in (mean, lower, upper)) or not lower < mean < upper:
            raise ValueError('Invalid Calc interval')
        output[name] = dict(expected=mean, lower_95pi=lower, upper_95pi=upper)
    if any(set(c['outputs']) != set(MODELS) for c in captures):
        raise ValueError('Incomplete Calc capture')
    if metadata.get('blank_age_guard') != 'passed' or not version.startswith('LibreOffice '):
        raise ValueError('Missing Calc validation metadata')
    if captures[0]['outputs'] != captures[-1]['outputs']:
        raise ValueError('Repeated baseline changed after input cycling')
    return dict(schema_version=1, engine='LibreOffice Calc', engine_version=version,
        workbook_sha256=WORKBOOK_SHA256, source_workbook_macros_executed=False, workbook_saved=False,
        harness_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        source_cells={name: f'Statistics!C{row}:E{row}' for name, row in MODELS.items()},
        blank_age_guard_passed=True, baseline_repeat_passed=True, cases=captures,
        limitation='Independent formula recalculation only; not native Excel or clinical validation.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workbook', type=Path)
    parser.add_argument('--soffice', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        fixture = collect(args.workbook, args.soffice)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.stderr or str(exc))
    with args.output.open('x') as stream:
        json.dump(fixture, stream, indent=2, allow_nan=False)
    print(f"Captured {len(fixture['cases'])} synthetic cases in {args.output}")
