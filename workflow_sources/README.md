# Workflow Source Registries

This folder separates literature/database source metadata into two auditable groups and then indexes papers by disease and ROI.

- `Disease/disease_literature_sources.json`: disease, pathology, clinical subtype, AD/FTD interpretation, and dataset-provenance sources.
- `Disease/AD/`, `Disease/FTD/`, `Disease/MCI/`, `Disease/VaD/`, `Disease/Mixed_Dementia/`: disease-specific paper indexes.
- `ROI/roi_literature_sources.json`: ROI, imaging-methods, hippocampal volume, cortical thickness, MRI atrophy-rate, and regional-feature evidence sources.
- `ROI/Hippocampus/`, `ROI/Amygdala/`, `ROI/Entorhinal_Cortex/`, `ROI/Parahippocampal_Gyrus/`, `ROI/Medial_Temporal_Lobe/`, `ROI/Cortical_Thickness/`, `ROI/White_Matter/`, `ROI/Whole_Brain_Atrophy/`, `ROI/Covariate_Adjustment/`, `ROI/Dataset_Provenance/`: ROI- or method-specific paper indexes.
- `atlas_translation/minimal_atlas_translation.json`: minimal atlas harmonisation dictionary. It maps source-specific FreeSurfer and literature ROI labels into workflow-standard ROI names, hemisphere, ROI category, translation confidence, and manual review status.

Each category row records `paper_code`, title, DOI, disease labels, extracted ROIs, imaging metrics, and evidence use. `paper_code` links the category index to the full canonical record and original URL.

`quantitative_reference_statistics.json` is the table-level registry used for patient-to-paper comparison. Every row records the source table, disease group, ROI, hemisphere, metric, mean, standard deviation, unit, sample size, atlas/parcellation information, article license, extraction method, and manual verification status. A row enters numerical ranking only when its units and feature definition are compatible with the patient feature and its source has been manually verified.

The quantitative registry also retains manually verified MAPS/MAPS-HBSI hippocampal volume and longitudinal atrophy-rate distributions from `ROI-009`. They remain excluded from the current FreeSurfer single-time-point ranking because the segmentation method and longitudinal endpoint are not harmonized.

## Atlas and segmentation naming

- `Desikan-Killiany-Tourville (DKT) Atlas` is used only for cortical measurements extracted from `lh.aparc.DKTatlas.stats` or `rh.aparc.DKTatlas.stats`.
- `FreeSurfer aseg (automated subcortical segmentation)` is used for hippocampus, amygdala, thalamus, ventricles, and other subcortical volumes extracted from `aseg.stats`.
- A derived feature that combines cortical and subcortical regions is labelled `mixed FreeSurfer aseg + Desikan-Killiany-Tourville (DKT) Atlas`.
- `atlas_name` describes the actual feature definition used by the workflow. If a paper does not report its exact FreeSurfer atlas/version, that uncertainty remains in `verification_note` and must be considered during harmonization.

## Atlas translation layer

The minimal atlas translation workflow is implemented in `atlas_translation_minimal_workflow.ipynb`. It reads the project dictionary at `atlas_translation/minimal_atlas_translation.json`, applies it to the structural FreeSurfer CSV, and produces an audit table with:

- original `source_roi_name` and `source_atlas_name`
- translated `standard_roi_name` and `standard_hemisphere`
- `standard_roi_category`
- `atlas_translation_rule`
- `atlas_translation_confidence`
- `atlas_translation_review_status`

This layer supports comparison across FreeSurfer output, paper evidence, MMC/Potvin normative validation, and final reports. It does not itself classify disease. Rows marked `pending_human_review` should remain visible but should not be used as final quantitative evidence until ROI definition and atlas compatibility are checked.

`method_evidence_statistics.json` stores numerical results that must not be represented as patient reference ranges. These include classifier AUC/sensitivity/specificity, FTD subtype regional patterns, and longitudinal rates without reusable mean/SD distributions. Stage 2A displays this layer separately and builds an extraction-coverage row for every registered paper.

Coverage statuses distinguish:

- quantitative ranges available for current matching
- complete quantitative ranges that are not harmonized
- method or regional-pattern evidence only
- bibliographic or qualitative registry records that still require table-level extraction

Current license handling is explicit:

- PLOS and MDPI CC BY sources may be reused with attribution.
- Sources with an unconfirmed license remain visible but require a license check.
- Traditionally copyrighted sources remain in the audit trail but are not treated as freely reusable content.

The root Disease and ROI JSON files remain the canonical database inputs. Category files may reference one paper more than once when it supports several ROIs; downstream code must deduplicate by `paper_code` before building the database.

## Synchronizing quantitative evidence

After editing `quantitative_reference_statistics.json`, refresh the Disease and ROI indexes with:

```bash
python3 workflow_sources/sync_quantitative_reference_categories.py
```

The synchronizer preserves qualitative entries, updates or inserts papers by `paper_code`, and embeds the applicable audited rows under `quantitative_evidence`. Disease indexes retain the relevant control and cross-disease groups from each paper. ROI indexes retain only rows for that exact ROI. `Control` is a comparison group and is therefore not maintained as a standalone disease folder.

Generated databases and extracted output artifacts should remain outside Git.
