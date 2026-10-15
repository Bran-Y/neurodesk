"""Rebuild saved report literature sections without changing clinical results."""
import hashlib
import json
from pathlib import Path
import re
import shutil
from datetime import datetime, timezone
import zipfile

import pandas as pd
from literature_audit import build_literature_audit
from source_catalog_visibility import unified_numeric_sources


def run(root):
    root = Path(root).resolve()
    inventory = json.loads((root/'outputs/final_reports_20261004/verification.json').read_text())
    selected = {root/r['report'] for r in inventory if r.get('report')}
    for case in (root/'cases').glob('*/config.json'):
        paths = sorted((root/'outputs'/case.parent.name).glob('**/concise_reports/*_concise_report.html'))
        if paths:
            selected.add(paths[-1])
    audit = build_literature_audit(root)['papers'].fillna('')
    pattern = re.compile(r'<details[^>]*>\s*<summary>(?:Literature coverage and zero-count explanations|Source catalog and evidence contribution)</summary>.*?</details>', re.S)
    plans = []
    for path in sorted(selected):
        sid = path.name.removesuffix('_concise_report.html')
        files = list(path.parent.parent.rglob(sid+'_source_coverage.csv'))
        direct = path.parent/(sid+'_source_coverage.csv')
        if direct.exists():
            files = [direct]
        assert len(files)==1, (sid, 'ambiguous or missing saved coverage', files)
        old = pd.read_csv(files[0]).fillna('')
        current = old.copy()
        # Refresh library counts only; never manufacture patient comparison counts.
        for _, paper in audit.iterrows():
            mask = current.doi.astype(str).str.lower().eq(str(paper.doi).lower()) if paper.doi else current.paper_id.eq(paper.paper_id)
            if not mask.any():
                current = pd.concat([current,pd.DataFrame([paper.to_dict()])],ignore_index=True)
            else:
                for key in ('quantitative_records','source_title','reported_statistic_records','unique_evidence_rows'):
                    current.loc[mask,key]=paper[key]
        shown = unified_numeric_sources(current)
        assert set(['10.1093/cercor/bhn113','10.1212/wnl.0b013e3182166e96','10.1016/j.neuroimage.2011.06.065']) <= set(shown.doi)
        section = '<details><summary>Source catalog and evidence contribution</summary><div style="overflow:auto">'+shown.to_html(index=False,escape=True,border=0)+'</div></details>'
        before = path.read_text()
        assert len(pattern.findall(before))==1, (sid,'unexpected source section')
        after = pattern.sub(lambda _: section,before)
        assert pattern.sub('',before)==pattern.sub('',after), 'Non-literature content changed'
        plans.append((path,after,sid,len(shown)))
    backup = root/'maintenance'/('saved_catalog_refresh_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True)
    protected = list((root/'outputs').glob('**/*.csv')) + list((root/'outputs').glob('segmentation_qc/**/*.json')) + list((root/'outputs').glob('segmentation_holds/**/*.json'))
    hashes = {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    for path,content,sid,count in plans:
        dest=backup/path.relative_to(root)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,dest)
        path.write_text(content)
        print('UPDATED',sid,count,'sources',str(path.relative_to(root)),flush=True)
    package=root/'final_patient_reports_20261004.zip'
    if package.exists():
        shutil.copy2(package,backup/package.name)
        replacements={str(p.relative_to(root)):p for p,_,_,_ in plans}
        temp=package.with_suffix('.refresh-tmp')
        with zipfile.ZipFile(package) as oldzip, zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as newzip:
            for info in oldzip.infolist():
                newzip.writestr(info,replacements.pop(info.filename).read_bytes() if info.filename in replacements else oldzip.read(info.filename))
            for name,path in replacements.items():
                newzip.write(path,name)
        temp.replace(package)
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==h for p,h in hashes.items())
    manifest={'reports':[{'subject_id':sid,'path':str(p.relative_to(root)),'sources':n} for p,_,sid,n in plans],
              'patient_measurements_and_qc_unchanged':True,'non_literature_html_unchanged':True}
    (backup/'verification.json').write_text(json.dumps(manifest,indent=2))
    print('COMPLETE',len(plans),'reports;',len(set(sid for _,_,sid,_ in plans)),'patients; measurements and QC unchanged',flush=True)


if __name__=='__main__':
    run(Path.cwd())
