# Workflow Sources and Data Scope

## Active Workflow Scope

This repository version contains an evidence-informed Neurodesk prototype workflow, not a diagnostic model. The current runnable analysis is a single-case prototype using one completed FreeSurfer subject.

## Structural MRI Data Used

- Dataset source: OASIS selected subject upload in Neurodesk.
- Completed FreeSurfer subject: OAS1_0003_MR1.
- FreeSurfer subject directory in Neurodesk runtime: /home/jovyan/derivatives/freesurfer/OAS1_0003_MR1.
- Active structural feature CSV in Neurodesk runtime: /home/jovyan/oasis_selected/ipd_vertical_dataset/oasis_freesurfer_roi_vertical_OAS1_0003_single_case.csv.
- Rows in active CSV at export time: 251.
- Subjects represented: OAS1_0003_MR1.
- Diagnoses represented: Dementia.
- Available columns: subject_id, diagnosis, sex, age, mmse, cdr, roi_name, imaging_metric, value_numeric, data_level, statistic_type, source_pipeline, hemisphere, unit, source_subject_dir, source_stats_file, metadata_source, metadata_completeness_status, analysis_scope, comparison_role.

## Data Limitations

- Only one measured participant is available in the current workflow run.
- sex is unknown and age, MMSE, and CDR are missing unless participant metadata is re-uploaded.
- No group-level comparison should be claimed from this version.
- Evidence matches are candidate matches and require manual review; they are not accepted evidence.

## Literature Evidence Sources

The active candidate evidence sources are listed in workflow_sources/literature_source_registry.json. Generated database artifacts such as SQLite, SQL dumps, spreadsheet exports, and runtime CSV outputs are intentionally excluded from Git.
