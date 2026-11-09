"""Dependency-free reader for the known DNA 2.5 behavior layers used by this rig.

The section layout was checked against Epic Games OpenRigLogic 5.8. Geometry
is intentionally not decoded. Unsupported versions are rejected explicitly.
"""
from pathlib import Path
import struct


class Reader:
    def __init__(self, data, offset=0, end=None):
        self.data, self.pos, self.end = data, offset, len(data) if end is None else end

    def take(self, fmt):
        size = struct.calcsize('>' + fmt)
        if self.pos + size > self.end:
            raise ValueError('DNA section overrun')
        values = struct.unpack_from('>' + fmt, self.data, self.pos)
        self.pos += size
        return values[0] if len(values) == 1 else values

    def u16(self): return self.take('H')
    def u32(self): return self.take('I')
    def f32(self): return self.take('f')

    def array(self, fmt):
        count = self.u32()
        size = struct.calcsize('>' + fmt) * count
        if self.pos + size > self.end:
            raise ValueError('Invalid DNA array size')
        values = list(struct.unpack_from('>' + str(count) + fmt, self.data, self.pos))
        self.pos += size
        return values

    def text(self):
        count = self.u32()
        if self.pos + count > self.end:
            raise ValueError('Invalid DNA string size')
        value = self.data[self.pos:self.pos + count].decode('utf-8')
        self.pos += count
        return value

    def vector(self, read): return [read() for _ in range(self.u32())]

    def lod_mapping(self):
        return {'lods': self.array('H'), 'indices': self.vector(lambda: self.array('H'))}

    def xyz(self): return {axis: self.array('f') for axis in ['xs', 'ys', 'zs']}

    def conditional(self):
        return {name: self.array(fmt) for name, fmt in [
            ('inputIndices', 'H'), ('outputIndices', 'H'), ('fromValues', 'f'),
            ('toValues', 'f'), ('slopeValues', 'f'), ('cutValues', 'f')]}

    def group(self):
        return {name: self.array(fmt) for name, fmt in [
            ('lods', 'H'), ('inputIndices', 'H'), ('outputIndices', 'H'),
            ('values', 'f'), ('jointIndices', 'H')]}

    def solver(self):
        size = self.u32()
        start = self.pos
        result = {'size': size, 'name': self.text(), 'rawControlIndices': self.array('H'),
                  'poseIndices': self.array('H'), 'rawControlValues': self.array('f'),
                  'radius': self.f32(), 'weightThreshold': self.f32()}
        for key in ['solverType', 'automaticRadius', 'distanceMethod', 'normalizeMethod', 'functionType', 'twistAxis']:
            result[key] = self.u16()
        if self.pos != start + size:
            raise ValueError('Unsupported RBF solver storage')
        return result

    def complete(self):
        if self.pos != self.end:
            raise ValueError(f'DNA section consumed {self.pos}, expected {self.end}')


def load(path):
    data = Path(path).read_bytes()
    if data[:3] != b'DNA':
        raise ValueError('Not a DNA file')
    root = Reader(data, 3)
    version = (root.u16(), root.u16())
    if version != (2, 5):
        raise ValueError(f'This reader supports DNA 2.5, found {version}')
    layers = {}
    for _ in range(root.u32()):
        tag = root.take('4s').decode('ascii')
        major, minor, offset, size = root.u16(), root.u16(), root.u32(), root.u32()
        if offset + size > len(data):
            raise ValueError('Layer outside file')
        layers[tag] = {'version': [major, minor], 'offset': offset, 'size': size}
    def layer(tag, expected):
        item = layers[tag]
        if item['version'] != expected:
            raise ValueError(f'Unsupported {tag} layer version {item["version"]}')
        return Reader(data, item['offset'], item['offset'] + item['size'])

    r = layer('desc', [1, 1])
    desc = {'name': r.text(), 'archetype': r.u16(), 'gender': r.u16(), 'age': r.u16(),
            'metadata': r.vector(lambda: [r.text(), r.text()]), 'translationUnit': r.u16(),
            'rotationUnit': r.u16(),
            'coordinateSystem': {k: r.u16() for k in ['xAxis', 'yAxis', 'zAxis']},
            'lodCount': r.u16(), 'maxLOD': r.u16(), 'complexity': r.text(), 'dbName': r.text()}
    r.complete()
    r = layer('defn', [1, 1])
    definition = {k: r.lod_mapping() for k in ['lodJointMapping', 'lodBlendShapeMapping', 'lodAnimatedMapMapping', 'lodMeshMapping']}
    for key in ['guiControlNames', 'rawControlNames', 'jointNames', 'blendShapeChannelNames', 'animatedMapNames', 'meshNames']:
        definition[key] = r.vector(r.text)
    definition['meshBlendShapeChannelMapping'] = {'from': r.array('H'), 'to': r.array('H')}
    definition['jointHierarchy'] = r.array('H')
    definition['neutralJointTranslations'], definition['neutralJointRotations'] = r.xyz(), r.xyz()
    r.complete()
    r = layer('bhvr', [1, 1])
    controls = {'psdCount': r.u16(), 'conditionals': r.conditional(),
                'psds': {'rows': r.array('H'), 'columns': r.array('H'), 'values': r.array('f')}}
    joints = {'rowCount': r.u16(), 'colCount': r.u16(), 'jointGroups': r.vector(r.group)}
    blends = {k: r.array('H') for k in ['lods', 'inputIndices', 'outputIndices']}
    maps = {'lods': r.array('H'), 'conditionals': r.conditional()}
    r.complete()
    r = layer('rbfb', [1, 0])
    rbf = {'lodSolverMapping': r.lod_mapping(), 'solvers': r.vector(r.solver),
           'poses': r.vector(lambda: {'name': r.text(), 'scale': r.f32()})}
    r.complete()
    r = layer('rbfe', [1, 0])
    rbf_ext = {'poseControlNames': r.vector(r.text), 'poses': r.vector(lambda: {
        'inputControlIndices': r.array('H'), 'outputControlIndices': r.array('H'),
        'outputControlWeights': r.array('f')})}
    r.complete()
    r = layer('jbmd', [1, 0])
    metadata = {'jointRepresentations': r.vector(lambda: {
        'translation': r.u16(), 'rotation': r.u16(), 'scale': r.u16()})}
    r.complete()
    # These known layers are empty in the supplied reference. Reject nonempty
    # behavior instead of dropping a learned or twist/swing dependency.
    r = layer('mlbh', [1, 0])
    ml = {'mlControlNames': r.vector(r.text), 'lodNeuralNetworkMapping': r.lod_mapping(),
          'neuralNetworkToMeshRegion': {'regionNames': r.vector(lambda: r.vector(r.text)),
                                       'indices': r.vector(lambda: r.vector(lambda: r.array('H')))},
          'neuralNetworks': r.vector(lambda: (_ for _ in ()).throw(ValueError('Learned networks are not supported')))}
    r.complete()
    r = layer('twsw', [1, 0])
    if r.u32() != 0 or r.u32() != 0:
        raise ValueError('Twist/swing behavior requires an explicit implementation')
    r.complete()
    return {'version': list(version), 'layers': layers, 'descriptor': desc, 'definition': definition,
            'behavior': {'controls': controls, 'joints': joints, 'blendShapeChannels': blends, 'animatedMaps': maps},
            'rbf': rbf, 'rbf_ext': rbf_ext, 'joint_metadata': metadata, 'ml': ml}
