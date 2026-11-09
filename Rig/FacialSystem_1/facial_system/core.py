"""Portable translation-only attachment data. Python standard library only."""
import copy
import datetime
import hashlib
import heapq
import json
import math
import os
from pathlib import Path
import struct
import tempfile

SCHEMA = 'driveNeutralData'
VERSION = 1


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def new_document(scene='', maya_linear_unit='cm'):
    return {'schema': SCHEMA, 'version': VERSION, 'translation_only': True,
            'coordinate_space': 'world', 'position_unit': 'centimeter',
            'created_utc': utc_now(), 'updated_utc': utc_now(),
            'source_scene': scene, 'maya_display_linear_unit': maya_linear_unit,
            'meshes': {}, 'joints': [], 'detection_settings': {}}


def point(value):
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise ValueError('Expected a three-component position')
    result = [float(x) for x in value]
    if not all(math.isfinite(x) for x in result):
        raise ValueError('Non-finite position')
    return result


def center(points):
    values = list(points)
    if not values:
        raise ValueError('Cannot calculate an empty vertex-group center')
    return [math.fsum(p[axis] for p in values) / len(values) for axis in range(3)]


def distance2(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def topology_hash(vertex_count, face_counts, face_vertices):
    if sum(face_counts) != len(face_vertices):
        raise ValueError('Invalid polygon connectivity')
    if any(i < 0 or i >= vertex_count for i in face_vertices):
        raise ValueError('Invalid polygon vertex ID')
    digest = hashlib.sha256()
    for values in ([vertex_count, len(face_counts)], face_counts, face_vertices):
        for value in values:
            digest.update(struct.pack('<I', int(value)))
    return digest.hexdigest()


def adjacency(vertex_count, face_counts, face_vertices):
    result = [set() for _ in range(vertex_count)]
    start = 0
    for count in face_counts:
        face = face_vertices[start:start + count]
        for i, a in enumerate(face):
            b = face[(i + 1) % count]
            result[a].add(b)
            result[b].add(a)
        start += count
    return result


def skin_patch(points, joint_position, vertex_ids, weights, max_vertices=32,
               relative_threshold=.25, neighbors=None):
    """Select strong skin-weight samples; retain the island containing the peak."""
    if max_vertices < 1 or not 0 <= relative_threshold <= 1:
        raise ValueError('Invalid detection settings')
    if len(vertex_ids) != len(weights):
        raise ValueError('Skin vertex and weight counts differ')
    candidates = [(int(i), float(w)) for i, w in zip(vertex_ids, weights)
                  if math.isfinite(w) and w > 1e-10]
    if not candidates:
        return [], None
    peak = max(w for _, w in candidates)
    candidates = [(i, w) for i, w in candidates if w >= peak * relative_threshold]
    chosen = heapq.nsmallest(max_vertices, candidates,
                            key=lambda pair: (-pair[1], distance2(points[pair[0]], joint_position), pair[0]))
    selected = {i for i, _ in chosen}
    if neighbors is not None and selected:
        # Correspondence/topology is used here, rather than proximity across a
        # closed mouth. A sparse peak may intentionally produce a small group.
        visited, pending = {chosen[0][0]}, [chosen[0][0]]
        while pending:
            current = pending.pop()
            for other in neighbors[current]:
                if other in selected and other not in visited:
                    visited.add(other)
                    pending.append(other)
        chosen = [(i, w) for i, w in chosen if i in visited]
    score = (peak, sum(w for _, w in chosen) / len(chosen),
             -min(distance2(points[i], joint_position) for i, _ in chosen))
    return sorted(i for i, _ in chosen), score


def nearest_patch(points, joint_position, max_vertices=32, neighbors=None):
    """An explicitly reviewable fallback, grown from one closest surface seed."""
    if not points or max_vertices < 1:
        return [], float('inf')
    seed = min(range(len(points)), key=lambda i: (distance2(points[i], joint_position), i))
    if neighbors is None:
        ids = heapq.nsmallest(max_vertices, range(len(points)),
                              key=lambda i: (distance2(points[i], joint_position), i))
    else:
        queue, seen, ids = [(distance2(points[seed], joint_position), seed)], {seed}, []
        while queue and len(ids) < max_vertices:
            _, current = heapq.heappop(queue)
            ids.append(current)
            for other in neighbors[current]:
                if other not in seen:
                    seen.add(other)
                    heapq.heappush(queue, (distance2(points[other], joint_position), other))
    return sorted(ids), distance2(points[seed], joint_position)


def compact_ids(ids):
    ids = sorted(set(ids))
    runs, index = [], 0
    while index < len(ids):
        end = index
        while end + 1 < len(ids) and ids[end + 1] == ids[end] + 1:
            end += 1
        runs.append(str(ids[index]) if end == index else str(ids[index]) + ':' + str(ids[end]))
        index = end + 1
    return ', '.join(runs)


def set_group(document, row, groups, method='manual', details=None):
    """Use captured defaults, even if the live mesh has since been sculpted."""
    normalized = []
    positions = []
    for mesh_id, ids in sorted(groups.items()):
        if mesh_id not in document['meshes']:
            raise ValueError('Vertex group refers to an uncaptured source mesh')
        mesh = document['meshes'][mesh_id]
        ids = sorted(set(ids))
        if any(type(i) is not int or i < 0 or i >= mesh['vertex_count'] for i in ids):
            raise ValueError('Vertex ID outside captured mesh')
        if not ids:
            continue
        normalized.append({'mesh_id': mesh_id, 'vertex_ids': ids})
        positions.extend(mesh['default_positions_cm'][i] for i in ids)
    row['vertex_groups'] = normalized
    row['vertex_count'] = len(positions)
    row['method'] = method if positions else 'unassigned'
    row['review_required'] = method == 'nearest_fallback' or not positions
    row['detection_details'] = details or {}
    row['default_group_center_cm'] = center(positions) if positions else None
    row['offset_from_group_cm'] = ([a - b for a, b in zip(row['default_world_position_cm'],
                                                      row['default_group_center_cm'])]
                                   if positions else None)
    document['updated_utc'] = utc_now()
    return row


def predicted_position(row, current_positions_by_mesh):
    positions = [current_positions_by_mesh[group['mesh_id']][i]
                 for group in row['vertex_groups'] for i in group['vertex_ids']]
    if not positions:
        raise ValueError('Joint has no assigned vertex group')
    current_center = center(positions)
    return [j + c - old for j, c, old in zip(row['default_world_position_cm'], current_center,
                                            row['default_group_center_cm'])]


def validate(document):
    if document.get('schema') != SCHEMA or document.get('version') != VERSION:
        raise ValueError('Unsupported driveNeutralData schema/version')
    if document.get('translation_only') is not True or document.get('coordinate_space') != 'world' or document.get('position_unit') != 'centimeter':
        raise ValueError('Expected world-space, translation-only data in centimeters')
    meshes = document['meshes']
    for key, mesh in meshes.items():
        if mesh['id'] != key or len(mesh['default_positions_cm']) != mesh['vertex_count']:
            raise ValueError('Invalid captured mesh: ' + str(key))
        for value in mesh['default_positions_cm']:
            point(value)
        if len(mesh['topology_sha256']) != 64:
            raise ValueError('Invalid topology fingerprint')
    seen = set()
    for row in document['joints']:
        key = row['joint']['uuid'] or row['joint']['path']
        if key in seen:
            raise ValueError('Duplicate joint entry: ' + row['joint']['name'])
        seen.add(key)
        point(row['default_world_position_cm'])
        point(row['default_local_translation_cm'])
        groups = {}
        for group in row['vertex_groups']:
            if group['mesh_id'] in groups:
                raise ValueError('Duplicate mesh inside a vertex group')
            ids = group['vertex_ids']
            if ids != sorted(set(ids)):
                raise ValueError('Vertex IDs must be sorted and unique')
            groups[group['mesh_id']] = ids
        rebuilt = copy.deepcopy(row)
        set_group({'meshes': meshes}, rebuilt, groups, row['method'])
        if row['vertex_count'] != rebuilt['vertex_count']:
            raise ValueError('Vertex count mismatch')
        for field in ('default_group_center_cm', 'offset_from_group_cm'):
            actual, expected = row[field], rebuilt[field]
            if (actual is None) != (expected is None):
                raise ValueError('Invalid group center/offset')
            if actual is not None and any(abs(a - b) > 1e-8 for a, b in zip(point(actual), expected)):
                raise ValueError('Captured group center/offset does not match saved defaults')
    return document


def save(document, path):
    validate(document)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=str(destination.parent),
                                         prefix=destination.name + '.', suffix='.tmp', delete=False) as handle:
            temporary = handle.name
            json.dump(document, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return str(destination)


def load(path):
    with open(path, encoding='utf-8') as handle:
        document = json.load(handle)
    return validate(document)


def fit_positions(document, target_positions_by_mesh):
    """Absolute fitted positions from the original snapshot, never prior fits."""
    validate(document)
    unknown = set(target_positions_by_mesh) - set(document['meshes'])
    if unknown:
        raise ValueError('Target mapping contains unknown source meshes')
    positions = {key: mesh['default_positions_cm'] for key, mesh in document['meshes'].items()}
    for key, values in target_positions_by_mesh.items():
        if len(values) != document['meshes'][key]['vertex_count']:
            raise ValueError('Target vertex count differs from the saved template')
        positions[key] = [point(value) for value in values]
    result = []
    for row in document['joints']:
        target = predicted_position(row, positions) if row['vertex_count'] else list(row['default_world_position_cm'])
        result.append({'joint': copy.deepcopy(row['joint']), 'position_cm': target,
                       'delta_cm': [a - b for a, b in zip(target, row['default_world_position_cm'])],
                       'assigned': bool(row['vertex_count'])})
    return result


def matrix_cell_from_extractor(basis, output_axis):
    if len(basis) != 3 or output_axis not in (0, 1, 2) or not all(math.isfinite(x) for x in basis):
        raise ValueError('Invalid native matrix extractor')
    active = [i for i, value in enumerate(basis) if abs(value - 1) < 1e-10]
    if len(active) != 1 or any(abs(value) > 1e-10 for i, value in enumerate(basis) if i != active[0]):
        raise ValueError('Expected a unit-axis matrix row extractor')
    return active[0] * 4 + output_axis


def execute_fit(plan, scene, progress=None):
    """Run an all-or-nothing fit through an undoable scene adapter.

    The adapter must roll back all writes, including geometry, on cancellation
    or failed postconditions. This function is independently testable without Maya.
    """
    jobs = [('Joint', row, scene.place_joint) for row in plan['joints']]
    jobs += [('Mesh', row, scene.write_mesh) for row in plan['mesh_edits']]
    jobs += [('Skin', row, scene.update_skin) for row in plan['skins']]
    jobs += [('Bind pose', row, scene.update_pose) for row in plan['poses']]
    total = len(jobs) + 1
    def report(step, text):
        if progress and progress(step, total, text) is False:
            raise RuntimeError('Fit cancelled; scene changes were rolled back.')
    scene.begin()
    try:
        for index, (label, job, action) in enumerate(jobs):
            name = job.get('name', job.get('path', ''))
            report(index, label + ': ' + name)
            action(job, lambda text, index=index: report(index, text))
        report(len(jobs), 'Verify fitted joints, mesh points, rotations, and scales')
        result = scene.verify(plan)
        if not result.get('passed'):
            raise ValueError('Fit verification failed; scene changes were rolled back.\n' + json.dumps(result, indent=2))
        report(total, 'Fit verified')
        scene.commit()
        return result
    except BaseException as failure:
        try:
            scene.rollback()
        except BaseException as rollback_failure:
            raise RuntimeError('Fit failed: {}\nAutomatic rollback also failed: {}'.format(
                failure, rollback_failure)) from rollback_failure
        raise
