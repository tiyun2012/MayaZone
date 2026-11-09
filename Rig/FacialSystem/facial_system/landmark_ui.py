"""Named facial points for cage generation and reference matching."""
import copy
import json
from pathlib import Path

from . import cage, cage_landmarks, project
from .neutral_editor import QtWidgets


class LandmarkDialog(QtWidgets.QDialog):
    def __init__(self, panel):
        super(LandmarkDialog, self).__init__(panel)
        self.panel = panel
        self.setWindowTitle('Facial Cage Landmarks')
        self.resize(900, 650)
        layout = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel('Before Create: suggest points from named rig joints, review them, and Set Source Vertex for each row. '
            'Reduced head generation protects faces around these points. After Bind: select a cage landmark or match it '
            'to one selected reference vertex / locator. L and R follow the rig names.')
        note.setWordWrap(True)
        layout.addWidget(note)
        tools = QtWidgets.QHBoxLayout()
        for label, action in (('Suggest from Rig', self._suggest), ('New Landmark Set', self._new),
                              ('Load JSON...', self._load), ('Save JSON...', self._save), ('Refresh', self.refresh)):
            tools.addWidget(self._button(label, action))
        layout.addLayout(tools)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Landmark', 'Source vertex', 'Cage vertex', 'Assignment'])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 250)
        layout.addWidget(self.table, 1)
        actions = QtWidgets.QHBoxLayout()
        for label, action in (('Set Source Vertex', self._assign), ('Select Source Vertex', self._select_source),
                              ('Clear Assignment', self._clear), ('Select Cage Landmark', self._select_cage)):
            actions.addWidget(self._button(label, action))
        layout.addLayout(actions)
        match = QtWidgets.QHBoxLayout()
        self.mirror = QtWidgets.QCheckBox('Mirror opposite cage point')
        self.mirror.setChecked(True)
        match.addWidget(self.mirror)
        match.addWidget(self._button('Move Cage Landmark to Selected Reference Point', self._match))
        layout.addLayout(match)
        self.status = QtWidgets.QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh()

    def _button(self, label, action):
        return self.panel.owner._button(label, lambda: self.panel.owner._guard(lambda: self._run(action)))

    def _run(self, action):
        try:
            return action()
        except Exception as exc:
            self.status.setText(str(exc))
            raise

    def _active(self):
        return cage.load()

    def _marks(self):
        active = self._active()
        return active.get('landmarks') if active else self.panel.landmark_draft

    def _edit_source(self):
        if self._active():
            raise ValueError('Source landmark assignments are fixed for this cage. Remove Working Layer before generating a replacement.')
        source = self.panel.source.text().strip()
        if not source:
            raise ValueError('Choose the Template / source head first')
        self.panel._check_neutral()
        return source

    def _key(self):
        row = self.table.currentRow()
        if row < 0:
            raise ValueError('Choose a landmark row')
        return self.rows[row]['key']

    def refresh(self):
        current = self.table.currentRow()
        marks = self._marks()
        assigned = {row['key']: row for row in marks['items']} if marks else {}
        self.rows = cage_landmarks.presets()
        known = {row['key'] for row in self.rows}
        self.rows.extend({'key': key, 'label': row.get('label', key)} for key, row in assigned.items() if key not in known)
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            item = assigned.get(row['key'], {})
            values = (row['label'], item.get('source_vertex', ''), item.get('cage_vertex', ''),
                      'Review rig suggestion' if item.get('method') == 'rig_suggestion_review' else item.get('method', 'Unassigned'))
            for column, value in enumerate(values):
                self.table.setItem(index, column, QtWidgets.QTableWidgetItem(str(value)))
        if self.rows:
            self.table.selectRow(max(0, min(current, len(self.rows) - 1)))
        self.status.setText('{} of {} landmarks assigned. Source assignments are made before cage generation; '
                            'cage matching is available after binding.'.format(len(assigned), len(self.rows)))

    def _suggest(self):
        source = self._edit_source()
        self.panel.landmark_draft = cage.suggest_landmarks(source, self.panel.landmark_draft)
        self.refresh()
        self.status.setText('Named-joint suggestions need visual review, especially upper/lower lips and eyelids. '
                            'Manual assignments were retained. Unrecognized rigs can be assigned by selecting vertices.')

    def _new(self):
        self.panel.landmark_draft = cage.landmark_draft(self._edit_source())
        self.refresh()

    def _assign(self):
        source = self._edit_source()
        self.panel.landmark_draft = cage.assign_landmark(source, self.panel.landmark_draft, self._key())
        self.refresh()

    def _clear(self):
        source = self._edit_source()
        marks = cage.landmark_draft(source, self.panel.landmark_draft)
        marks['items'] = [row for row in marks['items'] if row['key'] != self._key()]
        self.panel.landmark_draft = marks
        self.refresh()

    def _select_source(self):
        marks = self._marks()
        if not marks:
            raise ValueError('Assign or suggest source landmarks first')
        cage.select_landmark(marks, self._key(), cage_vertex=False)

    def _select_cage(self):
        active = self._active()
        if not active:
            raise ValueError('Create a Reduced head cage first')
        cage.select_landmark(active, self._key())

    def _match(self):
        active = self._active()
        if not active:
            raise ValueError('Create and bind a Reduced head cage first')
        position = cage.selected_world_point()
        report = cage.move_landmark(active, self._key(), position, mirror=self.mirror.isChecked())
        self.status.setText(json.dumps(report))

    def _save(self):
        marks = self._marks()
        if not marks:
            raise ValueError('Assign or suggest source landmarks first')
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save cage landmarks',
            str(Path(self.panel.owner.project_field.text()) / 'data/cageLandmarks.json'), 'JSON (*.json)')
        if path:
            project.write_json(path, cage_landmarks.validate(copy.deepcopy(marks)))
            self.status.setText('Saved source landmark assignments: ' + path)

    def _load(self):
        source = self._edit_source()
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Load cage landmarks', '', 'JSON (*.json)')
        if path:
            marks = json.loads(Path(path).read_text(encoding='utf-8'))
            self.panel.landmark_draft = cage.landmark_draft(source, marks)
            self.refresh()
