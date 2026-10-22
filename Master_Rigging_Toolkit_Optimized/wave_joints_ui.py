"""Ordered wave-joint authoring. Scene evaluation runs in native Maya nodes."""
try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets


class WaveJointsPanel(QtWidgets.QWidget):
    def __init__(self, parent, backend):
        super(WaveJointsPanel, self).__init__(parent)
        self.backend = backend
        self.driver_id = None
        self.loaded_system = None
        self.loaded_values = {}
        self.loaded_channels = {}
        self.setObjectName('WaveJointsPage')
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setProperty('qtPanel', True)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        group = QtWidgets.QGroupBox('Driver controller')
        form = QtWidgets.QFormLayout(group)
        self.driver = QtWidgets.QLineEdit()
        self.driver.setPlaceholderText('Controller for the wave attributes')
        self.driver.textEdited.connect(lambda *_: setattr(self, 'driver_id', None))
        row = QtWidgets.QHBoxLayout(); row.addWidget(self.driver, 1)
        self.button(row, 'Get selected', self.get_driver)
        self.button(row, 'Select', self.select_driver)
        form.addRow('Driver:', row)
        self.prefix = QtWidgets.QLineEdit('wave')
        self.prefix.setToolTip('Use another prefix for a separate wave on the same controller. Compatible existing attributes are reused.')
        form.addRow('Attribute prefix:', self.prefix)
        outer.addWidget(group)

        inputs = QtWidgets.QHBoxLayout()
        group = QtWidgets.QGroupBox('Driven joints · in wave order')
        layout = QtWidgets.QVBoxLayout(group)
        self.joints = QtWidgets.QListWidget()
        self.joints.setObjectName('WaveJointList')
        self.joints.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.joints.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.joints.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.joints.setMinimumWidth(165)
        self.joints.setFixedHeight(170)
        self.joints.setToolTip('Drag rows or use Up / Down to set the exact order. Each joint is stored by UUID.')
        layout.addWidget(self.joints)
        row = QtWidgets.QHBoxLayout()
        self.button(row, 'Add selected', self.add_selected)
        self.button(row, 'Get chain', self.get_chain)
        layout.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        self.button(row, 'Up', lambda: self.move(-1))
        self.button(row, 'Down', lambda: self.move(1))
        self.button(row, 'Reverse', self.reverse)
        layout.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        self.button(row, 'Remove', self.remove_rows)
        self.button(row, 'Clear', self.joints.clear)
        layout.addLayout(row)
        inputs.addWidget(group, 1)

        group = QtWidgets.QGroupBox('Local outputs')
        layout = QtWidgets.QVBoxLayout(group)
        self.outputs = QtWidgets.QTreeWidget()
        self.outputs.setColumnCount(4)
        self.outputs.setHeaderLabels(['Use', 'Channel', 'Gain', 'Phase °'])
        self.outputs.setRootIsDecorated(False)
        self.outputs.setAlternatingRowColors(True)
        self.outputs.setUniformRowHeights(True)
        for column, width in enumerate((38, 67, 77, 80)):
            self.outputs.setColumnWidth(column, width)
        self.outputs.header().setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        self.outputs.setMinimumWidth(265)
        self.outputs.setFixedHeight(248)
        self.axes = {}
        for key in backend.CHANNELS:
            item = QtWidgets.QTreeWidgetItem(self.outputs, ['', key.upper(), '', ''])
            item.setCheckState(0, QtCore.Qt.Checked if key == 'ty' else QtCore.Qt.Unchecked)
            gain = self.number(-1000., 1000., 1.)
            phase = self.number(-36000., 36000., 0.)
            self.outputs.setItemWidget(item, 2, gain)
            self.outputs.setItemWidget(item, 3, phase)
            self.axes[key] = (item, gain, phase)
        self.outputs.itemChanged.connect(self.axis_enabled)
        self.axis_enabled()
        layout.addWidget(self.outputs)
        note = QtWidgets.QLabel('Gain −1 flips direction. A 90° phase difference makes two axes move in a circle.')
        note.setWordWrap(True); note.setProperty('role', 'muted')
        layout.addWidget(note)
        inputs.addWidget(group, 1)
        outer.addLayout(inputs)

        group = QtWidgets.QGroupBox('Wave settings')
        grid = QtWidgets.QGridLayout(group)
        self.fields = {}
        settings = (
            ('offset', 'Offset · degrees', -1e9, 1e9),
            ('frequency', 'Cycles across list', -1000., 1000.),
            ('envelope', 'Envelope', 0., 1.),
            ('translation_amplitude', 'Translate amplitude · '+backend.cmds.currentUnit(query=True, linear=True), -1e9, 1e9),
            ('rotation_amplitude', 'Rotate amplitude · degrees', -36000., 36000.),
            ('speed', 'Speed · cycles / second', -1000., 1000.),
            ('root_weight', 'First joint amplitude', 0., 1.),
            ('tip_weight', 'Last joint amplitude', 0., 1.),
        )
        for index, (key, label, lo, hi) in enumerate(settings):
            spin = self.number(lo, hi, backend.PARAMS[key][2])
            self.fields[key] = spin
            column = (index % 2)*2; row = index//2
            grid.addWidget(QtWidgets.QLabel(label), row, column)
            grid.addWidget(spin, row, column+1)
        self.auto_time = QtWidgets.QCheckBox('Automatic time motion')
        self.auto_time.setToolTip('Off: animate Offset. On: add Speed × time to Offset. Speed is cycles per second.')
        grid.addWidget(self.auto_time, 4, 0, 1, 2)
        self.spacing = QtWidgets.QComboBox()
        self.spacing.addItem('Even spacing by list index', 'index')
        self.spacing.addItem('Spacing by rest distance', 'distance')
        grid.addWidget(self.spacing, 4, 2, 1, 2)
        outer.addWidget(group)

        group = QtWidgets.QGroupBox('Position falloff')
        form = QtWidgets.QFormLayout(group)
        row = QtWidgets.QHBoxLayout()
        for key, label, lo, hi in (('falloff_position', 'Peak · 0–1', 0., 1.),
                                   ('falloff_power', 'Power · 0 = off', 0., 1000.)):
            field = self.number(lo, hi, backend.PARAMS[key][2])
            self.fields[key] = field
            row.addWidget(QtWidgets.QLabel(label)); row.addWidget(field, 1)
        form.addRow(row)
        note = QtWidgets.QLabel('Position: 0 = first joint, 1 = last. Power 1 gives linear falloff; higher values keep a wider area strong. Power 0 disables falloff.')
        note.setWordWrap(True); note.setProperty('role', 'muted'); form.addRow(note)
        outer.addWidget(group)

        row = QtWidgets.QHBoxLayout()
        self.button(row, 'Validate', self.validate)
        self.build_button = self.button(row, 'Build wave', self.build)
        self.build_button.setProperty('role', 'primary')
        outer.addLayout(row)
        note = QtWidgets.QLabel('Envelope starts at 0 to retain the pose. Enable the wave, then key Offset or turn on Automatic time motion. Outputs add to the saved local values; scale and joint orientation stay intact.')
        note.setWordWrap(True); note.setProperty('role', 'muted'); outer.addWidget(note)

        group = QtWidgets.QGroupBox('Scene wave setups')
        layout = QtWidgets.QVBoxLayout(group)
        row = QtWidgets.QHBoxLayout()
        self.systems = QtWidgets.QComboBox(); row.addWidget(self.systems, 1)
        self.button(row, 'Refresh', self.refresh)
        self.button(row, 'Load', self.load)
        layout.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        self.button(row, 'Apply settings / order', self.update)
        self.button(row, 'Enable wave', lambda: self.set_envelope(1.))
        self.button(row, 'Mute wave', lambda: self.set_envelope(0.))
        layout.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        self.button(row, 'Select listed joints', self.select_joints)
        self.button(row, 'Select wave nodes', self.select_nodes)
        layout.addLayout(row)
        self.cleanup_attrs = QtWidgets.QCheckBox('Remove unused attributes when deleting')
        self.cleanup_attrs.setChecked(True)
        self.cleanup_attrs.setToolTip('Only attributes created by this setup are eligible. Animated attributes and those driving another system remain.')
        layout.addWidget(self.cleanup_attrs)
        button = self.button(layout, 'Delete wave · keep current joint pose', self.delete)
        button.setProperty('role', 'danger')
        outer.addWidget(group)
        self.status = QtWidgets.QLabel('Get a driver, load and order the joints, choose outputs, then Build wave.')
        self.status.setWordWrap(True); outer.addWidget(self.status)
        self.refresh()

    def number(self, lo, hi, value):
        field = QtWidgets.QDoubleSpinBox()
        field.setRange(lo, hi); field.setDecimals(4); field.setSingleStep(.1)
        field.setValue(value); field.setKeyboardTracking(False)
        field.setMinimumWidth(66)
        return field

    def button(self, layout, text, action):
        button = QtWidgets.QPushButton(text)
        button.setAutoDefault(False); button.setDefault(False)
        button.clicked.connect(lambda *_: self.guard(action))
        layout.addWidget(button)
        return button

    def guard(self, action):
        try:
            return action()
        except (ValueError, RuntimeError) as exc:
            self.status.setText(str(exc))
            self.backend.cmds.warning('waveJoints: '+str(exc))

    def axis_enabled(self, *_):
        for item, gain, phase in self.axes.values():
            enabled = item.checkState(0) == QtCore.Qt.Checked
            gain.setEnabled(enabled); phase.setEnabled(enabled)

    def _selected(self):
        commands = self.backend.cmds
        if commands.selectPref(query=True, trackSelectionOrder=True):
            return commands.ls(orderedSelection=True, long=True) or []
        return commands.ls(selection=True, long=True) or []

    def get_driver(self):
        selected = self._selected()
        if len(selected) != 1:
            raise ValueError('Select one driver controller.')
        node = self.backend.unique(selected[0])
        if self.backend.cmds.nodeType(node) not in ('transform', 'joint'):
            raise ValueError('Driver controller must be a transform or joint.')
        self.driver.setText(node); self.driver_id = self.backend.identity(node)

    def _driver(self):
        return self.backend.unique(self.driver_id or self.driver.text().strip())

    def _joints(self):
        return [self.backend.unique(self.joints.item(i).data(QtCore.Qt.UserRole), 'joint')
                for i in range(self.joints.count())]

    def _set_joints(self, nodes):
        records = [(self.backend.unique(node, 'joint'), self.backend.identity(self.backend.unique(node, 'joint'))) for node in nodes]
        self.joints.clear()
        for node, uid in records:
            item = QtWidgets.QListWidgetItem(node.rsplit('|', 1)[-1])
            item.setData(QtCore.Qt.UserRole, uid); item.setToolTip(node)
            self.joints.addItem(item)

    def add_selected(self):
        selected = self._selected()
        if not selected:
            raise ValueError('Select joints to append in the desired order.')
        nodes = self._joints()+[self.backend.unique(node, 'joint') for node in selected]
        ordered = dict.fromkeys(self.backend.identity(node) for node in nodes)
        self._set_joints(list(ordered))
        self.status.setText('Loaded {} joints. Confirm the order by dragging rows or using Up / Down.'.format(self.joints.count()))

    def get_chain(self):
        selected = self._selected()
        if len(selected) != 1:
            raise ValueError('Select the first joint of one unbranched chain.')
        self._set_joints(self.backend.ordered_chain(selected[0]))

    def move(self, step):
        rows = sorted((self.joints.row(item) for item in self.joints.selectedItems()), reverse=step > 0)
        for row in rows:
            destination = row+step
            if 0 <= destination < self.joints.count() and not self.joints.item(destination).isSelected():
                item = self.joints.takeItem(row); self.joints.insertItem(destination, item); item.setSelected(True)

    def reverse(self):
        self._set_joints(list(reversed(self._joints())))

    def remove_rows(self):
        for item in self.joints.selectedItems():
            self.joints.takeItem(self.joints.row(item))

    def _values(self):
        return dict({key: field.value() for key, field in self.fields.items()}, auto_time=self.auto_time.isChecked())

    def _channels(self):
        return {key: {'gain': gain.value(), 'phase': phase.value()} for key, (item, gain, phase) in self.axes.items()
                if item.checkState(0) == QtCore.Qt.Checked}

    def _arguments(self):
        return {'driver': self._driver(), 'joints': self._joints(), 'channels': self._channels(),
                'prefix': self.prefix.text().strip(), 'spacing': self.spacing.currentData(), 'settings': self._values()}

    def validate(self):
        info = self.backend.plan(**self._arguments())
        self.status.setText('Ready: {} joints, {} outputs each. {} compatible driver attributes will be reused. No scene edits.'.format(
            len(info['joints']), len(info['channels']), len(info['existing_attributes'])))

    def build(self):
        result = self.backend.build(**self._arguments())
        self.refresh(result['system']); self.load()
        envelope = self.fields['envelope'].value()
        self.status.setText('Built {} joints with {} native nodes. Envelope = {:g}. {}'.format(result['joint_count'], result['node_count'], envelope,
            'Press Enable wave to preview, then animate Offset or enable automatic time.' if envelope == 0 else 'Animate Offset or enable automatic time.'))

    def refresh(self, system=None):
        wanted = self.backend.identity(system) if isinstance(system, str) else self.systems.currentData()
        self.systems.clear()
        for meta in self.backend.list_systems():
            try:
                _meta, state = self.backend.read(meta)
                driver = self.backend.unique(state['driver_uuid']).rsplit('|', 1)[-1]
                label = '{} · {} · {} joints'.format(driver, state['prefix'], len(state['joints']))
            except (ValueError, RuntimeError):
                label = meta+' · needs checking'
            self.systems.addItem(label, self.backend.identity(meta))
        index = self.systems.findData(wanted)
        if index >= 0:
            self.systems.setCurrentIndex(index)

    def _system(self):
        uid = self.systems.currentData()
        if not uid:
            raise ValueError('Build a wave setup or choose one from the scene list.')
        return self.backend.unique(uid, 'network')

    def load(self):
        info = self.backend.current_settings(self._system())
        self.driver_id = self.backend.identity(info['driver']); self.driver.setText(info['driver'])
        self.prefix.setText(info['prefix']); self._set_joints(info['joints'])
        for key, field in self.fields.items():
            field.setValue(info['settings'][key])
        self.auto_time.setChecked(info['settings']['auto_time'])
        self.spacing.setCurrentIndex(self.spacing.findData(info['spacing']))
        for key, (item, gain, phase) in self.axes.items():
            item.setCheckState(0, QtCore.Qt.Checked if key in info['channels'] else QtCore.Qt.Unchecked)
            gain.setValue(info['channels'].get(key, {}).get('gain', 1.))
            phase.setValue(info['channels'].get(key, {}).get('phase', 0.))
        self.axis_enabled()
        self.loaded_system = self.systems.currentData()
        self.loaded_values = self._values()
        self.loaded_channels = self._channels()
        self.status.setText('Loaded scene setup. Apply settings / order changes live values. Changing the joints or output channels needs a new setup.'
            if info.get('falloff_available', True) else 'Loaded a 2.38 wave. Apply settings / order adds falloff controls in place; Power 0 retains the existing wave.')

    def update(self):
        system = self._system()
        _meta, state = self.backend.read(system)
        if (self.loaded_system != self.systems.currentData() or self.backend.identity(self._driver()) != state['driver_uuid']
                or self.prefix.text().strip() != state['prefix']):
            raise ValueError('Load the selected setup before updating; driver and prefix must match.')
        # Only send fields the user changed. Playback or Channel Box edits can
        # change live values since Load; a rounded UI display must not overwrite
        # them or try to set a connected animation channel during reordering.
        values = {key: value for key, value in self._values().items() if value != self.loaded_values.get(key)}
        channels = self._channels()
        if set(channels) == set(self.loaded_channels):
            live = self.backend.current_settings(system)['channels']
            for axis, fields in channels.items():
                for parameter, value in fields.items():
                    if value == self.loaded_channels[axis][parameter]:
                        channels[axis][parameter] = live[axis][parameter]
        self.backend.update(system, joints=self._joints(), channels=channels, spacing=self.spacing.currentData(), settings=values)
        self.load()
        self.status.setText('Updated settings and joint order. Saved local base values were retained. Undo restores the previous settings.')

    def set_envelope(self, value):
        self.backend.update(self._system(), settings={'envelope': value})
        self.load()
        self.status.setText('Wave enabled. Animate Offset or turn on automatic time motion.' if value else 'Wave muted; joints use their saved local values.')

    def select_driver(self):
        self.backend.cmds.select(self._driver(), replace=True)

    def select_joints(self):
        nodes = self._joints()
        if nodes:
            self.backend.cmds.select(nodes, replace=True)

    def select_nodes(self):
        meta, state = self.backend.read(self._system(), allow_missing=True)
        self.backend.cmds.select([meta]+[node for row in state['members'] if (node := self.backend.resolve(row['uuid']))], replace=True)

    def delete(self):
        result = self.backend.remove(self._system(), remove_unused_attributes=self.cleanup_attrs.isChecked())
        self.refresh()
        self.status.setText('Removed wave; kept {} joints at their current pose. {} animated, shared or retained driver attributes remain. Undo restores the setup.'.format(
            result['joint_count'], len(result['retained_attributes'])))
