# Neurodesk research workflow

Research prototype for structural MRI comparison and literature-linked reporting,
not a diagnostic service. Start with `00_START_HERE.ipynb`.

This public repository contains the workflow code, entry notebook, tests and
structured research references. It does not contain patient images, FreeSurfer
results, generated reports, credentials, original paper PDFs, or the original
Potvin calculator workbook. Supply authorized inputs and a FreeSurfer license
in your own environment. Do not commit patient data or credentials.

## Notebook input form
Run the notebook and use Patient input. Select a new T1 upload (up to 256 MiB),
an existing server image path, or a completed FS5.3 subject folder. Enter anonymous
ID, age, sex, magnetic field strength and scanner manufacturer. Click Validate &
use case: configuration is saved under cases/ID automatically. No CSV/JSON editing
is required for this route. Uploaded files are removed from widget memory after saving.
Use a new ID for new processing; saved IDs cannot be overwritten. For returning
cases enter cases/ID/config.json in Config. Do not start FS5.3 for existing results.
The original file-based route below remains available as an alternative.

## Quick start
1. Keep this folder intact. Install `requirements.txt` in your notebook kernel if needed.
2. Upload de-identified T1 NIfTI files using JupyterLab's file browser into `input_data/`,
   or use existing completed FreeSurfer 5.3 subject folders. MRI files are not included.
3. Fill `participants.csv`; configure `config.json`. Paths are relative to the config file.
   For existing results, set `subjects_dir` to their parent directory. Do not point it
   at FS8.2 outputs for a Potvin report. Every listed case must be completed.
4. Open the notebook, choose a Python kernel, Run All, then click Check status.
5. For new inputs only, confirm processing and click Start FS5.3. Neurodesk must supply
   `ml freesurfer/5.3.0` and a functioning FreeSurfer license. This serial detached queue
   can take hours per case. Closing the browser does not cancel it. Do not repeatedly submit.
   Read `outputs/queue_*.log` and per-case `*.processing.log` files if processing fails.
6. Once complete, click Generate reports. Select the subject and expand Research details.
   HTML reports contain static MRI views and can be opened without a notebook kernel.

## Metadata
Required: subject_id, age, sex (Male/Female as encoded by the reference model),
scanner_field_strength (tesla), scanner_manufacturer (Siemens/GE/Philips).
These are model requirements, not universal patient categories. Unsupported or missing
values must not be guessed. eTIV is read from that subject's actual aseg.stats.
For new processing add t1_path and t1_confirmed=true after confirming modality.
The NIfTI check does NOT establish T1 contrast or clinical image quality.
No OASIS scanner defaults or known diagnosis labels are supplied to the model.

## Data and scope
- Potvin main input is completed FS5.3 with bilateral DK aparc.stats.
- Output includes cortical thickness, volume and surface area. Missing reference
  coverage means unassessed, not normal. Subcortical calculator remains preview-only.
- Input completion checks do not replace visual skull stripping/segmentation QC.
- Atlas naming approval is distinct from numerical compatibility validation.
- FS8.2 and an in-house control group are not mixed into the Potvin reference.
- OASIS can supply evaluation cases; these cases are not automatically controls or
  disease evidence. Reference cohorts must exclude the evaluated participant and repeat scans.
- Supplied evidence records retain their source citations, approvals and limitations.
  Verify source/data licenses before redistribution; no new blanket license is granted.

## Contents
The root contains the active runtime modules, one entry notebook, example
configuration, tests and `workflow_sources/`. Some root-level `install_*`,
`refresh_*`, and `repair_*` scripts are site-specific migration helpers; they
are not needed for a new run and should not be executed without reviewing
their paths and effects. Case-specific QC scripts and historical test logs are
omitted. `requirements.txt` lists minimum dependencies, not a validated lockfile.
The core comparison and report tests can be run with:

```sh
python -m unittest test_pd_evidence test_report_interpretation \
  test_possible_disease_interpretation test_user_pipeline \
  test_mmc_normative_workflow test_case_controls test_pd_pattern_profile \
  test_report_presentation -q
```

The full test suite requires source PDFs, calculator workbooks and optional
interactive components intentionally omitted from this public release; it is
not expected to pass in a fresh checkout without those fixtures.

Structured literature records include source citations and provenance; their
presence is not permission to redistribute original article files or to use
group-level findings as individual diagnostic thresholds. The extracted Potvin
model data are for research comparison under the source's applicable terms.

## Remaining work
This release is a single-user notebook workflow, not a deployed multi-user web app.
Failed existing processing directories require manual inspection; automatic resume,
cancel UI, browser reconnection recovery and arbitrary new-patient end-to-end validation
remain future work. Do not interpret exported reports as clinical clearance.
