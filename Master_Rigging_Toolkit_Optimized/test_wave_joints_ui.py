"""Real Qt controls with the graph command adapter; no native Maya solver."""
import ast
from pathlib import Path
import sys
import types
import unittest
from unittest import mock
import uuid

from test_wave_joints import WaveCommands, backend
try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    try:
        from PySide2 import QtCore, QtWidgets
    except ImportError:
        QtWidgets = None


@unittest.skipIf(QtWidgets is None, 'Qt unavailable')
class WaveUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from wave_joints_ui import WaveJointsPanel
        cls.panel_class = WaveJointsPanel

    def setUp(self):
        self.commands = WaveCommands(); self.api = backend(self.commands)
        self.panel = self.panel_class(None, self.api)

    def tearDown(self):
        self.panel.close(); self.panel.deleteLater(); self.app.processEvents()

    def click(self, text):
        next(button for button in self.panel.findChildren(QtWidgets.QPushButton) if button.text() == text).click()
        self.app.processEvents()

    def inputs(self):
        self.commands.selection = [self.commands.driver]; self.click('Get selected')
        self.commands.selection = [self.commands.joints[0]]; self.click('Get chain')

    def build(self):
        self.inputs(); self.click('Build wave')
        self.assertFalse(self.commands.warnings)
        return self.api.list_systems()[0]

    def test_workflow_routes_to_lazy_wave_panel(self):
        source = Path(__file__).with_name('master_rigging_toolkit.py').read_text()
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MasterRiggingUI')
        workflows = ast.literal_eval(next(n.value for n in cls.body if isinstance(n, ast.Assign)
                                         and any(isinstance(t, ast.Name) and t.id == 'WORKFLOWS' for t in n.targets)))
        entry = next(row for row in workflows if row[0] == 'wave_joints')
        self.assertEqual(entry[1], 'waveJoints')
        self.assertIn('sine', entry[3])
        route = ast.get_source_segment(source, next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_navigation_changed'))
        self.assertIn('TabWaveJoints()', route)
        wrapper = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TabWaveJoints')
        self.assertIn("_pd_sdk_module('wave_joints')", ast.get_source_segment(source, wrapper))

    def test_actual_sibling_loader_imports_backend_and_builds_panel(self):
        source = Path(__file__).with_name('master_rigging_toolkit.py')
        tree = ast.parse(source.read_text())
        definitions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                       and node.name in ('_pd_sdk_module', 'TabWaveJoints')]
        namespace = {'QtWidgets': QtWidgets, 'uuid': uuid, '_POSE_SDK_MODULES': {}, '__file__': str(source)}
        maya = types.ModuleType('maya'); maya.cmds = self.commands
        with mock.patch.dict(sys.modules, {'maya': maya, 'maya.cmds': self.commands}):
            exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source), 'exec'), namespace)
            wrapper = namespace['TabWaveJoints']()
            try:
                self.assertIs(wrapper.panel.backend.cmds, self.commands)
                wrapper.panel.backend._time_ui_second = self.commands.ui_fps
                self.commands.selection = [self.commands.driver]; wrapper.panel.get_driver()
                self.commands.selection = [self.commands.joints[0]]; wrapper.panel.get_chain()
                wrapper.panel.build()
                self.assertEqual(len(wrapper.panel.backend.list_systems()), 1)
            finally:
                wrapper.close(); wrapper.deleteLater(); self.app.processEvents()

    def test_pick_chain_build_enable_and_mute(self):
        system = self.build()
        self.assertEqual(self.panel.joints.count(), 3)
        self.assertEqual(set(self.panel._channels()), {'ty'})
        self.panel.fields['offset'].setValue(90.)
        self.panel.fields['frequency'].setValue(0.)
        self.click('Apply settings / order'); self.click('Enable wave')
        for joint in self.commands.joints:
            self.assertAlmostEqual(self.commands.getAttr(joint+'.translateY'), 1.)
        self.click('Mute wave')
        for joint in self.commands.joints:
            self.assertAlmostEqual(self.commands.getAttr(joint+'.translateY'), 0.)
        self.assertEqual(self.api.list_systems(), [system])

    def test_append_deduplicates_and_up_down_reverse_define_exact_order(self):
        self.commands.tracked = True
        self.commands.selection = [self.commands.joints[2], self.commands.joints[0]]; self.click('Add selected')
        self.commands.selection = self.commands.joints; self.click('Add selected')
        self.assertEqual(self.panel._joints(), [self.commands.joints[i] for i in (2, 0, 1)])
        self.panel.joints.item(2).setSelected(True); self.click('Up')
        self.assertEqual(self.panel._joints(), [self.commands.joints[i] for i in (2, 1, 0)])
        self.click('Down')
        self.assertEqual(self.panel._joints(), [self.commands.joints[i] for i in (2, 0, 1)])
        self.click('Reverse')
        self.assertEqual(self.panel._joints(), [self.commands.joints[i] for i in (1, 0, 2)])
        self.assertTrue(self.commands.tracked)

    def test_output_checkboxes_gain_and_phase_drive_selected_channels(self):
        self.inputs()
        item, gain, phase = self.panel.axes['rz']
        self.assertFalse(gain.isEnabled())
        item.setCheckState(0, QtCore.Qt.Checked)
        self.assertTrue(gain.isEnabled())
        gain.setValue(-1.); phase.setValue(90.)
        self.panel.fields['envelope'].setValue(1.)
        self.panel.fields['frequency'].setValue(0.)
        self.click('Build wave')
        self.assertFalse(self.commands.warnings)
        for joint in self.commands.joints:
            self.assertAlmostEqual(self.commands.getAttr(joint+'.rotateZ'), -10.)

    def test_update_reorders_without_rounding_or_overwriting_animated_live_fields(self):
        system = self.build()
        self.commands.setAttr(self.commands.driver+'.waveOffset', 4.123456789)
        self.panel.load()
        curve = self.commands.add('timeKeys', 'animCurveTU')
        self.commands.setAttr(curve+'.output', 37.987654321)
        self.commands.connectAttr(curve+'.output', self.commands.driver+'.waveOffset')
        self.click('Reverse'); self.click('Apply settings / order')
        self.assertFalse(self.commands.warnings)
        self.assertAlmostEqual(self.commands.getAttr(self.commands.driver+'.waveOffset'), 37.987654321)
        self.assertEqual(self.api.current_settings(system)['joints'], list(reversed(self.commands.joints)))

    def test_saved_setup_reload_renames_and_delete_preserves_pose(self):
        system = self.build()
        renamed = self.commands.rename(self.commands.driver, '|renamed_ctrl')
        self.panel.refresh(system); self.click('Load')
        self.assertEqual(self.panel.driver.text(), renamed)
        self.click('Enable wave'); self.panel.fields['offset'].setValue(45.); self.click('Apply settings / order')
        poses = [self.commands.world(joint) for joint in self.commands.joints]
        self.click('Delete wave · keep current joint pose')
        self.assertFalse(self.commands.warnings)
        self.assertFalse(self.api.list_systems())
        for joint, matrix in zip(self.commands.joints, poses):
            self.assertEqual(self.commands.world(joint), matrix)
        self.assertIn('kept 3 joints', self.panel.status.text())

    def test_validate_changes_no_scene_state_and_errors_leave_inputs(self):
        self.inputs(); before = self.commands.snapshot()
        self.click('Validate')
        self.assertEqual(before, self.commands.snapshot())
        self.assertIn('Ready: 3 joints', self.panel.status.text())
        self.commands.selection = [self.commands.driver]
        self.click('Add selected')
        self.assertEqual(self.panel._joints(), self.commands.joints)
        self.assertIn('Choose a joint', self.panel.status.text())

    def test_select_buttons_and_unused_attribute_option(self):
        system = self.build()
        self.click('Select'); self.assertEqual(self.commands.selection, [self.commands.driver])
        self.click('Select listed joints'); self.assertEqual(self.commands.selection, self.commands.joints)
        self.click('Select wave nodes'); self.assertIn(system, self.commands.selection)
        self.panel.cleanup_attrs.setChecked(False)
        self.click('Delete wave · keep current joint pose')
        self.assertTrue(self.commands.objExists(self.commands.driver+'.waveOffset'))

    def test_changing_driver_or_channels_does_not_modify_loaded_setup(self):
        system = self.build(); before = self.commands.snapshot()
        self.panel.axes['rx'][0].setCheckState(0, QtCore.Qt.Checked)
        self.click('Apply settings / order')
        self.assertEqual(before, self.commands.snapshot())
        self.assertIn('output channels', self.panel.status.text())
        self.panel.prefix.setText('anotherWave')
        self.click('Apply settings / order')
        self.assertEqual(before, self.commands.snapshot())
        self.assertIn('must match', self.panel.status.text())
        self.assertEqual(self.api.list_systems(), [system])

    def test_falloff_fields_apply_on_existing_setup(self):
        system = self.build()
        self.panel.fields['falloff_position'].setValue(.5)
        self.panel.fields['falloff_power'].setValue(4.)
        self.click('Apply settings / order')
        self.assertFalse(self.commands.warnings)
        settings = self.api.current_settings(system)['settings']
        self.assertEqual(settings['falloff_power'], 4.)
        self.assertEqual(settings['falloff_position'], .5)
        self.assertFalse(self.commands.getAttr(self.commands.driver+'.waveFalloffPower', lock=True))

    def test_load_238_wave_and_apply_falloff_upgrades_original_graph(self):
        from test_wave_falloff import load_legacy
        system = self.api.unique(load_legacy(self.commands))
        self.panel.refresh(system); self.click('Load')
        self.assertIn('2.38 wave', self.panel.status.text())
        self.assertEqual(self.panel.fields['falloff_power'].value(), 0.)
        self.panel.fields['falloff_power'].setValue(2.)
        self.click('Apply settings / order')
        self.assertFalse(self.commands.warnings)
        self.assertTrue(self.api.current_settings(system)['falloff_available'])
        self.assertEqual(self.api.current_settings(system)['settings']['falloff_power'], 2.)


if __name__ == '__main__':
    unittest.main()
