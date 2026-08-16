#!/usr/bin/env bash
set -e
ml freesurfer/8.2.0
mkdir -p /home/jovyan/converted_nifti /home/jovyan/derivatives/freesurfer /home/jovyan/outputs /home/jovyan/logs
mri_convert /home/jovyan/neurodesk/disc1/OAS1_0001_MR1/RAW/OAS1_0001_MR1_mpr-1_anon.hdr /home/jovyan/converted_nifti/OAS1_0001_MR1_T1w.nii.gz
mri_convert /home/jovyan/neurodesk/disc1/OAS1_0003_MR1/RAW/OAS1_0003_MR1_mpr-1_anon.hdr /home/jovyan/converted_nifti/OAS1_0003_MR1_T1w.nii.gz
nohup recon-all -sd /home/jovyan/derivatives/freesurfer -i /home/jovyan/converted_nifti/OAS1_0001_MR1_T1w.nii.gz -s OAS1_0001_MR1 -all > /home/jovyan/logs/OAS1_0001_MR1_recon.log 2>&1 &
nohup recon-all -sd /home/jovyan/derivatives/freesurfer -i /home/jovyan/converted_nifti/OAS1_0003_MR1_T1w.nii.gz -s OAS1_0003_MR1 -all > /home/jovyan/logs/OAS1_0003_MR1_recon.log 2>&1 &
printf 'launched
' > /home/jovyan/neurodesk/freesurfer_launch_status.txt
