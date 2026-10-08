"""Install the selected PD update, preserving previous files in a dated backup."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / '00_START_HERE.ipynb').is_file() or not (root / 'user_pipeline.py').is_file():
        raise ValueError('Target must be the existing user workflow folder')
    with zipfile.ZipFile(args.archive) as archive:
        manifest = json.loads(archive.read('UPDATE_MANIFEST.json'))
        files = manifest['files']
        if set(archive.namelist()) != set(files) | {'UPDATE_MANIFEST.json'}:
            raise ValueError('Unexpected archive contents')
        contents = {}
        for name, digest in files.items():
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or '.env' in path.parts:
                raise ValueError('Unsafe archive path')
            target = root / name
            if not target.resolve().is_relative_to(root) or target.is_symlink():
                raise ValueError('Unsafe target')
            data = archive.read(name)
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError('File checksum mismatch: ' + name)
            contents[name] = data
    backup = root / 'maintenance' / ('before_pd_supplement_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True)
    for name in contents:
        target = root / name
        if target.exists():
            prior = backup / name
            prior.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, prior)
    for name, data in contents.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.pd-update-tmp')
        with temporary.open('xb') as stream:
            stream.write(data)
        temporary.replace(target)
    print(json.dumps(dict(installed=len(contents), backup=str(backup)), indent=2))


if __name__ == '__main__':
    main()
