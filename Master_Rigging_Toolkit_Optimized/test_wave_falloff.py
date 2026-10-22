"""Falloff values and migration of a recorded, shipped 2.38 graph fixture."""
import copy
import json
import math
from pathlib import Path
import unittest

from test_wave_joints import WaveCommands, backend


def load_legacy(commands):
    data = json.loads((Path(__file__).parent/'test_data'/'wave_v238.json').read_text())
    commands.nodes, commands.edges, commands.selection, commands.serial = copy.deepcopy(data['snapshot'])
    for node in commands.nodes.values():
        node['locked'] = set(node['locked'])
    return data['system_uuid']


class WaveFalloffTests(unittest.TestCase):
    def setUp(self):
        self.cmds = WaveCommands(); self.api = backend(self.cmds)

    def build(self, **settings):
        values = {'envelope': 1., 'frequency': 0., 'offset': 90.,
                  'translation_amplitude': 2., 'rotation_amplitude': 20.}
        values.update(settings)
        return self.api.build(self.cmds.driver, self.cmds.joints, channels=['ty', 'rz'], settings=values)['system']

    def weights(self, system):
        _meta, data = self.api.read(system)
        return [self.cmds.getAttr(self.api.resolve(row['falloff']['node'])+'.'+row['falloff']['attribute'])
                for row in data['joints']]

    def legacy(self):
        return self.api.unique(load_legacy(self.cmds))

    def test_peak_is_one_and_moving_peak_tracks_normalized_joint_position(self):
        system = self.build(falloff_power=1., falloff_position=.5)
        self.assertEqual(self.weights(system), [.5, 1., .5])
        self.api.update(system, settings={'falloff_position': 0.})
        self.assertEqual(self.weights(system), [1., .5, 0.])
        self.api.update(system, settings={'falloff_position': 1.})
        self.assertEqual(self.weights(system), [0., .5, 1.])

    def test_higher_power_keeps_a_wider_region_strong(self):
        system = self.build(falloff_position=.5)
        for power, expected in ((1., .5), (2., .75), (4., .9375), (8., .99609375)):
            self.api.update(system, settings={'falloff_power': power})
            weights = self.weights(system)
            self.assertEqual(weights, [expected, 1., expected])

    def test_only_wave_delta_is_multiplied_and_both_amplitude_types_are_affected(self):
        self.cmds.setAttr(self.cmds.joints[0]+'.translateY', 7.)
        self.cmds.setAttr(self.cmds.joints[0]+'.rotateZ', 11.)
        system = self.build(falloff_position=1., falloff_power=1.)
        self.assertEqual(self.weights(system), [0., .5, 1.])
        self.assertAlmostEqual(self.cmds.getAttr(self.cmds.joints[0]+'.translateY'), 7.)
        self.assertAlmostEqual(self.cmds.getAttr(self.cmds.joints[0]+'.rotateZ'), 11.)
        self.assertAlmostEqual(self.cmds.getAttr(self.cmds.joints[1]+'.translateY'), 1.)
        self.assertAlmostEqual(self.cmds.getAttr(self.cmds.joints[1]+'.rotateZ'), 10.)

    def test_disabled_falloff_is_one_and_all_power_nodes_are_defined_at_center(self):
        system = self.build(falloff_position=.5, falloff_power=0.)
        for power in (0., .0001, .5, 1., 1000.):
            self.cmds.setAttr(self.cmds.driver+'.waveFalloffPower', power)
            self.assertEqual(self.weights(system)[1], 1.)
            for node, data in self.cmds.nodes.items():
                if data['type'] == 'multiplyDivide' and self.cmds.getAttr(node+'.operation') == 3:
                    self.assertTrue(math.isfinite(self.cmds.getAttr(node+'.outputX')))
                    for axis in 'YZ':
                        self.assertEqual(self.cmds.getAttr(node+'.input2'+axis), 1.)
        self.api.update(system, settings={'falloff_power': 0.})
        self.assertEqual(self.weights(system), [1., 1., 1.])

    def test_graph_matches_reference_for_fractional_powers_edges_and_between_joints(self):
        system = self.build()
        for center in (0., .17, .5, .83, 1.):
            for power in (0., .0001, .5, 1., 2.5, 30., 1000.):
                self.api.update(system, settings={'falloff_position': center, 'falloff_power': power})
                expected = [1. if power == 0. else 1.-min(1., abs(s-center))**max(.001, power) for s in (0., .5, 1.)]
                for actual, value, s in zip(self.weights(system), expected, (0., .5, 1.)):
                    self.assertAlmostEqual(actual, value)
                    self.assertAlmostEqual(actual, self.api.falloff_weight(s, center, power))
                    self.assertTrue(0. <= actual <= 1.)

    def test_distance_spacing_and_reordered_joint_positions_drive_falloff(self):
        system = self.api.build(self.cmds.driver, self.cmds.joints, spacing='distance',
                                settings={'falloff_position': .25, 'falloff_power': 2.})['system']
        expected = [1.-.25**2, 1., 1.-.75**2]
        self.assertEqual(self.weights(system), expected)
        self.api.update(system, joints=list(reversed(self.cmds.joints)), spacing='index', settings={'falloff_position': 0., 'falloff_power': 1.})
        self.assertEqual(self.weights(system), [0., .5, 1.])

    def test_falloff_parameters_can_be_time_animated_and_remain_after_removal(self):
        system = self.build(falloff_power=2.)
        curve = self.cmds.add('falloffKeys', 'animCurveTU'); self.cmds.setAttr(curve+'.output', .5)
        self.cmds.connectAttr(curve+'.output', self.cmds.driver+'.waveFalloffPosition')
        self.assertEqual(self.weights(system), [.75, 1., .75])
        self.cmds.setAttr(curve+'.output', 0.)
        self.assertEqual(self.weights(system), [1., .75, 0.])
        posed = [self.cmds.world(joint) for joint in self.cmds.joints]
        report = self.api.remove(system)
        self.assertIn('waveFalloffPosition', report['retained_attributes'])
        self.assertIn(curve, self.cmds.nodes)
        for joint, expected in zip(self.cmds.joints, posed):
            self.assertEqual(self.cmds.world(joint), expected)

    def test_invalid_position_and_power_are_rejected_before_mutation(self):
        for values in ({'falloff_position': -.1}, {'falloff_position': 1.1},
                       {'falloff_power': -1.}, {'falloff_power': float('inf')}):
            before = self.cmds.snapshot()
            with self.assertRaises(ValueError):
                self.build(**values)
            self.assertEqual(before, self.cmds.snapshot())

    def test_old_wave_reads_and_removes_without_adding_any_falloff_data(self):
        system = self.legacy(); before = self.cmds.snapshot()
        info = self.api.current_settings(system)
        self.assertFalse(info['falloff_available'])
        self.assertEqual(info['settings']['falloff_power'], 0.)
        self.assertEqual(before, self.cmds.snapshot())
        self.assertFalse(self.cmds.objExists(self.cmds.driver+'.waveFalloffPosition'))
        self.api.remove(system)
        self.assertFalse(self.api.list_systems())

    def test_old_wave_upgrades_without_changing_pose_or_old_output_connections(self):
        system = self.legacy()
        old_nodes = set(self.cmds.nodes)
        poses = [self.cmds.world(joint) for joint in self.cmds.joints]
        output_inputs = {p: s for p, s in self.cmds.edges.items() if any(p.startswith(j+'.') for j in self.cmds.joints)}
        self.api.update(system)
        self.assertTrue(self.api.current_settings(system)['falloff_available'])
        self.assertTrue(old_nodes.issubset(self.cmds.nodes))
        self.assertEqual(self.weights(system), [1., 1., 1.])
        for joint, expected in zip(self.cmds.joints, poses):
            self.assertEqual(self.cmds.world(joint), expected)
        for plug, source in output_inputs.items():
            self.assertEqual(self.cmds.edges[plug], source)
        count = len(self.cmds.nodes); self.api.update(system)
        self.assertEqual(len(self.cmds.nodes), count)

    def test_old_wave_migration_preserves_bases_animation_then_applies_requested_falloff(self):
        system = self.legacy()
        curve = self.cmds.add('offsetKeys', 'animCurveTU'); self.cmds.setAttr(curve+'.output', 60.)
        self.cmds.connectAttr(curve+'.output', self.cmds.driver+'.waveOffset')
        values = [(self.cmds.getAttr(j+'.translateY'), self.cmds.getAttr(j+'.rotateZ')) for j in self.cmds.joints]
        self.api.update(system, settings={'falloff_power': 2.})
        self.assertEqual(self.cmds.edges[self.cmds.driver+'.waveOffset'], curve+'.output')
        for index, (joint, (y, z)) in enumerate(zip(self.cmds.joints, values)):
            weight = (.75, 1., .75)[index]; base_y = 3. if index == 0 else 0.
            self.assertAlmostEqual(self.cmds.getAttr(joint+'.translateY'), base_y+(y-base_y)*weight)
            self.assertAlmostEqual(self.cmds.getAttr(joint+'.rotateZ'), 7.+(z-7.)*weight)

    def test_upgrade_and_removal_support_undo_redo(self):
        system = self.legacy(); before = self.cmds.snapshot()
        self.api.update(system, settings={'falloff_power': 4., 'falloff_position': .3})
        upgraded = self.cmds.snapshot()
        self.cmds.undo(); self.assertEqual(before, self.cmds.snapshot())
        self.assertFalse(self.api.current_settings(system)['falloff_available'])
        self.cmds.redo(); self.assertEqual(upgraded, self.cmds.snapshot())
        self.api.remove(system); self.assertFalse(self.api.list_systems())
        self.cmds.undo(); self.assertTrue(self.api.current_settings(system)['falloff_available'])

    def test_upgrade_failure_rolls_back_attrs_nodes_and_rewiring(self):
        system = self.legacy(); _meta, data = self.api.read(system)
        row = data['joints'][0]; source = self.api.resolve(row['inputs']['ty']['node'])
        if self.cmds.nodeType(source) == 'unitConversion':
            source = self.cmds.edges[source+'.input'].split('.', 1)[0]
        self.cmds.fail_on = source+'.input1D[1]'
        before = self.cmds.snapshot()
        with self.assertRaisesRegex(RuntimeError, 'rolled back'):
            self.api.update(system, settings={'falloff_power': 2.})
        self.assertEqual(before, self.cmds.snapshot())
        self.assertFalse(self.api.current_settings(system)['falloff_available'])

    def test_foreign_driver_and_edited_legacy_base_stop_upgrade_without_edits(self):
        system = self.legacy(); _meta, data = self.api.read(system)
        source = self.api.resolve(data['joints'][0]['inputs']['ty']['node'])
        if self.cmds.nodeType(source) == 'unitConversion':
            source = self.cmds.edges[source+'.input'].split('.', 1)[0]
        self.cmds.setAttr(source+'.input1D[0]', 999.)
        before = self.cmds.snapshot()
        with self.assertRaisesRegex(ValueError, 'base value changed'):
            self.api.update(system)
        self.assertEqual(before, self.cmds.snapshot())
        self.setUp(); system = self.legacy()
        other = self.cmds.add('foreign', 'multiplyDivide')
        self.cmds.edges[self.cmds.joints[0]+'.translateY'] = other+'.outputX'
        before = self.cmds.snapshot()
        with self.assertRaisesRegex(ValueError, 'Joint output changed'):
            self.api.update(system)
        self.assertEqual(before, self.cmds.snapshot())


if __name__ == '__main__':
    unittest.main()
