"""Regressions for the supplied rig's inactive upper-nose modifiers."""
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class NeutralCheckTests(unittest.TestCase):
    def setUp(self):
        self.values = [0.] * 263
        for index in (254, 258, 262):
            self.values[index] = 1.
        self.writes = []
        cmds = types.ModuleType('maya.cmds')
        def get_attr(plug, **kwargs):
            if kwargs.get('multiIndices'):
                return list(range(263))
            return self.values[int(plug.rsplit('[', 1)[1][:-1])]
        cmds.getAttr = get_attr
        cmds.listConnections = lambda plug, **kwargs: ['CTRL_expressions.' + {
            51: 'noseWrinkleL', 52: 'noseWrinkleR',
            53: 'noseWrinkleUpperL', 54: 'noseWrinkleUpperR',
        }.get(int(plug.rsplit('[', 1)[1][:-1]), 'other')]
        cmds.setAttr = lambda *args, **kwargs: self.writes.append(args)
        om = types.ModuleType('maya.api.OpenMaya')
        om.MSpace = types.SimpleNamespace(kWorld=0, kObject=1)
        modules = {'maya': types.ModuleType('maya'), 'maya.cmds': cmds,
                   'maya.api': types.ModuleType('maya.api'), 'maya.api.OpenMaya': om,
                   'maya.api.OpenMayaAnim': types.ModuleType('maya.api.OpenMayaAnim')}
        self.modules = mock.patch.dict(sys.modules, modules)
        self.modules.start()
        for name in ('facial_system.scene_adapter', 'facial_system.fit'):
            sys.modules.pop(name, None)
        self.fit = importlib.import_module('facial_system.fit')
        self.bus = mock.patch.object(self.fit, 'native_bus', return_value='NFRv1_RAW')
        self.bus.start()

    def tearDown(self):
        self.bus.stop()
        for name in ('facial_system.scene_adapter', 'facial_system.fit'):
            sys.modules.pop(name, None)
        self.modules.stop()

    def test_saved_gui_upper_nose_defaults_are_neutral_without_scene_writes(self):
        self.values[53] = self.values[54] = 1.
        self.assertEqual(self.fit.check_neutral({}), 'NFRv1_RAW')
        self.assertEqual(self.writes, [])

    def test_zero_and_partial_modifier_values_are_also_neutral(self):
        for left, right in ((0., 0.), (.25, .8), (1., 0.)):
            self.values[53], self.values[54] = left, right
            self.assertEqual(self.fit.check_neutral({}), 'NFRv1_RAW')

    def test_actual_nose_expression_is_still_rejected_and_named(self):
        self.values[53] = self.values[54] = 1.
        for index, label in ((51, 'noseWrinkleL'), (52, 'noseWrinkleR')):
            self.values[index] = .4
            with self.assertRaises(ValueError) as raised:
                self.fit.check_neutral({})
            self.assertIn('CTRL_expressions.' + label, str(raised.exception))
            self.assertIn('raw ' + str(index), str(raised.exception))
            self.assertIn('0.4', str(raised.exception))
            self.values[index] = 0.

    def test_other_expressions_and_neck_poses_still_block_fitting(self):
        for index in (0, 150, 251, 254, 258, 262):
            saved = self.values[index]
            self.values[index] = .3
            with self.assertRaises(ValueError):
                self.fit.check_neutral({})
            self.values[index] = saved

    def test_invalid_modifier_values_are_not_silently_accepted(self):
        for value in (float('nan'), float('inf'), -1., 2.):
            self.values[53] = value
            with self.assertRaises(ValueError):
                self.fit.check_neutral({})
        self.assertEqual(self.writes, [])


if __name__ == '__main__':
    unittest.main()
