"""Pose weight SDK authoring panel. Maya scene writes belong to the backend."""
try:
    from PySide6 import QtCore,QtWidgets
except ImportError:
    from PySide2 import QtCore,QtWidgets

VALUE_RULES=(('Keep delta','keep_delta'),('Flip delta','flip_delta'),('Keep values','keep_values'),('Skip','skip'))


class SDKPanel(QtWidgets.QWidget):
    def __init__(self,owner,api,backend):
        super(SDKPanel,self).__init__(owner)
        self.owner,self.api,self.backend=owner,api,backend;self.meta=None;self.cells={};self.updating=False
        self.mirror_neutral_ref=None
        outer=QtWidgets.QVBoxLayout(self);outer.setContentsMargins(8,8,8,8)
        form=QtWidgets.QFormLayout();outer.addLayout(form)
        self.pose=QtWidgets.QComboBox();self.mode=QtWidgets.QComboBox()
        self.mode.addItem('Raw','raw');self.mode.addItem('Weight · Normalize blend','final')
        row=QtWidgets.QHBoxLayout();row.addWidget(self.pose,2);row.addWidget(self.mode,1)
        self.button(row,'Refresh poses',self.refresh_poses);self.button(row,'Use pose output',self.use_output)
        form.addRow('Pose weight:',row)
        self.weight=QtWidgets.QLineEdit();self.weight.setPlaceholderText('cone.poseWeightRaw or cone.poseWeight')
        form.addRow('Driver plug:',self.weight)
        self.driven=QtWidgets.QLineEdit();self.driven.setPlaceholderText('Transform / SDK offset to drive')
        row=QtWidgets.QHBoxLayout();row.addWidget(self.driven,1);self.button(row,'Get driven',self.get_driven);self.button(row,'Load channels',self.load_channels)
        form.addRow('Driven transform:',row)
        self.saved=QtWidgets.QComboBox();row=QtWidgets.QHBoxLayout();row.addWidget(self.saved,1)
        self.button(row,'Refresh SDKs',self.refresh_saved);self.button(row,'Load saved',self.load_saved)
        form.addRow('Scene SDK bindings:',row)
        row=QtWidgets.QHBoxLayout();self.key_value=self.number(0,1,1);row.addWidget(QtWidgets.QLabel('Driver key weight:'));row.addWidget(self.key_value)
        self.button(row,'Get live weight',self.live_weight)
        self.tangent=QtWidgets.QComboBox();self.tangent.addItems(['linear','auto','clamped','flat','step'])
        row.addWidget(QtWidgets.QLabel('Tangent:'));row.addWidget(self.tangent)
        self.button(row,'Read driven values',self.read_values);self.button(row,'Choose changed',self.choose_changed)
        outer.addLayout(row)
        self.table=QtWidgets.QTreeWidget();self.table.setColumnCount(9)
        self.table.setHeaderLabels(['Use','Channel','Source neutral','Driven value','Mirror channel','Value rule','Input axis','Mirror neutral','SDK / status'])
        self.table.setRootIsDecorated(False);self.table.setUniformRowHeights(True)
        self.table.setMinimumHeight(285);self.table.setMaximumHeight(340);self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        for col,width in enumerate((42,98,112,112,108,116,98,112,200)):self.table.setColumnWidth(col,width)
        self.table.header().setSectionResizeMode(8,QtWidgets.QHeaderView.Stretch);outer.addWidget(self.table)
        row=QtWidgets.QHBoxLayout();self.button(row,'Set driven key',self.set_key);self.button(row,'Key neutral at 0',self.key_neutral)
        self.button(row,'Save mirror map',self.save_map);self.button(row,'Select SDK curves',self.select_curves)
        self.button(row,'Remove created SDK · keep values',self.remove_sdk);outer.addLayout(row)
        mirror=QtWidgets.QGroupBox('Mirror SDK curves');mf=QtWidgets.QFormLayout(mirror);outer.addWidget(mirror)
        self.search=QtWidgets.QLineEdit('_L');self.replace=QtWidgets.QLineEdit('_R')
        row=QtWidgets.QHBoxLayout();row.addWidget(self.search);row.addWidget(self.replace);self.button(row,'Find counterparts',self.find_mirror)
        mf.addRow('Search / Replace:',row)
        self.mirror_weight=QtWidgets.QLineEdit();self.mirror_weight.setPlaceholderText('Opposite pose weight plug; editable')
        mf.addRow('Mirror driver:',self.mirror_weight)
        self.mirror_driven=QtWidgets.QLineEdit();self.mirror_driven.setPlaceholderText('Opposite driven transform; editable')
        row=QtWidgets.QHBoxLayout();row.addWidget(self.mirror_driven,1);self.button(row,'Get mirror driven',self.get_mirror_driven)
        self.button(row,'Read mirror neutral',self.read_mirror_neutral);mf.addRow('Mirror transform:',row)
        self.replace_owned=QtWidgets.QCheckBox('Replace SDK curves owned by the destination binding');mf.addRow(self.replace_owned)
        row=QtWidgets.QHBoxLayout();self.button(row,'Preview mirror',self.preview_mirror);self.button(row,'Mirror curves',self.mirror);mf.addRow(row)
        note=QtWidgets.QLabel('Raw is independent of Normalize. Weight follows cone.normalize; set Normalize = 1 above for fully normalized weights. '
            'Load the driven at neutral, pose it or edit Driven value, then set a key. Read the opposite transform at neutral before mirroring. '
            'Flip delta uses targetNeutral − (sourceValue − sourceNeutral). Input Reverse means 0 ↔ 1, independently of the value sign. '
            'Each channel supports one direct SDK in this first version. Other rig drivers remain protected.')
        note.setWordWrap(True);outer.addWidget(note)
        self.status=QtWidgets.QLabel('Load a PoseDriver setup, refresh poses, choose its output, then Get driven at neutral.')
        self.status.setWordWrap(True);outer.addWidget(self.status)
        self.driven.textEdited.connect(self.invalidate_source);self.weight.textEdited.connect(self.invalidate_source)
        self.mirror_driven.textChanged.connect(self.invalidate_mirror)
        self.refresh_saved()

    def button(self,layout,label,action):
        button=QtWidgets.QPushButton(label);button.setAutoDefault(False);button.setDefault(False)
        button.clicked.connect(lambda *_:self.guard(action));layout.addWidget(button);return button

    def number(self,lo=-1e12,hi=1e12,value=0):
        spin=QtWidgets.QDoubleSpinBox();spin.setRange(lo,hi);spin.setDecimals(8);spin.setSingleStep(.1);spin.setValue(value)
        spin.setKeyboardTracking(False);return spin

    def guard(self,action):
        try:return action()
        except (ValueError,RuntimeError) as exc:
            self.status.setText(str(exc));self.owner._error(exc)

    def invalidate_source(self,*_):
        self.table.clear();self.cells={};self.meta=None;self.status.setText('Driver or transform changed. Load channels again.')

    def invalidate_mirror(self,*_):
        if not self.updating:self.mirror_neutral_ref=None

    def refresh_poses(self):
        old=self.pose.currentData();self.pose.clear()
        group,state=self.api['_pd_read'](self.owner._group())
        for pose in state['poses']:self.pose.addItem(pose['name'],pose['id'])
        index=self.pose.findData(old)
        if index>=0:self.pose.setCurrentIndex(index)
        self.status.setText('Pose list refreshed. Use pose output copies its stable public driver plug.')

    def use_output(self):
        if not self.pose.currentData():self.refresh_poses()
        self.weight.setText(self.api['_pd_sdk_output'](self.owner._group(),self.pose.currentData(),self.mode.currentData()))
        self.invalidate_source();self.status.setText('Driver selected. Load/Get driven at neutral. Final Weight uses the current Normalize blend.')

    def get_driven(self):
        selected=self.backend.cmds.ls(selection=True,long=True) or []
        if len(selected)!=1:raise ValueError('Select one transform or SDK offset.')
        self.driven.setText(self.backend.transform(selected[0]));self.load_channels()

    def load_channels(self,preserve_values=False):
        old={c:cells['value'].value() for c,cells in self.cells.items()} if preserve_values else {}
        info=self.backend.inspect(self.weight.text().strip(),self.driven.text().strip());self.meta=info['meta']
        self.weight.setText(info['driver']);self.driven.setText(info['driven']);self.table.clear();self.cells={};self.updating=True
        try:
            for row in info['rows']:
                channel=row['channel'];item=QtWidgets.QTreeWidgetItem(self.table,['',channel,'','','','','','',row['status']])
                item.setCheckState(0,QtCore.Qt.Checked if row['enabled'] else QtCore.Qt.Unchecked);item.setToolTip(8,row['status'])
                cells={'item':item,'curve':row.get('curve')}
                for key,col,value in (('neutral',2,row['neutral']),('value',3,old.get(channel,row['value'])),('target_neutral',7,row['target_neutral'])):
                    cells[key]=self.number(value=value);self.table.setItemWidget(item,col,cells[key])
                combo=QtWidgets.QComboBox();combo.addItems([channel[:-1]+a for a in 'XYZ']);combo.setCurrentText(row['mirror_channel'])
                combo.currentIndexChanged.connect(self.invalidate_mirror);cells['mirror_channel']=combo;self.table.setItemWidget(item,4,combo)
                combo=QtWidgets.QComboBox()
                for label,value in VALUE_RULES:combo.addItem(label,value)
                combo.setCurrentIndex(combo.findData(row['rule']));cells['rule']=combo;self.table.setItemWidget(item,5,combo)
                combo=QtWidgets.QComboBox();combo.addItem('Keep 0→1','keep');combo.addItem('Reverse 1→0','reverse')
                combo.setCurrentIndex(combo.findData(row['input_rule']));cells['input_rule']=combo;self.table.setItemWidget(item,6,combo)
                self.cells[channel]=cells
        finally:self.updating=False
        data=info['data']
        if data.get('mirror_driver'):
            try:self.mirror_weight.setText(self.backend.plug_name(data['mirror_driver']))
            except ValueError:self.mirror_weight.clear()
        if data.get('mirror_driven'):
            try:
                self.mirror_driven.setText(self.backend.resolve(data['mirror_driven']));self.mirror_neutral_ref=data['mirror_driven']
            except ValueError:self.mirror_driven.clear();self.mirror_neutral_ref=None
        self.status.setText('Neutral restored from SDK metadata, or sampled on first load. Edit Key value or Read driven values; driver outputs are never overwritten.')

    def rows(self):
        if not self.cells:raise ValueError('Load the driven channels first.')
        result=[]
        for channel,cells in self.cells.items():
            row=dict(channel=channel,enabled=cells['item'].checkState(0)==QtCore.Qt.Checked)
            row.update({key:cells[key].value() for key in ('neutral','value','target_neutral')})
            row['mirror_channel']=cells['mirror_channel'].currentText()
            row.update({key:cells[key].currentData() for key in ('rule','input_rule')});result.append(row)
        return result

    def read_values(self):
        if not self.cells:raise ValueError('Load channels before sampling key values.')
        target=self.backend.transform(self.driven.text().strip())
        for channel,cells in self.cells.items():cells['value'].setValue(self.backend.cmds.getAttr(target+'.'+channel))
        self.status.setText('Current driven values sampled. Neutral references were kept.')

    def choose_changed(self):
        for cells in self.cells.values():cells['item'].setCheckState(0,QtCore.Qt.Checked if abs(cells['value'].value()-cells['neutral'].value())>1e-8 else QtCore.Qt.Unchecked)

    def live_weight(self):self.key_value.setValue(self.backend.cmds.getAttr(self.backend.driver(self.weight.text().strip())))

    def set_key(self):
        result=self.backend.capture(self.weight.text().strip(),self.driven.text().strip(),self.rows(),self.key_value.value(),self.tangent.currentText())
        self.meta=result['meta'];self.load_channels(True);self.refresh_saved();self.status.setText('Set {} driven channels at weight {}. Edit the Driven value fields to author another sample.'.format(result['channels'],result['driver_value']))

    def key_neutral(self):
        rows=self.rows()
        for row in rows:row['value']=row['neutral']
        result=self.backend.capture(self.weight.text().strip(),self.driven.text().strip(),rows,0.,self.tangent.currentText())
        self.meta=result['meta'];self.load_channels(True);self.refresh_saved();self.status.setText('Neutral keys written at weight 0; driver values were kept.')

    def refresh_saved(self):
        wanted=self.backend.identity(self.meta) if self.meta and self.backend.cmds.objExists(self.meta) else self.saved.currentData()
        self.saved.clear()
        for meta in self.backend.bindings():
            try:
                _,data=self.backend.read(meta)
                try:target=self.backend.resolve(data['driven'])
                except ValueError:target='Missing driven'
                label=target.rsplit('|',1)[-1]+' ← '+data['driver']['attr']
            except (ValueError,RuntimeError):label=meta+' · metadata needs checking'
            self.saved.addItem(label,self.backend.identity(meta))
        index=self.saved.findData(wanted)
        if index>=0:self.saved.setCurrentIndex(index)

    def load_saved(self):
        if not self.saved.currentData():raise ValueError('No SDK binding selected.')
        meta=self.backend.resolve(self.saved.currentData());self.meta=meta;_,data=self.backend.read(meta)
        self.weight.setText(self.backend.plug_name(data['driver']));self.driven.setText(self.backend.resolve(data['driven']));self.load_channels()

    def find_mirror(self):
        search,replace=self.api['_pd_mirror_tokens'](self.search.text(),self.replace.text())
        current=self.api['_pd_sdk_output'](self.owner._group(),self.pose.currentData(),self.mode.currentData())
        if not self.backend.same(current,self.weight.text().strip()):raise ValueError('Use the selected pose output before Find counterparts, or enter the mirror driver/transform manually.')
        output=self.api['_pd_sdk_mirror_output'](self.owner._group(),self.pose.currentData(),self.mode.currentData(),search,replace)
        target=self.api['_pd_mirror_object'](self.backend.transform(self.driven.text().strip()),search,replace,require_change=True)
        self.mirror_weight.setText(output);self.mirror_driven.setText(target)
        self.status.setText('Counterparts found. Put the mirror transform at neutral and Read mirror neutral before Preview.')

    def get_mirror_driven(self):
        selected=self.backend.cmds.ls(selection=True,long=True) or []
        if len(selected)!=1:raise ValueError('Select one opposite driven transform.')
        self.mirror_driven.setText(self.backend.transform(selected[0]))

    def read_mirror_neutral(self):
        if not self.cells:raise ValueError('Load source channels first.')
        target=self.backend.transform(self.mirror_driven.text().strip())
        values={channel:self.backend.finite(self.backend.cmds.getAttr(target+'.'+cells['mirror_channel'].currentText())) for channel,cells in self.cells.items()}
        for channel,value in values.items():self.cells[channel]['target_neutral'].setValue(value)
        self.mirror_neutral_ref=self.backend.identity(target);self.status.setText('Opposite neutral sampled in local channels. Adjust table values and Keep/Flip rules as needed.')

    def mirror_args(self):
        target=self.backend.transform(self.mirror_driven.text().strip())
        if self.mirror_neutral_ref!=self.backend.identity(target):raise ValueError('Read mirror neutral after choosing the target/channel mapping.')
        return self.weight.text().strip(),self.driven.text().strip(),self.mirror_weight.text().strip(),target,self.rows(),self.replace_owned.isChecked()

    def preview_mirror(self):
        result=self.backend.preview_mirror(*self.mirror_args())
        self.status.setText('Mirror ready: '+ '; '.join(r['channel']+' → '+r['mirror_channel']+' · '+r['rule']+' · '+r['input_rule'] for r in result))

    def save_map(self):
        target=self.mirror_driven.text().strip();weight=self.mirror_weight.text().strip()
        if target and self.mirror_neutral_ref!=self.backend.identity(self.backend.transform(target)):raise ValueError('Read mirror neutral before saving a target map.')
        self.meta=self.backend.save_map(self.weight.text().strip(),self.driven.text().strip(),self.rows(),weight or None,target or None)
        self.refresh_saved();self.status.setText('Mirror rules, local neutral references and object UUIDs saved in the scene.')

    def mirror(self):
        result=self.backend.mirror(*self.mirror_args());self.refresh_saved()
        self.status.setText('Mirrored {} SDK curves. Source keys/driver values were kept. Undo restores the prior destination.'.format(result['channels']))

    def select_curves(self):
        if not self.meta:raise ValueError('Load or create an SDK binding first.')
        _,data=self.backend.read(self.meta);curves=[self.backend.resolve(r['curve']) for r in data['rows'].values() if r.get('curve')]
        if not curves:raise ValueError('This binding has no created curves.')
        self.backend.cmds.select(curves,replace=True);self.status.setText('SDK curves selected for Graph Editor edits. Mirror copies the full curve and tangent data.')

    def remove_sdk(self):
        meta=self.backend.resolve(self.saved.currentData()) if self.saved.currentData() else self.meta
        if not meta:raise ValueError('Choose a saved SDK binding first.')
        count=self.backend.remove(meta);self.meta=None;self.invalidate_source();self.refresh_saved()
        self.status.setText('Removed {} created SDK curves; current driven values kept. PoseDriver and target transforms remain.'.format(count))
