"""Cached native stroke starts, shortcut-only radius changes and Q/Y recovery."""
import hashlib
import sys
import types
import unittest
from unittest import mock

import layer_skin_core as core
import layer_skin_session as sessions
import layer_skin_relax as relax
from test_layer_skin_session import FakeAPI
import test_layer_skin_component_selection as components
import test_layer_skin_brush_view as brush_tests
from test_layer_skin_brush_radius import no_mesh_work,native_settings_callbacks

ui=components.ui
if ui is not None:
    QtCore,QtWidgets=ui.QtCore,ui.QtWidgets
    QtGui=components.brush_module.QtGui
    QtTest=components.QtTest


class StagedStrokeTests(unittest.TestCase):
    def setUp(self):
        self.api=FakeAPI();self.session=sessions.Session(self.api)
        self.session.start('mesh',self.api.layer,'b','weights')
    def tearDown(self):self.session.close();sys.modules.pop(sessions.BRIDGE,None)

    def test_stroke_start_reuses_staged_state_without_skin_reads_or_encoding(self):
        values=self.session.values;state=self.session.state;expected=self.session._state_hash
        with no_mesh_work(self.session,self.api):self.session.before_stroke()
        self.assertIs(self.session.state,state);self.assertIs(self.session.stroke['baseline'],values)
        self.assertEqual(self.session.stroke['expected'],expected);self.assertEqual(self.api.calls,[])
        self.assertEqual(self.api._chunk_depth,1)

    def test_passive_surface_and_array_callbacks_do_not_arm_empty_strokes(self):
        self.session.can_begin_stroke=lambda:False
        with no_mesh_work(self.session,self.api),mock.patch.object(self.api.cmds,'ls',side_effect=AssertionError('Alias lookup repeated')),mock.patch.object(self.api.cmds,'listRelatives',side_effect=AssertionError('Parent query repeated')):
            for _ in range(200):
                for alias in ('mesh','meshShape','mesh.vtx[1]'):
                    self.assertEqual(self.session.surface(alias),'meshShape')
                    self.assertEqual(self.session.array_attribute(alias),'paintBuffer.values')
        self.assertIsNone(self.session.stroke);self.assertEqual(self.api._chunk_depth,0)

    def test_metadata_changed_after_staging_is_rejected_then_reloaded(self):
        self.api.state=core.edit(self.api.state,'properties',dict(layer=self.api.layer,name='External rename'))
        before=self.api.snapshot();self.session.before_stroke();self.api.paint_buffer.write([.6,0.,0.])
        with self.assertRaisesRegex(RuntimeError,'Layer data changed'):self.session.after_stroke()
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.undo_stack,[])
        self.assertEqual(self.api._chunk_depth,0);self.assertEqual(self.session.last_stroke['status'],'rejected')
        self.session.before_stroke();self.api.paint_buffer.write([.6,0.,0.]);self.session.after_stroke()
        self.assertEqual(self.session.values,[.6,0.,0.]);self.assertEqual(len(self.api.undo_stack),1)

    def test_cached_hash_uses_remapped_state_instead_of_raw_metadata(self):
        raw=core.encode(self.api.state);self.api.ids.reverse();self.api.weights=[0.,1.]*3
        original=self.api.metadata
        def metadata(ctx):ctx['raw_metadata']=raw;return original(ctx)
        with mock.patch.object(self.api,'metadata',side_effect=metadata):self.session.prepare()
        expected=hashlib.sha256(core.encode(core.remap(self.api.state,self.api.ids)).encode()).hexdigest()
        self.assertEqual(self.session._state_hash,expected)
        self.assertNotEqual(expected,hashlib.sha256(raw.encode()).hexdigest())
        self.session.before_stroke();self.api.paint_buffer.write([.6,0.,0.]);self.session.after_stroke()
        self.assertEqual(self.session.values,[.6,0.,0.]);self.assertEqual(len(self.api.undo_stack),1)

    def test_readonly_views_do_not_encode_and_unchanged_editable_state_reuses_its_hash(self):
        with mock.patch.object(core,'encode',side_effect=AssertionError('Unchanged state re-encoded')):
            self.session.prepare()
        self.api.state=core.edit(self.api.state,'properties',dict(layer=self.api.layer,name='New view'))
        self.session.readonly=True
        with mock.patch.object(core,'encode',side_effect=AssertionError('Readonly state encoded')):self.session.prepare()
        self.assertIsNone(self.session._state_hash);self.session.readonly=False
        with mock.patch.object(core,'encode',wraps=core.encode) as encode:self.session.prepare()
        self.assertEqual(encode.call_count,1);self.assertIsNotNone(self.session._state_hash)

    def test_undo_invalidates_staged_data_before_another_stroke(self):
        self.session.listen(lambda:None,lambda:None)
        self.session.before_stroke();self.api.paint_buffer.write([.6,0.,0.]);self.session.after_stroke()
        self.api.undo()
        for event,callback in self.api.callbacks.values():
            if event=='Undo':callback()
        self.assertTrue(self.session._paint_cache_dirty)
        with mock.patch.object(self.session,'snapshot',wraps=self.session.snapshot) as snapshot:self.session.before_stroke()
        self.assertEqual(snapshot.call_count,1);self.assertEqual(self.session.values,[0.]*3)
        self.assertFalse(self.session._paint_cache_dirty)

    def test_native_array_paint_changes_only_the_selected_vertices(self):
        before=self.api.snapshot();self.api.object_mode=False;self.api.paint_scope=lambda:frozenset({1})
        self.session.before_stroke();self.api.paint_buffer.write([.6,.8,.9]);self.session.after_stroke()
        self.assertEqual(self.session.values,[0.,.8,0.]);self.assertEqual(self.api.paint_buffer.read(),[0.,.8,0.])
        self.assertEqual(self.api.calls[-1][1]['values'],{'1':.8});self.assertEqual(len(self.api.undo_stack),1)
        self.api.undo();self.assertEqual(self.api.snapshot(),before)

    def test_scalar_callbacks_obey_the_same_selected_vertex_scope(self):
        self.api.object_mode=False;self.api.paint_scope=lambda:frozenset({1})
        self.session.before_stroke();self.session.set_value(1,0,.7);self.session.set_value(1,1,.8);self.session.after_stroke()
        self.assertEqual(self.api.calls[-1][1]['values'],{'1':.8});self.assertEqual(self.session.values,[0.,.8,0.])

    def test_invalid_component_scope_cannot_leak_unsaved_native_edits_into_the_next_stroke(self):
        self.api.object_mode=False;self.api.paint_scope=mock.Mock(side_effect=ValueError('Select vertices on the loaded mesh.'))
        before=self.api.snapshot()
        with self.assertRaisesRegex(ValueError,'Select vertices'):self.session.before_stroke()
        self.api.paint_buffer.write([.8,.8,.8])
        with self.assertRaisesRegex(RuntimeError,'Select vertices'):self.session.after_stroke()
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.paint_buffer.read(),[0.]*3)
        self.assertIsNone(self.session.stroke);self.assertEqual(self.api._chunk_depth,0)
        self.api.paint_scope=lambda:frozenset({1})
        self.session.before_stroke();self.api.paint_buffer.write([0.,.5,0.]);self.session.after_stroke()
        self.assertEqual(self.session.values,[0.,.5,0.]);self.assertEqual(len(self.api.undo_stack),1)

    def test_no_components_does_not_allocate_a_whole_mesh_scope_for_paint(self):
        selection=types.SimpleNamespace(length=lambda:0)
        om=types.SimpleNamespace(MGlobal=types.SimpleNamespace(getActiveSelectionList=lambda:selection))
        self.assertIsNone(relax.selected_scope({'count':100000000},om,all_if_empty=False))
        self.assertEqual(relax.selected_scope({'count':3},om),[0,1,2])

    def test_short_and_namespaced_surface_aliases_are_cached_without_ambiguity(self):
        target='|asset|ns:mesh|ns:meshShape';parent='|asset|ns:mesh'
        table={'ns:meshShape':[target],'ns:mesh':[parent],'ambiguous':[target,'|other|ns:meshShape']}
        def ls(name,**kw):return table.get(name,[name])
        def relatives(name,**kw):return [parent] if name==target and kw.get('parent') else [target] if name==parent and kw.get('shapes') else []
        with mock.patch.object(self.api.cmds,'ls',side_effect=ls),mock.patch.object(self.api.cmds,'listRelatives',side_effect=relatives):
            self.session._cache_surface(target);self.session.target=target
            self.assertEqual(self.session.surface('ambiguous'),'')
        with mock.patch.object(self.api.cmds,'ls',side_effect=AssertionError('Repeated resolution')),mock.patch.object(self.api.cmds,'listRelatives',side_effect=AssertionError('Repeated parent query')):
            for _ in range(100):
                for name in (target,parent,'ns:meshShape','ns:mesh','ns:mesh.vtx[1]'):
                    self.assertEqual(self.session.surface(name),target)
                self.assertEqual(self.session.surface('ambiguous'),'')
        self.session._cache_surface('meshShape');self.session.target='meshShape'
        self.assertNotIn('ns:mesh',self.session._surface_aliases)


@unittest.skipIf(ui is None,'PySide is required')
class PaintToolLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        self.case=components.ComponentSelectionTests();self.case.app=self.app;self.case.setUp()
        self.session=self.case.session;self.api=self.case.api;self.viewport=self.case.viewport;self.window=self.case.window
    def tearDown(self):self.case.tearDown()
    def event(self,name):self.case.mode_event(name)
    def shortcut(self,key=QtCore.Qt.Key_B if ui is not None else None,mods=None):
        event=QtGui.QKeyEvent(QtCore.QEvent.ShortcutOverride,key,QtCore.Qt.NoModifier if mods is None else mods)
        return self.session.brush.eventFilter(self.viewport,event)
    def pause(self):
        self.api.tool='selectSuperContext';self.session.tool_cleanup();self.event('ToolChanged');self.app.processEvents()

    def test_shortcut_override_without_keypress_arms_radius_and_defers_all_sync_queries(self):
        sync=mock.Mock(wraps=self.session.on_brush_settings);self.session.on_brush_settings=sync
        with no_mesh_work(self.session,self.api):
            self.assertFalse(self.shortcut());QtTest.QTest.mousePress(self.viewport,QtCore.Qt.LeftButton)
            for i in range(60):
                native_settings_callbacks(self.session);self.session.brush.queue_sync();self.app.processEvents()
                self.assertFalse(sync.called)
                self.api.context_settings['radius']=3.+i*.1
            QtTest.QTest.keyRelease(self.viewport,QtCore.Qt.Key_B);self.app.processEvents();self.assertFalse(sync.called)
            QtTest.QTest.mouseRelease(self.viewport,QtCore.Qt.LeftButton);self.app.processEvents()
        self.assertEqual(sync.call_count,1);self.assertAlmostEqual(self.window.brush_radius.value(),8.9)
        self.assertFalse(self.session.adjusting_brush);self.assertEqual(self.api.calls,[])

    def test_real_qt_shortcut_consumes_b_without_viewport_keypress_but_guard_is_ready(self):
        self.viewport.activateWindow();self.viewport.setFocus();self.app.processEvents()
        shortcut_class=getattr(QtGui,'QShortcut',None) or QtWidgets.QShortcut
        binding=shortcut_class(QtGui.QKeySequence('B'),self.viewport);binding.setContext(QtCore.Qt.WidgetShortcut)
        armed=[];binding.activated.connect(lambda:armed.append(self.session.adjusting_brush))
        with no_mesh_work(self.session,self.api):
            QtTest.QTest.keyPress(self.viewport,QtCore.Qt.Key_B);self.app.processEvents()
            self.assertEqual(armed,[True]);self.assertNotIn(QtCore.Qt.Key_B,self.case.native_keys)
            native_settings_callbacks(self.session)
            QtTest.QTest.keyRelease(self.viewport,QtCore.Qt.Key_B);self.app.processEvents()
        self.assertFalse(self.session.adjusting_brush);binding.deleteLater()

    def test_shortcut_override_does_not_intercept_modified_b_or_other_widgets(self):
        self.shortcut(mods=QtCore.Qt.ControlModifier);self.assertFalse(self.session.adjusting_brush)
        event=QtGui.QKeyEvent(QtCore.QEvent.ShortcutOverride,QtCore.Qt.Key_B,QtCore.Qt.NoModifier)
        self.assertFalse(self.session.brush.eventFilter(self.window.brush_radius,event))
        self.assertFalse(self.session.adjusting_brush)

    def test_window_shortcut_uses_focused_viewport_and_leaves_text_editor_shortcuts_alone(self):
        host=QtWidgets.QWidget();layout=QtWidgets.QVBoxLayout(host);layout.addWidget(self.viewport)
        editor=QtWidgets.QLineEdit();layout.addWidget(editor);self.viewport.setFocusPolicy(QtCore.Qt.StrongFocus)
        try:
            host.show();host.activateWindow();self.viewport.setFocus();self.app.processEvents()
            event=QtGui.QKeyEvent(QtCore.QEvent.ShortcutOverride,QtCore.Qt.Key_B,QtCore.Qt.NoModifier)
            self.assertFalse(self.session.brush.eventFilter(host,event));self.assertTrue(self.session.adjusting_brush)
            QtTest.QTest.keyRelease(self.viewport,QtCore.Qt.Key_B);self.app.processEvents()
            self.assertFalse(self.session.adjusting_brush)
            editor.setFocus();self.app.processEvents()
            event=QtGui.QKeyEvent(QtCore.QEvent.ShortcutOverride,QtCore.Qt.Key_B,QtCore.Qt.NoModifier)
            self.assertFalse(self.session.brush.eventFilter(host,event));self.assertFalse(self.session.adjusting_brush)
        finally:
            self.viewport.setParent(None);host.close();host.deleteLater();self.app.processEvents()

    def test_q_preserves_colors_and_y_restores_buffer_component_mode_and_brush_settings(self):
        before=self.api.snapshot();self.api.object_mode=False;self.api.selected=['mesh.vtx[1]']
        self.api.context_settings.update(radius=7.,opacity=.35,value=.6)
        self.pause();self.assertFalse(self.session.active);self.assertTrue(self.session.paint_armed)
        self.assertTrue(self.api.weight_view.visible);self.assertEqual(self.api.tool,'selectSuperContext')
        self.api.tool=self.api.paint_context;self.event('ToolChanged');self.session.tool_setup();self.app.processEvents()
        self.assertTrue(self.session.active);self.assertTrue(self.session.paint_armed)
        self.assertIs(self.api.paint_buffer.owner,self.session);self.assertEqual(self.api.tool,self.api.paint_context)
        self.assertEqual(self.api.selected,['mesh.vtx[1]','mesh']);self.assertFalse(self.api.object_mode)
        self.assertEqual([self.api.context_settings[k] for k in ('value','radius','opacity')],[.6,7.,.35])
        self.assertEqual([self.window.value.value(),self.window.brush_radius.value(),self.window.brush_opacity.value()],[.6,7.,.35])
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.session.context_starts,2)

    def test_q_alone_and_mode_events_never_force_the_brush_over_another_tool(self):
        self.pause();starts=self.session.context_starts
        self.api.object_mode=False;self.event('SelectModeChanged');QtTest.QTest.qWait(50)
        self.session.keep_paint_in_component_mode();self.session.tool_setup();self.app.processEvents()
        self.assertFalse(self.session.active);self.assertEqual(self.api.tool,'selectSuperContext')
        self.assertEqual(self.session.context_starts,starts)

    def test_queued_y_is_cancelled_when_user_switches_tool_before_it_runs(self):
        self.pause();self.api.tool=self.api.paint_context;self.event('ToolChanged')
        self.assertTrue(self.session._resume_queued);self.api.tool='moveSuperContext';self.app.processEvents()
        self.assertFalse(self.session.active);self.assertFalse(self.session._resume_queued)
        self.assertEqual(self.api.tool,'moveSuperContext')

    def test_stop_and_scene_reset_disarm_queued_resume(self):
        for action in (self.window.stop_paint,self.window.scene_reset):
            self.window.target.setText('mesh');self.window.refresh();self.window.paint();self.pause()
            self.api.tool=self.api.paint_context;self.event('ToolChanged');action();self.app.processEvents()
            self.assertFalse(self.session.paint_armed);self.assertFalse(self.session.active);self.assertIsNone(self.api.paint_buffer.owner)

    def test_y_checks_external_skin_edits_before_resuming(self):
        self.pause();saved=self.api.snapshot();self.api.weights=[.5,.5]*3
        self.api.tool=self.api.paint_context;self.event('ToolChanged');self.app.processEvents()
        self.assertFalse(self.session.active);self.assertFalse(self.session.paint_armed)
        self.assertEqual(self.api.tool,'selectSuperContext');self.assertEqual(self.api.state,saved[0])
        self.assertEqual(self.api.weights,[.5,.5]*3);self.assertTrue(any('outside Layer Skin' in w for w in self.api.warnings))

    def test_component_sync_queued_by_shortcut_does_not_restore_paint_after_q(self):
        self.shortcut(QtCore.Qt.Key_F9);self.pause();self.app.processEvents()
        self.assertEqual(self.api.tool,'selectSuperContext');self.assertFalse(self.session.active)

    def test_shift_relax_intersects_the_brush_with_selected_vertices(self):
        self.window.close();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        case=brush_tests.BrushViewTests();case.app=self.app;case.setUp()
        try:
            case.api.object_mode=False;case.api.paint_scope=lambda:frozenset({1})
            original=case.viewport.geometry
            def geometry(ctx,radius):
                result=original(ctx,radius);result.ray=lambda point:((0.,0.,0.),{0:1.,1:1.});return result
            case.viewport.geometry=geometry
            before=case.api.snapshot();case.press();case.release()
            self.assertEqual(case.session.values,[0.,.75,1.])
            self.assertEqual(set(case.api.calls[-1][1]['samples']),{'1'})
            case.api.undo();self.assertEqual(case.api.snapshot(),before)
        finally:case.tearDown()


if __name__=='__main__':unittest.main(verbosity=2)
