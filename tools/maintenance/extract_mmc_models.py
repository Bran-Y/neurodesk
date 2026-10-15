"""Extract numeric parameters and formula provenance without running Excel macros."""
import hashlib
import json
import re
import sys
from pathlib import Path

import openpyxl


def extract(path):
    w = openpyxl.load_workbook(path, keep_vba=True)
    if w['Thickness']['A1'].value != 'CORTICAL NORMS CALCULATOR (Desikan-Killiany atlas)':
        raise ValueError('Unsupported workbook atlas')
    if (w['Matrix']['C2'].value, w['Matrix']['G2'].value) != (
        '=Surface!F6-47.5830239', '=Surface!J6-1528926.15'
    ):
        raise ValueError('Workbook covariate centering changed')

    def matrix(name):
        # Parse the single absolute range; some Excel names include trailing spaces.
        ref = w.defined_names[name].attr_text.strip()
        sheet, cells = ref.split('!')
        cells = cells.strip()
        obj = w[sheet.strip("'")][cells]
        if hasattr(obj, 'value'):
            return [[obj.value]]
        return [[c.value for c in row] for row in obj]

    models = []
    for sheet, metric, unit in [('Thickness', 'cortical_thickness', 'mm'),
                                ('Surface', 'surface_area', 'mm2'),
                                ('Volume', 'roi_volume', 'mm3')]:
        for row in range(12, 87):
            formula = w[sheet][f'C{row}'].value
            if not isinstance(formula, str):
                continue
            match = re.search(r'MMULT\(X_(\w+),B_\1\)', formula)
            if not match:
                continue
            key = match[1]
            formulas = {}
            for col in ['C', 'D', 'E', 'F', 'I', 'L']:
                value = w[sheet][f'{col}{row}'].value
                formulas[col] = value.text if hasattr(value, 'text') else value
            if '1.961*SQRT' not in formulas['D'] or '2000-2' not in formulas['L']:
                raise ValueError(f'Unsupported interval/percentile formula: {sheet}!{row}')
            terms = matrix('p_' + key)[0]
            beta = [v[0] for v in matrix('B_' + key)]
            covariance = matrix('M_' + key)
            assert len(terms) == len(beta) == len(covariance)
            assert all(len(r) == len(beta) for r in covariance)
            models.append(dict(model_id=key, roi_name=key.rsplit('_', 1)[0].lower(),
                               hemisphere='lh' if key.rsplit('_', 1)[1][0] == 'L' else 'rh',
                               imaging_metric=metric, unit=unit,
                               label=w[sheet][f'A{row}'].value,
                               terms=terms, beta=beta, covariance=covariance,
                               mse=matrix('MSE_' + key)[0][0],
                               source_cells=f'{sheet}!C{row}:L{row}', formulas=formulas))
    return dict(source_file=Path(path).name,
                source_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                source_title='Normative morphometric data for cerebral cortical areas over the lifetime of the adult human brain',
                doi='10.1016/j.neuroimage.2017.05.019', atlas='Desikan-Killiany',
                reference_freesurfer_version='5.3', age_range=[18, 94],
                age_center=47.5830239, etiv_center=1528926.15,
                interval_multiplier=1.961, percentile_df=1998,
                implementation='Numeric port of C/D/E/F/I/L formulas; no VBA or FDR/CI macro execution.',
                models=models)


if __name__ == '__main__':
    data = extract(sys.argv[1])
    Path(sys.argv[2]).write_text(json.dumps(data, indent=2) + '\n')
    print(f'Extracted {len(data["models"])} models; sha256={data["source_sha256"]}')
