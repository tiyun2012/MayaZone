"""Preserve component painting; explicit Select pauses with retained colors."""
import unittest
from unittest import mock

from test_layer_skin_ui import Adapter, ui
from test_layer_skin_brush_radius import no_mesh_work

if ui is not None:
    QtCore,QtWidgets=ui.QtCore,ui.QtWidgets
    try:
        from PySide6 import QtTest
    except ImportError:
        from PySide2 import QtTest
    import layer_skin_brush_view as brush_module


@unittest.skipIf(ui is None,'PySide is required')
class ComponentSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        case=self;self.api=Adapter();self.native_keys=[]
        class Viewport(QtWidgets.QWidget):
            def keyPressEvent(widget,event):
                case.native_keys.append(event.key())
                masks={QtCore.Qt.Key_F9:'polymeshVertex',QtCore.Qt.Key_F10:'polymeshEdge',QtCore.Qt.Key_F11:'polymeshFace'}
                if event.modifiers()!=QtCore.Qt.NoModifier:return
                if event.key()==QtCore.Qt.Key_F8:case.api.cmds.selectMode(object=not case.api.object_mode)
                elif event.key() in masks:
                    case.api.cmds.selectMode(component=True);case.api.cmds.selectType(allComponents=False)
                    case.api.cmds.selectType(**{masks[event.key()]:True})
                else:return
                case.mode_event('SelectModeChanged');case.mode_event('SelectTypeChanged')
        self.viewport=Viewport();self.viewport.resize(200,100);self.viewport.show()
        self.api.make_brush_controller=lambda session:brush_module.BrushController(session,
            lambda s,w:self.viewport if w is self.viewport else None)
        self.window=ui.LayerUI(self.api);self.window.target.setText('mesh');self.window.show();self.window.refresh()
        self.window.choose_joint('|b');self.window.paint();self.app.processEvents();self.session=self.window.session

    def tearDown(self):
        if ui.shiboken.isValid(self.window):self.window.close()
        self.viewport.close();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete);self.app.processEvents()

    def mode_event(self,name):
        for kind,callback in list(self.api.callbacks.values()):
            if kind==name:callback()

    def test_f9_keeps_brush_buffer_and_native_feedback_in_vertex_mode(self):
        before=self.api.snapshot();self.api.events=[];controller=self.session.brush;values=self.session.values
        with no_mesh_work(self.session,self.api,allow_feedback=True):
            QtTest.QTest.keyClick(self.viewport,QtCore.Qt.Key_F9);self.app.processEvents()
        self.assertTrue(self.session.active);self.assertTrue(self.session.viewing);self.assertTrue(self.api.context_settings['colorfeedback'])
        self.assertFalse(self.api.object_mode);self.assertEqual(self.api.selection_types,{'polymeshVertex':True})
        self.assertIn(QtCore.Qt.Key_F9,self.native_keys);self.assertFalse(controller.closed)
        self.assertEqual(self.api.hilited,['mesh']);self.assertIs(self.session.brush,controller)
        self.assertIs(self.session.values,values);self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.calls,[])
        self.assertFalse(any(e[0]=='tool' for e in self.api.events))

    def test_f8_f10_f11_keep_native_toggle_and_component_masks(self):
        for key,mask in ((QtCore.Qt.Key_F8,None),(QtCore.Qt.Key_F10,'polymeshEdge'),(QtCore.Qt.Key_F11,'polymeshFace')):
            self.api.object_mode=True;self.window.paint();self.app.processEvents()
            QtTest.QTest.keyClick(self.viewport,key);self.app.processEvents()
            self.assertTrue(self.session.active);self.assertFalse(self.api.object_mode)
            self.assertEqual(self.api.tool,self.api.paint_context);self.assertTrue(self.api.context_settings['colorfeedback'])
            if mask:self.assertEqual(self.api.selection_types,{mask:True})

    def test_marking_menu_mode_change_keeps_paint_and_existing_vertices(self):
        before=self.api.snapshot();self.api.selected=['mesh.vtx[1]'];self.api.object_mode=False
        self.api.selection_types={'polymeshVertex':True}
        with no_mesh_work(self.session,self.api,allow_feedback=True):
            self.mode_event('SelectModeChanged');QtTest.QTest.qWait(50)
        self.assertTrue(self.session.active);self.assertEqual(self.api.tool,self.api.paint_context)
        self.assertEqual(self.api.selected,['mesh.vtx[1]','mesh']);self.assertFalse(self.api.object_mode)
        self.assertEqual(self.api.selection_types,{'polymeshVertex':True});self.assertTrue(self.api.context_settings['colorfeedback'])
        self.assertEqual(self.api.hilited,['mesh'])
        self.assertEqual(self.api.snapshot(),before)

    def test_select_type_change_without_selection_event_keeps_the_brush(self):
        self.api.object_mode=False;self.api.selection_types={'polymeshEdge':True};self.api.selected=['mesh.e[0]']
        self.mode_event('SelectTypeChanged');QtTest.QTest.qWait(50)
        self.assertTrue(self.session.active);self.assertEqual(self.api.selected,['mesh.e[0]','mesh'])
        self.assertEqual(self.api.selection_types,{'polymeshEdge':True});self.assertTrue(self.api.context_settings['colorfeedback'])

    def test_select_vertices_button_hilites_loaded_mesh_and_retains_selected_vertices(self):
        button=next(b for b in self.window.findChildren(QtWidgets.QPushButton) if b.text()=='Select vertices')
        before=self.api.snapshot();self.api.selected=['mesh.vtx[2]']
        button.click();self.app.processEvents()
        self.assertEqual(self.api.tool,'selectSuperContext');self.assertFalse(self.api.object_mode)
        self.assertEqual(self.api.hilited,['mesh']);self.assertEqual(self.api.selection_types,{'polymeshVertex':True})
        self.assertEqual(self.api.selected,['mesh.vtx[2]']);self.assertTrue(self.api.weight_view.visible)
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.calls,[])

    def test_pending_array_paint_is_saved_once_before_selection_and_undo_restores_it(self):
        before=self.api.snapshot();self.session.before_stroke();self.api.paint_buffer.write([.7,0.,0.])
        QtTest.QTest.keyClick(self.viewport,QtCore.Qt.Key_F9);self.app.processEvents()
        self.assertEqual(len(self.api.calls),1);self.assertEqual(len(self.api.undo_stack),1)
        self.assertEqual(self.session.values,[.7,0.,0.]);self.assertEqual(self.session.last_stroke['commit_reason'],'component_mode')
        self.assertTrue(self.session.active);self.assertEqual(self.api._chunk_depth,0)
        self.api.undo();self.assertEqual(self.api.snapshot(),before)

    def test_rejected_pending_paint_blocks_select_vertices_before_selection_changes(self):
        self.session.before_stroke();self.api.paint_buffer.write([.7,0.,0.]);self.api.fail=True
        before=self.api.snapshot();self.assertFalse(self.window.select_vertices())
        self.assertTrue(self.session.active)
        self.assertTrue(self.api.object_mode);self.assertEqual(self.api.snapshot(),before)
        self.assertEqual(self.api.undo_stack,[]);self.assertEqual(self.api._chunk_depth,0)
        self.assertTrue(self.window.status.text())

    def test_component_mode_has_priority_over_an_active_radius_guard(self):
        controller=self.session.brush;QtTest.QTest.keyPress(self.viewport,QtCore.Qt.Key_B)
        self.assertTrue(self.session.adjusting_brush)
        self.api.object_mode=False;self.mode_event('SelectModeChanged');QtTest.QTest.qWait(50)
        self.assertTrue(self.session.active);self.assertTrue(self.session.adjusting_brush);self.assertFalse(controller.closed)
        self.assertEqual(self.api.tool,self.api.paint_context);self.assertEqual(self.api.hilited,['mesh'])
        QtTest.QTest.keyRelease(self.viewport,QtCore.Qt.Key_B);self.app.processEvents()
        self.assertFalse(self.session.adjusting_brush)

    def test_function_keys_in_other_widgets_or_with_modifiers_do_not_steal_the_tool(self):
        QtTest.QTest.keyClick(self.window.brush_radius,QtCore.Qt.Key_F9)
        QtTest.QTest.keyClick(self.viewport,QtCore.Qt.Key_F9,QtCore.Qt.ControlModifier)
        self.assertTrue(self.session.active);self.assertEqual(self.api.tool,self.api.paint_context)
        self.assertEqual(self.api.calls,[])

    def test_component_clicks_do_not_rescan_weights_or_display_range(self):
        self.window.select_vertices();self.app.processEvents()
        with (no_mesh_work(self.session,self.api),
              mock.patch.object(self.window,'update_display_range',side_effect=AssertionError('Unchanged range rescanned'))):
            for selection in (['mesh.vtx[0]'],['mesh.vtx[1]'],['mesh.e[0]']):
                self.api.selected=selection;self.mode_event('SelectionChanged');self.app.processEvents()
        self.assertEqual(self.api.selected,['mesh.e[0]']);self.assertTrue(self.api.weight_view.visible)

    def test_explicit_paint_resumes_native_context_and_preserves_saved_values(self):
        before=self.api.snapshot();self.window.brush_radius.setValue(4.);self.window.brush_radius.editingFinished.emit()
        self.window.select_vertices();self.api.selected=['mesh.vtx[0]'];self.assertTrue(self.window.paint())
        self.assertTrue(self.session.active);self.assertFalse(self.api.object_mode);self.assertEqual(self.api.selected,['mesh.vtx[0]','mesh'])
        self.assertEqual(self.api.context_settings['radius'],4.);self.assertFalse(self.session.adjusting_brush)
        self.assertEqual(self.api.snapshot(),before)

    def test_select_vertices_keeps_real_preview_when_optional_hud_constructor_fails(self):
        import layer_skin_viewport as viewport
        from test_layer_skin_viewport import DisplayAPI
        display=DisplayAPI();display.r.MHUDRender=mock.Mock(side_effect=TypeError('MHUDRender : no matching constructor found'))
        before=self.api.snapshot();artist=display.snapshot()
        self.session.preview.close();self.session.preview=viewport.WeightView(display)
        self.api.selected=['mesh.vtx[1]']
        self.assertTrue(self.window.select_vertices());self.app.processEvents()
        self.assertFalse(self.session.active);self.assertTrue(self.session.preview.visible)
        self.assertEqual(self.session.preview_error,'');self.assertTrue(display.draw(self.session.preview))
        self.assertFalse(self.session.preview.report()['hud_enabled'])
        self.assertIn('no matching constructor',self.session.preview.report()['hud_constructor_error'])
        self.assertEqual(self.api.selected,['mesh.vtx[1]']);self.assertEqual(self.api.snapshot(),before)
        self.assertEqual(display.snapshot(),artist)
        self.window.stop_paint();self.assertEqual(display.registry,{});self.assertEqual(display.callbacks,{})

    def test_native_cleanup_and_tool_event_do_not_finish_the_handoff_twice(self):
        original=self.api.cmds.setToolTo
        def native(tool):
            original(tool);self.session.tool_cleanup();self.mode_event('ToolChanged')
        with mock.patch.object(self.api.cmds,'setToolTo',side_effect=native),mock.patch.object(self.session,'tool_cleanup',wraps=self.session.tool_cleanup) as cleanup:
            self.session.pause_for_components()
        self.assertEqual(cleanup.call_count,1);self.assertTrue(self.api.weight_view.visible)

    def test_mask_and_readonly_skin_views_keep_their_correct_colors(self):
        self.window.paint_mode.setCurrentIndex(1);self.window.paint();self.window.select_vertices()
        self.assertEqual(self.api.weight_view.display,'grayscale');self.assertEqual(self.api.weight_view.values,[1.]*3)
        self.window.view_skin(True);self.window.select_vertices()
        self.assertTrue(self.session.readonly);self.assertEqual(self.session.mode,'skin')
        self.assertEqual(self.api.weight_view.display,'heatmap');self.assertEqual(self.api.calls,[])

    def test_handoff_has_ready_colors_before_the_native_context_disappears(self):
        self.window.close();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        from test_layer_skin_inplace import NativeFeedbackTransitions
        case=NativeFeedbackTransitions();case.app=self.app;case.setUp()
        try:
            before=case.api.snapshot();case.window.session.pause_for_components()
            self.assertTrue(case.frames);self.assertNotIn('material',[kind for kind,values in case.frames])
            self.assertTrue(all(values==(.8,.6,.4) for kind,values in case.frames))
            self.assertEqual(case.api.snapshot(),before)
        finally:case.tearDown()


if __name__=='__main__':unittest.main(verbosity=2)
