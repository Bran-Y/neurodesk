# Active Source Code

The root notebook loads these modules through `run_workflow.bootstrap()`.
`workflow_paths.py` anchors shared data paths to the project root.

| Area | Main modules |
| --- | --- |
| Entry and controls | `user_pipeline.py`, `notebook_input.py`, `case_controls.py`, `case_controls.js` |
| Features | `finished_evidence_workflow.py`, `neurodesk_literature_to_pgsql.py`, `comparison_atlas.py`, `t2_pipeline.py` |
| Normative references | `mmc_normative_workflow.py`, `potvin_subcortical.py`, `reference_range_overlap.py` |
| Disease evidence | `pd_evidence.py`, `pd_reviewed_comparison.py`, `zheng_exploratory.py`, `possible_disease_interpretation.py` |
| Reports | `concise_case_report.py`, `compact_report_panel.py`, `report_interpretation.py` |
| QC and images | `report_quality.py`, `segmentation_holds.py`, `segmentation_viewer.py`, `mri_viewer.py`, `assistant_visual_review.py` |
| Provenance | `literature_audit.py`, `source_catalog_visibility.py`, `patient_evidence_ledger.py`, `*_fulltext_review.py` |

Existing import names are retained to avoid rewriting scientific logic. The widget
JavaScript remains adjacent to its Python module. Reference data belong under
`workflow_sources/`, not this directory.
