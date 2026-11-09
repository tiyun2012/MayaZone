"""Portable landmark definitions and protected-face reduction planning."""
import copy
import math

from . import core

SCHEMA = 'facialSystemCageLandmarks'


def presets():
    result = []
    for key, label, joint in (
        ('forehead', 'Forehead center', 'FACIAL_C_Forehead'),
        ('nose_bridge', 'Nose bridge', 'FACIAL_C_NoseBridge'),
        ('nose_tip', 'Nose tip', 'FACIAL_C_NoseTip'),
        ('upper_lip', 'Upper lip center', 'FACIAL_C_LipUpper'),
        ('lower_lip', 'Lower lip center', 'FACIAL_C_LipLower'),
        ('chin', 'Chin tip', 'FACIAL_C_Chin')):
        result.append({'key': key, 'label': label, 'joint': joint})
    for key, label, joint in (
        ('brow_inner', 'Brow inner', 'ForeheadIn'),
        ('brow_mid', 'Brow middle', 'ForeheadMid'),
        ('brow_outer', 'Brow outer', 'ForeheadOut'),
        ('eye_inner', 'Eye inner corner', 'EyeCornerInner'),
        ('eye_outer', 'Eye outer corner', 'EyeCornerOuter'),
        ('lid_upper', 'Upper eyelid', 'EyelidUpperA'),
        ('lid_lower', 'Lower eyelid', 'EyelidLowerA'),
        ('nose_wing', 'Nose wing', 'Nostril'),
        ('mouth_corner', 'Mouth corner', 'LipCorner'),
        ('lip_upper_side', 'Upper lip side', 'LipUpper'),
        ('lip_lower_side', 'Lower lip side', 'LipLower'),
        ('cheek', 'Cheek', 'CheekOuter'),
        ('jaw', 'Jaw angle', 'Jawline')):
        for side in ('L', 'R'):
            result.append({'key': key + '_' + side, 'label': label + ' ' + side,
                           'joint': 'FACIAL_' + side + '_' + joint})
    return result


def validate(data):
    if data.get('schema') != SCHEMA or data.get('version') != 1:
        raise ValueError('Expected facial cage landmark data')
    snapshot = data.get('source_snapshot', {})
    count = snapshot.get('vertex_count', 0)
    if not isinstance(count, int) or count <= 0 or not snapshot.get('identity', {}).get('uuid'):
        raise ValueError('Landmarks need a captured source mesh identity')
    if not snapshot.get('topology_sha256') or len(snapshot.get('default_positions_cm', [])) != count:
        raise ValueError('Incomplete landmark source topology or positions')
    for point in snapshot['default_positions_cm']:
        core.point(point)
    used = set()
    for item in data.get('items', []):
        key = item.get('key')
        index = item.get('source_vertex')
        if not isinstance(key, str) or not key or key in used:
            raise ValueError('Landmark names must be nonempty and unique')
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < count:
            raise ValueError('Invalid source vertex for landmark: ' + key)
        used.add(key)
    return data


def empty(snapshot):
    return validate({'schema': SCHEMA, 'version': 1,
                     'source_snapshot': copy.deepcopy(snapshot), 'items': []})


def assign(data, key, vertex, method='manual'):
    validate(data)
    result = copy.deepcopy(data)
    labels = {row['key']: row['label'] for row in presets()}
    item = {'key': key, 'label': labels.get(key, key),
            'source_vertex': vertex, 'method': method}
    result['items'] = [row for row in result['items'] if row['key'] != key] + [item]
    return validate(result)


def reduction_faces(vertex_count, counts, indices, pins=(), pairing=None, rings=0):
    """Exclude every face touching a protected vertex, with symmetric padding."""
    if not isinstance(rings, int) or not 0 <= rings <= 3:
        raise ValueError('Protected rings must be 0..3')
    if sum(counts) != len(indices) or any(n < 3 for n in counts):
        raise ValueError('Invalid source polygon counts')
    if any(not isinstance(i, int) or not 0 <= i < vertex_count for i in indices):
        raise ValueError('Invalid source polygon vertex IDs')
    protected = set(pins)
    if any(not isinstance(i, int) or not 0 <= i < vertex_count for i in protected):
        raise ValueError('Protected vertex is outside the source mesh')
    mirror = {}
    for a, b in (pairing or {}).get('pairs', []):
        mirror[a], mirror[b] = b, a
    faces, offset = [], 0
    for count in counts:
        faces.append(set(indices[offset:offset + count]))
        offset += count
    def reflect():
        protected.update(mirror[i] for i in tuple(protected) if i in mirror)
    reflect()
    for _ in range(rings):
        expanded = set().union(*(face for face in faces if face & protected)) if protected else set()
        protected.update(expanded)
        reflect()
    excluded = [i for i, face in enumerate(faces) if face & protected]
    excluded_set = set(excluded)
    return {'protected_vertices': sorted(protected), 'excluded_faces': excluded,
            'reduce_faces': [i for i in range(len(faces)) if i not in excluded_set]}


def component_ranges(shape, kind, indices):
    """Compress a sorted component list without relying on Maya selection."""
    values = sorted(set(indices))
    result, start, end = [], None, None
    for value in values + [None]:
        if start is not None and value != end + 1:
            result.append(shape + '.' + kind + '[' + str(start) +
                          (':' + str(end) if end != start else '') + ']')
            start = None
        if value is not None:
            if start is None:
                start = value
            end = value
    return result


def decode_source_map(colors, source_points, cage_points, tolerance_cm=.0001):
    """Decode Autodesk's RGB vertex-ID map, then verify exact retained positions."""
    if len(colors) != len(cage_points):
        raise ValueError('Reduction returned an incomplete source vertex map')
    result = []
    for color, point in zip(colors, cage_points):
        if len(color) < 2 or not all(math.isfinite(v) and v >= 0 for v in color[:2]):
            raise ValueError('Reduction returned an unset source vertex map')
        value = color[0] * 65536 + color[1]
        index = int(round(value))
        if abs(value - index) > .01 or not 0 <= index < len(source_points):
            raise ValueError('Reduction returned an invalid source vertex ID')
        if core.distance2(point, source_points[index]) > tolerance_cm ** 2:
            raise ValueError('Reduced cage no longer matches its retained source vertex positions')
        result.append(index)
    if len(set(result)) != len(result):
        raise ValueError('Reduction returned repeated source vertex IDs')
    return result


def map_items(data, source_ids):
    validate(data)
    inverse = {value: index for index, value in enumerate(source_ids)}
    result = copy.deepcopy(data)
    for item in result['items']:
        if item['source_vertex'] not in inverse:
            raise ValueError('Reduction removed protected landmark: ' + item['label'])
        item['cage_vertex'] = inverse[item['source_vertex']]
    return result


def remap_symmetry(pairing, source_ids):
    inverse = {source: cage for cage, source in enumerate(source_ids)}
    pairs = [[inverse[a], inverse[b]] for a, b in pairing['pairs'] if a in inverse and b in inverse]
    seam = [inverse[i] for i in pairing['seam'] if i in inverse]
    assigned = set(seam)
    for pair in pairs:
        assigned.update(pair)
    return {'vertex_count': len(source_ids), 'pairs': pairs, 'seam': seam,
            'unpaired': sorted(set(range(len(source_ids))) - assigned),
            'tolerance_cm': pairing['tolerance_cm']}
