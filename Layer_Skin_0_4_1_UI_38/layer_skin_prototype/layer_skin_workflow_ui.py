"""Selection-driven layer authoring UI; scene changes use the plugin command."""
import json
import functools
import weakref
try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

BASE='__base__'


def color_action(function):
    @functools.wraps(function)
    def call(self,*args,**kwargs):
        transition=getattr(self.session,'color_transition',None)
        if transition is None:return function(self,*args,**kwargs)
        with transition():return function(self,*args,**kwargs)
    return call


class InfluenceSummaries:
    """Keep weight summaries only for unchanged buffers in the loaded stack.

    Core edits replace sample dictionaries and base arrays rather than mutate
    them. Retain one summary per live layer, dropping obsolete source objects
    on every lookup so deleted layers and old paint snapshots cannot pile up.
    """
    def __init__(self):
        self.scope=None;self.entries={}

    def get(self,core,ctx,state,identity):
        scope=(core,ctx['uuid'],state['topology'],state['vertex_count'],tuple(state['influences']))
        if scope!=self.scope:
            self.scope=scope;self.entries.clear()
        live={BASE:(state['base'],)}
        live.update((row['id'],(row.get('samples'),row.get('generated'))) for row in state['layers'])
        for layer,(sources,_) in list(self.entries.items()):
            current=live.get(layer)
            if current is None or len(current)!=len(sources) or any(a is not b for a,b in zip(current,sources)):
                del self.entries[layer]
        if identity not in self.entries:
            weighted=frozenset(core.weighted_influences(state,identity))
            if identity in live:self.entries[identity]=(live[identity],weighted)
            return weighted
        return self.entries[identity][1]


class LayerUI(QtWidgets.QDialog):
    def __init__(self,api,table_type,parent=None):
        super(LayerUI,self).__init__(parent)
        self.api=api;self.session=api.make_session();self.session.on_change=self.session_changed
        def destroyed(*_,session=self.session,owner=weakref.ref(self)):
            session.close();window=owner()
            if window is not None:window._closed=True;window.ctx=None;window.state=None;window.rows=[];window._weight_status=None
        self.destroyed.connect(destroyed)
        self.ctx=None;self.state=None;self.rows=[];self.browser=None;self._browser_key=None
        self._chosen_joints=[];self._joint_source=None;self._last_viewport_joints=[]
        self._active_joint=None;self._active_joint_path=None;self._syncing_browser=False
        self._weight_status=None;self._cleanup_dialog=None
        self._refreshing=False;self._working=False;self._closed=False;self._changing_joint=False
        self._timer=QtCore.QTimer(self);self._timer.setSingleShot(True);self._timer.timeout.connect(self.follow_selection)
        self._paint_timer=QtCore.QTimer(self);self._paint_timer.setSingleShot(True);self._paint_timer.timeout.connect(self.commit_released_stroke)
        self.session.on_pending=self.queue_stroke_release;self.session.can_begin_stroke=self.brush_button_held
        self.relax_brush_revision=11
        self._brush_operation='replace';self.operation_groups={};self.operation_buttons={};self.operation_radios={}
        self.setObjectName(api.WINDOW);self.setWindowTitle('Layer Skin {} | Authoring · UI 38'.format(api.VERSION))
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose);self.resize(1280,940);self.setMinimumWidth(1040)
        outer=QtWidgets.QVBoxLayout(self)
        self.tabs=QtWidgets.QTabWidget();outer.addWidget(self.tabs)
        self.layer_page=QtWidgets.QWidget();layer_layout=QtWidgets.QVBoxLayout(self.layer_page);layer_layout.setContentsMargins(0,0,0,0)
        self.tabs.addTab(self.layer_page,'Layers')
        self.dock_layout=QtWidgets.QMainWindow(self.layer_page,QtCore.Qt.Widget)
        self.dock_layout.setWindowFlags(QtCore.Qt.Widget)
        layer_layout.addWidget(self.dock_layout)
        scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setMinimumWidth(690);self.dock_layout.setCentralWidget(scroll)
        content=QtWidgets.QWidget();layout=QtWidgets.QVBoxLayout(content);layout.setSpacing(7);scroll.setWidget(content)
        row=QtWidgets.QHBoxLayout();self.target=QtWidgets.QLineEdit();self.target.setReadOnly(True)
        self.target.setPlaceholderText('Select a skinned mesh in Maya');row.addWidget(self.target,1)
        self.pin=QtWidgets.QCheckBox('Pin mesh');row.addWidget(self.pin)
        self.pin.toggled.connect(lambda *_:self.queue_selection())
        self.button(row,'Refresh',lambda *_:self.refresh(force_browser=True));layout.addLayout(row)
        row=QtWidgets.QHBoxLayout();row.addWidget(QtWidgets.QLabel('Layers · top overrides bottom'),1)
        self.button(row,'+',lambda *_:self.run('add')).setToolTip('Add a layer; Base is captured automatically on first add.')
        self.button(row,'−',lambda *_:self.run('delete')).setToolTip('Delete the selected editable layer.')
        layout.addLayout(row)
        self.layers=table_type();self.layers.setMinimumHeight(175);layout.addWidget(self.layers)
        self.layers.propertyRequested.connect(self.properties);self.layers.orderRequested.connect(self.reorder)
        self.layers.actionRequested.connect(self.layer_action);self.layers.currentItemChanged.connect(self.layer_changed)
        note=QtWidgets.QLabel('Double-click a name to rename. Double-click its mask icon to paint a mask. Base · 0 always has alpha 1 and a white mask.')
        note.setWordWrap(True);layout.addWidget(note)
        row=QtWidgets.QHBoxLayout();self.paint_mode=QtWidgets.QComboBox();self.paint_mode.addItems(['Weights','Mask'])
        self.paint_mode.currentIndexChanged.connect(self.paint_mode_changed);row.addWidget(self.paint_mode)
        self.paint_button=self.button(row,'Paint',self.paint);self.paint_button.setCheckable(True)
        self.paint_button.setToolTip('Start painting the selected mode. Mask mode automatically displays the layer mask in grayscale.')
        self.select_vertices_button=self.button(row,'Select vertices',self.select_vertices);self.select_vertices_button.setCheckable(True)
        self.select_vertices_button.setToolTip('Save pending paint and switch to vertex selection, keeping weight colors visible. Click Paint or use Maya\'s Y to return. F9 / right-click Vertex keeps the brush active in component mode.')
        self.button(row,'Stop / shaded view',self.stop_paint).setToolTip('Save pending strokes, exit the brush and restore the original mesh display. Select and component tools keep the weight colors until this button is pressed.')
        layout.addLayout(row)
        row=QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel('Brush radius'));self.brush_radius=self.number(.001,100000,1,.1);row.addWidget(self.brush_radius)
        row.addWidget(QtWidgets.QLabel('Opacity'));self.brush_opacity=self.number(0,1,1,.05);row.addWidget(self.brush_opacity)
        row.addWidget(QtWidgets.QLabel('Falloff'));self.brush_falloff=QtWidgets.QComboBox()
        for title,profile in (('Solid','solid'),('Smooth','poly'),('Gaussian','gaussian')):self.brush_falloff.addItem(title,profile)
        self.brush_falloff.setToolTip('Replace / Add / Scale brush falloff. Solid + Opacity 1 applies the full value throughout the brush. Smooth and Gaussian soften the edge. Relax / Shift uses its own smooth curve.')
        self.brush_falloff.currentIndexChanged.connect(self.falloff_changed);row.addWidget(self.brush_falloff);layout.addLayout(row)
        for control in (self.brush_radius,self.brush_opacity):control.editingFinished.connect(self.update_brush)
        note=QtWidgets.QLabel('Exact Replace: Solid + Opacity 1. Soft falloff blends near the edge. Relax / Shift keeps its smooth curve.')
        note.setWordWrap(True);layout.addWidget(note)
        row=QtWidgets.QHBoxLayout()
        self.show_skin=QtWidgets.QCheckBox('Show final skin weights');self.show_skin.toggled.connect(self.view_skin);row.addWidget(self.show_skin)
        self.display_range=QtWidgets.QLabel('Black 0 · White 1');row.addWidget(self.display_range,1)
        self.display_range.setToolTip('Loaded values for the current view. Black is 0; white is 1. Painting commits on release.')
        self.button(row,'Paint info',self.paint_info).setToolTip('Print the loaded plug-in, active paint context, mesh and last callback error in the Script Editor.')
        layout.addLayout(row)
        row=QtWidgets.QHBoxLayout();row.addWidget(QtWidgets.QLabel('Weight display'))
        self.weight_display=QtWidgets.QComboBox();self.weight_display.addItems(['Heat map','Grayscale']);row.addWidget(self.weight_display)
        self.weight_display.setToolTip('Fixed 0–1 colors for layer weights and final skin-weight views. Mask views stay grayscale. Display colors do not change weights.')
        self.ramp_preview=QtWidgets.QLabel();self.ramp_preview.setMinimumWidth(110);self.ramp_preview.setFixedHeight(14);row.addWidget(self.ramp_preview,1)
        row.addWidget(QtWidgets.QLabel('0 → 1'));layout.addLayout(row)
        note=QtWidgets.QLabel('F9 / right-click Vertex keeps Paint in component mode. Q or Select vertices selects components; Y returns to the brush. Stop / shaded view restores shading.')
        note.setWordWrap(True);layout.addWidget(note)
        self.session.set_display('heatmap');self.weight_display.currentIndexChanged.connect(self.display_changed)
        self.whole=QtWidgets.QCheckBox('Replace / Add / Scale: whole mesh (otherwise selected vertices only)');layout.addWidget(self.whole)
        operations_row=QtWidgets.QHBoxLayout();operations_row.setSpacing(6);layout.addLayout(operations_row)
        self.operation_choice=QtWidgets.QButtonGroup(self);self.operation_choice.setExclusive(True)
        for name in ('relax','replace','add','scale'):
            group=QtWidgets.QGroupBox(name.title());group.setObjectName('LayerSkinOperation_'+name)
            column=QtWidgets.QVBoxLayout(group);column.setContentsMargins(8,18,8,8);column.setSpacing(6)
            radio=QtWidgets.QRadioButton('Use brush');radio.setObjectName('LayerSkinBrush_'+name)
            radio.setToolTip('Select {} for regular painting. Shift always uses Relax.'.format(name.title()))
            self.operation_choice.addButton(radio);column.addWidget(radio)
            self.operation_groups[name]=group;self.operation_radios[name]=radio
            radio.toggled.connect(lambda checked,name=name:self.select_operation(name) if checked else None)
            operations_row.addWidget(group,1)
        relax_layout=self.operation_groups['relax'].layout()
        self.relax_iterations=QtWidgets.QSpinBox();self.relax_iterations.setRange(1,100);self.relax_iterations.setValue(3)
        self.relax_strength=self.number(0,1,.5,.05)
        self.relax_max_new=QtWidgets.QSpinBox();self.relax_max_new.setRange(0,1000);self.relax_max_new.setSpecialValueText('Unlimited')
        self.brush_passes=QtWidgets.QSpinBox();self.brush_passes.setRange(1,10);self.brush_passes.setValue(1)
        self.brush_passes.setToolTip('Jacobi passes per Relax brush stamp, including Shift. Execute uses Iterations. One brush pass is a responsive default.')
        self.preserve_coverage=QtWidgets.QCheckBox('Keep coverage');self.preserve_coverage.setChecked(False)
        self.preserve_coverage.setToolTip('Off by default: smooth the visible layer contribution and feather into neighboring empty vertices inside the brush. Enable to keep coverage fixed; a single-joint painted boundary can then remain unchanged. Masks are independent.')
        self.relax_max_new.setToolTip('Maximum new influences per vertex relative to the start of this Flood action or entire Shift stroke. Existing influences are not pruned. This does not add joints to the skinCluster.')
        form=QtWidgets.QFormLayout();form.setHorizontalSpacing(5)
        for title,widget in (('Iterations',self.relax_iterations),('Strength',self.relax_strength),('Max new',self.relax_max_new),('Brush passes',self.brush_passes)):
            widget.setMinimumWidth(66);form.addRow(title,widget)
        self.relax_max_new.setMinimumWidth(88)  # Keep "Unlimited" readable at minimum window width.
        relax_layout.addLayout(form);relax_layout.addWidget(self.preserve_coverage);relax_layout.addStretch(1)
        self.operation_buttons['relax']=self.button(relax_layout,'Execute',self.relax)
        self.value=self.number(0,1,1,.05)
        self.add_value=self.number(-1,1,.1,.05)
        self.scale_value=self.number(0,100,.5,.1)
        self.operation_values={'replace':self.value,'add':self.add_value,'scale':self.scale_value}
        for name,label,description in (('replace','Value','Set the layer weight or mask to this value.'),
                                      ('add','Amount','Add this amount. A negative amount subtracts weight.'),
                                      ('scale','Multiplier','Multiply the current value. 1 keeps it; 0.5 halves it.')):
            column=self.operation_groups[name].layout();column.addWidget(QtWidgets.QLabel(label))
            control=self.operation_values[name];control.setToolTip(description);column.addWidget(control)
            control.editingFinished.connect(lambda name=name:self.operation_value_changed(name))
            note=QtWidgets.QLabel(description+' Results stay between 0 and 1.');note.setWordWrap(True);column.addWidget(note)
            column.addStretch(1)
            self.operation_buttons[name]=self.button(column,'Execute',lambda *_,name=name:self.execute_operation(name))
        self.operation_radios['replace'].setChecked(True)
        note=QtWidgets.QLabel('Selected vertices or edge endpoints; none = whole mesh. 0–1 joints: all neighbor influences. 2+ joints: redistribute within their existing combined weight.')
        note.setText('Relax: '+note.text());note.setWordWrap(True);layout.addWidget(note)
        hint=QtWidgets.QLabel('Use brush selects the Paint operation. Shift + paint: Relax. B + drag: radius. Execute applies the full operation; brush Opacity affects strokes only.')
        hint.setWordWrap(True);layout.addWidget(hint)
        self.button(layout,'Clear paint edits',lambda *_:self.run('clear'))
        self.session.relax_settings=self.brush_settings;self.session.on_brush_settings=self.sync_brush_settings
        self.button(layout,'Inspect selected influence weights',self.inspect)
        row=QtWidgets.QHBoxLayout();self.button(row,'Undo + refresh',lambda *_:self.history(False));self.button(row,'Redo + refresh',lambda *_:self.history(True))
        self.button(row,'Cleanup…',self.open_cleanup).setToolTip('Inspect saved data for the current mesh, clear memory caches, or remove its saved layers while keeping current skin weights.')
        self.button(row,'Restore original',lambda *_:self.finish('restore'));layout.addLayout(row)
        layout.addStretch(1)
        self.joint_dock=QtWidgets.QDockWidget('Joint hierarchy',self.dock_layout)
        self.joint_dock.setObjectName('LayerSkinJointHierarchyDock')
        self.joint_dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea|QtCore.Qt.RightDockWidgetArea)
        self.joint_dock.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable|QtWidgets.QDockWidget.DockWidgetFloatable)
        self.joint_dock.setMinimumWidth(270)
        joint_panel=QtWidgets.QWidget();g=QtWidgets.QVBoxLayout(joint_panel)
        self.browser_host=QtWidgets.QWidget();self.browser_host.setMinimumHeight(230)
        host_layout=QtWidgets.QVBoxLayout(self.browser_host);host_layout.setContentsMargins(0,0,0,0)
        self.browser_error=QtWidgets.QLabel();self.browser_error.setWordWrap(True);self.browser_error.hide();host_layout.addWidget(self.browser_error)
        g.addWidget(self.browser_host,1)
        legend=QtWidgets.QLabel('Gray: no weights yet. Click the padlock to protect a joint in this layer. The first stroke adds an unlocked joint automatically.');legend.setWordWrap(True);g.addWidget(legend)
        self.paint_joint=QtWidgets.QLabel('Paint joint: —');self.paint_joint.setWordWrap(True);g.addWidget(self.paint_joint)
        row=QtWidgets.QHBoxLayout();row.addWidget(QtWidgets.QLabel('Redistribution'))
        self.redistribution=QtWidgets.QComboBox()
        self.redistribution.setEnabled(False)
        self.redistribution.addItem('Proportional','proportional');self.redistribution.addItem('Equal','equal')
        self.redistribution.setToolTip('For Replace/Add/Scale: share other unlocked weighted contributions by their current ratios or equally. Locked layer contributions stay fixed. No unrelated zero-weight joints receive weights. Reducing a weight can reduce layer coverage; Relax uses its topology average.')
        row.addWidget(self.redistribution,1);g.addLayout(row);self.redistribution.currentIndexChanged.connect(self.redistribution_changed)
        assignment=QtWidgets.QGroupBox('Assign weights');a=QtWidgets.QGridLayout(assignment)
        self.method=QtWidgets.QComboBox();self.method.addItems(['Distance to bone','Distance to joint','Joint axis'])
        self.method.setToolTip('Distance to joint: closest selected joint pivot. Distance to bone: closest segment from a selected joint to its joint children, including transform buffers; a tip uses its pivot. Joint axis: closest bone first, with positive local-axis preference only for equally close bones. If all axes are negative, the nearest bone still receives the vertex. All methods assign full coverage without Radius or Falloff, using the cached pre-skin/bind-space reference.')
        a.addWidget(QtWidgets.QLabel('Method'),0,0);a.addWidget(self.method,0,1,1,3)
        self.axis=QtWidgets.QComboBox();self.axis.addItems(['+X','-X','+Y','-Y','+Z','-Z'])
        self.assignment_scope=QtWidgets.QComboBox();self.assignment_scope.addItems(['Whole mesh','Selected vertices'])
        self.axis.setToolTip('For Joint axis, prefer the positive side of this local axis when bones are equally close. Distance stays primary; the negative side is still assigned.')
        a.addWidget(QtWidgets.QLabel('Axis'),1,0);a.addWidget(self.axis,1,1,1,3)
        self.method.currentIndexChanged.connect(self.assignment_method_changed);self.assignment_method_changed()
        a.addWidget(QtWidgets.QLabel('Scope'),2,0);a.addWidget(self.assignment_scope,2,1,1,3)
        self.keep_paint=QtWidgets.QCheckBox('Preserve painted / flooded edits')
        self.keep_paint.setToolTip('Off: Assign selected joints replaces weight overrides within the selected scope. On: keep paint, Flood and Relax overrides. Rebuild always preserves them. Layer masks are kept in both cases.')
        a.addWidget(self.keep_paint,3,0,1,4)
        self.button(a,'Assign selected joints',self.assign,4,0,1,4).setToolTip('Assign every scoped vertex to its nearest selected joint or bone at full layer coverage. By default this replaces painted, flooded and relaxed weight overrides there; layer masks and vertices outside the scope are preserved.')
        row=QtWidgets.QHBoxLayout()
        self.button(row,'Rebuild layer',lambda *_:self.assign(rebuild=True)).setToolTip('Regenerate using every joint already used by this layer.')
        self.button(row,'Recapture reference',lambda *_:self.run('reference'));a.addLayout(row,5,0,1,4)
        self.reference_status=QtWidgets.QLabel('Assignment uses the skin input mesh and matching bind-space joint frames.');self.reference_status.setWordWrap(True)
        self.reference_status.setToolTip('All three assignment methods use a cached pre-skin reference. Bound joint frames come from bindPreMatrix. Unbound joints retain captured offsets under a bound ancestor, or relative to the mesh when none exists. Upstream deformers may affect the skin input. Recapture explicitly refreshes this snapshot; brush picking still uses the visible mesh.')
        self.reference_status.setMinimumHeight(self.reference_status.fontMetrics().lineSpacing()*4)
        a.addWidget(self.reference_status,6,0,1,4);g.addWidget(assignment)
        self.button(g,'Clear assignment cache',self.clear_cache)
        self.joint_dock.setWidget(joint_panel);self.dock_layout.addDockWidget(QtCore.Qt.RightDockWidgetArea,self.joint_dock)
        self.dock_layout.resizeDocks([self.joint_dock],[320],QtCore.Qt.Horizontal)
        self.status=QtWidgets.QLabel('Select a skinned mesh. Selection only loads data; + creates the layer stack.');self.status.setWordWrap(True);outer.addWidget(self.status)
        self.utilities=self.session.helper('layer_skin_io_ui').Utilities(self)
        self.numpy_panel=self.session.helper('layer_skin_numpy_ui').PerformancePanel(self)
        self.utilities.scroll.widget().layout().insertWidget(0,self.numpy_panel)
        self.tabs.addTab(self.utilities,'Utilities');self.tabs.currentChanged.connect(self.page_changed)
        self.update_display_range()

    def page_changed(self,index):
        if index:
            if not self.stop_paint():
                blocker=QtCore.QSignalBlocker(self.tabs);self.tabs.setCurrentIndex(0);del blocker
            return
        if self.target.text():self.refresh()
        self.queue_selection()

    def number(self,low,high,value,step):
        widget=QtWidgets.QDoubleSpinBox();widget.setRange(low,high);widget.setDecimals(3);widget.setSingleStep(step);widget.setValue(value);widget.setKeyboardTracking(False)
        return widget
    def button(self,layout,title,callback,*position):
        button=QtWidgets.QPushButton(title);button.setAutoDefault(False);button.setDefault(False);button.clicked.connect(callback);layout.addWidget(button,*position);return button
    def message(self,text,error=False):
        self.status.setText(str(text))
        if error:self.api.cmds.warning(str(text))
    def showEvent(self,event):
        super(LayerUI,self).showEvent(event)
        try:
            self.session.listen(self.queue_selection,self.scene_reset)
            self.ensure_browser()
            self.queue_selection()
        except Exception as exc:self.message(exc,True)
    def ensure_browser(self):
        if self.browser is not None:return True
        try:
            self.browser=self.session.make_browser(self.browser_host,self.browser_selected)
            self.browser_error.hide();self._browser_key=None;return True
        except Exception as exc:
            text='Could not build joint hierarchy: '+str(exc)+'. Click Refresh to retry.'
            self.browser_error.setText(text);self.browser_error.show();self.message(text,True);return False
    def hideEvent(self,event):
        self._timer.stop();self._paint_timer.stop();self.session.unlisten();self.stop_paint(discard=True);super(LayerUI,self).hideEvent(event)
    def closeEvent(self,event):
        self._closed=True;self._timer.stop();self._paint_timer.stop()
        self.numpy_panel.shutdown()
        try:self.session.close()
        finally:
            self.utilities.clear_file();self.utilities._backend=None
            self.ctx=None;self.state=None;self.rows=[];self.browser=None;self._weight_status=None
            super(LayerUI,self).closeEvent(event)
    def queue_selection(self,*_):
        if not self._closed and not self.session.closed and self.isVisible() and not self._timer.isActive():self._timer.start(0)
    def session_changed(self):
        if hasattr(self,'paint_button'):self.sync_tool_buttons()
        self.queue_selection()
    def sync_tool_buttons(self):
        painting=self.session.active and self.api.cmds.currentCtx()==self.api.paint_context
        selecting=self.session.viewing and not self.session.active and self.api.cmds.currentCtx()=='selectSuperContext'
        for button,value in ((self.paint_button,painting),(self.select_vertices_button,selecting)):
            blocker=QtCore.QSignalBlocker(button);button.setChecked(value);del blocker

    def brush_button_held(self):return bool(QtWidgets.QApplication.mouseButtons() & QtCore.Qt.LeftButton)
    def queue_stroke_release(self):
        if not self._closed and not self.session.closed and not self._paint_timer.isActive():self._paint_timer.start(30)
    def commit_released_stroke(self):
        if self._closed or self.session.closed or self.session.stroke is None:return
        if self.brush_button_held():self.queue_stroke_release();return
        try:self.session.flush_pending('mouse_release_fallback')
        except Exception as exc:self.message('Stroke rejected: '+str(exc),True)
    @color_action
    def paint_mode_changed(self,*_):
        previous=1 if self.session.mode=='mask' else 0
        viewing=self.session.viewing
        if not self.stop_paint(keep_view=True):
            blocker=QtCore.QSignalBlocker(self.paint_mode);self.paint_mode.setCurrentIndex(previous);del blocker
        elif viewing:self.update_preview(mode='mask' if self.paint_mode.currentIndex()==1 else 'weights')
    @color_action
    def follow_selection(self):
        if self._working or self._changing_joint or self._closed or self.session.closed:return
        if self.session._selection_handoff:return
        previous=(self.session.values,self.session.viewing,self.session.mode,self.session.display)
        try:
            if self.session._component_mode_dirty:self.session.keep_paint_in_component_mode()
        except Exception as exc:
            self.message(exc,True);return
        if self.session.adjusting_brush:
            self.session._settings_selection_deferred=True;return
        self.session._settings_selection_deferred=False
        if self.tabs.currentIndex()!=0:return
        try:
            mesh,joints=self.session.selection()
            if mesh and not self.pin.isChecked() and (mesh!=self.target.text() or self.ctx is None):
                if not self.stop_paint():return
                self._chosen_joints=[];self._joint_source=None
                self._active_joint=None;self._active_joint_path=None
                self.target.setText(mesh);self.refresh(force_browser=True)
            elif self.target.text():
                # Only Undo/Redo or a completed stroke requires a full refresh.
                if getattr(self.session,'needs_refresh',False):
                    self.session.needs_refresh=False;self.refresh(snapshot=self.session.take_committed_snapshot())
            if not self.session.active:
                self._paint_timer.stop()
                blocker=QtCore.QSignalBlocker(self.show_skin);self.show_skin.setChecked(self.session.viewing and self.session.mode=='skin');del blocker
            if joints!=self._last_viewport_joints:
                self._last_viewport_joints=list(joints)
                if joints:self._chosen_joints=list(joints);self._joint_source='viewport';self.choose_joint(joints[-1])
            if (self.session.values is not previous[0] or
                    (self.session.viewing,self.session.mode,self.session.display)!=previous[1:]):self.update_display_range()
        except Exception as exc:self.message(exc,True)
        finally:self.sync_tool_buttons()
    def scene_reset(self,*_):
        self.utilities.scene_reset()
        dialog=self._cleanup_dialog() if self._cleanup_dialog else None
        if dialog:
            try:dialog.close()
            except RuntimeError:pass
        self._cleanup_dialog=None
        self._timer.stop();self._paint_timer.stop();self.stop_paint(discard=True);self.target.clear();self.ctx=None;self.state=None;self.rows=[]
        self._chosen_joints=[];self._joint_source=None;self._last_viewport_joints=[]
        self._active_joint=None;self._active_joint_path=None;self.paint_joint.setText('Paint joint: —')
        self._weight_status=None
        self.layers.set_layers([]);self._browser_key=None
        if self.browser:self.browser.scope(None)
        if self.browser:self.browser.set_layer_status(set(),set(),{})
        if hasattr(self.browser,'set_influence_locks'):self.browser.set_influence_locks((),False,self.toggle_joint_lock)
        blocker=QtCore.QSignalBlocker(self.redistribution);self.redistribution.setCurrentIndex(0);self.redistribution.setEnabled(False);del blocker
        self.session.helper('layer_skin_cleanup').clear_caches(self.api);self.message('Select a skinned mesh in the new scene.')
    def selected_id(self):return self.layers.identity(self.layers.currentItem())
    def layer(self,identity=None):
        identity=identity or self.selected_id()
        if identity==BASE:raise ValueError('Base · 0 is preserved. Select an editable layer above it.')
        for row in self.rows:
            if row['id']==identity:return row
        raise ValueError('Select a layer first.')
    @color_action
    def refresh(self,keep=None,force_browser=False,snapshot=None):
        if not self.target.text():return False
        self.ensure_browser()
        keep=keep or self.selected_id()
        self._refreshing=True
        try:
            self.ctx,_meta,self.state=self.session.snapshot(self.target.text()) if snapshot is None else snapshot
            self.target.setText(self.ctx['shape']);self.rows=list(reversed(self.state['layers']))
            base=dict(id=BASE,name='Base · 0',enabled=True,opacity=1.,samples={},mask={})
            self.layers.set_layers(self.rows+[base],keep or (self.rows[0]['id'] if self.rows else BASE))
            hierarchy=self.session.helper('layer_skin_joint_view')
            roots=hierarchy.skin_roots(self.api,self.ctx)
            paths=tuple(path.fullPathName() for path in self.ctx['influences'])
            key=(self.ctx['uuid'],tuple(self.ctx['ids']),paths,roots)
            if self.browser and (force_browser or key!=self._browser_key):
                self.browser.scope(roots);self._browser_key=key
            self.populate_joints()
            paint_error=None
            if self.session.active or self.session.viewing:
                try:
                    if self.session.active and self.session.mode=='weights' and self.session.readonly!=self.joint_locked(self.session.joint):
                        self.session.start(self.target.text(),self.session.layer,self.session.joint,'weights',self.joint_locked(self.session.joint),
                            self.brush_value(),self.brush_radius.value(),self.brush_opacity.value(),joint_path=self.session.joint_path,operation=self._brush_operation)
                    elif self.session.active:self.session.refresh_view((self.ctx,_meta,self.state),force=force_browser)
                    else:self.session.view(self.ctx['shape'],self.selected_id() or BASE,self.active_joint(),self.session.mode,
                        joint_path=self._active_joint_path,snapshot=(self.ctx,_meta,self.state))
                except Exception as exc:
                    self.stop_paint(discard=True);paint_error='Paint stopped after refresh: '+str(exc)
            self.update_display_range()
            ref=self.state.get('reference');stats=self.api.cache_stats()
            source=('Skin input / bind space' if ref.get('geometry_source')=='skin_input_bind' else 'Legacy posed reference · next Assign uses skin input') if ref else 'Skin input / bind space · captured on first Assign'
            derived=len(ref.get('derived_joints',())) if ref else 0
            self.reference_status.setText(source+(' · {} unbound offsets'.format(derived) if derived else '')+'. '+
                ('Captured at frame {}. '.format(ref['time']) if ref else '')+
                '{} cached assignments built · {} cache hits. Paint and masks survive rebuild.'.format(stats['builds'],stats['hits']))
            stroke=getattr(self.session,'last_stroke',None)
            stroke_status=None
            if (self.session.active and stroke and stroke['mesh']==self.ctx['shape'] and stroke['layer']==self.selected_id()
                    and stroke['mode']==self.session.mode and (self.session.mode=='mask' or stroke['joint']==self.session.joint)):
                if stroke['status']=='saved':
                    count=stroke['changed_vertices']
                    stroke_status='Stroke saved · {} {} · {}.'.format(count,'vertex' if count==1 else 'vertices',stroke['mode'])
                elif stroke['status'] in ('rejected','verification_failed'):
                    stroke_status='Stroke {}: {}'.format(stroke['status'].replace('_',' '),stroke['error'])
            self.message(paint_error or stroke_status or '{} vertices · {} skin influences · {} editable layers. {}'.format(self.ctx['count'],len(self.ctx['ids']),len(self.rows),'Ready.' if _meta else 'Base preview; + starts editing.'))
            return True
        except Exception as exc:
            self.stop_paint(discard=True);self.ctx=None;self.state=None;self.rows=[];self.layers.set_layers([])
            self._active_joint=None;self._active_joint_path=None;self._weight_status=None;self.paint_joint.setText('Paint joint: —')
            if self.browser:self.browser.set_layer_status(set(),set(),{})
            self.message(exc,True);return False
        finally:self._refreshing=False
    def populate_joints(self):
        identity=self.selected_id();row=next((row for row in self.rows if row['id']==identity),None)
        members=set(self.ctx['ids'] if identity==BASE else (row or {}).get('joints',[]))
        paths={path.fullPathName():joint for joint,path in zip(self.ctx['ids'],self.ctx['influences'])}
        if self._weight_status is None:self._weight_status=InfluenceSummaries()
        weighted=self._weight_status.get(self.api.core,self.ctx,self.state,identity)
        if self.browser:self.browser.set_layer_status(weighted,members,paths)
        if hasattr(self.browser,'set_influence_locks'):
            self.browser.set_influence_locks((row or {}).get('influence_locks',()),row is not None,self.toggle_joint_lock)
        blocker=QtCore.QSignalBlocker(self.redistribution)
        self.redistribution.setCurrentIndex(self.redistribution.findData((row or {}).get('redistribution','proportional')))
        self.redistribution.setEnabled(row is not None);del blocker
        records=getattr(self.browser,'records',None)
        if records is not None and self._active_joint not in records.values():
            self._active_joint=None;self._active_joint_path=None
        if self._active_joint is None:
            preferred=next((path for path,joint in paths.items() if joint in members),next(iter(paths),None))
            if preferred:self.choose_joint(preferred)
        else:
            current=next((path for path,joint in paths.items() if joint==self._active_joint),None)
            if current:self._active_joint_path=current
            self.update_paint_joint_label()
            self.sync_browser_joint()
    @color_action
    def layer_changed(self,*_):
        if self._refreshing:return
        viewing=self.session.viewing
        if not self.stop_paint(keep_view=True):
            blocker=QtCore.QSignalBlocker(self.layers)
            for i in range(self.layers.topLevelItemCount()):
                if self.layers.identity(self.layers.topLevelItem(i))==self.session.layer:self.layers.setCurrentItem(self.layers.topLevelItem(i),1);break
            del blocker;return
        if self.ctx:self.populate_joints()
        if viewing:self.update_preview()
    def browser_selected(self,*_):
        if self._closed or self._refreshing or self._syncing_browser or self._changing_joint:return
        joints=self.browser.joints() if self.browser else []
        if joints:
            self._chosen_joints=list(joints);self._joint_source='browser';self.choose_joint(joints[-1],sync=False)
        elif self._joint_source=='browser':self._chosen_joints=[]
    def joint_locked(self,joint=None):
        row=next((row for row in self.rows if row['id']==self.selected_id()),{})
        return (self.active_joint() if joint is None else joint) in row.get('influence_locks',())
    @color_action
    def change_influence_settings(self,data):
        resume=self.session.active and self.api.cmds.currentCtx()==self.api.paint_context
        result=self.run('influence_settings',data)
        if resume:self.paint()
        return result
    def toggle_joint_lock(self,path,locked):
        try:
            row=self.layer();identity=self.api.joint_id(path);locks=set(row.get('influence_locks',()))
            if locked:locks.add(identity)
            else:locks.discard(identity)
            return self.change_influence_settings(dict(influence_locks=sorted(locks)))
        except Exception as exc:self.message(exc,True);return False
    def redistribution_changed(self,*_):
        if self._refreshing or self._working:return
        self.change_influence_settings(dict(redistribution=self.redistribution.currentData()))
    @color_action
    def choose_joint(self,path,sync=True):
        if self._changing_joint:return False
        # Native tool changes can process Qt events before returning. Defer
        # selection refresh until the brush and hierarchy share the new joint.
        self._changing_joint=True
        try:
            identity=self.api.joint_id(path)
            changed=identity!=self._active_joint
            owns_tool=self.session.active and self.api.cmds.currentCtx()==self.api.paint_context
            resume=changed and owns_tool and self.session.mode=='weights' and not self.session.readonly
            resume_skin=changed and owns_tool and self.session.mode=='skin'
            viewing=self.session.viewing
            reused=False
            if changed and owns_tool and self.session.mode in ('weights','skin') and not self._refreshing:
                try:
                    if not self.save_pending_paint():self.sync_browser_joint();return False
                    readonly=self.joint_locked(identity) if self.session.mode=='weights' else self.session.readonly
                    self.session.start(self.target.text(),self.session.layer,identity,self.session.mode,readonly,
                        self.brush_value(),self.brush_radius.value(),self.brush_opacity.value(),joint_path=path,operation=self._brush_operation)
                    reused=True
                except Exception as exc:
                    self.sync_browser_joint();self.message(exc,True);return False
            if changed and not reused and self.session.mode in ('weights','skin') and not self.stop_paint(keep_view=True):
                self.sync_browser_joint();return False
            self._active_joint=identity;self._active_joint_path=path;self.update_paint_joint_label()
            if sync:self.sync_browser_joint()
            if reused:self.update_display_range()
            elif resume and not self._refreshing:self.paint()
            elif resume_skin and not self._refreshing:self.view_skin(True)
            elif changed and viewing and self.session.mode in ('weights','skin') and not self._refreshing:self.update_preview()
            return True
        finally:
            self._changing_joint=False;self.queue_selection()
    def sync_browser_joint(self):
        if self.browser and self._active_joint_path and not self._syncing_browser and self._active_joint_path not in self.browser.joints():
            self._syncing_browser=True
            try:self.browser.select_joint(self._active_joint_path)
            finally:self._syncing_browser=False
    def update_paint_joint_label(self):
        path=self._active_joint_path
        self.paint_joint.setText('Paint joint: '+(path.rsplit('|',1)[-1] if path else '—'))
        self.paint_joint.setToolTip(path or 'Choose a joint in the hierarchy.')
    def chosen_joints(self):
        _,viewport=self.session.selection()
        if viewport and viewport!=self._last_viewport_joints:
            self._chosen_joints=list(viewport);self._joint_source='viewport';self._last_viewport_joints=list(viewport)
        if self._joint_source=='browser':return self.browser.joints() if self.browser else []
        return list(self._chosen_joints) or (self.browser.joints() if self.browser else viewport)
    def properties(self,identity,values):
        if self._refreshing or self._working or identity==BASE:return
        try:
            row=self.layer(identity)
            if all(row[key]==value for key,value in values.items()):return
            if 'name' in values:
                values['name']=values['name'].strip()
                if not values['name']:raise ValueError('Layer name cannot be empty.')
            if all(row[key]==value for key,value in values.items()):return
            self.run('properties',values,identity)
        except Exception as exc:self.refresh(identity);self.message(exc,True)
    def reorder(self,visible_order):
        if visible_order==[row['id'] for row in self.rows]:return
        self.run('reorder',{'order':list(reversed(visible_order))})
    @color_action
    def run(self,action,extra=None,layer_id=None):
        if self._working or self._refreshing:return False
        self._working=True;keep=layer_id or self.selected_id()
        try:
            if not self.stop_paint(keep_view=action not in ('bake','restore')):return False
            data={'target':self.target.text()}
            if action not in ('add','reference','bake','restore','reorder'):data['layer']=self.layer(keep)['id']
            if action=='add':data['name']='Layer {}'.format(len(self.rows)+1)
            if action in ('flood','mask','clear'):data.update(whole=self.whole.isChecked(),value=self.value.value())
            if action=='flood':
                data['joint']=self.active_joint()
            data.update(extra or {})
            if action=='flood':result=self.session.edit_joints(self.target.text(),keep,[self._active_joint_path],'flood',data)
            else:result=self.api.cmds.rtkLayerSkin(action=action,data=json.dumps(data))
            self.refresh(None if action=='add' else keep)
            if action=='add' and self.rows:self.layers.setCurrentItem(self.layers.topLevelItem(0),1)
            if result:self.message(result)
            return True
        except Exception as exc:self.refresh(keep);self.message(exc,True);return False
        finally:self._working=False
    def layer_action(self,action,identity):
        if action in ('paint_mask','view_mask'):
            if action=='view_mask':self.view_mask(True,identity)
            else:
                self.paint_mode.setCurrentIndex(1);self.paint(layer_id=identity)
        else:self.run(action,layer_id=identity)
    def active_joint(self):
        return self._active_joint
    def save_pending_paint(self):
        self._paint_timer.stop();self.sync_brush_settings()
        try:self.session.flush_pending('action_change');return True
        except Exception as exc:self.message('Stroke rejected: '+str(exc),True);return False
    @color_action
    def paint(self,*_,layer_id=None):
        try:
            self.layer(layer_id)
            if not self.save_pending_paint():return False
            self.session.start(self.target.text(),layer_id or self.selected_id(),self.active_joint(),
                'mask' if self.paint_mode.currentIndex()==1 else 'weights',self.paint_mode.currentIndex()==0 and self.joint_locked(),
                self.brush_value(),self.brush_radius.value(),self.brush_opacity.value(),joint_path=self._active_joint_path,operation=self._brush_operation)
            blocker=QtCore.QSignalBlocker(self.show_skin);self.show_skin.setChecked(False);del blocker
            self.update_display_range()
            colors='blue 0, green 0.5, red 1' if self.session.effective_display()=='heatmap' else 'black 0, white 1'
            self.message('Locked joint · viewing saved layer weights. Unlock the padlock to paint.' if self.session.readonly else '{} brush · layer {} · {}. Shift: Relax. Release commits one Undo.'.format(self._brush_operation.title(),'mask' if self.paint_mode.currentIndex()==1 else 'weights',colors))
            return True
        except Exception as exc:self.message(exc,True);return False
    @color_action
    def select_vertices(self,*_):
        try:
            if not self.target.text():raise ValueError('Load a skinned mesh first.')
            self._paint_timer.stop()
            if self.session.active:self.session.pause_for_components()
            elif self.api.cmds.currentCtx()!='selectSuperContext':self.api.cmds.setToolTo('selectSuperContext')
            if not self.session.viewing:
                self.session.view(self.target.text(),self.selected_id() or BASE,self.active_joint(),
                    'mask' if self.paint_mode.currentIndex()==1 else 'weights',joint_path=self._active_joint_path)
            parents=self.api.cmds.listRelatives(self.session.target,parent=True,fullPath=True) or []
            if len(parents)!=1:raise ValueError('The loaded mesh needs one transform parent for vertex selection.')
            self.api.cmds.hilite(parents[0],replace=True)
            self.api.cmds.selectMode(component=True)
            self.api.cmds.selectType(allComponents=False)
            self.api.cmds.selectType(polymeshVertex=True)
            self.session.show_preview();self.session.queue_preview()
            self.update_display_range()
            if self.session.preview_error:
                self.message('Select vertices · weight display unavailable: '+self.session.preview_error,True)
                return False
            self.message('Select vertices · weight colors visible. Click Paint or use Maya\'s Y to resume the brush.')
            return True
        except Exception as exc:self.message(exc,True);return False
        finally:self.sync_tool_buttons()

    @color_action
    def view_mask(self,enabled,identity=None):
        if not enabled:self.stop_paint();return
        try:
            if not self.stop_paint():return
            self.session.start(self.target.text(),identity or self.selected_id(),mode='mask',readonly=True)
            self.update_display_range()
            self.message('Viewing mask · white 1, black 0. Painting is disabled until Paint is selected.')
        except Exception as exc:self.message(exc,True)
    @color_action
    def view_skin(self,enabled):
        if not enabled:self.stop_paint();return
        try:
            if not self.stop_paint():
                blocker=QtCore.QSignalBlocker(self.show_skin);self.show_skin.setChecked(False);del blocker;return
            self.session.start(self.target.text(),self.selected_id() or BASE,self.active_joint(),mode='skin',readonly=True,joint_path=self._active_joint_path)
            self.update_display_range()
            blocker=QtCore.QSignalBlocker(self.show_skin);self.show_skin.setChecked(True);del blocker
            self.message('Final skin weights · read-only · colors follow Weight display. Click Paint to edit the selected layer.')
        except Exception as exc:self.message(exc,True)
    @color_action
    def stop_paint(self,*_,discard=False,keep_view=False):
        self._paint_timer.stop()
        self.sync_brush_settings()
        if not discard:
            try:self.session.flush_pending('action_change')
            except Exception as exc:
                self.message('Stroke rejected: '+str(exc),True);return False
        self.session.stop(keep_view=keep_view,disarm=not keep_view)
        self.sync_tool_buttons()
        self.update_display_range()
        if hasattr(self,'show_skin'):
            blocker=QtCore.QSignalBlocker(self.show_skin);self.show_skin.setChecked(keep_view and self.session.viewing and self.session.mode=='skin');del blocker
        return True
    def update_preview(self,mode=None):
        if not self.session.viewing or self.session.active or not self.target.text():return
        try:
            self.session.view(self.target.text(),self.selected_id() or BASE,self.active_joint(),
                mode or self.session.mode,joint_path=self._active_joint_path)
            self.update_display_range()
        except Exception as exc:self.stop_paint(discard=True);self.message(exc,True)
    def update_display_range(self):
        if not hasattr(self,'display_range'):return
        values=self.session.values
        heat=(self.session.effective_display()=='heatmap' if self.session.viewing else self.weight_display.currentIndex()==0 and self.paint_mode.currentIndex()!=1)
        self.display_range.setText('Values {:.2f}–{:.2f}'.format(min(values),max(values)) if self.session.viewing and values else ('Blue 0 · Green 0.5 · Red 1' if heat else 'Black 0 · White 1'))
        ramp=('stop:0 #050d59,stop:0.25 #00ccff,stop:0.5 #1aff26,stop:0.75 #ffe600,stop:1 #ff0d00' if heat else 'stop:0 black,stop:1 white')
        self.ramp_preview.setStyleSheet('border:1px solid #555;background:qlineargradient(x1:0,y1:0,x2:1,y2:0,'+ramp+');')
    @color_action
    def display_changed(self,*_):
        try:self.session.set_display('heatmap' if self.weight_display.currentIndex()==0 else 'grayscale');self.update_display_range()
        except Exception as exc:
            blocker=QtCore.QSignalBlocker(self.weight_display);self.weight_display.setCurrentIndex(0 if self.session.display=='heatmap' else 1);del blocker
            self.message(exc,True)
    @color_action
    def relax(self,*_):
        if self._working or self._refreshing:return False
        try:
            layer=self.layer();joints=self.chosen_joints()
            if not self.select_operation('relax'):return False
            self.operation_radios['relax'].setChecked(True)
            resume=self.session.active and self.api.cmds.currentCtx()==self.api.paint_context
            mode=self.session.mode;readonly=self.session.readonly
            if not self.stop_paint(keep_view=True):return False
            self._working=True
            data=dict(target=self.target.text(),layer=layer['id'],joints=list(dict.fromkeys(self.api.joint_id(path) for path in joints)),
                      iterations=self.relax_iterations.value(),strength=self.relax_strength.value(),max_new=self.relax_max_new.value(),
                      mode='mask' if self.paint_mode.currentIndex()==1 else 'weights',preserve_coverage=self.preserve_coverage.isChecked())
            result=self.api.cmds.rtkLayerSkin(action='relax',data=json.dumps(data))
            self.refresh(layer['id'])
            if resume:
                if readonly and mode=='skin':self.view_skin(True)
                else:self.paint()
            elif not self.session.viewing:
                self.session.view(self.target.text(),layer['id'],self.active_joint(),
                    'mask' if self.paint_mode.currentIndex()==1 else 'weights',joint_path=self._active_joint_path)
                self.update_display_range()
            self.message(result or 'Relax complete. Weight colors updated.')
            return True
        except Exception as exc:self.message(exc,True);return False
        finally:
            self._working=False;self.session.show_preview()
    def brush_value(self):
        return self.operation_values[self._brush_operation].value() if self._brush_operation!='relax' else 1.
    @color_action
    def select_operation(self,name):
        if name==self._brush_operation:return True
        previous=self._brush_operation
        try:
            self.sync_brush_settings();self.session.flush_pending('operation_change')
            flags=self.session.helper('layer_skin_operations').brush_flags(name,self.operation_values[name].value() if name!='relax' else 1.)
            if self.session.active and not self.session.readonly:
                self.api.cmds.artUserPaintCtx(self.api.paint_context,edit=True,**flags)
            self._brush_operation=name;self.session.brush_operation=name
            self.brush_falloff.setEnabled(name!='relax')
            if hasattr(self,'status'):self.message('{} selected for Paint. Shift always uses Relax.'.format(name.title()))
            return True
        except Exception as exc:
            blocker=QtCore.QSignalBlocker(self.operation_radios[previous]);self.operation_radios[previous].setChecked(True);del blocker
            self.message(exc,True);return False
    def operation_value_changed(self,name):
        if name==self._brush_operation:self.update_brush()
    @color_action
    def execute_operation(self,name):
        if self._working or self._refreshing:return False
        try:
            layer=self.layer();mode='mask' if self.paint_mode.currentIndex()==1 else 'weights'
            resume=self.session.active and self.api.cmds.currentCtx()==self.api.paint_context
            if not self.select_operation(name):return False
            self.operation_radios[name].setChecked(True)
            if not self.stop_paint(keep_view=True):return False
            self._working=True
            data=dict(target=self.target.text(),layer=layer['id'],mode=mode,operation=name,
                      amount=self.operation_values[name].value(),whole=self.whole.isChecked(),joint=self.active_joint())
            if mode=='weights':result=self.session.edit_joints(self.target.text(),layer['id'],[self._active_joint_path],'value_operation',data)
            else:result=self.api.cmds.rtkLayerSkin(action='value_operation',data=json.dumps(data))
            self.refresh(layer['id'])
            if resume:self.paint()
            elif not self.session.viewing:
                self.session.view(self.target.text(),layer['id'],self.active_joint(),mode,joint_path=self._active_joint_path)
                self.update_display_range()
            self.message('{} {} · {} · {}'.format(name.title(),mode,self.operation_values[name].value(),
                'Unchanged.' if 'unchanged' in str(result).lower() else 'Complete.'))
            return True
        except Exception as exc:self.message(exc,True);return False
        finally:
            self._working=False;self.session.show_preview()
    def update_brush(self):
        if self.session.active:
            field={self.brush_radius:'radius',self.brush_opacity:'opacity'}.get(self.sender())
            if field=='radius':values=dict(radius=self.brush_radius.value())
            elif field=='opacity':values=dict(opacity=0. if self.session.readonly else self.brush_opacity.value())
            else:
                values=dict(radius=self.brush_radius.value(),opacity=0. if self.session.readonly else self.brush_opacity.value())
                if not self.session.readonly:values.update(self.session.helper('layer_skin_operations').brush_flags(self._brush_operation,self.brush_value()))
            self.session.update_brush_settings(**values)
    @color_action
    def falloff_changed(self,*_):
        try:self.session.set_brush_profile(self.brush_falloff.currentData())
        except Exception as exc:
            blocker=QtCore.QSignalBlocker(self.brush_falloff);self.brush_falloff.setCurrentIndex(self.brush_falloff.findData(self.session.brush_profile));del blocker
            self.message(exc,True)
    def sync_brush_settings(self):
        if self._closed or not self.session.active or self.api.cmds.currentCtx()!=self.api.paint_context:return
        for flag,control in (('radius',self.brush_radius),('value',self.operation_values.get(self._brush_operation)),('opacity',self.brush_opacity)):
            if control is None or (flag in ('value','opacity') and self.session.readonly):continue
            value=self.api.cmds.artUserPaintCtx(self.api.paint_context,query=True,**{flag:True})
            if value is not None:
                blocker=QtCore.QSignalBlocker(control);control.setValue(float(value));del blocker
        profile=self.api.cmds.artUserPaintCtx(self.api.paint_context,query=True,stampProfile=True)
        index=self.brush_falloff.findData(profile)
        if index>=0:
            blocker=QtCore.QSignalBlocker(self.brush_falloff);self.brush_falloff.setCurrentIndex(index);del blocker
            self.session.brush_profile=profile
    def brush_settings(self):
        return dict(iterations=self.brush_passes.value(),strength=self.relax_strength.value(),max_new=self.relax_max_new.value(),
            preserve_coverage=self.preserve_coverage.isChecked(),joints=list(dict.fromkeys(self.api.joint_id(path) for path in self.chosen_joints())))
    def paint_info(self,*_):
        try:
            report=self.session.paint_report()
            print('Layer Skin paint info\n'+json.dumps(report,indent=2,ensure_ascii=False))
            self.message('Paint info printed in the Script Editor. Active tool: '+str(report['active_context']))
            return report
        except Exception as exc:self.message(exc,True)
    def assignment_method_changed(self,*_):
        enabled=self.method.currentIndex()==2
        self.axis.setEnabled(enabled)
    @color_action
    def assign(self,*_,rebuild=False):
        method=['bone','point','axis'][self.method.currentIndex()]
        settings=dict(method=method,axis=self.axis.currentText(),max_seconds=120)
        data=dict(whole=self.assignment_scope.currentIndex()==0,settings=settings,replace_manual=not rebuild and not self.keep_paint.isChecked())
        if rebuild and method!='axis':return self.run('assign',data)
        if self._working or self._refreshing:return False
        try:
            layer=self.layer()
            if rebuild:
                ctx=self.api.context(self.target.text())
                paths={identity:path.fullPathName() for identity,path in zip(ctx['ids'],ctx['influences'])}
                if any(identity not in paths for identity in layer['joints']):raise ValueError('Layer joint membership changed. Refresh before rebuilding.')
                joints=[paths[identity] for identity in layer['joints']]
            else:joints=self.chosen_joints()
            if not self.stop_paint(keep_view=True):return False
            self._working=True
            result=self.session.edit_joints(self.target.text(),layer['id'],joints,'assign',data)
            self.refresh(layer['id'])
            if result:
                assignment=self.layer(layer['id']).get('assignment',{})
                count=assignment.get('assigned_vertices');total=assignment.get('scope_vertices')
                suffix=' · {} of {} scoped vertices assigned'.format(count,total) if count is not None and total is not None else ''
                self.message(str(result)+suffix)
            return True
        except Exception as exc:
            self.refresh();self.message(exc,True);return False
        finally:self._working=False
    def open_cleanup(self,*_):
        dialog=self._cleanup_dialog() if self._cleanup_dialog else None
        if dialog:
            try:dialog.show();dialog.raise_();dialog.activateWindow();return dialog
            except RuntimeError:pass
        dialog=self.session.helper('layer_skin_cleanup_ui').CleanupDialog(self)
        self._cleanup_dialog=weakref.ref(dialog);dialog.show();return dialog
    @color_action
    def clear_cache(self,*_):
        try:
            if not self.stop_paint(keep_view=True):return False
            self.session.helper('layer_skin_cleanup').clear_caches(self.api)
            self._weight_status=None
            self.utilities.invalidate()
            if self.session.viewing:self.session.show_preview()
            self.reference_status.setText('Memory caches cleared. Saved assignment reference, paint and masks are kept.')
            self.message('Memory caches cleared. Saved layers and skin weights are kept.');return True
        except Exception as exc:self.message(exc,True);return False
    def remove_saved_layers(self,plan):
        if self._working or self._refreshing:return None
        helper=self.session.helper('layer_skin_cleanup')
        helper.validate(self.api,plan,self.target.text())
        if not self.stop_paint():return None
        self._working=True
        try:
            result=helper.remove(self.api,plan)
            self._weight_status=None;self.session.last_stroke=None;self.session.last_error=''
            ready=self.refresh(force_browser=True)
            self.message('Saved layer data removed; current skin weights kept. Undo restores the layers. '+
                         ('Use + to start a fresh stack from current skin.' if ready else 'This mesh is outside the editor limits; cleanup still completed.'))
            return result
        finally:self._working=False
    def inspect(self,*_):
        try:self.api.inspect(self)
        except Exception as exc:self.message(exc,True)
    @color_action
    def history(self,redo):
        try:
            self.stop_paint(discard=True,keep_view=True);self.api.cmds.redo() if redo else self.api.cmds.undo();self.refresh()
        except Exception as exc:self.message(exc,True)
    def finish(self,action):
        text='Keep current weights and remove layer authoring data?' if action=='bake' else 'Restore every original captured weight and remove layer authoring data?'
        if QtWidgets.QMessageBox.question(self,'Layer Skin',text,QtWidgets.QMessageBox.Apply|QtWidgets.QMessageBox.Cancel,QtWidgets.QMessageBox.Cancel)==QtWidgets.QMessageBox.Apply:self.run(action)
