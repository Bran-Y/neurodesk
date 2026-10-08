# Parkinson disease sources

## Acquired data

Laansma et al. (2021), International Multicenter Analysis of Brain Structure Across Clinical Stages of Parkinson's Disease. DOI: https://doi.org/10.1002/mds.28706

The paper reports 2,357 PD participants and 1,182 controls. Imaging used FreeSurfer 5.3. The public ENIGMA TOOLBOX tables contain 68 cortical thickness, 68 cortical surface area and 16 subcortical volume group effects. Per-ROI sample counts are retained, rather than substituting the overall cohort size.

Published Table 1 cohort demographics are transcribed separately in
`enigma_pd_cohort_demographics.json`, including cohort-level sample size, age,
female percentage and PD disease duration. These fields support population
applicability and cohort-overlap review only; they are not ROI reference
ranges or patient-level diagnostic predictors.

Data documentation: https://enigma-toolbox.readthedocs.io/en/latest/pages/04.loadsumstats/#parkinson-s-disease

Pinned repository commit: b08974b55243060cbc1fad12c87048037446e8f7. Raw tables are not redistributed in this repository; every imported record contains its URL, CSV line and SHA-256 checksum. Consult the upstream repository for its license and original tables.

These data are adjusted group contrasts, NOT individual patient measurements, group mean/SD distributions, diagnostic cutoffs or individual prediction intervals. Raw CI and SE columns are preserved but not interpreted as Cohen d intervals: their scale is not equivalent to the d column in these files. Blank FDR values remain blank; p-values such as `<0.001` remain censored strings. No significance-based or probability classification is derived.

## Workflow use

`pd_evidence.py` routes both patient and reference labels through the existing Atlas Translation gateway. Units, FreeSurfer version, unique matching and normative calculation status are checked. Reports show measured values, Potvin interval status, the published PD-minus-Control effect and an explicit directional-context statement. Within-range findings do not establish Control or rule out PD. Missing mappings and unavailable normative models are retained, not converted into normal findings.

Both native aseg thalamus labels have registry mappings. Directional comparison
still requires a calculated individual normative result. The reference
source/mapping review is not asserted to be human-approved. This module does
not feed effect sizes into the individual-range ranking engine.

## Original supplement integration

The 65-page source PDF is not redistributed here.
`import_pd_supplement.py` extracts S2a-S2c (152 existing contrasts) and
S4a-S4l (608 stage-specific contrasts). Each record preserves its table,
page, extracted row, PDF SHA-256, metric-specific adjustments, and per-ROI
sample sizes. The main 152 records are enriched, not duplicated.

The automated eight-field audit in `enigma_pd_supplement_audit.json` found six
PDF/TOOLBOX discrepancies. All six rows remain mapped but cannot provide
directional candidate evidence. Original CSV values remain available.
The published right pallidum SE is normalized to 8.69; original `8,69` is retained.
Regression CI and SE describe the adjusted difference b, not d uncertainty or
an individual prediction interval. Automated extraction is not human approval.

`pd_evidence.py` now renders separate HY1/HY2/HY3/HY4-5 comparisons using the
same Atlas Translation and patient normative statuses. AI receives these as
separate sensitivity context, not additional independent candidate votes.
No patient HY stage is assigned. HY4-5 left ventricle direction is withheld
because summary S3c and detailed S4l disagree about its sign. Per-ROI sample
sizes are retained because summary HY totals also differ from the main text.
MoCA and duration regressions remain in the source PDF and are not yet imported.

PPMI is represented in the ENIGMA study. Membership overlap with the three test cases has not been excluded. Results must not be described as independent validation. Known participant diagnostic labels are not used in matching or inference.

## Individual patient data source

The Parkinson Progression Marker Initiative (PPMI), 2011. DOI: https://doi.org/10.1016/j.pneurobio.2011.09.005

Access: https://www.ppmi-info.org/access-data-specimens/download-data

This is a cohort/provenance reference, not an MRI threshold paper. Additional individual-level PD/Control data require authorized access and were NOT acquired by this update. The three user-provided PPMI images are test cases, not a newly constructed normative cohort. Clinical measures such as MDS-UPDRS, Hoehn and Yahr stage, MoCA and visit-specific diagnostic verification remain separate required inputs for a future PD clinical assessment.
