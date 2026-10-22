"""Viewport-only Shift gestures, using Maya's own Artisan brush feedback.

Do not parent a painted/translucent Qt widget to M3dView: it can obscure the
native viewport and retain circle trails on Windows/VP2. No overlay is created.
"""
import json
import math
import time
import weakref

try:
    from PySide6 import QtCore,QtGui,QtWidgets
    import shiboken6 as shiboken
except ImportError:
    from PySide2 import QtCore,QtGui,QtWidgets
    import shiboken2 as shiboken


class NativeView:
    def __init__(self,session,view,widget,receiver=None):
        self.session=session;self.view=view;self.widget=widget
        self.receiver=receiver if receiver is not None else widget
        self._redrawing=False;self._last_redraw=None
    @staticmethod
    def find(session,watched):
        if not isinstance(watched,QtWidgets.QWidget):return None
        cmds=session.api.cmds;panel=cmds.getPanel(underPointer=True)
        if not panel or cmds.getPanel(typeOf=panel)!='modelPanel':return None
        import maya.api.OpenMayaUI as omui
        view=omui.M3dView.getM3dViewFromModelPanel(panel)
        widget=shiboken.wrapInstance(int(view.widget()),QtWidgets.QWidget)
        if watched is not widget and not widget.isAncestorOf(watched):return None
        return NativeView(session,view,widget,watched)
    def point(self,event):
        position=event.globalPosition() if hasattr(event,'globalPosition') else event.screenPos()
        origin=self.widget.mapToGlobal(QtCore.QPoint(0,0))
        return float(position.x()-origin.x()),float(position.y()-origin.y())
    def geometry(self,ctx,radius):return NativeGeometry(self,ctx,radius)
    def feedback(self,point):
        """Move Artisan's outline without sending a press, drag or release.

        The custom Shift handler owns the real held-button gesture. Forward only
        a buttonless, modifier-free hover to the original viewport receiver so
        Maya can position its normal outline. BrushController guards reentry.
        """
        if not shiboken.isValid(self.widget) or not shiboken.isValid(self.receiver):return False
        global_point=QtCore.QPointF(self.widget.mapToGlobal(QtCore.QPoint(0,0)))+QtCore.QPointF(*point)
        local=global_point-QtCore.QPointF(self.receiver.mapToGlobal(QtCore.QPoint(0,0)))
        window=global_point-QtCore.QPointF(self.receiver.window().mapToGlobal(QtCore.QPoint(0,0)))
        event=QtGui.QMouseEvent(QtCore.QEvent.MouseMove,local,window,global_point,
            QtCore.Qt.NoButton,QtCore.Qt.NoButton,QtCore.Qt.NoModifier)
        QtWidgets.QApplication.sendEvent(self.receiver,event)
        return True
    def redraw(self,force=False):
        # scheduleRefresh waits for Maya idle, which can be delayed throughout
        # a held gesture. Throttle immediate drag redraws to 30/sec; idle and
        # forced final redraws can also occur.
        if self._redrawing or not shiboken.isValid(self.widget):return False
        # Action handoffs publish their own completed frame. Do not force an
        # intermediate material/old-joint frame while the panel is held.
        if getattr(self.session,'display_transition_active',False) or not self.widget.updatesEnabled():return False
        now=time.monotonic()
        if not force and self._last_redraw is not None and now-self._last_redraw<1./30.:
            self.view.scheduleRefresh();return False
        self._redrawing=True
        try:
            self.view.refresh(False,True);self._last_redraw=now;return True
        finally:self._redrawing=False


class NativeGeometry:
    def __init__(self,viewport,ctx,radius):
        self.viewport=viewport;self.om=viewport.session.api.om;self.math=viewport.session.helper('layer_skin_brush')
        self.fn=self.om.MFnMesh(ctx['dag']);self.iterator=self.om.MItMeshVertex(ctx['dag']);self.rows={};self.projected={}
        self.radius=float(radius);self.radius_source='radius';self.projected_radius=None
        self.native_screen_radius=None;self.effective_screen_radius=None;self.screen_radius_source='projected world radius'
        self.update_radius()
        self.points={}
        self.grid=self.math.ConnectedSurface(self.point)
        self.accelerator=self.fn.autoUniformGridParams()
    def point(self,v):
        if v not in self.points:
            p=self.fn.getPoint(v,self.om.MSpace.kWorld);self.points[v]=(p.x,p.y,p.z)
        return self.points[v]
    def update_radius(self):
        # Read Artisan's effective world radius after its outline has moved.
        # Both the API points and this radius use Maya world space. Applying
        # MDistance.uiUnit() here can multiply an already-internal radius again.
        api=self.viewport.session.api
        for flag in ('worldRadius','radius'):
            try:value=float(api.cmds.artUserPaintCtx(api.paint_context,query=True,**{flag:True}))
            except (RuntimeError,TypeError,ValueError):continue
            if math.isfinite(value) and value>0:
                self.radius=value;self.radius_source=flag;break
        if not math.isfinite(self.radius) or self.radius<=0:raise ValueError('Maya did not report a positive brush radius.')
        # The native outline can be smaller than a circle reconstructed from
        # worldRadius (screen-mode painting, depth changes or native settings).
        # Never let that reconstructed circle be the only screen-space bound.
        self.native_screen_radius=None
        try:value=float(api.cmds.artUserPaintCtx(api.paint_context,query=True,screenRadius=True))
        except (RuntimeError,TypeError,ValueError):value=None
        if value is not None and math.isfinite(value) and value>0:self.native_screen_radius=value
        self.screen_radius_source='screenRadius' if self.native_screen_radius is not None else 'projected world radius'
    def report(self):
        return dict(world_radius=self.radius,radius_source=self.radius_source,
            projected_radius_pixels=self.projected_radius,projected_vertices=len(self.projected),
            native_screen_radius_pixels=self.native_screen_radius,effective_screen_radius_pixels=self.effective_screen_radius,
            screen_radius_source=self.screen_radius_source,boundary_revision=37,position_vertices=len(self.points),
            geometry_scope='connected footprint and boundary per gesture',
            footprint='connected world sphere clipped to native screen circle',neighbor_halo='read only')
    def neighbors(self,v):
        if v not in self.rows:
            self.iterator.setIndex(v);self.rows[v]=tuple(self.iterator.getConnectedVertices())
        return self.rows[v]
    def ray(self,point):
        view=self.viewport.view;widget=self.viewport.widget
        sx=point[0]*view.portWidth()/max(1,widget.width())
        sy=view.portHeight()-1-point[1]*view.portHeight()/max(1,widget.height())
        x=int(round(sx));y=int(round(sy))
        if not 0<=x<view.portWidth() or not 0<=y<view.portHeight():return None
        origin=self.om.MPoint();direction=self.om.MVector()
        view.viewToWorld(x,y,origin,direction);direction.normalize()
        hit=self.fn.closestIntersection(self.om.MFloatPoint(origin),self.om.MFloatVector(direction),
            self.om.MSpace.kWorld,1e12,False,accelParams=self.accelerator)
        if hit is None:return None
        p=hit[0];center=(p.x,p.y,p.z)
        a,screen_radius=self.projected_circle(center)
        if self.native_screen_radius is not None:a=(sx,sy,True)
        r2=screen_radius*screen_radius
        def clip(v):
            if v not in self.projected:self.projected[v]=view.worldToView(self.om.MPoint(*self.point(v)))
            projected=self.projected[v]
            if not projected[2]:return 0.
            d2=(projected[0]-a[0])**2+(projected[1]-a[1])**2
            return self.math.falloff(math.sqrt(d2/r2))
        seeds=self.fn.getPolygonVertices(hit[2]);factors=self.grid.footprint(center,seeds,self.neighbors,radius=self.radius,clip=clip)
        return center,factors
    def projected_circle(self,center):
        om=self.om;view=self.viewport.view
        inverse=view.modelViewMatrix().inverse();right=om.MVector(1.,0.,0.)*inverse;right.normalize()
        point=om.MPoint(*center);offset=point+right*self.radius
        a=view.worldToView(point);b=view.worldToView(offset)
        radius=math.hypot(a[0]-b[0],a[1]-b[1])
        if radius==0:
            # worldToView returns integer port coordinates. A tiny valid brush
            # can round to one point; measure a longer camera-right reference
            # at the same depth and divide, retaining the actual world bound.
            b=view.worldToView(point+right*(self.radius*1024.))
            radius=math.hypot(a[0]-b[0],a[1]-b[1])/1024.
        if not a[2] or not math.isfinite(radius) or radius<=0:raise ValueError('The brush circle could not be projected into the active viewport.')
        self.projected_radius=radius
        self.effective_screen_radius=min(radius,self.native_screen_radius) if self.native_screen_radius is not None else radius
        return a,self.effective_screen_radius
    def screen_radius(self,center):
        radius=self.projected_circle(center)[1];view=self.viewport.view;widget=self.viewport.widget
        return max(1.,radius*widget.width()/max(1,view.portWidth()))


class BrushController(QtCore.QObject):
    def __init__(self,session,view_provider=None):
        app=QtWidgets.QApplication.instance()
        super(BrushController,self).__init__(app)
        self._session=weakref.ref(session);self.view_provider=view_provider or NativeView.find
        self.closed=False;self.dragging=False;self.finishing=False;self.block_release=False;self.b_down=False
        self.radius_adjusting=False;self.radius_button_down=False
        self.transaction=None;self.viewport=None;self.geometry=None;self.sampler=None
        self.expected=None;self.baseline=None;self.last=None;self._sync_queued=False;self._component_sync_queued=False
        self.component_scope=None
        self._feedback_active=False;self.hover_events=0;self.shift_gesture=False
        self.started_strokes=0;self.mesh_hits=0;self.footprint_vertices=0;self.preview_vertices=set()
        self.last_footprint=None
        self._preview_dirty=False;self._last_preview=None;self.preview_uploads=0
        self._preview_timer=QtCore.QTimer(self);self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._preview_timeout)
        app.installEventFilter(self)
    @property
    def drawing(self):return self.dragging or self.finishing
    def report(self):
        return dict(active=self.drawing,stamps=self.transaction.stamps if self.transaction else 0,
            staged_vertices=len(self.transaction.touched) if self.transaction else 0,last_stroke=self.last,
            neighbor_rows=len(getattr(self.geometry,'rows',{})),feedback_backend='Maya Artisan outline',
            solver='layer one-ring Relax',qt_viewport_overlay=False,passive_hover_events=self.hover_events,
            started_strokes=self.started_strokes,mesh_hits=self.mesh_hits,footprint_vertices=self.footprint_vertices,
            radius_adjusting=self.radius_adjusting,settings_revision=30,
            component_selection_hotkeys=True,
            preview_uploads=self.preview_uploads,preview_fps=30,
            preview_changed_vertices=len(self.preview_vertices),footprint=self.footprint_report())
    def footprint_report(self):
        report=getattr(self.geometry,'report',None)
        return report() if report is not None else self.last_footprint
    def move_outline(self,point):
        self._feedback_active=True
        try:
            if self.viewport.feedback(point):self.hover_events+=1
        finally:self._feedback_active=False
    def sync(self):
        self._sync_queued=False;s=self._session()
        if self.closed or not s or s.closed:return
        if self.b_down or self.radius_button_down:return
        try:
            if s.on_brush_settings:s.on_brush_settings()
        finally:
            # Native release callbacks can run after the Qt event filter.
            # Keep the settings guard through that native event, then release
            # it at idle after both B and the radius mouse button are up.
            if self.radius_adjusting and not self.b_down and not self.radius_button_down:
                self.radius_adjusting=False
                if (s.needs_refresh or s._settings_selection_deferred) and s.on_change:s.on_change()
    def queue_sync(self):
        if not self._sync_queued:self._sync_queued=True;QtCore.QTimer.singleShot(0,self.sync)
    def queue_component_sync(self):
        s=self._session()
        if s is not None:s._component_mode_dirty=True
        if self._component_sync_queued:return
        self._component_sync_queued=True
        def update():
            self._component_sync_queued=False;s=self._session()
            if self.closed or not s or s.closed:return
            try:s.keep_paint_in_component_mode()
            except Exception as exc:s.last_error=str(exc);s.api.cmds.warning('Layer Skin component mode: '+str(exc))
        QtCore.QTimer.singleShot(0,update)
    def settings_changed(self):
        self.radius_adjusting=True;self.queue_sync()
    def keyboard_view(self,session,watched):
        view=self.view_provider(session,watched)
        if view is not None:return view
        # ShortcutOverride can arrive at Maya's main window instead of the
        # viewport child. Only fall back to an actual focused viewport in that
        # same window; text fields and other editors keep their own shortcuts.
        focused=QtWidgets.QApplication.focusWidget()
        if focused is None:return None
        if isinstance(watched,QtWidgets.QWidget):
            if watched is not focused.window() and not watched.isAncestorOf(focused):return None
        elif isinstance(watched,QtGui.QWindow):
            if focused.window().windowHandle()!=watched:return None
        else:return None
        return self.view_provider(session,focused)
    def begin(self,viewport,point):
        s=self._session();s.flush_pending('shift_brush_start');self.sync()
        ctx,meta,state=s.snapshot(s.target)
        self.component_scope=s.paint_scope(ctx)
        if not meta or s.layer=='__base__':raise ValueError('Choose an editable layer before Shift painting.')
        owner=getattr(s.api,'_layer_skin_command_owner',None)
        composed=owner.get('expected_weights') if isinstance(owner,dict) else None
        if not s.api.same(ctx['weights'],composed(state) if callable(composed) else s.api.core.composite(state),2e-6):
            raise ValueError('Skin weights changed outside Layer Skin. Undo native edits before layer painting.')
        if state is not s.state or meta!=s._prepared_meta or s._paint_cache_dirty:
            s.prepare((ctx,meta,state))
        settings=dict(s.relax_settings() if s.relax_settings else {})
        settings['opacity']=float(s.api.cmds.artUserPaintCtx(s.api.paint_context,query=True,opacity=True))
        radius=float(s.api.cmds.artUserPaintCtx(s.api.paint_context,query=True,radius=True))
        math_module=s.helper('layer_skin_brush');relax=s.helper('layer_skin_relax')
        self.transaction=math_module.RelaxStroke(state,s.layer,s.mode,settings,relax)
        self.started_strokes+=1;self.mesh_hits=0;self.footprint_vertices=0;self.preview_vertices=set()
        self.expected=s._hash_for_state(state,False,ctx)
        self.baseline=list(s.values);self.viewport=viewport;self.dragging=True
        self._stop_preview();self._last_preview=None;self.preview_uploads=0
        self.last_footprint=None;self.move_outline(point)
        if self.viewport is not viewport or not self.dragging:return
        self.geometry=viewport.geometry(ctx,radius);hit=self.geometry.ray(point)
        self.screen_radius=self.geometry.screen_radius(hit[0]) if hit else 24.
        self.sampler=math_module.PointSampler(max(1.,self.screen_radius*.2),max_samples=8)
        viewport.widget.grabMouse()
        self.apply_point(point,first_hit=hit,outline_ready=True)
    def apply_point(self,point,first_hit=None,outline_ready=False):
        s=self._session();changed=set()
        samples=self.sampler.feed(point)
        for i,sample in enumerate(samples):
            # A coarse input move can produce multiple stamps at different
            # depths. Move the native brush and query its radii at EACH stamp,
            # not once at the final cursor position for the entire segment.
            if outline_ready and i==0:
                hit=first_hit
            else:
                viewport=self.viewport
                self.move_outline(sample)
                if self.viewport is not viewport or not self.dragging:return
                update=getattr(self.geometry,'update_radius',None)
                if update is not None:update()
                hit=self.geometry.ray(sample)
            if hit:
                self.mesh_hits+=1;self.footprint_vertices+=len(hit[1])
                self.screen_radius=self.geometry.screen_radius(hit[0])
                footprint=hit[1]
                if self.component_scope is not None:footprint={v:weight for v,weight in footprint.items() if v in self.component_scope}
                changed.update(self.transaction.stamp(footprint,self.geometry.neighbors))
        # Keep the outline under the cursor even if spacing generated no stamp
        # here. This hover never adds solver scope or another relaxation pass.
        if not outline_ready and (not samples or tuple(samples[-1])!=tuple(point)):
            viewport=self.viewport
            self.move_outline(point)
            if self.viewport is not viewport or not self.dragging:return
        if changed:
            self.preview_vertices.update(changed)
            for v,value in self.transaction.preview(changed,s.joint).items():s.values[v]=value
            self._preview_dirty=True;self._publish_preview()
        viewport=self.viewport
        if self.viewport is viewport and self.dragging:viewport.redraw()
    def _stop_preview(self):
        self._preview_timer.stop();self._preview_dirty=False
    def _publish_preview(self,force=False):
        s=self._session()
        if not self._preview_dirty or not s or s.closed:return False
        now=time.monotonic();remaining=0. if self._last_preview is None else 1./30.-(now-self._last_preview)
        if not force and remaining>0:
            if not self._preview_timer.isActive():self._preview_timer.start(max(1,math.ceil(remaining*1000)))
            return False
        self._preview_timer.stop();self._preview_dirty=False
        s._write_buffer();s.reload_feedback();self._last_preview=time.monotonic();self.preview_uploads+=1
        return True
    def _preview_timeout(self):
        if self.closed or not self.dragging:return
        try:
            if self._publish_preview() and self.viewport is not None:self.viewport.redraw()
        except Exception as exc:
            s=self._session()
            try:self.cancel('preview_error')
            finally:
                if s:s.last_error=str(exc);s.api.cmds.warning('Layer Skin Relax preview: '+str(exc))
    def _release(self):
        self.dragging=False
        try:
            if self.viewport and shiboken.isValid(self.viewport.widget) and QtWidgets.QWidget.mouseGrabber() is self.viewport.widget:
                self.viewport.widget.releaseMouse()
        except RuntimeError:pass
    def _redraw_final(self):
        try:
            if self.viewport and shiboken.isValid(self.viewport.widget):self.viewport.redraw(force=True)
        except RuntimeError:pass
    def finish(self,reason='mouse_release'):
        if not self.dragging:return
        s=self._session();transaction=self.transaction
        data=transaction.payload() if transaction else {};rows=data.get('samples',data.get('values',{}))
        self.finishing=True;s._committing=True
        self.last_footprint=self.footprint_report()
        self._preview_timer.stop()
        self._release();self.transaction=None;self.geometry=None;self.sampler=None
        report=dict(status='unchanged',action='relax',mode=s.mode,mesh=s.target,layer=s.layer,joint=s.joint,
            submitted_vertices=len(rows),changed_vertices=len(rows),layer_values_verified=False,commit_reason=reason,
            stamps=transaction.stamps if transaction else 0,joint_path=s.joint_path,solver='layer one-ring Relax',
            preserve_coverage=transaction.preserve if transaction else None,mesh_hits=self.mesh_hits,
            footprint_vertices=self.footprint_vertices,preview_changed_vertices=len(self.preview_vertices),footprint=self.last_footprint)
        if not rows and transaction:
            if not transaction.strength or not transaction.opacity:report['unchanged_reason']='Brush strength or opacity is zero.'
            elif not self.mesh_hits:report['unchanged_reason']='The brush ray did not hit the mesh.'
            elif not self.footprint_vertices:report['unchanged_reason']='No vertices are inside the brush. Increase Brush radius.'
            elif transaction.preserve and s.mode=='weights':report['unchanged_reason']='No weight change with Preserve coverage enabled. Turn it off to smooth the painted boundary.'
            else:report['unchanged_reason']='The sampled layer values are already uniform, or the joint-group budget prevents a transfer.'
        try:
            self._publish_preview(force=True)
            if rows:
                data.update(target=s.target,expected=self.expected)
                provider=getattr(s.api,'commit_edit',None);receipt=None;scope=s.receipt_scope()
                if callable(provider) and scope:receipt=provider('relax_stroke',data,scope)
                else:s.api.cmds.rtkLayerSkin(action='relax_stroke',data=json.dumps(data))
                changed={key:s.values[int(key)] for key in rows}
                if not s._accept_paint_receipt(receipt,scope,changed):s.prepare()
                saved=next(row for row in s.state['layers'] if row['id']==s.layer)
                for key,value in rows.items():
                    if s.mode=='mask':valid=abs(saved['mask'].get(key,1.)-value)<=2e-6
                    else:
                        sample=saved['samples'].get(key) or saved.get('generated',{}).get(key)
                        valid=bool(sample and abs(sample['coverage']-value['coverage'])<=2e-6 and s.api.same(sample['weights'],value['weights'],2e-6))
                    if not valid:raise RuntimeError('Saved Relax values differ from the brush preview. The authoring command remains in Undo.')
                report.update(status='saved',layer_values_verified=True);s.last_error=''
            else:s.values=self.baseline[:];s._write_buffer()
        except Exception as exc:
            report.update(status='rejected',error=str(exc));s.last_error=str(exc)
            s.prepare();raise
        finally:
            report['preview_uploads']=self.preview_uploads
            s._committing=False;s.last_stroke=report;self.last=dict(report)
            self._stop_preview()
            self.expected=None;self.baseline=None
            try:
                if s.active and s.api.cmds.artUserPaintCtx(s.api.paint_context,exists=True):s.reload_feedback()
            finally:self._redraw_final();self.finishing=False;self.viewport=None
            if rows:s.needs_refresh=True
            if s.on_change:s.on_change()
    def cancel(self,reason='escape'):
        s=self._session();self.finishing=True
        try:
            self._stop_preview()
            self.last_footprint=self.footprint_report()
            self._release()
            if s and self.baseline is not None:
                s.values=self.baseline[:];s._write_buffer()
                if s.active and s.api.cmds.artUserPaintCtx(s.api.paint_context,exists=True):s.reload_feedback()
        finally:
            self._redraw_final()
            self.last=dict(status='cancelled',reason=reason,footprint=self.last_footprint)
            self.transaction=None;self.geometry=None;self.sampler=None;self.baseline=None;self.expected=None
            self.finishing=False;self.viewport=None
    def eventFilter(self,watched,event):
        s=self._session()
        if self.closed or not s or s.closed:return False
        if self._feedback_active:return False
        kind=event.type();press=QtCore.QEvent.MouseButtonPress;release=QtCore.QEvent.MouseButtonRelease;move=QtCore.QEvent.MouseMove
        shortcut=QtCore.QEvent.ShortcutOverride
        owned=self.dragging or self.block_release
        try:
            if kind in (shortcut,QtCore.QEvent.KeyPress,QtCore.QEvent.KeyRelease):
                if (kind in (shortcut,QtCore.QEvent.KeyPress) and event.key() in (QtCore.Qt.Key_F8,QtCore.Qt.Key_F9,QtCore.Qt.Key_F10,QtCore.Qt.Key_F11)
                        and event.modifiers()==QtCore.Qt.NoModifier and not event.isAutoRepeat()
                        and s.active and not s._configuring_view and s.api.cmds.currentCtx()==s.api.paint_context
                        and self.keyboard_view(s,watched) is not None):
                    self.queue_component_sync()
                    # Native F8-F11 set the mask. Do not switch to Select or
                    # re-enter Paint over the top of a deliberate Q/tool change.
                    return False
                if event.key()==QtCore.Qt.Key_B:
                    if kind in (shortcut,QtCore.QEvent.KeyPress):
                        if event.modifiers()!=QtCore.Qt.NoModifier or event.isAutoRepeat():return False
                        if not self.dragging and not self.b_down and (not s.active or s.api.cmds.currentCtx()!=s.api.paint_context or self.keyboard_view(s,watched) is None):return False
                        starting=not self.radius_adjusting
                        self.radius_adjusting=True;self.b_down=True
                        if starting:
                            if self.dragging:self.finish('radius_change');self.block_release=True
                            s.flush_pending('radius_change')
                    else:
                        if not self.b_down and not self.radius_adjusting:return False
                        self.b_down=False
                    if not self.b_down and not self.radius_button_down:self.queue_sync()
                    return False
                if kind==shortcut:return False
                if self.dragging and kind==QtCore.QEvent.KeyPress and event.key()==QtCore.Qt.Key_Escape:
                    self.cancel();self.block_release=True;return True
                if self.dragging and kind==QtCore.QEvent.KeyPress and event.key()==QtCore.Qt.Key_Z and event.modifiers() & QtCore.Qt.ControlModifier:
                    self.cancel('history_shortcut');self.block_release=True;return False
                if self.dragging and self.shift_gesture and kind==QtCore.QEvent.KeyRelease and event.key()==QtCore.Qt.Key_Shift:
                    self.finish('shift_release');self.block_release=True;return False
                return False
            if self.radius_adjusting:
                if kind==press and event.button()==QtCore.Qt.LeftButton:
                    if self.b_down:self.radius_button_down=True;return False
                    # A genuine new paint press supersedes a queued idle sync.
                    self.radius_adjusting=False;self.radius_button_down=False
                elif kind==release and event.button()==QtCore.Qt.LeftButton:
                    self.radius_button_down=False
                    if not self.b_down:self.queue_sync()
                    if not owned:return False
                elif kind==move and (self.b_down or self.radius_button_down):return False
                elif kind==QtCore.QEvent.WindowDeactivate:
                    self.b_down=False;self.radius_button_down=False;self.queue_sync()
            if owned and kind==release and event.button()==QtCore.Qt.LeftButton:
                if self.dragging:self.finish()
                self.block_release=False;self.queue_sync();return True
            if owned and kind==move:
                if self.dragging:self.apply_point(self.viewport.point(event))
                return True
            if self.dragging and kind in (QtCore.QEvent.WindowDeactivate,):
                self.cancel('focus_lost');self.block_release=False;return False
            if kind==release:
                if not self.b_down and self.view_provider(s,watched) is not None:self.queue_sync()
                return False
            if kind!=press or event.button()!=QtCore.Qt.LeftButton or self.b_down:return False
            mods=event.modifiers()
            if mods & (QtCore.Qt.AltModifier|QtCore.Qt.ControlModifier):return False
            if not mods & QtCore.Qt.ShiftModifier and s.brush_operation!='relax':return False
            if not s.active or s.readonly or s.api.cmds.currentCtx()!=s.api.paint_context:return False
            viewport=self.view_provider(s,watched)
            if viewport is None:return False
            self.shift_gesture=bool(mods & QtCore.Qt.ShiftModifier)
            owned=True;self.block_release=True
            self.begin(viewport,viewport.point(event));return True
        except Exception as exc:
            self.radius_adjusting=False;self.radius_button_down=False;self.b_down=False
            try:self.cancel('error')
            except Exception:pass
            s.last_error=str(exc);s.api.cmds.warning('Layer Skin Relax brush: '+str(exc))
            if owned:self.block_release=True
            return owned
    def close(self):
        if self.closed:return
        try:
            if self.dragging:self.cancel('tool_cleanup')
        finally:
            self._stop_preview()
            self.closed=True;self.block_release=False;self.radius_adjusting=False;self.radius_button_down=False;self.b_down=False
            app=QtWidgets.QApplication.instance()
            if app:app.removeEventFilter(self)
            self.deleteLater()
    def abandon(self):
        # Late Maya exit: do not touch viewport widgets or the DG.
        self._stop_preview()
        self.closed=True;self.dragging=False;self.finishing=False;self.transaction=None;self.geometry=None
        self.radius_adjusting=False;self.radius_button_down=False;self.b_down=False
        self.baseline=None;self.viewport=None;self._feedback_active=False;self._session=lambda:None


def attach(session):
    if QtWidgets.QApplication.instance() is None:return None
    return BrushController(session)
