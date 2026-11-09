"""Maya table editor for driveNeutralData.json. No external Maya plug-ins.

Internal reusable vertex-group and fitting pages for facial_system.show().
"""
import copy
from pathlib import Path

from maya import OpenMayaUI
import maya.cmds as cmds
try:
    from PySide2 import QtCore, QtGui, QtWidgets
    from shiboken2 import wrapInstance
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import wrapInstance

from . import core
from . import scene_adapter as adapter

OBJECT_NAME = 'DriveNeutralDataEditor_v1_1_1'
VERSION = '1.1.1'
_dialog = None


def maya_window():
    pointer = OpenMayaUI.MQtUtil.mainWindow()
    return wrapInstance(int(pointer), QtWidgets.QWidget) if pointer else None


class NeutralDataEditor(QtWidgets.QDialog):
    def __init__(self, parent=None, auto_detect=True):
        super(NeutralDataEditor, self).__init__(parent)
        self.setObjectName(OBJECT_NAME)
        self.setWindowTitle('Drive Neutral Data ' + VERSION)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Window)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.resize(1130, 730)
        self.document = None
        self.dirty = False
        self._filling = False
        self._busy = False
        self.sources = []
        self.target_mapping = {}
        self.fit_result = None
        self._buttons = []
        self._build()
        self._set_sources(adapter.skin_meshes() or adapter.selected_meshes())
        if auto_detect and self.sources:
            QtCore.QTimer.singleShot(0, lambda: self._guard(self._detect))

    def _button(self, text, callback, parent=None):
        button = QtWidgets.QPushButton(text, parent)
        button.clicked.connect(lambda checked=False: self._guard(callback))
        self._buttons.append(button)
        return button

    def _build(self):
        outer = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        outer.addWidget(self.tabs)
        definition = QtWidgets.QWidget()
        self.tabs.addTab(definition, 'Define Vertex Groups')
        layout = QtWidgets.QVBoxLayout(definition)
        notice = QtWidgets.QLabel('Translation only. Put the rig in neutral before the first capture. '
                                 'Update replaces a row with your selected vertices; captured defaults stay fixed.')
        notice.setWordWrap(True)
        notice.setStyleSheet('padding: 8px; background: #293d4c; color: #e7f2fa;')
        layout.addWidget(notice)

        source_row = QtWidgets.QHBoxLayout()
        source_row.addWidget(QtWidgets.QLabel('Source meshes'))
        self.source_field = QtWidgets.QLineEdit()
        self.source_field.setReadOnly(True)
        source_row.addWidget(self.source_field, 1)
        source_row.addWidget(self._button('Use Selected Meshes', self._selected_sources))
        source_row.addWidget(self._button('All Skin Meshes', lambda: self._set_sources(adapter.skin_meshes())))
        layout.addLayout(source_row)

        settings = QtWidgets.QHBoxLayout()
        self.scope = QtWidgets.QComboBox()
        self.scope.addItem('Auto: connected facial joints / skin influences', 'auto')
        self.scope.addItem('Skin influences of source meshes', 'skin')
        self.scope.addItem('Selected joints + children', 'selected')
        settings.addWidget(self.scope, 1)
        settings.addWidget(QtWidgets.QLabel('Max auto vertices'))
        self.max_vertices = QtWidgets.QSpinBox()
        self.max_vertices.setRange(1, 2000)
        self.max_vertices.setValue(32)
        settings.addWidget(self.max_vertices)
        settings.addWidget(QtWidgets.QLabel('Min / peak weight'))
        self.threshold = QtWidgets.QDoubleSpinBox()
        self.threshold.setRange(0, 1)
        self.threshold.setSingleStep(.05)
        self.threshold.setValue(.25)
        settings.addWidget(self.threshold)
        self.fallback = QtWidgets.QCheckBox('Nearest fallback')
        self.fallback.setChecked(True)
        self.fallback.setToolTip('Unweighted joints get a connected nearby patch, marked Review.')
        settings.addWidget(self.fallback)
        settings.addWidget(self._button('Auto-detect Groups', self._detect))
        layout.addLayout(settings)

        tools = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText('Filter joint, group, or source...')
        self.search.textChanged.connect(self._filter)
        tools.addWidget(self.search, 1)
        tools.addWidget(self._button('Add Selected Joints', self._add_joints))
        tools.addWidget(self._button('Remove Selected Rows', self._remove_rows))
        tools.addWidget(self._button('Validate Scene', self._validate_scene))
        tools.addWidget(self._button('New Capture', self._new_capture))
        layout.addLayout(tools)

        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['Joint', 'Vertex group', 'Verts', 'Select vertices',
                                             'Update group', 'Select joint', 'Source'])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setColumnWidth(0, 250)
        self.table.setColumnWidth(1, 260)
        self.table.setColumnWidth(2, 52)
        self.table.setColumnWidth(3, 105)
        self.table.setColumnWidth(4, 105)
        self.table.setColumnWidth(5, 80)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self._item_changed)
        self.table.itemSelectionChanged.connect(self._details)
        layout.addWidget(self.table, 1)

        self.details = QtWidgets.QLabel('No row selected')
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self.details)
        self.summary = QtWidgets.QLabel('Ready - source data only; no joints or skin weights are changed.')
        layout.addWidget(self.summary)

        file_row = QtWidgets.QHBoxLayout()
        self.file_field = QtWidgets.QLineEdit(adapter.default_path())
        file_row.addWidget(self.file_field, 1)
        file_row.addWidget(self._button('Save JSON', self._save))
        file_row.addWidget(self._button('Save As...', self._save_as))
        file_row.addWidget(self._button('Load JSON...', self._load))
        layout.addLayout(file_row)
        self._build_fit_tab()

    def _build_fit_tab(self):
        panel = QtWidgets.QWidget()
        self.tabs.addTab(panel, 'Fit New Shape')
        layout = QtWidgets.QVBoxLayout(panel)
        label = QtWidgets.QLabel('Load your original driveNeutralData.json, map the head to Head_FitTarget, '
                                'then Preview Positions. Apply updates the native rig; rotations stay fixed. '
                                'Use a saved copy of the rig for this first Maya test.')
        label.setWordWrap(True)
        label.setStyleSheet('padding: 8px; background: #293d4c; color: #e7f2fa;')
        layout.addWidget(label)
        row = QtWidgets.QHBoxLayout()
        self.fit_json_label = QtWidgets.QLineEdit(self.file_field.text())
        self.fit_json_label.setReadOnly(True)
        self.file_field.textChanged.connect(self.fit_json_label.setText)
        row.addWidget(self.fit_json_label, 1)
        row.addWidget(self._button('Load Neutral JSON...', self._load))
        layout.addLayout(row)
        self.mapping_table = QtWidgets.QTableWidget(0, 3)
        self.mapping_table.setHorizontalHeaderLabels(['Captured source mesh', 'Edited target mesh', 'Map selected'])
        self.mapping_table.setColumnWidth(0, 300)
        self.mapping_table.setColumnWidth(1, 530)
        self.mapping_table.horizontalHeader().setStretchLastSection(True)
        self.mapping_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.mapping_table.itemChanged.connect(self._mapping_changed)
        layout.addWidget(self.mapping_table, 1)
        self.fit_options = QtWidgets.QCheckBox('Install edited rest mesh and retain existing skin weights')
        self.fit_options.setChecked(True)
        layout.addWidget(self.fit_options)
        self.fit_moved_only = QtWidgets.QCheckBox('Preview only joints whose positions change')
        self.fit_moved_only.setChecked(True)
        layout.addWidget(self.fit_moved_only)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self._button('Preview Positions', self._preview_fit))
        buttons.addWidget(self._button('Clear Preview', self._clear_fit_preview))
        buttons.addWidget(self._button('Apply Neutral Fit', self._apply_fit))
        buttons.addWidget(self._button('Reset to Saved Template', lambda: self._apply_fit(reset=True)))
        buttons.addWidget(self._button('Export Fit Result...', self._export_fit))
        layout.addLayout(buttons)
        self.fit_status = QtWidgets.QLabel('Load the saved neutral JSON. Blank targets keep their captured defaults.')
        self.fit_status.setWordWrap(True)
        self.fit_status.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self.fit_status)

    def _sync_mapping(self):
        self._mapping_filling = True
        try:
            meshes = self.document['meshes'] if self.document else {}
            self.target_mapping = {key: value for key, value in self.target_mapping.items() if key in meshes}
            if meshes and not self.target_mapping:
                try:
                    from . import fit as fitter
                    self.target_mapping.update(fitter.guess_target(self.document))
                except (RuntimeError, ValueError):
                    pass
            self.mapping_keys = list(meshes)
            self.mapping_table.setRowCount(0)
            self.mapping_table.setRowCount(len(meshes))
            for index, key in enumerate(self.mapping_keys):
                mesh = meshes[key]
                item = QtWidgets.QTableWidgetItem(mesh['identity']['name'])
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                item.setToolTip(mesh['identity']['path'])
                self.mapping_table.setItem(index, 0, item)
                self.mapping_table.setItem(index, 1, QtWidgets.QTableWidgetItem(self.target_mapping.get(key, '')))
                button = QtWidgets.QPushButton('Use Selected')
                button.clicked.connect(lambda checked=False, key=key: self._guard(lambda: self._map_selected(key)))
                self.mapping_table.setCellWidget(index, 2, button)
        finally:
            self._mapping_filling = False

    def _mapping_changed(self, item):
        if getattr(self, '_mapping_filling', False) or item.column() != 1:
            return
        self.target_mapping[self.mapping_keys[item.row()]] = item.text().strip()
        self.fit_result = None
        self.fit_status.setText('Target mapping changed. Preview again before applying.')

    def _map_selected(self, key):
        selected = adapter.selected_meshes()
        if len(selected) != 1:
            raise ValueError('Select exactly one edited target mesh in Maya, then click Use Selected.')
        adapter.assert_topology(self.document['meshes'][key], adapter.mesh_path(selected[0]))
        self.target_mapping[key] = selected[0]
        # Keep the clicked mapping-row button alive while its Qt signal runs.
        self._mapping_filling = True
        try:
            self.mapping_table.item(self.mapping_keys.index(key), 1).setText(selected[0])
        finally:
            self._mapping_filling = False
        self.fit_result = None
        self.fit_status.setText('Target mapping changed. Preview again before applying.')

    def _preview_fit(self):
        if not self.document:
            raise ValueError('Load driveNeutralData.json first.')
        from . import fit as fitter
        self.fit_result = fitter.preview(self.document, self.target_mapping,
                                         moved_only=self.fit_moved_only.isChecked())
        moved = sum(sum(x * x for x in row['delta_cm']) > 1e-14 for row in self.fit_result['joints'])
        self.fit_status.setText('Preview: {} joints, {} moved. Green locators are under DN_FitPreview. '
                               'The original rig has not been changed.'.format(self.fit_result['joint_count'], moved))

    def _clear_fit_preview(self):
        from . import fit as fitter
        fitter.clear_preview()
        self.fit_status.setText('Preview markers removed.')

    def _apply_fit(self, reset=False):
        if not self.document:
            raise ValueError('Load driveNeutralData.json first.')
        from . import fit as fitter
        progress = QtWidgets.QProgressDialog('Prepare fit...', 'Cancel', 0, 100, self)
        progress.setWindowTitle('Apply neutral fit' if not reset else 'Restore captured template')
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
            self.fit_result = fitter.apply(self.document, self.target_mapping,
                                            install_mesh=True if reset else self.fit_options.isChecked(),
                                            reset=reset, progress=report)
            self.fit_status.setText('PASS: {} joints. Max joint error {:.6f} cm; mesh error {:.6f} cm. '
                                   'Rotations/scales retained. Maya Undo reverses this fit. Save the rig as a new .ma file.'.format(
                                       self.fit_result['joint_count'], self.fit_result['maximum_joint_position_error_cm'],
                                       self.fit_result['maximum_mesh_position_error_cm']))
        finally:
            progress.close()
            progress.deleteLater()
            self._busy = False
            self.tabs.setEnabled(True)

    def _export_fit(self):
        from . import fit as fitter
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Export fit result',
                                                      str(Path(self.file_field.text()).with_name('driveNeutralFitResult.json')),
                                                      'JSON (*.json)')
        if path:
            if Path(path).resolve() == Path(self.file_field.text()).resolve():
                raise ValueError('Keep the original driveNeutralData.json. Export the fit result to a different file.')
            fitter.save_report(self.fit_result, path)
            self.fit_status.setText('Saved fit result: ' + path)

    def _guard(self, action):
        if self._busy:
            return
        try:
            return action()
        except adapter.Cancelled as exc:
            self.summary.setText(str(exc))
            self.fit_status.setText(str(exc))
        except Exception as exc:
            self.summary.setText(str(exc))
            self.fit_status.setText(str(exc))
            cmds.warning('Drive Neutral Data: ' + str(exc))
            QtWidgets.QMessageBox.warning(self, 'Drive Neutral Data', str(exc))

    def _set_sources(self, names):
        self.sources = list(dict.fromkeys(names))
        self.source_field.setText('; '.join(name.split('|')[-1] for name in self.sources))
        self.source_field.setToolTip('\n'.join(self.sources))

    def _selected_sources(self):
        names = adapter.selected_meshes()
        if not names:
            raise ValueError('Select polygon mesh objects or their components in Maya first.')
        self._set_sources(names)

    def _mark_dirty(self):
        self.dirty = True
        if self.document:
            self.document['updated_utc'] = core.utc_now()
        self.setWindowTitle('Drive Neutral Data 1.1 *')

    def _detect(self):
        progress = QtWidgets.QProgressDialog('Reading source meshes...', 'Cancel', 0, 100, self)
        progress.setWindowTitle('Detect neutral vertex groups')
        progress.setWindowModality(QtCore.Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        self._busy = True
        self.table.setEnabled(False)
        for button in self._buttons:
            button.setEnabled(False)
        progress.show()
        def report(value, total, text):
            progress.setLabelText(text)
            progress.setValue(min(99, int(100 * value / max(1, total))))
            QtWidgets.QApplication.processEvents()
            return not progress.wasCanceled()
        try:
            new_data = adapter.detect(self.sources, scope=self.scope.currentData(),
                                       max_vertices=self.max_vertices.value(),
                                       relative_threshold=self.threshold.value(),
                                       nearest_fallback=self.fallback.isChecked(),
                                       existing=self.document, progress=report)
            self.document = new_data
            self._render()
            self._mark_dirty()
        finally:
            progress.close()
            progress.deleteLater()
            self._busy = False
            self.table.setEnabled(True)
            for button in self._buttons:
                button.setEnabled(True)

    def _render(self):
        self._filling = True
        self.table.setUpdatesEnabled(False)
        try:
            rows = self.document['joints'] if self.document else []
            self.table.setRowCount(0)
            self.table.setRowCount(len(rows))
            for index, row in enumerate(rows):
                tooltip = self._group_tooltip(row)
                joint = QtWidgets.QTableWidgetItem(row['joint']['name'])
                joint.setToolTip(row['joint']['path'] + '\nEdit this field to associate a different joint; scene names are not changed.')
                self.table.setItem(index, 0, joint)
                group = QtWidgets.QTableWidgetItem(row['group_name'])
                group.setToolTip(tooltip)
                self.table.setItem(index, 1, group)
                count = QtWidgets.QTableWidgetItem(str(row['vertex_count']))
                count.setFlags(count.flags() & ~QtCore.Qt.ItemIsEditable)
                count.setToolTip(tooltip)
                self.table.setItem(index, 2, count)
                for column, text, action in [
                    (3, 'Select Verts', lambda i=index: adapter.select_group(self.document, self.document['joints'][i])),
                    (4, 'Update', lambda i=index: self._update_group(i)),
                    (5, 'Joint', lambda i=index: adapter.select_joint(self.document['joints'][i]))]:
                    button = QtWidgets.QPushButton(text)
                    button.clicked.connect(lambda checked=False, action=action: self._guard(action))
                    if column == 4:
                        button.setToolTip('Replace this group with the currently selected source vertices. Uses the saved default mesh positions.')
                    self.table.setCellWidget(index, column, button)
                source = {'skin_weights': 'Skin weights', 'nearest_fallback': 'Nearest - REVIEW',
                          'manual': 'Manual', 'unassigned': 'Unassigned'}.get(row['method'], row['method'])
                item = QtWidgets.QTableWidgetItem(source)
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                if row['review_required']:
                    item.setForeground(QtGui.QColor('#edb55d'))
                item.setToolTip(tooltip)
                self.table.setItem(index, 6, item)
        finally:
            self._filling = False
            self.table.setUpdatesEnabled(True)
        self._filter()
        self._details()
        self._sync_mapping()

    def _group_tooltip(self, row):
        lines = []
        for group in row['vertex_groups']:
            mesh = self.document['meshes'][group['mesh_id']]
            lines.append(mesh['identity']['path'] + '.vtx[' + core.compact_ids(group['vertex_ids']) + ']')
        return '\n'.join(lines) or 'Unassigned - select vertices in Maya and click Update.'

    def _filter(self, text=None):
        query = self.search.text().strip().lower()
        rows = self.document['joints'] if self.document else []
        visible = 0
        for index, row in enumerate(rows):
            haystack = ' '.join([row['joint']['path'], row['group_name'], row['method'],
                                 self._group_tooltip(row)]).lower()
            hidden = bool(query and query not in haystack)
            self.table.setRowHidden(index, hidden)
            visible += int(not hidden)
        review = sum(row['review_required'] for row in rows)
        manual = sum(row['method'] == 'manual' for row in rows)
        empty = sum(not row['vertex_count'] for row in rows)
        self.summary.setText('{} / {} joints | {} manual | {} review | {} unassigned'.format(
            visible, len(rows), manual, review, empty))

    def _details(self):
        index = self.table.currentRow()
        if not self.document or index < 0 or index >= len(self.document['joints']):
            self.details.setText('Select a row to inspect its captured default position and vertex IDs.')
            return
        row = self.document['joints'][index]
        self.details.setText('{}\nDefault joint (cm): {}   |   Group center (cm): {}\n{}'.format(
            row['joint']['path'], self._vector(row['default_world_position_cm']),
            self._vector(row['default_group_center_cm']), self._group_tooltip(row)))
        self.details.setMaximumHeight(95)

    @staticmethod
    def _vector(value):
        return ', '.join('{:.5f}'.format(x) for x in value) if value is not None else 'unassigned'

    def _item_changed(self, item):
        if self._filling or self._busy or not self.document:
            return
        def change():
            index = item.row()
            if item.column() == 0:
                adapter.reassign_joint(self.document, index, item.text().strip())
            elif item.column() == 1:
                text = item.text().strip()
                if not text:
                    raise ValueError('Vertex-group name cannot be empty')
                self.document['joints'][index]['group_name'] = text
            else:
                return
            self._mark_dirty()
        self._guard(change)
        self._refresh_row(item.row())

    def _refresh_row(self, index):
        """Keep row widgets alive while a row button or item editor is active."""
        row = self.document['joints'][index]
        self._filling = True
        try:
            self.table.item(index, 0).setText(row['joint']['name'])
            self.table.item(index, 0).setToolTip(row['joint']['path'])
            self.table.item(index, 1).setText(row['group_name'])
            self.table.item(index, 1).setToolTip(self._group_tooltip(row))
            self.table.item(index, 2).setText(str(row['vertex_count']))
            self.table.item(index, 2).setToolTip(self._group_tooltip(row))
            text = {'skin_weights': 'Skin weights', 'nearest_fallback': 'Nearest - REVIEW',
                    'manual': 'Manual', 'unassigned': 'Unassigned'}.get(row['method'], row['method'])
            item = self.table.item(index, 6)
            item.setText(text)
            item.setForeground(QtGui.QColor('#edb55d') if row['review_required']
                               else self.table.palette().color(QtGui.QPalette.Text))
            item.setToolTip(self._group_tooltip(row))
        finally:
            self._filling = False
        self._filter()
        self._details()

    def _update_group(self, index):
        groups = adapter.selection_groups(self.document)
        core.set_group(self.document, self.document['joints'][index], groups, 'manual')
        self._mark_dirty()
        self._refresh_row(index)
        self.table.selectRow(index)

    def _ensure_sources(self, document):
        for name in self.sources:
            snapshot, _ = adapter.mesh_snapshot(name)
            if snapshot['id'] not in document['meshes']:
                document['meshes'][snapshot['id']] = snapshot
            elif snapshot['topology_sha256'] != document['meshes'][snapshot['id']]['topology_sha256']:
                raise ValueError('Source topology changed. Start a New Capture.')
        return document

    def _add_joints(self):
        names = adapter.selected_joints()
        if not names:
            raise ValueError('Select joint objects in Maya first.')
        document = copy.deepcopy(self.document) if self.document else core.new_document(
            cmds.file(query=True, sceneName=True), cmds.currentUnit(query=True, linear=True))
        self._ensure_sources(document)
        self.document = adapter.add_joints(document, names)
        self._mark_dirty()
        self._render()

    def _remove_rows(self):
        indices = {item.row() for item in self.table.selectedItems() if not self.table.isRowHidden(item.row())}
        if not indices or not self.document:
            raise ValueError('Select table rows to remove from the data.')
        self.document['joints'] = [row for index, row in enumerate(self.document['joints']) if index not in indices]
        self._mark_dirty()
        self._render()

    def _validate_scene(self):
        if not self.document:
            raise ValueError('Capture or load data first.')
        problems = adapter.validate_scene(self.document)
        if problems:
            raise ValueError('{} scene issue(s):\n{}'.format(len(problems), '\n'.join(problems[:15])))
        self.summary.setText('Valid: saved vertex IDs/connectivity and joint identities match this scene.')

    def _confirm_replace(self):
        if not self.dirty:
            return True
        answer = QtWidgets.QMessageBox.question(self, 'Unsaved neutral data', 'Save the current table first?',
                                                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel,
                                                QtWidgets.QMessageBox.Save)
        if answer == QtWidgets.QMessageBox.Cancel:
            return False
        if answer == QtWidgets.QMessageBox.Save:
            try:
                return bool(self._save())
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, 'Save failed', str(exc))
                return False
        return True

    def _new_capture(self):
        if not self._confirm_replace():
            return
        self.document = None
        self.target_mapping = {}
        self.fit_result = None
        self.dirty = False
        self.setWindowTitle('Drive Neutral Data 1.1')
        self._render()
        self.summary.setText('Defaults cleared from this window. Put the rig in neutral, then Auto-detect Groups.')

    def _save(self):
        if not self.document:
            raise ValueError('Capture or load data first.')
        path = self.file_field.text().strip()
        if not path:
            return self._save_as()
        if Path(path).suffix.lower() != '.json':
            path += '.json'
        self.document['updated_utc'] = core.utc_now()
        core.save(self.document, path)
        self.file_field.setText(path)
        self.dirty = False
        self.setWindowTitle('Drive Neutral Data 1.1')
        self.summary.setText('Saved {} joints to {}'.format(len(self.document['joints']), path))
        return True

    def _save_as(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save neutral drive data',
                                                      self.file_field.text() or adapter.default_path(), 'JSON (*.json)')
        if not path:
            return False
        self.file_field.setText(path)
        return self._save()

    def _load(self):
        if not self._confirm_replace():
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Load neutral drive data',
                                                      self.file_field.text(), 'JSON (*.json)')
        if not path:
            return
        self._load_data(core.load(path), path)

    def _load_data(self, data, path):
        core.validate(data)
        self.document = data
        self.target_mapping = {}
        self.fit_result = None
        self.file_field.setText(path)
        names = []
        for mesh in data['meshes'].values():
            try:
                names.append(adapter.resolve(mesh['identity']))
            except ValueError:
                names.append(mesh['identity']['path'])
        self._set_sources(names)
        settings = data.get('detection_settings', {})
        self.max_vertices.setValue(settings.get('max_vertices', 32))
        self.threshold.setValue(settings.get('minimum_fraction_of_peak_weight', .25))
        self.fallback.setChecked(settings.get('nearest_fallback', True))
        self.dirty = False
        self.setWindowTitle('Drive Neutral Data 1.1')
        self._render()

    def closeEvent(self, event):
        if self._busy or not self._confirm_replace():
            event.ignore()
        else:
            event.accept()


def show(auto_detect=True):
    """Open the editor; reuse a visible window rather than losing unsaved data."""
    global _dialog
    parent = maya_window()
    existing = parent.findChild(QtWidgets.QDialog, OBJECT_NAME) if parent else None
    if existing and existing.isVisible():
        existing.raise_()
        existing.activateWindow()
        _dialog = existing
        return existing
    _dialog = NeutralDataEditor(parent=parent, auto_detect=auto_detect)
    _dialog.show()
    return _dialog


def show_fit():
    """Open directly at the target-mapping and fitting step without recapturing."""
    dialog = show(auto_detect=False)
    dialog.tabs.setCurrentIndex(1)
    return dialog
