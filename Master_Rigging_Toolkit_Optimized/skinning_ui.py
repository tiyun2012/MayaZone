"""Unified Skinning Tools: OpenMaya weight editor and existing Copy Skinning."""
import importlib.util
import json
import os
from functools import wraps
import maya.cmds as cmds
import maya.mel as mel
import maya.OpenMayaUI as omui
try:
    from PySide6 import QtWidgets,QtCore
    import shiboken6 as shiboken
except ImportError:
    from PySide2 import QtWidgets,QtCore
    import shiboken2 as shiboken

_dialog=None


def sibling(name):
    filename=os.path.join(os.path.dirname(__file__),name+'.py')
    if not os.path.isfile(filename):raise ImportError('Missing '+name+'.py. Replace the complete Skinning Tools folder.')
    spec=importlib.util.spec_from_file_location('_rtk_'+name+'_panel',filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def action(function):
    @wraps(function)
    def guarded(self,*args,**kwargs):
        if self._busy:return
        self._busy=True;enabled=self.isEnabled();self.setEnabled(False)
        try:return function(self,*args,**kwargs)
        except Exception as exc:self.say(exc,True)
        finally:
            self._busy=False
            if shiboken.isValid(self):self.setEnabled(enabled)
    return guarded


def fold(layout,title,widget,opened=False):
    button=QtWidgets.QToolButton();button.setText(title);button.setCheckable(True);button.setChecked(opened)
    button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon);button.setSizePolicy(QtWidgets.QSizePolicy.Expanding,QtWidgets.QSizePolicy.Fixed)
    def toggle(value):
        button.setArrowType(QtCore.Qt.DownArrow if value else QtCore.Qt.RightArrow);widget.setVisible(value)
    button.toggled.connect(toggle);layout.addWidget(button);layout.addWidget(widget);toggle(opened)
    return button


class WeightEditorPanel(QtWidgets.QWidget):
    def __init__(self,copy_ui,parent=None):
        super(WeightEditorPanel,self).__init__(parent)
        self.copy_ui=copy_ui;self.info=None;self.copied=None;self.hidden=set();self.extra=set();self._busy=False
        outer=QtWidgets.QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(8)
        scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        body=QtWidgets.QWidget();scroll.setWidget(body);outer.addWidget(scroll,1)
        layout=QtWidgets.QVBoxLayout(body);layout.setContentsMargins(4,4,4,4);layout.setSpacing(10)
        mesh_box=QtWidgets.QGroupBox('Mesh and selection');form=QtWidgets.QFormLayout(mesh_box)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow);form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
        row=QtWidgets.QHBoxLayout();self.mesh=QtWidgets.QLineEdit();self.mesh.setMinimumWidth(0);self.mesh.setPlaceholderText('Select a skinned mesh or its components')
        row.addWidget(self.mesh,1);self.button(row,'Get mesh',lambda:self.get_mesh());self.button(row,'Refresh',lambda:self.refresh());form.addRow('Mesh:',row)
        self.mesh.textChanged.connect(self.invalidate)
        self.scope=QtWidgets.QComboBox();self.scope.addItem('Current component / object selection',False);self.scope.addItem('Whole loaded mesh',True)
        form.addRow('Edit scope:',self.scope)
        self.scope.setToolTip('Refresh after changing the selection or using Undo / Redo. A selected mesh object means all vertices.');layout.addWidget(mesh_box)
        influences=QtWidgets.QGroupBox('Influences');influence_layout=QtWidgets.QVBoxLayout(influences)
        row=QtWidgets.QHBoxLayout();self.search=QtWidgets.QLineEdit();self.search.setMinimumWidth(0);self.search.setPlaceholderText('Filter influences…');self.search.textChanged.connect(self.render);row.addWidget(self.search,1)
        self.weighted=QtWidgets.QCheckBox('Weighted only');self.weighted.setChecked(True);row.addWidget(self.weighted)
        self.button(row,'Load all',lambda:self.load_all());influence_layout.addLayout(row)
        self.table=QtWidgets.QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['Influence','Average weight','Hold'])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows);self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers);self.table.setMinimumHeight(165)
        self.table.setAlternatingRowColors(True);self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1,QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2,QtWidgets.QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self.update_total);influence_layout.addWidget(self.table,1)
        self.total=QtWidgets.QLabel('Select influence rows to edit their combined weight.');self.total.setWordWrap(True);influence_layout.addWidget(self.total)
        layout.addWidget(influences,1)
        edit=QtWidgets.QGroupBox('Weight editing');edit_layout=QtWidgets.QVBoxLayout(edit)
        grid=QtWidgets.QGridLayout();grid.addWidget(QtWidgets.QLabel('Set total'),0,0);self.value=self.spin(0,1,.5,4);grid.addWidget(self.value,0,1)
        button=QtWidgets.QPushButton('Set weight');button.setProperty('primary',True);button.clicked.connect(lambda *_:self.edit('set',self.value.value()));grid.addWidget(button,0,2,1,2)
        grid.addWidget(QtWidgets.QLabel('Nudge'),1,0);self.nudge=self.spin(.0001,1,.005,4);grid.addWidget(self.nudge,1,1)
        button=QtWidgets.QPushButton('−');button.setToolTip('Subtract the nudge amount');button.clicked.connect(lambda *_:self.edit('nudge',-self.nudge.value()));grid.addWidget(button,1,2)
        button=QtWidgets.QPushButton('+');button.setToolTip('Add the nudge amount');button.clicked.connect(lambda *_:self.edit('nudge',self.nudge.value()));grid.addWidget(button,1,3)
        grid.setColumnStretch(1,1);grid.setColumnStretch(2,1);grid.setColumnStretch(3,1);edit_layout.addLayout(grid)
        row=QtWidgets.QHBoxLayout()
        for value in (0.,.1,.25,.5,.75,.9,1.):
            button=self.button(row,str(value),lambda v=value:self.edit('set',v));button.setToolTip('Set selected influences to a combined weight of '+str(value))
        edit_layout.addLayout(row)
        row=QtWidgets.QHBoxLayout();row.addWidget(QtWidgets.QLabel('Blend strength:'));self.strength=self.spin(0,1,1,3);row.addWidget(self.strength,1)
        self.auto_refresh=QtWidgets.QCheckBox('Refresh after actions');self.auto_refresh.setChecked(True);row.addWidget(self.auto_refresh);edit_layout.addLayout(row);layout.addWidget(edit)
        selection=QtWidgets.QWidget();selection_layout=QtWidgets.QVBoxLayout(selection);selection_layout.setContentsMargins(4,4,4,4)
        row=QtWidgets.QHBoxLayout();self.hold_scope=QtWidgets.QComboBox()
        for title,value in (('Selected rows','selected'),('Other influences','other'),('Visible rows','visible'),('All influences','all')):self.hold_scope.addItem(title,value)
        row.addWidget(self.hold_scope,1)
        for title,mode in (('Hold','hold'),('Unhold','unhold'),('Toggle','toggle')):self.button(row,title,lambda m=mode:self.hold(m))
        selection_layout.addLayout(row)
        grid=QtWidgets.QGridLayout()
        for i,(title,kind) in enumerate((('Select joints','joints'),('Select affected','replace'),('Add affected','add'),('Deselect affected','remove'),('Influence set','set'))):
            button=QtWidgets.QPushButton(title);button.clicked.connect(lambda *_,k=kind:self.select_action(k));grid.addWidget(button,i//3,i%3)
        selection_layout.addLayout(grid)
        row=QtWidgets.QHBoxLayout();self.button(row,'Show selected joints',lambda:self.add_joints());self.button(row,'Hide rows',lambda:self.hide_rows())
        self.neighbors=QtWidgets.QCheckBox('Joint neighbors');row.addWidget(self.neighbors);selection_layout.addLayout(row)
        fold(layout,'Selection and Hold',selection)
        utilities=QtWidgets.QWidget();utility_layout=QtWidgets.QVBoxLayout(utilities);utility_layout.setContentsMargins(4,4,4,4)
        grid=QtWidgets.QGridLayout()
        for i,(title,callback) in enumerate((('Copy vertex weights',lambda:self.copy_weights()),('Paste average',lambda:self.edit('paste')),('Average boundary',lambda:self.edit('average')),('Smooth / Hammer',lambda:self.edit('smooth')))):
            button=QtWidgets.QPushButton(title);button.clicked.connect(lambda *_,f=callback:f());grid.addWidget(button,i//2,i%2)
        utility_layout.addLayout(grid)
        row=QtWidgets.QHBoxLayout();row.addWidget(QtWidgets.QLabel('Prune below:'));self.threshold=self.spin(0,1,.001,5);row.addWidget(self.threshold,1);self.button(row,'Prune',lambda:self.edit('prune'));utility_layout.addLayout(row)
        fold(layout,'Clipboard and cleanup',utilities)
        mirror=QtWidgets.QWidget();form=QtWidgets.QFormLayout(mirror);form.setContentsMargins(4,4,4,4)
        form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows);form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        self.axis=QtWidgets.QComboBox()
        for label,axis in (('YZ plane · reflect X',0),('XZ plane · reflect Y',1),('XY plane · reflect Z',2)):self.axis.addItem(label,axis)
        form.addRow('World mirror plane:',self.axis)
        self.direction=QtWidgets.QComboBox();self.direction.addItem('Positive → negative',1);self.direction.addItem('Negative → positive',-1);form.addRow('Source → destination:',self.direction)
        row=QtWidgets.QHBoxLayout();self.left=QtWidgets.QLineEdit('_L');self.right=QtWidgets.QLineEdit('_R');row.addWidget(self.left);row.addWidget(QtWidgets.QLabel('↔'));row.addWidget(self.right);form.addRow('Influence tokens:',row)
        self.geometry=QtWidgets.QComboBox();self.geometry.addItem('Pre-skin · automatic','base');self.geometry.addItem('Current · deformed','current');form.addRow('Sample mesh:',self.geometry)
        self.base=QtWidgets.QLineEdit();self.base.setMinimumWidth(0);self.base.setPlaceholderText('Optional mesh with matching topology');form.addRow('Base override:',self.base)
        button=QtWidgets.QPushButton('Mirror weights into destination side');button.clicked.connect(lambda *_:self.edit('mirror'));form.addRow(button)
        fold(layout,'Mirror weights',mirror)
        tools=QtWidgets.QWidget();row=QtWidgets.QHBoxLayout(tools);row.setContentsMargins(4,4,4,4)
        self.button(row,'Component Editor',lambda:mel.eval('ComponentEditor;'));self.button(row,'Paint Skin Weights',lambda:mel.eval('ArtPaintSkinWeightsToolOptions;'))
        fold(layout,'Maya tools',tools)
        self.status=QtWidgets.QLabel();self.status.setWordWrap(True);self.status.setMinimumWidth(0);outer.addWidget(self.status)
        self.report=QtWidgets.QPlainTextEdit();self.report.setReadOnly(True);self.report.setFixedHeight(110)
        self.details_toggle=fold(outer,'Action details',self.report)
        self.say('Ready. Get a mesh, then select influence rows to edit weights.')

    @staticmethod
    def spin(low,high,value,decimals):
        widget=QtWidgets.QDoubleSpinBox();widget.setDecimals(decimals);widget.setRange(low,high);widget.setValue(value);widget.setSingleStep(.01);return widget
    def button(self,layout,title,callback):
        button=QtWidgets.QPushButton(title);button.clicked.connect(lambda *_:callback());layout.addWidget(button);return button
    def say(self,text,error=False):
        self.report.setPlainText(str(text))
        brief=str(text).splitlines()[0] if str(text) else ''
        self.status.setText(brief[:200]+('…' if len(brief)>200 else ''));self.status.setToolTip(str(text))
        if error:self.details_toggle.setChecked(True)
        if error:cmds.warning('Skinning Tools: '+str(text))
    def api(self):return self.copy_ui.backend()
    def invalidate(self,*_):
        self.info=None;self.hidden.clear();self.extra.clear()
        if hasattr(self,'table'):self.table.setRowCount(0)
    def selected_ids(self):
        return [self.table.item(index.row(),0).data(QtCore.Qt.UserRole) for index in self.table.selectionModel().selectedRows()]
    def visible_ids(self):return [self.table.item(i,0).data(QtCore.Qt.UserRole) for i in range(self.table.rowCount())]
    def render(self,*_):
        if not self.info:return
        selected=set(self.selected_ids());query=self.search.text().lower();self.table.setRowCount(0)
        for record in self.info['rows']:
            identity=record['uuid']
            if identity in self.hidden or (query and query not in record['path'].lower()):continue
            row=self.table.rowCount();self.table.insertRow(row)
            for column,text in enumerate((record['path'].rsplit('|',1)[-1],'{:.6f}'.format(record['weight']),'HOLD' if record['held'] else 'Free')):
                item=QtWidgets.QTableWidgetItem(text);item.setToolTip(record['path']);item.setData(QtCore.Qt.UserRole,identity);self.table.setItem(row,column,item)
            if identity in selected:
                for column in range(3):self.table.item(row,column).setSelected(True)
        self.update_total()
    def update_total(self):
        if not hasattr(self,'total'):return
        selected=set(self.selected_ids())
        weight=sum(r['weight'] for r in self.info['rows'] if r['uuid'] in selected) if self.info else 0
        self.total.setText('Selected combined average: {:.6f} · {} influence(s)'.format(weight,len(selected)))
    def refresh_impl(self):
        api=self.api();editor=api.load_editor();selected=set(self.selected_ids())
        info=editor.inspect(api.editor_api(),self.mesh.text(),self.scope.currentData(),self.weighted.isChecked(),self.neighbors.isChecked())
        if self.extra:
            full=editor.inspect(api.editor_api(),self.mesh.text(),self.scope.currentData(),False)
            present={r['uuid'] for r in info['rows']};info['rows'].extend(r for r in full['rows'] if r['uuid'] in self.extra-present)
        self.info=info;self.render()
        for i in range(self.table.rowCount()):
            if self.table.item(i,0).data(QtCore.Qt.UserRole) in selected:
                for column in range(3):self.table.item(i,column).setSelected(True)
        self.update_total();return info
    @action
    def get_mesh(self):
        selected=cmds.ls(selection=True,objectsOnly=True,long=True) or []
        if not selected:raise ValueError('Select one skinned mesh or its components.')
        self.mesh.setText(self.api().mesh_path(selected[0]).fullPathName());self.refresh_impl()
        self.say('Loaded '+self.info['skin']+' · {} vertices in scope.'.format(self.info['vertex_count']))
    @action
    def refresh(self):
        info=self.refresh_impl();self.say('{} · {} vertices · {} listed influences.'.format(info['skin'],info['vertex_count'],self.table.rowCount()))
    @action
    def load_all(self):
        self.weighted.setChecked(False);self.hidden.clear();self.refresh_impl()
    @action
    def add_joints(self):
        api=self.api();ctx=api.context(self.mesh.text(),read_weights=False)
        selected=set(cmds.ls(selection=True,long=True,type='joint') or []);matches={r['uuid'] for r in ctx['influences'] if r['path'] in selected}
        if not matches:raise ValueError('Select joints already bound to the loaded mesh. This button only changes the list.')
        self.extra.update(matches);self.hidden-=matches
        # Joint selection does not provide a vertex scope; update using an explicit whole-mesh inspection.
        full=api.load_editor().inspect(api.editor_api(),self.mesh.text(),True,False)
        self.info=full
        if self.weighted.isChecked():self.info['rows']=[r for r in full['rows'] if r['weight']>1e-8 or r['uuid'] in self.extra]
        self.render();self.say('Added existing skin influences to the list; skin binding is unchanged. Reselect mesh components before editing.')
    def hide_rows(self):self.hidden.update(self.selected_ids());self.render()
    @action
    def hold(self,mode):
        if not self.info:raise ValueError('Get the mesh first.')
        selected=set(self.selected_ids());all_ids={r['uuid'] for r in self.info['influences']};scope=self.hold_scope.currentData()
        ids=selected if scope=='selected' else all_ids-selected if scope=='other' else set(self.visible_ids()) if scope=='visible' else all_ids
        if scope=='other' and not selected:raise ValueError('Select influence rows before changing Other influences.')
        api=self.api();count=api.load_editor().set_hold(api.editor_api(),self.mesh.text(),sorted(ids),mode)
        if self.auto_refresh.isChecked():
            try:self.refresh_impl()
            except Exception as exc:self.say('{} Hold states changed. Refresh: {}'.format(count,exc));return
        self.say('{}: {} influence(s). Undo restores Hold states.'.format(mode,count))
    @action
    def select_action(self,kind):
        if not self.info:raise ValueError('Get the mesh first.')
        api=self.api();ids=self.selected_ids();lookup={r['uuid']:r['path'] for r in self.info['influences']}
        if kind=='set':
            ctx=api.context(self.mesh.text(),read_weights=False)
            name=cmds.sets([r['path'] for r in ctx['influences']],name=ctx['skin'].rsplit('|',1)[-1]+'_Joints_Set')
            self.say('Created '+name);return
        if not ids:raise ValueError('Select influence rows first.')
        if kind=='joints':cmds.select([lookup[identity] for identity in ids],replace=True);return
        count=api.load_editor().affected_vertices(api.editor_api(),self.mesh.text(),ids,kind)
        self.say('{}: {} affected vertices.'.format(kind,count))
    @action
    def copy_weights(self):
        api=self.api();self.copied=api.load_editor().clipboard(api.editor_api(),self.mesh.text(),self.scope.currentData())
        self.say('Copied the average of {} vertices ({} nonzero influences).'.format(self.copied['vertex_count'],len(self.copied['influences'])))
    @action
    def edit(self,kind,value=0):
        if not self.info:raise ValueError('Get the mesh and refresh first.')
        api=self.api();data=dict(operation='edit',action=kind,mesh=self.mesh.text(),mesh_uuid=self.info['uuid'],topology=self.info['topology'],
            influences=self.selected_ids(),whole_mesh=self.scope.currentData(),value=value,threshold=self.threshold.value(),strength=self.strength.value(),
            clipboard=self.copied,axis=self.axis.currentData(),direction=self.direction.currentData(),left=self.left.text(),right=self.right.text(),
            geometry=self.geometry.currentData(),base=self.base.text())
        summary=json.loads(cmds.rtkCopySkin(data=json.dumps(data)))
        refresh_error=''
        if self.auto_refresh.isChecked():
            try:self.refresh_impl()
            except Exception as exc:refresh_error=' Refresh skipped: '+str(exc)
        self.say('{}: {} / {} vertices changed. {} held influences preserved. Undo restores weights.{}'.format(kind,summary['changed_vertices'],summary['eligible_vertices'],summary['held_influences'],refresh_error))


class TasksPanel(QtWidgets.QWidget):
    """Task records and explicit progress recovery; no scene polling or edits."""
    def __init__(self,copy_ui,parent=None):
        super(TasksPanel,self).__init__(parent);self.copy_ui=copy_ui;self.report=None;self.rows={};self.activity_key=None
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(4,8,4,4);layout.setSpacing(8)
        note=QtWidgets.QLabel('Tracked Skinning Tools tasks and the current Maya progress window. Other scripts may have an unknown owner. Updates require a responsive Maya UI; press Escape during calculations.')
        note.setWordWrap(True);layout.addWidget(note)
        self.table=QtWidgets.QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Operation','State','Stage','Elapsed'])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows);self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers);self.table.setAlternatingRowColors(True);self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2,QtWidgets.QHeaderView.Stretch)
        self.table.setColumnWidth(1,135);self.table.setColumnWidth(3,70);layout.addWidget(self.table,1)
        self.details=QtWidgets.QPlainTextEdit();self.details.setReadOnly(True);self.details.setFixedHeight(125);layout.addWidget(self.details)
        row=QtWidgets.QHBoxLayout()
        self.refresh_button=QtWidgets.QPushButton('Refresh');self.refresh_button.clicked.connect(self.refresh);row.addWidget(self.refresh_button)
        self.cancel_button=QtWidgets.QPushButton('Cancel');self.cancel_button.clicked.connect(lambda *_:self.stop(False));row.addWidget(self.cancel_button)
        self.force_button=QtWidgets.QPushButton('Force stop / reset');self.force_button.clicked.connect(lambda *_:self.stop(True));row.addWidget(self.force_button)
        self.force_button.setToolTip('Requests cancellation for a tracked calculation. For an unknown owner, closes only its progress UI. Never interrupts native Maya calls or an atomic weight write.')
        self.clear_button=QtWidgets.QPushButton('Clear history');self.clear_button.clicked.connect(self.clear_history);row.addWidget(self.clear_button);layout.addLayout(row)
        self.status=QtWidgets.QLabel('No task selected.');self.status.setWordWrap(True);layout.addWidget(self.status)
        limits=QtWidgets.QLabel('Force Stop cannot terminate arbitrary scripts or a blocked native call. During writing / verification, wait for the atomic operation and any rollback to finish. Stale progress can be reset only when no tracked task is active.')
        limits.setWordWrap(True);layout.addWidget(limits)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.timer=QtCore.QTimer(self);self.timer.setInterval(500);self.timer.timeout.connect(self.refresh)
        self.cancel_button.setEnabled(False);self.force_button.setEnabled(False)
    def api(self):return getattr(self.copy_ui,'task_api',self.copy_ui.backend)()
    def showEvent(self,event):
        super(TasksPanel,self).showEvent(event);self.refresh();self.timer.start()
    def hideEvent(self,event):
        self.timer.stop();super(TasksPanel,self).hideEvent(event)
    def selected_id(self):
        row=self.table.currentRow();item=self.table.item(row,0) if row>=0 else None
        return item.data(QtCore.Qt.UserRole) if item else None
    def refresh(self,*_):
        try:
            selected=self.selected_id();self.report=self.api().task_report();active=self.report['active'];self.rows={}
            items=([active] if active else [])+self.report['history']
            native=self.report['maya_progress']
            activity=(active['id'] if active else None,(native['title'],native['status']) if native and not active else None)
            if activity!=self.activity_key:
                self.activity_key=activity
                self.status.setText('Active: '+active['name'] if active else 'Untracked Maya progress is available for inspection.' if native else 'No tracked task is running.')
            if native and not (active and active['native_progress']):
                items.insert(0,dict(id='maya-progress',name=native['title'] or 'Maya progress',state='Owner unknown',stage=native['status'],elapsed=None,message='An external or leftover progress window. Reset closes its UI; it does not terminate its script.'))
            self.table.blockSignals(True)
            try:
                self.table.setRowCount(len(items))
                for index,item in enumerate(items):
                    self.rows[item['id']]=item
                    for column,text in enumerate((item['name'],item['state'],item['stage'],'{:.1f}s'.format(item['elapsed']) if item['elapsed'] is not None else 'Unknown')):
                        cell=QtWidgets.QTableWidgetItem(text);cell.setData(QtCore.Qt.UserRole,item['id']);cell.setToolTip(text);self.table.setItem(index,column,cell)
                choice=next((i for i,item in enumerate(items) if item['id']==selected),0)
                if items:self.table.selectRow(choice)
            finally:self.table.blockSignals(False)
            self.selection_changed()
        except Exception as exc:
            self.cancel_button.setEnabled(False);self.force_button.setEnabled(False);self.status.setText(str(exc))
    def selection_changed(self):
        identity=self.selected_id();item=self.rows.get(identity);active=self.report['active'] if self.report else None
        tracked=bool(active and identity==active['id']);can_stop=tracked and not active['atomic']
        self.cancel_button.setEnabled(bool(can_stop));self.force_button.setEnabled(bool(can_stop or (identity=='maya-progress' and not active)))
        if not item:self.details.setPlainText('No tracked task or identifiable Maya progress window.');return
        lines=['Operation: '+item['name'],'State: '+item['state'],'Stage: '+item['stage']]
        if tracked:lines.append('Last checkpoint: {:.1f}s ago · progress stage {}%'.format(item.get('since_checkpoint',0.),item['progress']))
        if item.get('message'):lines.append(item['message'])
        self.details.setPlainText('\n'.join(lines))
    def stop(self,force):
        try:
            identity=self.selected_id()
            if identity is None:raise ValueError('Select an active task or an unknown Maya progress row.')
            text=self.api().stop_task(identity,force=force,expected_progress=self.report['maya_progress'] if identity=='maya-progress' else None)
            self.refresh();self.status.setText(text)
        except Exception as exc:self.status.setText(str(exc))
    def clear_history(self,*_):
        try:self.api().task_service().clear_finished();self.refresh();self.status.setText('Finished task history cleared.')
        except Exception as exc:self.status.setText(str(exc))


class SkinningToolsPanel(QtWidgets.QWidget):
    def __init__(self,parent=None,copy_ui=None):
        super(SkinningToolsPanel,self).__init__(parent)
        self.copy_ui=copy_ui or sibling('copy_skinning_ui')
        self.setObjectName('rtkSkinningTools')
        self.setStyleSheet("""
            #rtkSkinningTools QPushButton { min-height: 24px; padding: 2px 8px; }
            #rtkSkinningTools QPushButton[primary="true"] { background: #397a9e; color: white; border: 1px solid #5393b4; border-radius: 3px; }
            #rtkSkinningTools QGroupBox { font-weight: bold; margin-top: 10px; padding-top: 10px; }
            #rtkSkinningTools QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
            #rtkSkinningTools QToolButton { text-align: left; padding: 5px 4px; }
            #rtkSkinningTools QLineEdit, #rtkSkinningTools QComboBox, #rtkSkinningTools QAbstractSpinBox { min-height: 24px; }
            #rtkSkinningTools QTabBar::tab { min-width: 120px; padding: 8px 16px; }
        """)
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(8)
        self.tabs=QtWidgets.QTabWidget();self.tabs.setDocumentMode(True);layout.addWidget(self.tabs,1)
        self.editor=WeightEditorPanel(self.copy_ui,self);self.tabs.addTab(self.editor,'Weight Editor')
        self.copy_panel=self.copy_ui.CopySkinningPanel(self);self.tabs.addTab(self.copy_panel,'Copy Skinning')
        self.tasks=TasksPanel(self.copy_ui,self);self.tabs.addTab(self.tasks,'Tasks')
        for button in self.findChildren(QtWidgets.QPushButton):button.setAutoDefault(False)


def show():
    global _dialog
    if _dialog is not None and shiboken.isValid(_dialog):
        _dialog.show();_dialog.raise_();_dialog.activateWindow();return _dialog
    parent=shiboken.wrapInstance(int(omui.MQtUtil.mainWindow()),QtWidgets.QWidget)
    _dialog=QtWidgets.QDialog(parent);_dialog.setWindowTitle('Skinning Tools 0.4.3');_dialog.resize(780,860)
    _dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose,False)
    layout=QtWidgets.QVBoxLayout(_dialog);layout.addWidget(SkinningToolsPanel())
    _dialog.show();return _dialog
