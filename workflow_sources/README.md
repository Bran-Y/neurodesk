# Workflow Source Registries

This folder separates literature/database source metadata into two auditable groups.

- `Disease/disease_literature_sources.json`: disease, pathology, clinical subtype, AD/FTD interpretation, and dataset-provenance sources.
- `ROI/roi_literature_sources.json`: ROI, imaging-methods, hippocampal volume, cortical thickness, MRI atrophy-rate, and regional-feature evidence sources.

Each row has a `paper_code` so downstream evidence tables can link candidate matches back to the source registry and original URL.

Generated databases and extracted output artifacts should remain outside Git.
