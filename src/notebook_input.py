"""Notebook input form; research inputs are validated before configuration is saved."""
from pathlib import Path
import json
import math
import re
import tempfile
import shutil
import pandas as pd

MAX_UPLOAD_BYTES = 256 * 1024 * 1024


def validate_image(path):
    import nibabel as nib
    import numpy as np
    path = Path(path)
    if not path.is_file() or not str(path).lower().endswith(('.nii', '.nii.gz')):
        raise ValueError('Select an existing .nii or .nii.gz file')
    img = nib.load(path)
    if len(img.shape) != 3 or min(img.shape) <= 1:
        raise ValueError('Expected a 3D structural MRI')
    if not np.isfinite(img.affine).all() or abs(np.linalg.det(img.affine[:3,:3])) < 1e-12:
        raise ValueError('Invalid image affine')
    if not all(math.isfinite(float(v)) and v > 0 for v in img.header.get_zooms()[:3]):
        raise ValueError('Invalid voxel dimensions')
    # Check decompressed size before reading voxel data (compressed input can be tiny).
    if math.prod(img.shape) * max(img.get_data_dtype().itemsize, 8) > 512 * 1024 * 1024:
        raise ValueError('Image exceeds notebook validation memory limit')
    if not np.isfinite(np.asanyarray(img.dataobj)).all():
        raise ValueError('Image contains nonfinite voxels')
    return path.resolve()


def save_case(root, values, upload=None):
    from user_pipeline import completed
    root = Path(root).resolve()
    sid = values['subject_id'].strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', sid):
        raise ValueError('Use an anonymous ID: letters, numbers, underscore or hyphen')
    modality = values.get('modality', 'T1')
    if modality not in ('T1', 'T2'):
        raise ValueError('Unsupported modality')
    age = float(values['age']) if str(values.get('age', '')).strip() else None
    strength = float(values['scanner_field_strength']) if str(values.get('scanner_field_strength', '')).strip() else None
    if (age is not None and (not math.isfinite(age) or not 0 < age <= 120)) or (strength is not None and (not math.isfinite(strength) or strength <= 0)):
        raise ValueError('Enter valid age and field strength; do not guess missing information')
    if modality == 'T1' and (age is None or strength is None or values['sex'] not in ('Male','Female') or values['scanner_manufacturer'] not in ('Siemens','GE','Philips')):
        raise ValueError('Select sex and manufacturer supported by the reference model')
    if values['mode'] not in ('new','existing'):
        raise ValueError('Unknown input mode')
    if modality == 'T2' and values['mode'] != 'new':
        raise ValueError('T2 requires a new image, not an existing FS5.3 result')
    case = root/'cases'/sid
    if case.exists():
        raise FileExistsError('A saved configuration already exists for this ID. Use its config path, or a new ID.')
    subject_root = root/'subjects_fs53'
    source = None
    temporary = None
    try:
        if values['mode'] == 'existing':
            subject = Path(values['subject_path']).expanduser().resolve()
            if subject.name != sid:
                raise ValueError('Subject ID must match the existing subject folder name')
            ok, detail = completed(subject)
            if not ok:
                raise ValueError(detail)
            subject_root = subject.parent
        else:
            if not values.get('modality_confirmed', values.get('t1_confirmed') if modality == 'T1' else False):
                raise ValueError('Confirm selected modality and de-identification first')
            if (subject_root/sid).exists():
                raise FileExistsError('Processing results already exist for this ID')
            if upload and values.get('image_path','').strip():
                raise ValueError('Choose either upload or server path, not both')
            if upload:
                name, content = upload
                if len(content) > MAX_UPLOAD_BYTES:
                    raise ValueError('Upload limit is 256 MiB; use a server path instead')
                suffix = '.nii.gz' if name.lower().endswith('.nii.gz') else '.nii' if name.lower().endswith('.nii') else None
                if suffix is None:
                    raise ValueError('Only NIfTI .nii or .nii.gz is accepted')
                temporary = tempfile.TemporaryDirectory()
                source = Path(temporary.name)/(modality+'w'+suffix)
                source.write_bytes(content)
            else:
                source = Path(values.get('image_path','')).expanduser()
                if not source.is_absolute():
                    source = root/source
            source = validate_image(source)
        case.parent.mkdir(parents=True, exist_ok=True)
        case.mkdir(exist_ok=False)
        try:
            if upload and source:
                target = case/source.name
                shutil.copyfile(source, target)
                source = target
            row = dict(subject_id=sid, age=age, sex=values['sex'], scanner_field_strength=strength,
                       scanner_manufacturer=values['scanner_manufacturer'],
                       modality=modality, image_path=str(source or ''),
                       modality_confirmed=values['mode']=='new',
                       t1_path=str(source or '') if modality == 'T1' else '',
                       t1_confirmed=values['mode']=='new' and modality == 'T1',
                       segmentation_qc_status='pending_visual_review')
            pd.DataFrame([row]).to_csv(case/'participants.csv',index=False)
            config = dict(subjects_dir=str(subject_root), metadata_csv='participants.csv',
                          output_dir=str(root/'outputs'/sid), input_mode=values['mode'], modality=modality)
            (case/'config.json').write_text(json.dumps(config,indent=2))
        except Exception:
            shutil.rmtree(case)  # Only this newly reserved case directory is rolled back.
            raise
        return case/'config.json'
    finally:
        if temporary:
            temporary.cleanup()


def input_form(root, on_saved, on_changed):
    import ipywidgets as w
    from IPython.display import clear_output
    mode = w.Dropdown(options=[('Upload / select MRI','new'),('Existing FS5.3 result','existing')],description='Input:')
    modality = w.Dropdown(options=['T1','T2'],description='Modality:')
    scope = w.HTML()
    sid = w.Text(description='Subject ID:')
    age = w.Text(description='Age:')
    sex = w.Dropdown(options=[('Select...',None),('Male','Male'),('Female','Female')],description='Sex:')
    strength = w.Text(description='Field (T):')
    maker = w.Dropdown(options=[('Select...',None),('Siemens','Siemens'),('GE','GE'),('Philips','Philips')],description='Scanner:')
    upload = w.FileUpload(accept='.nii,.nii.gz',multiple=False,description='Upload T1')
    path = w.Text(description='T1 path:',placeholder='Alternative server path for large files',layout=w.Layout(width='95%'))
    existing = w.Text(description='FS folder:',placeholder='/path/to/subjects/SUBJECT_ID',layout=w.Layout(width='95%'))
    confirm = w.Checkbox(description='I confirm this is de-identified T1-weighted MRI',value=False)
    save = w.Button(description='Validate & use case',button_style='primary')
    message = w.Output()
    new_box = w.VBox([upload,path,confirm])
    def changed(change):
        modality.disabled = mode.value == 'existing'
        if mode.value == 'existing' and modality.value != 'T1':
            modality.value = 'T1'
        upload.description = 'Upload ' + modality.value
        path.description = modality.value + ' path:'
        confirm.description = 'I confirm this is de-identified ' + modality.value + '-weighted MRI'
        scope.value = ('<p>T2: SynthStrip + SynthSeg, descriptive volumes and QC only. '
                       'No Potvin ranges, cortical thickness or disease prediction. Metadata may be left unknown.</p>'
                       if modality.value == 'T2' else '<p>T1: FS5.3 structural processing and reference comparison.</p>')
        if change.get('owner') in (mode, modality) and confirm.value:
            confirm.value = False
        new_box.layout.display = '' if mode.value=='new' else 'none'
        existing.layout.display = '' if mode.value=='existing' else 'none'
        on_changed()
    for item in (mode,modality,sid,age,sex,strength,maker,upload,path,existing,confirm):
        item.observe(changed,names='value')
    existing.layout.display='none'
    def persist(_):
        with message:
            clear_output(wait=True)
            save.disabled=True
            try:
                payload=None
                if mode.value=='new' and upload.value:
                    if isinstance(upload.value,dict):
                        name,item=next(iter(upload.value.items()))
                    else:
                        item=upload.value[0]
                        name=item['name']
                    payload=(name,item['content'])
                config=save_case(root,dict(mode=mode.value,subject_id=sid.value,age=age.value,
                    sex=sex.value,scanner_field_strength=strength.value,scanner_manufacturer=maker.value,
                    image_path=path.value,subject_path=existing.value,modality=modality.value,
                    modality_confirmed=confirm.value,t1_confirmed=confirm.value),payload)
                # Remove binary payload from widget state before the notebook is saved.
                upload.value={} if isinstance(upload.value,dict) else ()
                on_saved(str(config))
                print('Validated and saved:',config)
                print('Use Check status, then Start processing for NEW images only; Generate reports for completed results.')
            except Exception as exc:
                print(type(exc).__name__+': '+str(exc))
            finally:
                save.disabled=False
    save.on_click(persist)
    return w.VBox([w.HTML('<h3>Patient input</h3><p>Research use only. Upload limit: 256 MiB. For larger files use the Jupyter file browser and enter their server path. Modality and segmentation quality still require review.</p>'),
        mode,modality,scope,sid,age,sex,strength,maker,new_box,existing,save,message])
