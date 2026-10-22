"""Native sine waves on ordered joints. No plug-in, expressions or callbacks.

Distance math is centimeters and rotation math is radians internally. Offset
and axis phase are explicit degrees; translation settings use scene UI units.
"""
from contextlib import contextmanager
import json
import math
import re
import uuid

import maya.cmds as cmds

TAG = 'rtkWaveJointsVersion'
STATE = 'rtkWaveJointsState'
CHANNELS = {short: (base+axis, amplitude) for short_base, base, amplitude in
            (('t', 'translate', 'translation_amplitude'), ('r', 'rotate', 'rotation_amplitude'))
            for short, axis in ((short_base+a.lower(), a) for a in 'XYZ')}
PARAMS = {
    'offset': ('Offset', 'double', 0., None, None),
    'frequency': ('Frequency', 'double', 1., None, None),
    'envelope': ('Envelope', 'double', 0., 0., 1.),
    'translation_amplitude': ('TranslateAmplitude', 'doubleLinear', 1., None, None),
    'rotation_amplitude': ('RotateAmplitude', 'doubleAngle', 10., None, None),
    'root_weight': ('RootWeight', 'double', 1., 0., 1.),
    'tip_weight': ('TipWeight', 'double', 1., 0., 1.),
    'speed': ('Speed', 'double', 1., None, None),
    'auto_time': ('AutoTime', 'bool', False, None, None),
    'falloff_position': ('FalloffPosition', 'double', .5, 0., 1.),
    'falloff_power': ('FalloffPower', 'double', 0., 0., 1000.),
}
FALLOFF_KEYS = {'falloff_position', 'falloff_power'}
NODE_TYPES = {'multiplyDivide', 'plusMinusAverage', 'sin', 'unitConversion', 'timeToUnitConversion', 'condition', 'clamp'}
LINEAR_CM = {'mm': .1, 'cm': 1., 'm': 100., 'km': 100000., 'in': 2.54,
             'ft': 30.48, 'yd': 91.44, 'mi': 160934.4}


def unique(value, kind=None):
    if not isinstance(value, str) or not value.strip() or '.' in value:
        raise ValueError('Choose a scene object, not a component: '+str(value))
    nodes = list(dict.fromkeys(cmds.ls(value.strip(), long=True, allPaths=True) or []))
    if len(nodes) != 1:
        raise ValueError('Object is missing, ambiguous or instanced: '+value)
    node = nodes[0]
    if kind and cmds.nodeType(node) != kind:
        raise ValueError('Choose a '+kind+': '+node)
    return node


def identity(node):
    values = cmds.ls(node, uuid=True) or []
    if len(values) != 1:
        raise ValueError('Cannot identify object: '+str(node))
    return values[0]


def resolve(value):
    nodes = cmds.ls(value, long=True, allPaths=True) or []
    return nodes[0] if len(nodes) == 1 else None


def _key(plug):
    node, attr = plug.split('.', 1)
    return identity(unique(node)), cmds.attributeName(plug, long=True, leaf=False)


def _inputs(plug):
    return cmds.listConnections(plug, source=True, destination=False, plugs=True,
                                skipConversionNodes=False) or []


def _editable(node):
    if cmds.referenceQuery(node, isNodeReferenced=True) or any(cmds.lockNode(node, query=True, lock=True) or []):
        raise ValueError('Object is locked or referenced: '+node)


def _writable(plug):
    _editable(plug.split('.', 1)[0])
    if cmds.getAttr(plug, lock=True) or _inputs(plug):
        raise ValueError('Channel is locked or already driven: '+plug)


def _finite(value, label):
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(label+' must be a finite number.') from exc
    if not math.isfinite(value):
        raise ValueError(label+' must be a finite number.')
    return value


def _angle_factor():
    return 1. if cmds.currentUnit(query=True, angle=True) in ('rad', 'radian') else math.pi/180.


def _linear_factor():
    unit = cmds.currentUnit(query=True, linear=True)
    if unit not in LINEAR_CM:
        raise ValueError('Unsupported Maya linear unit: '+str(unit))
    return LINEAR_CM[unit]


def _internal(value, channel):
    return float(value)*(_angle_factor() if channel.startswith('r') else _linear_factor())


def _ui_value(value, parameter):
    return math.radians(value)/_angle_factor() if parameter == 'rotation_amplitude' else value


def _settings(values=None):
    values = values or {}
    if set(values)-set(PARAMS):
        raise ValueError('Unknown wave parameter: '+', '.join(sorted(set(values)-set(PARAMS))))
    result = {}
    for key, (_suffix, _kind, default, lo, hi) in PARAMS.items():
        value = values.get(key, default)
        if key == 'auto_time':
            if value not in (False, True, 0, 1):
                raise ValueError('Auto time must be on or off.')
            result[key] = bool(value)
            continue
        value = _finite(value, key)
        if lo is not None and not lo <= value <= hi:
            raise ValueError(key+' must be between '+str(lo)+' and '+str(hi)+'.')
        result[key] = value
    return result


def _channels(channels=None):
    channels = {'ty': {'gain': 1., 'phase': 0.}} if channels is None else channels
    if isinstance(channels, (tuple, list)):
        channels = {key: {} for key in channels}
    if not isinstance(channels, dict) or not channels or set(channels)-set(CHANNELS):
        raise ValueError('Choose one or more outputs: tx, ty, tz, rx, ry, rz.')
    result = {}
    for key in CHANNELS:
        if key in channels:
            value = channels[key]
            if not isinstance(value, dict) or set(value)-{'gain', 'phase'}:
                raise ValueError('Each output has a gain and phase: '+key)
            result[key] = {'gain': _finite(value.get('gain', 1.), key+' gain'),
                           'phase': _finite(value.get('phase', 0.), key+' phase')}
    return result


def _fractions(order, spacing, points):
    if spacing not in ('index', 'distance'):
        raise ValueError('Choose index or distance spacing.')
    if len(order) == 1:
        return [0.]
    if spacing == 'index':
        return [i/(len(order)-1.) for i in range(len(order))]
    distances = [0.]
    for a, b in zip(order, order[1:]):
        distances.append(distances[-1]+math.sqrt(sum((x-y)**2 for x, y in zip(points[a], points[b]))))
    if distances[-1] <= 1e-10:
        raise ValueError('Distance spacing needs separated joint positions.')
    return [value/distances[-1] for value in distances]


def ordered_chain(root):
    """Root-first, direct joint children; never guess the branch to follow."""
    result = [unique(root, 'joint')]
    while True:
        children = cmds.listRelatives(result[-1], children=True, fullPath=True, type='joint') or []
        if len(children) > 1:
            raise ValueError('Joint chain branches at '+result[-1]+'. Use the ordered list to choose joints.')
        if not children:
            return result
        result.append(unique(children[0], 'joint'))


def list_systems():
    return sorted(node for node in cmds.ls(type='network') or []
                  if cmds.attributeQuery(TAG, node=node, exists=True))


def _attribute_specs(prefix, channels, include_falloff=True):
    result = {key: (prefix+spec[0], spec[1]) for key, spec in PARAMS.items()
              if include_falloff or key not in FALLOFF_KEYS}
    for key in channels:
        result[key+'_gain'] = (prefix+key[0].upper()+key[1].upper()+'Gain', 'double')
        result[key+'_phase'] = (prefix+key[0].upper()+key[1].upper()+'Phase', 'double')
    return result


def _time_node():
    nodes = cmds.ls(type='time') or []
    if 'time1' in nodes:
        return 'time1'
    if len(nodes) != 1:
        raise ValueError('Cannot identify the Maya time node for automatic motion.')
    return unique(nodes[0], 'time')


def _time_ui_second():
    from maya.api import OpenMaya as om
    return om.MTime(1., om.MTime.kSeconds).asUnits(om.MTime.uiUnit())


def plan(driver, joints, channels=None, prefix='wave', spacing='index', settings=None):
    """Read-only preflight. Never replaces incoming joint connections."""
    driver = unique(driver)
    if cmds.nodeType(driver) not in ('transform', 'joint'):
        raise ValueError('Driver controller must be a transform or joint.')
    _editable(driver)
    prefix = str(prefix).strip()
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,47}', prefix):
        raise ValueError('Attribute prefix must start with a letter and use letters, digits or underscores (48 max).')
    if not joints or isinstance(joints, str):
        raise ValueError('Load an ordered list of joints.')
    joints = [unique(joint, 'joint') for joint in joints]
    order = [identity(joint) for joint in joints]
    if len(order) != len(set(order)):
        raise ValueError('A joint occurs more than once in the ordered list.')
    channels, values = _channels(channels), _settings(settings)
    if 'sin' not in (cmds.allNodeTypes() or []):
        raise ValueError('waveJoints requires the native sin node (Maya 2024 or newer). No nodes were created.')
    points, records = {}, []
    for joint, uid in zip(joints, order):
        _editable(joint)
        base = {}
        for key, (channel, _amplitude) in CHANNELS.items():
            if key not in channels:
                continue
            _writable(joint+'.'+channel)
            compound = 'rotate' if key.startswith('r') else 'translate'
            if (cmds.getAttr(joint+'.'+compound, lock=True)
                    or cmds.connectionInfo(joint+'.'+compound, isExactDestination=True)):
                raise ValueError('Joint compound is locked or driven: '+joint+'.'+compound)
            base[key] = _internal(_finite(cmds.getAttr(joint+'.'+channel), channel), key)
        point = list(cmds.xform(joint, query=True, worldSpace=True, translation=True))
        if len(point) != 3 or not all(math.isfinite(v) for v in point):
            raise ValueError('Joint has an invalid world position: '+joint)
        points[uid] = point
        records.append({'uuid': uid, 'point': point, 'base': base})
    fractions = _fractions(order, spacing, points)
    specs = _attribute_specs(prefix, channels)
    existing = []
    for key, (attribute, kind) in specs.items():
        if not cmds.attributeQuery(attribute, node=driver, exists=True):
            continue
        plug = driver+'.'+attribute
        if cmds.getAttr(plug, type=True) != kind or cmds.getAttr(plug, lock=True):
            raise ValueError('Existing wave attribute has a different type or is locked: '+plug)
        sources = _inputs(plug)
        if sources and (len(sources) != 1 or cmds.nodeType(sources[0].split('.', 1)[0]) not in
                        ('animCurveTA', 'animCurveTL', 'animCurveTU')):
            raise ValueError('Reused wave attributes may have direct time animation only: '+plug)
        current = cmds.getAttr(plug)
        if not math.isfinite(float(current)):
            raise ValueError('Existing wave attribute has an invalid value: '+plug)
        if key in PARAMS:
            values[key] = bool(current) if key == 'auto_time' else (
                math.degrees(current*_angle_factor()) if key == 'rotation_amplitude' else float(current))
        else:
            axis, parameter = key.split('_', 1)
            channels[axis][parameter] = float(current)
        existing.append(attribute)
    values = _settings(values)
    return {'driver': driver, 'driver_uuid': identity(driver), 'joints': records, 'order': order,
            'channels': channels, 'settings': values, 'prefix': prefix, 'spacing': spacing,
            'fractions': fractions, 'attributes': specs, 'existing_attributes': existing,
            'time': _time_node()}


@contextmanager
def _transaction(label):
    if not cmds.undoInfo(query=True, state=True):
        raise ValueError('Enable Maya Undo before editing a wave setup.')
    name = label+'_'+uuid.uuid4().hex
    try:
        cmds.undoInfo(openChunk=True, chunkName=name)
        try:
            yield
        finally:
            cmds.undoInfo(closeChunk=True)
    except Exception as exc:
        if cmds.undoInfo(query=True, undoName=True) == name:
            cmds.undo()
            raise RuntimeError(label+' was rolled back: '+str(exc)) from exc
        raise


class _Graph:
    def __init__(self, prefix):
        self.prefix, self.members = prefix, {}

    def remember(self, node):
        self.members[identity(node)] = cmds.nodeType(node)
        return node

    def node(self, kind, label):
        return self.remember(cmds.createNode(kind, name=':'+self.prefix+'_'+label+'#', skipSelect=True))

    def connect(self, source, destination, factor=1.):
        cmds.connectAttr(source, destination)
        sources = _inputs(destination)
        if len(sources) != 1:
            raise RuntimeError('Cannot verify connection to '+destination)
        actual, conversion = sources[0], factor
        seen = set()
        while _key(actual) != _key(source):
            node = unique(actual.split('.', 1)[0])
            if cmds.nodeType(node) not in ('unitConversion', 'timeToUnitConversion') or identity(node) in seen:
                raise RuntimeError('Unexpected connection while creating wave: '+destination)
            seen.add(identity(node)); self.remember(node)
            cmds.setAttr(node+'.conversionFactor', conversion)
            conversion = 1.
            upstream = _inputs(node+'.input')
            if len(upstream) != 1:
                raise RuntimeError('Missing conversion input: '+node)
            actual = upstream[0]
        return sources[0]

    def put(self, value, plug):
        if isinstance(value, str):
            self.connect(value, plug)
        else:
            cmds.setAttr(plug, float(value))

    def multiply(self, a, b, label, operation=1):
        node = self.node('multiplyDivide', label)
        cmds.setAttr(node+'.operation', operation)
        if operation == 3:
            for axis in 'YZ':
                cmds.setAttr(node+'.input1'+axis, 0.)
                cmds.setAttr(node+'.input2'+axis, 1.)
        self.put(a, node+'.input1X'); self.put(b, node+'.input2X')
        return node+'.outputX'

    def add(self, a, b, label, subtract=False):
        node = self.node('plusMinusAverage', label)
        cmds.setAttr(node+'.operation', 2 if subtract else 1)
        self.put(a, node+'.input1D[0]'); self.put(b, node+'.input1D[1]')
        return node+'.output1D'

    def greater(self, a, b, when_true, when_false, label):
        node = self.node('condition', label)
        cmds.setAttr(node+'.operation', 2)
        for value, attr in ((a, 'firstTerm'), (b, 'secondTerm'),
                            (when_true, 'colorIfTrueR'), (when_false, 'colorIfFalseR')):
            self.put(value, node+'.'+attr)
        return node+'.outColorR'

    def clamp(self, value, label):
        node = self.node('clamp', label)
        cmds.setAttr(node+'.minR', 0.); cmds.setAttr(node+'.maxR', 1.)
        self.put(value, node+'.inputR')
        return node+'.outputR'


def falloff_weight(position, falloff_position=.5, falloff_power=0.):
    """Reference equation. Higher positive power keeps a wider strong region."""
    values = _settings({'falloff_position': falloff_position, 'falloff_power': falloff_power})
    distance = min(1., abs(_finite(position, 'Joint position')-values['falloff_position']))
    power = values['falloff_power']
    return 1. if power == 0. else 1.-distance**max(.001, power)


def _falloff_exponent(graph, power):
    safe = graph.greater(power, .001, power, .001, 'falloffSafePower')
    return graph.multiply(safe, .5, 'falloffHalfPower')


def _falloff_graph(graph, position, center, power, exponent, label):
    difference = graph.add(position, center, label+'_distance', subtract=True)
    squared = graph.multiply(difference, difference, label+'_distanceSquared')
    squared = graph.clamp(squared, label+'_safeDistance')
    distance_power = graph.multiply(squared, exponent, label+'_power', operation=3)
    weight = graph.add(1., distance_power, label+'_weight', subtract=True)
    # Both branches are defined at distance=0, power=0: the exponent above is
    # always positive. Do not rely on conditional evaluation to hide 0**0.
    return graph.greater(power, 0., weight, 1., label+'_enabled')


def _record_plug(plug):
    node, attribute = _key(plug)
    return {'node': node, 'attribute': attribute}


def build(driver, joints, channels=None, prefix='wave', spacing='index', settings=None):
    info = plan(driver, joints, channels, prefix, spacing, settings)
    label = re.sub(r'[^A-Za-z0-9_]', '_', info['driver'].rsplit('|', 1)[-1])+'_'+info['prefix']
    graph = _Graph(label)
    with _transaction('BuildWaveJoints'):
        meta = cmds.createNode('network', name=':'+label+'_wave_META#', skipSelect=True)
        for attribute in (TAG, STATE):
            cmds.addAttr(meta, longName=attribute, dataType='string')
        cmds.setAttr(meta+'.'+TAG, '1', type='string')
        for attribute in ('driver',):
            cmds.addAttr(meta, longName=attribute, attributeType='message')
        for attribute in ('joints', 'members'):
            cmds.addAttr(meta, longName=attribute, attributeType='message', multi=True)
        cmds.addAttr(meta, longName='positions', attributeType='double', multi=True)
        cmds.connectAttr(info['driver']+'.message', meta+'.driver')
        plugs, created = {}, []
        for key, (attribute, kind) in info['attributes'].items():
            plugs[key] = info['driver']+'.'+attribute
            if attribute in info['existing_attributes']:
                continue
            value = info['settings'][key] if key in PARAMS else info['channels'][key.split('_')[0]][key.split('_')[1]]
            kwargs = {'longName': attribute, 'attributeType': kind, 'keyable': True,
                      'defaultValue': _ui_value(value, key)}
            if key in PARAMS and PARAMS[key][3] is not None:
                kwargs.update(minValue=PARAMS[key][3], maxValue=PARAMS[key][4])
            cmds.addAttr(info['driver'], **kwargs)
            cmds.setAttr(plugs[key], _ui_value(value, key))
            created.append(attribute)
        clock = graph.node('timeToUnitConversion', 'seconds')
        # Calibrate one second on the unconnected native time plug. This avoids
        # assumptions about its internal numeric time representation and never
        # moves the user's timeline or changes scene frame-rate preferences.
        cmds.setAttr(clock+'.input', _time_ui_second())
        cmds.setAttr(clock+'.conversionFactor', 1.)
        second = _finite(cmds.getAttr(clock+'.output'), 'Native time conversion')
        if second <= 0.:
            raise RuntimeError('Cannot calibrate the native time conversion.')
        graph.connect(info['time']+'.outTime', clock+'.input')
        cmds.setAttr(clock+'.conversionFactor', 1./second)
        motion = graph.multiply(clock+'.output', plugs['speed'], 'timeCycles')
        motion = graph.multiply(motion, plugs['auto_time'], 'autoTime')
        motion = graph.multiply(motion, 360., 'timeDegrees')
        phase = graph.add(plugs['offset'], motion, 'phase')
        frequency = graph.multiply(plugs['frequency'], 360., 'frequencyDegrees')
        taper_delta = graph.add(plugs['tip_weight'], plugs['root_weight'], 'taperDelta', subtract=True)
        exponent = _falloff_exponent(graph, plugs['falloff_power'])
        amplitudes = {key: graph.multiply(plugs[CHANNELS[key][1]], plugs[key+'_gain'], key+'_amplitude')
                      for key in info['channels']}
        for index, row in enumerate(info['joints']):
            joint = unique(row['uuid'], 'joint')
            position = meta+'.positions[{}]'.format(index)
            cmds.setAttr(position, info['fractions'][index])
            cmds.connectAttr(joint+'.message', meta+'.joints[{}]'.format(index))
            row['position_index'] = index
            falloff = _falloff_graph(graph, position, plugs['falloff_position'], plugs['falloff_power'], exponent,
                                     'j{}_falloff'.format(index+1))
            row['falloff'] = _record_plug(falloff)
            spatial = graph.multiply(frequency, position, 'j{}_spacing'.format(index+1))
            joint_phase = graph.add(phase, spatial, 'j{}_phase'.format(index+1))
            taper = graph.add(plugs['root_weight'], graph.multiply(taper_delta, position, 'j{}_taperDelta'.format(index+1)),
                              'j{}_taper'.format(index+1))
            weight = graph.multiply(plugs['envelope'], taper, 'j{}_envelope'.format(index+1))
            row['inputs'] = {}
            for key in info['channels']:
                axis_phase = graph.add(joint_phase, plugs[key+'_phase'], 'j{}_{}_phase'.format(index+1, key))
                sine = graph.node('sin', 'j{}_{}_sin'.format(index+1, key))
                radians = graph.node('unitConversion', 'j{}_{}_radians'.format(index+1, key))
                graph.connect(axis_phase, radians+'.input')
                graph.connect(radians+'.output', sine+'.input')
                cmds.setAttr(radians+'.conversionFactor', math.pi/180.)
                wave = graph.multiply(sine+'.output', weight, 'j{}_{}_weight'.format(index+1, key))
                delta = graph.multiply(wave, amplitudes[key], 'j{}_{}_delta'.format(index+1, key))
                delta = graph.multiply(delta, falloff, 'j{}_{}_falloff'.format(index+1, key))
                output = graph.add(row['base'][key], delta, 'j{}_{}_local'.format(index+1, key))
                actual = graph.connect(output, joint+'.'+CHANNELS[key][0])
                source, attribute = _key(actual)
                row['inputs'][key] = {'node': source, 'attribute': attribute}
        state = {key: info[key] for key in ('driver_uuid', 'joints', 'order', 'channels', 'prefix', 'spacing')}
        state.update(schema=1, falloff_version=1, meta=identity(meta), attributes={k: v[0] for k, v in info['attributes'].items()},
                     created_attributes=created, members=[{'uuid': key, 'type': kind} for key, kind in graph.members.items()])
        for index, row in enumerate(state['members']):
            cmds.connectAttr(unique(row['uuid'])+'.message', meta+'.members[{}]'.format(index))
        cmds.setAttr(meta+'.'+STATE, json.dumps(state), type='string')
        read(meta)
        for row in state['joints']:
            for key in state['channels']:
                _finite(cmds.getAttr(unique(row['uuid'])+'.'+CHANNELS[key][0]), 'Wave output')
    return {'system': meta, 'driver': info['driver'], 'joint_count': len(info['joints']),
            'node_count': len(graph.members)+1, 'reused_attributes': info['existing_attributes']}


def read(system, allow_missing=False):
    meta = unique(system, 'network')
    try:
        if cmds.getAttr(meta+'.'+TAG) != '1':
            raise ValueError('Unknown ownership version')
        data = json.loads(cmds.getAttr(meta+'.'+STATE))
        if data['schema'] != 1 or data['meta'] != identity(meta):
            raise ValueError('Metadata identity changed')
        ids = [row['uuid'] for row in data['joints']]
        owned = [row['uuid'] for row in data['members']]
        if (not ids or len(ids) != len(set(ids)) or set(data['order']) != set(ids)
                or len(data['order']) != len(ids) or len(owned) != len(set(owned))
                or data['driver_uuid'] in owned or set(ids).intersection(owned) or data['meta'] in owned):
            raise ValueError('Ownership list changed')
        channels = _channels(data['channels'])
        if data.get('falloff_version') not in (None, 1):
            raise ValueError('Unknown falloff graph version')
        specs = _attribute_specs(data['prefix'], channels, include_falloff=bool(data.get('falloff_version')))
        if data['attributes'] != {key: value[0] for key, value in specs.items()}:
            raise ValueError('Driver attribute records changed')
        if not set(data['created_attributes']).issubset(data['attributes'].values()):
            raise ValueError('Created attribute records changed')
        driver = resolve(data['driver_uuid'])
        if driver:
            if [identity(unique(p.split('.', 1)[0])) for p in _inputs(meta+'.driver')] != [data['driver_uuid']]:
                raise ValueError('Driver link changed')
            for attribute, kind in specs.values():
                if allow_missing and not cmds.objExists(driver+'.'+attribute):
                    continue
                if not cmds.objExists(driver+'.'+attribute) or cmds.getAttr(driver+'.'+attribute, type=True) != kind:
                    raise ValueError('Driver attribute is missing or has changed type')
        elif not allow_missing:
            raise ValueError('Driver is missing')
        for index, row in enumerate(data['members']):
            member = resolve(row['uuid'])
            if row['type'] not in NODE_TYPES or (not member and not allow_missing):
                raise ValueError('Wave node is missing or has an invalid type')
            if member and (cmds.nodeType(member) != row['type'] or
                           [identity(unique(p.split('.', 1)[0])) for p in _inputs(meta+'.members[{}]'.format(index))] != [row['uuid']]):
                raise ValueError('Member ownership link changed')
        positions = []
        kinds = {member['uuid']: member['type'] for member in data['members']}
        for index, row in enumerate(data['joints']):
            positions.append(row['position_index'])
            if (set(row['base']) != set(channels) or set(row['inputs']) != set(channels)
                    or len(row['point']) != 3 or not all(math.isfinite(float(v)) for v in row['point']+list(row['base'].values()))
                    or any(item['node'] not in owned for item in row['inputs'].values())):
                raise ValueError('Joint output records changed')
            if data.get('falloff_version'):
                weight = row['falloff']
                if kinds.get(weight['node']) != 'condition' or weight['attribute'] != 'outColorR':
                    raise ValueError('Falloff ownership record changed')
            joint = resolve(row['uuid'])
            if joint and (cmds.nodeType(joint) != 'joint' or
                          [identity(unique(p.split('.', 1)[0])) for p in _inputs(meta+'.joints[{}]'.format(index))] != [row['uuid']]):
                raise ValueError('Source joint link changed')
            if not joint and not allow_missing:
                raise ValueError('Source joint is missing')
        if sorted(positions) != list(range(len(ids))):
            raise ValueError('Position indices changed')
        _fractions(data['order'], data['spacing'], {row['uuid']: row['point'] for row in data['joints']})
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise ValueError('Wave metadata is incomplete or changed: '+str(exc)) from exc
    return meta, data


def current_settings(system):
    meta, state = read(system)
    driver = unique(state['driver_uuid'])
    values, channels = {}, {}
    for key in PARAMS:
        if key not in state['attributes']:
            values[key] = PARAMS[key][2]
            continue
        value = cmds.getAttr(driver+'.'+state['attributes'][key])
        if key == 'rotation_amplitude':
            value = math.degrees(value*_angle_factor())
        values[key] = bool(value) if key == 'auto_time' else float(value)
    for key in state['channels']:
        channels[key] = {parameter: cmds.getAttr(driver+'.'+state['attributes'][key+'_'+parameter])
                         for parameter in ('gain', 'phase')}
    return {'system': meta, 'driver': driver, 'prefix': state['prefix'], 'settings': values,
            'channels': channels, 'spacing': state['spacing'], 'joints': [unique(i) for i in state['order']],
            'falloff_available': bool(state.get('falloff_version'))}


def _falloff_upgrade_plan(meta, state):
    """Inspect a saved 2.38 graph without changing nodes or source channels."""
    driver = unique(state['driver_uuid']); _editable(driver)
    owned = {row['uuid'] for row in state['members']}
    result = {'new_attributes': {}, 'values': {}, 'outputs': {}}
    for key in FALLOFF_KEYS:
        suffix, kind, default, _lo, _hi = PARAMS[key]
        attribute = state['prefix']+suffix; plug = driver+'.'+attribute
        if not cmds.objExists(plug):
            result['new_attributes'][key] = attribute; result['values'][key] = default
            continue
        if cmds.getAttr(plug, type=True) != kind or cmds.getAttr(plug, lock=True):
            raise ValueError('Existing falloff attribute has a different type or is locked: '+plug)
        sources = _inputs(plug)
        if sources and (len(sources) != 1 or cmds.nodeType(sources[0].split('.', 1)[0]) != 'animCurveTU'):
            raise ValueError('Reused falloff attributes may have direct time animation only: '+plug)
        result['values'][key] = _finite(cmds.getAttr(plug), plug)
    _settings(result['values'])
    for row in state['joints']:
        joint = unique(row['uuid'], 'joint')
        for channel in state['channels']:
            expected = row['inputs'][channel]
            inputs = _inputs(joint+'.'+CHANNELS[channel][0])
            if len(inputs) != 1 or _key(inputs[0]) != (expected['node'], expected['attribute']):
                raise ValueError('Joint output changed; falloff upgrade stopped: '+joint+'.'+CHANNELS[channel][0])
            source = inputs[0]; seen = set()
            while True:
                node = unique(source.split('.', 1)[0]); uid = identity(node)
                if uid not in owned or uid in seen:
                    raise ValueError('Cannot verify the saved wave output: '+source)
                seen.add(uid)
                if cmds.nodeType(node) != 'unitConversion':
                    break
                upstream = _inputs(node+'.input')
                if len(upstream) != 1:
                    raise ValueError('The saved wave conversion input changed: '+node)
                source = upstream[0]
            if cmds.nodeType(node) != 'plusMinusAverage' or _key(source)[1] != 'output1D' or cmds.getAttr(node+'.operation') != 1:
                raise ValueError('Cannot find the original local-value sum: '+source)
            _editable(node)
            destination = node+'.input1D[1]'
            upstream = _inputs(destination)
            if cmds.getAttr(destination, lock=True) or len(upstream) != 1 or _key(upstream[0])[0] not in owned:
                raise ValueError('The saved wave contribution is locked or changed: '+destination)
            base = cmds.getAttr(node+'.input1D[0]')
            if _inputs(node+'.input1D[0]') or abs(base-row['base'][channel]) > 3e-5*max(1., abs(base), abs(row['base'][channel])):
                raise ValueError('The saved local base value changed: '+node)
            result['outputs'][(row['uuid'], channel)] = (upstream[0], destination)
    return result


def _install_falloff(meta, state, upgrade):
    driver = unique(state['driver_uuid'])
    label = re.sub(r'[^A-Za-z0-9_]', '_', driver.rsplit('|', 1)[-1])+'_'+state['prefix']
    graph = _Graph(label)
    for key in sorted(FALLOFF_KEYS):
        suffix, kind, default, lo, hi = PARAMS[key]
        attribute = state['prefix']+suffix
        if key in upgrade['new_attributes']:
            cmds.addAttr(driver, longName=attribute, attributeType=kind, keyable=True,
                         defaultValue=default, minValue=lo, maxValue=hi)
            cmds.setAttr(driver+'.'+attribute, default)
            state['created_attributes'].append(attribute)
        state['attributes'][key] = attribute
    power = driver+'.'+state['attributes']['falloff_power']
    center = driver+'.'+state['attributes']['falloff_position']
    exponent = _falloff_exponent(graph, power)
    for index, row in enumerate(state['joints']):
        weight = _falloff_graph(graph, meta+'.positions[{}]'.format(row['position_index']),
                                center, power, exponent, 'j{}_falloff'.format(index+1))
        row['falloff'] = _record_plug(weight)
        for channel in state['channels']:
            source, destination = upgrade['outputs'][(row['uuid'], channel)]
            weighted = graph.multiply(source, weight, 'j{}_{}_falloff'.format(index+1, channel))
            cmds.disconnectAttr(source, destination)
            graph.connect(weighted, destination)
    for uid, kind in graph.members.items():
        index = len(state['members'])
        state['members'].append({'uuid': uid, 'type': kind})
        cmds.connectAttr(unique(uid)+'.message', meta+'.members[{}]'.format(index))
    state['falloff_version'] = 1


def update(system, joints=None, channels=None, spacing=None, settings=None):
    meta, state = read(system)
    live = current_settings(meta)
    upgrade = _falloff_upgrade_plan(meta, state) if not state.get('falloff_version') else None
    if upgrade:
        live['settings'].update(upgrade['values'])
    values = _settings(dict(live['settings'], **(settings or {})))
    channels = _channels(live['channels'] if channels is None else channels)
    if set(channels) != set(state['channels']):
        raise ValueError('Changing output channels needs a new setup. Delete this setup and build again.')
    joints = live['joints'] if joints is None else joints
    order = [identity(unique(joint, 'joint')) for joint in joints]
    if len(order) != len(state['order']) or set(order) != set(state['order']):
        raise ValueError('Updating order requires the same joints, each once. Rebuild to change the joint list.')
    spacing = state['spacing'] if spacing is None else spacing
    fractions = dict(zip(order, _fractions(order, spacing, {row['uuid']: row['point'] for row in state['joints']})))
    driver = unique(state['driver_uuid'])
    writes = []
    attributes = dict(state['attributes'])
    if upgrade:
        attributes.update({key: state['prefix']+PARAMS[key][0] for key in FALLOFF_KEYS})
    for key, attribute in attributes.items():
        value = values[key] if key in PARAMS else channels[key.split('_')[0]][key.split('_')[1]]
        value = _ui_value(value, key)
        plug = driver+'.'+attribute
        if upgrade and key in upgrade['new_attributes']:
            writes.append((plug, value))
        elif abs(float(cmds.getAttr(plug))-value) > 1e-10:
            _writable(plug); writes.append((plug, value))
    _editable(meta); _writable(meta+'.'+STATE)
    for row in state['joints']:
        plug = meta+'.positions[{}]'.format(row['position_index'])
        _writable(plug); writes.append((plug, fractions[row['uuid']]))
    with _transaction('UpdateWaveJoints'):
        if upgrade:
            _install_falloff(meta, state, upgrade)
        for plug, value in writes:
            cmds.setAttr(plug, value)
        state.update(order=order, spacing=spacing, channels=channels)
        cmds.setAttr(meta+'.'+STATE, json.dumps(state), type='string')
        read(meta)
    return current_settings(meta)


def remove(system, remove_unused_attributes=True):
    """Keep this frame's local channels/world pose; preserve animated/SDK attrs."""
    meta, state = read(system, allow_missing=True)
    owned = {row['uuid'] for row in state['members']} | {state['meta']}
    snapshots, allowed = [], set()
    for row in state['joints']:
        joint = resolve(row['uuid'])
        if not joint:
            continue
        _editable(joint)
        values = {}
        for key in state['channels']:
            plug = joint+'.'+CHANNELS[key][0]
            if cmds.getAttr(plug, lock=True) or cmds.getAttr(joint+'.'+('rotate' if key.startswith('r') else 'translate'), lock=True):
                raise ValueError('Unlock the joint channel before removing wave: '+plug)
            if any(identity(unique(p.split('.', 1)[0])) not in owned for p in _inputs(plug)):
                raise ValueError('Joint channel now has another driver: '+plug)
            values[plug] = _finite(cmds.getAttr(plug), plug)
            allowed.add(_key(plug))
        snapshots.append({'uuid': row['uuid'], 'values': values,
                          'world': cmds.xform(joint, query=True, worldSpace=True, matrix=True),
                          'jointOrient': cmds.getAttr(joint+'.jointOrient'), 'rotateAxis': cmds.getAttr(joint+'.rotateAxis')})
    for uid in owned:
        node = resolve(uid)
        if not node:
            continue
        _editable(node)
        for plug in cmds.listConnections(node, source=False, destination=True, plugs=True, skipConversionNodes=False) or []:
            if identity(unique(plug.split('.', 1)[0])) not in owned and _key(plug) not in allowed:
                raise ValueError('Another system uses wave output: '+plug+'. Disconnect it before removal.')
    driver = resolve(state['driver_uuid'])
    removed, retained = [], []
    with _transaction('RemoveWaveJoints'):
        nodes = [resolve(uid) for uid in owned if uid != state['meta']]
        nodes = [node for node in nodes if node]
        if nodes:
            cmds.delete(nodes)
        for snapshot in snapshots:
            for plug, value in snapshot['values'].items():
                cmds.setAttr(plug, value)
        if driver:
            for attribute in state['created_attributes']:
                plug = driver+'.'+attribute
                if not cmds.objExists(plug):
                    continue
                connected = _inputs(plug) or (cmds.listConnections(plug, source=False, destination=True, plugs=True) or [])
                protected = (cmds.referenceQuery(driver, isNodeReferenced=True) or any(cmds.lockNode(driver, query=True, lock=True) or [])
                             or cmds.getAttr(plug, lock=True))
                if remove_unused_attributes and not connected and not protected:
                    cmds.deleteAttr(plug); removed.append(attribute)
                else:
                    retained.append(attribute)
        cmds.delete(meta)
        if driver:
            retained = [attribute for attribute in state['attributes'].values() if cmds.objExists(driver+'.'+attribute)]
        for snapshot in snapshots:
            joint = unique(snapshot['uuid'], 'joint')
            matrix = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
            if any(abs(a-b) > 2e-5*max(1., abs(a), abs(b)) for a, b in zip(matrix, snapshot['world'])):
                raise RuntimeError('Joint pose changed on removal: '+joint)
            if (cmds.getAttr(joint+'.jointOrient') != snapshot['jointOrient'] or
                    cmds.getAttr(joint+'.rotateAxis') != snapshot['rotateAxis']):
                raise RuntimeError('Joint orientation definition changed: '+joint)
    return {'joint_count': len(snapshots), 'removed_attributes': removed, 'retained_attributes': retained}
