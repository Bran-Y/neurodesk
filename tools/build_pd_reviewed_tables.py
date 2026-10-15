"""Import approved extractions without changing their reported statistics."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def moments(raw):
    parts = re.findall(r'[-+]?\d*\.?\d+', str(raw).replace('\u2212', '-').replace(',', '.'))
    return (float(parts[0]), float(parts[1])) if len(parts) >= 2 else (None, None)


def workbook_tables(path):
    from openpyxl import load_workbook
    output = {}
    for sheet in load_workbook(path, read_only=True, data_only=True):
        if sheet.title.startswith('Table ') or sheet.title == 'Cortical findings':
            values = list(sheet.values)
            output[sheet.title] = [dict(zip(values[0], row)) for row in values[1:]
                                  if any(value is not None for value in row)]
    return output


def xml_tables(path):
    output = {}
    for wrap in ET.parse(path).findall('.//table-wrap'):
        table = wrap.find('.//table')
        output[wrap.findtext('label')] = dict(
            headers=[[ ''.join(c.itertext()) for c in r] for r in table.findall('./thead/tr')],
            rows=[[ ''.join(c.itertext()) for c in r] for r in table.findall('./tbody/tr')],
            footnotes=[''.join(f.itertext()) for f in wrap.findall('./table-wrap-foot/fn')])
    return output


def build(extractions, mak_dom, gerrits_xml, output):
    sources = []
    def source(name, doi, version, tables, path):
        obj = dict(paper=name, doi=doi, processing_version=version,
                   approval_status='accepted', source_tables=tables, records=[],
                   extraction_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                   extraction_file=Path(path).name, source_url='https://doi.org/' + doi)
        sources.append(obj)
        return obj

    for name, doi, filename, version in (
            ('Sokolowski 2024', '10.1371/journal.pone.0295069',
             'Sokolowski_2024_PLOS_PD_longitudinal_extraction.xlsx', '7.1.1'),
            ('Hanganu 2014', '10.1093/brain/awu036',
             'Hanganu_2014_Brain_PD_MCI_longitudinal_extraction.xlsx', '5.3.0')):
        path = Path(extractions) / filename
        tables = workbook_tables(path)
        obj = source(name, doi, version, tables, path)
        for table_name, rows in tables.items():
            if table_name == 'Table 1':
                continue
            for index, raw in enumerate(rows, 2):
                if 'mean_change' in ' '.join(map(str, raw)) or 'PD-MCI mean +/- SD' in raw:
                    for group in ('PD-MCI', 'PD-non-MCI', 'HC'):
                        mean = raw.get(group + ' mean_change')
                        sd = None
                        if group + ' mean +/- SD' in raw:
                            mean, sd = moments(raw[group + ' mean +/- SD'])
                        obj['records'].append(dict(source_table=table_name, source_row=index,
                            record_kind='longitudinal_change', group=group,
                            structure=raw.get('structure', raw.get('structure_code')),
                            mean=mean, sd=sd, percent_change=raw.get(group + ' percent_change', raw.get(group + ' percent')),
                            unit=raw.get('unit', 'mm' if raw.get('structure') == 'CTh' else 'mm3'),
                            definition='Published longitudinal change; not current absolute morphology', raw=raw))
                else:
                    obj['records'].append(dict(source_table=table_name, source_row=index,
                        record_kind='correlation' if any(str(k).startswith('r ') for k in raw) else
                                    'vertex_cluster' if 'cluster_size_mm2' in raw else 'qualitative_map',
                        structure=raw.get('region', raw.get('structure', raw.get('regions'))), raw=raw))
    path = Path(mak_dom)
    dom = json.loads(path.read_text())
    obj = source('Mak 2015 ICICLE-PD', '10.1093/brain/awv211', '5.3.0',
                 {'Table 1': dom[0]['rows'], 'Table 2': dom[1]['rows']}, path)
    side = None
    for index, raw in enumerate(dom[1]['rows'][2:], 3):
        side = {'Left': 'lh', 'Right': 'rh'}.get(raw[0], side)
        for group, offset in (('HC', 2), ('PD-NC', 4), ('PD-MCI', 6)):
            for kind, column, unit in (('baseline_volume', offset, 'ml'),
                                       ('longitudinal_change', offset + 1, '%')):
                mean, sd = moments(raw[column])
                obj['records'].append(dict(source_table='Table 2', source_row=index,
                    record_kind=kind, group=group, structure=raw[1], hemisphere=side,
                    mean=mean, sd=sd, unit=unit, raw=raw,
                    definition='Native aseg, FS5.3 longitudinal-stream initialized measurements',
                    study_group_test_p=raw[8 if kind == 'baseline_volume' else 9]))
    path = Path(gerrits_xml)
    tables = xml_tables(path)
    obj = source('Gerrits 2016', '10.1371/journal.pone.0148852', '5.3.0', tables, path)
    for name in ('Table 2', 'Table 3', 'Table 4'):
        for index, raw in enumerate(tables[name]['rows'], 1):
            if name == 'Table 4':
                obj['records'].append(dict(source_table=name, source_row=index,
                    record_kind='correlation', structure=raw[1], raw=raw))
                continue
            kind = 'vertex_cluster' if name == 'Table 2' else 'pial_surface_area' if 'surface' in raw[0].lower() else 'log_volume'
            for group, column in (('PD', 2), ('HC', 3)):
                mean, sd = moments(raw[column])
                obj['records'].append(dict(source_table=name, source_row=index,
                    record_kind=kind, group=group, structure=raw[0 if name == 'Table 2' else 1],
                    mean=mean, sd=sd, unit='mm' if name == 'Table 2' else 'mm2' if kind == 'pial_surface_area' else 'log(volume)',
                    definition='Vertex cluster, not whole DK parcel' if name == 'Table 2' else
                        'Pial area, not aparc white-surface area' if kind == 'pial_surface_area' else
                        'Ventricle volume log-transformed; logarithm base not specified in table/methods', raw=raw))
    data = dict(schema_version=1, approval_manifest='workflow_sources/paper_reading_reviews/pd_paper_review_approvals.json',
        sources=sources, limitations=['Study approval does not establish individual diagnostic validation.',
        'No reference mean, SD, sign, p-value or transformation is inferred from a patient diagnosis.'])
    for obj in sources:
        for number, record in enumerate(obj['records'], 1):
            record['evidence_id'] = obj['paper'].split()[0].upper() + f'_Q{number:04d}'
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(data, indent=2, ensure_ascii=True) + '\n')
    print([(s['paper'], len(s['records'])) for s in sources])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--extractions', type=Path, required=True)
    parser.add_argument('--mak-dom', type=Path, required=True)
    parser.add_argument('--gerrits-xml', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.extractions, args.mak_dom, args.gerrits_xml, args.output)
