"""First coarse cage layer page for the Facial System workflow."""
import json
from pathlib import Path

import maya.cmds as cmds

from . import cage, project, scene_ops
from . import scene_adapter as adapter
from .neutral_editor import QtWidgets


class CagePanel(QtWidgets.QWidget):
    def __init__(self, owner):
        super(CagePanel, self).__init__(owner)
        self.owner = owner
        self.data = None
        self.symmetry_previous = None
        self._filling = False
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(owner._note('First test: choose the original head, Create Coarse Layer, then Bind Cage before editing. '
                                    'Move the cage vertices to match your reference face. Bake creates an independent target '
                                    'for Fit Joints. The reference mesh is a visual guide and may have different topology.'))
        grid = QtWidgets.QGridLayout()
        self.source = self._field(grid, 0, 'Template / source head', 'source')
        self.reference = self._field(grid, 1, 'Reference face (optional)', 'reference')
        self.custom = self._field(grid, 2, 'Custom cage (optional)', 'custom')
        layout.addLayout(grid)
        options = QtWidgets.QHBoxLayout()
        options.addWidget(QtWidgets.QLabel('Auto cage: Around'))
        self.around = QtWidgets.QSpinBox()
        self.around.setRange(6, 32)
        self.around.setSingleStep(2)
        self.around.setValue(12)
        options.addWidget(self.around)
        options.addWidget(QtWidgets.QLabel('Height divisions'))
        self.rings = QtWidgets.QSpinBox()
        self.rings.setRange(4, 24)
        self.rings.setValue(12)
        options.addWidget(self.rings)
        self.conform = QtWidgets.QCheckBox('Fit seed cage to source surface')
        self.conform.setChecked(True)
        options.addWidget(self.conform)
        options.addStretch(1)
        layout.addLayout(options)
        actions = QtWidgets.QHBoxLayout()
        actions.addWidget(owner._button('1  Create Coarse Layer', self._create))
        actions.addWidget(owner._button('Resume / Refresh Scene Layer', self.refresh))
        actions.addWidget(owner._button('2  Bind Cage', self._bind))
        layout.addLayout(actions)
        self.layer_summary = QtWidgets.QLabel('No cage layer loaded. The auto seed is a small symmetric sphere fitted to the head.')
        self.layer_summary.setWordWrap(True)
        layout.addWidget(self.layer_summary)
        settings = QtWidgets.QHBoxLayout()
        self.enabled = QtWidgets.QCheckBox('Layer enabled')
        self.enabled.setChecked(True)
        settings.addWidget(self.enabled)
        settings.addWidget(QtWidgets.QLabel('Weight'))
        self.weight = QtWidgets.QDoubleSpinBox()
        self.weight.setRange(0., 1.)
        self.weight.setSingleStep(.1)
        self.weight.setValue(1.)
        settings.addWidget(self.weight)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(['Offset', 'Surface'])
        self.mode.setToolTip('Offset is the coarse fitting default. Surface also accounts for driver orientation.')
        settings.addWidget(self.mode)
        settings.addWidget(owner._button('Select Cage Vertices', self._select_vertices))
        settings.addWidget(owner._button('Select Preview', self._select_preview))
        layout.addLayout(settings)
        mirror = QtWidgets.QHBoxLayout()
        mirror.addWidget(owner._button('Enable Mirror Editing', self._enable_symmetry))
        mirror.addWidget(owner._button('Restore Previous Symmetry', self.restore_symmetry))
        mirror.addWidget(owner._button('Mirror +X to -X', lambda: self._mirror('positive')))
        mirror.addWidget(owner._button('Mirror -X to +X', lambda: self._mirror('negative')))
        mirror.addWidget(owner._button('Reset Cage', self._reset))
        layout.addLayout(mirror)
        view = QtWidgets.QHBoxLayout()
        view.addWidget(owner._button('Select Source', self._select_source))
        view.addWidget(owner._button('Select Reference', self._select_reference))
        view.addWidget(owner._button('Check Layer', self._inspect))
        view.addWidget(owner._button('Test Cage Response', self._test_response))
        view.addWidget(owner._button('Save Layer Data...', self._export))
        view.addWidget(owner._button('Remove Working Layer', self._remove))
        layout.addLayout(view)
        bake = QtWidgets.QHBoxLayout()
        bake.addWidget(QtWidgets.QLabel('Baked target name'))
        self.output = QtWidgets.QLineEdit('Head_FitTarget')
        bake.addWidget(self.output, 1)
        bake.addWidget(owner._button('3  Bake Target + Use in Fit Joints', self._bake))
        layout.addLayout(bake)
        self.status = QtWidgets.QPlainTextEdit()
        self.status.setReadOnly(True)
        self.status.setPlaceholderText('Bind time and layer checks appear here. Cage evaluation uses native Maya nodes.')
        layout.addWidget(self.status, 1)
        note = QtWidgets.QLabel('Edit cage vertices after binding. Hide the original head in the viewport if it overlaps the preview. '
                               'Keep cage topology fixed. Existing Head_FitTarget objects are retained; a new bake gets a numbered name.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.enabled.toggled.connect(self._settings)
        self.weight.valueChanged.connect(self._settings)
        self.mode.currentTextChanged.connect(self._settings)
        for widget in (self.enabled, self.weight, self.mode):
            widget.setEnabled(False)

    def _field(self, grid, row, label, attribute):
        grid.addWidget(QtWidgets.QLabel(label), row, 0)
        field = QtWidgets.QLineEdit()
        grid.addWidget(field, row, 1)
        grid.addWidget(self.owner._button('Use Selected', lambda: self._assign(attribute)), row, 2)
        return field

    def _assign(self, attribute):
        selected = adapter.selected_meshes()
        if len(selected) != 1:
            raise ValueError('Select exactly one polygon mesh')
        getattr(self, attribute).setText(selected[0])

    def suggest_source(self, document):
        if self.source.text().strip() or not document:
            return
        meshes = [mesh for mesh in document['meshes'].values() if 'head' in mesh['identity']['name'].lower()]
        if len(meshes) == 1:
            try:
                self.source.setText(adapter.resolve(meshes[0]['identity']))
            except ValueError:
                pass

    def _current(self):
        data = cage.load()
        if data is None:
            raise ValueError('Create or resume a cage layer first')
        self.data = data
        return data

    def refresh(self):
        self.data = cage.load()
        self._filling = True
        try:
            for widget in (self.enabled, self.weight, self.mode):
                widget.setEnabled(self.data is not None)
            if self.data:
                self.source.setText(cage.resolve(self.data['source']))
                if self.data.get('reference'):
                    try:
                        self.reference.setText(cage.resolve(self.data['reference']))
                    except ValueError:
                        self.reference.setText(self.data['reference']['path'])
                self.weight.setValue(self.data['weight'])
                self.enabled.setChecked(self.data['enabled'])
                self.mode.setCurrentText(self.data['mode'])
                pairing = self.data['symmetry']
                self.layer_summary.setText('Layer 1: {} cage vertices | {} fit vertices | {} mirror pairs | {} unmatched | {}'.format(
                    pairing['vertex_count'], self.data['source_snapshot']['vertex_count'], len(pairing['pairs']),
                    len(pairing['unpaired']), 'Bound' if self.data.get('deformer') else 'Ready to bind'))
            else:
                self.layer_summary.setText('No cage layer in this scene. Choose a source head and Create Coarse Layer.')
        finally:
            self._filling = False
        return self.data

    def _show(self, result):
        self.status.setPlainText(json.dumps(result, indent=2))
        self.refresh()
        return result

    def _create(self):
        source = self.source.text().strip()
        if not source:
            raise ValueError('Choose the template/source head first')
        if self.owner.document or scene_ops.inspect()['native_graph_present']:
            scene_ops.check_neutral(self.owner.document)
        self.data = self.owner._run_job('Create coarse cage', lambda progress: cage.create(
            source, reference=self.reference.text().strip() or None, custom_cage=self.custom.text().strip() or None,
            around=self.around.value(), rings=self.rings.value(), conform=self.conform.isChecked(), progress=progress))
        self.refresh()
        self.status.setPlainText('Cage created. Bind now, before moving its vertices.\nCreation: {:.3f} seconds.'.format(self.data['create_seconds']))

    def _bind(self):
        data = self._current()
        self.data = self.owner._run_job('Bind coarse cage', lambda progress: cage.bind(data, progress=progress))
        self._show(cage.inspect(self.data))

    def _settings(self, *args):
        if not self._filling:
            self.owner._guard(lambda: self._change_settings())

    def _change_settings(self):
        data = self._current()
        self.data = cage.set_layer(data, weight=self.weight.value(), enabled=self.enabled.isChecked(), mode=self.mode.currentText())
        self.refresh()

    def _select_vertices(self):
        cage.select_vertices(self._current())

    def _select_preview(self):
        cmds.select(cage.resolve(self._current()['preview']), replace=True)

    def _select_source(self):
        source = cage.resolve(self.data['source']) if self.data else self.source.text().strip()
        if not source:
            raise ValueError('Choose the source head first')
        cmds.select(source, replace=True)

    def _select_reference(self):
        reference = self.reference.text().strip()
        if not reference:
            raise ValueError('Choose a reference face first')
        cmds.select(reference, replace=True)

    def _enable_symmetry(self):
        data = self._current()
        previous = cage.enable_symmetry(data)
        if self.symmetry_previous is None:
            self.symmetry_previous = previous
        self.status.setPlainText('Native Object-X mirror editing enabled. Move cage vertices with Maya manipulators. '
                                 'Prior symmetry settings are restored when this window closes.')

    def restore_symmetry(self):
        if self.symmetry_previous is not None:
            cage.restore_symmetry(self.symmetry_previous)
            self.symmetry_previous = None

    def _mirror(self, direction):
        self._show(cage.mirror(self._current(), direction=direction))

    def _reset(self):
        data = self._current()
        result = self.owner._run_job('Reset coarse cage', lambda progress: cage.reset(data, progress=progress))
        self._show(result)

    def _inspect(self):
        return self._show(cage.inspect(self._current()))

    def _test_response(self):
        return self._show(cage.test_response(self._current()))

    def export_current(self):
        data = cage.load()
        return cage.export(data) if data else None

    def _export(self):
        data = self.export_current()
        if data is None:
            raise ValueError('Create a cage layer first')
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save cage layer data',
            str(Path(self.owner.project_field.text()) / 'data/wrapFitData.json'), 'JSON (*.json)')
        if path:
            project.write_json(path, data)
            self.status.setPlainText('Saved layer data: ' + path + '\nSave the Maya scene to retain the complete native cage graph.')

    def _bake(self):
        data = self._current()
        target = cage.bake(data, name=self.output.text().strip())
        self.status.setPlainText('Baked independent target: ' + target)
        self.owner._use_cage_target(data, target)
        return target

    def _remove(self):
        data = self._current()
        self.restore_symmetry()
        cage.remove(data)
        self.data = None
        self.refresh()
        self.status.setPlainText('Working cage layer removed. Source, reference, and baked targets were retained.')
