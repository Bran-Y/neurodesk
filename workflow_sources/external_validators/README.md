# External normative validators

This folder contains an extracted MMC normal-reference model and optional manual exports. The original workbook is not redistributed.

## Automated normal-reference workflow

Run `mmc_normative_brain_health_workflow.ipynb` from the project directory.
It uses `mmc_dk_models.json`, extracted by `extract_mmc_models.py` from the supplied
`mmc1.xlsm`. The JSON records the workbook SHA256, model matrices and original
formula cells. It computes expected values, pointwise 95% prediction intervals,
ZOP and percentiles using the workbook formulas. This is normative assessment,
not machine-learning cross-validation. Excel macro-based CI and FDR calculations
are not reproduced.

The workbook title explicitly names Desikan-Killiany (DK). Its source reference is
Potvin et al., 2017, DOI https://doi.org/10.1016/j.neuroimage.2017.05.019.
Do not replace DK with DKT based on ROI names. The reference used FreeSurfer 5.3;
current 8.2 measurements require software-version and segmentation QC review.
Subcortical/aseg regions are outside this cortical workbook's coverage.

Outputs in `mmc_normative_outputs/` include covariate provenance, per-ROI normal
reference results, qualitative literature candidates and one report per subject.
No recorded diagnosis is used to compute a normal-reference result. Literature
numbers from different methods are not pooled. Matching a paper creates a candidate
for case review, not accepted evidence or a disease prediction.

## MMC / Potvin calculator

Place the calculator workbook here when running the notebook in Neurodesk:

```text
workflow_sources/external_validators/mmc1.xlsm
```

The legacy bridge reads workbook structure only. The new automated workflow above
uses the extracted numeric model without executing macros.

The intended use is:

1. Use the notebook's MMC bridge table to identify the subject covariates and observed FreeSurfer ROI values.
2. Enter age, sex, scanner field strength, scanner manufacturer, eTIV and observed values into `mmc1.xlsm`.
3. Export the returned predicted values, 95% prediction intervals, ZOP and percentiles to:

```text
workflow_sources/external_validators/mmc_outputs_manual_export.csv
```

The CSV should use these columns:

```text
mmc_sheet,mmc_region,hemisphere,observed_value,predicted_value,lower_95_prediction_interval,upper_95_prediction_interval,zop,percentile
```

This output supports typical-aging cross-validation. Disease interpretation remains in the reference-linked evidence workflow.
