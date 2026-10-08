"""Import pinned ENIGMA PD group statistics, never individual reference ranges."""
import csv
import hashlib
import io
import json
from pathlib import Path
from urllib.request import urlopen

COMMIT = 'b08974b55243060cbc1fad12c87048037446e8f7'
BASE = 'https://raw.githubusercontent.com/MICA-MNI/ENIGMA/' + COMMIT + '/'
DOI = '10.1002/mds.28706'
TITLE = "International Multicenter Analysis of Brain Structure Across Clinical Stages of Parkinson's Disease"
TABLES = [('CortThick', 'cortical_thickness', 'mm'),
          ('CortSurf', 'surface_area', 'mm2'), ('Subvol', 'roi_volume', 'mm3')]


def install(root):
    sources = Path(root) / 'workflow_sources'
    folder = sources / 'Disease/PD'
    raw = folder / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    records, downloads = [], []
    for table, metric, unit in TABLES:
        name = 'parkinsons_case-controls_' + table + '_PDvsCN.csv'
        url = BASE + 'enigmatoolbox/datasets/summary_statistics/' + name
        data = urlopen(url, timeout=60).read()
        rows = list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
        assert rows and {'Structure', 'd_icv', 'n_controls', 'n_patients'} <= set(rows[0])
        (raw / name).write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        downloads.append(dict(file=name, url=url, sha256=digest, rows=len(rows)))
        for line, row in enumerate(rows, 2):
            label = row['Structure']
            # Preserve source spelling; unsupported aggregate labels remain unmapped.
            side = {'L': 'lh', 'R': 'rh'}.get(label.split('_')[0], '')
            roi = label[2:] if side else label
            if table == 'Subvol':
                names = {'accumb': 'Accumbens-area', 'amyg': 'Amygdala', 'caud': 'Caudate',
                         'hippo': 'Hippocampus', 'pal': 'Pallidum', 'put': 'Putamen',
                         'thal': 'Thalamus-Proper', 'LatVent': 'Lateral-Ventricle'}
                assert label[0] in ('L', 'R') and label[1:] in names
                side = 'lh' if label[0] == 'L' else 'rh'
                roi = ('Left-' if side == 'lh' else 'Right-') + names[label[1:]]
            records.append(dict(
                evidence_id=f'PD-ENIGMA-2021:{table}:{label}', paper_code='PD-ENIGMA-2021',
                doi=DOI, source_title=TITLE, source_url='https://doi.org/' + DOI,
                source_data_url=url, source_line=line, source_sha256=digest,
                source_structure=label, roi_name=roi, hemisphere=side, imaging_metric=metric,
                unit=unit, atlas_name='FreeSurfer aseg' if table == 'Subvol' else 'Desikan-Killiany',
                processing_software_version='5.3.0', disease='PD', comparator='Control',
                effect_size=float(row['d_icv']), effect_size_type='Cohen d (PD minus Control)',
                n_controls=int(float(row['n_controls'])), n_patients=int(float(row['n_patients'])),
                p_value_as_reported=row.get('pobs'), raw_columns=row,
                evidence_type='group_effect_size', numeric_individual_range_use=False,
                mean=None, standard_deviation=None, lower_95pi=None, upper_95pi=None,
                human_review_status='pending_human_review',
                permitted_use='descriptive_group_direction_context',
                limitations='No individual reference distribution. Raw CI/SE columns are not treated as Cohen d intervals or individual PI. PPMI cohort overlap is possible; not independent validation.'))
    license_data = urlopen(BASE + 'LICENSE', timeout=60).read()
    (raw / 'ENIGMA_LICENSE.txt').write_bytes(license_data)
    package = dict(schema_version=1, repository_commit=COMMIT, downloads=downloads,
                   paper_doi=DOI, cohort_total=dict(PD=2357, Control=1182),
                   adjustment='Age, sex, cohort; ICV also for regional surface area and subcortical volume. See paper models 1a/1b.',
                   license_note='Repository BSD-3-Clause retained; paper/data attribution and PPMI terms remain applicable.',
                   records=records)
    (folder / 'enigma_pd_group_statistics.json').write_text(json.dumps(package, indent=2) + '\n')
    papers = [dict(paper_code='PD-ENIGMA-2021', source_title=TITLE, doi=DOI, year=2021,
                   evidence_use='Group PD/Control effect sizes; not individual normal ranges.',
                   data_file='workflow_sources/Disease/PD/enigma_pd_group_statistics.json'),
              dict(paper_code='PD-PPMI-2011', source_title='The Parkinson Progression Marker Initiative (PPMI)',
                   doi='10.1016/j.pneurobio.2011.09.005', year=2011,
                   evidence_use='Dataset design/provenance, not an ROI disease threshold.',
                   data_access_url='https://www.ppmi-info.org/access-data-specimens/download-data',
                   access_status='Individual-level additional data require authorized PPMI access; not downloaded by this importer.')]
    for paper in papers:
        paper.update(source_label=paper['source_title'], source_url='https://doi.org/' + paper['doi'],
                     input_value='https://doi.org/' + paper['doi'], disease_focus='PD',
                     evidence_category='disease_evidence', source_group='Parkinson disease evidence')
    (folder / 'pd_literature.json').write_text(json.dumps(papers, indent=2) + '\n')
    canonical = sources / 'Disease/disease_literature_sources.json'
    catalog = json.loads(canonical.read_text())
    ids = {p['paper_code'] for p in papers}
    catalog = [p for p in catalog if p.get('paper_code') not in ids] + papers
    canonical.write_text(json.dumps(catalog, indent=2) + '\n')
    print(json.dumps(dict(records=len(records), downloads=downloads), indent=2))


if __name__ == '__main__':
    install(Path(__file__).parent)
