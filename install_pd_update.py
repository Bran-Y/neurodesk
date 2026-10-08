"""Install additive PD report hooks without replacing unrelated remote edits."""
import json
from datetime import datetime, timezone
from pathlib import Path


def install(root):
    root = Path(root)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    report = root / 'concise_case_report.py'
    text = report.read_text()
    if 'from pd_evidence import render_pd' not in text:
        anchor = '    from zheng_exploratory import compare, render\n'
        assert text.count(anchor) == 1, 'Report hook changed; inspect before modifying'
        text = text.replace(anchor, '    from pd_evidence import render_pd\n'
                            '    body.append(render_pd(result, subject_id))\n' + anchor)
    if 'from pd_evidence import compare_result' not in text:
        anchor = '    export_ledger(result, subject_id, output_dir)\n'
        assert text.count(anchor) == 1, 'Export hook changed; inspect before modifying'
        text = text.replace(anchor, anchor + '    from pd_evidence import compare_result\n'
                            "    pd.DataFrame(compare_result(result, subject_id)).to_csv(\n"
                            "        out / f'{subject_id}_pd_source_comparisons.csv', index=False)\n")
    compile(text, str(report), 'exec')
    backup = root / 'maintenance' / ('pd_update_' + stamp)
    backup.mkdir(parents=True, exist_ok=True)
    if text != report.read_text():
        (backup / report.name).write_bytes(report.read_bytes())
        report.write_text(text)
    catalog_path = root / 'workflow_sources/Disease/disease_literature_sources.json'
    catalog = json.loads(catalog_path.read_text())
    papers = json.loads((root / 'workflow_sources/Disease/PD/pd_literature.json').read_text())
    ids = {r['paper_code'] for r in papers}
    updated = [r for r in catalog if r.get('paper_code') not in ids] + papers
    (backup / catalog_path.name).write_bytes(catalog_path.read_bytes())
    catalog_path.write_text(json.dumps(updated, indent=2) + '\n')
    print('PD report hooks and catalog installed; backups:', backup)


if __name__ == '__main__':
    install(Path(__file__).parent)
