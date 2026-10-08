"""Collect current outputs and displayed QC evidence without copying MRI or keys."""
from pathlib import Path
import json
import zipfile


def export(root):
    root = Path(root).resolve()
    archive = root / 'reviewed_pd_followup_results_20261003.zip'
    selected = {}
    for name in ('reviewed_pd_update_tests.log', 'reviewed_pd_patient_audit.log',
                 'workflow_sources/Disease/PD/reviewed_pd_quantitative_tables.json'):
        path = root / name
        if path.exists():
            selected[path] = name
    folder = root / 'outputs/patient_audit_reviewed_pd_20261003'
    for path in (root / 'outputs/assistant_visual_review_20261003').glob('*'):
        if path.is_file():
            selected[path] = str(path.relative_to(root))
    if folder.exists():
        for path in folder.iterdir():
            if path.is_file():
                selected[path] = str(path.relative_to(root))
    audit = folder / 'patient_output_checks.json'
    if audit.exists():
        for row in json.loads(audit.read_text()):
            if row.get('report_path'):
                parent = Path(row['report_path']).parent
                for path in parent.iterdir():
                    if path.is_file() and path.name.startswith(row['subject_id']):
                        selected[path] = str(path.relative_to(root))
    for path in (root / 'outputs/segmentation_overlay_cache').glob('*/*/boundaries_*/*'):
        if path.suffix in ('.json', '.png'):
            selected[path] = str(path.relative_to(root))
    for path in (root / 'outputs/segmentation_overlay_cache').glob('*/*/brain_mask_overlay.png'):
        selected[path] = str(path.relative_to(root))
    for name in ('repair_status.json', 'reconstruction.log', 'launcher.log', 'retry.sh'):
        path = root / 'maintenance/topology_retry_0031_20261003' / name
        if path.exists():
            selected[path] = str(path.relative_to(root))
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path, name in selected.items():
            bundle.write(path, name)
    print('FOLLOWUP_RESULTS_EXPORTED', archive.stat().st_size, len(selected))


if __name__ == '__main__':
    export(Path(__file__).parent)
