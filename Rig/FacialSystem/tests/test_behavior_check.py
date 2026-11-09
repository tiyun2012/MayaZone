import copy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import facial_system
from facial_system import validation


class BehaviorCheckTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        data = Path(self.folder.name)
        self.outputs = [{'destination': 'jaw.tx', 'dof': 0, 'neutral': 5.},
                        {'destination': 'jaw.rx', 'dof': 3, 'neutral': 0.},
                        {'destination': 'jaw.sx', 'dof': 6, 'neutral': 1.}]
        (data / 'behavior.json').write_text(json.dumps({'outputs': self.outputs, 'raw_count': 2}))
        cases = [{'name': 'zero', 'raw': [0., 0.], 'expected': [5., 0., 1.]},
                 {'name': 'one', 'raw': [1., 0.], 'expected': [7., 6., 1.]}]
        with gzip.open(data / 'validation_cases.json.gz', 'wt') as handle:
            json.dump({'cases': cases}, handle)
        self.values = [0.25, 0.5]
        self.connections = {'NS:NFRv1_RAW.value[0]': 'NS:GUI.first',
                            'NS:NFRv1_RAW.value[1]': 'NS:GUI.second'}
        self.original_values = list(self.values)
        self.original_connections = dict(self.connections)
        self.undo_enabled = True
        self.undo_queue = ['OriginalArtistAction']
        self.suspended = False
        self.output_error = 0.
        self.read_error = False
        cmds = types.ModuleType('maya.cmds')
        def get_attr(plug, **kwargs):
            if kwargs.get('lock'):
                return False
            if plug == 'NS:matrix':
                return [8.] + [0.] * 15
            return self.values[int(plug.rsplit('[', 1)[1][:-1])]
        def set_attr(plug, value):
            self.values[int(plug.rsplit('[', 1)[1][:-1])] = value
            if self.undo_enabled:
                self.undo_queue.append('setAttr')
        def disconnect(source, dest):
            self.assertEqual(self.connections.pop(dest), source)
        def connect(source, dest, **kwargs):
            self.connections[dest] = source
        def undo_info(**kwargs):
            if kwargs.get('query'):
                return self.undo_enabled
            if 'stateWithoutFlush' in kwargs:
                self.undo_enabled = kwargs['stateWithoutFlush']
        def refresh(**kwargs):
            if 'suspend' in kwargs:
                self.suspended = kwargs['suspend']
        cmds.getAttr, cmds.setAttr = get_attr, set_attr
        cmds.disconnectAttr, cmds.connectAttr = disconnect, connect
        cmds.undoInfo, cmds.refresh = undo_info, refresh
        def output_value(name):
            if self.read_error:
                raise RuntimeError('simulated output read failure')
            return {'NS:jaw.tx': 8. + 2. * self.values[0] + self.output_error,
                    'NS:jaw.rx': 6. * self.values[0], 'NS:jaw.sx': 1.}[name]
        class Plug:
            def __init__(other, name): other.name = name
            def asMDistance(other): return types.SimpleNamespace(asCentimeters=lambda: output_value(other.name))
            def asMAngle(other): return types.SimpleNamespace(asDegrees=lambda: output_value(other.name))
            def asDouble(other): return output_value(other.name)
        class Selection:
            def add(other, name): other.name = name
            def getPlug(other, index): return Plug(other.name)
        om = types.ModuleType('maya.api.OpenMaya')
        om.MSelectionList = Selection
        fitter = types.ModuleType('facial_system.fit')
        fitter.native_bus = lambda document: 'NS:NFRv1_RAW'
        fitter.translation_writer = lambda *args: {'kind': 'native_constant', 'plug': 'NS:matrix', 'cell': 0}
        fitter.flat = list
        fitter.sources = lambda plug: [self.connections[plug]] if plug in self.connections else []
        ops = types.ModuleType('facial_system.scene_ops')
        ops.scope_document = lambda: {}
        adapter = types.ModuleType('facial_system.scene_adapter')
        adapter.Cancelled = type('Cancelled', (Exception,), {})
        modules = {'maya': types.ModuleType('maya'), 'maya.cmds': cmds,
                   'maya.api': types.ModuleType('maya.api'), 'maya.api.OpenMaya': om,
                   'facial_system.fit': fitter, 'facial_system.scene_ops': ops,
                   'facial_system.scene_adapter': adapter}
        self.patches = [mock.patch.dict(sys.modules, modules), mock.patch.object(validation, 'DATA', data),
                        mock.patch.object(facial_system, 'fit', fitter, create=True),
                        mock.patch.object(facial_system, 'scene_ops', ops, create=True)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.folder.cleanup()

    def assertRestored(self):
        self.assertEqual(self.values, self.original_values)
        self.assertEqual(self.connections, self.original_connections)
        self.assertEqual(self.undo_queue, ['OriginalArtistAction'])
        self.assertTrue(self.undo_enabled)
        self.assertFalse(self.suspended)

    def test_fitted_translation_baseline_passes_and_restores_inputs(self):
        report = validation.check_behavior()
        self.assertTrue(report['passed'])
        self.assertEqual(report['cases'], 2)
        self.assertEqual(report['neutral_translation_offsets_cm'], {'jaw.tx': 3.})
        self.assertEqual(report['maximum_errors']['translation_cm'], 0.)
        self.assertRestored()

    def test_changed_response_is_not_hidden_by_neutral_offset(self):
        self.output_error = .1
        report = validation.check_behavior()
        self.assertFalse(report['passed'])
        self.assertAlmostEqual(report['maximum_errors']['translation_cm'], .1)
        self.assertRestored()

    def test_cancel_restores_connections_values_refresh_and_undo(self):
        with self.assertRaisesRegex(Exception, 'cancelled'):
            validation.check_behavior(progress=lambda *args: False)
        self.assertRestored()

    def test_output_read_failure_still_restores_scene(self):
        self.read_error = True
        with self.assertRaisesRegex(RuntimeError, 'simulated output'):
            validation.check_behavior()
        self.assertRestored()

    def test_rotation_and_scale_references_receive_no_translation_offset(self):
        values = validation.adjusted_reference(self.outputs, [5., 6., 1.],
                                              {'jaw.tx': 3., 'jaw.rx': 100., 'jaw.sx': 100.})
        self.assertEqual(values, [8., 6., 1.])

    def test_existing_disabled_undo_state_stays_disabled(self):
        self.undo_enabled = False
        report = validation.check_behavior()
        self.assertTrue(report['passed'])
        self.assertFalse(self.undo_enabled)
        self.assertEqual(self.connections, self.original_connections)
        self.assertEqual(self.values, self.original_values)
        self.assertEqual(self.undo_queue, ['OriginalArtistAction'])

    def test_connection_restoration_failure_cannot_report_pass(self):
        cmds = sys.modules['maya.cmds']
        cmds.connectAttr = mock.Mock(side_effect=RuntimeError('simulated restore failure'))
        with self.assertRaisesRegex(RuntimeError, 'could not restore raw inputs'):
            validation.check_behavior()
        self.assertTrue(self.undo_enabled)
        self.assertFalse(self.suspended)


if __name__ == '__main__':
    unittest.main()
