# T2 research branch

Select Upload / select MRI, then Modality T2 in 00_START_HERE.ipynb.
Provide an anonymous subject ID and a de-identified 3D NIfTI volume (.nii/.nii.gz).
Age, sex and scanner information may remain unknown for this descriptive branch.
Confirm the declared sequence, Validate & use case, authorise processing, then Start processing.
Check status before Generate reports. Existing case IDs are never overwritten.

The server runs SynthStrip and SynthSeg-robust using freesurfer/8.2.0 in a detached
CPU process. SynthSeg reads the original image, not the skull-stripped derivative.
The existing T1/FS5.3 reconstruction queue is independent and is not restarted.

Outputs: outputs/CASE/t2_synthseg/CASE/
- brain.nii.gz and brain_mask.nii.gz: native-grid extraction and binary mask.
- segmentation.nii.gz and resampled.nii.gz: aligned SynthSeg label/display volumes.
- volumes.csv: tool-reported soft-segmentation volumes, not voxel-count volumes.
- qc.csv: automatic scores, not manual QC approval.
- status.json: input/output hashes, exact commands and processing status.
- processing.log: software build and tool logs.
- report.html: skull-stripped preview, descriptive measurements and limitations.

This is not T2 lesion segmentation, cortical thickness measurement, or diagnosis.
No FS5.3/Potvin model or Zheng AD/Control distribution is applied to SynthSeg outputs.
Unknown modalities fail closed. NIfTI geometry checks cannot prove the sequence type.
Do not manufacture covariates to satisfy a model. Real supplied T2 scans still need
end-to-end execution and visual segmentation QC before scientific interpretation.

Tests use synthetic outputs and mocked tool execution to validate routing,
error handling, geometry checks, integrity protection and report generation.
They do not establish model accuracy on patient T2 scans.

Sources:
- https://surfer.nmr.mgh.harvard.edu/docs/synthstrip/
- https://surfer.nmr.mgh.harvard.edu/fswiki/SynthSeg
