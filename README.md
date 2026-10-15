# Neurodesk MRI Evidence Workflow

**Structural MRI measurements, traceable literature evidence, and research reports.**

Start with [00_START_HERE.ipynb](00_START_HERE.ipynb). This workflow connects
FreeSurfer measurements with normative references and AD/PD research evidence.
It supports segmentation QC, regional comparisons, MRI views, and saved reports.
It is a research prototype, not a validated diagnostic service.

## Repository Guide

| Location | Purpose |
| --- | --- |
| [00_START_HERE.ipynb](00_START_HERE.ipynb) | Main interactive entry point |
| [src/](src/README.md) | Active workflow, reference comparisons, QC, report rendering |
| [workflow_sources/](workflow_sources/) | Literature registries, extracted statistics, atlas mappings |
| [tests/](tests/) | Regression tests |
| [tools/](tools/README.md) | Explicit maintenance and reporting commands |
| [docs/](docs/README.md) | Documentation and migration map |
| [validation_tools/](validation_tools/) | Reference-calculator validation support |
| [config.json](config.json), [participants.csv](participants.csv) | Configuration and empty metadata template |

`input_data/`, `cases/`, `subjects_fs53/`, and `outputs/` are local runtime data,
not public GitHub content. Historical installers and notebooks are not entry points.

## Quick Start

1. Keep this directory structure intact on your Neurodesk server.
2. Install dependencies into the notebook kernel: `python -m pip install -r requirements.txt`.
3. Open `00_START_HERE.ipynb` and run the entry cell. It loads `src/` automatically.
4. Select an existing case, or provide a de-identified MRI and metadata through the form.
5. For new processing only, confirm modality and start processing. Existing results do not need reprocessing.
6. Generate reports, review segmentation QC, and inspect comparisons and source evidence.

T1 processing requires Neurodesk FreeSurfer 5.3 and a valid FreeSurfer license.
T2 uses a separate FreeSurfer 8.2 descriptive workflow; it is not silently substituted
into the T1 normative comparison. Processing can take hours.

## Evidence and Interpretation

- Potvin references support normative comparisons for compatible measurements.
- ENIGMA PD provides published group-effect direction and stage-reference context.
- AD literature contributes regional evidence where compatible data are available.
- Source records, QC decisions, and measurement coverage remain inspectable.
- Coverage and pattern agreement are not diagnostic accuracy or disease probability.

## Development

```bash
python run_workflow.py test
node tests/test_case_controls_frontend.cjs
python run_workflow.py tools/audit_all_patients.py --help
```

For a Python session, run `from run_workflow import bootstrap; bootstrap()` before
importing modules. The notebook and CLI entry points do this automatically.

## Public Repository Safety

Do not publish patient images, case metadata, patient reports, credentials, FreeSurfer
binaries, or downloaded papers without permission. Ignore rules reduce accidental
staging; they do not remove already-tracked files or establish redistribution rights.
Review the staged files and source licenses before publication. No blanket license
is granted for third-party data.
