"""Local T1 display for the selected research subject; no external image URLs."""
from pathlib import Path
import hashlib
import json


def prepare_subject_t1(subject_id, fs_root, cache_dir):
    return prepare_subject_image(subject_id, fs_root, cache_dir, 'T1.mgz')


def prepare_subject_image(subject_id, fs_root, cache_dir, image_name='brain.mgz'):
    import nibabel as nib
    import numpy as np
    if Path(subject_id).name != subject_id:
        raise ValueError('Invalid subject ID')
    if Path(image_name).name != image_name:
        raise ValueError('Invalid image name')
    source = Path(fs_root) / subject_id / 'mri' / image_name
    if not source.is_file():
        raise FileNotFoundError(f'Requested image unavailable for {subject_id}: {source}')
    root_key = hashlib.sha256(str(Path(fs_root).resolve()).encode()).hexdigest()[:12]
    target = Path(cache_dir) / root_key / f'{subject_id}_{Path(image_name).stem}.nii.gz'
    target.parent.mkdir(parents=True, exist_ok=True)
    metadata = target.with_suffix('.json')
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    old = json.loads(metadata.read_text()) if metadata.exists() else {}
    if not target.exists() or old.get('source_sha256') != source_hash:
        original = nib.load(source)
        # Preserve the voxel-to-world transform; the data are FreeSurfer conformed T1.
        image = nib.Nifti1Image(np.asarray(original.dataobj, dtype=np.float32), original.affine)
        image.set_qform(original.affine, code=1)
        image.set_sform(original.affine, code=1)
        nib.save(image, target)
        check = nib.load(target)
        if check.shape != original.shape or not np.allclose(check.affine, original.affine):
            raise ValueError('T1 conversion changed geometry')
        if not np.array_equal(np.asarray(check.dataobj), np.asarray(original.dataobj)):
            raise ValueError('T1 conversion changed voxel values')
        metadata.write_text(json.dumps(dict(subject_id=subject_id, source_path=str(source),
            source_sha256=source_hash, display_path=str(target), shape=list(check.shape),
            affine=check.affine.tolist(), image_kind=image_name), indent=2))
    return target


class SliceMRIViewer:
    """Kernel-rendered slices using standard widgets, without WebGL or custom JS."""

    def __init__(self, path):
        import ipywidgets as w
        import nibabel as nib
        import numpy as np
        self.image = nib.as_closest_canonical(nib.load(path))
        self.data = self.image.get_fdata(dtype=np.float32)
        if self.data.ndim != 3 or min(self.data.shape) < 2 or not np.isfinite(self.data).all():
            raise ValueError('MRI must be finite and three-dimensional')
        positions = np.argwhere(self.data != 0)
        if not len(positions):
            raise ValueError('MRI has no nonzero voxels')
        center = np.median(positions, axis=0).astype(int)
        low, maximum = float(self.data.min()), float(self.data.max())
        if maximum <= low:
            raise ValueError('MRI has no intensity range')
        high = float(np.percentile(self.data[self.data != 0], 99))
        high = maximum if high <= low else high
        self.closed = False
        self.sliders = [w.IntSlider(value=int(center[i]), min=0, max=self.data.shape[i]-1,
            description=name, continuous_update=False, layout=w.Layout(width='100%'))
            for i, name in enumerate(('Sagittal', 'Coronal', 'Axial'))]
        self.window = w.FloatRangeSlider(value=(low, high), min=low, max=maximum,
            step=(maximum-low)/500, description='Intensity', continuous_update=False,
            layout=w.Layout(width='100%'))
        self.picture = w.Image(format='png', layout=w.Layout(width='100%'))
        self.notice = w.HTML()
        self.box = w.VBox([self.picture, *self.sliders, self.window, self.notice],
                         layout=w.Layout(width='100%'))
        for control in [*self.sliders, self.window]:
            control.observe(self.render, names='value')
        self.render()

    def render(self, change=None):
        if self.closed:
            return
        import io
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        low, high = self.window.value
        if high <= low:
            self.notice.value = '<p>Select an intensity upper limit greater than the lower limit.</p>'
            return
        x, y, z = (slider.value for slider in self.sliders)
        sections = (self.data[x, :, :], self.data[:, y, :], self.data[:, :, z])
        zooms = self.image.header.get_zooms()
        fig = Figure(figsize=(12, 4.5), dpi=100, facecolor='black')
        FigureCanvasAgg(fig)
        for ax, section, label, index, (h, v) in zip(fig.subplots(1, 3), sections,
                ('Sagittal: A right, S up', 'Coronal: R right, S up', 'Axial: R right, A up'),
                (x, y, z), ((1, 2), (0, 2), (0, 1))):
            ax.imshow(section.T, origin='lower', cmap='gray', vmin=low, vmax=high,
                      aspect=zooms[v]/zooms[h])
            ax.set_title(f'{label}\nSlice {index}', color='white', fontsize=11)
            ax.axis('off')
        fig.tight_layout()
        buffer = io.BytesIO()
        fig.savefig(buffer, format='png', facecolor='black')
        self.picture.value = buffer.getvalue()
        fig.clear()
        self.notice.value = '<p>Drag a slice slider and release to update. Indices are zero-based; orientation is labelled above each view. A live kernel is required.</p>'

    def close(self):
        if self.closed:
            return
        self.closed = True
        for control in [*self.sliders, self.window]:
            control.unobserve(self.render, names='value')
            control.close()
        self.picture.close()
        self.notice.close()
        self.box.close()
        self.data = None


class SubjectMRIViewer:
    def __init__(self, fs_root, cache_dir, image_name='brain.mgz'):
        import ipywidgets as widgets
        self.fs_root, self.cache_dir = fs_root, cache_dir
        self.image_name = image_name
        self.status = widgets.HTML()
        self.box = widgets.VBox([self.status])
        self.viewer = None
        self.subject_id = None

    def show(self, subject_id):
        import html
        self.box.layout.display = ''
        if self.subject_id == subject_id and self.viewer is not None:
            return
        # Remove previous-subject image before attempting a new load.
        self.box.children = (self.status,)
        self.subject_id = None
        if self.viewer is not None:
            self.viewer.close()
            self.viewer = None
        self.status.value = '<p>Loading MRI for ' + html.escape(subject_id) + '...</p>'
        try:
            from ipyniivue import NiiVue
            path = prepare_subject_image(subject_id, self.fs_root, self.cache_dir, self.image_name)
            self.viewer = NiiVue(height=480)
            self.viewer.load_volumes([{'path': str(path)}])
            self.box.children = (self.status, self.viewer)
            self.subject_id = subject_id
            self.status.value = '<p><b>' + html.escape(subject_id) + '</b> | ' + html.escape(self.image_name) + '. Scroll to inspect slices. Image source: ' + html.escape(str(Path(self.fs_root) / subject_id / 'mri' / self.image_name)) + '</p>'
        except Exception as exc:
            if self.viewer is not None:
                self.viewer.close()
                self.viewer = None
            self.box.children = (self.status,)
            self.status.value = '<p>MRI display unavailable for ' + html.escape(subject_id) + ': ' + html.escape(str(exc)) + '</p>'

    def hide(self):
        self.box.layout.display = 'none'


def skull_stripped_report_html(subject_id, fs_root, cache_dir):
    """Embed orthogonal slices for offline reports; never fall back to full-head T1."""
    import base64
    import html
    import io
    import nibabel as nib
    import numpy as np
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    path = prepare_subject_image(subject_id, fs_root, cache_dir, 'brain.mgz')
    image = nib.as_closest_canonical(nib.load(path))
    data = image.get_fdata()
    if data.ndim != 3 or not np.isfinite(data).all():
        raise ValueError('MRI must be finite and three-dimensional')
    positions = np.argwhere(data != 0)
    if not len(positions):
        raise ValueError('MRI has no nonzero voxels')
    center = np.median(positions, axis=0).astype(int)
    high = float(np.percentile(data[data > 0], 99))
    fig = Figure(figsize=(9, 3), dpi=110)
    FigureCanvasAgg(fig)
    slices = [data[center[0], :, :], data[:, center[1], :], data[:, :, center[2]]]
    axes = [(1, 2), (0, 2), (0, 1)]
    zooms = image.header.get_zooms()
    for ax, section, title, (horizontal, vertical) in zip(fig.subplots(1, 3), slices,
                          ('Sagittal (A right, S up)', 'Coronal (R right, S up)', 'Axial (R right, A up)'), axes):
        ax.imshow(section.T, origin='lower', cmap='gray', vmin=0, vmax=high,
                  aspect=zooms[vertical] / zooms[horizontal])
        ax.set_title(title, fontsize=9)
        ax.axis('off')
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format='png')
    source = Path(fs_root) / subject_id / 'mri' / 'brain.mgz'
    stamp = Path(fs_root) / subject_id / 'scripts' / 'build-stamp.txt'
    version = stamp.read_text().strip() if stamp.exists() else 'Version not recorded'
    return ('<h4>Skull-stripped MRI</h4><img style="max-width:100%" alt="' + html.escape(subject_id) +
            ' orthogonal brain slices" src="data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode() +
            '"><p>' + html.escape(str(source)) + ' | ' + html.escape(version) + '</p>')
