"""Qt handoff regressions: incoming-tool invalidation, repaint and cancellation."""
import unittest
from unittest import mock
from test_layer_skin_ui import Adapter,ui


@unittest.skipIf(ui is None,'PySide is required')
class SelectionFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=ui.QtWidgets.QApplication.instance() or ui.QtWidgets.QApplication([])
    def setUp(self):
        self.api=Adapter();self.window=ui.LayerUI(self.api);self.window.target.setText('mesh')
        self.window.show();self.window.refresh();self.window.choose_joint('|b');self.app.processEvents()
        self.session=self.window.session
    def tearDown(self):
        if ui.shiboken.isValid(self.window):self.window.close()
        self.app.processEvents()
    def emit(self,event):
        for kind,callback in list(self.api.callbacks.values()):
            if kind==event:callback()
    def test_select_before_any_paint_shows_colors_without_creating_a_native_paint_buffer(self):
        before=self.api.snapshot()
        with mock.patch.object(self.api,'make_paint_buffer',side_effect=AssertionError('Selection allocated a paint buffer')):
            self.assertTrue(self.window.select_vertices());self.app.processEvents()
        self.assertTrue(self.api.weight_view.visible);self.assertFalse(self.session.active)
        self.assertFalse(self.api.context_exists);self.assertEqual(self.api.snapshot(),before)
        self.assertTrue(self.window.select_vertices_button.isChecked());self.assertFalse(self.window.paint_button.isChecked())
    def test_select_button_publishes_after_component_setup_and_repeated_click_restores_view(self):
        self.window.paint();self.session.before_stroke();self.api.paint_buffer.write([.6,0.,0.])
        original=self.api.cmds.selectType
        def component(**flags):
            result=original(**flags)
            if flags.get('polymeshVertex'):self.api.weight_view.clear()
            return result
        self.api.cmds.selectType=component
        self.assertTrue(self.window.select_vertices());self.assertTrue(self.api.weight_view.visible)
        self.assertAlmostEqual(self.api.weight_view.values[0],.6);self.assertEqual(len(self.api.undo_stack),1)
        self.app.processEvents();self.api.weight_view.clear();self.window.select_vertices_button.click()
        self.assertTrue(self.api.weight_view.visible);self.assertFalse(self.session.active)
        self.assertTrue(self.window.select_vertices_button.isChecked());self.assertEqual(len(self.api.undo_stack),1)
    def test_q_handoff_recovers_colors_after_incoming_tool_invalidates_old_feedback(self):
        self.window.paint();self.session.tool_cleanup()
        self.api.tool='selectSuperContext';self.api.weight_view.clear();self.emit('ToolChanged')
        with (mock.patch.object(self.api,'context',side_effect=AssertionError('Tool handoff reread skin')),
              mock.patch.object(self.session,'prepare',side_effect=AssertionError('Tool handoff prepared again'))):
            self.app.processEvents()
        self.assertTrue(self.api.weight_view.visible);self.assertEqual(self.api.weight_view.values,self.session.values)
        self.assertTrue(self.window.select_vertices_button.isChecked());self.assertFalse(self.window.paint_button.isChecked())
    def test_repeated_mode_events_queue_one_cached_republish_without_skin_or_array_work(self):
        self.window.select_vertices();self.app.processEvents();self.api.weight_view.clear();before=self.api.weight_view.updates
        with (mock.patch.object(self.api,'context',side_effect=AssertionError('Selection reread skin')),
              mock.patch.object(self.api.core,'encode',side_effect=AssertionError('Selection encoded state')),
              mock.patch.object(self.api.paint_buffer,'read',side_effect=AssertionError('Selection read paint array')),
              mock.patch.object(self.api.paint_buffer,'write',side_effect=AssertionError('Selection uploaded paint array'))):
            for _ in range(20):self.emit('SelectModeChanged');self.emit('SelectTypeChanged')
            self.app.processEvents()
        self.assertTrue(self.api.weight_view.visible);self.assertEqual(self.api.weight_view.updates,before+1)
    def test_stop_cancels_queued_view_and_clears_both_mode_buttons(self):
        self.window.paint();self.window.select_vertices();self.window.stop_paint();self.app.processEvents()
        self.assertFalse(self.api.weight_view.visible);self.assertFalse(self.window.paint_button.isChecked())
        self.assertFalse(self.window.select_vertices_button.isChecked());self.assertFalse(self.session.paint_armed)
    def test_return_to_paint_cancels_queued_passive_preview_and_keeps_components(self):
        self.window.paint();self.window.select_vertices();self.api.selected=['mesh.vtx[1]']
        self.window.paint();self.app.processEvents()
        self.assertTrue(self.session.active);self.assertTrue(self.api.context_settings['colorfeedback'])
        self.assertFalse(self.api.weight_view.visible);self.assertIn('mesh.vtx[1]',self.api.selected)
        self.assertTrue(self.window.paint_button.isChecked());self.assertFalse(self.window.select_vertices_button.isChecked())
    def test_switching_joint_in_selection_keeps_the_view_and_current_components(self):
        self.window.paint();self.window.select_vertices();self.app.processEvents();self.api.selected=['mesh.vtx[1]']
        self.window.choose_joint('|a');self.app.processEvents()
        self.assertFalse(self.session.active);self.assertTrue(self.api.weight_view.visible)
        self.assertEqual(self.api.weight_view.values,self.session.values);self.assertEqual(self.session.joint,'a')
        self.assertEqual(self.api.selected,['mesh.vtx[1]']);self.assertEqual(self.api.tool,'selectSuperContext')
    def test_y_resume_updates_mode_buttons_without_leaving_the_preview_attached(self):
        self.window.paint();self.window.select_vertices();self.app.processEvents()
        self.api.tool=self.api.paint_context;self.emit('ToolChanged');self.app.processEvents()
        self.assertTrue(self.session.active);self.assertFalse(self.api.weight_view.visible)
        self.assertTrue(self.window.paint_button.isChecked());self.assertFalse(self.window.select_vertices_button.isChecked())
    def test_close_cancels_the_queued_preview_without_late_scene_reads(self):
        self.window.select_vertices();self.window.close()
        with mock.patch.object(self.api,'context',side_effect=AssertionError('Closed view read skin')):self.app.processEvents()
        self.assertTrue(self.session.closed);self.assertFalse(self.api.weight_view.visible)


if __name__=='__main__':unittest.main()
