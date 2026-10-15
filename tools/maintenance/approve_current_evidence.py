"""Apply user approval to pending source/mapping records, never compatibility gates."""
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path


def approve(root):
    root = Path(root)
    src = root / 'workflow_sources'
    stamp = datetime.now(timezone.utc).isoformat()
    batch = root / 'notebook_backups' / ('evidence_approval_' + stamp.replace(':', '-'))
    changes = []

    def visit(value, pointer, entries, implicit_pending=False):
        if isinstance(value, list):
            for i, row in enumerate(value):
                visit(row, f'{pointer}/{i}', entries, implicit_pending)
        elif isinstance(value, dict):
            fields = [k for k in ('human_review_status', 'manual_review_status')
                      if value.get(k) in ('pending_human_review', 'pending_review')]
            if implicit_pending and any(k in value for k in ('imaging_metric', 'paper_code', 'reference_id')) and not value.get('human_review_status'):
                fields.append('human_review_status')
            rejected = any(value.get(k) == 'rejected' for k in
                           ('human_review_status', 'manual_review_status', 'source_review_status', 'case_review_status'))
            if fields and not rejected:
                entries.append({'pointer': pointer, 'previous': {k: value.get(k) for k in fields}})
                for field in fields:
                    value[field] = 'accepted'
                value['human_review_status'] = 'accepted'
                value['data_use_status'] = 'user_approved_research_use'
                value['approval_record'] = {
                    'approved_at': stamp, 'approved_by': 'project_user',
                    'basis': 'Explicit user request: approve the currently pending records',
                    'scope': 'Research use subject to measurement compatibility checks',
                    'independent_source_reverification': False,
                }
            for key, row in list(value.items()):
                if key != 'approval_record':
                    visit(row, pointer + '/' + key, entries)

    candidates = [src / f for f in ('quantitative_reference_statistics.json',
                  'method_evidence_statistics.json', 'reviewed_roi_evidence.json')]
    for folder in ('Disease', 'ROI', 'paper_reading_reviews', 'atlas_translation'):
        candidates.extend((src / folder).rglob('*.json'))
    for path in sorted(set(candidates)):
        if not path.exists() or any(p.startswith('.') for p in path.parts):
            continue
        original = path.read_bytes()
        value = json.loads(original)
        entries = []
        visit(value, '', entries, path.parent == src)
        if not entries:
            continue
        if path.parent.name == 'atlas_translation' and isinstance(value, dict):
            value.setdefault('status_scheme', {})['accepted'] = (
                'User approved research use; mapping relation, anatomical equivalence '
                'and quantitative compatibility remain independently checked.')
        backup = batch / path.relative_to(root)
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(original)
        updated = (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()
        path.write_bytes(updated)
        changes.append({'path': str(path.relative_to(root)), 'records': entries,
                        'before_sha256': hashlib.sha256(original).hexdigest(),
                        'after_sha256': hashlib.sha256(updated).hexdigest()})
    if changes:
        ledger = src / 'evidence_approval_history.json'
        history = json.loads(ledger.read_text()) if ledger.exists() else []
        history.append({'approved_at': stamp, 'backup': str(batch), 'changes': changes})
        ledger.write_text(json.dumps(history, indent=2) + '\n')
    return {c['path']: len(c['records']) for c in changes}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    from workflow_paths import project_root
    parser.add_argument('--root', type=Path, default=project_root())
    print(json.dumps(approve(parser.parse_args().root), indent=2))
