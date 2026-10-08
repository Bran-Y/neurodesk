from importlib import reload
import user_pipeline, compact_report_panel, concise_case_report, report_quality, mri_viewer, segmentation_viewer, workflow_audit, pd_evidence, pd_reviewed_comparison, report_interpretation, assistant_visual_review
for module in (assistant_visual_review, report_interpretation, pd_reviewed_comparison, pd_evidence, workflow_audit, mri_viewer, segmentation_viewer, report_quality, concise_case_report, compact_report_panel, user_pipeline):
    reload(module)
user_pipeline.show()
