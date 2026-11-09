"""Read-only Maya adapter for defining translation-only neutral attachments."""
import copy
from pathlib import Path
import re

import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma

from . import core as core


class Cancelled(Exception):
    pass


def dag_path(name):
    selection = om.MSelectionList()
    selection.add(name)
    return selection.getDagPath(0)


def identity(path):
    if isinstance(path, str):
        path = dag_path(path)
    return {'uuid': om.MFnDependencyNode(path.node()).uuid().asString(),
            'path': path.fullPathName(), 'name': path.partialPathName()}


def resolve(info, kind=None):
    for candidate in (info.get('uuid'), info.get('path'), info.get('name')):
        if not candidate:
            continue
        found = cmds.ls(candidate, long=True) or []
        if kind:
            found = [name for name in found if cmds.nodeType(name) == kind]
        if len(found) == 1:
            return found[0]
    raise ValueError('Cannot uniquely resolve ' + info.get('path', info.get('name', 'object')))


def mesh_path(name):
    path = dag_path(name.split('.', 1)[0])
    if path.node().hasFn(om.MFn.kMesh):
        return path
    shapes = cmds.listRelatives(path.fullPathName(), shapes=True, noIntermediate=True,
                               fullPath=True, type='mesh') or []
    if len(shapes) != 1:
        raise ValueError('Select one polygon mesh shape: ' + name)
    return dag_path(shapes[0])


def selected_meshes():
    result = {}
    for name in cmds.ls(selection=True, long=True) or []:
        try:
            path = mesh_path(name)
            result[identity(path)['uuid']] = path.fullPathName()
        except (RuntimeError, ValueError):
            pass
    return list(result.values())


def skin_meshes():
    result = {}
    for skin in cmds.ls(type='skinCluster') or []:
        for shape in cmds.skinCluster(skin, query=True, geometry=True) or []:
            try:
                path = mesh_path(shape)
                result[identity(path)['uuid']] = path.fullPathName()
            except (RuntimeError, ValueError):
                pass
    return sorted(result.values())


def selected_joints(include_children=False):
    selected = cmds.ls(selection=True, long=True, type='joint') or []
    result = set(selected)
    if include_children:
        for joint in selected:
            result.update(cmds.listRelatives(joint, allDescendents=True, fullPath=True, type='joint') or [])
    return sorted(result)


def skin_history(name):
    history = cmds.listHistory(name) or []
    # Passing [] to ls can mean "all scene nodes"; an independent target must
    # not accidentally inherit every skinCluster in the scene here.
    return (cmds.ls(history, type='skinCluster') or []) if history else []


def discover_joints(mesh_names, scope='auto'):
    if scope == 'selected':
        result = selected_joints(include_children=True)
        if not result:
            raise ValueError('Select one or more joints before using Selected joints + children')
        return result, 'selected joints and children'
    if scope == 'auto':
        # The rebuilt rig has one explicit conversion per driven joint channel.
        # This identifies the original connected-joint scope, including joints
        # that currently have no skin weights.
        nodes = cmds.ls('NFRv1_channel_*', type='unitConversion') or []
        nodes += cmds.ls('*:NFRv1_channel_*', type='unitConversion') or []
        result = set()
        for node in set(nodes):
            result.update(cmds.listConnections(node + '.output', source=False, destination=True,
                                               type='joint') or [])
        if result:
            return sorted(set(cmds.ls(list(result), long=True) or [])), 'connected native facial joints'
    result = set()
    for name in mesh_names:
        path = mesh_path(name)
        for skin in skin_history(path.fullPathName()):
            for influence in cmds.skinCluster(skin, query=True, influence=True) or []:
                if cmds.nodeType(influence) == 'joint':
                    result.update(cmds.ls(influence, long=True) or [])
    if not result:
        raise ValueError('No joint influences found. Load skinned meshes or choose selected joints.')
    return sorted(result), 'skin influence joints'


def joint_record(name):
    path = dag_path(name)
    if not path.node().hasFn(om.MFn.kJoint):
        raise ValueError('Expected a joint: ' + name)
    transform = om.MFnTransform(path)
    matrix = list(path.inclusiveMatrix())
    local = transform.translation(om.MSpace.kTransform)
    parent = om.MDagPath(path)
    parent.pop()
    row = {'joint': identity(path),
           'parent': identity(parent) if parent.length() else None,
           'group_name': path.partialPathName().split('|')[-1].replace(':', '_') + '_neutralVerts',
           'default_world_position_cm': matrix[12:15],
           'default_local_translation_cm': [local.x, local.y, local.z],
           'default_world_matrix': matrix, 'vertex_groups': [], 'vertex_count': 0,
           'method': 'unassigned', 'review_required': True, 'detection_details': {},
           'default_group_center_cm': None, 'offset_from_group_cm': None}
    return row


def mesh_snapshot(name):
    path = mesh_path(name)
    fn = om.MFnMesh(path)
    counts, vertices = fn.getVertices()
    counts, vertices = list(counts), list(vertices)
    info = identity(path)
    return {'id': info['uuid'], 'identity': info, 'vertex_count': fn.numVertices,
            'polygon_count': fn.numPolygons,
            'topology_sha256': core.topology_hash(fn.numVertices, counts, vertices),
            'default_positions_cm': [[p.x, p.y, p.z] for p in fn.getPoints(om.MSpace.kWorld)],
            'default_world_matrix': list(path.inclusiveMatrix())}, core.adjacency(fn.numVertices, counts, vertices)


def assert_topology(snapshot, path):
    fn = om.MFnMesh(path)
    counts, vertices = fn.getVertices()
    actual = core.topology_hash(fn.numVertices, list(counts), list(vertices))
    if actual != snapshot['topology_sha256']:
        raise ValueError('Vertex IDs/connectivity changed: ' + path.fullPathName())


def detect(mesh_names, scope='auto', max_vertices=32, relative_threshold=.25,
           nearest_fallback=True, existing=None, progress=None):
    def report(value, total, text):
        if progress and progress(value, total, text) is False:
            raise Cancelled('Detection cancelled. Existing table data was kept.')
    if not mesh_names:
        raise ValueError('Load at least one source mesh')
    joints, scope_name = discover_joints(mesh_names, scope)
    document = copy.deepcopy(existing) if existing else core.new_document(
        cmds.file(query=True, sceneName=True), cmds.currentUnit(query=True, linear=True))
    rows = {row['joint']['uuid']: row for row in document['joints']}
    for joint in joints:
        info = identity(joint)
        if info['uuid'] not in rows:
            rows[info['uuid']] = joint_record(joint)
    # Mesh topology is checked every run; original positions are deliberately
    # retained when the user sculpts the live mesh and detects groups again.
    paths, neighbors = {}, {}
    for i, name in enumerate(mesh_names):
        report(i, len(mesh_names) + len(joints), 'Capture/check mesh: ' + name.split('|')[-1])
        snapshot, graph = mesh_snapshot(name)
        key = snapshot['id']
        if key in document['meshes']:
            if snapshot['topology_sha256'] != document['meshes'][key]['topology_sha256']:
                raise ValueError('Source topology changed. Start a New Capture for this mesh.')
        else:
            document['meshes'][key] = snapshot
        paths[key], neighbors[key] = mesh_path(name), graph
    wanted = {identity(joint)['uuid'] for joint in joints}
    candidates = {}
    for mesh_index, (mesh_id, path) in enumerate(paths.items()):
        report(mesh_index, len(paths) + len(joints), 'Read skin weights: ' + path.partialPathName())
        mesh = document['meshes'][mesh_id]
        for skin in skin_history(path.fullPathName()):
            selection = om.MSelectionList()
            selection.add(skin)
            fn = oma.MFnSkinCluster(selection.getDependNode(0))
            for influence_index, influence in enumerate(fn.influenceObjects()):
                if influence_index % 16 == 0:
                    report(mesh_index, len(paths) + len(joints), 'Read skin weights: ' + skin + ' / ' + influence.partialPathName())
                key = identity(influence)['uuid']
                if key not in wanted or rows[key]['method'] == 'manual':
                    continue
                affected, weights = fn.getPointsAffectedByInfluence(influence)
                offset = 0
                for index in range(affected.length()):
                    affected_path, component = affected.getComponent(index)
                    if component.apiType() != om.MFn.kMeshVertComponent:
                        raise ValueError('Expected polygon vertex skin components')
                    components = om.MFnSingleIndexedComponent(component)
                    ids = (list(range(mesh['vertex_count'])) if components.isComplete
                           else list(components.getElements()))
                    values = [weights[offset + j] for j in range(len(ids))]
                    offset += len(ids)
                    # One skinCluster has one output geometry. The selection
                    # sometimes names its intermediate shape, so compare its
                    # parent transform as well as its shape UUID.
                    other = identity(affected_path)
                    same_shape = other['uuid'] == mesh_id
                    same_parent = affected_path.fullPathName().rsplit('|', 1)[0] == path.fullPathName().rsplit('|', 1)[0]
                    if not (same_shape or same_parent):
                        continue
                    ids, score = core.skin_patch(mesh['default_positions_cm'], rows[key]['default_world_position_cm'],
                                                 ids, values, max_vertices, relative_threshold, neighbors[mesh_id])
                    if score and (key not in candidates or score > candidates[key][0]):
                        candidates[key] = (score, mesh_id, ids, skin)
    for index, joint in enumerate(joints):
        report(len(paths) + index, len(paths) + len(joints), 'Build group: ' + joint.split('|')[-1])
        key = identity(joint)['uuid']
        row = rows[key]
        if row['method'] == 'manual':
            continue
        if key in candidates:
            _, mesh_id, ids, skin = candidates[key]
            core.set_group(document, row, {mesh_id: ids}, 'skin_weights', {'skin_cluster': skin})
        elif nearest_fallback:
            options = []
            for mesh_id in paths:
                ids, d2 = core.nearest_patch(document['meshes'][mesh_id]['default_positions_cm'],
                                             row['default_world_position_cm'], max_vertices, neighbors[mesh_id])
                if ids:
                    options.append((d2, mesh_id, ids))
            if options:
                d2, mesh_id, ids = min(options)
                core.set_group(document, row, {mesh_id: ids}, 'nearest_fallback', {'distance_cm': d2 ** .5})
            else:
                core.set_group(document, row, {}, 'unassigned')
        else:
            core.set_group(document, row, {}, 'unassigned')
    document['joints'] = sorted(rows.values(), key=lambda row: row['joint']['name'].lower())
    document['detection_settings'] = {'scope': scope_name, 'max_vertices': max_vertices,
                                      'minimum_fraction_of_peak_weight': relative_threshold,
                                      'nearest_fallback': nearest_fallback}
    document['updated_utc'] = core.utc_now()
    report(1, 1, 'Done')
    return core.validate(document)


def add_joints(document, names):
    document = copy.deepcopy(document)
    found = {row['joint']['uuid'] for row in document['joints']}
    for name in names:
        row = joint_record(name)
        if row['joint']['uuid'] not in found:
            document['joints'].append(row)
            found.add(row['joint']['uuid'])
    document['joints'].sort(key=lambda row: row['joint']['name'].lower())
    document['updated_utc'] = core.utc_now()
    return document


def selection_groups(document):
    names = cmds.ls(selection=True, long=True, flatten=True) or []
    components = [name for name in names if re.search(r'\.(vtx|f|e)\[', name)]
    if not components:
        raise ValueError('Select source mesh vertices (or faces/edges), then click that row\'s Update.')
    converted = cmds.polyListComponentConversion(components, toVertex=True) or []
    converted = cmds.ls(converted, flatten=True, long=True) or []
    groups, checked = {}, set()
    for component in converted:
        match = re.fullmatch(r'(.+)\.vtx\[(\d+)\]', component)
        if not match:
            continue
        path = mesh_path(match[1])
        key = identity(path)['uuid']
        if key not in document['meshes']:
            raise ValueError('Selected mesh is not a captured source. Add it to Sources and detect first.')
        if key not in checked:
            assert_topology(document['meshes'][key], path)
            checked.add(key)
        groups.setdefault(key, set()).add(int(match[2]))
    if not groups:
        raise ValueError('No polygon vertices selected')
    return {key: sorted(ids) for key, ids in groups.items()}


def select_group(document, row):
    components, transforms = [], set()
    for group in row['vertex_groups']:
        mesh = document['meshes'][group['mesh_id']]
        path = mesh_path(resolve(mesh['identity']))
        assert_topology(mesh, path)
        transforms.add(path.fullPathName().rsplit('|', 1)[0])
        components.extend(path.fullPathName() + '.vtx[' + str(i) + ']' for i in group['vertex_ids'])
    if not components:
        raise ValueError('This joint has no vertex group yet')
    cmds.selectMode(component=True)
    cmds.selectType(polymeshVertex=True)
    cmds.hilite(list(transforms), replace=True)
    cmds.select(components, replace=True)


def select_joint(row):
    name = resolve(row['joint'], 'joint')
    cmds.selectMode(object=True)
    cmds.select(name, replace=True)


def reassign_joint(document, row_index, name):
    replacement = joint_record(name)
    key = replacement['joint']['uuid']
    if any(i != row_index and row['joint']['uuid'] == key for i, row in enumerate(document['joints'])):
        raise ValueError('This joint already has a row')
    old = document['joints'][row_index]
    replacement['group_name'] = old['group_name']
    document['joints'][row_index] = replacement
    core.set_group(document, replacement, {group['mesh_id']: group['vertex_ids'] for group in old['vertex_groups']}, 'manual')
    return replacement


def validate_scene(document):
    core.validate(document)
    problems = []
    for mesh in document['meshes'].values():
        try:
            assert_topology(mesh, mesh_path(resolve(mesh['identity'])))
        except (RuntimeError, ValueError) as exc:
            problems.append(str(exc))
    for row in document['joints']:
        try:
            resolve(row['joint'], 'joint')
        except (RuntimeError, ValueError) as exc:
            problems.append(str(exc))
    return problems


def default_path():
    scene = cmds.file(query=True, sceneName=True)
    base = Path(scene).parent if scene else Path(cmds.workspace(query=True, rootDirectory=True))
    return str(base / 'driveNeutralData.json')
