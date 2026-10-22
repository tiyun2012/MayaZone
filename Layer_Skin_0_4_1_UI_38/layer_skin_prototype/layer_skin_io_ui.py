"""Utilities page inside Layer Skin: final-skin files and layer-aware import."""
import contextlib
import os
import weakref
try:
    from PySide6 import QtCore,QtWidgets
except ImportError:
    from PySide2 import QtCore,QtWidgets


class Utilities(QtWidgets.QWidget):
    def __init__(self,window):
        super(Utilities,self).__init__(window)
        self.owner=weakref.ref(window);self._backend=None;self.snapshot=None;self.plan=None
        self.manual={};self.manual_paths={};self.file_stamp=None;self._busy=False;self._filling=False
        outer=QtWidgets.QVBoxLayout(self);outer.setContentsMargins(0,0,0,0)
        self.scroll=QtWidgets.QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame);outer.addWidget(self.scroll,1)
        content=QtWidgets.QWidget();self.scroll.setWidget(content);layout=QtWidgets.QVBoxLayout(content)
        note=QtWidgets.QLabel('Export the final native skin result. Import creates a new top layer and keeps your existing layers, masks and bind matrices.');note.setWordWrap(True);layout.addWidget(note)
        export=QtWidgets.QGroupBox('Export skinning');e=QtWidgets.QGridLayout(export);layout.addWidget(export)
        self.export_mesh=QtWidgets.QLineEdit();self.export_mesh.setPlaceholderText('Mesh to export')
        e.addWidget(self.export_mesh,0,0,1,3);self.button(e,'Use selected mesh',lambda:self.pick_mesh(self.export_mesh),0,3)
        self.button(e,'Use layer mesh',lambda:self.export_mesh.setText(window.target.text()),1,0)
        self.export_geometry=QtWidgets.QComboBox();self.export_geometry.addItems(['Pre-deformed / base','Current deformed'])
        e.addWidget(self.export_geometry,1,1,1,2)
        self.include_geometry=QtWidgets.QCheckBox('Include transfer geometry');self.include_geometry.setChecked(True);e.addWidget(self.include_geometry,1,3)
        self.export_path=QtWidgets.QLineEdit();self.export_path.setPlaceholderText('Save to .rtkskin')
        e.addWidget(self.export_path,2,0,1,3);self.button(e,'Browse…',self.choose_export,2,3)
        self.button(e,'Export skin file',self.export_file,3,0,1,4)
        group=QtWidgets.QGroupBox('Import skinning');g=QtWidgets.QGridLayout(group);layout.addWidget(group)
        self.import_path=QtWidgets.QLineEdit();self.import_path.setPlaceholderText('Open a .rtkskin file')
        g.addWidget(self.import_path,0,0,1,3);self.button(g,'Browse…',self.choose_import,0,3)
        load_row=QtWidgets.QHBoxLayout();self.button(load_row,'Load file',self.load_file);self.button(load_row,'Unload',self.unload_file);g.addLayout(load_row,1,0)
        self.file_info=QtWidgets.QLabel('No file loaded.');self.file_info.setWordWrap(True);g.addWidget(self.file_info,1,1,1,3)
        self.target=QtWidgets.QLineEdit();self.target.setPlaceholderText('Target mesh; skinned or unskinned')
        g.addWidget(self.target,2,0,1,3);self.button(g,'Use selected mesh',lambda:self.pick_mesh(self.target),2,3)
        self.button(g,'Use layer mesh',lambda:self.target.setText(window.target.text()),3,0)
        self.method=QtWidgets.QComboBox();self.method.addItems(['Vertex ID · matching topology','Closest surface · barycentric'])
        g.addWidget(self.method,3,1,1,3)
        self.target_geometry=QtWidgets.QComboBox();self.target_geometry.addItems(['Pre-deformed / base','Current deformed'])
        g.addWidget(QtWidgets.QLabel('Target geometry'),4,0);g.addWidget(self.target_geometry,4,1)
        self.max_distance=self.number(0,1000000,0,6);self.max_distance.setSpecialValueText('Unlimited')
        g.addWidget(QtWidgets.QLabel('Max surface distance'),4,2);g.addWidget(self.max_distance,4,3)
        self.layer_name=QtWidgets.QLineEdit('Imported skin');g.addWidget(QtWidgets.QLabel('New layer name'),5,0);g.addWidget(self.layer_name,5,1,1,3)
        self.copy_dq=QtWidgets.QCheckBox('Import DQ weights · skin-wide');self.copy_dq.setChecked(True);g.addWidget(self.copy_dq,6,0,1,2)
        self.copy_method=QtWidgets.QCheckBox('Restore method · skin-wide');self.copy_method.setChecked(True);g.addWidget(self.copy_method,6,2,1,2)
        for control in (self.copy_dq,self.copy_method):control.setToolTip('These are native skinCluster settings, shared by the whole layer stack. Layer enable/alpha does not blend them. Undo restores their previous values.')
        self.create_skin=QtWidgets.QCheckBox('Create skinCluster if missing');self.create_skin.setChecked(True);g.addWidget(self.create_skin,7,0,1,2)
        self.add_influences=QtWidgets.QCheckBox('Add missing mapped influences');self.add_influences.setChecked(True);g.addWidget(self.add_influences,7,2,1,2)
        note=QtWidgets.QLabel('Surface transfer compares mesh-object positions in centimeters. Align model shapes in their own object spaces. Maximum surface distance and joint tolerance use the current Maya linear unit.');note.setWordWrap(True);g.addWidget(note,8,0,1,4)
        mapping=QtWidgets.QGroupBox('Influence mapping');m=QtWidgets.QGridLayout(mapping);layout.addWidget(mapping)
        self.root=QtWidgets.QLineEdit();self.root.setPlaceholderText('Optional joint hierarchy root; blank searches scene joints')
        m.addWidget(self.root,0,0,1,3);self.button(m,'Use selected joint root',self.pick_root,0,3)
        self.use_name=QtWidgets.QCheckBox('Names');self.use_name.setChecked(True);self.use_distance=QtWidgets.QCheckBox('Bind distance');self.use_distance.setChecked(True)
        self.ignore_namespace=QtWidgets.QCheckBox('Ignore namespaces');self.ignore_namespace.setChecked(True)
        m.addWidget(self.use_name,1,0);m.addWidget(self.use_distance,1,1);m.addWidget(self.ignore_namespace,1,2)
        self.tolerance=self.number(0,1000000,.01,6);m.addWidget(self.tolerance,1,3)
        self.search=QtWidgets.QLineEdit();self.replace=QtWidgets.QLineEdit();self.edits=QtWidgets.QSpinBox();self.edits.setRange(0,10);self.edits.setValue(3)
        self.search.setPlaceholderText('Search in source names');self.replace.setPlaceholderText('Replace with')
        m.addWidget(self.search,2,0);m.addWidget(self.replace,2,1);m.addWidget(QtWidgets.QLabel('Max name edits'),2,2);m.addWidget(self.edits,2,3)
        self.table=QtWidgets.QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['Source influence','Target influence','Match'])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers);self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection);self.table.setMinimumHeight(120)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch);m.addWidget(self.table,3,0,1,4)
        self.button(m,'Map row to selected joint',self.map_selected,4,0,1,2);self.button(m,'Clear row override',self.clear_manual,4,2);self.button(m,'Reset mapping',self.reset_mapping,4,3)
        row=QtWidgets.QHBoxLayout();outer.addLayout(row)
        self.preview_button=self.button(row,'Preview import',self.preview_import)
        self.import_button=self.button(row,'Import as new layer',self.import_file);self.import_button.setEnabled(False)
        self.note=QtWidgets.QLabel('Load a file, choose the target, then Preview import. No scene data is created by Preview.');self.note.setWordWrap(True);outer.addWidget(self.note)
        layout.addStretch(1)
        for field in (self.target,self.root,self.layer_name,self.search,self.replace):field.textChanged.connect(self.invalidate)
        self.import_path.textChanged.connect(self.path_changed)
        for box in (self.method,self.target_geometry):box.currentIndexChanged.connect(self.invalidate)
        for value in (self.max_distance,self.tolerance,self.edits):value.valueChanged.connect(self.invalidate)
        for check in (self.copy_dq,self.copy_method,self.use_name,self.use_distance,self.ignore_namespace,self.create_skin,self.add_influences):check.toggled.connect(self.invalidate)
        self.method.currentIndexChanged.connect(self.method_changed);self.method_changed()
    @property
    def backend(self):
        if self._backend is None:
            window=self.owner();factory=getattr(window.api,'make_skin_io_backend',None)
            self._backend=factory(window.session) if factory else window.session.helper('layer_skin_io_backend').Backend(window.api)
        return self._backend
    @property
    def io(self):return self.owner().session.helper('layer_skin_io')
    def verticalScrollBar(self):return self.scroll.verticalScrollBar()
    def number(self,low,high,value,decimals):
        field=QtWidgets.QDoubleSpinBox();field.setRange(low,high);field.setDecimals(decimals);field.setValue(value);field.setKeyboardTracking(False);return field
    def button(self,layout,text,callback,*position):
        button=QtWidgets.QPushButton(text);button.setAutoDefault(False);button.setDefault(False)
        button.clicked.connect(lambda *_:callback());layout.addWidget(button,*position);return button
    def method_changed(self,*_):
        enabled=self.method.currentIndex()==1;self.max_distance.setEnabled(enabled);self.target_geometry.setEnabled(enabled)
    def invalidate(self,*_):
        self.plan=None
        if hasattr(self,'import_button'):self.import_button.setEnabled(False)
    def path_changed(self,*_):
        self.clear_file();self.file_info.setText('Path changed; load the file again.')
    def clear_file(self):
        self.snapshot=None;self.file_stamp=None;self.manual={};self.manual_paths={};self.invalidate()
        if hasattr(self,'table'):self.table.setRowCount(0)
    def unload_file(self):self.clear_file();self.file_info.setText('File unloaded. Load file to read it again.')
    def capture_ui(self):
        return dict(text={name:getattr(self,name).text() for name in ('export_mesh','export_path','import_path','target','layer_name','root','search','replace')},
            combos={name:getattr(self,name).currentIndex() for name in ('export_geometry','method','target_geometry')},
            numbers={name:getattr(self,name).value() for name in ('max_distance','tolerance','edits')},
            checks={name:getattr(self,name).isChecked() for name in ('include_geometry','copy_dq','copy_method','create_skin','add_influences','use_name','use_distance','ignore_namespace')},
            snapshot=self.snapshot,file_stamp=self.file_stamp,manual=dict(self.manual),manual_paths=dict(self.manual_paths),file_info=self.file_info.text())
    def restore_ui(self,state):
        for name,value in state['text'].items():getattr(self,name).setText(value)
        for name,value in state['combos'].items():getattr(self,name).setCurrentIndex(value)
        for name,value in state['numbers'].items():getattr(self,name).setValue(value)
        for name,value in state['checks'].items():getattr(self,name).setChecked(value)
        self.snapshot=state['snapshot'];self.file_stamp=state['file_stamp'];self.manual=dict(state['manual']);self.manual_paths=dict(state['manual_paths'])
        self.file_info.setText(state['file_info']);self.invalidate()
    def scene_reset(self):
        self.target.clear();self.export_mesh.clear();self.root.clear();self.manual={};self.manual_paths={};self.invalidate();self.table.setRowCount(0)
        self.note.setText('Scene changed. Choose the new target and Preview again; the external file remains loaded.')
    @contextlib.contextmanager
    def operation(self):
        if self._busy:raise RuntimeError('A Utilities operation is already running.')
        window=self.owner();self._busy=True;previous=window._working;window._working=True
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor);self.setEnabled(False)
        try:
            if not window.stop_paint():raise RuntimeError('A pending paint stroke could not be saved. Resolve it before file operations.')
            yield
        finally:self.setEnabled(True);QtWidgets.QApplication.restoreOverrideCursor();window._working=previous;self._busy=False
    def error(self,exc):self.note.setText(str(exc));self.owner().message(str(exc),True)
    def pick_mesh(self,field):
        try:field.setText(self.backend.selected_mesh())
        except Exception as exc:self.error(exc)
    def pick_root(self):
        try:self.root.setText(self.backend.selected_joint())
        except Exception as exc:self.error(exc)
    def choose_export(self):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'Export skinning',self.export_path.text(),'Rig Toolkit skin (*.rtkskin)')
        if path:self.export_path.setText(path if path.lower().endswith('.rtkskin') else path+'.rtkskin')
    def choose_import(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Import skinning',self.import_path.text(),'Rig Toolkit skin (*.rtkskin)')
        if path:self.import_path.setText(path);self.load_file()
    def export_file(self):
        try:
            path=self.export_path.text().strip()
            if not path:self.choose_export();path=self.export_path.text().strip()
            if not path:return
            if not path.lower().endswith('.rtkskin'):path+='.rtkskin';self.export_path.setText(path)
            overwrite=os.path.exists(path)
            if overwrite and QtWidgets.QMessageBox.question(self,'Replace skin file?',path,QtWidgets.QMessageBox.Yes|QtWidgets.QMessageBox.Cancel,QtWidgets.QMessageBox.Cancel)!=QtWidgets.QMessageBox.Yes:return
            with self.operation():result=self.backend.export(self.export_mesh.text(),path,'current' if self.export_geometry.currentIndex() else 'base',self.include_geometry.isChecked(),overwrite)
            self.note.setText('Exported {} vertices / {} influences to {}.'.format(result['vertices'],result['influences'],result['path']))
        except Exception as exc:self.error(exc)
    def stamp(self):
        value=os.stat(self.import_path.text().strip());return os.path.abspath(self.import_path.text().strip()),value.st_size,value.st_mtime_ns
    def require_file(self):
        if self.snapshot is None:raise ValueError('Load a skin file first.')
        if self.stamp()!=self.file_stamp:raise ValueError('The skin file changed on disk. Load it again.')
    def load_file(self):
        try:
            self.clear_file()
            with self.operation():
                before=self.stamp();self.snapshot=self.io.read(self.import_path.text().strip());self.file_stamp=self.stamp()
                if before!=self.file_stamp:raise ValueError('The skin file changed while loading. Load it again.')
            value=self.snapshot;self.file_info.setText('{} vertices · {} influences · {} geometry · DQ {}.'.format(value['count'],len(value['influences']),value.get('geometry','base') if value.get('points') is not None else 'no surface','included' if value.get('dq') is not None else 'absent'))
            self.layer_name.setText(os.path.splitext(os.path.basename(self.import_path.text()))[0]+'_import')
            self.note.setText('File loaded. Preview matches weighted influences; existing target layers remain intact.')
        except Exception as exc:self.clear_file();self.error(exc)
    def settings(self):
        return dict(options=dict(name=self.use_name.isChecked(),distance=self.use_distance.isChecked(),ignore_namespace=self.ignore_namespace.isChecked(),
            tolerance=self.tolerance.value(),max_edits=self.edits.value(),search=self.search.text(),replace=self.replace.text()),
            root=self.root.text().strip(),method='surface' if self.method.currentIndex() else 'id',geometry='current' if self.target_geometry.currentIndex() else 'base',
            max_distance=self.max_distance.value(),copy_dq=self.copy_dq.isChecked(),copy_method=self.copy_method.isChecked(),name=self.layer_name.text().strip())
    def fill_mapping(self,plan):
        rows=plan['report']['rows'];self.table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for col,text in enumerate((row['source'],row.get('target') or '—',row['method'])):
                item=QtWidgets.QTableWidgetItem(text);item.setToolTip(text)
                if col==0:item.setData(QtCore.Qt.UserRole,row['source_uuid'])
                self.table.setItem(i,col,item)
    def preview_import(self):
        try:
            self.invalidate();self.require_file()
            paths={identity:path for identity,path in self.manual_paths.items() if identity in self.manual.values()}
            with self.operation():plan=self.backend.preview(self.snapshot,self.target.text().strip(),manual=self.manual,manual_paths=paths,**self.settings())
            self.plan=plan;self.fill_mapping(plan);self.import_button.setEnabled(plan['report']['complete'])
            self.note.setText(('Ready: import {} vertices as a new top layer. '.format(plan['payload']['count']) if plan['report']['complete'] else 'Resolve the highlighted mapping rows before Import. ')+
                ('Create a skinCluster. ' if not plan.get('skin') else '')+('{} mapped influences need binding. '.format(len(plan.get('missing',[]))) if plan.get('missing') else '')+
                ' '.join(plan['report'].get('errors',[])))
        except Exception as exc:self.error(exc)
    def selected_source(self):
        row=self.table.currentRow()
        if row<0:raise ValueError('Select a source influence row in the mapping table.')
        return self.table.item(row,0).data(QtCore.Qt.UserRole)
    def map_selected(self):
        try:
            identity=self.selected_source();path=self.backend.selected_joint();target_id=self.owner().api.joint_id(path)
            self.manual[identity]=target_id;self.manual_paths[target_id]=path;self.preview_import()
        except Exception as exc:self.error(exc)
    def clear_manual(self):
        try:self.manual.pop(self.selected_source(),None);self.preview_import()
        except Exception as exc:self.error(exc)
    def reset_mapping(self):self.manual={};self.manual_paths={};self.preview_import()
    def import_file(self):
        try:
            self.require_file()
            if self.plan is None:raise ValueError('Preview the import first.')
            plan=self.plan
            with self.operation():result=self.backend.commit(plan,self.create_skin.isChecked(),self.add_influences.isChecked())
            window=self.owner();window.target.setText(plan['target']);window.refresh(force_browser=True)
            if window.rows:window.layers.setCurrentItem(window.layers.topLevelItem(0),1)
            self.invalidate();self.note.setText(str(result)+' Undo restores the previous stack, weights and DQ settings.');window.message(self.note.text())
        except Exception as exc:self.invalidate();self.error(exc)
