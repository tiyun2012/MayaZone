"""Portable cage symmetry and settings; no Maya dependency."""
import copy
import math

from . import core

SCHEMA = 'facialSystemCageLayer'


def enum_index(description, label):
    index = 0
    for field in description.split(':'):
        parts = field.split('=', 1)
        if len(parts) == 2:
            index = int(parts[1])
        if parts[0].strip().lower() == label.lower():
            return index
        index += 1
    raise ValueError('Native enum does not contain ' + label)


def bounds(points):
    points = [core.point(point) for point in points]
    if not points:
        raise ValueError('Cage/source has no vertices')
    low = [min(p[axis] for p in points) for axis in range(3)]
    high = [max(p[axis] for p in points) for axis in range(3)]
    return low, high


def symmetry_map(points, tolerance=None):
    """Freeze unique reciprocal mirror pairs about cage-local X=0."""
    points = [core.point(point) for point in points]
    low, high = bounds(points)
    tolerance = tolerance if tolerance is not None else max(max(b - a for a, b in zip(low, high)) * 1e-5, 1e-6)
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError('Symmetry tolerance must be positive and finite')
    buckets = {}
    def cell(point):
        return tuple(math.floor(x / tolerance) for x in point)
    for index, point in enumerate(points):
        buckets.setdefault(cell(point), []).append(index)
    seam = [i for i, p in enumerate(points) if abs(p[0]) <= tolerance]
    nearest = {}
    for index, point in enumerate(points):
        if abs(point[0]) <= tolerance:
            continue
        reflected = [-point[0], point[1], point[2]]
        key = cell(reflected)
        matches = []
        for x in (-1, 0, 1):
            for y in (-1, 0, 1):
                for z in (-1, 0, 1):
                    for candidate in buckets.get((key[0] + x, key[1] + y, key[2] + z), ()):
                        if points[candidate][0] * point[0] < 0:
                            distance = core.distance2(points[candidate], reflected)
                            if distance <= tolerance * tolerance:
                                matches.append((distance, candidate))
        if matches:
            nearest[index] = min(matches)[1]
    pairs = [[i, j] for i, j in sorted(nearest.items())
             if points[i][0] > 0 and nearest.get(j) == i]
    assigned = set(seam)
    for pair in pairs:
        assigned.update(pair)
    return {'vertex_count': len(points), 'pairs': pairs, 'seam': seam,
            'unpaired': sorted(set(range(len(points))) - assigned), 'tolerance_cm': tolerance}


def mirrored_positions(points, pairing, direction='positive'):
    result = [core.point(point) for point in points]
    if len(result) != pairing['vertex_count']:
        raise ValueError('Cage vertex count changed after symmetry capture')
    if direction not in ('positive', 'negative', 'average'):
        raise ValueError('Mirror direction must be positive, negative, or average')
    for positive, negative in pairing['pairs']:
        if direction == 'average':
            a, b = result[positive], result[negative]
            center = [(a[0] - b[0]) * .5, (a[1] + b[1]) * .5, (a[2] + b[2]) * .5]
            result[positive] = center
            result[negative] = [-center[0], center[1], center[2]]
        else:
            source, destination = (positive, negative) if direction == 'positive' else (negative, positive)
            p = result[source]
            result[destination] = [-p[0], p[1], p[2]]
    for index in pairing['seam']:
        result[index][0] = 0.
    return result


def validate(data):
    if data.get('schema') != SCHEMA or data.get('version') != 1:
        raise ValueError('Expected Facial System cage layer data')
    points = data.get('rest_cage_points_cm', [])
    pairing = data.get('symmetry', {})
    if len(points) != pairing.get('vertex_count') or not points:
        raise ValueError('Saved cage rest points and symmetry counts differ')
    for point in points:
        core.point(point)
    matrix = data.get('rest_cage_world_matrix_cm', [])
    if len(matrix) != 16 or not all(math.isfinite(value) for value in matrix):
        raise ValueError('Invalid saved cage rest matrix')
    if data.get('cage_snapshot', {}).get('vertex_count') != len(points):
        raise ValueError('Saved cage topology and rest point counts differ')
    used = set()
    if any(len(pair) != 2 for pair in pairing.get('pairs', [])):
        raise ValueError('Mirror pairs must contain two vertex IDs')
    for group in pairing.get('pairs', []) + [[index] for index in pairing.get('seam', []) + pairing.get('unpaired', [])]:
        for index in group:
            if not isinstance(index, int) or index < 0 or index >= len(points) or index in used:
                raise ValueError('Invalid or repeated symmetry vertex ID')
            used.add(index)
    if used != set(range(len(points))):
        raise ValueError('Saved symmetry groups do not cover every cage vertex')
    for key in ('source', 'root', 'cage', 'preview', 'session'):
        if not data.get(key, {}).get('uuid'):
            raise ValueError('Missing saved cage object identity: ' + key)
    weight = data.get('weight', 1.)
    if not isinstance(weight, (float, int)) or not math.isfinite(weight) or not 0 <= weight <= 1:
        raise ValueError('Layer weight must be between zero and one')
    return data


def export_data(data, points, matrix):
    validate(data)
    result = copy.deepcopy(data)
    result['current_cage_points_cm'] = [core.point(p) for p in points]
    if len(result['current_cage_points_cm']) != len(data['rest_cage_points_cm']):
        raise ValueError('Cage topology changed after creation')
    if len(matrix) != 16 or not all(math.isfinite(value) for value in matrix):
        raise ValueError('Invalid cage transform matrix')
    result['current_cage_world_matrix_cm'] = list(matrix)
    return result
