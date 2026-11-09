"""Maya workflow sharing one neutral document, cage layer, and target mapping."""
import json
from pathlib import Path

import maya.cmds as cmds

from . import __version__, core, fit, project, scene_ops, validation
from . import scene_adapter as adapter
from .neutral_editor import NeutralDataEditor, QtCore, QtGui, QtWidgets, maya_window
from .cage_ui import CagePanel

OBJECT_NAME = 'FacialSystem_Workflow_v1'
STEP_NAMES = ('Scene Setup', 'Vertex Groups', 'Cage Wrap', 'Fit Joints', 'Check & Save')
STEP_IDS = ('setup', 'groups', 'wrap', 'fit', 'check')
_dialog = None


class FacialSystemWindow(NeutralDataEditor):
    def __init__(self, parent=None):
        self.behavior_report = None
        self.fit_check_report = None
        self.project_scene = ''
        self._applied_reset = False
        self._historical_fit = False
        self._pending_cage_target = None
        self._ready = False
        super(FacialSystemWindow, self).__init__(parent=parent, auto_detect=False)
        self.setObjectName(OBJECT_NAME)
        self.resize(1230, 850)
        self._ready = True
        self._refresh_scene()
        self._update_workflow()

    def _build(self):
        super(FacialSystemWindow, self)._build()
        outer = self.layout()
        title = QtWidgets.QLabel('FACIAL SYSTEM   |   ' + __version__)
        title.setStyleSheet('font-size: 20px; font-weight: 600; padding: 4px 0;')
        outer.insertWidget(0, title)
        subtitle = QtWidgets.QLabel('Define neutral attachments, fit the mesh with a cage, update joints, then check and save.')
        subtitle.setWordWrap(True)
        outer.insertWidget(1, subtitle)
        bar = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(0, 3, 0, 6)
        row.addWidget(QtWidgets.QLabel('Project folder'))
        self.project_field = QtWidgets.QLineEdit(str(Path(cmds.workspace(query=True, rootDirectory=True)) /
                                                   'facial_system' / 'character'))
        row.addWidget(self.project_field, 1)
        row.addWidget(self._button('Browse...', self._browse_project))
        row.addWidget(self._button('Load Project...', self._load_project))
        row.addWidget(self._button('Save Project', self._save_project))
        outer.insertWidget(2, bar)
        self.tabs.setTabText(0, '2  Vertex Groups')
        self.tabs.setTabText(1, '4  Fit Joints')
        self.tabs.insertTab(0, self._setup_page(), '1  Scene Setup')
        self.wrap_panel = CagePanel(self)
        self.tabs.insertTab(2, self.wrap_panel, '3  Cage Wrap')
        self.tabs.addTab(self._check_page(), '5  Check & Save')
        self.tabs.setCurrentIndex(0)
        footer = QtWidgets.QHBoxLayout()
        self.back_button = self._button('Back', lambda: self.tabs.setCurrentIndex(self.tabs.currentIndex() - 1))
        footer.addWidget(self.back_button)
        self.workflow_status = QtWidgets.QLabel('Start with the current scene or the bundled template.')
        self.workflow_status.setWordWrap(True)
        footer.addWidget(self.workflow_status, 1)
        self.next_button = self._button('Next: Vertex Groups', lambda: self.tabs.setCurrentIndex(self.tabs.currentIndex() + 1))
        footer.addWidget(self.next_button)
        outer.addLayout(footer)
        self.tabs.currentChanged.connect(self._update_workflow)
        self.fit_options.toggled.connect(self._fit_settings_changed)

    def _note(self, text):
        label = QtWidgets.QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet('padding: 10px; background: #293d4c; color: #e7f2fa;')
        return label

    def _setup_page(self):
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        layout.addWidget(self._note('Already have the rig, driveNeutralData.json, and Head_FitTarget? '
                                   'Keep the current scene and choose Load Existing Neutral JSON below. '
                                   'It opens the fitting step without recapturing your defaults.'))
        self.scene_info = QtWidgets.QLabel('Reading current scene...')
        self.scene_info.setWordWrap(True)
        self.scene_info.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self.scene_info)
        scene_group = QtWidgets.QGroupBox('Scene')
        actions = QtWidgets.QHBoxLayout(scene_group)
        actions.addWidget(self._button('Use / Refresh Current Scene', self._refresh_scene))
        actions.addWidget(self._button('Open Bundled Template', self._open_template))
        actions.addWidget(self._button('Open Saved Project Scene', self._open_project_scene))
        layout.addWidget(scene_group)
        data_group = QtWidgets.QGroupBox('Neutral data')
        actions = QtWidgets.QHBoxLayout(data_group)
        actions.addWidget(self._button('Load Existing Neutral JSON...', self._resume_neutral))
        actions.addWidget(self._button('Define / Review Vertex Groups', lambda: self.tabs.setCurrentIndex(1)))
        actions.addWidget(self._button('Check Neutral Inputs', self._check_neutral))
        layout.addWidget(data_group)
        target_group = QtWidgets.QGroupBox('New shape')
        actions = QtWidgets.QVBoxLayout(target_group)
        actions.addWidget(QtWidgets.QLabel('To make another target, select the original head mesh, create an independent copy, '
                                           'then sculpt its vertices while retaining vertex IDs and connectivity.'))
        actions.itemAt(0).widget().setWordWrap(True)
        actions.addWidget(self._button('Create Head_FitTarget from Selected Mesh', self._create_target))
        actions.addWidget(self._button('Open Cage Wrap', lambda: self.tabs.setCurrentIndex(STEP_IDS.index('wrap'))))
        layout.addWidget(target_group)
        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(self._button('Select Facial GUI', lambda: scene_ops.select_controls('face', self.document)))
        controls.addWidget(self._button('Select Neck / Head Drivers', lambda: scene_ops.select_controls('neck', self.document)))
        layout.addLayout(controls)
        self.setup_status = QtWidgets.QLabel('No new capture is made when this window opens.')
        self.setup_status.setWordWrap(True)
        layout.addWidget(self.setup_status)
        layout.addStretch(1)
        return panel

    def _check_page(self):
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        layout.addWidget(self._note('Behavior Check tests the expression and neck solver using the current neutral translations. '
                                   'Fit Geometry Check compares the neutral joints and visible meshes with your targets. '
                                   'Review expressions, skin deformation, and playback in the viewport before using the character.'))
        row = QtWidgets.QHBoxLayout()
        self.case_limit = QtWidgets.QComboBox()
        self.case_limit.addItem('All 107 reference poses', None)
        self.case_limit.addItem('First 40 reference poses', 40)
        row.addWidget(self.case_limit)
        row.addWidget(self._button('Run Behavior Check', self._run_behavior_check))
        row.addWidget(self._button('Check Fit Geometry', self._run_fit_check))
        row.addWidget(self._button('Check Neutral Inputs', self._check_neutral))
        layout.addLayout(row)
        self.check_summary = QtWidgets.QLabel('No checks run in this window yet.')
        self.check_summary.setWordWrap(True)
        layout.addWidget(self.check_summary)
        self.report_view = QtWidgets.QPlainTextEdit()
        self.report_view.setReadOnly(True)
        self.report_view.setPlaceholderText('Check results appear here. Saved reports are in the project reports folder.')
        layout.addWidget(self.report_view, 1)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self._button('Save Character Scene As...', self._save_character_scene))
        row.addWidget(self._button('Save Project + Reports', self._save_project))
        row.addWidget(self._button('Export Fit Result...', self._export_fit))
        row.addWidget(self._button('Select Facial GUI', lambda: scene_ops.select_controls('face', self.document)))
        layout.addLayout(row)
        layout.addWidget(QtWidgets.QLabel('The saved native rig animates with stock Maya nodes. DNA and this tool window are not needed for playback.'))
        return panel

    def _set_title(self):
        self.setWindowTitle('Facial System ' + __version__ + (' *' if self.dirty else ''))

    def _update_workflow(self, *args):
        if not self._ready:
            return
        index = self.tabs.currentIndex()
        self.back_button.setEnabled(index > 0 and not self._busy)
        last = len(STEP_NAMES) - 1
        self.next_button.setEnabled(index < last and not self._busy)
        self.next_button.setText('Next: ' + STEP_NAMES[min(index + 1, last)] if index < last else 'Last Step')
        count = len(self.document['joints']) if self.document else 0
        mapped = sum(bool(name.strip()) for name in self.target_mapping.values())
        result = 'no fit result'
        if self.fit_result:
            result = ('saved fit result; recheck scene' if self._historical_fit else
                      'fit applied' if self.fit_result.get('applied_to_scene') else 'positions previewed')
        self.workflow_status.setText('{} joints | {} target meshes | {}'.format(count, mapped, result))
        self._set_title()

    def _invalidate_checks(self):
        self.behavior_report = None
        self.fit_check_report = None
        if hasattr(self, 'check_summary'):
            self.check_summary.setText('Settings changed. Run checks for the current scene before saving a final character.')
            self.report_view.clear()

    def _mark_dirty(self):
        super(FacialSystemWindow, self)._mark_dirty()
        self.fit_result = None
        self._applied_reset = False
        self._invalidate_checks()
        self.fit_status.setText('Vertex groups changed. Preview positions again before applying.')
        self._update_workflow()

    def _render(self):
        super(FacialSystemWindow, self)._render()
        if hasattr(self, 'wrap_panel'):
            self.wrap_panel.suggest_source(self.document)
        self._update_workflow()

    def _mapping_changed(self, item):
        super(FacialSystemWindow, self)._mapping_changed(item)
        if not getattr(self, '_mapping_filling', False):
            self._applied_reset = False
            self._invalidate_checks()
            self._update_workflow()

    def _map_selected(self, key):
        super(FacialSystemWindow, self)._map_selected(key)
        self._applied_reset = False
        self._invalidate_checks()
        self._update_workflow()

    def _fit_settings_changed(self, *args):
        self.fit_result = None
        self._applied_reset = False
        self._invalidate_checks()
        self.fit_status.setText('Fit settings changed. Preview positions again before applying.')
        self._update_workflow()

    def _detect(self):
        scene_ops.check_neutral(self.document)
        try:
            return super(FacialSystemWindow, self)._detect()
        finally:
            self._update_workflow()

    def _add_joints(self):
        scene_ops.check_neutral(self.document)
        return super(FacialSystemWindow, self)._add_joints()

    def _preview_fit(self):
        self.fit_result = None
        self._invalidate_checks()
        super(FacialSystemWindow, self)._preview_fit()
        self._applied_reset = False
        self._historical_fit = False
        self._update_workflow()

    def _apply_fit(self, reset=False):
        self.fit_result = None
        self._applied_reset = False
        self._invalidate_checks()
        try:
            super(FacialSystemWindow, self)._apply_fit(reset=reset)
            self._applied_reset = reset
            self._historical_fit = False
        finally:
            self._update_workflow()

    def _guard(self, action):
        if self._busy:
            return
        try:
            return action()
        except adapter.Cancelled as exc:
            message = str(exc)
            self.summary.setText(message)
            self.fit_status.setText(message)
            self.setup_status.setText(message)
            self.check_summary.setText(message)
            self.wrap_panel.status.setPlainText(message)
        except Exception as exc:
            message = str(exc)
            self.summary.setText(message)
            self.fit_status.setText(message)
            self.setup_status.setText(message)
            self.check_summary.setText(message)
            self.wrap_panel.status.setPlainText(message)
            cmds.warning('Facial System: ' + message)
            QtWidgets.QMessageBox.warning(self, 'Facial System', message)

    def _save(self):
        result = super(FacialSystemWindow, self)._save()
        self._update_workflow()
        return result

    def _load_data(self, data, path):
        super(FacialSystemWindow, self)._load_data(data, path)
        self._applied_reset = False
        self._invalidate_checks()
        self.wrap_panel.suggest_source(self.document)
        if self._pending_cage_target:
            pending = self._pending_cage_target
            self._map_cage_target(pending['snapshot'], pending['target'])
        self._update_workflow()

    def _new_capture(self):
        previous = self.document
        super(FacialSystemWindow, self)._new_capture()
        if self.document is None and previous is not None:
            self._invalidate_checks()
            self._update_workflow()

    def _refresh_scene(self):
        info = scene_ops.inspect()
        self.scene_info.setText('Scene: {}\nNative facial rig: {}\n{} joints | {} skinClusters | {} skinned mesh shapes'.format(
            info['scene'] or '(untitled)', 'Ready' if info['native_graph_present'] else 'Open one NFRv1 rig',
            info['joint_count'], info['skin_cluster_count'], len(info['skinned_meshes'])))
        self._set_sources(info['skinned_meshes'])
        self._historical_fit = bool(self.fit_result)
        self._guard(self.wrap_panel.refresh)
        self._invalidate_checks()
        self.setup_status.setText('Current scene inspected. Load saved neutral data, or continue to Vertex Groups for a new capture.')
        self._update_workflow()
        return info

    def _check_neutral(self):
        report = scene_ops.check_neutral(self.document)
        self.setup_status.setText(report['message'])
        self.fit_status.setText(report['message'])
        return report

    def _resume_neutral(self):
        previous = self.document
        self._load()
        if self.document is not None and self.document is not previous:
            self.tabs.setCurrentIndex(STEP_IDS.index('fit'))

    def _confirm_scene_change(self):
        if not self._confirm_replace():
            return False
        if not cmds.file(query=True, modified=True):
            return True
        choice = QtWidgets.QMessageBox.question(self, 'Unsaved Maya scene',
                    'Save the current Maya scene before opening another scene?',
                    QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel,
                    QtWidgets.QMessageBox.Save)
        if choice == QtWidgets.QMessageBox.Cancel:
            return False
        if choice == QtWidgets.QMessageBox.Save:
            return bool(self._save_character_scene())
        return True

    def _open_template(self):
        if not self._confirm_scene_change():
            return
        self.wrap_panel.restore_symmetry()
        scene_ops.open_template(discard_current=True)
        self._pending_cage_target = None
        self.document = None
        self.fit_result = None
        self.target_mapping = {}
        self.dirty = False
        self._render()
        self._refresh_scene()
        self.setup_status.setText('Bundled template opened. Save a character copy, then load or define neutral groups.')

    def _open_project_scene(self):
        if not self.project_scene or not Path(self.project_scene).is_file():
            raise ValueError('Load a project with an existing saved Maya scene first')
        if not self._confirm_scene_change():
            return
        self.wrap_panel.restore_symmetry()
        cmds.file(self.project_scene, open=True, force=True, executeScriptNodes=False)
        self.fit_result = None
        self._refresh_scene()
        self.setup_status.setText('Project scene opened. Neutral data and target mapping were retained; run fresh checks.')

    def _create_target(self):
        scene_ops.check_neutral(self.document)
        name = scene_ops.create_fit_target()
        if self.document:
            self.target_mapping.update(fit.guess_target(self.document))
            self._sync_mapping()
        self.fit_result = None
        self._invalidate_checks()
        self._update_workflow()
        self.setup_status.setText('Created independent target: {}. Sculpt positions while retaining vertex IDs.'.format(name))

    def _browse_project(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Choose Facial System project folder', self.project_field.text())
        if folder:
            self.project_field.setText(folder)

    def _save_project(self):
        if not self.document:
            raise ValueError('Load or define neutral vertex groups before saving a project')
        folder = self.project_field.text().strip()
        if not folder:
            raise ValueError('Choose a project folder first')
        manifest = project.save(folder, self.document, self.target_mapping,
                    scene=cmds.file(query=True, sceneName=True), install_mesh=self.fit_options.isChecked(),
                    fit_result=self.fit_result, behavior_report=self.behavior_report,
                    fit_check=self.fit_check_report,
                    current_step={'setup': 0, 'groups': 1, 'wrap': 2, 'fit': 2, 'check': 3}[STEP_IDS[self.tabs.currentIndex()]],
                    current_step_id=STEP_IDS[self.tabs.currentIndex()], wrap_data=self.wrap_panel.export_current())
        self.file_field.setText(str(Path(manifest).parent / 'data' / 'driveNeutralData.json'))
        self.dirty = False
        self.project_scene = cmds.file(query=True, sceneName=True)
        self.setup_status.setText('Project saved: ' + manifest)
        self.check_summary.setText('Project and available reports saved. Use Save Character Scene As to save Maya scene edits.')
        self._update_workflow()
        return manifest

    def _load_project(self):
        if not self._confirm_replace():
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Load Facial System project',
                    str(Path(self.project_field.text()) / project.PROJECT_FILE), 'JSON (*.json)')
        if not path:
            return
        loaded = project.load(path)
        self._load_data(loaded['document'], loaded['neutral_path'])
        self.project_field.setText(loaded['root'])
        self.target_mapping = loaded['mapping']
        self.fit_options.setChecked(loaded['manifest'].get('install_mesh', True))
        self._sync_mapping()
        self.project_scene = loaded['scene']
        # Reports are history. Scene edits can occur outside this window;
        # fresh checks are required before any current PASS is displayed.
        self.fit_result = loaded['reports'].get('fit_result')
        self._historical_fit = bool(self.fit_result)
        self._applied_reset = bool(self.fit_result and self.fit_result.get('reset_to_template'))
        self._invalidate_checks()
        step_id = loaded['manifest'].get('current_step_id')
        if step_id not in STEP_IDS:
            legacy = ('setup', 'groups', 'fit', 'check')
            step_id = legacy[max(0, min(3, int(loaded['manifest'].get('current_step', 0))))]
        self.tabs.setCurrentIndex(STEP_IDS.index(step_id))
        self._guard(self.wrap_panel.refresh)
        if loaded.get('wrap_data') and self.wrap_panel.data is None:
            self.wrap_panel.source.setText(loaded['wrap_data']['source']['path'])
            self.wrap_panel.status.setPlainText('Saved cage data found. Open the saved Maya project scene to resume its native cage layer.')
        self.setup_status.setText('Project loaded. Maya scene was not changed. Saved scene: ' + (self.project_scene or '(none)'))
        self._update_workflow()

    def _run_job(self, title, action):
        progress = QtWidgets.QProgressDialog(title, 'Cancel', 0, 100, self)
        progress.setWindowTitle(title)
        progress.setWindowModality(QtCore.Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        self._busy = True
        self.tabs.setEnabled(False)
        progress.show()
        def report(value, total, text):
            progress.setLabelText(text)
            progress.setValue(min(99, int(100 * value / max(1, total))))
            QtWidgets.QApplication.processEvents()
            return not progress.wasCanceled()
        try:
            return action(report)
        finally:
            progress.close()
            progress.deleteLater()
            self._busy = False
            self.tabs.setEnabled(True)
            self._update_workflow()

    def _run_behavior_check(self):
        self.behavior_report = None
        self.check_summary.setText('Checking facial behavior...')
        self.report_view.clear()
        self.behavior_report = self._run_job('Check facial behavior',
            lambda progress: validation.check_behavior(limit=self.case_limit.currentData(), progress=progress))
        report = self.behavior_report
        errors = report['maximum_errors']
        self.check_summary.setText('Behavior {}: {} poses, {} channels. Max T {:.6f} cm | R {:.6f} deg | S {:.3g}.'.format(
            'PASS' if report['passed'] else 'FAIL', report['cases'], report['joint_channels'],
            errors['translation_cm'], errors['rotation_degrees'], errors['scale']))
        self.report_view.setPlainText(json.dumps(report, indent=2))
        return report

    def _run_fit_check(self):
        self.fit_check_report = None
        self.check_summary.setText('Checking neutral fit geometry...')
        self.report_view.clear()
        if not self.document:
            raise ValueError('Load neutral data and map your target before checking the fit')
        self.fit_check_report = validation.check_fit(self.document, self.target_mapping,
                    install_mesh=self.fit_options.isChecked(), reset=self._applied_reset)
        report = self.fit_check_report
        self.check_summary.setText('Fit geometry {}: {} joints, {} meshes. Max joint {:.6f} cm | mesh {:.6f} cm.'.format(
            'PASS' if report['passed'] else 'FAIL', report['joint_count'], report['mesh_count'],
            report['maximum_joint_position_error_cm'], report['maximum_mesh_position_error_cm']))
        self.report_view.setPlainText(json.dumps(report, indent=2))
        return report

    def _save_character_scene(self):
        default = Path(self.project_field.text()) / 'scenes' / 'character_fitted.ma'
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save character scene as', str(default), 'Maya ASCII (*.ma)')
        if not path:
            return None
        result = scene_ops.save_scene(path, overwrite=True)
        self.project_scene = result
        self.setup_status.setText('Character scene saved: ' + result)
        self.check_summary.setText('Character scene saved: ' + result)
        return result

    def _map_cage_target(self, snapshot, target):
        if not self.document:
            return False
        meshes = self.document['meshes']
        direct = [key for key, mesh in meshes.items() if mesh['identity']['uuid'] == snapshot['identity']['uuid']]
        matches = direct or [key for key, mesh in meshes.items()
                             if mesh['topology_sha256'] == snapshot['topology_sha256']]
        if len(matches) != 1:
            return False
        self.target_mapping[matches[0]] = target
        self._sync_mapping()
        self.fit_result = None
        self._applied_reset = False
        self._invalidate_checks()
        self._update_workflow()
        return True

    def _use_cage_target(self, data, target):
        snapshot = data['source_snapshot']
        self._pending_cage_target = {'snapshot': snapshot, 'target': target}
        mapped = self._map_cage_target(snapshot, target)
        self.tabs.setCurrentIndex(STEP_IDS.index('fit'))
        self.fit_status.setText(('Baked target mapped: ' if mapped else 'Baked target: ') + target +
            ('. Preview joint positions next.' if mapped else '. Load neutral JSON, then map this selected target to the head row.'))

    def closeEvent(self, event):
        if self._busy or not self._confirm_replace():
            event.ignore()
            return
        try:
            self.wrap_panel.restore_symmetry()
        except Exception as exc:
            cmds.warning('Facial System could not restore prior symmetry settings: ' + str(exc))
        event.accept()


def _existing_window():
    parent = maya_window()
    found = parent.findChild(QtWidgets.QDialog, OBJECT_NAME) if parent else None
    if found is not None:
        return found
    return _dialog


def close_window():
    existing = _existing_window()
    if existing is None:
        return True
    try:
        return bool(existing.close())
    except RuntimeError:
        return True


def show(step=None):
    global _dialog
    if step is not None and step not in STEP_IDS:
        raise ValueError('Step must be setup, groups, wrap, fit, or check')
    existing = _existing_window()
    try:
        visible = existing is not None and existing.isVisible()
    except RuntimeError:
        visible = False
    if visible:
        _dialog = existing
    else:
        _dialog = FacialSystemWindow(parent=maya_window())
        _dialog.show()
    if step is not None:
        _dialog.tabs.setCurrentIndex(STEP_IDS.index(step))
    _dialog.raise_()
    _dialog.activateWindow()
    return _dialog
