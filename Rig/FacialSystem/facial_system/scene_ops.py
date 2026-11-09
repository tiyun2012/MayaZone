"""Scene setup actions; only stock undoable Maya commands perform edits."""
from pathlib import Path

import maya.cmds as cmds

from . import core, scene_adapter as adapter

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / 'templates' / 'facialRig_native_v1.ma'


def scope_document(document=None):
    if document and document.get('joints'):
        return document
    meshes = adapter.skin_meshes()
    joints, _ = adapter.discover_joints(meshes, 'auto')
    return {'joints': [{'joint': adapter.identity(adapter.dag_path(name))} for name in joints]}


def inspect():
    buses = [name for name in (cmds.ls(type='network') or [])
             if name.rsplit(':', 1)[-1] == 'NFRv1_RAW']
    return {'scene': cmds.file(query=True, sceneName=True),
            'modified': bool(cmds.file(query=True, modified=True)),
            'native_buses': buses, 'native_graph_present': len(buses) == 1,
            'joint_count': len(cmds.ls(type='joint') or []),
            'skin_cluster_count': len(cmds.ls(type='skinCluster') or []),
            'skinned_meshes': adapter.skin_meshes(),
            'template_available': TEMPLATE.is_file()}


def check_neutral(document=None):
    from . import fit
    scope = scope_document(document)
    bus = fit.check_neutral(scope)
    return {'passed': True, 'bus': bus, 'message': 'Facial and neck/head inputs are neutral.'}


def save_scene(path, overwrite=False):
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() != '.ma':
        path = path.with_suffix('.ma')
    if path == TEMPLATE.resolve():
        raise ValueError('Save a character copy outside the bundled template')
    if path.exists() and not overwrite:
        raise ValueError('Scene already exists; choose a new name')
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = cmds.file(query=True, sceneName=True)
    try:
        cmds.file(rename=str(path))
        cmds.file(save=True, type='mayaAscii', force=bool(overwrite))
    except Exception:
        if previous:
            cmds.file(rename=previous)
        raise
    return str(path)


def open_template(discard_current=False):
    if not TEMPLATE.is_file():
        raise ValueError('Bundled template was not found; extract the complete FacialSystem folder')
    if cmds.file(query=True, modified=True) and not discard_current:
        raise ValueError('Save the current scene before opening the bundled template')
    return cmds.file(str(TEMPLATE), open=True, force=bool(discard_current), executeScriptNodes=False)


def create_fit_target(name='Head_FitTarget'):
    """Duplicate one selected visible mesh into an independent world-space copy."""
    from . import cage
    selected = adapter.selected_meshes()
    if len(selected) != 1:
        raise ValueError('Select exactly one source head mesh first')
    if cmds.objExists(name):
        raise ValueError(name + ' already exists. Use it in Fit New Shape, or rename it before creating another.')
    with cage.transaction('FacialSystem_CreateFitTarget'):
        created = cage._copy_mesh(selected[0], name)
        cmds.select(created, replace=True)
    return adapter.mesh_path(created).fullPathName()


def select_controls(kind='face', document=None):
    from . import fit
    bus = fit.native_bus(scope_document(document))
    prefix = bus[:-len('NFRv1_RAW')]
    names = ['CTRL_faceGUI'] if kind == 'face' else ['neck_01', 'neck_02', 'head']
    actual = [prefix + name for name in names if cmds.objExists(prefix + name)]
    if not actual:
        raise ValueError('The requested controls are not present in this scene')
    cmds.select(actual, replace=True)
    return actual
