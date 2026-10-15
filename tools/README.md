# Maintenance Tools

Run from the project root: `python run_workflow.py tools/<script>.py [arguments]`.

- `audit_*.py`: inspect saved outputs and evidence.
- `build_*.py`: build report collections.
- `refresh_*.py`: update existing saved outputs; review scope before running.
- `prepare_*.py`, `finalize_*.py`: dataset-specific preparation and review utilities.
- `maintenance/`: existing extraction and processing helpers; inspect paths before use.

Historical installers, repairs, and AI-era evaluation helpers were moved to an
external recovery backup, not included in the active tool directory.

Some tools require private data and server-specific paths. None run automatically.
A filename beginning with `finalize` does not authorize QC approval.
