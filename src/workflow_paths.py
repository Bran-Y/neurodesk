"""Keep data paths anchored to the bundle, not the relocated source files."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def project_root():
    return PROJECT_ROOT
