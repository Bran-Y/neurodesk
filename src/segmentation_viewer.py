"""Source-bound original MRI, mask and label overlays for pre-report review."""
import base64
import hashlib
import html
import json
from pathlib import Path


def overlay_data(fs_root, subject_id):
    import nibabel as nib
    import numpy as np
    if Path(subject_id).name != subject_id:
        raise ValueError('Invalid subject ID')
    directory = Path(fs_root) / subject_id / 'mri'
    names = ('orig.mgz', 'brainmask.mgz', 'aseg.mgz')
    images = [nib.load(directory / name) for name in names]
    original = images[0]
    if len(original.shape) != 3:
        raise ValueError('Original MRI must be three-dimensional')
    for name, image in zip(names[1:], images[1:]):
        if image.shape != original.shape or not np.allclose(image.affine, original.affine, atol=1e-5):
            raise ValueError('Overlay geometry mismatch: ' + name)
    data = [np.asarray(image.dataobj) for image in images]
    if not all(np.isfinite(array).all() for array in data):
        raise ValueError('Nonfinite MRI or segmentation values')
    mask = data[1] > 0
    if not mask.any() or mask.all():
        raise ValueError('Brain mask is empty or covers the entire volume')
    if not np.equal(data[2], np.rint(data[2])).all() or not (data[2] > 0).any():
        raise ValueError('aseg labels must be nonempty integers')
    return original, data[0], mask, data[2], [directory / name for name in names]


def prepare_overlays(fs_root, subject_id, cache_dir):
    import nibabel as nib
    import numpy as np
    original, image, mask, labels, sources = overlay_data(fs_root, subject_id)
    fingerprint = hashlib.sha256()
    fingerprint.update(str(Path(fs_root).resolve()).encode())
    for path in sources:
        fingerprint.update(path.read_bytes())
    key = fingerprint.hexdigest()
    folder = Path(cache_dir) / subject_id / key[:20]
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, data in (('original', image), ('brain_mask', mask.astype(np.uint8)),
                       ('aseg_labels', labels.astype(np.int16))):
        path = folder / (name + '.nii.gz')
        if not path.exists():
            converted = nib.Nifti1Image(data, original.affine)
            converted.set_qform(original.affine, 1)
            converted.set_sform(original.affine, 1)
            nib.save(converted, path)
        paths.append(path)
    manifest = dict(subject_id=subject_id, original_source=str(sources[0]),
                    mask_source=str(sources[1]), mask_definition='brainmask.mgz > 0',
                    label_source=str(sources[2]), source_sha256=key,
                    overlay_opacity=0.6, geometry_verified=True)
    (folder / 'overlay_provenance.json').write_text(json.dumps(manifest, indent=2))
    return paths, manifest


def prepare_surface_overlays(fs_root, subject_id, folder):
    import nibabel as nib
    import numpy as np
    directory = Path(fs_root) / subject_id
    original = nib.load(directory / 'mri/orig.mgz')
    # FreeSurfer surfaces use tkregister RAS; NIfTI overlays use scanner RAS.
    transform = original.affine @ np.linalg.inv(original.header.get_vox2ras_tkr())
    paths = []
    for name in ('lh.white', 'rh.white', 'lh.pial', 'rh.pial'):
        source = directory / 'surf' / name
        points, faces = nib.freesurfer.read_geometry(source)
        if (not np.isfinite(points).all() or len(points) == 0 or len(faces) == 0 or
                faces.min() < 0 or faces.max() >= len(points)):
            raise ValueError('Invalid cortical surface: ' + name)
        vertices = nib.affines.apply_affine(transform, points).astype(np.float32)
        target = Path(folder) / (name + '.gii')
        gifti = nib.gifti.GiftiImage(darrays=[
            nib.gifti.GiftiDataArray(vertices, intent='NIFTI_INTENT_POINTSET'),
            nib.gifti.GiftiDataArray(faces.astype(np.int32), intent='NIFTI_INTENT_TRIANGLE')])
        nib.save(gifti, target)
        paths.append(target)
    return paths


def save_overlay_montage(fs_root, subject_id, cache_dir):
    """Several slices per plane; this records displayed evidence, not QC acceptance."""
    import nibabel as nib
    import numpy as np
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    paths, manifest = prepare_overlays(fs_root, subject_id, cache_dir)
    canonical = [nib.as_closest_canonical(nib.load(path)) for path in paths]
    image, mask, labels = [obj.get_fdata(dtype=np.float32) for obj in canonical]
    positions = np.argwhere(mask > 0)
    bounds = np.quantile(positions, (0.2, 0.5, 0.8), axis=0).astype(int)
    high = np.percentile(image[image > 0], 99)
    fig = Figure(figsize=(12, 10), dpi=110, facecolor='black')
    FigureCanvasAgg(fig)
    zooms = canonical[0].header.get_zooms()
    axes = fig.subplots(3, 3)
    for plane, (name, h, v) in enumerate((('Sagittal: A right, S up', 1, 2),
                                        ('Coronal: R right, S up', 0, 2),
                                        ('Axial: R right, A up', 0, 1))):
        for column, index in enumerate(bounds[:, plane]):
            section = np.take(image, index, axis=plane).T
            mask_section = np.take(mask, index, axis=plane).T > 0
            ax = axes[plane, column]
            ax.imshow(section, origin='lower', cmap='gray', vmin=0, vmax=high,
                      aspect=zooms[v] / zooms[h])
            colour = np.zeros((*section.shape, 4))
            colour[..., :3] = (0.1, 0.8, 0.4)
            colour[..., 3] = mask_section * 0.6
            ax.imshow(colour, origin='lower', aspect=zooms[v] / zooms[h])
            ax.set_title(f'{name} | slice {index}', color='white', fontsize=9)
            ax.axis('off')
    fig.suptitle(subject_id + ' | orig.mgz + brain mask | opacity 0.6', color='white')
    fig.tight_layout()
    target = paths[0].parent / 'brain_mask_overlay.png'
    fig.savefig(target, facecolor='black')
    fig.clear()
    manifest['montage_path'] = str(target)
    return target, manifest


def overlay_report_html(fs_root, subject_id, cache_dir):
    path, manifest = save_overlay_montage(fs_root, subject_id, cache_dir)
    return ('<h4>Original MRI with brain-mask overlay</h4><img style="max-width:100%" alt="' +
            html.escape(subject_id) + ' original MRI and mask, opacity 0.6" src="data:image/png;base64,' +
            base64.b64encode(path.read_bytes()).decode() + '"><p>' +
            html.escape(manifest['original_source']) + ' | mask: ' +
            html.escape(manifest['mask_definition']) +
            '. Multi-slice display is available for review; approval is recorded separately.</p>')


def surface_slice_segments(vertices, faces, plane, coordinate):
    """Intersect surface triangles with a voxel-space slice, not a thick point cloud."""
    import numpy as np
    triangles = vertices[faces]
    distance = triangles[:, :, plane] - coordinate
    crossing = (distance.min(axis=1) < 0) & (distance.max(axis=1) > 0)
    triangles, distance = triangles[crossing], distance[crossing]
    if not len(triangles):
        return np.empty((0, 2, 2))
    endpoints = np.zeros((len(triangles), 2, 3))
    counts = np.zeros(len(triangles), dtype=int)
    for first, second in ((0, 1), (1, 2), (2, 0)):
        selected = np.flatnonzero(distance[:, first] * distance[:, second] < 0)
        fraction = distance[selected, first] / (distance[selected, first] - distance[selected, second])
        points = triangles[selected, first] + fraction[:, None] * (triangles[selected, second] - triangles[selected, first])
        endpoints[selected, counts[selected]] = points
        counts[selected] += 1
    axes = [axis for axis in range(3) if axis != plane]
    return endpoints[counts == 2][:, :, axes]


def save_boundary_montages(fs_root, subject_id, cache_dir):
    """Source-bound 21-slice label and white/pial evidence; never a QC approval."""
    import nibabel as nib
    import numpy as np
    from matplotlib.figure import Figure
    from matplotlib.collections import LineCollection
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    paths, base_manifest = prepare_overlays(fs_root, subject_id, cache_dir)
    source = Path(fs_root) / subject_id
    surfaces = [source / 'surf' / name for name in ('lh.white', 'rh.white', 'lh.pial', 'rh.pial')]
    fingerprint = hashlib.sha256(base_manifest['source_sha256'].encode())
    for path in surfaces:
        fingerprint.update(path.read_bytes())
    key = fingerprint.hexdigest()
    directory = paths[0].parent / ('boundaries_' + key[:16])
    directory.mkdir(exist_ok=True)
    targets = {mode: directory / (mode + '_overlay.png') for mode in ('aseg', 'surfaces')}
    manifest_path = directory / 'boundary_provenance.json'
    if all(path.exists() for path in targets.values()) and manifest_path.exists():
        return targets, json.loads(manifest_path.read_text())
    original = nib.load(source / 'mri/orig.mgz')
    canonical = [nib.as_closest_canonical(nib.load(path)) for path in paths]
    image, mask, labels = [obj.get_fdata(dtype=np.float32) for obj in canonical]
    transform = np.linalg.inv(canonical[0].affine) @ original.affine @ np.linalg.inv(original.header.get_vox2ras_tkr())
    meshes = []
    for path in surfaces:
        vertices, faces = nib.freesurfer.read_geometry(path)
        if not np.isfinite(vertices).all() or not len(faces) or faces.min() < 0 or faces.max() >= len(vertices):
            raise ValueError('Invalid surface: ' + path.name)
        meshes.append((nib.affines.apply_affine(transform, vertices), faces, 'yellow' if path.suffix == '.white' else '#ff5252'))
    positions = np.argwhere(mask > 0)
    bounds = np.quantile(positions, np.linspace(0.08, 0.92, 7), axis=0).astype(int)
    high = np.percentile(image[image > 0], 99)
    # Bilateral native aseg structures use the same named colour.
    palette = {10: '#c68aff', 49: '#c68aff', 11: '#66baff', 50: '#66baff',
               12: '#ffbf55', 51: '#ffbf55', 13: '#ff729f', 52: '#ff729f',
               17: '#68e66a', 53: '#68e66a', 18: '#ff5555', 54: '#ff5555',
               26: '#f4ff63', 58: '#f4ff63', 4: '#40dddf', 43: '#40dddf',
               5: '#40dddf', 44: '#40dddf', 14: '#40dddf', 15: '#40dddf'}
    from matplotlib.colors import to_rgba
    for mode, target in targets.items():
        fig = Figure(figsize=(21, 10), dpi=130, facecolor='black')
        FigureCanvasAgg(fig)
        axes = fig.subplots(3, 7)
        for plane, name in enumerate(('Sagittal A right S up', 'Coronal R right S up', 'Axial R right A up')):
            for column, index in enumerate(bounds[:, plane]):
                ax = axes[plane, column]
                ax.imshow(np.take(image, index, axis=plane).T, origin='lower', cmap='gray', vmin=0, vmax=high)
                if mode == 'aseg':
                    section = np.take(labels, index, axis=plane).T
                    colour = np.zeros((*section.shape, 4))
                    for code, value in palette.items():
                        colour[section == code] = to_rgba(value, 0.55)
                    ax.imshow(colour, origin='lower')
                else:
                    for vertices, faces, colour in meshes:
                        segments = surface_slice_segments(vertices, faces, plane, float(index) + 0.01)
                        ax.add_collection(LineCollection(segments, colors=colour, linewidths=0.5))
                ax.set_xlim(0, image.shape[[axis for axis in range(3) if axis != plane][0]])
                ax.set_ylim(0, image.shape[[axis for axis in range(3) if axis != plane][1]])
                ax.set_title(f'{name} | {index}', color='white', fontsize=8)
                ax.axis('off')
        legend = ('White boundary yellow; pial boundary red' if mode == 'surfaces' else
                  'Thalamus purple; caudate blue; putamen orange; pallidum pink; hippocampus green; amygdala red; accumbens yellow; ventricles cyan')
        fig.suptitle(subject_id + ' | ' + legend, color='white', fontsize=11)
        fig.tight_layout(rect=(0, 0, 1, 0.95))
        fig.savefig(target, facecolor='black')
        fig.clear()
    manifest = dict(subject_id=subject_id, source_sha256=key, source_root=str(source),
        slices_per_plane=bounds.T.tolist(), image_orientation='Canonical RAS',
        surface_transform='inverse(canonical_affine) @ orig_affine @ inverse(vox2ras_tkr)',
        surface_intersection='Triangle-plane intersection at index+0.01 voxels',
        scope='21 slices per modality, sampled review; not exhaustive human QC',
        human_qc_accepted=False, images={key: str(path) for key, path in targets.items()})
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return targets, manifest


def boundary_report_html(fs_root, subject_id, cache_dir):
    paths, manifest = save_boundary_montages(fs_root, subject_id, cache_dir)
    body = ['<details><summary>Multi-slice cortical boundary and subcortical-label checks</summary>',
            '<p>21 sampled slices per modality. Yellow: white boundary; red: pial boundary. '
            'Native aseg label colours are identified in the image legend. This display does not record human approval.</p>']
    for mode, path in paths.items():
        body.append('<h5>' + html.escape(mode) + '</h5><img style="max-width:100%" src="data:image/png;base64,' +
                    base64.b64encode(path.read_bytes()).decode() + '">')
    body.append('</details>')
    return ''.join(body)


class SegmentationViewer:
    def __init__(self, result):
        import ipywidgets as w
        self.result = result
        self.viewer = None
        self.subject_id = None
        self.status = w.HTML()
        self.mode = w.Dropdown(description='Overlay:', options=[
            ('Brain mask (opacity 0.6)', 'mask'), ('Subcortical labels', 'aseg'),
            ('Cortical white/pial surfaces', 'surfaces'), ('Original MRI only', 'original')])
        self.box = w.VBox([self.mode, self.status])
        self.mode.observe(self.change_mode, names='value')

    def change_mode(self, change):
        if self.subject_id:
            self.show(self.subject_id)

    def show(self, subject_id):
        self.subject_id = subject_id
        if self.viewer is not None:
            self.viewer.close()
            self.viewer = None
        self.box.children = (self.mode, self.status)
        try:
            from ipyniivue import NiiVue
            paths, manifest = prepare_overlays(self.result['fs_root'], subject_id,
                Path(self.result['project_dir']) / 'outputs/segmentation_overlay_cache')
            self.viewer = NiiVue(height=480)
            volumes = [{'path': str(paths[0])}]
            if self.mode.value == 'mask':
                volumes.append({'path': str(paths[1]), 'colormap': 'green',
                                'opacity': 0.6, 'cal_min': 0, 'cal_max': 1})
            elif self.mode.value == 'aseg':
                volumes.append({'path': str(paths[2]), 'colormap': 'freesurfer', 'opacity': 0.6})
            self.viewer.load_volumes(volumes)
            if self.mode.value == 'surfaces':
                meshes = prepare_surface_overlays(self.result['fs_root'], subject_id, paths[0].parent)
                self.viewer.load_meshes([{'path': str(path)} for path in meshes])
            self.status.value = ('<p><b>' + html.escape(subject_id) + '</b> | ' + html.escape(self.mode.label) +
                ' | Original: ' + html.escape(manifest['original_source']) + '</p>')
            self.box.children = (self.mode, self.status, self.viewer)
        except Exception as exc:
            self.status.value = '<p>QC overlay unavailable: ' + html.escape(str(exc)) + '</p>'

    def close(self):
        self.mode.unobserve(self.change_mode, names='value')
        if self.viewer is not None:
            self.viewer.close()
        self.box.close()
