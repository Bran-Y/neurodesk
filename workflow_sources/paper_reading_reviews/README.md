# Three-paper reading update

## Files
- three_paper_review.json: methods, cohort definitions, limitations and exact source locations.
- zheng_2023_supplement_manifest.json: archive hashes, file counts and program headers.
- zheng_2023_supplement_statistics.json: 280 recomputed group-level records from S1/S2.

## Important findings

Zheng 2023: each development supplement has 263 scan directories containing aseg
and bilateral aparc statistics. Selected data give AD left hippocampus
2919.012 mm3 (sample SD 534.125), not the printed Table 1 mean 2933.4
and SD 540.1. Control left mean/SD reproduce approximately 3562.863/431.101.
Do not replace published values or enable ranking before reconciling the AD discrepancy.
Scan-directory uniqueness is not independently verified person identity. Program
CVS headers do not establish an exact FreeSurfer release. DKT and a2009s files
also exist, but this extraction uses aparc.stats (DK), not those alternate atlases.

Desikan 2009: selected OASIS estimated-MCI labels and ADNI converter-MCI labels
are not interchangeable. Left/right measures are added in the described
analysis and volumes corrected for eTIV. Table 2 performance statistics are
not individual normal ranges; do not substitute parent OASIS age bounds.

Du 2007: Table 2 contains lobar thickness mean/SD for AD, FTD and controls.
These are not individual gyral or hemisphere references. Clinical diagnoses
lack autopsy confirmation; no age min/max was inferred from means and SDs.

All additions remain pending human review and comparison_compatible=false.
No original numerical reference rows were replaced; Stage 8 is not automatically
enabled by this source intake. External ADNI evidence remains separate from
the OASIS pilot cohort and needs scope/reuse review.

## Reproduction

Download public supplements via the publisher links:
- https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0279574.s001&type=supplementary
- https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0279574.s002&type=supplementary

Run build_paper_reading_update.py with those ZIP paths. It reads ZIP members
without extracting or executing them and writes aggregates only. It uses
sample SD (ddof=1), original hemisphere labels and each file's native atlas.
Run install_paper_reading_reviews.py to link the reviews to canonical registries.
Individual records and source ZIP files are not published in this update.

Sources:
- https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0279574
- https://pmc.ncbi.nlm.nih.gov/articles/PMC2714061/
- https://pmc.ncbi.nlm.nih.gov/articles/PMC1853284/
