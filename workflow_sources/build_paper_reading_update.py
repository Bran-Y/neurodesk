"""Reproduce supplemental-file audit; never enable diagnostic ranking.

Usage: python3 workflow_sources/build_paper_reading_update.py /tmp/zheng_s1.zip /tmp/zheng_s2.zip
Only aggregate statistics and provenance are written, not subject identifiers.
"""
import collections
import hashlib
import json
from pathlib import Path
import statistics
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'paper_reading_reviews'


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def extract(path, group):
    values = collections.defaultdict(list)
    counts = collections.Counter()
    headers = set()
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        selected = [n for n in names if n.endswith(('/aseg.stats', '/lh.aparc.stats', '/rh.aparc.stats'))]
        assert sum(n.endswith('/aseg.stats') for n in selected) == 263
        subject_dirs = [str(Path(n).parent.parent) for n in selected if n.endswith('/aseg.stats')]
        assert len(subject_dirs) == len(set(subject_dirs))
        for n in selected:
            filename = Path(n).name
            counts[filename] += 1
            data = z.read(n).decode('utf-8')
            for line in data.splitlines():
                if line.startswith(('# cvs_version', '# mrisurf.c-cvs_version', '# build-stamp')):
                    headers.add(line)
                if line.startswith('#') or not line.strip():
                    continue
                fields = line.split()
                if filename == 'aseg.stats':
                    roi = fields[4]
                    if roi not in ('Left-Hippocampus','Right-Hippocampus','Left-Amygdala','Right-Amygdala'):
                        continue
                    side, roi = roi.split('-', 1)
                    values[(roi.lower(), 'lh' if side == 'Left' else 'rh', 'roi_volume', 'FreeSurfer aseg', 'mm3')].append(float(fields[3]))
                else:
                    for metric, column, unit in [('roi_volume',3,'mm3'), ('cortical_thickness',4,'mm')]:
                        values[(fields[0], filename[:2], metric, 'Desikan-Killiany', unit)].append(float(fields[column]))
    rows = []
    for (roi, side, metric, atlas, unit), v in sorted(values.items()):
        rows.append(dict(diagnosis=group, roi_name=roi, hemisphere=side, imaging_metric=metric,
                         atlas_name=atlas, unit=unit, sample_size=len(v), mean=statistics.mean(v),
                         standard_deviation=statistics.stdev(v), statistic_origin='recomputed_from_supplement_not_printed_table',
                         doi='10.1371/journal.pone.0279574', source_file='S1' if group == 'AD' else 'S2',
                         reference_age_min=55, reference_age_max=97, age_scope='pooled study sample; individual ages unavailable in parsed stats',
                         human_review_status='pending_human_review', comparison_compatible=False,
                         limitation='Unadjusted; patient-level age/sex and cross-version calibration not established. Not a validated reference interval.'))
    return rows, dict(group=group, sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                      total_archive_entries=len(names), selected_files=dict(counts),
                      unique_scan_directories=len(subject_dirs), unique_persons_verified=False,
                      program_version_headers=sorted(headers),
                      software_release='not established from program CVS headers',
                      other_stats_filenames=sorted({Path(n).name for n in names if n.endswith('.stats')}))


if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    all_rows, manifests = [], []
    for path, group in zip(sys.argv[1:3], ['AD','Control']):
        rows, manifest = extract(path, group)
        all_rows.extend(rows)
        manifests.append(manifest)
    assert len(manifests) == 2
    save(OUT / 'zheng_2023_supplement_statistics.json', all_rows)
    save(OUT / 'zheng_2023_supplement_manifest.json', manifests)
    print('aggregate rows', len(all_rows))
    for r in all_rows:
        if r['roi_name'] == 'hippocampus':
            print(r['diagnosis'],r['hemisphere'],r['sample_size'],round(r['mean'],3),round(r['standard_deviation'],3))
