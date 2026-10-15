"""Entry point for the notebook, maintenance commands, and regression tests."""
from pathlib import Path
import runpy
import sys
import unittest

ROOT = Path(__file__).resolve().parent


def bootstrap():
    for relative in ('src', 'tools'):
        path = str(ROOT / relative)
        if path not in sys.path:
            sys.path.append(path)
    return ROOT


def main():
    bootstrap()
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        if len(sys.argv) > 2:
            sys.path.insert(0, str(ROOT / 'tests'))
            suite = unittest.defaultTestLoader.loadTestsFromNames(sys.argv[2:])
        else:
            suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_*.py')
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    if len(sys.argv) > 1:
        script = (ROOT / sys.argv[1]).resolve()
        if not script.is_relative_to(ROOT / 'tools') or not script.is_file():
            raise SystemExit('Specify a Python script under tools/, or use: python run_workflow.py test')
        sys.argv = [str(script), *sys.argv[2:]]
        runpy.run_path(str(script), run_name='__main__')
        return 0
    from user_pipeline import show
    show()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
