"""Portable project manifests; never recapture neutral positions."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from . import core

SCHEMA = 'facialSystemProject'
PROJECT_FILE = 'facialSystemProject.json'


def write_json(path, value):
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=str(path.parent), suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, indent=2, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return str(path)


def data_fingerprint(document, mapping, install_mesh=True):
    """Identify the settings/report pair; this is not a live geometry check."""
    core.validate(document)
    payload = {'document': document, 'mapping': dict(mapping), 'install_mesh': bool(install_mesh)}
    # Saving the same capture changes timestamps, not its fitting meaning.
    payload['document'] = {k: v for k, v in document.items() if k not in ('created_utc', 'updated_utc')}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode('utf-8')).hexdigest()


def save(folder, document, mapping, scene='', install_mesh=True,
         fit_result=None, behavior_report=None, fit_check=None, current_step=0,
         current_step_id=None, wrap_data=None, landmark_data=None):
    core.validate(document)
    if not isinstance(mapping, dict) or set(mapping) - set(document['meshes']):
        raise ValueError('Project target mapping contains unknown source meshes')
    if not all(isinstance(value, str) for value in mapping.values()):
        raise ValueError('Project target mesh names must be strings')
    if landmark_data is not None:
        from . import cage_landmarks
        cage_landmarks.validate(landmark_data)
    root = Path(folder).expanduser().resolve()
    if root.is_file():
        raise ValueError('Choose a project folder, not a file')
    for name in ('data', 'scenes', 'reports'):
        (root / name).mkdir(parents=True, exist_ok=True)
    neutral_path = root / 'data' / 'driveNeutralData.json'
    core.save(document, neutral_path)
    refs = {}
    for key, filename, report in (
            ('fit_result', 'driveNeutralFitResult.json', fit_result),
            ('behavior_report', 'rigBehaviorCheck.json', behavior_report),
            ('fit_check', 'fitGeometryCheck.json', fit_check)):
        if report is not None:
            rel = 'reports/' + filename
            write_json(root / rel, report)
            refs[key] = rel
    scene_ref = ''
    if scene:
        actual = Path(scene).expanduser().resolve()
        try:
            scene_ref = actual.relative_to(root).as_posix()
        except ValueError:
            scene_ref = str(actual)
    manifest = {'schema': SCHEMA, 'version': 1, 'saved_utc': core.utc_now(),
                'neutral_data': 'data/driveNeutralData.json', 'scene': scene_ref,
                'target_mapping': dict(mapping), 'install_mesh': bool(install_mesh),
                'current_step': max(0, min(3, int(current_step))), 'reports': refs,
                'data_fingerprint': data_fingerprint(document, mapping, install_mesh)}
    if current_step_id is not None:
        if current_step_id not in ('setup', 'groups', 'wrap', 'fit', 'check'):
            raise ValueError('Unknown workflow step')
        manifest['current_step_id'] = current_step_id
    if wrap_data is not None:
        from . import cage_core
        cage_core.validate(wrap_data)
        write_json(root / 'data/wrapFitData.json', wrap_data)
        manifest['wrap_data'] = 'data/wrapFitData.json'
    if landmark_data is not None:
        write_json(root / 'data/cageLandmarks.json', landmark_data)
        manifest['landmark_data'] = 'data/cageLandmarks.json'
    write_json(root / PROJECT_FILE, manifest)
    return str(root / PROJECT_FILE)


def load(path):
    path = Path(path).expanduser().resolve()
    if path.is_dir():
        path = path / PROJECT_FILE
    with path.open(encoding='utf-8') as handle:
        manifest = json.load(handle)
    if manifest.get('schema') != SCHEMA or manifest.get('version') != 1:
        raise ValueError('Expected a Facial System project manifest')
    root = path.parent
    def resolved(reference):
        if not isinstance(reference, str) or not reference:
            raise ValueError('Project file reference is missing')
        candidate = Path(reference)
        return candidate if candidate.is_absolute() else root / candidate
    document_path = resolved(manifest['neutral_data'])
    document = core.load(document_path)
    mapping = manifest.get('target_mapping', {})
    if not isinstance(mapping, dict) or set(mapping) - set(document['meshes']):
        raise ValueError('Project target mapping contains unknown source meshes')
    if not all(isinstance(value, str) for value in mapping.values()):
        raise ValueError('Project target names must be strings')
    reports = {}
    for key, ref in manifest.get('reports', {}).items():
        target = resolved(ref)
        if target.is_file():
            with target.open(encoding='utf-8') as handle:
                reports[key] = json.load(handle)
    scene = manifest.get('scene', '')
    reports_match_data = manifest.get('data_fingerprint') == data_fingerprint(
        document, mapping, manifest.get('install_mesh', True))
    if not reports_match_data:
        reports = {}
    wrap_data = None
    if manifest.get('wrap_data'):
        from . import cage_core
        with resolved(manifest['wrap_data']).open(encoding='utf-8') as handle:
            wrap_data = cage_core.validate(json.load(handle))
    landmark_data = None
    if manifest.get('landmark_data'):
        from . import cage_landmarks
        with resolved(manifest['landmark_data']).open(encoding='utf-8') as handle:
            landmark_data = cage_landmarks.validate(json.load(handle))
    return {'manifest': manifest, 'document': document, 'mapping': dict(mapping),
            'neutral_path': str(document_path), 'root': str(root),
            'scene': str(resolved(scene)) if scene else '', 'reports': reports,
            'reports_match_data': reports_match_data, 'wrap_data': wrap_data,
            'landmark_data': landmark_data}
