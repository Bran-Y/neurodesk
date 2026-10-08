"""Add the optional AI panel without replacing unrelated remote edits."""
from datetime import datetime, timezone
from pathlib import Path
import shutil


def install(root=None):
    root = Path(root or Path(__file__).parent)
    for name in ('ai_evidence_assistant.py', 'compact_report_panel.py'):
        compile((root / name).read_text(), name, 'exec')
    from ai_evidence_assistant import settings
    settings(root)
    target = root / 'compact_report_panel.py'
    code = target.read_text()
    if 'self.ai = AIEvidencePanel(result, self.subject)' in code:
        print('AI hook already installed.')
        return
    old = '        self.box = widgets.VBox([self.subject, self.status, self.report, self.mri_button, self.mri.box, self.details])'
    new = '''        try:
            from ai_evidence_assistant import AIEvidencePanel
            self.ai = AIEvidencePanel(result, self.subject)
            ai_box = self.ai.box
        except (ImportError, OSError, ValueError):
            self.ai = None
            ai_box = widgets.HTML('<p>Optional AI module unavailable. Numeric reports are unaffected.</p>')
        self.box = widgets.VBox([self.subject, self.status, self.report, self.mri_button,
                                self.mri.box, ai_box, self.details])'''
    if code.count(old) != 1:
        raise ValueError('Panel changed; inspect before installation. No file modified.')
    updated = code.replace(old, new)
    compile(updated, str(target), 'exec')
    backup = root / 'maintenance' / ('ai_update_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True)
    shutil.copy2(target, backup / target.name)
    target.write_text(updated)
    print('Installed optional AI panel; original backed up in', backup)


if __name__ == '__main__':
    install()
