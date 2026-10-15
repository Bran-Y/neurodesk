"""Regression checks for the organized, AI-report-free repository layout."""
import ast
import importlib
import json
from pathlib import Path
import unittest

from workflow_paths import project_root


class LayoutTests(unittest.TestCase):
    def test_root_and_data_locations(self):
        root = project_root()
        self.assertTrue((root / '00_START_HERE.ipynb').is_file())
        self.assertTrue((root / 'workflow_sources').is_dir())
        self.assertTrue((root / 'requirements.txt').is_file())

    def test_runtime_imports_and_widget_asset(self):
        root = project_root()
        for name in ('user_pipeline', 'compact_report_panel', 'concise_case_report',
                     'report_quality', 'pd_evidence', 'report_interpretation'):
            module = importlib.import_module(name)
            self.assertEqual(Path(module.__file__).parent, root / 'src')
        import case_controls
        self.assertTrue(Path(case_controls.__file__).with_suffix('.js').is_file())
        self.assertIn('function render', str(case_controls.CaseControls._esm))

    def test_no_retired_ai_module_imports(self):
        retired = {'ai_credentials', 'ai_evidence_assistant', 'automatic_ai_report', 'notebook_ai_key'}
        for folder in ('src', 'tools', 'tests'):
            for path in (project_root() / folder).rglob('*.py'):
                for node in ast.walk(ast.parse(path.read_text())):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        names = [node.module]
                    self.assertFalse({name.split('.')[0] for name in names} & retired, str(path))

    def test_notebook_initializes_paths_before_workflow(self):
        data = json.loads((project_root() / '00_START_HERE.ipynb').read_text())
        cell = next(c for c in data['cells'] if c['cell_type'] == 'code')
        source = ''.join(cell['source'])
        self.assertLess(source.index('bootstrap()'), source.index('import user_pipeline'))

    def test_old_ai_snapshot_export_removed(self):
        import report_quality
        self.assertFalse(hasattr(report_quality, 'export_ai_snapshot'))


if __name__ == '__main__':
    unittest.main()
