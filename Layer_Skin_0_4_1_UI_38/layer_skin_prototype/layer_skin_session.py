"""Window-owned selection, joint hierarchy and native Artisan sessions. No frame solver."""
import hashlib
import contextlib
import functools
import json
import math
import sys
import types
import importlib.util
import os

BRIDGE='_rtk_layer_skin_paint_041'
CONTEXT='rtkLayerSkinPaint041'
BASE='__base__'
NATIVE_EDIT_MESSAGE=('Skin weights changed outside Layer Skin. Maya Paint Skin Weights edits the final skinCluster, '
                     'not the selected layer. Undo the native strokes to resume layer painting, or use Cleanup > Remove saved layers '
                     'to keep the native result. Existing layer data has been kept.')


HEAT_STOPS=((0.,(.02,.05,.35)),(.25,(0.,.8,1.)),(.5,(.1,1.,.15)),(.75,(1.,.9,0.)),(1.,(1.,.05,0.)))
# Maya Artisan's color-ramp entries are R,G,B,position,interpolation.
HEAT_RAMP=','.join(str(value) for position,color in HEAT_STOPS for value in (*color,position,1))


def feedback_flags(enabled=True,display='grayscale',profile='solid'):
    """Documented built-in profile and context-local viewport feedback."""
    if profile not in ('solid','poly','gaussian'):raise ValueError('Choose Solid, Smooth or Gaussian falloff.')
    result=dict(stampProfile=profile,accopacity=False,usepressure=False,outline=True,outwhilepaint=True,tangentOutline=True,brushfeedback=True,
                colorfeedback=enabled,colorfeedbackOverride=enabled,disablelighting=enabled,useColorRamp=False,useMaxMinColor=True,
                rampMinColor=(0.,0.,0.),rampMaxColor=(1.,1.,1.),colorrangelower=0.,colorrangeupper=1.)
    if display=='heatmap':result.update(useColorRamp=True,useMaxMinColor=False,colorRamp=HEAT_RAMP)
    return result


def make_weight_view(api):
    factory=getattr(api,'make_weight_view',None)
    if factory:return factory()
    name='_rtk_layer_skin_viewport_35'
    if name not in sys.modules:
        path=os.path.join(os.path.dirname(globals().get('__file__') or make_weight_view.__code__.co_filename),'layer_skin_viewport.py')
        spec=importlib.util.spec_from_file_location(name,path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);sys.modules[name]=module
    return sys.modules[name].WeightView(api)


def authoring_module(name):
    revision=37 if name in ('layer_skin_brush_view','layer_skin_brush') else 30 if name=='layer_skin_relax' else 20
    key='_rtk_layer_skin_authoring_{}_'.format(revision)+name
    if key not in sys.modules:
        path=os.path.join(os.path.dirname(globals().get('__file__') or authoring_module.__code__.co_filename),name+'.py')
        spec=importlib.util.spec_from_file_location(key,path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);sys.modules[key]=module
    return sys.modules[key]


def protect_browser_widget(widget):
    """Native selection/navigation remain available; scene-edit gestures do not."""
    try:
        from PySide6 import QtCore,QtWidgets
    except ImportError:
        from PySide2 import QtCore,QtWidgets
    class ReadOnlyBrowser(QtCore.QObject):
        def eventFilter(self,watched,event):
            kind=event.type()
            if kind in (QtCore.QEvent.DragEnter,QtCore.QEvent.DragMove,QtCore.QEvent.Drop,QtCore.QEvent.ContextMenu):return True
            if kind in (QtCore.QEvent.KeyPress,QtCore.QEvent.ShortcutOverride) and event.key() in (QtCore.Qt.Key_Delete,QtCore.Qt.Key_Backspace,QtCore.Qt.Key_F2):
                event.accept();return True
            if kind==QtCore.QEvent.MouseButtonPress and event.button()==QtCore.Qt.MiddleButton:return True
            return False
    guard=ReadOnlyBrowser(widget)
    views=widget.findChildren(QtWidgets.QAbstractItemView)
    if isinstance(widget,QtWidgets.QAbstractItemView):views.append(widget)
    for view in views:
        view.setDragEnabled(False);view.setAcceptDrops(False);view.viewport().setAcceptDrops(False)
        view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        view.setContextMenuPolicy(QtCore.Qt.PreventContextMenu)
        view.installEventFilter(guard);view.viewport().installEventFilter(guard)
    widget.installEventFilter(guard)
    return guard


def dispatch(method,*args):
    module=sys.modules.get(BRIDGE);session=getattr(module,'session',None)
    if session is None:return '-id -1' if method=='initialize' else '' if method in ('surface','array_attribute') else 0.
    try:return getattr(session,method)(*args)
    except Exception as exc:
        session.last_error=str(exc)
        if session.stroke is not None:session.stroke['error']=str(exc)
        session.api.cmds.warning('Layer Skin paint: '+str(exc))
        return '-id -1' if method=='initialize' else '' if method in ('surface','array_attribute') else 0.


def mel_procedures():
    """Only numeric IDs/values cross per-vertex callbacks. Surface strings are escaped."""
    # A single Python expression returns a value to MEL. An import statement
    # followed by an expression can execute without returning the scalar.
    prefix="__import__('sys').modules['"+BRIDGE+"'].dispatch"
    return r'''
global proc string rtkLSInit041(string $name) {
 return python("PREFIX('initialize',\"" + encodeString($name) + "\")");
}
global proc float rtkLSGet041(int $id, int $index) {
 return python("PREFIX('get_value'," + $id + "," + $index + ")");
}
global proc rtkLSSet041(int $id, int $index, float $value) {
 python("PREFIX('set_value'," + $id + "," + $index + "," + $value + ")");
}
global proc rtkLSFinish041(int $id) { python("PREFIX('finalize'," + $id + ")"); }
global proc rtkLSBefore041() { python("PREFIX('before_stroke')"); }
global proc rtkLSAfter041() { python("PREFIX('after_stroke')"); }
global proc string rtkLSSurface041(string $name) {
 return python("PREFIX('surface',\"" + encodeString($name) + "\")");
}
global proc string rtkLSArray041(string $name) {
 return python("PREFIX('array_attribute',\"" + encodeString($name) + "\")");
}
global proc rtkLSCleanup041(string $context) { python("PREFIX('tool_cleanup')"); }
global proc rtkLSSetup041(string $context) {
 artUserPaintCtx -e -whichTool "userPaint" -ic "" -fc ""
  -gvc "" -svc "" -gsc "rtkLSSurface041"
  -gac "rtkLSArray041" -sac "" -cc "" -tcc "rtkLSCleanup041" -fullpaths true $context;
 artUserPaintCtx -e -beforeStrokeCmd "rtkLSBefore041" -afterStrokeCmd "rtkLSAfter041" $context;
 python("PREFIX('tool_setup')");
}
'''.replace('PREFIX',prefix)


def color_action(function):
    @functools.wraps(function)
    def call(self,*args,**kwargs):
        with self.color_transition():return function(self,*args,**kwargs)
    return call


class Session:
    def __init__(self,api):
        self.api=api;self.target=None;self.skin=None;self.layer=None;self.joint=None;self.mode='mask';self.readonly=True
        self.state=None;self.values=[];self.stroke=None;self.previous_tool=None;self.active=False
        self.callbacks=[];self.on_change=None;self.browsers=[];self.closed=False
        self.needs_refresh=False
        self.last_error=''
        self.joint_path=None
        self._committing=False;self.last_stroke=None
        self._view_ready=False;self._configuring_view=False
        self.on_pending=None;self.can_begin_stroke=None
        self.paint_events={}
        self.buffer=None;self._undo_chunk=False
        self.display='grayscale'
        self.viewing=False;self.preview=make_weight_view(api);self.preview_error=''
        self._stopping=False;self._saving=False
        self.brush=None;self.relax_settings=None;self.on_brush_settings=None
        self.brush_operation='replace'
        self.brush_profile='solid'
        self.context_starts=0;self.context_reuses=0;self.last_view_update=None
        self._buffer_factory=None
        self._display_gate=None
        self._editing_brush_settings=False
        self._settings_selection_deferred=False
        self._selection_handoff=False
        self._component_mode_dirty=False
        self._surface_aliases=set();self._surface_rejected=set();self._surface_parents=();self._surface_target=None
        self._state_hash=None;self._paint_cache_dirty=False;self._paint_dag=None
        self._prepared_context=None;self._prepared_meta=None;self._committed_snapshot=None
        self._preview_revision=0
        self._preview_generation=0;self._preview_queued=False
        self._preview_signature=None;self._preview_attempts=0
        self.paint_armed=False;self._resume_generation=0;self._resume_queued=False
        self._brush_values=dict(value=1.,radius=1.,opacity=1.)
        self.brush_settings_edits=0;self.brush_settings_skipped=0

    def helper(self,name):return authoring_module(name)

    @property
    def display_transition_active(self):return bool(self._display_gate and self._display_gate.depth)

    @contextlib.contextmanager
    def color_transition(self):
        if self.closed:
            yield;return
        if self._display_gate is None:
            helper=self.helper('layer_skin_feedback')
            self._display_gate=helper.DisplayGate(lambda:helper.surfaces(self.api),getattr(self.api.cmds,'warning',None))
        attempts=self._preview_attempts
        with self._display_gate.hold():
            try:yield
            finally:
                # A failed layer action can leave painting paused. Publish the
                # retained values rather than leaving a bare material frame.
                if (self._display_gate.depth==1 and self._preview_attempts==attempts
                        and self.viewing and not self.active and not self._saving and not self.closed):
                    signature=(self.target,self._preview_revision,self.effective_display())
                    if not self.preview.visible or self._preview_signature!=signature:self.show_preview()

    def paint_event(self,event):
        self.paint_events[event]=self.paint_events.get(event,0)+1

    @property
    def adjusting_brush(self):
        brush=self.brush
        return self._editing_brush_settings or bool(brush and not brush.closed and
            (getattr(brush,'radius_adjusting',False) or getattr(brush,'b_down',False)))

    def update_brush_settings(self,**values):
        """Edit scalar Artisan settings without republishing any mesh data."""
        if self.closed or not self.active:return False
        cmds=self.api.cmds
        changes={key:value for key,value in values.items()
                 if cmds.artUserPaintCtx(CONTEXT,query=True,**{key:True})!=value}
        if not changes:
            self.brush_settings_skipped+=1;return False
        # A real pending paint/Relax gesture must be saved once before settings
        # change. With no pending gesture this performs no skin or array reads.
        configuring=self._configuring_view;editing=self._editing_brush_settings
        self._configuring_view=True;self._editing_brush_settings=True
        try:
            if self.brush is not None:self.brush.settings_changed()
            self.flush_pending('brush_settings_change')
            cmds.artUserPaintCtx(CONTEXT,edit=True,**changes)
            self._brush_values.update({key:value for key,value in changes.items() if key in self._brush_values})
            self.brush_settings_edits+=1
            return True
        finally:
            self._configuring_view=configuring;self._editing_brush_settings=editing

    def snapshot(self,target):
        ctx=self.api.context(target);meta,state=self.api.metadata(ctx)
        return ctx,meta,state or self.api.core.create(ctx['weights'],ctx['count'],ctx['ids'],ctx['topology'])

    def selection(self):
        """Mesh changes only. Joint clicks do not replace the active mesh."""
        cmds=self.api.cmds;meshes=[];joints=[]
        for name in cmds.ls(selection=True,long=True,objectsOnly=True) or []:
            kind=cmds.nodeType(name)
            if kind=='joint':joints.append(name);continue
            shapes=[name] if kind=='mesh' else cmds.listRelatives(name,shapes=True,noIntermediate=True,fullPath=True) or []
            shapes=[shape for shape in shapes if cmds.nodeType(shape)=='mesh']
            if len(shapes)==1:meshes.append(shapes[0])
        return (meshes[0] if len(set(meshes))==1 else None),joints

    def listen(self,changed,scene_reset):
        if self.callbacks:return
        om=self.api.om
        try:
            def selection_changed(*args):
                if not self.closed:changed()
            def history_changed(*args):
                if not self.closed:
                    self._end_chunk()
                    self.stroke=None;self._paint_cache_dirty=True;self.needs_refresh=True;changed()
                    self._committed_snapshot=None
            def mode_changed(*args):
                if not self.closed:
                    self._component_mode_dirty=True;changed()
                    self.queue_preview()
            def tool_changed(*args):
                if self.closed or self._configuring_view:return
                if self.api.cmds.currentCtx()==CONTEXT:
                    # toolSetupCmd can be delayed until the first surface click.
                    # ToolChanged also reconnects immediately on Q -> Y.
                    if self.paint_armed and not self.active:self.tool_setup()
                elif self.active:
                    # Normal Artisan cleanup runs before the incoming tool's
                    # setup. This is a fallback for contexts which skip it.
                    dispatch('tool_cleanup')
                self.queue_preview()
            self.callbacks.append(om.MEventMessage.addEventCallback('SelectionChanged',selection_changed))
            for name in ('SelectModeChanged','SelectTypeChanged'):
                self.callbacks.append(om.MEventMessage.addEventCallback(name,mode_changed))
            self.callbacks.append(om.MEventMessage.addEventCallback('ToolChanged',tool_changed))
            for name in ('Undo','Redo'):
                self.callbacks.append(om.MEventMessage.addEventCallback(name,history_changed))
            for message in (om.MSceneMessage.kBeforeNew,om.MSceneMessage.kBeforeOpen):
                self.callbacks.append(om.MSceneMessage.addCallback(message,lambda *args:scene_reset() if not self.closed else None))
            if hasattr(om.MSceneMessage,'kMayaExiting'):
                self.callbacks.append(om.MSceneMessage.addCallback(om.MSceneMessage.kMayaExiting,lambda *args:self.maya_exit()))
            for before,after in (('kBeforeSave','kAfterSave'),('kBeforeExport','kAfterExport')):
                if hasattr(om.MSceneMessage,before) and hasattr(om.MSceneMessage,after):
                    self.callbacks.append(om.MSceneMessage.addCallback(getattr(om.MSceneMessage,before),lambda *args:self.before_file_io()))
                    self.callbacks.append(om.MSceneMessage.addCallback(getattr(om.MSceneMessage,after),lambda *args:self.after_file_io()))
        except Exception:
            self.unlisten();raise

    def unlisten(self):
        errors=[]
        while self.callbacks:
            identity=self.callbacks.pop()
            try:self.api.om.MMessage.removeCallback(identity)
            except RuntimeError as exc:errors.append(str(exc))
        if errors:self.api.cmds.warning('Layer Skin listener cleanup: '+'; '.join(errors))

    def layer_values(self,state,layer_id,joint,mode):
        n=state['vertex_count'];k=len(state['influences'])
        if layer_id==BASE:
            if mode=='mask':return [1.]*n
            if joint not in state['influences']:return [0.]*n
            column=state['influences'].index(joint)
            return state['base'][column:n*k:k]
        index=next((i for i,row in enumerate(state['layers']) if row['id']==layer_id),None)
        if index is None:raise ValueError('Select a layer first.')
        layer=state['layers'][index]
        if mode=='mask':
            values=[1.]*n
            for key,val in layer['mask'].items():
                values[int(key)]=val
            return values
        if joint not in state['influences']:return [0.]*n
        column=state['influences'].index(joint)
        values=[0.]*n
        for source in (layer.get('generated') or {},layer['samples']):
            for key,sample in source.items():
                values[int(key)]=sample['weights'][column]*sample['coverage']
        return values

    def values_for_view(self,ctx,meta,state,layer,joint,mode,readonly,joint_path):
        """Validate and stage the next view before replacing live callback state."""
        if not readonly and (not meta or layer==BASE):raise ValueError('Add an editable layer before painting. Base is preserved.')
        if mode=='weights' and not readonly and joint in next((row.get('influence_locks',()) for row in state['layers'] if row['id']==layer),()):
            raise ValueError('This joint is locked in the selected layer. Unlock its padlock to paint.')
        if mode in ('weights','skin'):
            if joint is None:raise ValueError('Choose a joint in the hierarchy to paint.')
            if joint not in state['influences']:
                if not joint_path or self.api.cmds.nodeType(joint_path)!='joint' or self.api.joint_id(joint_path)!=joint:
                    raise ValueError('The chosen joint is missing. Choose it again in the hierarchy.')
        if mode=='skin':return ctx['weights'][ctx['ids'].index(joint)::len(ctx['ids'])] if joint in ctx['ids'] else [0.]*ctx['count']
        return self.layer_values(state,layer,joint,mode)

    def _hash_for_state(self,state,readonly=False,ctx=None):
        if state is self.state and self._state_hash is not None and not self._paint_cache_dirty:return self._state_hash
        # Viewing a different readonly column must not compress the stack.
        # Editable views stage the command's canonical guard once, not per dab.
        if readonly:return None
        guard=getattr(self.api,'state_hash',None)
        if not callable(guard):
            owner=getattr(self.api,'_layer_skin_command_owner',None)
            guard=owner.get('state_hash') if isinstance(owner,dict) else None
        if callable(guard) and ctx is not None:return guard(ctx,state)
        return hashlib.sha256(self.api.core.encode(state).encode()).hexdigest()

    def prepare(self,snapshot=None):
        ctx,meta,state=self.snapshot(self.target) if snapshot is None else snapshot
        values=self.values_for_view(ctx,meta,state,self.layer,self.joint,self.mode,self.readonly,self.joint_path)
        # Hash the canonical, influence-remapped state. raw_metadata can encode
        # an older influence order and is not the command's expected-state key.
        state_hash=self._hash_for_state(state,self.readonly,ctx)
        self._cache_surface(ctx['shape'])
        self.values=values
        self.state=state
        self._state_hash=state_hash;self._paint_cache_dirty=False
        self._paint_dag=ctx.get('dag')
        self._prepared_context=ctx;self._prepared_meta=meta;self._committed_snapshot=None
        self._preview_revision+=1
        self.target=ctx['shape'];self.skin=ctx['skin'];self.mesh_uuid=ctx['uuid']
        self._view_ready=True
        self._write_buffer()
        return ctx,state

    def reuse_context(self,target,layer,joint,mode,readonly,joint_path,operation,flags,radius,opacity):
        """Retarget the existing native array without exposing a tool/default frame."""
        cmds=self.api.cmds
        if not (self.api.VERSION=='0.4.1' and self._buffer_factory==self.api.make_paint_buffer
                and self.active and self._view_ready and self.buffer is not None and self.buffer.owner is self
                and cmds.currentCtx()==CONTEXT and cmds.artUserPaintCtx(CONTEXT,exists=True)):
            return False
        try:self.buffer.attribute()
        except RuntimeError:return False
        if cmds.artUserPaintCtx(CONTEXT,query=True,whichTool=True)!='userPaint':return False
        # A viewport/component pick may have removed Artisan's paint surface.
        # Explicit Paint must still restore the loaded object in that case.
        selected=cmds.ls(selection=True,long=True,objectsOnly=True) or []
        component_mode=cmds.selectMode(query=True,component=True)
        hilited=(cmds.ls(hilite=True,long=True) or []) if component_mode else []
        if component_mode:
            selected+=hilited
            if not any(self.surface(node)==self.target for node in selected):return False
        elif len(selected)!=1 or self.surface(selected[0])!=self.target:return False
        ctx,meta,state=self.snapshot(target)
        if (ctx['shape'],ctx['skin'],ctx['uuid'],ctx['count'])!=(self.target,self.skin,self.mesh_uuid,len(self.values)):
            return False
        values=self.values_for_view(ctx,meta,state,layer,joint,mode,readonly,joint_path)
        if not readonly and not self.api.same(ctx['weights'],self.api.core.composite(state),2e-6):
            self.last_error=NATIVE_EDIT_MESSAGE;raise ValueError(NATIVE_EDIT_MESSAGE)
        requested=dict(flags,radius=float(radius),opacity=0. if readonly else float(opacity),
                       stampProfile=self.brush_profile,accopacity=False,usepressure=False)
        native={flag:cmds.artUserPaintCtx(CONTEXT,query=True,**{flag:True}) for flag in requested}
        changes={flag:value for flag,value in requested.items() if value!=native[flag]}
        changed=values!=self.values or self.buffer.read()!=values
        display_changed=self.effective_display()!=('grayscale' if mode=='mask' else self.display)
        state_hash=self._hash_for_state(state,readonly,ctx)
        fields=('target','skin','mesh_uuid','layer','joint','mode','readonly','joint_path','brush_operation','state','values','last_error','_state_hash','_paint_cache_dirty','_paint_dag','_prepared_context','_prepared_meta','_committed_snapshot')
        previous={field:getattr(self,field) for field in fields}
        configuring=self._configuring_view;self._configuring_view=True
        try:
            self.target=ctx['shape'];self.skin=ctx['skin'];self.mesh_uuid=ctx['uuid']
            self.layer=layer;self.joint=joint;self.mode=mode;self.readonly=readonly;self.joint_path=joint_path
            self.brush_operation=operation;self.state=state;self.values=values
            self._state_hash=state_hash;self._paint_cache_dirty=False
            self._paint_dag=ctx.get('dag')
            self._prepared_context=ctx;self._prepared_meta=meta;self._committed_snapshot=None
            self._preview_revision+=1
            if component_mode and self._surface_parents and self._surface_parents[0] not in hilited:
                cmds.hilite(self._surface_parents[0],replace=False)
            if component_mode and self._surface_parents:self._bind_surface(self._surface_parents[0])
            if changed:self._write_buffer()
            if changes:cmds.artUserPaintCtx(CONTEXT,edit=True,**changes)
            if changed or display_changed or not cmds.artUserPaintCtx(CONTEXT,query=True,colorfeedback=True):self.reload_feedback()
            self.last_error='';self.viewing=True;self.context_reuses+=1
            self.paint_armed=True;self._brush_values=dict(value=float(flags['value']),radius=float(radius),opacity=float(opacity))
            self.last_view_update='in_place' if changed or display_changed else 'already_current'
            return True
        except Exception as exc:
            for field,value in previous.items():setattr(self,field,value)
            try:
                self._write_buffer()
                restore={flag:value for flag,value in native.items() if value is not None}
                if restore:cmds.artUserPaintCtx(CONTEXT,edit=True,**restore)
                self.reload_feedback()
            except Exception as rollback:
                self.last_error='{}; feedback restore failed: {}'.format(exc,rollback)
                raise RuntimeError(self.last_error) from exc
            self.last_error=str(exc);raise
        finally:self._configuring_view=configuring

    @color_action
    def start(self,target,layer,joint=None,mode='mask',readonly=False,value=1.,radius=1.,opacity=1.,joint_path=None,operation='replace'):
        if self.closed:raise ValueError('This Layer Skin window is closed.')
        other=getattr(sys.modules.get(BRIDGE),'session',None)
        if other is not None and other is not self and other.active:raise ValueError('Stop the other Layer Skin paint session first.')
        if other is not None and other is not self:other.flush_pending('another_view')
        if mode not in ('mask','weights','skin'):raise ValueError('Unknown paint mode.')
        flags=self.helper('layer_skin_operations').brush_flags(operation,value)
        if mode=='skin' and not readonly:raise ValueError('Final skin weights are a read-only view. Use Weights and Paint to edit the selected layer.')
        self.flush_pending('view_change')
        if self.reuse_context(target,layer,joint,mode,readonly,joint_path,operation,flags,radius,opacity):return
        self.stop()
        self.target=target;self.layer=layer;self.joint=joint;self.mode=mode;self.readonly=readonly
        self.brush_operation=operation
        self.joint_path=joint_path
        self.last_error='';ctx,state=self.prepare();cmds=self.api.cmds
        if not readonly and not self.api.same(ctx['weights'],self.api.core.composite(state),2e-6):
            # A native brush does not author our layer metadata. Refuse before
            # selecting a tool or accepting samples, rather than on first write.
            self.last_error=NATIVE_EDIT_MESSAGE
            self.stop()
            raise ValueError(NATIVE_EDIT_MESSAGE)
        bridge=sys.modules.get(BRIDGE) or types.ModuleType(BRIDGE)
        bridge.session=self;bridge.dispatch=dispatch;sys.modules[BRIDGE]=bridge
        self._configuring_view=True
        try:
            self.buffer=self.api.make_paint_buffer(self.target)
            self._buffer_factory=self.api.make_paint_buffer
            self.buffer.owner=self
            self._write_buffer()
            self.api.mel.eval(mel_procedures())
            # Verify actual MEL return values before changing the current tool.
            surface=self.api.mel.eval('rtkLSSurface041('+json.dumps(self.target,ensure_ascii=False)+')')
            if surface!=self.target:raise RuntimeError('The paint callback did not resolve the loaded mesh. Open Paint info for details.')
            sample=self.api.mel.eval('rtkLSGet041(1,0)')
            if sample is None or not math.isfinite(float(sample)) or abs(float(sample)-self.values[0])>1e-6:
                raise RuntimeError('The paint callback did not return a vertex value. Open Paint info for details.')
            attribute=self.api.mel.eval('rtkLSArray041('+json.dumps(self.target,ensure_ascii=False)+')')
            if attribute!=self.buffer.attribute():raise RuntimeError('Maya did not resolve the native vertex array. Open Paint info for details.')
            parents=cmds.listRelatives(self.target,parent=True,fullPath=True) or []
            if len(parents)!=1:raise ValueError('The paint mesh needs one transform parent.')
            if not cmds.artUserPaintCtx(CONTEXT,exists=True):cmds.artUserPaintCtx(CONTEXT,whichTool='userPaint')
            cmds.artUserPaintCtx(CONTEXT,edit=True,whichTool='userPaint',toolSetupCmd='rtkLSSetup041',
                initializeCmd='',finalizeCmd='',
                getValueCommand='',setValueCommand='',getSurfaceCommand='rtkLSSurface041',
                beforeStrokeCmd='rtkLSBefore041',afterStrokeCmd='rtkLSAfter041',
                getArrayAttrCommand='rtkLSArray041',setArrayValueCommand='',chunkCommand='',toolCleanupCmd='rtkLSCleanup041',fullpaths=True,
                radius=float(radius),opacity=0. if readonly else float(opacity),paintmode='screen',**flags,
                pickColor=False,pickValue=False,selectclonesource=False,projective=False,
                interactiveUpdate=True,**feedback_flags(False,self.effective_display(),self.brush_profile))
            previous=cmds.currentCtx();self.previous_tool=previous if previous!=CONTEXT else 'selectSuperContext'
            self.active=True;self.paint_armed=True
            self._brush_values=dict(value=float(flags['value']),radius=float(radius),opacity=float(opacity))
            # Keep a component selection intact. Hiliting supplies Artisan's
            # surface without replacing the user's selected vertices/edges.
            if cmds.selectMode(query=True,component=True):
                cmds.hilite(parents[0],replace=False);self._bind_surface(parents[0])
            else:cmds.select(parents[0],replace=True)
            cmds.setToolTo(CONTEXT)
            if cmds.currentCtx()!=CONTEXT:raise RuntimeError('Maya did not activate the Layer Skin brush. Click Paint again; open Paint info if it persists.')
            actual=cmds.artUserPaintCtx(CONTEXT,query=True,whichTool=True)
            if actual!='userPaint':raise RuntimeError('Maya activated Artisan tool type {!r}; Layer Skin requires userPaint. Open Paint info for details.'.format(actual))
            # Native tool preferences can restore another operation on setToolTo.
            # Apply the chosen group again once activation has completed.
            cmds.artUserPaintCtx(CONTEXT,edit=True,**flags)
            self.reload_feedback()
            self.viewing=True
            factory=getattr(self.api,'make_brush_controller',None)
            self.brush=factory(self) if factory else authoring_module('layer_skin_brush_view').attach(self)
            self.context_starts+=1;self.last_view_update='started'
        except Exception as exc:
            self.last_error=str(exc)
            self.stop();raise
        finally:self._configuring_view=False

    def reload_feedback(self):
        """Publish feedback while keeping the existing native colors enabled."""
        configuring=self._configuring_view;self._configuring_view=True
        try:
            self.api.cmds.artUserPaintCtx(CONTEXT,edit=True,**feedback_flags(display=self.effective_display(),profile=self.brush_profile))
        finally:self._configuring_view=configuring

    @color_action
    def set_brush_profile(self,profile):
        if profile not in ('solid','poly','gaussian'):raise ValueError('Choose Solid, Smooth or Gaussian falloff.')
        if profile==self.brush_profile:return
        self.flush_pending('falloff_change')
        previous=self.brush_profile;configuring=self._configuring_view;self._configuring_view=True
        try:
            if self.active:self.api.cmds.artUserPaintCtx(CONTEXT,edit=True,stampProfile=profile,accopacity=False,usepressure=False)
            self.brush_profile=profile
        except Exception:
            if self.active:self.api.cmds.artUserPaintCtx(CONTEXT,edit=True,stampProfile=previous,accopacity=False,usepressure=False)
            raise
        finally:self._configuring_view=configuring

    def effective_display(self):return 'grayscale' if self.mode=='mask' else self.display

    @color_action
    def set_display(self,display):
        if display not in ('heatmap','grayscale'):raise ValueError('Unknown weight display.')
        self.flush_pending('display_change')
        self.display=display
        if self.active:self.reload_feedback()
        elif self.viewing:self.show_preview()

    @color_action
    def show_preview(self,force=False,allow_active=False):
        if not self.viewing or (self.active and not allow_active) or self._saving or self.closed:return
        self._preview_attempts+=1
        try:
            if hasattr(self.preview,'show_versioned'):
                self.preview.show_versioned(self.target,self.values,self.effective_display(),self._preview_revision,force=force)
            else:self.preview.show(self.target,self.values,self.effective_display(),force=force)
            self.preview_error=''
            self._preview_signature=(self.target,self._preview_revision,self.effective_display())
        except Exception as exc:
            error=str(exc)
            if error!=self.preview_error:self.api.cmds.warning('Layer Skin weight display: '+error)
            self.preview_error=error

    def queue_preview(self):
        """Publish after Maya finishes incoming-tool/component setup, once."""
        if self.closed or self.active or not self.viewing or self._saving or self._preview_queued:return
        generation=self._preview_generation;self._preview_queued=True
        def publish():
            if generation!=self._preview_generation:return
            self._preview_queued=False
            if self.closed or self.active or not self.viewing or self._saving:return
            self.show_preview()
            if self.on_change:self.on_change()
        self.helper('layer_skin_brush_view').QtCore.QTimer.singleShot(0,publish)

    @color_action
    def view(self,target,layer,joint=None,mode='weights',joint_path=None,snapshot=None):
        """Select the displayed data without changing Maya's tool or selection."""
        self.target=target;self.layer=layer;self.joint=joint;self.joint_path=joint_path;self.mode=mode
        self.readonly=mode=='skin' or layer==BASE
        self.prepare(snapshot);self._view_ready=False;self.viewing=True;self.show_preview()

    def before_file_io(self):
        if self.closed:return
        self.flush_pending('file_save');self._saving=True;self.preview.clear()

    def after_file_io(self):
        if self.closed:return
        self._saving=False;self.show_preview(force=True)

    def array_attribute(self,name):
        self.paint_event('array_attribute')
        if self.buffer is None or self.buffer.owner is not self or not self._view_ready or not self.surface(name):return ''
        return self.buffer.attribute()

    def _write_buffer(self):
        if self.buffer is None or self.buffer.owner is not self:return
        configuring=self._configuring_view;self._configuring_view=True
        try:self.buffer.write(self.values)
        finally:self._configuring_view=configuring

    def _end_chunk(self):
        if self._undo_chunk:
            self._undo_chunk=False
            self.api.cmds.undoInfo(closeChunk=True)

    def _capture_array(self):
        if self.buffer is None or self.buffer.owner is not self or self.stroke is None or self.readonly:return
        self.paint_event('array_read')
        values=self.buffer.read();baseline=self.stroke['baseline']
        if len(values)!=len(baseline):raise ValueError('The native paint array has a different vertex count. Click Paint again.')
        if any(not math.isfinite(value) for value in values):raise ValueError('The native paint array contains a non-finite weight.')
        scope=self.stroke.get('vertices');restore=False;changed={}
        for i,value in enumerate(values):
            if abs(value-baseline[i])<=1e-8:continue
            if scope is not None and i not in scope:values[i]=baseline[i];restore=True
            else:changed[str(i)]=self.api.core.unit(value)
        if restore:self.buffer.write(values)
        if self.mode=='weights' and changed:
            clamped=self.api.core.influence_rules().clamp_values(self.state,self.layer,self.joint,changed)
            if clamped!=changed:
                for key,value in clamped.items():values[int(key)]=value
                self.buffer.write(values)
            changed=clamped
        for key in self.stroke.get('array_keys',()):self.stroke['values'].pop(key,None)
        self.stroke['values'].update(changed)
        self.stroke['array_keys']=set(changed)
        if changed:self.paint_event('accepted_array')

    def _cache_surface(self,target):
        if target==self._surface_target:return
        cmds=self.api.cmds
        parents=tuple(cmds.listRelatives(target,parent=True,fullPath=True) or [])
        aliases={target,*parents}
        for path in tuple(aliases):
            short=path.rsplit('|',1)[-1]
            resolved=cmds.ls(short,long=True,objectsOnly=True) or []
            # Never map an ambiguous short name onto the loaded mesh.
            if len(resolved)==1 and resolved[0]==path:aliases.add(short)
        self._surface_target=target;self._surface_parents=parents
        self._surface_aliases=aliases;self._surface_rejected=set()

    def surface(self,name):
        if not name:return ''
        node=name.split('.',1)[0]
        if node==self.target or node in self._surface_aliases:return self.target
        if node in self._surface_rejected:return ''
        # Resolve an unfamiliar callback spelling once, outside the known-alias
        # path; repeated foreign surfaces are also cached until retargeting.
        cmds=self.api.cmds;resolved=cmds.ls(node,long=True,objectsOnly=True) or []
        if len(resolved)==1:
            names=[resolved[0]]+(cmds.listRelatives(resolved[0],shapes=True,noIntermediate=True,fullPath=True) or [])
            if self.target in names:self._surface_aliases.add(node);return self.target
        self._surface_rejected.add(node)
        return ''

    def paint_report(self):
        """Read-only diagnostics: no skin reads, stroke start, selection or writes."""
        cmds=self.api.cmds
        current=cmds.currentCtx()
        report=dict(package_version=self.api.VERSION,active_context=current,
            layer_skin_context=CONTEXT,active=self.active and current==CONTEXT,readonly=self.readonly,
            mode=self.mode,mesh=self.target,layer=self.layer,joint=self.joint,
            vertex_values=len(self.values),last_callback_error=self.last_error or None,
            last_stroke=dict(self.last_stroke) if self.last_stroke else None,
            pending_vertices=len(self.stroke['values']) if self.stroke else 0,committing=self._committing,
            view_ready=self._view_ready,configuring_view=self._configuring_view,
            callback_counts=dict(self.paint_events),
            feedback_backend='native doubleArray',
            paint_array=self.buffer.attribute() if self.buffer is not None else None,
            paint_array_geometry=self.buffer.geometry_sources() if self.buffer is not None else [],
            selection=cmds.ls(selection=True,long=True) or [])
        report['authoring_revision']='ui35_viewport_constructor'
        report['paint_armed']=self.paint_armed;report['resume_queued']=self._resume_queued
        report['paint_cache']=dict(ready=self._state_hash is not None,dirty=self._paint_cache_dirty,surface_aliases=len(self._surface_aliases))
        report['brush_settings_updates']=dict(adjusting=self.adjusting_brush,edits=self.brush_settings_edits,
                                             unchanged_skipped=self.brush_settings_skipped)
        layer=next((row for row in (self.state or {}).get('layers',()) if row['id']==self.layer),{})
        report['influence_locks']=layer.get('influence_locks',[])
        report['redistribution']=layer.get('redistribution','proportional')
        report['brush_falloff']=self.brush_profile
        report['native_view_updates']=dict(starts=self.context_starts,reuses=self.context_reuses,last=self.last_view_update,
                                          feedback_refresh='enable_only')
        report['brush_operation']=self.brush_operation
        report['color_handoff']=self._display_gate.report() if self._display_gate else None
        report['viewing']=self.viewing;report['persistent_display']=self.preview.report()
        report['persistent_display_error']=self.preview_error or None
        report['relax_brush']=self.brush.report() if self.brush is not None else None
        report['weight_display']=self.display;report['effective_display']=self.effective_display()
        errors={}
        if self.skin and hasattr(cmds,'getAttr'):
            report['skinCluster']=self.skin;report['skin_settings']={}
            for attribute in ('normalizeWeights','maintainMaxInfluences','maxInfluences','skinningMethod'):
                try:report['skin_settings'][attribute]=cmds.getAttr(self.skin+'.'+attribute)
                except Exception as exc:errors['skin.'+attribute]=str(exc)
        if hasattr(self.api,'plugin_details'):
            try:report['registered_plugin']=self.api.plugin_details()
            except Exception as exc:errors['registered_plugin']=str(exc)
        try:report['object_selection_mode']=cmds.selectMode(query=True,object=True)
        except Exception as exc:errors['object_selection_mode']=str(exc)
        report['selected_surfaces']=[]
        for name in report['selection']:
            try:
                surface=self.surface(name)
                if surface and surface not in report['selected_surfaces']:report['selected_surfaces'].append(surface)
            except Exception as exc:errors['surface:'+name]=str(exc)
        if cmds.artUserPaintCtx(CONTEXT,exists=True):
            context={}
            for flag in ('whichTool','paintNodeArray','toolSetupCmd','initializeCmd','finalizeCmd','beforeStrokeCmd','afterStrokeCmd','getValueCommand','setValueCommand',
                         'getSurfaceCommand','getArrayAttrCommand','setArrayValueCommand','paintoperationtype','stampProfile','profileShapeFile',
                         'outline','brushfeedback','tangentOutline','colorfeedback','colorfeedbackOverride','disablelighting','radius','worldRadius','screenRadius','opacity',
                         'useColorRamp','useMaxMinColor','colorRamp','accopacity','usepressure','value','selectedattroper'):
                try:context[flag]=cmds.artUserPaintCtx(CONTEXT,query=True,**{flag:True})
                except Exception as exc:errors[flag]=str(exc)
            report['context_settings']=context
        if self.values:report['display_values']=dict(min=min(self.values),max=max(self.values),mean=sum(self.values)/len(self.values))
        report['display_source']='skinCluster weights (read-only)' if self.mode=='skin' else 'selected layer '+self.mode
        if errors:report['query_errors']=errors
        return report

    def initialize(self,name):
        self.paint_event('initialize')
        if not self._view_ready or not self.surface(name):return '-id -1'
        # Artisan can request surface data again while refreshing feedback.
        # This must not replace the pending stroke or its stale-data guard.
        # Display setup can request an ID before setToolTo activates the brush.
        # Returning -1 there binds all feedback reads to the zero-value path.
        if self.active and not self.readonly and not self._configuring_view and not self.adjusting_brush and self.stroke is None and not self._committing and not (self.brush and self.brush.drawing):self._begin_stroke()
        return '-id 1'

    def _begin_stroke(self):
        if not self._view_ready or self.state is None or self._paint_cache_dirty:self.prepare()
        if self._state_hash is None:self._state_hash=hashlib.sha256(self.api.core.encode(self.state).encode()).hexdigest()
        try:vertices=self.paint_scope()
        except Exception as exc:
            # Artisan can still deliver array edits after a MEL callback error.
            # Keep a rejected header so release restores its working buffer
            # rather than letting those edits leak into the next valid stroke.
            self.stroke=dict(values={},error=str(exc),expected=self._state_hash,vertices=frozenset(),
                scope=(self.target,self.layer,self.joint,self.mode),baseline=self.values,
                operation=self.brush_operation,profile=self.brush_profile)
            raise
        if self.buffer is not None and not self.readonly and not self._undo_chunk:
            import uuid
            self._undo_chunk='LayerSkinPaint_'+uuid.uuid4().hex
            try:self.api.cmds.undoInfo(openChunk=True,chunkName=self._undo_chunk)
            except Exception:self._undo_chunk=False;raise
        self.stroke=dict(values={},error=None,expected=self._state_hash,
                         scope=(self.target,self.layer,self.joint,self.mode),vertices=vertices,baseline=self.values,operation=self.brush_operation,profile=self.brush_profile)

    def paint_scope(self,ctx=None):
        """Snapshot selected vertices/edge endpoints once per genuine stroke."""
        if not self.api.cmds.selectMode(query=True,component=True):return None
        provider=getattr(self.api,'paint_scope',None)
        if provider is not None:return provider()
        dag=(ctx or {}).get('dag',self._paint_dag)
        # Recording adapters can omit DAG handles; Maya contexts always supply
        # one. Scope extraction itself uses selection only, never skin weights.
        if dag is None:return None
        vertices=self.helper('layer_skin_relax').selected_scope(dict(dag=dag),self.api.om,all_if_empty=False)
        return frozenset(vertices) if vertices else None

    def before_stroke(self):
        self.paint_event('before_stroke')
        if self.adjusting_brush:
            self.paint_event('ignored_settings_before_stroke');return
        if self.brush and self.brush.drawing:return
        if self.active and not self.readonly and self._view_ready and not self._configuring_view and not self._committing:
            if self.stroke is None:self._begin_stroke()
            if self.buffer is not None and self.on_pending:self.on_pending()

    def after_stroke(self):
        self.paint_event('after_stroke')
        if self.adjusting_brush:
            self.paint_event('ignored_settings_after_stroke');return
        if self.brush and self.brush.drawing:return
        if not self.active or self._configuring_view or self._committing:return
        if self.readonly:
            self._write_buffer()
            return
        # Array mode has no per-surface finalizer. The after-stroke hook
        # captures native data; the Qt release timer is its idempotent fallback.
        self.finalize(1)

    def get_value(self,identity,index):
        if identity!=1 or not 0<=index<len(self.values):return 0.
        return self.stroke['values'].get(str(index),self.values[index]) if (self.stroke and self.stroke['values']) else self.values[index]

    def set_value(self,identity,index,value):
        self.paint_event('set_value')
        if self.adjusting_brush:
            self.paint_event('ignored_settings_set_value');return
        if self.brush and self.brush.drawing:return
        if identity!=1 or not self.active or not self._view_ready or self.readonly or self._committing or self._configuring_view:
            self.paint_event('ignored_set_value');return
        if self.stroke is None:
            # Some native sequences deliver samples without another surface
            # initializer. The UI permits this only while the brush is held;
            # late callbacks during Undo or display setup stay read-only.
            if self.can_begin_stroke is not None and not self.can_begin_stroke():
                self.paint_event('ignored_unarmed_set_value');return
            self._begin_stroke()
        if self.stroke['error']:return
        if not 0<=index<len(self.values):raise ValueError('Paint vertex is outside the loaded mesh.')
        if self.stroke.get('vertices') is not None and index not in self.stroke['vertices']:return
        value=self.api.core.unit(value)
        if self.mode=='weights':value=self.api.core.influence_rules().clamp_values(self.state,self.layer,self.joint,{str(index):value})[str(index)]
        first=not self.stroke['values'];self.stroke['values'][str(index)]=value
        self.paint_event('accepted_sample')
        if first and self.on_pending:self.on_pending()

    def flush_pending(self,reason='action_change'):
        if self.closed:return
        if self.brush and self.brush.drawing:self.brush.finish(reason)
        if self.stroke is not None and not self.readonly and not self._committing and (self.buffer is not None or self.stroke['values']):self.finalize(1,reason)
        elif self.stroke is not None:
            self.stroke=None;self._end_chunk()

    def finalize(self,identity,reason='native_finalize'):
        self.paint_event('finalize')
        if self.adjusting_brush and reason=='native_finalize':
            self.paint_event('ignored_settings_finalize');return
        if identity!=1 or self._committing or self.stroke is None:return
        stroke=self.stroke
        if self.readonly:self.stroke=None;self._end_chunk();return
        report=dict(status='unchanged',mesh=self.target,layer=self.layer,joint=self.joint,mode=self.mode,
                    submitted_vertices=len(stroke['values']),changed_vertices=0,layer_values_verified=False,commit_reason=reason,
                    joint_path=self.joint_path,operation=stroke.get('operation','replace'),falloff=stroke.get('profile',self.brush_profile))
        committed=False;self._committing=True
        try:
            self._capture_array()
            report['submitted_vertices']=len(stroke['values'])
            if stroke['error']:raise RuntimeError(stroke['error'])
            if stroke['scope']!=(self.target,self.layer,self.joint,self.mode):raise RuntimeError('The paint view changed before its pending stroke could be saved.')
            changed={key:value for key,value in stroke['values'].items() if value!=stroke['baseline'][int(key)]}
            report['changed_vertices']=len(changed)
            if not changed:return
            data=dict(target=self.target,layer=self.layer,joint=self.joint,mode=self.mode,values=changed,expected=stroke['expected'])
            # Keep the pending values available to feedback reads throughout
            # the native command, including mesh evaluation and binding.
            receipt=None;scope=None
            if self.mode=='weights' and self.joint not in self.state['influences']:
                self.edit_joints(self.target,self.layer,[self.joint_path],'paint',data)
            else:
                provider=getattr(self.api,'commit_paint',None)
                if provider is not None and self._prepared_meta:
                    scope=dict(shape=self.target,skin=self.skin,uuid=self.mesh_uuid,count=len(self.values),
                        ids=list(self.state['influences']),topology=self.state['topology'],meta=self._prepared_meta,
                        layer=self.layer,joint=self.joint,mode=self.mode)
                    receipt=provider(data,scope)
                else:self.api.cmds.rtkLayerSkin(action='paint',data=json.dumps(data))
            committed=True
            if not self._accept_paint_receipt(receipt,scope,changed):self.prepare()
            if any(abs(self.values[int(key)]-value)>2e-6 for key,value in changed.items()):
                raise RuntimeError('The paint command returned but saved layer values do not match the stroke. Open Paint info; the command remains in Undo.')
            report.update(status='saved',layer_values_verified=True);self.last_error=''
        except Exception as exc:
            self.last_error=str(exc)
            report.update(status='verification_failed' if committed else 'rejected',error=str(exc))
            # A rejected command rolls back its own scene edits. Discard only
            # its preview and reload the unchanged layer for the next gesture.
            try:self.prepare()
            except Exception as refresh_error:report['refresh_error']=str(refresh_error)
            raise
        finally:
            self.stroke=None;self._committing=False;self.last_stroke=report
            self._end_chunk()
            if report['status']!='unchanged':
                self.needs_refresh=True
                if self.on_change:self.on_change()

    def receipt_scope(self):
        if not self._prepared_meta or self.state is None:return None
        return dict(shape=self.target,skin=self.skin,uuid=self.mesh_uuid,count=len(self.values),
            ids=list(self.state['influences']),topology=self.state['topology'],meta=self._prepared_meta,
            layer=self.layer,joint=self.joint,mode=self.mode)

    def _accept_paint_receipt(self,receipt,scope,changed):
        if not isinstance(receipt,dict) or receipt.get('scope')!=scope or self._prepared_context is None:return False
        if (self.target,self.skin,self.mesh_uuid,self.layer,self.joint,self.mode)!=(
                scope['shape'],scope['skin'],scope['uuid'],scope['layer'],scope['joint'],scope['mode']):return False
        state=receipt.get('state')
        if not isinstance(state,dict) or any(key not in receipt for key in ('state_hash','weights','raw_metadata')):return False
        if state.get('influences')!=scope['ids'] or state.get('vertex_count')!=scope['count'] or state.get('topology')!=scope['topology']:return False
        layer=next((row for row in state['layers'] if row['id']==self.layer),None)
        if layer is None:return False
        column=state['influences'].index(self.joint) if self.mode=='weights' else None
        delta={}
        for key in changed:
            if self.mode=='mask':delta[key]=layer['mask'].get(key,1.)
            else:
                sample=layer['samples'].get(key) or layer.get('generated',{}).get(key)
                delta[key]=sample['weights'][column]*sample['coverage'] if sample else 0.
        if any(abs(delta[key]-value)>2e-6 for key,value in changed.items()):return False
        self.state=state;self._state_hash=receipt['state_hash'];self._paint_cache_dirty=False
        self._preview_revision+=1
        for key,value in delta.items():self.values[int(key)]=value
        self._prepared_context=dict(self._prepared_context,weights=receipt['weights'],raw_metadata=receipt['raw_metadata'])
        self._committed_snapshot=(self._prepared_context,self._prepared_meta,self.state)
        self.paint_event('verified_commit_receipt')
        return True

    def take_committed_snapshot(self):
        snapshot=self._committed_snapshot;self._committed_snapshot=None
        if (self.closed or not self.active or self._paint_cache_dirty or self.api.cmds.currentCtx()!=CONTEXT):return None
        return snapshot

    @color_action
    def refresh_view(self,snapshot=None,force=False):
        if (snapshot is not None and not force and self.active and snapshot[0] is self._prepared_context
                and snapshot[2] is self.state and not self._paint_cache_dirty):return
        if (self.active or self.viewing) and self.stroke is None and not self._committing and not (self.brush and self.brush.drawing):
            previous=self.values
            self.prepare(snapshot)
            # A successful stroke already updated the buffer. Reconfiguring
            # the whole context here can restart its surface feedback.
            if self.active:
                if force or self.values!=previous:self.reload_feedback()
            else:
                self._view_ready=False;self.show_preview(force=force)

    @color_action
    def pause_for_components(self):
        """Release Artisan's mouse handling while retaining saved weight colors."""
        if self.closed or not self.active or self._configuring_view or self._selection_handoff:return False
        self._selection_handoff=True
        try:
            if self.on_brush_settings:self.on_brush_settings()
            self.flush_pending('component_selection')
            # Publish the same colors before Artisan relinquishes feedback.
            # Component selection then has a ready display on its first frame.
            self.show_preview(allow_active=True)
            cmds=self.api.cmds
            if cmds.currentCtx()==CONTEXT:cmds.setToolTo('selectSuperContext')
            # Maya normally calls toolCleanupCmd during setToolTo. Keep the
            # same lifecycle for contexts/hosts that omit that callback.
            if self.active:self.tool_cleanup()
            return True
        finally:
            self._selection_handoff=False
            if self.on_change:self.on_change()

    def keep_paint_in_component_mode(self):
        """Keep the loaded surface paintable without taking over another tool."""
        if not self._component_mode_dirty:return
        self._component_mode_dirty=False
        if self.closed or not self.active or self._configuring_view:return
        cmds=self.api.cmds
        if cmds.currentCtx()!=CONTEXT:return
        self.flush_pending('component_mode')
        configuring=self._configuring_view;self._configuring_view=True
        try:
            parent=self._surface_parents[0] if self._surface_parents else self.target
            if cmds.selectMode(query=True,component=True):
                hilited=cmds.ls(hilite=True,long=True) or []
                if parent not in hilited and self.target not in hilited:cmds.hilite(parent,replace=False)
                self._bind_surface(parent)
            elif (cmds.ls(selection=True,long=True) or [])!=[parent]:cmds.select(parent,replace=True)
            self.reload_feedback()
        finally:self._configuring_view=configuring

    def _bind_surface(self,parent):
        """Retain components and add the object-level Artisan surface atomically."""
        cmds=self.api.cmds;selected=cmds.ls(selection=True,long=True) or []
        if parent in selected or self.target in selected:return
        om=self.api.om
        if hasattr(om,'MSelectionList') and hasattr(om,'MGlobal'):
            merged=om.MSelectionList(om.MGlobal.getActiveSelectionList());merged.add(parent)
            om.MGlobal.setActiveSelectionList(merged)
        else:cmds.select(parent,add=True,noExpand=True)

    def tool_setup(self):
        """Re-enter only when Maya explicitly returns to this armed context."""
        if self.closed or self.active or self._configuring_view or not self.paint_armed or self._resume_queued:return
        generation=self._resume_generation;self._resume_queued=True
        def resume():
            if generation!=self._resume_generation:return
            self._resume_queued=False
            bridge=sys.modules.get(BRIDGE)
            if (self.closed or not self.paint_armed or self.active or self._configuring_view
                    or getattr(bridge,'session',None) is not self or self.api.cmds.currentCtx()!=CONTEXT):return
            try:
                self.start(self.target,self.layer,self.joint,self.mode,self.readonly,
                    joint_path=self.joint_path,operation=self.brush_operation,**self._brush_values)
                if self.on_brush_settings:self.on_brush_settings()
                if self.on_change:self.on_change()
            except Exception as exc:
                self.last_error=str(exc);self.paint_armed=False
                if self.api.cmds.currentCtx()==CONTEXT:self.api.cmds.setToolTo('selectSuperContext')
                self.api.cmds.warning('Layer Skin resume: '+str(exc))
        self.helper('layer_skin_brush_view').QtCore.QTimer.singleShot(0,resume)

    @color_action
    def tool_cleanup(self):
        self.paint_event('tool_cleanup')
        if self.active:
            # Capture scalar settings once at handoff, including a B-drag radius
            # whose release sync has not run yet. Never query them per drag frame.
            try:
                for flag in ('value','radius','opacity'):
                    if self.readonly and flag=='opacity':continue
                    value=self.api.cmds.artUserPaintCtx(CONTEXT,query=True,**{flag:True})
                    if value is not None:self._brush_values[flag]=float(value)
                profile=self.api.cmds.artUserPaintCtx(CONTEXT,query=True,stampProfile=True)
                if profile in ('solid','poly','gaussian'):self.brush_profile=profile
            except RuntimeError:pass
        # Finish inside Artisan's outgoing cleanup, before the native skin
        # brush can change settings/weights or put its own edits in our chunk.
        # Deactivate first so reentrant/late paint callbacks cannot add samples.
        self.active=False;self._view_ready=False;self.previous_tool=None
        try:
            self.flush_pending('tool_change')
        finally:
            # Releasing the working array and closing Undo must also happen
            # when the command rejects a stroke. Never switch the incoming tool.
            self.stroke=None;self._end_chunk();self._view_ready=False
            if self.brush is not None:
                brush=self.brush;self.brush=None;brush.close()
            if self.buffer is not None and self.buffer.owner is self:self.buffer.owner=None
            self.buffer=None
            if self.api.cmds.artUserPaintCtx(CONTEXT,exists=True):
                self.api.cmds.artUserPaintCtx(CONTEXT,edit=True,colorfeedback=False,colorfeedbackOverride=False,disablelighting=False)
            if not self._stopping:
                self.show_preview();self.queue_preview()
            if self.on_change:self.on_change()

    @color_action
    def stop(self,keep_view=False,disarm=True):
        self._resume_generation+=1;self._resume_queued=False
        self._preview_generation+=1;self._preview_queued=False
        self._committed_snapshot=None
        if disarm:self.paint_armed=False
        self._end_chunk()
        self.stroke=None
        previous=self.previous_tool;self.previous_tool=None;active=self.active;self.active=False
        self._stopping=True
        error=None
        try:
            if self.brush is not None:
                brush=self.brush;self.brush=None
                try:brush.close()
                except Exception as exc:error=exc
            try:self.preview.clear()
            except Exception as exc:error=exc
            if active and self.api.cmds.currentCtx()==CONTEXT:
                try:self.api.cmds.artUserPaintCtx(CONTEXT,edit=True,colorfeedback=False,colorfeedbackOverride=False,disablelighting=False)
                finally:self.api.cmds.setToolTo(previous or 'selectSuperContext')
        finally:
            self._view_ready=False
            if not keep_view:self.values=[];self.state=None;self.viewing=False
            if self.buffer is not None and self.buffer.owner is self:self.buffer.owner=None
            self.buffer=None
            self._stopping=False
        if error is not None:raise error

    def add_joints(self,target,layer,joints):
        """Compatibility API; the UI paints/assigns without a separate add step."""
        return self.edit_joints(target,layer,joints,'membership')

    def edit_joints(self,target,layer,joints,action,data=None):
        """Bind at zero if needed, then commit one edit; roll back only this chunk."""
        if action not in ('membership','paint','assign','flood','value_operation'):raise ValueError('Unsupported joint edit.')
        if self.closed:raise ValueError('This Layer Skin window is closed.')
        cmds=self.api.cmds;ctx,meta,state=self.snapshot(target)
        if not meta:raise ValueError('Add a layer first.')
        current=next((row for row in state['layers'] if row['id']==layer),None)
        if current is None:raise ValueError('Select an editable layer.')
        data=dict(data or {})
        if data.get('expected') and data['expected']!=hashlib.sha256(self.api.core.encode(state).encode()).hexdigest():
            raise RuntimeError('Layer data changed during the stroke. The unfinished stroke was discarded.')
        joints=list(dict.fromkeys(joints))
        if not joints or any(not isinstance(joint,str) or cmds.nodeType(joint)!='joint' for joint in joints):raise ValueError('Choose joints in the browser or viewport.')
        if action=='assign' and data.get('settings',{}).get('method')=='axis':
            # Resolve once per joint, never per vertex. Full DAG depth ensures
            # every selected descendant runs before its selected ancestors.
            joints=[(cmds.ls(joint,long=True) or [joint])[0] for joint in joints]
            joints=sorted(set(joints),key=lambda path:(-path.count('|'),path))
        if not cmds.undoInfo(query=True,state=True):raise ValueError('Enable Undo before editing layer weights.')
        if cmds.referenceQuery(ctx['skin'],isNodeReferenced=True) or self.api.om.MFnDependencyNode(self.api.obj(ctx['skin'])).isLocked:
            raise ValueError('Referenced or locked skin cannot accept influences.')
        ids=[self.api.om.MFnDependencyNode(self.api.obj(joint)).uuid().asString() for joint in joints]
        locked=set(current.get('influence_locks',()))
        if action in ('paint','value_operation','flood') and data.get('joint') in locked:
            raise ValueError('This joint is locked in the selected layer. Unlock its padlock to edit weights.')
        if action=='assign':
            pairs=[(path,identity) for path,identity in zip(joints,ids) if identity not in locked]
            if not pairs:raise ValueError('All chosen joints are locked in the selected layer.')
            joints,ids=map(list,zip(*pairs))
        if action in ('paint','value_operation') and data.get('joint') not in ids:raise ValueError('The painted joint no longer matches the selected hierarchy joint.')
        data.update(target=target,layer=layer)
        if action=='membership':data['joints']=list(dict.fromkeys(current.get('joints',[])+ids))
        elif action=='assign':data['joints']=ids
        existing_set=set(ctx['ids'])
        self.api.core.storage().dimensions(ctx['count'],len(existing_set|set(ids)))
        unbound=[(joint,identity) for joint,identity in zip(joints,ids) if identity not in existing_set]
        import uuid
        if not unbound:return cmds.rtkLayerSkin(action=action,data=json.dumps(data))
        chunk='LayerSkinJointEdit_'+uuid.uuid4().hex
        failed=None;result=None;cmds.undoInfo(openChunk=True,chunkName=chunk)
        try:
            if unbound:
                for joint,_ in unbound:
                    cmds.skinCluster(ctx['skin'],edit=True,addInfluence=joint,weight=0.)
                after=self.api.context(target)
                after_columns={identity:i for i,identity in enumerate(after['ids'])}
                old_columns=[after_columns[identity] for identity in ctx['ids']]
                new_columns=[i for identity,i in after_columns.items() if identity not in existing_set]
                width=len(after['ids']);after_weights=after['weights']
                for i in new_columns:
                    col_vals=after_weights[i::width]
                    if col_vals and (min(col_vals)<-1e-8 or max(col_vals)>1e-8):
                        raise RuntimeError('Maya assigned nonzero weight while adding an influence.')
                projected=[after_weights[v*width+i] for v in range(ctx['count']) for i in old_columns]
                if not self.api.same(projected,ctx['weights'],2e-6):raise RuntimeError('Maya changed existing weights while adding an influence.')
                if data.get('expected'):
                    _,remapped=self.api.metadata(after)
                    expected_state=self.api.core.remap(state,after['ids'])
                    if remapped!=expected_state:raise RuntimeError('Layer data changed while binding the painted joint. The stroke was discarded.')
                    data['expected']=hashlib.sha256(self.api.core.encode(expected_state).encode()).hexdigest()
            result=cmds.rtkLayerSkin(action=action,data=json.dumps(data))
        except Exception as exc:failed=exc
        finally:cmds.undoInfo(closeChunk=True)
        if failed:
            owned=self._undo_chunk or chunk
            self._end_chunk()
            if cmds.undoInfo(query=True,undoName=True)==owned:cmds.undo()
            raise failed
        return result

    def make_browser(self,parent,selected):
        browser=self.api.make_joint_tree(parent,selected);self.browsers.append(browser);return browser

    def close(self):
        if self.closed:return
        self.closed=True;errors=[]
        for operation in [self.unlisten,self.stop,self.preview.close]+[browser.close for browser in self.browsers]:
            try:operation()
            except Exception as exc:errors.append(str(exc))
        self.browsers=[];self.on_change=None;self.on_pending=None;self.can_begin_stroke=None;self.relax_settings=None;self.on_brush_settings=None
        bridge=sys.modules.get(BRIDGE)
        owned=bridge and getattr(bridge,'session',None) is self
        if owned:bridge.session=None
        try:
            if owned and self.api.cmds.artUserPaintCtx(CONTEXT,exists=True):self.api.cmds.deleteUI(CONTEXT,toolContext=True)
        except RuntimeError as exc:errors.append(str(exc))
        if errors:self.api.cmds.warning('Layer Skin session cleanup: '+'; '.join(errors))

    def maya_exit(self):
        # Maya owns UI/tool teardown now. Remove Python callbacks/references
        # without selecting objects, switching tools or deleting native UI.
        if self.closed:return
        if self._display_gate is not None:self._display_gate.abandon()
        self.closed=True;self.unlisten();self.stroke=None;self.state=None;self.values=[];self.active=False;self.paint_armed=False;self._resume_generation+=1;self._resume_queued=False;self.on_change=None;self.on_pending=None;self.can_begin_stroke=None
        if self.buffer is not None and self.buffer.owner is self:self.buffer.owner=None
        self.buffer=None;self._undo_chunk=False
        self.viewing=False;self.preview.abandon()
        if self.brush is not None:self.brush.abandon();self.brush=None
        self.relax_settings=None;self.on_brush_settings=None
        bridge=sys.modules.get(BRIDGE)
        if bridge and getattr(bridge,'session',None) is self:bridge.session=None
        for browser in self.browsers:browser.closed=True
        self.browsers=[]

