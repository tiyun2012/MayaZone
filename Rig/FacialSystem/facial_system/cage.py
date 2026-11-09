"""One native Proximity Wrap cage layer. No callbacks or plug-ins."""
from contextlib import contextmanager
import copy
import json
import math
import re
import time

import maya.cmds as cmds
import maya.api.OpenMaya as om

from . import cage_core, cage_landmarks, core, fit, scene_adapter as adapter

MARKER = 'facialSystemCageLayer'
DATA_ATTR = 'layerData'


@contextmanager
def transaction(label):
    if not cmds.undoInfo(query=True, state=True):
        raise ValueError('Enable Maya Undo before editing the cage layer')
    previous = cmds.undoInfo(query=True, undoName=True)
    cmds.undoInfo(openChunk=True, chunkName=label)
    try:
        yield
    except Exception as exc:
        cmds.undoInfo(closeChunk=True)
        current = cmds.undoInfo(query=True, undoName=True)
        if current == label:
            cmds.undo()
        elif current != previous:
            raise RuntimeError(str(exc) + '\nThe undo queue changed; no unrelated action was undone.') from exc
        raise
    else:
        cmds.undoInfo(closeChunk=True)


def node_info(name):
    matches = cmds.ls(name, long=True) or []
    if len(matches) != 1:
        raise ValueError('Object is missing or ambiguous: ' + name)
    return {'uuid': cmds.ls(matches[0], uuid=True)[0], 'path': matches[0], 'name': matches[0].split('|')[-1]}


def resolve(info):
    # Session-owned objects must match UUIDs, never an unrelated replacement name.
    found = cmds.ls(info['uuid'], long=True) or []
    if len(found) != 1:
        raise ValueError('Saved cage object is missing: ' + info.get('path', 'object'))
    return found[0]


def transform(name):
    path = adapter.mesh_path(name)
    return path.fullPathName().rsplit('|', 1)[0]


def _matrix(name):
    return list(adapter.dag_path(name).inclusiveMatrix())


def _set_matrix(name, matrix):
    values = list(matrix)
    values[12:15] = [fit.ui_distance(x) for x in values[12:15]]
    cmds.xform(name, worldSpace=True, matrix=values)


def _set_points(name, points, progress=None, label='Update cage vertices'):
    path = adapter.mesh_path(name).fullPathName()
    for index, point in enumerate(points):
        if progress and index % 32 == 0 and progress(index, len(points), label) is False:
            raise adapter.Cancelled('Cage operation cancelled; prior scene state restored.')
        cmds.xform(path + '.vtx[' + str(index) + ']', objectSpace=True,
                   translation=[fit.ui_distance(x) for x in core.point(point)])


def _copy_mesh(source, name, root=None):
    original = adapter.mesh_path(source)
    parent = transform(source)
    children = cmds.listRelatives(parent, children=True, fullPath=True) or []
    if any(cmds.nodeType(child) != 'mesh' for child in children):
        raise ValueError('Source transform must contain mesh shapes only: ' + parent)
    temporary = cmds.duplicate(parent, name='FS_CopyTmp', returnRootsOnly=True,
                               upstreamNodes=False, inputConnections=False)[0]
    cmds.delete(temporary, constructionHistory=True)
    for shape in cmds.listRelatives(temporary, shapes=True, fullPath=True) or []:
        if cmds.getAttr(shape + '.intermediateObject'):
            cmds.delete(shape)
    # The supplied head transform has locked TRS channels. Move only the new
    # duplicated output shape under a fresh transform instead of inheriting
    # those channel locks or changing any original source settings.
    copied_shape = adapter.mesh_path(temporary).fullPathName()
    copied_matrix = _matrix(transform(temporary))
    options = {'name': name}
    if root:
        options['parent'] = root
    result = cmds.createNode('transform', **options)
    _set_matrix(result, copied_matrix)
    cmds.parent(copied_shape, result, shape=True, relative=True)
    cmds.delete(temporary)
    result = transform(result)
    snapshot, _ = adapter.mesh_snapshot(original.fullPathName())
    adapter.assert_topology(snapshot, adapter.mesh_path(result))
    if adapter.skin_history(result):
        raise ValueError('Independent copy unexpectedly retained a skinCluster')
    actual = fit.points(adapter.mesh_path(result))
    if max((core.distance2(a, b) for a, b in zip(snapshot['default_positions_cm'], actual)), default=0.) > 1e-8:
        raise ValueError('Independent copy did not preserve source positions')
    return result


def sessions():
    return [node for node in (cmds.ls(type='network') or [])
            if cmds.attributeQuery(MARKER, node=node, exists=True) and cmds.getAttr(node + '.' + MARKER)]


def load(node=None):
    if node is None:
        found = sessions()
        if not found:
            return None
        if len(found) != 1:
            raise ValueError('More than one cage session exists; specify the desired session node')
        node = found[0]
    if not cmds.attributeQuery(MARKER, node=node, exists=True) or not cmds.getAttr(node + '.' + MARKER):
        raise ValueError('Expected a Facial System cage session')
    return cage_core.validate(json.loads(cmds.getAttr(node + '.' + DATA_ATTR)))


def _save(data):
    cage_core.validate(data)
    cmds.setAttr(resolve(data['session']) + '.' + DATA_ATTR,
                 json.dumps(data, allow_nan=False), type='string')


def _check(data):
    cage_core.validate(data)
    cage_path = adapter.mesh_path(resolve(data['cage']))
    preview_path = adapter.mesh_path(resolve(data['preview']))
    adapter.assert_topology(data['cage_snapshot'], cage_path)
    adapter.assert_topology(data['source_snapshot'], preview_path)
    if data.get('deformer'):
        deformer = resolve(data['deformer'])
        if cmds.nodeType(deformer) != 'proximityWrap':
            raise ValueError('The saved cage deformer is no longer Proximity Wrap')
        if deformer not in (cmds.listHistory(preview_path.fullPathName()) or []):
            raise ValueError('The saved deformer is no longer in the preview mesh history')
    return cage_path, preview_path


def _set_enum(node, attribute, label):
    values = cmds.attributeQuery(attribute.rsplit('.', 1)[-1], node=node, listEnum=True) or []
    if len(values) != 1:
        raise ValueError('Native enum is unavailable: ' + attribute)
    cmds.setAttr(node + '.' + attribute, cage_core.enum_index(values[0], label))


def landmark_draft(source, existing=None):
    path = adapter.mesh_path(source)
    if existing is None:
        snapshot, _ = adapter.mesh_snapshot(path.fullPathName())
        return cage_landmarks.empty(snapshot)
    cage_landmarks.validate(existing)
    snapshot = existing['source_snapshot']
    if adapter.identity(path)['uuid'] != snapshot['identity']['uuid']:
        raise ValueError('Landmarks belong to another source mesh. Choose their source, or start a new landmark set.')
    adapter.assert_topology(snapshot, path)
    current = fit.points(path)
    if max((core.distance2(a, b) for a, b in zip(current, snapshot['default_positions_cm'])), default=0.) > 1e-8:
        raise ValueError('Landmark source positions changed. Restore the captured neutral shape, or start a new landmark set.')
    return copy.deepcopy(existing)


def suggest_landmarks(source, existing=None):
    """Named-joint proposals only; manual assignments are retained for review."""
    data = landmark_draft(source, existing)
    try:
        joints, _ = adapter.discover_joints([source])
    except ValueError:
        joints = []
    names = {}
    for joint in joints:
        names.setdefault(joint.split('|')[-1].split(':')[-1], []).append(joint)
    manual = {item['key'] for item in data['items'] if item.get('method') == 'manual'}
    points = data['source_snapshot']['default_positions_cm']
    for preset in cage_landmarks.presets():
        found = names.get(preset['joint'], [])
        if preset['key'] in manual or len(found) != 1:
            continue
        position = _matrix(found[0])[12:15]
        index = min(range(len(points)), key=lambda i: core.distance2(points[i], position))
        data = cage_landmarks.assign(data, preset['key'], index, 'rig_suggestion_review')
    return data


def assign_landmark(source, data, key):
    data = landmark_draft(source, data)
    selected = cmds.ls(selection=True, flatten=True, long=True) or []
    if len(selected) != 1:
        raise ValueError('Select exactly one source mesh vertex for this landmark')
    match = re.fullmatch(r'(.+)\.vtx\[(\d+)\]', selected[0])
    if not match or adapter.identity(adapter.mesh_path(match[1]))['uuid'] != data['source_snapshot']['identity']['uuid']:
        raise ValueError('Select one vertex on the Template / source head')
    return cage_landmarks.assign(data, key, int(match[2]))


def selected_world_point():
    selected = cmds.ls(selection=True, flatten=True, long=True) or []
    if len(selected) != 1:
        raise ValueError('Select one reference vertex or one positioned locator/transform')
    match = re.fullmatch(r'(.+)\.vtx\[(\d+)\]', selected[0])
    if match:
        points = fit.points(adapter.mesh_path(match[1]))
        index = int(match[2])
        if not 0 <= index < len(points):
            raise ValueError('Selected vertex is outside the reference mesh')
        return points[index]
    if '.' in selected[0] or cmds.nodeType(selected[0]) not in ('transform', 'joint'):
        raise ValueError('Select a mesh vertex, locator transform, or joint')
    return _matrix(selected[0])[12:15]


def select_landmark(data, key, cage_vertex=True):
    marks = data.get('landmarks') if cage_vertex else data
    if not marks:
        raise ValueError('This cage has no saved landmark assignments')
    item = next((row for row in marks['items'] if row['key'] == key), None)
    field = 'cage_vertex' if cage_vertex else 'source_vertex'
    if item is None or field not in item:
        raise ValueError('Assign this landmark on the source before generating a Reduced head cage')
    if cage_vertex:
        path, _ = _check(data)
    else:
        path = adapter.mesh_path(adapter.resolve(marks['source_snapshot']['identity']))
        adapter.assert_topology(marks['source_snapshot'], path)
    cmds.selectMode(component=True)
    cmds.selectType(polymeshVertex=True)
    cmds.select(path.fullPathName() + '.vtx[' + str(item[field]) + ']', replace=True)


def move_landmark(data, key, position_cm, mirror=True):
    path, _ = _check(data)
    if not data.get('deformer'):
        raise ValueError('Bind the cage before matching its landmarks to the reference')
    item = next((row for row in data.get('landmarks', {}).get('items', []) if row['key'] == key), None)
    if item is None or 'cage_vertex' not in item:
        raise ValueError('This cage has no control for that landmark')
    point = om.MPoint(*core.point(position_cm)) * om.MMatrix(_matrix(resolve(data['cage']))).inverse()
    value = [point.x, point.y, point.z]
    index = item['cage_vertex']
    updates = {index: value}
    if mirror:
        if index in data['symmetry']['unpaired']:
            raise ValueError('This landmark has no captured mirror partner. Disable mirror matching to move this point alone.')
        if index in data['symmetry']['seam']:
            value[0] = 0.
        for a, b in data['symmetry']['pairs']:
            if index in (a, b):
                updates[b if index == a else a] = [-value[0], value[1], value[2]]
                break
    with transaction('FacialSystem_MoveCageLandmark'):
        for vertex, position in updates.items():
            cmds.xform(path.fullPathName() + '.vtx[' + str(vertex) + ']', objectSpace=True,
                       translation=[fit.ui_distance(x) for x in position])
    return {'landmark': item['label'], 'updated_cage_vertices': sorted(updates), 'mirrored': bool(mirror)}


def _reduced_copy(source, root, source_points, center, landmarks, target_vertices, rings, progress):
    cage = _copy_mesh(source, 'FS_Cage_L1', root)
    path = adapter.mesh_path(cage)
    counts, indices = om.MFnMesh(path).getVertices()
    centered = [[p[i] - center[i] for i in range(3)] for p in source_points]
    source_pairing = cage_core.symmetry_map(centered)
    pins = [item['source_vertex'] for item in landmarks['items']]
    plan = cage_landmarks.reduction_faces(len(source_points), list(counts), list(indices),
                                          pins, source_pairing, rings)
    if progress and progress(0, 1, 'Reduce working head; preserve landmark faces') is False:
        raise adapter.Cancelled('Cage reduction cancelled; scene restored.')
    source_ids = list(range(len(source_points)))
    reduced = target_vertices < len(source_points) and bool(plan['reduce_faces'])
    if reduced:
        map_name = 'FS_CageSourceVertexIDs'
        if map_name in (cmds.polyColorSet(cage, query=True, allColorSets=True) or []):
            cmds.polyColorSet(cage, delete=True, colorSet=map_name)
        components = cage_landmarks.component_ranges(path.fullPathName(), 'f', plan['reduce_faces'])
        cmds.polyReduce(components, version=1, termination=1, vertexCount=target_vertices,
                        constructionHistory=False, replaceOriginal=True, preserveTopology=True,
                        keepBorder=True, keepBorderWeight=1., keepQuadsWeight=.5,
                        keepHardEdge=True, keepHardEdgeWeight=.5, keepCreaseEdge=True,
                        keepCreaseEdgeWeight=.5, keepMapBorder=False, keepColorBorder=False,
                        keepFaceGroupBorder=False, useVirtualSymmetry=2,
                        symmetryPlaneX=1., symmetryPlaneY=0., symmetryPlaneZ=0.,
                        symmetryPlaneW=fit.ui_distance(-center[0]),
                        symmetryTolerance=fit.ui_distance(source_pairing['tolerance_cm']),
                        vertexMapName=map_name, cachingReduce=True)
        path = adapter.mesh_path(cage)
        actual = fit.points(path, om.MSpace.kObject)
        colors = om.MFnMesh(path).getVertexColors(map_name)
        source_ids = cage_landmarks.decode_source_map([[c.r, c.g, c.b] for c in colors], source_points, actual)
        if not set(plan['protected_vertices']).issubset(source_ids):
            raise ValueError('Reduction removed protected vertices. Increase the cage count or reduce protection rings.')
        cmds.polyColorSet(cage, delete=True, colorSet=map_name)
    if progress and progress(1, 1, 'Validate retained landmark IDs') is False:
        raise adapter.Cancelled('Cage reduction cancelled; scene restored.')
    if len(source_ids) > 5000:
        raise ValueError('The generated cage exceeds 5000 vertices. Lower the target count or protection rings.')
    marks = cage_landmarks.map_items(landmarks, source_ids)
    pairing = cage_landmarks.remap_symmetry(source_pairing, source_ids)
    return cage, source_ids, marks, pairing, {
        'requested_vertices': target_vertices, 'actual_vertices': len(source_ids),
        'protected_landmarks': len(marks['items']), 'protected_vertices': len(plan['protected_vertices']),
        'excluded_faces': len(plan['excluded_faces']), 'protected_rings': rings,
        'reduction_ran': reduced, 'note': 'Protected faces and borders can keep the count above the requested target.'}


def create(source, reference=None, custom_cage=None, around=12, rings=12,
           conform=True, progress=None, seed='sphere', target_vertices=400,
           landmarks=None, protected_rings=0):
    """Create an independent preview and a symmetric coarse seed cage."""
    if sessions():
        raise ValueError('A cage layer already exists. Resume it, or remove the working layer before creating another.')
    source_path = adapter.mesh_path(source)
    snapshot, _ = adapter.mesh_snapshot(source_path.fullPathName())
    source_points_object = fit.points(source_path, om.MSpace.kObject)
    low, high = cage_core.bounds(source_points_object)
    center = [(a + b) * .5 for a, b in zip(low, high)]
    halves = [(b - a) * .5 for a, b in zip(low, high)]
    if min(halves) <= 1e-6:
        raise ValueError('Source must be a three-dimensional head mesh')
    if seed not in ('sphere', 'reduced'):
        raise ValueError('Cage generation must be sphere or reduced')
    if not custom_cage and seed == 'sphere' and (around < 6 or around > 32 or around % 2 or rings < 4 or rings > 24):
        raise ValueError('Use an even Around value 6..32 and Rings 4..24')
    if not isinstance(target_vertices, int) or not 24 <= target_vertices <= 5000:
        raise ValueError('Reduced cage target must be 24..5000 vertices')
    if not isinstance(protected_rings, int) or not 0 <= protected_rings <= 3:
        raise ValueError('Protected rings must be 0..3')
    landmark_data = landmark_draft(source, landmarks) if seed == 'reduced' and not custom_cage else None
    reduction, source_ids = None, None
    if reference:
        reference = transform(reference)
    started = time.perf_counter()
    with transaction('FacialSystem_CreateCage'):
        root = cmds.group(empty=True, name='FS_CageWork')
        cmds.addAttr(root, longName='facialSystemCageRoot', attributeType='bool', defaultValue=True)
        preview = _copy_mesh(source_path.fullPathName(), 'FS_CagePreview', root)
        if custom_cage or seed == 'reduced':
            if custom_cage:
                cage = _copy_mesh(custom_cage, 'FS_Cage_L1', root)
            else:
                cage, source_ids, landmark_data, pairing, reduction = _reduced_copy(
                    source_path.fullPathName(), root, source_points_object, center,
                    landmark_data, target_vertices, protected_rings, progress)
            cage_points = fit.points(adapter.mesh_path(cage), om.MSpace.kObject)
            if len(cage_points) > 5000:
                raise ValueError('Use a coarse custom cage with at most 5000 vertices')
            bounds = cage_core.bounds(cage_points)
            pivot = [(a + b) * .5 for a, b in zip(*bounds)] if custom_cage else center
            local_shift = om.MMatrix([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, *pivot, 1])
            new_matrix = list(local_shift * om.MMatrix(_matrix(cage)))
            cage_points = [[p[i] - pivot[i] for i in range(3)] for p in cage_points]
            _set_matrix(cage, new_matrix)
            if custom_cage:
                pairing = cage_core.symmetry_map(cage_points)
        else:
            cage = cmds.polySphere(name='FS_Cage_L1', radius=1., subdivisionsAxis=around,
                                    subdivisionsHeight=rings, axis=(0, 1, 0), constructionHistory=False)[0]
            cage = cmds.parent(cage, root, absolute=True)[0]
            unit = fit.points(adapter.mesh_path(cage), om.MSpace.kObject)
            unit = [[x / math.sqrt(sum(t * t for t in p)) for x in p] for p in unit]
            pairing = cage_core.symmetry_map(unit)
            local_shift = om.MMatrix([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, *center, 1])
            new_matrix = list(local_shift * source_path.inclusiveMatrix())
            _set_matrix(cage, new_matrix)
            cage_points = [[p[i] * halves[i] * 1.02 for i in range(3)] for p in unit]
            if conform:
                fn = om.MFnMesh(source_path)
                matrix = om.MMatrix(new_matrix)
                inverse = matrix.inverse()
                for index, point in enumerate(cage_points):
                    if progress and index % 16 == 0 and progress(index, len(cage_points), 'Fit seed cage to source') is False:
                        raise adapter.Cancelled('Cage creation cancelled; scene restored.')
                    closest, _ = fn.getClosestPoint(om.MPoint(*point) * matrix, om.MSpace.kWorld)
                    p = closest * inverse
                    # Keep some seed spacing to avoid coincident controls at
                    # neck borders, nostrils, and other narrow surface regions.
                    cage_points[index] = [.1 * a + .9 * b for a, b in zip(point, (p.x, p.y, p.z))]
            cage_points = cage_core.mirrored_positions(cage_points, pairing, 'average')
        _set_points(cage, cage_points, progress)
        cage = transform(cage)
        # Proximity Wrap binds original geometry. Give both originals the same
        # local frame, preserving visible world positions and vertex IDs. This
        # also keeps cage Object-X symmetry aligned on translated/rotated heads.
        bind_matrix = om.MMatrix(_matrix(cage))
        if not math.isfinite(bind_matrix.det4x4()) or abs(bind_matrix.det4x4()) < 1e-12:
            raise ValueError('Cage bind transform is singular')
        inverse = bind_matrix.inverse()
        preview_world = fit.points(adapter.mesh_path(preview))
        preview_local = []
        for point in preview_world:
            p = om.MPoint(*point) * inverse
            preview_local.append([p.x, p.y, p.z])
        _set_matrix(preview, list(bind_matrix))
        _set_points(preview, preview_local, progress, label='Prepare shared cage bind space')
        cmds.delete([cage, preview], constructionHistory=True)
        cage_snapshot, _ = adapter.mesh_snapshot(cage)
        # Keep the original sphere vertex correspondence even when closest-
        # point conforming makes several seed vertices coincide.
        node = cmds.createNode('network', name='FS_CageLayer01')
        cmds.addAttr(node, longName=MARKER, attributeType='bool', defaultValue=True)
        cmds.addAttr(node, longName=DATA_ATTR, dataType='string')
        data = {'schema': cage_core.SCHEMA, 'version': 1, 'created_utc': core.utc_now(),
                'source': node_info(transform(source)), 'reference': node_info(reference) if reference else None,
                'root': node_info(root), 'cage': node_info(cage), 'preview': node_info(preview),
                'session': node_info(node), 'deformer': None, 'source_snapshot': snapshot,
                'cage_snapshot': cage_snapshot, 'rest_cage_points_cm': cage_points,
                'rest_cage_world_matrix_cm': _matrix(cage), 'symmetry': pairing,
                'weight': 1., 'enabled': True, 'mode': 'Offset',
                'seed': {'kind': 'custom' if custom_cage else seed, 'around': around, 'rings': rings, 'conform': conform},
                'create_seconds': time.perf_counter() - started}
        if source_ids is not None:
            data.update({'cage_source_vertex_ids': source_ids, 'landmarks': landmark_data, 'reduction': reduction})
        for key in ('source', 'root', 'cage', 'preview', 'reference'):
            if data.get(key):
                cmds.addAttr(node, longName=key + 'Link', attributeType='message')
                cmds.connectAttr(resolve(data[key]) + '.message', node + '.' + key + 'Link')
        shape = adapter.mesh_path(cage).fullPathName()
        cmds.setAttr(shape + '.overrideEnabled', True)
        cmds.setAttr(shape + '.overrideShading', False)
        cmds.setAttr(shape + '.overrideColor', 17)
        _save(data)
        cmds.select(cage, replace=True)
    return data


def bind(data, progress=None):
    cage_path, preview = _check(data)
    if data.get('deformer'):
        raise ValueError('The cage is already bound. Edit its vertices or use Reset Cage.')
    current = fit.points(cage_path, om.MSpace.kObject)
    if max(core.distance2(a, b) for a, b in zip(current, data['rest_cage_points_cm'])) > 1e-8 or \
            max(abs(a - b) for a, b in zip(_matrix(resolve(data['cage'])), data['rest_cage_world_matrix_cm'])) > 1e-7:
        raise ValueError('Bind before moving the cage. Reset Cage, bind, then reshape it.')
    started = time.perf_counter()
    result = copy.deepcopy(data)
    original = fit.points(preview)
    if max(abs(a - b) for a, b in zip(_matrix(resolve(data['preview'])), data['rest_cage_world_matrix_cm'])) > 1e-7:
        raise ValueError('The working preview moved out of the saved cage bind space. Recreate the coarse layer.')
    if max((core.distance2(a, b) ** .5 for a, b in
            zip(original, data['source_snapshot']['default_positions_cm'])), default=0.) > .0001:
        raise ValueError('The working preview changed before binding. Recreate the coarse layer.')
    with transaction('FacialSystem_BindCage'):
        deformer = cmds.deformer(preview.fullPathName(), type='proximityWrap', name='FS_CageWrap_L1')[0]
        _set_enum(deformer, 'wrapMode', data['mode'])
        cmds.setAttr(deformer + '.envelope', data['weight'] if data['enabled'] else 0.)
        for attribute, value in (('useBindTags', False), ('smoothNormals', 0), ('smoothInfluences', 0),
                                 ('softNormalization', False), ('maxDrivers', 1), ('falloffScale', 1.)):
            cmds.setAttr(deformer + '.' + attribute, value)
        cmds.proximityWrap(deformer, edit=True, applyUserDefaults=False, addDrivers=[cage_path.fullPathName()])
        indices = cmds.proximityWrap(deformer, query=True, driverIndices=True) or []
        if len(indices) != 1:
            raise ValueError('Expected one connected cage driver')
        driver = deformer + '.drivers[' + str(indices[0]) + ']'
        _set_enum(deformer, 'drivers[' + str(indices[0]) + '].driverWrapMode', 'Global')
        # A finite coverage radius, computed once at bind, includes all source
        # vertices. No closest-point search runs from Python during dragging.
        fn = om.MFnMesh(cage_path)
        max_gap = 0.
        for index, point in enumerate(original):
            if progress and index % 128 == 0 and progress(index, len(original), 'Bind cage coverage') is False:
                raise adapter.Cancelled('Cage bind cancelled; scene restored.')
            closest, _ = fn.getClosestPoint(om.MPoint(*point), om.MSpace.kWorld)
            max_gap = max(max_gap, core.distance2(point, [closest.x, closest.y, closest.z]) ** .5)
        low, high = cage_core.bounds(original)
        diagonal = core.distance2(low, high) ** .5
        radius = max_gap * 1.25 + diagonal * .01
        cmds.setAttr(driver + '.driverFalloffStart', 0.)
        cmds.setAttr(driver + '.driverFalloffEnd', radius)
        cmds.setAttr(driver + '.driverDropoffRate', 4.)
        # Explicit ramp and settings keep the test independent of user defaults.
        for i, position, value in ((0, 0., 1.), (1, 1., 0.)):
            prefix = deformer + '.falloffRamp[' + str(i) + ']'
            cmds.setAttr(prefix + '.falloffRamp_Position', position)
            cmds.setAttr(prefix + '.falloffRamp_FloatValue', value)
            cmds.setAttr(prefix + '.falloffRamp_Interp', 1)
        after = fit.points(adapter.mesh_path(resolve(data['preview'])))
        error = max((core.distance2(a, b) ** .5 for a, b in zip(original, after)), default=0.)
        if error > .0001:
            raise ValueError('Binding changed the rest mesh by {:.6f} cm'.format(error))
        result.update({'deformer': node_info(deformer), 'driver_index': indices[0],
                       'bind_seconds': time.perf_counter() - started, 'falloff_end_cm': radius,
                       'bind_rest_error_cm': error})
        _save(result)
    return result


def set_layer(data, weight=1., enabled=True, mode='Offset'):
    if not math.isfinite(weight) or not 0 <= weight <= 1 or mode not in ('Offset', 'Surface'):
        raise ValueError('Use weight 0..1 and Offset or Surface mode')
    _check(data)
    result = copy.deepcopy(data)
    with transaction('FacialSystem_CageSettings'):
        if data.get('deformer'):
            node = resolve(data['deformer'])
            _set_enum(node, 'wrapMode', mode)
            cmds.setAttr(node + '.envelope', weight if enabled else 0.)
        result.update({'weight': float(weight), 'enabled': bool(enabled), 'mode': mode})
        _save(result)
    return result


def reset(data, progress=None):
    _check(data)
    with transaction('FacialSystem_ResetCage'):
        _set_matrix(resolve(data['cage']), data['rest_cage_world_matrix_cm'])
        _set_points(resolve(data['cage']), data['rest_cage_points_cm'], progress)
    return inspect(data)


def mirror(data, direction='positive'):
    path, _ = _check(data)
    current = fit.points(path, om.MSpace.kObject)
    target = cage_core.mirrored_positions(current, data['symmetry'], direction)
    with transaction('FacialSystem_MirrorCage'):
        _set_points(path.fullPathName(), target)
    return inspect(data)


def inspect(data):
    cage_path, preview = _check(data)
    started = time.perf_counter()
    current = fit.points(preview)
    baseline = data['source_snapshot']['default_positions_cm']
    return {'schema': 'facialSystemCageCheck', 'version': 1,
            'bound': bool(data.get('deformer')), 'cage_vertices': om.MFnMesh(cage_path).numVertices,
            'fit_vertices': len(current), 'unpaired_cage_vertices': len(data['symmetry']['unpaired']),
            'maximum_surface_delta_cm': max((core.distance2(a, b) ** .5 for a, b in zip(current, baseline)), default=0.),
            'read_evaluated_output_ms': (time.perf_counter() - started) * 1000.,
            'timing_note': 'Output read may be cached; this is not a drag-FPS benchmark.',
            'bind_seconds': data.get('bind_seconds'), 'mode': data['mode']}


def test_response(data, delta_cm=.2):
    """Move one control briefly, read the output, and restore its exact state."""
    path, preview = _check(data)
    if not data.get('deformer') or not data['enabled'] or data['weight'] <= 0:
        raise ValueError('Bind and enable the cage with a positive weight before testing its response')
    if not math.isfinite(delta_cm) or delta_cm <= 0:
        raise ValueError('Test movement must be positive and finite')
    current = fit.points(path, om.MSpace.kObject)
    index = max(range(len(current)), key=lambda i: current[i][0])
    original = current[index]
    component = path.fullPathName() + '.vtx[' + str(index) + ']'
    before = fit.points(preview)
    label = 'FacialSystem_TestCageResponse'
    started = time.perf_counter()
    with transaction(label):
        try:
            moved = [original[0], original[1] + delta_cm, original[2]]
            cmds.xform(component, objectSpace=True, translation=[fit.ui_distance(x) for x in moved])
            after = fit.points(preview)
            elapsed = (time.perf_counter() - started) * 1000.
        finally:
            cmds.xform(component, objectSpace=True, translation=[fit.ui_distance(x) for x in original])
    # Remove only our zero-net-change test from the queue when identifiable.
    if cmds.undoInfo(query=True, undoName=True) == label:
        cmds.undo()
    restored = fit.points(preview)
    moved_error = max((core.distance2(a, b) ** .5 for a, b in zip(before, after)), default=0.)
    restore_error = max((core.distance2(a, b) ** .5 for a, b in zip(before, restored)), default=0.)
    return {'schema': 'facialSystemCageResponseTest', 'version': 1,
            'control_vertex': index, 'control_move_cm': delta_cm,
            'maximum_output_move_cm': moved_error, 'maximum_restore_error_cm': restore_error,
            'one_control_update_and_output_read_ms': elapsed,
            'passed': moved_error > 1e-6 and restore_error <= .0001,
            'scope': 'One native control movement and restoration; actual Maya measurement, not a frame-rate guarantee.'}


def bake(data, name='Head_FitTarget'):
    _, preview = _check(data)
    if not data.get('deformer'):
        raise ValueError('Bind the cage before baking a fitting target')
    if not name or any(character in name for character in '|.:/\\'):
        raise ValueError('Use a simple object name for the baked target')
    with transaction('FacialSystem_BakeCage'):
        # Maya assigns a suffix when that name already exists. Existing targets
        # are retained, and the UI maps the actual returned name explicitly.
        result = _copy_mesh(preview.fullPathName(), name)
        adapter.assert_topology(data['source_snapshot'], adapter.mesh_path(result))
        cmds.select(result, replace=True)
    return adapter.mesh_path(result).fullPathName()


def export(data):
    path, _ = _check(data)
    return cage_core.export_data(data, fit.points(path, om.MSpace.kObject), _matrix(resolve(data['cage'])))


def remove(data):
    cage_core.validate(data)
    cage_path = adapter.mesh_path(resolve(data['cage']))
    preview = adapter.mesh_path(resolve(data['preview']))
    root = resolve(data['root'])
    if not cmds.attributeQuery('facialSystemCageRoot', node=root, exists=True) or not cmds.getAttr(root + '.facialSystemCageRoot'):
        raise ValueError('The saved work group has no Facial System cage ownership marker')
    expected = {resolve(data['cage']), resolve(data['preview'])}
    children = set(cmds.listRelatives(root, children=True, fullPath=True) or [])
    if children != expected:
        raise ValueError('The cage work group contains additional objects. Move them out before removing it.')
    for path in (cage_path, preview):
        if any(cmds.nodeType(child) != 'mesh' for child in
               (cmds.listRelatives(transform(path.fullPathName()), children=True, fullPath=True) or [])):
            raise ValueError('An owned mesh contains additional child objects')
    with transaction('FacialSystem_RemoveCage'):
        cmds.delete(resolve(data['preview']), constructionHistory=True)
        cmds.delete(root)
        cmds.delete(resolve(data['session']))


def enable_symmetry(data):
    path, _ = _check(data)
    if data['symmetry']['unpaired']:
        raise ValueError('This cage has unmatched mirror vertices. Use the manual mirror buttons, or supply a symmetric cage.')
    previous = {key: cmds.symmetricModelling(query=True, **{key: True})
                for key in ('symmetry', 'about', 'axis', 'tolerance', 'preserveSeam')}
    cmds.symmetricModelling(symmetry=1, about='object', axis='x',
                            tolerance=fit.ui_distance(data['symmetry']['tolerance_cm']), preserveSeam=1)
    select_vertices(data)
    return previous


def select_vertices(data):
    path, _ = _check(data)
    cmds.selectMode(component=True)
    cmds.selectType(polymeshVertex=True)
    cmds.select(path.fullPathName() + '.vtx[*]', replace=True)


def restore_symmetry(previous):
    if previous is not None:
        cmds.symmetricModelling(**previous)
