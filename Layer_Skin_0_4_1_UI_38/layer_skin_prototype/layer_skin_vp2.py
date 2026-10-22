"""Node-free Viewport 2.0 weight display using nonselectable UI triangles.

Only model-panel renderer overrides and transient CPU arrays are changed. No
DG modifier, color set, mesh input/output plug, shader or scene node is written.
Maya's scene render, depth test, component drawing and default picking remain.
"""
import uuid


class WeightRenderer:
    def __init__(self, api, palette, render_api=None, view_api=None):
        if render_api is None:
            import maya.api.OpenMayaRender as render_api
        if view_api is None:
            import maya.api.OpenMayaUI as view_api
        self.api=api;self.om=api.om;self.r=render_api;self.ui=view_api;self.palette=palette
        self.name='rtkLayerSkinView_'+uuid.uuid4().hex
        self.mesh=None;self.dag=None;self.handle=None;self.fn=None;self.expected_count=0
        self.points=None;self.indices=None;self.colors=None;self.native_palettes={}
        self.panels={};self.skipped=[];self.callbacks=[];self.registered=False;self.closed=False
        self.enabled=False;self.geometry_dirty=True;self.override=None;self.destination=None
        self.draw_error='';self.geometry_updates=0;self.color_updates=0;self.draws=0;self.refreshes=0
        self.hud=None;self.hud_error=''
        self._make_override()

    @property
    def valid(self):
        return bool(self.handle and self.handle.isValid() and self.handle.isAlive())

    @property
    def visible(self):
        return self.enabled and self.registered and bool(self.panels) and self.valid

    def _make_override(self):
        r=self.r;owner=self
        class Scene(r.MSceneRender):
            def __init__(self):
                super(Scene,self).__init__('rtkLayerSkinScene')
            def renderFilterOverride(self):return r.MSceneRender.kRenderAllItems
            def clearOperation(self):
                self.mClearOperation.setMask(r.MClearOperation.kClearAll)
                self.mClearOperation.setOverridesColors(False)
                return self.mClearOperation
            def hasUIDrawables(self):return owner.visible and owner.points is not None and not owner.draw_error
            def addPostUIDrawables(self,manager,frame):
                if not self.hasUIDrawables() or not owner.allowed(owner.destination):return
                # Priority 1 is above the ordinary surface (0) and below Maya
                # wire/point priorities (2+). Depth testing stays enabled.
                manager.beginDrawable(r.MUIDrawManager.kNonSelectable)
                try:
                    manager.setPaintStyle(r.MUIDrawManager.kFlat)
                    manager.setDepthPriority(r.MRenderItem.sDormantFilledDepthPriority+1)
                    manager.mesh(r.MUIDrawManager.kTriangles,owner.points,color=owner.colors,index=owner.indices)
                    owner.draws+=1
                finally:manager.endDrawable()
        class Override(r.MRenderOverride):
            def __init__(self):
                super(Override,self).__init__(owner.name)
                self.operations=[Scene()]
                # MHUDRender has a default constructor; unlike scene/present
                # operations it does not accept a custom operation name.
                try:owner.hud=r.MHUDRender()
                except TypeError as exc:
                    # The heat map is in Scene, independent of the HUD pass.
                    # Report an unavailable binding without losing the view.
                    owner.hud_error=str(exc)
                else:self.operations.append(owner.hud)
                self.operations.append(r.MPresentTarget('rtkLayerSkinPresent'))
                self.index=0
            def uiName(self):return 'Layer Skin weight display'
            def supportedDrawAPIs(self):return r.MRenderer.kAllDevices
            def setup(self,destination):
                owner.destination=destination
                try:owner.prepare_geometry()
                except Exception as exc:owner.draw_error=str(exc)
            def cleanup(self):pass
            def startOperationIterator(self):self.index=0;return True
            def renderOperation(self):return self.operations[self.index] if self.index<len(self.operations) else None
            def nextRenderOperation(self):self.index+=1;return self.index<len(self.operations)
            def select(self,*args):return False  # Maya owns hit testing/components.
        self.override=Override()

    def _unlisten(self):
        failed=[];errors=[]
        while self.callbacks:
            identity=self.callbacks.pop()
            try:self.om.MMessage.removeCallback(identity)
            except RuntimeError:pass  # Maya may already remove a deleted node's callback.
            except Exception as exc:failed.append(identity);errors.append(str(exc))
        self.callbacks=failed
        if errors:raise RuntimeError('Weight viewport callbacks: '+'; '.join(errors))

    def _listen(self):
        self._unlisten()
        def dirty(*args):self.geometry_dirty=True
        # Geometry is reread only after an evaluated mesh/transform change.
        for node in (self.dag.node(),self.dag.transform()):
            self.callbacks.append(self.om.MNodeMessage.addNodeDirtyCallback(node,dirty))

    def prepare_geometry(self):
        if not self.enabled or not self.valid or not self.geometry_dirty:return
        if self.fn.numVertices!=self.expected_count:
            raise ValueError('Mesh topology changed. Refresh Layer Skin before viewing weights.')
        points=self.fn.getPoints(self.om.MSpace.kWorld)
        _,triangles=self.fn.getTriangles()
        if len(points)!=self.expected_count or len(triangles)%3:
            raise ValueError('The weight display could not read matching mesh triangles.')
        self.points=points;self.indices=self.om.MUintArray(triangles)
        self.geometry_dirty=False;self.geometry_updates+=1;self.draw_error=''

    def show(self,mesh,values,display):
        if self.closed:raise RuntimeError('The viewport renderer is closed.')
        changed=mesh!=self.mesh or not self.valid
        try:
            if changed:
                self.clear()
                selection=self.om.MSelectionList();selection.add(mesh);dag=selection.getDagPath(0)
                fn=self.om.MFnMesh(dag)
                if fn.numVertices!=len(values):
                    raise ValueError('Mesh topology changed. Refresh Layer Skin before viewing weights.')
                self.mesh=mesh;self.dag=dag;self.fn=fn;self.handle=self.om.MObjectHandle(dag.node())
                self.expected_count=len(values);self.geometry_dirty=True;self._listen()
            elif len(values)!=self.expected_count:
                raise ValueError('Mesh topology changed. Refresh Layer Skin before viewing weights.')
            if display not in self.native_palettes:
                self.native_palettes[display]=tuple(self.om.MColor(value) for value in self.palette.tables[display])
            colors=self.om.MColorArray(self.palette.map(values,display,self.native_palettes[display]))
            self.colors=colors;self.color_updates+=1;self.enabled=True
            self.prepare_geometry()
            self.reveal()
        except Exception:
            self.clear();raise

    def reveal(self):
        if not self.enabled or not self.valid:return
        if not self.registered:
            self.r.MRenderer.registerOverride(self.override);self.registered=True
        cmds=self.api.cmds;self.skipped=[];available=cmds.getPanel(type='modelPanel') or []
        for panel in tuple(self.panels):
            if panel not in available:self.panels.pop(panel,None)
        try:
            for panel in available:
                if cmds.modelEditor(panel,query=True,rendererName=True)!='vp2Renderer':continue
                current=cmds.modelEditor(panel,query=True,rendererOverrideName=True) or ''
                if current and current!=self.name:
                    self.panels.pop(panel,None);self.skipped.append(panel);continue
                if panel not in self.panels:self.panels[panel]=current if current!=self.name else ''
                if current!=self.name:cmds.modelEditor(panel,edit=True,rendererOverrideName=self.name,noUndo=True)
            if not self.panels:
                raise RuntimeError('Use a Viewport 2.0 panel with the standard renderer for the weight display. Existing custom renderer overrides were preserved.')
            self.request_refresh()
        except Exception:
            self.clear();raise

    def request_refresh(self):
        for panel in tuple(self.panels):
            try:self.ui.M3dView.getM3dViewFromModelPanel(panel).scheduleRefresh();self.refreshes+=1
            except RuntimeError:pass  # A panel can close during a tool handoff.

    def allowed(self,panel):
        if not panel or panel not in self.panels or not self.valid or not self.dag.isVisible():return False
        cmds=self.api.cmds
        if not cmds.modelEditor(panel,query=True,polymeshes=True):return False
        if cmds.isolateSelect(panel,query=True,state=True):
            group=cmds.isolateSelect(panel,query=True,viewObjects=True)
            members=cmds.sets(group,query=True) or []
            names=cmds.ls(members,long=True,objectsOnly=True) or []
            target=self.dag.fullPathName()
            if not any(target==name or target.startswith(name+'|') for name in names):return False
        return True

    def clear(self):
        self.enabled=False;errors=[];cmds=self.api.cmds
        for panel,previous in tuple(self.panels.items()):
            try:
                if cmds.modelEditor(panel,exists=True) and cmds.modelEditor(panel,query=True,rendererOverrideName=True)==self.name:
                    cmds.modelEditor(panel,edit=True,rendererOverrideName=previous,noUndo=True)
            except Exception as exc:errors.append(str(exc));continue
            self.panels.pop(panel,None)
        try:self._unlisten()
        except Exception as exc:errors.append(str(exc))
        # Retain a registered object if a failed restore still references it.
        if not self.panels and self.registered:
            try:self.r.MRenderer.deregisterOverride(self.override);self.registered=False
            except Exception as exc:errors.append(str(exc))
        if not self.panels:
            self.mesh=None;self.handle=None;self.fn=None;self.dag=None;self.expected_count=0
            self.points=None;self.indices=None;self.colors=None;self.geometry_dirty=True;self.draw_error=''
        if errors:raise RuntimeError('Weight viewport cleanup: '+'; '.join(errors))

    def close(self):self.clear();self.closed=True

    def abandon(self):
        # Maya shutdown owns panel/renderer teardown. Do not call graphics APIs.
        self.enabled=False;self.closed=True;self._unlisten();self.panels={}
        self.mesh=None;self.handle=None;self.fn=None;self.dag=None;self.points=None;self.indices=None;self.colors=None

    def report(self):
        return dict(backend='VP2 viewport draw pass',visible=self.visible,scene_nodes_created=0,
                    renderer_revision=35,hud_enabled=self.hud is not None,hud_constructor_error=self.hud_error or None,
                    renderer=self.name,panels=list(self.panels),skipped_custom_panels=list(self.skipped),
                    geometry_updates=self.geometry_updates,color_updates=self.color_updates,draws=self.draws,
                    refresh_requests=self.refreshes,last_draw_error=self.draw_error)
