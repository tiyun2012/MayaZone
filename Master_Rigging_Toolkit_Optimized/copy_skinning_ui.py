"""Copy Skinning panel: embedded in RTK, or run show() independently in Maya."""
import importlib.util
import json
import os
from functools import wraps
from types import SimpleNamespace
import maya.cmds as cmds
try:
    from PySide6 import QtWidgets,QtCore
    import shiboken6 as shiboken
except ImportError:
    from PySide2 import QtWidgets,QtCore
    import shiboken2 as shiboken
import maya.OpenMayaUI as omui

_backend=None
_dialog=None


def fold(layout,title,widget,opened=False):
    button=QtWidgets.QToolButton();button.setText(title);button.setCheckable(True);button.setChecked(opened)
    button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
    button.setSizePolicy(QtWidgets.QSizePolicy.Expanding,QtWidgets.QSizePolicy.Fixed)
    def toggle(value):
        button.setArrowType(QtCore.Qt.DownArrow if value else QtCore.Qt.RightArrow);widget.setVisible(value)
    button.toggled.connect(toggle);layout.addWidget(button);layout.addWidget(widget);toggle(opened)
    return button


def busy_action(function):
    @wraps(function)
    def guarded(self,*_):
        if self._busy:return
        self._busy=True;enabled=self.isEnabled();self.setEnabled(False)
        try:return function(self)
        finally:
            self._busy=False
            if shiboken.isValid(self):self.setEnabled(enabled)
    return guarded


def backend():
    global _backend
    path=os.path.join(os.path.dirname(__file__),'copy_skinning_plugin.py')
    loaded=[cmds.pluginInfo(p,query=True,path=True) for p in (cmds.pluginInfo(query=True,listPlugins=True) or [])]
    if not any(os.path.normcase(os.path.realpath(p))==os.path.normcase(os.path.realpath(path)) for p in loaded):
        cmds.loadPlugin(path,quiet=True)
    if cmds.pluginInfo(path,query=True,version=True)!='0.4.3':
        raise RuntimeError('Copy Skinning plug-in 0.4.3 is required. Save your scene and restart Maya after replacing the complete folder; the old registered command is still loaded.')
    return task_api()


def task_api():
    """Read/recover progress even when the registered plug-in is outdated."""
    global _backend
    if _backend is None:
        path=os.path.join(os.path.dirname(__file__),'copy_skinning_plugin.py')
        spec=importlib.util.spec_from_file_location('_rtk_copy_skin_ui_backend_01',path)
        _backend=importlib.util.module_from_spec(spec);spec.loader.exec_module(_backend)
    return _backend


class CopySkinningPanel(QtWidgets.QWidget):
    def __init__(self,parent=None):
        super(CopySkinningPanel,self).__init__(parent)
        self.regions={'source':None,'target':None};self.preview_data=None;self.display={};self.mesh_info={}
        self.manual_mapping={};self.reviewed_mapping=None;self.mapping_cache=None;self.map_dirty=True
        self._busy=False
        outer=QtWidgets.QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(8)
        scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        body=QtWidgets.QWidget();scroll.setWidget(body);outer.addWidget(scroll,1)
        layout=QtWidgets.QVBoxLayout(body);layout.setContentsMargins(4,4,4,4);layout.setSpacing(10)
        note=QtWidgets.QLabel('Load the visible source and target meshes. Pre-skin geometry is detected automatically.')
        note.setWordWrap(True);layout.addWidget(note)
        meshes=QtWidgets.QGroupBox('Meshes');form=QtWidgets.QFormLayout(meshes);self.fields={}
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
        for role in ('source','target'):
            field=QtWidgets.QLineEdit();field.setMinimumWidth(0);field.setPlaceholderText('Select '+role+' mesh in Maya, then Load')
            button=QtWidgets.QPushButton('Load selected');button.clicked.connect(lambda *_,r=role:self.get(r))
            row=QtWidgets.QHBoxLayout();row.addWidget(field,1);row.addWidget(button);form.addRow(role.title()+':',row)
            field.textChanged.connect(lambda *_,r=role:self.mesh_changed(r));self.fields[role]=field
            label=QtWidgets.QLabel('Not loaded');label.setWordWrap(True)
            self.mesh_info[role]=label;form.addRow('',label)
        layout.addWidget(meshes)
        setup=QtWidgets.QWidget();setup_layout=QtWidgets.QVBoxLayout(setup);setup_layout.setContentsMargins(0,0,0,0)
        row=QtWidgets.QHBoxLayout()
        button=QtWidgets.QPushButton('Refresh meshes');button.clicked.connect(self.refresh_meshes);row.addWidget(button)
        button=QtWidgets.QPushButton('Clear cache');button.clicked.connect(self.clear_geometry_cache);row.addWidget(button);setup_layout.addLayout(row)
        bind=QtWidgets.QPushButton('Prepare target / refresh mapping');bind.setToolTip('Bind an unskinned target, or reuse its existing skin without changing weights.');bind.clicked.connect(self.bind);setup_layout.addWidget(bind)
        fold(layout,'Mesh setup and cache',setup)
        transfer=QtWidgets.QGroupBox('Transfer settings');options=QtWidgets.QFormLayout(transfer)
        options.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow);options.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
        self.method=QtWidgets.QComboBox()
        for label,value in (('Vertex ID','id'),('Closest surface','surface'),('Faces / painted masks','region')):self.method.addItem(label,value)
        self.method.setCurrentIndex(1)
        options.addRow('Copy method:',self.method)
        self.geometry=QtWidgets.QComboBox();self.geometry.addItem('Pre-skin · automatic','base');self.geometry.addItem('Current · deformed','current')
        options.addRow('Sample geometry:',self.geometry)
        self.opacity=QtWidgets.QDoubleSpinBox();self.opacity.setRange(0,1);self.opacity.setSingleStep(.1);self.opacity.setValue(1);options.addRow('Copy strength:',self.opacity)
        layout.addWidget(transfer)
        advanced=QtWidgets.QWidget();advanced_layout=QtWidgets.QVBoxLayout(advanced);advanced_layout.setContentsMargins(4,4,4,4)
        options=QtWidgets.QFormLayout();options.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows);advanced_layout.addLayout(options)
        self.topology=QtWidgets.QCheckBox('Verify face connectivity for vertex IDs');self.topology.setChecked(True);options.addRow(self.topology)
        self.distance=QtWidgets.QDoubleSpinBox();self.distance.setDecimals(4);self.distance.setRange(0,1e8);self.distance.setSpecialValueText('Unlimited');options.addRow('Max distance · scene units:',self.distance)
        self.dq=QtWidgets.QCheckBox('Copy DQ blend weights');options.addRow(self.dq)
        self.max_seconds=QtWidgets.QSpinBox();self.max_seconds.setRange(0,3600);self.max_seconds.setValue(120);self.max_seconds.setSpecialValueText('Unlimited')
        self.max_seconds.setToolTip('Stops calculation between Maya calls. A blocked native Maya evaluation must return before the limit can be checked.')
        options.addRow('Calculation time limit · seconds:',self.max_seconds)
        self.override_check=QtWidgets.QCheckBox('Use explicit pre-skin mesh overrides · advanced');options.addRow(self.override_check)
        self.base_group=QtWidgets.QGroupBox('Explicit base mesh overrides · matching vertex IDs and connectivity')
        base_form=QtWidgets.QFormLayout(self.base_group)
        for role in ('source','target'):
            field=QtWidgets.QLineEdit();field.setPlaceholderText('Blank = automatic evaluated skin input')
            button=QtWidgets.QPushButton('Get selected');button.clicked.connect(lambda *_,r=role+'_base':self.get(r))
            row=QtWidgets.QHBoxLayout();row.addWidget(field,1);row.addWidget(button);base_form.addRow(role.title()+' base:',row);self.fields[role+'_base']=field
        advanced_layout.addWidget(self.base_group)
        self.advanced_toggle=fold(layout,'Advanced transfer options',advanced)
        self.region_group=QtWidgets.QGroupBox('Method 3 · source surface restriction and target blend area')
        region_layout=QtWidgets.QVBoxLayout(self.region_group);self.mask_checks={};self.region_labels={}
        mask_note=QtWidgets.QLabel('Capture source faces / target faces or vertices, or paint both masks. If faces and a mask are supplied, both apply. Black = excluded; white = full contribution.')
        mask_note.setWordWrap(True);region_layout.addWidget(mask_note)
        for role in ('source','target'):
            box=QtWidgets.QGroupBox(role.title()+' region');body=QtWidgets.QVBoxLayout(box)
            row=QtWidgets.QHBoxLayout();label=QtWidgets.QLabel('No captured components');self.region_labels[role]=label
            button=QtWidgets.QPushButton('Get selected faces' if role=='source' else 'Get selected faces / vertices')
            button.clicked.connect(lambda *_,r=role:self.capture(r));row.addWidget(button);row.addWidget(label,1)
            clear=QtWidgets.QPushButton('Clear');clear.clicked.connect(lambda *_,r=role:self.invalidate_region(r));row.addWidget(clear);body.addLayout(row)
            check=QtWidgets.QCheckBox('Use painted '+role+' mask');self.mask_checks[role]=check;body.addWidget(check)
            row=QtWidgets.QHBoxLayout()
            for title,action in (('Reset black','black'),('Fill white','white'),('Set selected','selected'),('Paint','paint')):
                button=QtWidgets.QPushButton(title);button.clicked.connect(lambda *_,r=role,a=action:self.mask(r,a));row.addWidget(button)
            body.addLayout(row);region_layout.addWidget(box)
        row=QtWidgets.QHBoxLayout();row.addWidget(QtWidgets.QLabel('Mask brush / selected value:'))
        self.mask_value=QtWidgets.QDoubleSpinBox();self.mask_value.setRange(0,1);self.mask_value.setSingleStep(.1);self.mask_value.setValue(1);row.addWidget(self.mask_value)
        hide=QtWidgets.QPushButton('Restore mask display');hide.clicked.connect(self.restore_display);row.addWidget(hide);region_layout.addLayout(row)
        self.threshold=QtWidgets.QDoubleSpinBox();self.threshold.setDecimals(4);self.threshold.setRange(.0001,1);self.threshold.setValue(.001)
        row=QtWidgets.QHBoxLayout();row.addWidget(QtWidgets.QLabel('Source mask search threshold:'));row.addWidget(self.threshold);region_layout.addLayout(row)
        layout.addWidget(self.region_group)
        mapping=QtWidgets.QGroupBox('Influence mapping · automatic + editable UUID pairs');mf=QtWidgets.QFormLayout(mapping)
        self.match_name=QtWidgets.QCheckBox('Match by name');self.match_name.setChecked(True)
        self.match_distance=QtWidgets.QCheckBox('Match by distance');self.match_distance.setChecked(True)
        row=QtWidgets.QHBoxLayout();row.addWidget(self.match_name);row.addWidget(self.match_distance);mf.addRow(row)
        self.joint_tolerance=QtWidgets.QDoubleSpinBox();self.joint_tolerance.setDecimals(5);self.joint_tolerance.setRange(0,1e6);self.joint_tolerance.setValue(.01)
        mf.addRow('Joint tolerance · scene units:',self.joint_tolerance)
        self.joint_space=QtWidgets.QComboBox();self.joint_space.addItem('Bind / rest positions','bind');self.joint_space.addItem('Current joint positions','current');mf.addRow('Measure joints:',self.joint_space)
        self.name_edits=QtWidgets.QSpinBox();self.name_edits.setRange(0,10);self.name_edits.setValue(3);mf.addRow('Similar name · max changed characters:',self.name_edits)
        self.ignore_namespace=QtWidgets.QCheckBox('Ignore namespaces for name matching');self.ignore_namespace.setChecked(True);mf.addRow(self.ignore_namespace)
        self.search=QtWidgets.QLineEdit();self.replace=QtWidgets.QLineEdit();mf.addRow('Search in source name:',self.search);mf.addRow('Replace with:',self.replace)
        help_=QtWidgets.QLabel('Manual → same joint → exact name → proximity / similar name. Similar names need ≥60% similarity. Equal candidates remain unresolved. Review ambiguous rows and assign a target below.')
        help_.setWordWrap(True);mf.addRow(help_)
        row=QtWidgets.QHBoxLayout()
        button=QtWidgets.QPushButton('Build / refresh mapping');button.clicked.connect(lambda *_:self.build_mapping());row.addWidget(button)
        button=QtWidgets.QPushButton('Clear all manual overrides');button.clicked.connect(self.clear_manual);row.addWidget(button);mf.addRow(row)
        self.mapping_table=QtWidgets.QTableWidget(0,5);self.mapping_table.setHorizontalHeaderLabels(['Source joint','Target joint','Match / status','Distance (cm)','Edits'])
        self.mapping_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows);self.mapping_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.mapping_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers);self.mapping_table.setMinimumHeight(180)
        self.mapping_table.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.Stretch)
        self.mapping_table.horizontalHeader().setSectionResizeMode(1,QtWidgets.QHeaderView.Stretch)
        self.mapping_table.verticalHeader().hide();self.mapping_table.setAlternatingRowColors(True)
        self.mapping_table.itemSelectionChanged.connect(self.mapping_row_selected);mf.addRow(self.mapping_table)
        self.target_choice=QtWidgets.QComboBox();mf.addRow('Selected row target:',self.target_choice)
        row=QtWidgets.QHBoxLayout()
        button=QtWidgets.QPushButton('Set row mapping');button.clicked.connect(self.set_manual);row.addWidget(button)
        button=QtWidgets.QPushButton('Use selected target joint');button.clicked.connect(self.use_selected_joint);row.addWidget(button);mf.addRow(row)
        self.mapping_status=QtWidgets.QLabel('Get both meshes, then build mapping.');self.mapping_status.setWordWrap(True);mf.addRow(self.mapping_status)
        self.mapping_toggle=QtWidgets.QToolButton();self.mapping_toggle.setText('Influence mapping · automatic / manual');self.mapping_toggle.setCheckable(True)
        self.mapping_toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.mapping_toggle.setSizePolicy(QtWidgets.QSizePolicy.Expanding,QtWidgets.QSizePolicy.Fixed)
        def toggle_mapping(value):
            self.mapping_toggle.setArrowType(QtCore.Qt.DownArrow if value else QtCore.Qt.RightArrow);mapping.setVisible(value)
        self.mapping_toggle.toggled.connect(toggle_mapping);layout.addWidget(self.mapping_toggle);layout.addWidget(mapping);toggle_mapping(False)
        for control in (self.match_name,self.match_distance,self.ignore_namespace):control.toggled.connect(self.mapping_options_changed)
        for control in (self.joint_tolerance,self.name_edits):control.valueChanged.connect(self.mapping_options_changed)
        for control in (self.search,self.replace):control.textChanged.connect(self.mapping_options_changed)
        self.joint_space.currentIndexChanged.connect(self.mapping_options_changed)
        layout.addStretch(1)
        row=QtWidgets.QHBoxLayout();self.action_buttons={}
        for label,slot in (('Preview',self.preview),('Select preview vertices',self.select_preview),('Copy skinning',self.copy)):
            button=QtWidgets.QPushButton(label);button.clicked.connect(slot);row.addWidget(button);self.action_buttons[label]=button
        self.action_buttons['Copy skinning'].setProperty('primary',True)
        outer.addLayout(row)
        self.status=QtWidgets.QLabel();self.status.setWordWrap(True);self.status.setMinimumWidth(0);outer.addWidget(self.status)
        self.report=QtWidgets.QPlainTextEdit();self.report.setReadOnly(True);self.report.setFixedHeight(130)
        self.details_toggle=fold(outer,'Transfer details',self.report)
        self.method.currentIndexChanged.connect(self.update_controls);self.geometry.currentIndexChanged.connect(self.geometry_changed)
        self.override_check.toggled.connect(self.update_controls);self.update_controls()
        self.say('Ready. Load source and target deformed meshes. Pre-skin geometry is detected automatically; mapping options open if a joint needs manual assignment.')

    def say(self,text,error=False):
        self.report.setPlainText(str(text))
        lines=str(text).splitlines();brief=lines[0] if lines else ''
        counts=next((line for line in lines if line.startswith('Eligible:')),None)
        if counts:brief+='\n'+counts
        self.status.setText(brief[:220]+('…' if len(brief)>220 else ''));self.status.setToolTip(str(text))
        if error:self.details_toggle.setChecked(True)
        if error:cmds.warning('Copy Skinning: '+str(text))

    def update_controls(self,*_):
        surface=self.method.currentData()!='id';self.geometry.setEnabled(surface);self.distance.setEnabled(surface)
        self.topology.setEnabled(not surface);self.base_group.setEnabled(surface and self.geometry.currentData()=='base')
        self.override_check.setEnabled(surface and self.geometry.currentData()=='base')
        self.base_group.setVisible(surface and self.geometry.currentData()=='base' and self.override_check.isChecked())
        self.region_group.setEnabled(self.method.currentData()=='region')
        self.region_group.setVisible(self.method.currentData()=='region')

    def geometry_changed(self,*_):
        self.preview_data=None;self.update_controls();self.refresh_meshes()

    def invalidate_region(self,role):
        self.regions[role]=None;self.preview_data=None
        if role in self.region_labels:self.region_labels[role].setText('No captured components')

    def mesh_changed(self,role):
        self.invalidate_region(role);self.manual_mapping={};self.mapping_cache=None;self.reviewed_mapping=None;self.map_dirty=True
        if hasattr(self,'mapping_table'):self.mapping_table.setRowCount(0)
        if role in self.mesh_info:self.mesh_info[role].setText('Mesh changed · load or preview to refresh geometry.')

    def mapping_options_changed(self,*_):
        self.map_dirty=True;self.preview_data=None
        self.mapping_status.setText('Settings changed. Build / refresh mapping to update the table.')

    def build_mapping(self,quiet=False):
        if self._busy and not quiet:return None
        try:
            report=backend().preview_mapping(self.data());self.mapping_cache=report;self.map_dirty=False
            self.reviewed_mapping={'source_ids':report['source_ids'],'target_ids':report['target_ids'],
                                   'pairs':{r['source_uuid']:r['target_uuid'] for r in report['rows']}}
            selected=self.mapping_table.currentRow();self.mapping_table.setRowCount(len(report['rows']))
            for index,row in enumerate(report['rows']):
                values=[row['source'].rsplit('|',1)[-1],(row['target'] or '—').rsplit('|',1)[-1],row['method'],
                        '{:.6g}'.format(row['distance']) if row['distance'] is not None else '—',str(row['edits']) if row['edits'] is not None else '—']
                for column,value in enumerate(values):
                    item=QtWidgets.QTableWidgetItem(value);item.setToolTip(row['source']+' → '+(row['target'] or 'unmapped'));self.mapping_table.setItem(index,column,item)
            self.target_choice.clear();self.target_choice.addItem('Automatic','__auto__');self.target_choice.addItem('Unmapped · block copying this row',None)
            for target in report['target_influences']:self.target_choice.addItem(target['path'],target['uuid'])
            if report['rows']:self.mapping_table.selectRow(min(max(0,selected),len(report['rows'])-1))
            self.mapping_row_selected()
            resolved=sum(r['target_uuid'] is not None for r in report['rows'])
            text='{} / {} rows mapped. {}'.format(resolved,len(report['rows']),'Ready to preview / copy.' if report['complete'] else '; '.join(report['errors']))
            self.mapping_status.setText(text)
            if not report['complete']:self.mapping_toggle.setChecked(True)
            if not quiet:self.say(text)
            return report
        except Exception as exc:
            self.mapping_cache=None;self.reviewed_mapping=None;self.map_dirty=True
            self.mapping_status.setText(str(exc));self.say(exc,not quiet);return None

    def mapping_row_selected(self):
        index=self.mapping_table.currentRow()
        if not self.mapping_cache or not 0<=index<len(self.mapping_cache['rows']):return
        identity=self.mapping_cache['rows'][index]['source_uuid'];value=self.manual_mapping.get(identity,'__auto__')
        choice=self.target_choice.findData(value)
        if choice>=0:self.target_choice.setCurrentIndex(choice)

    def set_manual(self,*_):
        try:
            index=self.mapping_table.currentRow()
            if not self.mapping_cache or not 0<=index<len(self.mapping_cache['rows']):raise ValueError('Select a source row in the mapping table.')
            identity=self.mapping_cache['rows'][index]['source_uuid'];value=self.target_choice.currentData()
            if value=='__auto__':self.manual_mapping.pop(identity,None)
            else:self.manual_mapping[identity]=value
            self.build_mapping()
        except Exception as exc:self.say(exc,True)

    def use_selected_joint(self,*_):
        try:
            names=cmds.ls(selection=True,long=True,objectsOnly=True) or []
            if len(names)!=1:raise ValueError('Select one of the target skin influences.')
            api=backend();identity=api.om.MFnDependencyNode(api.object_(names[0])).uuid().asString()
            choice=self.target_choice.findData(identity)
            if choice<2:raise ValueError('Selected joint is not an influence of the target skinCluster.')
            self.target_choice.setCurrentIndex(choice);self.set_manual()
        except Exception as exc:self.say(exc,True)

    def clear_manual(self,*_):
        self.manual_mapping={};self.build_mapping()

    def get(self,role):
        if self._busy:return
        self._busy=True;enabled=self.isEnabled();self.setEnabled(False)
        try:
            selected=cmds.ls(selection=True,long=True,objectsOnly=True) or []
            selected=list(dict.fromkeys(selected))
            if len(selected)!=1:raise ValueError('Select one mesh.')
            path=backend().mesh_path(selected[0]);self.fields[role].setText(path.fullPathName())
            if role in ('source','target'):self.load_role(role)
            if role in ('source','target') and all(self.fields[r].text() for r in ('source','target')):self.build_mapping(quiet=True)
        except Exception as exc:self.say(exc,True)
        finally:
            self._busy=False
            if shiboken.isValid(self):self.setEnabled(enabled)

    def load_role(self,role):
        data=self.data();self.mesh_info[role].setText('Checking for skin weights…')
        try:
            info=backend().load_mesh(data[role],data['geometry'],data[role+'_base'],role=='source',data['method'],max_seconds=data['max_seconds'])
        except Exception as exc:
            self.preview_data=None;self.mesh_info[role].setText('Load failed · see details');self.mesh_info[role].setToolTip(str(exc));raise
        self.mesh_info[role].setText('{} vertices · {} influences · ready'.format(info['vertices'],info['influences']))
        self.mesh_info[role].setToolTip('Pre-skin input: '+info['input_geometry'])
        self.say('{} loaded and validated. Reusable geometry is cached when it fits; weights are read at Preview / Copy.'.format(role.title()))
        return info

    @busy_action
    def refresh_meshes(self):
        try:
            for role in ('source','target'):
                if self.fields[role].text().strip():self.load_role(role)
            if all(self.fields[r].text().strip() for r in ('source','target')) and self.map_dirty:self.build_mapping(quiet=True)
        except Exception as exc:self.say(exc,True)

    @busy_action
    def clear_geometry_cache(self):
        try:backend().clear_cache();self.preview_data=None;self.say('Geometry cache cleared. Load / Preview / Copy rebuilds it automatically.')
        except Exception as exc:self.say(exc,True)

    def capture(self,role):
        try:
            value=backend().capture_region(self.fields[role].text(),role=='source');self.regions[role]=value;self.preview_data=None
            self.region_labels[role].setText('{} faces · {} vertices'.format(len(value['faces']),len(value['vertices'])))
        except Exception as exc:self.say(exc,True)

    def mask(self,role,action):
        try:
            api=backend();ctx=api.context(self.fields[role].text());key=ctx['uuid']
            if key not in self.display:
                self.display[key]={'shape':ctx['shape'],'colors':cmds.getAttr(ctx['shape']+'.displayColors'),
                                   'set':cmds.polyColorSet(ctx['shape'],query=True,currentColorSet=True) or []}
            name=api.mask_action(ctx['shape'],role,action,self.mask_value.value());self.mask_checks[role].setChecked(True);self.preview_data=None
            self.say('{} mask: {}. Paint grayscale; change the brush value here and click Paint again, or use Maya Tool Settings. Preview reads the latest mask.'.format(role.title(),name))
        except Exception as exc:self.say(exc,True)

    def restore_display(self):
        try:
            cmds.setToolTo('selectSuperContext')
            for identity,state in list(self.display.items()):
                matches=cmds.ls(identity,long=True) or []
                if not matches:continue
                shape=matches[0]
                if state['set'] and state['set'][0] in (cmds.polyColorSet(shape,query=True,allColorSets=True) or []):cmds.polyColorSet(shape,currentColorSet=True,colorSet=state['set'][0])
                cmds.setAttr(shape+'.displayColors',state['colors'])
            self.display.clear();self.say('Restored mesh color display. Transfer masks remain saved on the meshes.')
        except Exception as exc:self.say(exc,True)

    def data(self):
        return dict(source=self.fields['source'].text(),target=self.fields['target'].text(),method=self.method.currentData(),geometry=self.geometry.currentData(),
                    source_base=self.fields['source_base'].text() if self.override_check.isChecked() else '',target_base=self.fields['target_base'].text() if self.override_check.isChecked() else '',source_region=self.regions['source'],target_region=self.regions['target'],
                    source_mask=self.mask_checks['source'].isChecked(),target_mask=self.mask_checks['target'].isChecked(),mask_threshold=self.threshold.value(),
                    verify_topology=self.topology.isChecked(),opacity=self.opacity.value(),max_distance=self.distance.value(),copy_dq=self.dq.isChecked(),max_seconds=self.max_seconds.value(),
                    ignore_namespace=self.ignore_namespace.isChecked(),search=self.search.text(),replace=self.replace.text(),
                    match_name=self.match_name.isChecked(),match_distance=self.match_distance.isChecked(),joint_tolerance=self.joint_tolerance.value(),
                    joint_space=self.joint_space.currentData(),name_edits=self.name_edits.value(),manual_mapping=dict(self.manual_mapping),
                    reviewed_mapping=self.reviewed_mapping if not self.map_dirty else None)

    def show_summary(self,summary,prefix):
        lines=[prefix,'Method: {} | Geometry: {}'.format(summary['method'],summary['geometry']),
               'Eligible: {} | Changed: {} | Masked: {} | Distance skips: {}'.format(summary['eligible_vertices'],summary['changed_vertices'],summary['masked_vertices'],summary['distance_skips']),
               'Source triangles: {} | Degenerate triangles skipped: {}'.format(summary['source_triangles'],summary['degenerate_triangles_skipped']),
               'Largest accepted distance: {:.6g} cm'.format(summary['max_hit_distance_cm']),'Influences:']
        lines.extend('  {} → {}'.format(a,b) for a,b in summary['influence_mapping'])
        if summary['changed_ids_truncated']:lines.append('Vertex selection preview is limited to 5,000 IDs; Copy processes the complete eligible region.')
        if 'cache' in summary:
            cache=summary['cache'];lines.append('Session cache: {} entries · {:.1f} MiB estimated · {} nearest queries reused. Source index reused: {}.'.format(cache['items'],cache['estimated_bytes']/1048576.,cache['reused_queries'],summary['surface_cache_reused']))
        if summary.get('preview_cache_reused'):lines.append('Reused Preview after validating live geometry, weights, masks and mapping.')
        if summary.get('write_preflight')=='deferred until Copy':lines.append('Copy checks target locks and drivers before writing.')
        self.say('\n'.join(lines))

    @busy_action
    def preview(self):
        try:
            if self.map_dirty and self.build_mapping(quiet=True) is None:return
            data=self.data();summary=backend().preview_transfer(data,progress=True);self.preview_data=(data,summary)
            self.show_summary(summary,'PREVIEW · weights unchanged')
        except Exception as exc:self.preview_data=None;self.say(exc,True)

    @busy_action
    def select_preview(self):
        try:
            if self.map_dirty and self.build_mapping(quiet=True) is None:return
            # Validate scene inputs and reuse a read-only result when unchanged.
            data=self.data();summary=backend().select_preview_vertices(data,progress=True);ids=summary['changed_ids']
            self.show_summary(summary,'Selected changed target vertices' if ids else 'No changed vertices')
        except Exception as exc:self.say(exc,True)

    @busy_action
    def copy(self):
        try:
            if self.map_dirty and self.build_mapping(quiet=True) is None:return
            backend();summary=json.loads(cmds.rtkCopySkin(data=json.dumps(self.data())))
            self.preview_data=None;self.show_summary(summary,'COPIED · Maya Undo restores previous weights')
        except Exception as exc:self.say(exc,True)

    @busy_action
    def bind(self):
        try:
            skin=backend().bind_target(self.fields['source'].text(),self.fields['target'].text());self.load_role('target');self.build_mapping(quiet=True)
            self.say('Using target skin: '+skin+'. Existing weights are kept until Copy. '+self.mapping_status.text())
        except Exception as exc:self.say(exc,True)


def show():
    global _dialog
    parent=shiboken.wrapInstance(int(omui.MQtUtil.mainWindow()),QtWidgets.QWidget)
    if _dialog is not None and shiboken.isValid(_dialog):
        _dialog.show();_dialog.raise_();_dialog.activateWindow();return _dialog
    filename=os.path.join(os.path.dirname(__file__),'skinning_ui.py')
    spec=importlib.util.spec_from_file_location('_rtk_skinning_combined_panel',filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    panel=module.SkinningToolsPanel(copy_ui=SimpleNamespace(backend=backend,task_api=task_api,CopySkinningPanel=CopySkinningPanel))
    _dialog=QtWidgets.QDialog(parent);_dialog.setWindowTitle('Skinning Tools 0.4.3');_dialog.resize(780,860)
    _dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose,False)
    layout=QtWidgets.QVBoxLayout(_dialog);layout.addWidget(panel)
    _dialog.show();return _dialog
