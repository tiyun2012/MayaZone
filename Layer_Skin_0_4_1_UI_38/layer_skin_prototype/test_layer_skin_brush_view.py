"""Real Qt gesture routing with a deterministic viewport adapter; no Maya/GPU."""
import json
import sys
import types
import unittest
from unittest import mock
import layer_skin_core as core
import layer_skin_session as sessions
from test_layer_skin_session import FakeAPI

try:
    from PySide6 import QtCore,QtGui,QtWidgets
    import layer_skin_brush_view as view_module
except ImportError:
    try:
        from PySide2 import QtCore,QtGui,QtWidgets
        import layer_skin_brush_view as view_module
    except ImportError:view_module=None


@unittest.skipIf(view_module is None,'PySide is required')
class BrushViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        case=self;self.native_events=[];self.probe_callbacks=False;self.feedback_failure=False
        class ViewportWidget(QtWidgets.QWidget):
            def mouseMoveEvent(widget,event):
                case.native_events.append((event.type(),event.button(),event.buttons(),event.modifiers()))
                if case.probe_callbacks:
                    case.session.before_stroke();case.session.set_value(1,0,.99);case.session.after_stroke()
        self.api=FakeAPI();self.widget=ViewportWidget();self.widget.setMouseTracking(True);self.widget.resize(400,200);self.widget.show()
        state=self.api.state
        state=core.edit(state,'assign',dict(layer=self.api.layer,generated={
            '0':dict(weights=[1.,0.],coverage=1.),'1':dict(weights=[0.,1.],coverage=1.),'2':dict(weights=[0.,1.],coverage=1.)},scope=[0,1,2]))
        self.api.state=state;self.api.weights=core.composite(state);self.builds=0;self.redraws=0;self.hit=True
        case=self
        class Geometry:
            rows={0:[1],1:[0,2],2:[1]}
            def ray(self,point):return ((0,0,0),{0:1.}) if case.hit else None
            def neighbors(self,v):return self.rows[v]
            def screen_radius(self,point):return 10.
        class View:
            widget=case.widget
            def point(self,event):return float(event.position().x()),float(event.position().y())
            def geometry(self,ctx,radius):case.builds+=1;return Geometry()
            def redraw(self,force=False):case.redraws+=1
            def feedback(self,point):
                if case.feedback_failure:raise RuntimeError('native hover failed')
                return view_module.NativeView(case.session,None,case.widget).feedback(point)
        self.viewport=View()
        self.api.make_brush_controller=lambda session:view_module.BrushController(session,lambda s,w:self.viewport if w is self.widget else None)
        self.session=sessions.Session(self.api);self.session.relax_settings=lambda:dict(strength=.5,iterations=1,preserve_coverage=True)
        self.session.start('mesh',self.api.layer,joint='b',mode='weights');self.controller=self.session.brush
    def tearDown(self):
        self.session.close();self.widget.close();self.app.processEvents();sys.modules.pop(sessions.BRIDGE,None)
    def mouse(self,kind,point=(20,20),shift=True):
        button=QtCore.Qt.NoButton if kind==QtCore.QEvent.MouseMove else QtCore.Qt.LeftButton
        buttons=QtCore.Qt.NoButton if kind==QtCore.QEvent.MouseButtonRelease else QtCore.Qt.LeftButton
        mods=QtCore.Qt.ShiftModifier if shift else QtCore.Qt.NoModifier
        event=QtGui.QMouseEvent(kind,QtCore.QPointF(*point),QtCore.QPointF(self.widget.mapToGlobal(QtCore.QPoint(*point))),button,buttons,mods)
        return self.controller.eventFilter(self.widget,event)
    def press(self):return self.mouse(QtCore.QEvent.MouseButtonPress)
    def release(self,shift=True):return self.mouse(QtCore.QEvent.MouseButtonRelease,shift=shift)
    def key(self,key,kind=QtCore.QEvent.KeyPress,mods=QtCore.Qt.NoModifier,watched=None):
        return self.controller.eventFilter(watched or self.widget,QtGui.QKeyEvent(kind,key,mods))
    def test_shift_stages_live_feedback_then_saves_one_guarded_undo_on_release(self):
        before=self.api.snapshot();self.assertTrue(self.press())
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.session.values,[.5,1.,1.]);self.assertEqual(self.api.calls,[])
        self.assertTrue(self.mouse(QtCore.QEvent.MouseMove,(24,20)))
        self.assertGreater(self.session.values[0],.5);self.assertEqual(self.builds,1)
        self.assertTrue(self.release());self.assertEqual(self.api.calls[-1][0],'relax_stroke')
        self.assertEqual(len(self.api.undo_stack),1);self.assertFalse(self.controller.drawing)
        self.assertTrue(self.session.last_stroke['layer_values_verified']);self.assertIsNone(self.api._chunk)
        self.api.undo();self.assertEqual(self.api.snapshot(),before)
    def test_normal_mouse_and_non_viewport_shift_press_pass_through(self):
        self.assertFalse(self.mouse(QtCore.QEvent.MouseButtonPress,shift=False));self.assertFalse(self.release(False))
        other=QtWidgets.QWidget();event=QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress,QtCore.QPointF(0,0),QtCore.QPointF(0,0),QtCore.Qt.LeftButton,QtCore.Qt.LeftButton,QtCore.Qt.ShiftModifier)
        self.assertFalse(self.controller.eventFilter(other,event));other.deleteLater();self.assertEqual(self.api.calls,[])
    def test_selected_relax_operation_uses_same_layer_solver_without_shift(self):
        self.session.brush_operation='relax';before=self.api.snapshot()
        self.assertTrue(self.mouse(QtCore.QEvent.MouseButtonPress,shift=False));self.assertEqual(self.session.values,[.5,1.,1.])
        self.assertEqual(self.api.snapshot(),before);self.assertTrue(self.release(False))
        self.assertEqual(self.api.calls[-1][0],'relax_stroke');self.assertEqual(len(self.api.undo_stack),1)
        self.api.undo();self.assertEqual(self.api.snapshot(),before)
    def test_shift_temporarily_relaxes_for_all_native_operations_without_changing_them(self):
        for operation in ('replace','add','scale'):
            with self.subTest(operation=operation):
                self.session.brush_operation=operation;before=self.api.snapshot()
                self.assertFalse(self.mouse(QtCore.QEvent.MouseButtonPress,shift=False))
                self.assertTrue(self.press());self.assertTrue(self.release());self.assertEqual(self.session.brush_operation,operation)
                self.api.undo();self.assertEqual(self.api.snapshot(),before);self.session.prepare()
    def test_regular_relax_does_not_finish_on_a_shift_key_release(self):
        self.session.brush_operation='relax';self.assertTrue(self.mouse(QtCore.QEvent.MouseButtonPress,shift=False))
        self.key(QtCore.Qt.Key_Shift,QtCore.QEvent.KeyRelease);self.assertTrue(self.controller.dragging)
        self.release(False);self.assertEqual(len(self.api.calls),1)
    def test_selected_relax_preserves_native_b_radius_shortcut_and_escape_cancel(self):
        self.session.brush_operation='relax';before=self.api.snapshot()
        self.assertFalse(self.key(QtCore.Qt.Key_B));self.assertFalse(self.mouse(QtCore.QEvent.MouseButtonPress,shift=False))
        self.key(QtCore.Qt.Key_B,QtCore.QEvent.KeyRelease)
        self.assertTrue(self.mouse(QtCore.QEvent.MouseButtonPress,shift=False));self.assertTrue(self.key(QtCore.Qt.Key_Escape));self.release(False)
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.calls,[])
    def test_escape_discards_preview_and_consumes_remaining_release(self):
        before=self.api.snapshot();self.press();self.assertTrue(self.key(QtCore.Qt.Key_Escape))
        self.assertEqual(self.session.values,[0.,1.,1.]);self.assertTrue(self.release())
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.calls,[]);self.assertEqual(self.api.undo_stack,[])
    def test_releasing_shift_finishes_once_and_never_forwards_a_pressless_drag(self):
        self.press();self.assertFalse(self.key(QtCore.Qt.Key_Shift,QtCore.QEvent.KeyRelease))
        self.assertTrue(self.mouse(QtCore.QEvent.MouseMove,(24,20),shift=False));self.assertTrue(self.release(False))
        self.assertEqual(len(self.api.calls),1);self.assertEqual(self.session.last_stroke['commit_reason'],'shift_release')
    def test_b_shortcut_has_priority_over_shift_relax_and_queues_radius_sync(self):
        sync=mock.Mock();self.session.on_brush_settings=sync
        self.assertFalse(self.key(QtCore.Qt.Key_B));self.assertFalse(self.press())
        self.api.context_settings['radius']=3.25
        self.key(QtCore.Qt.Key_B,QtCore.QEvent.KeyRelease);self.app.processEvents()
        self.assertFalse(sync.called)
        self.release();self.app.processEvents()
        self.assertEqual(sync.call_count,1);self.assertEqual(self.api.calls,[])
    def test_radius_sync_is_not_scheduled_for_unrelated_ui_clicks(self):
        other=QtWidgets.QWidget();sync=mock.Mock();self.session.on_brush_settings=sync
        event=QtGui.QMouseEvent(QtCore.QEvent.MouseButtonRelease,QtCore.QPointF(0,0),QtCore.QPointF(0,0),QtCore.Qt.LeftButton,QtCore.Qt.NoButton,QtCore.Qt.NoModifier)
        self.controller.eventFilter(other,event);self.app.processEvents();self.assertFalse(sync.called);other.deleteLater()
    def test_unbound_or_readonly_display_never_starts_a_relax_edit(self):
        self.session.readonly=True;self.assertFalse(self.press());self.assertEqual(self.api.calls,[])
    def test_no_hit_stroke_creates_no_command_and_restores_original_array(self):
        self.hit=False;before=self.api.snapshot();self.press();self.release()
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.calls,[]);self.assertEqual(self.session.values,[0.,1.,1.])
    def test_stale_state_rejects_commit_and_releases_gesture(self):
        self.press();self.api.state=core.edit(self.api.state,'properties',dict(layer=self.api.layer,name='Renamed elsewhere'))
        self.release();self.assertFalse(self.controller.drawing);self.assertFalse(self.session._committing)
        self.assertTrue(any('changed' in warning for warning in self.api.warnings));self.assertEqual(self.api.undo_stack,[])
        self.assertEqual(self.session.values,[0.,1.,1.])
    def test_failed_backend_commit_restores_preview_and_does_not_leave_undo_open(self):
        before=self.api.snapshot();self.press();self.api.fail=True;self.release()
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.session.values,[0.,1.,1.])
        self.assertFalse(self.controller.drawing);self.assertFalse(self.session._committing);self.assertIsNone(self.api._chunk)
    def test_tool_cleanup_finishes_pending_custom_stroke_and_keeps_incoming_tool(self):
        self.press();self.api.tool='selectSuperContext';self.session.tool_cleanup()
        self.assertEqual(self.api.tool,'selectSuperContext');self.assertEqual(len(self.api.calls),1)
        self.assertIsNone(self.session.brush);self.assertTrue(self.controller.closed);self.assertFalse(self.session.active)
    def test_cancel_on_history_shortcut_allows_native_undo_and_discards_preview(self):
        self.press();self.assertFalse(self.key(QtCore.Qt.Key_Z,mods=QtCore.Qt.ControlModifier))
        self.assertEqual(self.api.calls,[]);self.assertEqual(self.session.values,[0.,1.,1.]);self.assertTrue(self.release(False))
    def test_native_callbacks_during_custom_preview_do_not_open_a_second_stroke(self):
        self.press();self.session.before_stroke();self.session.set_value(1,0,.9);self.session.after_stroke()
        self.assertIsNone(self.session.stroke);self.assertEqual(self.api.calls,[]);self.release()
        self.assertEqual(len(self.api.calls),1)
    def test_mask_shift_relax_saves_mask_without_changing_authored_weights(self):
        self.api.state=core.edit(self.api.state,'paint',dict(layer=self.api.layer,mode='mask',values={'0':0.}))
        self.api.weights=core.composite(self.api.state);samples=self.api.state['layers'][0]['samples']
        self.session.start('mesh',self.api.layer,mode='mask');self.controller=self.session.brush
        self.press();self.release()
        self.assertEqual(self.api.state['layers'][0]['mask']['0'],.5);self.assertEqual(self.api.state['layers'][0]['samples'],samples)
    def test_exit_disarms_the_controller_without_native_or_widget_cleanup_calls(self):
        self.press();self.api.events=[];self.api.calls=[]
        self.session.maya_exit();self.assertTrue(self.controller.closed);self.assertFalse(self.controller.drawing)
        self.assertEqual(self.api.events,[]);self.assertEqual(self.api.calls,[])

    def test_shift_never_adds_a_painted_qt_child_over_the_viewport(self):
        children=self.widget.findChildren(QtWidgets.QWidget)
        self.press()
        for x in range(21,61):self.mouse(QtCore.QEvent.MouseMove,(x,20))
        self.assertEqual(self.widget.findChildren(QtWidgets.QWidget),children)
        self.assertTrue(self.api.context_settings['outline'])
        self.release();self.assertEqual(self.widget.findChildren(QtWidgets.QWidget),children)

    def test_native_outline_receives_only_buttonless_hover_without_reentering_relax(self):
        self.native_events=[];self.press();stamps=self.controller.transaction.stamps
        self.assertEqual(len(self.native_events),1)
        self.mouse(QtCore.QEvent.MouseMove,(24,20))
        self.assertEqual(len(self.native_events),3) # Initial point + two interpolated stamps.
        self.assertGreater(self.controller.transaction.stamps,stamps)
        self.assertTrue(all(event==(QtCore.QEvent.MouseMove,QtCore.Qt.NoButton,QtCore.Qt.NoButton,QtCore.Qt.NoModifier) for event in self.native_events))
        self.assertEqual(self.api.calls,[]);self.assertIsNone(self.session.stroke)
        self.release();self.assertEqual(len(self.api.calls),1);self.assertEqual(len(self.api.undo_stack),1)
        self.assertEqual(self.controller.report()['feedback_backend'],'Maya Artisan outline')

    def test_native_callbacks_during_hover_cannot_create_a_native_authoring_stroke(self):
        self.probe_callbacks=True;self.press();self.mouse(QtCore.QEvent.MouseMove,(24,20))
        self.assertEqual(len(self.native_events),3);self.assertIsNone(self.session.stroke);self.assertIsNone(self.api._chunk)
        self.assertEqual(self.api.calls,[]);self.assertLess(self.session.values[0],.99)
        self.release();self.assertEqual(len(self.api.calls),1);self.assertIsNone(self.api._chunk)

    def test_no_hit_release_and_cancel_request_native_redraw(self):
        self.hit=False;self.press();self.assertEqual(self.api.calls,[])
        before=self.redraws;self.release();self.assertGreater(self.redraws,before)
        self.press();before=self.redraws;self.key(QtCore.Qt.Key_Escape)
        self.assertGreater(self.redraws,before);self.release();self.assertEqual(self.api.calls,[])

    def test_unchanged_stroke_distinguishes_missed_mesh_from_no_vertices_in_radius(self):
        self.hit=False;self.press();self.release()
        self.assertIn('did not hit',self.session.last_stroke['unchanged_reason'])
        self.assertEqual(self.session.last_stroke['mesh_hits'],0)
        self.hit=True;geometry=self.viewport.geometry(None,None);geometry.ray=lambda point:((0,0,0),{})
        with mock.patch.object(self.viewport,'geometry',return_value=geometry):self.press()
        self.release();report=self.session.last_stroke
        self.assertIn('Increase Brush radius',report['unchanged_reason'])
        self.assertGreater(report['mesh_hits'],0);self.assertEqual(report['footprint_vertices'],0)
        self.assertEqual(self.api.calls,[])

    def test_hover_failure_discards_preview_and_releases_forwarding_guard(self):
        before=self.api.snapshot();self.feedback_failure=True;self.press()
        self.assertFalse(self.controller.drawing);self.assertFalse(self.controller._feedback_active)
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.session.values,[0.,1.,1.])
        self.assertTrue(any('native hover failed' in text for text in self.api.warnings))
        self.release();self.feedback_failure=False;self.press();self.release()
        self.assertEqual(len(self.api.undo_stack),1)

    def test_tool_handoff_during_native_feedback_finishes_once_without_redraw_reentry(self):
        self.press()
        def handoff(point):
            self.api.tool='selectSuperContext';self.session.tool_cleanup();return True
        with mock.patch.object(self.viewport,'feedback',side_effect=handoff):self.mouse(QtCore.QEvent.MouseMove,(24,20))
        self.assertEqual(self.api.tool,'selectSuperContext');self.assertFalse(self.session.active)
        self.assertTrue(self.controller.closed);self.assertFalse(self.controller._feedback_active)
        self.assertIsNone(self.session.brush);self.assertEqual(len(self.api.undo_stack),1)
        self.assertIsNone(self.api._chunk);self.assertEqual(self.api.warnings,[])
    def test_tool_handoff_on_first_outline_does_not_build_geometry_or_start_an_edit(self):
        def handoff(point):
            self.api.tool='selectSuperContext';self.session.tool_cleanup();return True
        with mock.patch.object(self.viewport,'feedback',side_effect=handoff):self.press()
        self.assertEqual(self.builds,0);self.assertFalse(self.controller.dragging)
        self.assertIsNone(self.controller.geometry);self.assertEqual(self.api.undo_stack,[])
        self.assertEqual(self.api.warnings,[]);self.assertIsNone(self.session.brush)
    def test_outline_moves_before_geometry_radius_sampling_on_press_and_drag(self):
        events=[];original=self.viewport.geometry
        def hover(point):events.append('hover');return True
        def geometry(ctx,radius):
            events.append('geometry');result=original(ctx,radius)
            result.update_radius=lambda:events.append('radius');return result
        with mock.patch.object(self.viewport,'feedback',side_effect=hover),mock.patch.object(self.viewport,'geometry',side_effect=geometry):
            self.press();self.assertEqual(events,['hover','geometry'])
            self.mouse(QtCore.QEvent.MouseMove,(24,20));self.assertEqual(events,['hover','geometry','hover','radius','hover','radius'])
        self.release();self.assertEqual(len(self.api.undo_stack),1)
    def test_interpolated_stamps_query_radius_at_each_sample_not_at_drag_endpoint(self):
        cursor=[None];samples=[];radius_queries=[];original=self.viewport.geometry
        def hover(point):cursor[0]=tuple(point);return True
        def geometry(ctx,radius):
            result=original(ctx,radius);ray=result.ray
            def update():radius_queries.append(cursor[0])
            def hit(point):
                samples.append((tuple(point),cursor[0]));return ray(point)
            result.update_radius=update;result.ray=hit;return result
        with mock.patch.object(self.viewport,'feedback',side_effect=hover),mock.patch.object(self.viewport,'geometry',side_effect=geometry):
            self.press();self.mouse(QtCore.QEvent.MouseMove,(30,20))
        self.assertEqual([point for point,outline in samples],[(20,20),(22,20),(24,20),(26,20),(28,20),(30,20)])
        self.assertTrue(all(point==outline for point,outline in samples),samples)
        self.assertEqual(radius_queries,[(22,20),(24,20),(26,20),(28,20),(30,20)])
        self.release();self.assertEqual(len(self.api.undo_stack),1)

    def test_cursor_motion_without_a_stamp_still_moves_the_outline(self):
        moves=[]
        with mock.patch.object(self.viewport,'feedback',side_effect=lambda point:moves.append(tuple(point)) or True):
            self.press();stamps=self.controller.transaction.stamps
            self.mouse(QtCore.QEvent.MouseMove,(21,20))
            self.assertEqual(self.controller.transaction.stamps,stamps)
            self.assertEqual(moves,[(20,20),(21,20)])
        self.release()
    def test_moving_footprint_keeps_halo_and_previous_stamp_fixed_then_commits_one_undo(self):
        self.api.state=core.edit(self.api.state,'paint',dict(layer=self.api.layer,mode='weights',joint='b',values={'2':0.}))
        self.api.weights=core.composite(self.api.state);self.session.prepare()
        geometry=self.viewport.geometry(None,None);scope={0:1.}
        geometry.ray=lambda point:((0,0,0),dict(scope))
        geometry.report=lambda:dict(world_radius=1.,radius_source='worldRadius',neighbor_halo='read only')
        before=self.api.snapshot();weights=list(self.api.weights)
        with mock.patch.object(self.viewport,'geometry',return_value=geometry):self.press()
        first=self.session.values[0];scope.clear();scope[2]=1.
        self.mouse(QtCore.QEvent.MouseMove,(24,20))
        self.assertEqual(self.session.values[0],first);self.assertEqual(self.session.values[1],1.)
        self.release();self.assertEqual(len(self.api.undo_stack),1)
        self.assertEqual(self.api.weights[2:4],weights[2:4])
        self.assertEqual(self.controller.report()['footprint']['neighbor_halo'],'read only')
        self.assertEqual(self.session.last_stroke['footprint']['radius_source'],'worldRadius')
        self.api.undo();self.assertEqual(self.api.snapshot(),before)
    def test_sparse_patch_updates_center_neighbor_and_native_array_during_drag_then_persists(self):
        self.session.stop()
        state=core.edit(core.create([1.,0.]*3,3,['a','b'],'topology'),'add',dict(name='Paint patch'))
        self.api.layer=state['layers'][0]['id']
        self.api.state=core.edit(state,'paint',dict(layer=self.api.layer,mode='weights',joint='b',values={'0':1.}))
        self.api.weights=core.composite(self.api.state)
        self.session.relax_settings=lambda:dict(strength=.5,iterations=1)
        self.session.start('mesh',self.api.layer,joint='b',mode='weights');self.controller=self.session.brush
        geometry=self.viewport.geometry(None,None);geometry.ray=lambda point:((0.,0.,0.),{0:1.,1:1.})
        before=self.api.snapshot()
        with mock.patch.object(self.viewport,'geometry',return_value=geometry):self.press()
        self.assertEqual(self.session.values,[.5,.25,0.]);self.assertEqual(self.api.paint_buffer.read(),[.5,.25,0.])
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.calls,[])
        self.assertGreater(self.redraws,0)
        self.release();self.assertTrue(self.session.last_stroke['layer_values_verified'])
        self.session.start('mesh',self.api.layer,joint='a',mode='weights')
        self.session.start('mesh',self.api.layer,joint='b',mode='weights')
        self.assertEqual(self.api.paint_buffer.read(),[.5,.25,0.]);self.assertEqual(len(self.api.undo_stack),1)
        self.api.undo();self.assertEqual(self.api.snapshot(),before)


@unittest.skipIf(view_module is None,'PySide is required')
class NativeFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def test_native_feedback_preserves_child_local_window_and_global_coordinates(self):
        log=[]
        class Receiver(QtWidgets.QWidget):
            def mouseMoveEvent(self,event):
                local=event.position() if hasattr(event,'position') else event.localPos()
                global_point=event.globalPosition() if hasattr(event,'globalPosition') else event.screenPos()
                log.append((local,global_point,event.button(),event.buttons(),event.modifiers()))
        parent=QtWidgets.QWidget();parent.resize(100,100);parent.show()
        receiver=Receiver(parent);receiver.setGeometry(5,10,80,80);receiver.setMouseTracking(True);receiver.show()
        try:
            view=view_module.NativeView(None,None,parent,receiver)
            self.assertTrue(view.feedback((25.25,30.5)));self.assertEqual(len(log),1)
            self.assertEqual(log[0][0],QtCore.QPointF(20.25,20.5))
            expected=QtCore.QPointF(parent.mapToGlobal(QtCore.QPoint(0,0)))+QtCore.QPointF(25.25,30.5)
            # QApplication may round screen coordinates to the physical pixel.
            self.assertLessEqual(abs(log[0][1].x()-expected.x()),.5)
            self.assertLessEqual(abs(log[0][1].y()-expected.y()),.5)
            self.assertEqual(log[0][2:],(QtCore.Qt.NoButton,QtCore.Qt.NoButton,QtCore.Qt.NoModifier))
        finally:parent.close();parent.deleteLater();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
    def test_input_point_keeps_fractional_coordinates_before_high_dpi_conversion(self):
        widget=QtWidgets.QWidget();widget.move(20,30);widget.show()
        try:
            origin=QtCore.QPointF(widget.mapToGlobal(QtCore.QPoint(0,0)))
            event=types.SimpleNamespace(globalPosition=lambda:origin+QtCore.QPointF(10.25,20.75))
            self.assertEqual(view_module.NativeView(None,None,widget).point(event),(10.25,20.75))
        finally:widget.deleteLater();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
    def test_deleted_viewport_receiver_does_not_receive_feedback(self):
        widget=QtWidgets.QWidget();view=view_module.NativeView(None,None,widget)
        widget.deleteLater();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        self.assertFalse(view.feedback((10,10)))
    def test_color_handoff_and_existing_disabled_updates_defer_forced_brush_redraw(self):
        widget=QtWidgets.QWidget();native=mock.Mock();session=types.SimpleNamespace(display_transition_active=True)
        view=view_module.NativeView(session,native,widget)
        try:
            self.assertFalse(view.redraw(force=True));native.refresh.assert_not_called();native.scheduleRefresh.assert_not_called()
            session.display_transition_active=False;widget.setUpdatesEnabled(False)
            self.assertFalse(view.redraw(force=True));native.refresh.assert_not_called()
            widget.setUpdatesEnabled(True);self.assertTrue(view.redraw(force=True));native.refresh.assert_called_once_with(False,True)
        finally:widget.deleteLater();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
    def test_changed_preview_redraws_without_waiting_for_maya_idle_and_is_throttled(self):
        widget=QtWidgets.QWidget();native=mock.Mock();view=view_module.NativeView(None,native,widget)
        try:
            with mock.patch.object(view_module.time,'monotonic',side_effect=[0.,.001,.04,.041]):
                view.redraw();view.redraw();view.redraw();view.redraw(force=True)
            self.assertEqual(native.refresh.call_args_list,[mock.call(False,True)]*3)
            native.scheduleRefresh.assert_called_once()
        finally:widget.deleteLater();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
    def test_native_redraw_reentry_and_failure_do_not_leave_a_busy_guard(self):
        widget=QtWidgets.QWidget();native=mock.Mock();view=view_module.NativeView(None,native,widget)
        try:
            native.refresh.side_effect=lambda *args:view.redraw(force=True)
            view.redraw(force=True);self.assertEqual(native.refresh.call_count,1)
            native.refresh.side_effect=RuntimeError('redraw failed')
            with self.assertRaisesRegex(RuntimeError,'redraw failed'):view.redraw(force=True)
            native.refresh.side_effect=None;view.redraw(force=True)
            self.assertEqual(native.refresh.call_count,3);self.assertFalse(view._redrawing)
        finally:widget.deleteLater();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)


@unittest.skipIf(view_module is None,'PySide is required')
class NativeViewContractTests(unittest.TestCase):
    def geometry(self,points=None,radius=1.,world_radius=1.,perspective=False,clipped=(),native_screen_radius=None):
        class Vector:
            def __init__(self,*args):
                self.x,self.y,self.z=(args[0].x,args[0].y,args[0].z) if len(args)==1 else (args or (0.,0.,0.))
            def normalize(self):return self
            def __mul__(self,value):
                if not isinstance(value,(float,int)):return Vector(self)
                return Vector(self.x*value,self.y*value,self.z*value)
            def __add__(self,value):return Vector(self.x+value.x,self.y+value.y,self.z+value.z)
        log=[]
        class View:
            def portWidth(self):return 800
            def portHeight(self):return 400
            def modelViewMatrix(self):return types.SimpleNamespace(inverse=lambda:None)
            def worldToView(self,p):
                log.append(('project',p.x,p.y,p.z))
                depth=(1.-p.z) if perspective else 1.
                return round(400+100*p.x/depth),round(200+100*p.y/depth),(p.x,p.y,p.z) not in clipped
            def viewToWorld(self,x,y,origin,direction):
                log.append(('ray',x,y));origin.z=1.;direction.z=-1.
        points=points or [(-.2,0,0),(0,0,0),(.2,0,0)]
        class Mesh:
            def getPoints(self,space):
                raise AssertionError('Full mesh position read')
            def getPoint(self,v,space):
                log.append(('point',v,space));return Vector(*points[v])
            def autoUniformGridParams(self):return 'accelerator'
            def closestIntersection(self,origin,direction,space,maxParam,both,*,accelParams):
                log.append(('intersection',space,both,accelParams));return Vector(0,0,0),1.,0,0,0,0
            def getPolygonVertices(self,face):return list(range(len(points)))
        import layer_skin_brush
        def query(name,query,**flags):
            if 'screenRadius' in flags:
                if isinstance(native_screen_radius,Exception):raise native_screen_radius
                return native_screen_radius
            if 'worldRadius' in flags:
                if isinstance(world_radius,Exception):raise world_radius
                return world_radius
            return radius
        cmd=mock.Mock(side_effect=query)
        om=types.SimpleNamespace(MDistance=mock.Mock(side_effect=AssertionError('No UI-unit radius conversion')),
            MFnMesh=lambda path:Mesh(),MItMeshVertex=lambda path:types.SimpleNamespace(
            setIndex=lambda v:None,getConnectedVertices=lambda:list(range(len(points)))),MSpace=types.SimpleNamespace(kWorld=4),
            MPoint=Vector,MVector=Vector,MFloatPoint=lambda v:v,MFloatVector=lambda v:v)
        session=types.SimpleNamespace(api=types.SimpleNamespace(om=om,cmds=types.SimpleNamespace(artUserPaintCtx=cmd),paint_context='paint'),helper=lambda name:layer_skin_brush)
        viewport=types.SimpleNamespace(session=session,view=View(),widget=types.SimpleNamespace(width=lambda:400,height=lambda:200))
        return view_module.NativeGeometry(viewport,dict(dag='mesh'),radius),log,cmd
    def test_native_ray_uses_documented_output_arguments_and_high_dpi_port_coordinates(self):
        geometry,log,cmd=self.geometry()
        center,factors=geometry.ray((10,10))
        self.assertIn(('ray',20,379),log);self.assertIn(('intersection',4,False,'accelerator'),log)
        self.assertEqual(center,(0,0,0));self.assertEqual(set(factors),{0,1,2});self.assertIsNone(geometry.ray((-1,0)))
    def test_world_radius_takes_precedence_without_scene_unit_conversion(self):
        geometry,log,cmd=self.geometry([(0,0,0),(.5,0,0),(1.5,0,0)],radius=100.,world_radius=1.)
        self.assertEqual(set(geometry.ray((200,100))[1]),{0,1})
        self.assertEqual(geometry.radius,1.);self.assertEqual(geometry.report()['radius_source'],'worldRadius')
        self.assertEqual(geometry.report()['projected_radius_pixels'],100.)
        self.assertEqual(geometry.screen_radius((0,0,0)),50.)
    def test_invalid_or_unavailable_world_radius_falls_back_to_raw_radius(self):
        for value in (None,0.,float('nan'),float('inf'),RuntimeError('unsupported query')):
            with self.subTest(value=value):
                geometry,log,cmd=self.geometry(radius=.25,world_radius=value)
                self.assertEqual(geometry.radius,.25);self.assertEqual(geometry.report()['radius_source'],'radius')
                self.assertEqual(set(geometry.ray((200,100))[1]),{0,1,2})
    def test_perspective_foreground_vertex_inside_world_sphere_outside_circle_is_excluded(self):
        geometry,log,cmd=self.geometry([(0,0,0),(.2,0,.5),(.6,0,.6)],perspective=True)
        factors=geometry.ray((200,100))[1]
        self.assertEqual(set(factors),{0,1});self.assertAlmostEqual(factors[1],.5041)
        self.assertLess(sum(value*value for value in geometry.points[2]),geometry.radius**2)
    def test_exact_projected_edge_and_clipped_vertices_are_excluded_at_high_dpi(self):
        geometry,log,cmd=self.geometry([(0,0,0),(.49,0,.5),(.5,0,.5),(.51,0,.5),(.1,0,0)],
            perspective=True,clipped=[(.1,0,0)])
        factors=geometry.ray((200,100))[1]
        self.assertEqual(set(factors),{0,1});self.assertLess(factors[1],.002)
        self.assertEqual(geometry.screen_radius((0,0,0)),50.)
    def test_repeated_rays_cache_candidate_projections_without_scanning_all_vertices(self):
        geometry,log,cmd=self.geometry([(0,0,0),(.2,0,0),(100,0,0)])
        geometry.ray((200,100));first=len([row for row in log if row[0]=='project'])
        geometry.ray((200,100));second=len([row for row in log if row[0]=='project'])
        self.assertEqual(second-first,2) # Only this stamp's center and radius reference.
        self.assertEqual(geometry.report()['projected_vertices'],2)
        self.assertEqual(len([row for row in log if row[0]=='point']),3)
    def test_subpixel_projection_does_not_expand_the_native_world_radius(self):
        geometry,log,cmd=self.geometry([(0,0,0),(.0005,0,0),(.001,0,0),(.002,0,0)],radius=.001,world_radius=.001)
        self.assertEqual(set(geometry.ray((200,100))[1]),{0,1})
        self.assertAlmostEqual(geometry.report()['projected_radius_pixels'],.1,places=3)
        self.assertEqual(geometry.radius,.001)
    def test_native_radius_changes_reuse_mesh_and_hash_but_change_footprint(self):
        geometry,log,cmd=self.geometry([(0,0,0),(.5,0,0),(1.5,0,0)])
        points=geometry.points;grid=geometry.grid
        self.assertEqual(set(geometry.ray((200,100))[1]),{0,1})
        cmd.side_effect=lambda *args,**kwargs:None if kwargs.get('screenRadius') else 2.
        geometry.update_radius();self.assertEqual(set(geometry.ray((200,100))[1]),{0,1,2})
        self.assertIs(geometry.points,points);self.assertIs(geometry.grid,grid)

    def test_native_screen_circle_bounds_a_larger_reconstructed_world_circle(self):
        geometry,log,cmd=self.geometry([(0,0,0),(.2,0,0),(.3,0,0),(.6,0,0)],native_screen_radius=30.)
        # The world radius projects to 100 px, but Maya's outline is only 30 px.
        # All four points fit the world sphere; only the first two fit the brush.
        self.assertEqual(set(geometry.ray((200,99.5))[1]),{0,1})
        self.assertEqual(geometry.screen_radius((0,0,0)),15.) # 2x device pixels.
        report=geometry.report()
        self.assertEqual(report['native_screen_radius_pixels'],30.)
        self.assertEqual(report['effective_screen_radius_pixels'],30.)
        self.assertEqual(report['screen_radius_source'],'screenRadius')

    def test_native_screen_clip_uses_the_sample_cursor_not_rounded_hit_projection(self):
        geometry,log,cmd=self.geometry([(0,0,0),(.3,0,0),(.6,0,0)],native_screen_radius=30.)
        # Hit projection is (400,200) in this recorder; this stamp is at (430,200).
        # A lagging/reprojected hit center must not define the native circle.
        self.assertEqual(set(geometry.ray((215,99.5))[1]),{1})

    def test_native_screen_radius_never_expands_the_world_bound(self):
        geometry,log,cmd=self.geometry([(0,0,0),(.5,0,0),(1.,0,0),(1.1,0,0)],native_screen_radius=200.)
        self.assertEqual(set(geometry.ray((200,99.5))[1]),{0,1})
        self.assertEqual(geometry.report()['effective_screen_radius_pixels'],100.)

    def test_missing_or_invalid_native_screen_radius_retains_world_fallback(self):
        for value in (None,0.,float('nan'),float('inf'),RuntimeError('unsupported query')):
            with self.subTest(value=value):
                geometry,log,cmd=self.geometry([(0,0,0),(.5,0,0),(1.,0,0)],native_screen_radius=value)
                self.assertEqual(set(geometry.ray((200,99.5))[1]),{0,1})
                self.assertIsNone(geometry.report()['native_screen_radius_pixels'])
                self.assertEqual(geometry.report()['screen_radius_source'],'projected world radius')

    def test_screen_clipped_vertices_stay_outside_preview_payload_and_native_dirty_rows(self):
        import layer_skin_brush,layer_skin_relax
        from test_layer_skin_relax import layer_state
        points=[(0,0,0),(.2,0,0),(.3,0,0),(.6,0,0)]
        for mode in ('weights','mask'):
            with self.subTest(mode=mode):
                geometry,log,cmd=self.geometry(points,native_screen_radius=30.)
                geometry.neighbors=lambda v:tuple(u for u in range(4) if u!=v)
                factors=geometry.ray((200,99.5))[1]
                state,layer=layer_state([[1.,0.],[0.,1.],[.9,.1],[.8,.2]])
                state=core.edit(state,'paint',dict(layer=layer,mode='mask',values={'0':0.,'1':.5,'2':.9}))
                stroke=layer_skin_brush.RelaxStroke(state,layer,mode,dict(strength=.7,iterations=20),layer_skin_relax)
                for _ in range(10):stroke.stamp(factors,geometry.neighbors)
                payload=stroke.payload()
                self.assertEqual(set(payload['samples' if mode=='weights' else 'values']),{'0','1'})
                result,dirty,_=layer_skin_relax.prepare_stroke({},state,payload,core)
                self.assertEqual(dirty,[0,1])
                before=core.composite(state);after=core.composite(result)
                self.assertEqual(after[4:],before[4:])

    def test_screen_radius_changes_keep_the_same_mesh_hash_and_tighten_the_clip(self):
        geometry,log,cmd=self.geometry([(0,0,0),(.2,0,0),(.6,0,0)],native_screen_radius=80.)
        grid=geometry.grid;points=geometry.points
        self.assertEqual(set(geometry.ray((200,99.5))[1]),{0,1,2})
        cmd.side_effect=lambda *args,**flags:30. if flags.get('screenRadius') else 1.
        geometry.update_radius()
        self.assertEqual(set(geometry.ray((200,99.5))[1]),{0,1})
        self.assertIs(geometry.grid,grid);self.assertIs(geometry.points,points)
