"""Real Qt widgets with simulated Maya adapters, not a Maya runtime test.

Run separately with PySide6 available and QT_QPA_PLATFORM=offscreen.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import types

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE / 'attachments'))
from test_core import fixture

cmds = types.ModuleType('maya.cmds')
cmds.ls = lambda *args, **kwargs: []
cmds.file = lambda **kwargs: '/tmp/current_character.ma' if kwargs.get('sceneName') else False
cmds.workspace = lambda **kwargs: tempfile.gettempdir()
cmds.objExists = lambda name: False
cmds.select = lambda *args, **kwargs: None
errors = []
cmds.warning = lambda text: errors.append(text)
omui = types.ModuleType('maya.OpenMayaUI')
omui.MQtUtil = types.SimpleNamespace(mainWindow=lambda: 0)
om = types.ModuleType('maya.api.OpenMaya')
om.MSpace = types.SimpleNamespace(kWorld=0, kObject=1)
sys.modules.update({'maya': types.ModuleType('maya'), 'maya.cmds': cmds,
                    'maya.OpenMayaUI': omui, 'maya.api': types.ModuleType('maya.api'),
                    'maya.api.OpenMaya': om, 'maya.api.OpenMayaAnim': types.ModuleType('maya.api.OpenMayaAnim')})

import facial_system
from facial_system import core, fit, project, ui

Qt = ui.QtWidgets
app = Qt.QApplication.instance() or Qt.QApplication([])
app.setStyle('Fusion')
palette = ui.QtGui.QPalette()
for role, color in (('Window', '#343434'), ('WindowText', '#dedede'), ('Base', '#242424'),
                    ('AlternateBase', '#303030'), ('Text', '#dedede'),
                    ('Button', '#444444'), ('ButtonText', '#dedede')):
    palette.setColor(getattr(ui.QtGui.QPalette, role), ui.QtGui.QColor(color))
app.setPalette(palette)
Qt.QMessageBox.warning = lambda *args: errors.append(str(args[-1]))
Qt.QMessageBox.question = lambda *args: Qt.QMessageBox.Discard
ui.scene_ops.inspect = lambda: {'scene': '/tmp/current_character.ma', 'native_graph_present': True,
                               'joint_count': 339, 'skin_cluster_count': 7, 'skinned_meshes': ['headShape']}
ui.scene_ops.check_neutral = lambda *args: {'passed': True, 'message': 'Neutral inputs checked.'}

window = facial_system.show()
assert window.tabs.count() == 5
assert window.tabs.currentIndex() == 0
assert 'Facial System' in window.windowTitle()
assert facial_system.show(step='fit') is window
assert window.tabs.currentIndex() == 3
window.tabs.setCurrentIndex(0)
window.next_button.click()
assert window.tabs.currentIndex() == 1
window.back_button.click()
assert window.tabs.currentIndex() == 0

document, _ = fixture()
prototype = document['joints'][0]
document['joints'] = []
for index in range(331):
    row = copy.deepcopy(prototype)
    name = 'FACIAL_C_Joint_' + str(index).zfill(3)
    row['joint'] = {'uuid': name, 'path': '|rig|' + name, 'name': name}
    row['group_name'] = name + '_neutralVerts'
    document['joints'].append(row)
window.document = document
window._render()
assert window.table.rowCount() == 331
selected = []
ui.adapter.select_joint = lambda row: selected.append(('joint', row['joint']['name']))
ui.adapter.select_group = lambda doc, row: selected.append(('group', row['joint']['name']))
ui.adapter.selection_groups = lambda doc: {'mesh': [4, 5, 6, 7]}
window.table.cellWidget(83, 5).click()
window.table.cellWidget(29, 3).click()
assert selected == [('joint', 'FACIAL_C_Joint_083'), ('group', 'FACIAL_C_Joint_029')]
window.table.cellWidget(10, 4).click()
assert window.document['joints'][10]['method'] == 'manual'
assert 'Facial System' in window.windowTitle()
window.search.setText('Joint_003')
assert sum(not window.table.isRowHidden(i) for i in range(331)) == 1
window.search.clear()
window.mapping_table.item(0, 1).setText('Head_FitTarget')
assert window.target_mapping == {'mesh': 'Head_FitTarget'}
ui.adapter.selected_meshes = lambda: ['Head_FitTarget']
ui.adapter.mesh_path = lambda name: name
ui.adapter.assert_topology = lambda *args: None
mapping_button = window.mapping_table.cellWidget(0, 2)
mapping_button.click()
assert window.mapping_table.cellWidget(0, 2) is mapping_button
assert window.target_mapping == {'mesh': 'Head_FitTarget'}

calls = []
target = [[x + 3, y, z] for x, y, z in document['meshes']['mesh']['default_positions_cm']]
def preview(doc, mapping, **kwargs):
    calls.append(('preview', dict(mapping)))
    return {'schema': 'driveNeutralFitResult', 'version': 1, 'applied_to_scene': False,
            'joints': core.fit_positions(doc, {'mesh': target}), 'joint_count': len(doc['joints'])}
def apply(doc, mapping, **kwargs):
    calls.append(('apply', kwargs['reset'], kwargs['install_mesh']))
    kwargs['progress'](1, 2, 'Simulated Maya Apply')
    return {'passed': True, 'joint_count': len(doc['joints']), 'maximum_joint_position_error_cm': 0.,
            'maximum_mesh_position_error_cm': 0., 'applied_to_scene': True,
            'reset_to_template': kwargs['reset']}
fit.preview, fit.apply = preview, apply
window._preview_fit()
assert calls[-1] == ('preview', {'mesh': 'Head_FitTarget'})
window._apply_fit()
assert calls[-1] == ('apply', False, True)
assert window.tabs.isEnabled() and not window._busy
window._apply_fit(reset=True)
assert window._applied_reset
window.mapping_table.item(0, 1).setText('Head_FitTargetEdited')
assert not window._applied_reset and window.fit_result is None

def behavior(limit=None, progress=None):
    progress(1, 2, 'Simulated pose check')
    return {'passed': True, 'cases': 107, 'joint_channels': 1962,
            'maximum_errors': {'translation_cm': 0., 'rotation_degrees': 0., 'scale': 0.}}
ui.validation.check_behavior = behavior
window._run_behavior_check()
assert window.behavior_report['passed'] and 'PASS' in window.check_summary.text()
def failed_behavior(**kwargs):
    raise RuntimeError('Simulated check failure')
ui.validation.check_behavior = failed_behavior
window._guard(window._run_behavior_check)
assert window.behavior_report is None
assert window.tabs.isEnabled() and not window._busy
assert 'Simulated check failure' in window.check_summary.text()
errors.clear()  # This error is intentional.

with tempfile.TemporaryDirectory() as folder:
    baseline = copy.deepcopy(window.document)
    window.project_field.setText(folder)
    manifest = window._save_project()
    loaded = project.load(manifest)
    assert loaded['document'] == baseline
    assert loaded['mapping'] == {'mesh': 'Head_FitTargetEdited'}
    Qt.QFileDialog.getOpenFileName = lambda *args: (manifest, 'JSON (*.json)')
    ui.adapter.resolve = lambda identity, *args: identity['path']
    window._load_project()
    assert window.document == baseline
    assert window.target_mapping == loaded['mapping']
    scene_saves = []
    ui.scene_ops.save_scene = lambda path, **kwargs: scene_saves.append(path) or path
    Qt.QFileDialog.getSaveFileName = lambda *args: (str(Path(folder) / 'scenes/character.ma'), 'Maya ASCII (*.ma)')
    window._save_character_scene()
    assert len(scene_saves) == 1

ui.validation.check_fit = lambda *args, **kwargs: {
    'passed': True, 'joint_count': 331, 'mesh_count': 1,
    'maximum_joint_position_error_cm': 0., 'maximum_mesh_position_error_cm': 0.}
window._run_fit_check()
assert 'PASS' in window.check_summary.text()
window.mapping_table.item(0, 1).setText('AnotherTarget')
assert window.fit_check_report is None and window.fit_result is None

# Exercise the real cage-page widgets with a simulated scene layer. Native
# geometry evaluation remains for the Maya response-test button.
from test_cage_core import cage_fixture
from facial_system import cage, cage_core
state = [None]
cage_calls = []
def create_cage(source, **kwargs):
    cage_calls.append(('create', source, kwargs['around'], kwargs['rings']))
    kwargs['progress'](1, 2, 'Simulated cage creation')
    layer = cage_fixture()
    layer['source_snapshot'] = copy.deepcopy(window.document['meshes']['mesh'])
    layer['source'] = copy.deepcopy(layer['source_snapshot']['identity'])
    layer['create_seconds'] = .001
    layer['deformer'] = None
    state[0] = layer
    return layer
def bind_cage(data, **kwargs):
    cage_calls.append(('bind',))
    kwargs['progress'](1, 2, 'Simulated native bind')
    state[0] = copy.deepcopy(data)
    state[0]['deformer'] = {'uuid': 'nativeWrap', 'path': 'nativeWrap'}
    state[0]['bind_seconds'] = .002
    return state[0]
def layer_settings(data, **kwargs):
    state[0] = copy.deepcopy(data)
    state[0].update(kwargs)
    return state[0]
cage.load = lambda *args: copy.deepcopy(state[0])
cage.create, cage.bind = create_cage, bind_cage
cage.resolve = lambda info: info['path']
cage.set_layer = layer_settings
cage.inspect = lambda data: {'bound': bool(data['deformer']), 'bind_seconds': data.get('bind_seconds')}
cage.test_response = lambda data: {'passed': True, 'maximum_output_move_cm': .2, 'maximum_restore_error_cm': 0.}
cage.reset = lambda data, **kwargs: {'reset': True}
cage.mirror = lambda data, direction: {'mirror': direction}
cage.bake = lambda data, **kwargs: '|Head_FitTarget1|Head_FitTargetShape1'
cage.export = lambda data: cage_core.export_data(data, data['rest_cage_points_cm'], data['rest_cage_world_matrix_cm'])
restored_symmetry = []
cage.enable_symmetry = lambda data: {'symmetry': 0, 'about': 'world', 'axis': 'y'}
cage.restore_symmetry = lambda previous: restored_symmetry.append(previous)
panel = window.wrap_panel
panel.source.setText('headShape')
panel._create()
assert cage_calls[-1] == ('create', 'headShape', 12, 12)
assert window.tabs.isEnabled() and not window._busy
panel._bind()
assert cage_calls[-1] == ('bind',)
panel.weight.setValue(.6)
assert state[0]['weight'] == .6
panel._enable_symmetry()
panel.restore_symmetry()
assert len(restored_symmetry) == 1
panel._mirror('positive')
panel._reset()
panel._test_response()
assert 'true' in panel.status.toPlainText()
target = panel._bake()
assert window.target_mapping['mesh'] == target
assert window.tabs.currentIndex() == ui.STEP_IDS.index('fit')
with tempfile.TemporaryDirectory() as folder:
    window.project_field.setText(folder)
    manifest = window._save_project()
    loaded = project.load(manifest)
    assert loaded['wrap_data']['rest_cage_points_cm'] == state[0]['rest_cage_points_cm']
    assert loaded['manifest']['current_step_id'] == 'fit'
    assert loaded['manifest']['current_step'] == 2
window.tabs.setCurrentIndex(ui.STEP_IDS.index('wrap'))
app.processEvents()
if len(sys.argv) > 1:
    window.grab().save(sys.argv[1])
assert not errors, errors
window.dirty = False
window.close()
print(json.dumps({'qt': 'PySide6, offscreen', 'rows': 331, 'workflow_steps': 5,
                  'shared_window_and_navigation': True, 'manual_group_editing': True,
                  'preview_apply_reset_dispatch': True, 'project_save_load': True,
                  'scene_save_dispatch': True, 'failed_check_restores_controls': True,
                  'mapping_changes_clear_old_results': True, 'mapping_row_sender_retained': True,
                  'cage_create_bind_mirror_reset_test_bake_dispatch': True,
                  'baked_target_maps_to_joint_fitting': True, 'cage_project_round_trip': True,
                  'maya_runtime_tested': False}, indent=2))
