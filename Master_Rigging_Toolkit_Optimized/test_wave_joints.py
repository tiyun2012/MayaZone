"""Native-node graph evaluation with typed plug units; not a Maya solver."""
import ast
import copy
import math
from pathlib import Path
import types
import unittest


class WaveCommands:
    def __init__(self, legacy_sine=True):
        self.nodes, self.edges, self.selection, self.warnings = {}, {}, [], []
        self.serial = 0; self.legacy_sine = legacy_sine
        self.units = {'linear': 'cm', 'angle': 'deg', 'time': 'film'}
        self.seconds = 0.; self.tracked = False; self.enabled = True
        self.native_time_scale = 1.
        self.open = None; self.history = []; self.future = []
        self.fail_on = None; self.available = ['sin']
        self.driver = self.add('|wave_ctrl', 'transform')
        first = self.add('|first_L', 'joint')
        second = self.add(first+'|second_L', 'joint', first)
        third = self.add(second+'|third_L', 'joint', second)
        self.joints = [first, second, third]
        self.setAttr(second+'.translateX', 2.)
        self.setAttr(third+'.translateX', 6.)
        self.add('time1', 'time')

    def add(self, name, kind='network', parent=None):
        self.serial += 1
        self.nodes[name] = {'uuid': 'wave-u'+str(self.serial), 'type': kind, 'attrs': {},
                            'kinds': {'message': 'message'}, 'locked': set(), 'node_lock': False,
                            'ref': False, 'parent': parent, 'instanced': False}
        if kind in ('transform', 'joint'):
            for base in ('translate', 'rotate', 'scale', 'jointOrient', 'rotateAxis'):
                self.nodes[name]['kinds'][base] = 'double3'
                for axis in 'XYZ':
                    attr = base+axis
                    self.nodes[name]['attrs'][attr] = 1. if base == 'scale' else 0.
                    self.nodes[name]['kinds'][attr] = 'doubleAngle' if base in ('rotate', 'jointOrient', 'rotateAxis') else 'doubleLinear' if base == 'translate' else 'double'
        return name

    def kind(self, plug):
        node, attr = plug.split('.', 1)
        data = self.nodes[node]
        if data['type'] == 'unitConversion' and attr in ('input', 'output'):
            return 'generic'
        if data['type'] == 'timeToUnitConversion' and attr == 'input' or data['type'] == 'time' and attr == 'outTime':
            return 'time'
        if data['type'] == 'sin' and attr == 'input':
            return 'doubleAngle'
        if data['type'] == 'sin' and attr == 'output' and self.legacy_sine:
            return 'doubleLinear'
        return data['kinds'].get(attr.split('[')[0], 'double')

    def factor(self, kind):
        if kind == 'doubleAngle':
            return math.pi/180. if self.units['angle'] == 'deg' else 1.
        if kind == 'doubleLinear':
            return {'cm': 1., 'm': 100., 'mm': .1}[self.units['linear']]
        if kind == 'time':
            return 1./self.ui_fps()
        return 1.

    def ui_fps(self):
        return {'film': 24., 'ntsc': 30., '60fps': 60.}[self.units['time']]

    def ls(self, value=None, **kw):
        if kw.get('selection') or kw.get('orderedSelection'):
            found = self.selection[:]
        elif value is None:
            found = list(self.nodes)
        else:
            values = value if isinstance(value, (list, tuple)) else [value]
            found = list(dict.fromkeys(n for v in values for n, d in self.nodes.items()
                                      if v in (n, d['uuid'], n.rsplit('|', 1)[-1])))
        if kw.get('type'):
            found = [n for n in found if self.nodes[n]['type'] == kw['type']]
        if kw.get('uuid'):
            return [self.nodes[n]['uuid'] for n in found]
        if kw.get('allPaths') and any(self.nodes[n]['instanced'] for n in found):
            return found+['|instancePath']
        return found

    def nodeType(self, node):
        return self.nodes[node]['type']

    def allNodeTypes(self):
        return self.available[:]

    def objExists(self, value):
        if '.' not in value:
            return value in self.nodes
        node, attr = value.split('.', 1)
        return node in self.nodes and (attr in self.nodes[node]['attrs'] or attr.split('[')[0] in self.nodes[node]['kinds'])

    def referenceQuery(self, node, **kw):
        return self.nodes[node]['ref']

    def lockNode(self, node, **kw):
        return [self.nodes[node]['node_lock']]

    def attributeQuery(self, attribute, node, **kw):
        return attribute in self.nodes[node]['kinds']

    def attributeName(self, plug, **kw):
        return plug.split('.', 1)[1]

    def connectionInfo(self, plug, **kw):
        return plug in self.edges

    def _matches(self, plug, query):
        if '.' not in query:
            return plug.split('.', 1)[0] == query
        return plug == query or (query.endswith(('.translate', '.rotate')) and plug in [query+a for a in 'XYZ'])

    def listConnections(self, query, **kw):
        pairs = []
        if kw.get('source'):
            pairs += [(dst, src) for dst, src in self.edges.items() if self._matches(dst, query)]
        if kw.get('destination'):
            pairs += [(src, dst) for dst, src in self.edges.items() if self._matches(src, query)]
        if kw.get('connections'):
            return [p for pair in pairs for p in pair]
        values = [p[1] if kw.get('plugs') else p[1].split('.', 1)[0] for p in pairs]
        return list(dict.fromkeys(values))

    def _value(self, plug, stack=None):
        stack = set() if stack is None else stack.copy()
        if plug in stack:
            raise RuntimeError('Dependency cycle: '+plug)
        stack.add(plug)
        if plug in self.edges:
            return self._value(self.edges[plug], stack)
        node, attr = plug.split('.', 1)
        data = self.nodes[node]; kind = data['type']
        get = lambda a: self._value(node+'.'+a, stack)
        if kind == 'multiplyDivide' and attr == 'outputX':
            if get('operation') == 3:
                a, b = get('input1X'), get('input2X')
                if a == 0. and b <= 0.:
                    raise RuntimeError('Undefined zero-base exponent')
                return a**b
            return get('input1X')*get('input2X')
        if kind == 'condition' and attr == 'outColorR':
            return get('colorIfTrueR') if get('firstTerm') > get('secondTerm') else get('colorIfFalseR')
        if kind == 'clamp' and attr == 'outputR':
            return min(get('maxR'), max(get('minR'), get('inputR')))
        if kind == 'plusMinusAverage' and attr == 'output1D':
            return get('input1D[0]')+(-1 if get('operation') == 2 else 1)*get('input1D[1]')
        if kind in ('unitConversion', 'timeToUnitConversion') and attr == 'output':
            return get('input')*get('conversionFactor')*(self.native_time_scale if kind == 'timeToUnitConversion' else 1.)
        if kind == 'sin' and attr == 'output':
            return math.sin(get('input'))
        if kind == 'time' and attr == 'outTime':
            return self.seconds
        if attr in ('translate', 'rotate', 'scale', 'jointOrient', 'rotateAxis') and kind in ('joint', 'transform'):
            return [get(attr+a) for a in 'XYZ']
        return data['attrs'].get(attr, 1. if attr == 'conversionFactor' else 0.)

    def getAttr(self, plug, **kw):
        node, attr = plug.split('.', 1)
        if kw.get('type'):
            return self.kind(plug)
        if kw.get('lock'):
            return attr in self.nodes[node]['locked']
        value = self._value(plug)
        if isinstance(value, list):
            return [tuple(v/self.factor(self.kind(plug+a)) for v, a in zip(value, 'XYZ'))]
        return value/self.factor(self.kind(plug)) if isinstance(value, (int, float)) else value

    def setAttr(self, plug, *values, **kw):
        if self.fail_on == plug:
            raise RuntimeError('Injected write failure')
        node, attr = plug.split('.', 1)
        if 'lock' in kw:
            self.nodes[node]['locked'].add(attr) if kw['lock'] else self.nodes[node]['locked'].discard(attr)
        if kw.get('type') == 'double3':
            for axis, value in zip('XYZ', values):
                self.setAttr(plug+axis, value)
        elif values:
            value = values[0]
            self.nodes[node]['attrs'][attr] = value*self.factor(self.kind(plug)) if isinstance(value, (int, float)) else value

    def addAttr(self, node, **kw):
        attribute = kw['longName']; kind = kw.get('attributeType', kw.get('dataType'))
        self.nodes[node]['kinds'][attribute] = kind
        if not kw.get('multi'):
            self.setAttr(node+'.'+attribute, kw.get('defaultValue', '' if kind == 'string' else 0.))

    def createNode(self, kind, name, **kw):
        name = name.lstrip(':').replace('#', str(self.serial+1))
        while name in self.nodes:
            name += '1'
        return self.add(name, kind)

    def connectAttr(self, source, destination, **kw):
        if self.fail_on == destination:
            raise RuntimeError('Injected connection failure')
        if destination in self.edges:
            raise RuntimeError('Destination is already connected')
        a, b = self.kind(source), self.kind(destination)
        typed = {'doubleLinear', 'doubleAngle'}
        if a != b and 'generic' not in (a, b) and (a in typed or b in typed) and 'message' not in (a, b):
            converter = self.createNode('unitConversion', 'autoUnits#')
            self.edges[converter+'.input'] = source
            self.setAttr(converter+'.conversionFactor', self.factor(b)/self.factor(a))
            source = converter+'.output'
        self.edges[destination] = source

    def disconnectAttr(self, source, destination):
        if self.edges.get(destination) != source:
            raise RuntimeError('Connection changed')
        del self.edges[destination]

    def deleteAttr(self, plug):
        node, attr = plug.split('.', 1)
        self.nodes[node]['attrs'].pop(attr, None); self.nodes[node]['kinds'].pop(attr, None)
        self.edges = {d: s for d, s in self.edges.items() if d != plug and s != plug}

    def delete(self, values):
        for node in values if isinstance(values, (tuple, list)) else [values]:
            if self.fail_on == node:
                raise RuntimeError('Injected delete failure')
            del self.nodes[node]
            self.edges = {d: s for d, s in self.edges.items() if d.split('.', 1)[0] != node and s.split('.', 1)[0] != node}

    def rename(self, node, name):
        self.nodes[name] = self.nodes.pop(node)
        self.edges = {(name+d[len(node):] if d.startswith(node+'.') else d):
                      (name+s[len(node):] if s.startswith(node+'.') else s) for d, s in self.edges.items()}
        for data in self.nodes.values():
            if data['parent'] == node:
                data['parent'] = name
        return name

    def listRelatives(self, node, **kw):
        if kw.get('parent'):
            parent = self.nodes[node]['parent']
            return [parent] if parent else []
        return [n for n, d in self.nodes.items() if d['parent'] == node and (not kw.get('type') or d['type'] == kw['type'])]

    @staticmethod
    def product(a, b):
        return [sum(a[r*4+k]*b[k*4+c] for k in range(4)) for r in range(4) for c in range(4)]

    def world(self, node):
        ident = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]
        result = ident[:]
        for base in ('rotateAxis', 'rotate', 'jointOrient'):
            for axis in range(3):
                angle = self._value(node+'.'+base+'XYZ'[axis]); a, b = (axis+1)%3, (axis+2)%3
                rotation = ident[:]; rotation[a*4+a] = rotation[b*4+b] = math.cos(angle)
                rotation[a*4+b] = math.sin(angle); rotation[b*4+a] = -math.sin(angle)
                result = self.product(result, rotation)
        for i in range(3):
            for c in range(3):
                result[i*4+c] *= self._value(node+'.scale'+'XYZ'[i])
        result[12:15] = [self._value(node+'.translate'+a) for a in 'XYZ']
        parent = self.nodes[node]['parent']
        return self.product(result, self.world(parent)) if parent else result

    def xform(self, node, **kw):
        matrix = self.world(node)
        for i in range(12, 15):
            matrix[i] /= self.factor('doubleLinear')
        return matrix[12:15] if kw.get('translation') else matrix

    def currentUnit(self, **kw):
        return next(self.units[k] for k in ('linear', 'angle', 'time') if kw.get(k))

    def selectPref(self, **kw):
        return self.tracked

    def select(self, nodes=None, **kw):
        self.selection = [] if kw.get('clear') else list(nodes) if isinstance(nodes, (tuple, list)) else [nodes]

    def warning(self, message):
        self.warnings.append(message)

    def snapshot(self):
        return copy.deepcopy((self.nodes, self.edges, self.selection, self.serial))

    def undoInfo(self, **kw):
        if kw.get('query'):
            return (self.history[-1][0] if self.history else '') if kw.get('undoName') else self.enabled
        if kw.get('openChunk'):
            self.open = (kw['chunkName'], self.snapshot())
        elif kw.get('closeChunk'):
            self.history.append(self.open); self.open = None; self.future = []

    def undo(self):
        name, saved = self.history.pop(); self.future.append((name, self.snapshot()))
        self.nodes, self.edges, self.selection, self.serial = copy.deepcopy(saved)

    def redo(self):
        name, saved = self.future.pop(); self.history.append((name, self.snapshot()))
        self.nodes, self.edges, self.selection, self.serial = copy.deepcopy(saved)


def backend(commands):
    source = Path(__file__).with_name('wave_joints.py')
    tree = ast.parse(source.read_text())
    tree.body = [node for node in tree.body if not (isinstance(node, ast.Import) and any(a.name == 'maya.cmds' for a in node.names))]
    module = types.ModuleType('_wave_test_backend'); module.cmds = commands
    exec(compile(tree, str(source), 'exec'), module.__dict__)
    module._time_ui_second = commands.ui_fps
    return module


class WaveJointsTests(unittest.TestCase):
    def setUp(self):
        self.cmds = WaveCommands(); self.api = backend(self.cmds)

    def build(self, **kwargs):
        return self.api.build(self.cmds.driver, self.cmds.joints, **kwargs)

    def driver_attr(self, suffix, value):
        self.cmds.setAttr(self.cmds.driver+'.wave'+suffix, value)

    def assert_matrix(self, a, b):
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y, places=7)

    def test_default_build_retains_pose_and_generates_no_runtime_python(self):
        before = [self.cmds.world(j) for j in self.cmds.joints]
        result = self.build()
        for joint, matrix in zip(self.cmds.joints, before):
            self.assert_matrix(self.cmds.world(joint), matrix)
        self.assertTrue(all(not data['locked'] for data in self.cmds.nodes.values()))
        self.assertFalse(any(d['type'] in ('expression', 'script', 'scriptNode') for d in self.cmds.nodes.values()))
        self.assertEqual(self.api.list_systems(), [result['system']])

    def test_sine_samples_and_saved_translation_base(self):
        self.cmds.setAttr(self.cmds.joints[0]+'.translateY', 3.)
        self.build(settings={'envelope': 1., 'frequency': .25, 'translation_amplitude': 2.})
        for offset in (0., 35., 90., -120., 360.):
            self.driver_attr('Offset', offset)
            for i, joint in enumerate(self.cmds.joints):
                expected = (3. if i == 0 else 0.)+2.*math.sin(math.radians(offset+90.*i/2.))
                self.assertAlmostEqual(self.cmds.getAttr(joint+'.translateY'), expected, places=8)

    def test_rotation_is_added_to_local_value_and_orientation_is_unchanged(self):
        for joint in self.cmds.joints:
            self.cmds.setAttr(joint+'.rotateZ', 7.)
            self.cmds.setAttr(joint+'.jointOrient', 6., 10., -3., type='double3')
        self.build(channels=['rz'], settings={'envelope': 1., 'frequency': 0., 'offset': 90., 'rotation_amplitude': 20.})
        for joint in self.cmds.joints:
            self.assertAlmostEqual(self.cmds.getAttr(joint+'.rotateZ'), 27.)
            self.assertEqual(self.cmds.getAttr(joint+'.jointOrient'), [(6., 10., -3.)])
            self.assertEqual(self.cmds.getAttr(joint+'.scale'), [(1., 1., 1.)])

    def test_circular_outputs_and_negative_gain(self):
        self.build(channels={'ty': {}, 'tz': {'phase': 90., 'gain': -1.}}, settings={'envelope': 1., 'frequency': 0., 'translation_amplitude': 3.})
        for offset in (0, 20, 90, 170):
            self.driver_attr('Offset', offset)
            joint = self.cmds.joints[0]
            y, z = (self.cmds.getAttr(joint+'.translate'+a) for a in ('Y', 'Z'))
            self.assertAlmostEqual(y*y+z*z, 9.)
            self.assertAlmostEqual(z, -3.*math.cos(math.radians(offset)))

    def test_taper_and_distance_spacing_use_cached_rest_positions(self):
        result = self.build(spacing='distance', settings={'envelope': 1., 'frequency': .25, 'root_weight': 0., 'tip_weight': 1.})
        for joint, fraction in zip(self.cmds.joints, (0., .25, 1.)):
            self.assertAlmostEqual(self.cmds.getAttr(joint+'.translateY'), fraction*math.sin(math.pi/2*fraction))
        self.api.update(result['system'], spacing='index')
        self.assertAlmostEqual(self.cmds.getAttr(self.cmds.joints[1]+'.translateY'), .5*math.sin(math.pi/4))
        self.api.update(result['system'], spacing='distance')
        self.assertAlmostEqual(self.cmds.getAttr(self.cmds.joints[1]+'.translateY'), .25*math.sin(math.pi/8))

    def test_time_is_seconds_and_manual_offset_is_independent(self):
        for native_scale in (1., 6000.):
            self.setUp(); self.cmds.native_time_scale = native_scale
            result = self.build(settings={'envelope': 1., 'frequency': 0., 'speed': 1., 'auto_time': True})
            for fps in ('film', 'ntsc', '60fps'):
                self.cmds.units['time'] = fps
                self.cmds.seconds = .25
                self.assertAlmostEqual(self.cmds.getAttr(self.cmds.joints[0]+'.translateY'), 1.)
            self.api.update(result['system'], settings={'auto_time': False, 'offset': -90.})
            self.cmds.seconds = 500.
            self.assertAlmostEqual(self.cmds.getAttr(self.cmds.joints[0]+'.translateY'), -1.)

    def test_maya_legacy_distance_and_new_unitless_sine_outputs_are_equal(self):
        results = []
        for legacy in (True, False):
            commands = WaveCommands(legacy_sine=legacy); api = backend(commands)
            commands.units.update(linear='m', angle='rad')
            api.build(commands.driver, commands.joints, channels=['ty', 'rz'], settings={
                'envelope': 1., 'frequency': 0., 'offset': 90., 'translation_amplitude': 2., 'rotation_amplitude': 30.})
            results.append([commands.getAttr(commands.joints[0]+'.translateY'), commands.getAttr(commands.joints[0]+'.rotateZ')])
        self.assertEqual(results[0], results[1])
        self.assertAlmostEqual(results[0][0], 2.)
        self.assertAlmostEqual(results[0][1], math.pi/6)

    def test_changing_ui_units_after_build_keeps_physical_motion(self):
        self.build(channels=['ty', 'rz'], settings={'envelope': 1., 'frequency': 0., 'offset': 90.,
                   'translation_amplitude': 2., 'rotation_amplitude': 30.})
        self.cmds.units.update(linear='m', angle='rad')
        self.assertAlmostEqual(self.cmds.getAttr(self.cmds.joints[0]+'.translateY'), .02)
        self.assertAlmostEqual(self.cmds.getAttr(self.cmds.joints[0]+'.rotateZ'), math.pi/6)
        info = self.api.current_settings(self.api.list_systems()[0])
        self.assertAlmostEqual(info['settings']['translation_amplitude'], .02)
        self.assertAlmostEqual(info['settings']['rotation_amplitude'], 30.)

    def test_update_reorders_same_joints_without_accumulating_rest_offsets(self):
        self.cmds.setAttr(self.cmds.joints[1]+'.translateY', 4.)
        result = self.build(settings={'envelope': 1., 'frequency': .25})
        count = len(self.cmds.nodes)
        for order in (list(reversed(self.cmds.joints)), self.cmds.joints)*2:
            self.api.update(result['system'], joints=order)
            for i, joint in enumerate(order):
                expected = (4. if joint == self.cmds.joints[1] else 0.)+math.sin(math.pi/2*i/2.)
                self.assertAlmostEqual(self.cmds.getAttr(joint+'.translateY'), expected)
        self.assertEqual(len(self.cmds.nodes), count)

    def test_remove_keeps_posed_joints_definitions_other_channels_and_other_setup(self):
        a = self.build(settings={'envelope': 1., 'frequency': .3, 'offset': 42.})
        b = self.build(prefix='twist', channels=['rz'], settings={'envelope': 1., 'frequency': .4, 'rotation_amplitude': 15.})
        before = [self.cmds.world(j) for j in self.cmds.joints]
        result = self.api.remove(a['system'])
        for joint, matrix in zip(self.cmds.joints, before):
            self.assert_matrix(self.cmds.world(joint), matrix)
        self.assertEqual(result['joint_count'], 3)
        self.assertEqual(self.api.list_systems(), [b['system']])
        self.assertIn(self.cmds.joints[0]+'.rotateZ', self.cmds.edges)
        self.assertNotIn(self.cmds.joints[0]+'.translateY', self.cmds.edges)
        self.assertFalse(self.cmds.attributeQuery('waveOffset', node=self.cmds.driver, exists=True))

    def test_removal_undo_redo_and_renamed_nodes_use_uuid(self):
        result = self.build(settings={'envelope': 1., 'offset': 70.})
        _meta, state = self.api.read(result['system'])
        changed = self.cmds.rename(self.cmds.joints[-1], '|renamed_joint')
        self.cmds.rename(self.api.resolve(state['members'][0]['uuid']), 'renamed_math')
        meta = self.cmds.rename(result['system'], 'renamed_wave')
        pose = self.cmds.world(changed)
        self.api.remove(meta)
        self.assert_matrix(self.cmds.world(changed), pose)
        self.cmds.undo(); self.api.read(meta)
        self.assert_matrix(self.cmds.world(changed), pose)
        self.cmds.redo(); self.assertNotIn(meta, self.cmds.nodes)
        self.assert_matrix(self.cmds.world(changed), pose)

    def test_remove_retains_animated_and_sdk_driver_attributes(self):
        result = self.build()
        curve = self.cmds.add('timeKeys', 'animCurveTU')
        self.cmds.connectAttr(curve+'.output', self.cmds.driver+'.waveOffset')
        sdk = self.cmds.add('externalSDK', 'animCurveUU')
        self.cmds.connectAttr(self.cmds.driver+'.waveEnvelope', sdk+'.input')
        report = self.api.remove(result['system'])
        self.assertEqual(set(report['retained_attributes']), {'waveOffset', 'waveEnvelope'})
        self.assertIn(curve, self.cmds.nodes); self.assertIn(sdk, self.cmds.nodes)

    def test_build_reuses_compatible_attrs_and_preserves_existing_animation(self):
        self.cmds.addAttr(self.cmds.driver, longName='waveOffset', attributeType='double', defaultValue=12.)
        curve = self.cmds.add('timeKeys', 'animCurveTU'); self.cmds.setAttr(curve+'.output', 23.)
        self.cmds.connectAttr(curve+'.output', self.cmds.driver+'.waveOffset')
        result = self.build()
        self.assertEqual(result['reused_attributes'], ['waveOffset'])
        self.assertEqual(self.cmds.getAttr(self.cmds.driver+'.waveOffset'), 23.)
        report = self.api.remove(result['system'])
        self.assertTrue(self.cmds.objExists(self.cmds.driver+'.waveOffset'))
        self.assertIn('waveOffset', report['retained_attributes'])

    def test_existing_driver_on_another_axis_does_not_block_chosen_axis(self):
        other = self.cmds.add('foreign', 'multiplyDivide')
        self.cmds.connectAttr(other+'.outputX', self.cmds.joints[0]+'.rotateX')
        self.build(channels=['rz'])
        self.assertIn(self.cmds.joints[0]+'.rotateX', self.cmds.edges)

    def test_foreign_output_consumer_blocks_removal_without_edits(self):
        result = self.build(); _meta, data = self.api.read(result['system'])
        output = data['joints'][0]['inputs']['ty']; source = self.api.resolve(output['node'])+'.'+output['attribute']
        extra = self.cmds.add('|external', 'transform')
        self.cmds.connectAttr(source, extra+'.translateY')
        before = self.cmds.snapshot()
        with self.assertRaisesRegex(ValueError, 'Another system uses'):
            self.api.remove(result['system'])
        self.assertEqual(before, self.cmds.snapshot())

    def test_partial_deleted_nodes_and_attributes_still_allow_safe_removal(self):
        result = self.build(); _meta, data = self.api.read(result['system'])
        self.cmds.delete(self.api.resolve(data['members'][1]['uuid']))
        self.cmds.deleteAttr(self.cmds.driver+'.waveSpeed')
        self.api.remove(result['system'])
        self.assertFalse(self.api.list_systems())

    def test_build_failure_rolls_back_nodes_attributes_and_connections(self):
        self.cmds.fail_on = self.cmds.joints[1]+'.translateY'
        before = self.cmds.snapshot()
        with self.assertRaisesRegex(RuntimeError, 'rolled back'):
            self.build()
        self.assertEqual(before, self.cmds.snapshot())

    def test_update_and_remove_failures_roll_back(self):
        result = self.build(); before = self.cmds.snapshot()
        self.cmds.fail_on = self.cmds.driver+'.waveOffset'
        with self.assertRaisesRegex(RuntimeError, 'rolled back'):
            self.api.update(result['system'], settings={'offset': 30.})
        self.assertEqual(before, self.cmds.snapshot())
        self.cmds.fail_on = self.cmds.joints[1]+'.translateY'
        with self.assertRaisesRegex(RuntimeError, 'rolled back'):
            self.api.remove(result['system'])
        self.assertEqual(before, self.cmds.snapshot())

    def test_missing_sine_bad_values_duplicate_and_instanced_joints_are_read_only(self):
        for mutation, kwargs in (
            (lambda: setattr(self.cmds, 'available', []), {}),
            (lambda: None, {'settings': {'offset': float('nan')}}),
            (lambda: None, {'channels': []}),
            (lambda: None, {'prefix': 'bad space'}),
            (lambda: self.cmds.nodes[self.cmds.joints[0]].update(instanced=True), {}),
        ):
            self.setUp(); mutation(); before = self.cmds.snapshot()
            with self.assertRaises(ValueError):
                self.build(**kwargs)
            self.assertEqual(before, self.cmds.snapshot())
        before = self.cmds.snapshot()
        with self.assertRaises(ValueError):
            self.api.build(self.cmds.driver, [self.cmds.joints[0]]*2)
        self.assertEqual(before, self.cmds.snapshot())

    def test_locked_and_connected_joint_channels_are_protected_before_build(self):
        self.cmds.nodes[self.cmds.joints[0]]['locked'].add('translateY')
        before = self.cmds.snapshot()
        with self.assertRaisesRegex(ValueError, 'locked'):
            self.build()
        self.assertEqual(before, self.cmds.snapshot())
        self.cmds.nodes[self.cmds.joints[0]]['locked'].clear()
        foreign = self.cmds.add('foreignDriver', 'multiplyDivide')
        self.cmds.connectAttr(foreign+'.outputX', self.cmds.joints[0]+'.translateY')
        before = self.cmds.snapshot()
        with self.assertRaisesRegex(ValueError, 'driven'):
            self.build()
        self.assertEqual(before, self.cmds.snapshot())

    def test_changed_joint_driver_and_locked_member_stop_removal_read_only(self):
        result = self.build(); _meta, data = self.api.read(result['system'])
        first = self.api.resolve(data['members'][0]['uuid'])
        self.cmds.nodes[first]['node_lock'] = True; before = self.cmds.snapshot()
        with self.assertRaisesRegex(ValueError, 'locked'):
            self.api.remove(result['system'])
        self.assertEqual(before, self.cmds.snapshot())
        self.cmds.nodes[first]['node_lock'] = False
        foreign = self.cmds.add('foreignDriver', 'multiplyDivide')
        self.cmds.edges[self.cmds.joints[0]+'.translateY'] = foreign+'.outputX'
        before = self.cmds.snapshot()
        with self.assertRaisesRegex(ValueError, 'another driver'):
            self.api.remove(result['system'])
        self.assertEqual(before, self.cmds.snapshot())

    def test_branch_chain_single_joint_and_identical_distance_inputs(self):
        self.assertEqual(self.api.ordered_chain(self.cmds.joints[0]), self.cmds.joints)
        self.cmds.add('|first_L|branch', 'joint', self.cmds.joints[0])
        with self.assertRaisesRegex(ValueError, 'branches'):
            self.api.ordered_chain(self.cmds.joints[0])
        result = self.api.build(self.cmds.driver, [self.cmds.joints[0]], spacing='distance')
        self.assertEqual(result['joint_count'], 1)
        self.api.remove(result['system'])
        for joint in self.cmds.joints:
            self.cmds.setAttr(joint+'.translateX', 0.)
        with self.assertRaisesRegex(ValueError, 'separated'):
            self.api.plan(self.cmds.driver, self.cmds.joints, spacing='distance')

    def test_update_rejects_topology_change_and_driven_parameter_without_edits(self):
        result = self.build(); before = self.cmds.snapshot()
        with self.assertRaisesRegex(ValueError, 'output channels'):
            self.api.update(result['system'], channels=['rz'])
        with self.assertRaisesRegex(ValueError, 'same joints'):
            self.api.update(result['system'], joints=self.cmds.joints[:2])
        self.assertEqual(before, self.cmds.snapshot())
        curve = self.cmds.add('timeKeys', 'animCurveTU')
        self.cmds.connectAttr(curve+'.output', self.cmds.driver+'.waveOffset')
        before = self.cmds.snapshot()
        with self.assertRaisesRegex(ValueError, 'already driven'):
            self.api.update(result['system'], settings={'offset': 10.})
        self.assertEqual(before, self.cmds.snapshot())

    def test_metadata_membership_tampering_blocks_cleanup(self):
        result = self.build(); meta = result['system']
        foreign = self.cmds.add('foreign', 'multiplyDivide')
        self.cmds.edges[meta+'.members[0]'] = foreign+'.message'
        before = self.cmds.snapshot()
        with self.assertRaisesRegex(ValueError, 'ownership link'):
            self.api.remove(meta)
        self.assertEqual(before, self.cmds.snapshot())


if __name__ == '__main__':
    unittest.main()
