"""Real Qt repaint checks with recorded color backends; not Maya/VP2 pixels."""
import sys
import unittest
from unittest import mock
from test_layer_skin_ui import Adapter
import layer_skin_session as sessions

try:
    from PySide6 import QtCore,QtWidgets
except ImportError:
    try:from PySide2 import QtCore,QtWidgets
    except ImportError:QtWidgets=None
try:import layer_skin_feedback as feedback
except ImportError:feedback=None


@unittest.skipIf(QtWidgets is None,'PySide is required')
class ColorHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        import layer_skin_ui as ui
        self.api=Adapter();self.frames=[];case=self
        class Canvas(QtWidgets.QWidget):
            def paintEvent(widget,event):
                if case.api.tool==sessions.CONTEXT and case.api.context_settings.get('colorfeedback'):
                    case.frames.append(('native',case.api.paint_buffer.read()))
                elif case.api.weight_view.visible:case.frames.append(('held',case.api.weight_view.values[:]))
                else:case.frames.append(('material',[]))
        self.canvas=Canvas();self.canvas.resize(200,100);self.canvas.show();self.app.processEvents()
        self.api.feedback_surfaces=lambda:[(self.canvas,self.canvas.repaint)]
        def instrument(owner,name):
            original=getattr(owner,name)
            def call(*args,**kwargs):
                result=original(*args,**kwargs);self.canvas.repaint();self.app.processEvents();return result
            setattr(owner,name,call)
        instrument(self.api.cmds,'artUserPaintCtx');instrument(self.api.cmds,'setToolTo')
        instrument(self.api.weight_view,'show');instrument(self.api.weight_view,'clear')
        self.window=ui.LayerUI(self.api);self.window.target.setText('mesh');self.window.show();self.window.refresh()
        self.window.choose_joint('|b');self.app.processEvents();self.frames=[]
    def tearDown(self):
        self.window.close();self.canvas.close();self.canvas.deleteLater();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        sys.modules.pop(sessions.BRIDGE,None)
    def assert_continuous(self):
        self.assertTrue(self.frames);self.assertNotIn('material',[kind for kind,values in self.frames])
        self.assertTrue(self.canvas.updatesEnabled())
    def test_held_colors_enter_paint_without_an_intermediate_material_frame(self):
        self.window.session.view('mesh',self.window.selected_id(),'b',mode='weights');self.frames=[]
        before=self.api.snapshot();self.window.paint()
        self.assert_continuous();self.assertEqual(self.frames[-1],('native',self.window.session.values))
        self.assertEqual(self.api.snapshot(),before)
    def test_active_joint_switch_presents_new_weights_without_material_flash(self):
        self.window.run('paint',dict(mode='weights',joint='b',values={'0':.8}))
        self.window.choose_joint('|a');self.window.paint();before=self.api.snapshot();self.frames=[]
        self.assertTrue(self.window.choose_joint('|b'))
        self.assert_continuous();self.assertEqual(self.frames[-1],('native',[.8,0.,0.]))
        self.assertEqual(self.api.snapshot(),before)
    def test_brush_operation_changes_and_execute_keep_a_continuous_weight_view(self):
        w=self.window;w.whole.setChecked(True);w.paint();self.frames=[]
        w.operation_radios['add'].setChecked(True);self.assert_continuous()
        self.frames=[];self.assertTrue(w.execute_operation('add'));self.assert_continuous()
        self.assertEqual(self.frames[-1],('native',[.1,.1,.1]))
        w.stop_paint(keep_view=True);self.frames=[]
        self.assertTrue(w.execute_operation('scale'));self.assert_continuous();self.assertEqual(self.frames[-1],('held',[.05,.05,.05]))
    def test_selection_refresh_and_joint_change_publish_only_the_requested_joint(self):
        self.window.run('paint',dict(mode='weights',joint='b',values={'0':.8}));self.window.paint()
        self.window.session.needs_refresh=True;self.api.selected=['|a'];self.frames=[]
        self.window.follow_selection()
        self.assert_continuous();self.assertEqual(self.window.active_joint(),'a')
        self.assertTrue(all(values==[0.,0.,0.] for kind,values in self.frames))
    def test_mask_and_display_changes_keep_a_color_frame_available(self):
        self.window.paint();self.frames=[];self.window.paint_mode.setCurrentIndex(1)
        self.window.paint();self.assert_continuous();self.assertEqual(self.frames[-1][1],[1.,1.,1.])
        self.frames=[];self.window.paint_mode.setCurrentIndex(0);self.window.paint()
        self.window.weight_display.setCurrentIndex(1);self.assert_continuous()
    def test_layer_edit_keeps_held_colors_and_explicit_stop_restores_material(self):
        self.window.paint();self.window.stop_paint(keep_view=True);self.frames=[]
        self.assertTrue(self.window.run('paint',dict(mode='weights',joint='b',values={'1':.6})))
        self.assert_continuous();self.assertEqual(self.frames[-1],('held',[0.,.6,0.]))
        self.frames=[];self.window.stop_paint()
        self.assertTrue(self.frames);self.assertEqual(self.frames[-1][0],'material')
    def test_rejected_pending_stroke_keeps_old_joint_colors_and_reenables_repaint(self):
        self.window.paint();session=self.window.session;session.before_stroke();self.api.paint_buffer.write([.7,0.,0.])
        before=self.api.snapshot();self.api.fail=True;self.frames=[]
        self.assertFalse(self.window.choose_joint('|a'));self.assert_continuous()
        self.assertEqual(self.window.active_joint(),'b');self.assertEqual(self.api.snapshot(),before)
    def test_layer_switch_and_undo_keep_the_new_color_view_visible(self):
        self.window.run('paint',dict(mode='weights',joint='b',values={'0':.8}))
        self.window.paint();self.frames=[]
        self.window.layers.setCurrentItem(self.window.layers.topLevelItem(1),1)
        self.assert_continuous();self.assertEqual(self.frames[-1][0],'held')
        self.frames=[];self.window.history(False);self.assert_continuous()
    def test_failed_layer_action_retains_last_color_values_without_changing_data(self):
        self.window.run('paint',dict(mode='weights',joint='b',values={'0':.8}));self.window.paint()
        before=self.api.snapshot();self.api.fail=True;self.frames=[]
        self.assertFalse(self.window.run('properties',dict(opacity=.4)))
        self.assert_continuous();self.assertEqual(self.frames[-1],('held',[.8,0.,0.]))
        self.assertEqual(self.api.snapshot(),before)
    def test_maya_exit_during_handoff_does_not_present_or_restore_native_widgets(self):
        session=self.window.session;self.api.events=[];self.frames=[]
        with mock.patch.object(self.canvas,'setUpdatesEnabled',wraps=self.canvas.setUpdatesEnabled) as updates:
            with session.color_transition():
                session.maya_exit();updates.reset_mock()
            updates.assert_not_called()
        self.assertEqual(self.frames,[]);self.assertEqual(self.api.events,[])
        self.assertTrue(session._display_gate.abandoned);self.assertEqual(session._display_gate.depth,0)


@unittest.skipIf(QtWidgets is None or feedback is None,'Feedback helper and PySide are required')
class DisplayGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        self.widget=QtWidgets.QWidget();self.other=QtWidgets.QWidget();self.present=mock.Mock()
        self.gate=feedback.DisplayGate(lambda:[(self.widget,self.present)])
    def tearDown(self):
        for widget in (self.widget,self.other):
            if feedback.valid(widget):widget.deleteLater()
        self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
    def test_nested_handoffs_present_once_after_restoring_updates(self):
        with self.gate.hold():
            self.assertFalse(self.widget.updatesEnabled());self.assertTrue(self.other.updatesEnabled())
            with self.gate.hold():self.assertFalse(self.widget.updatesEnabled())
            self.present.assert_not_called()
        self.assertTrue(self.widget.updatesEnabled());self.present.assert_called_once();self.assertEqual(self.gate.depth,0)
    def test_preexisting_disabled_view_is_kept_disabled_and_not_redrawn(self):
        self.widget.setUpdatesEnabled(False)
        with self.gate.hold():pass
        self.assertFalse(self.widget.updatesEnabled());self.present.assert_not_called()
    def test_duplicate_surface_is_only_held_and_presented_once(self):
        gate=feedback.DisplayGate(lambda:[(self.widget,self.present),(self.widget,self.present)])
        with gate.hold():self.assertFalse(self.widget.updatesEnabled())
        self.assertTrue(self.widget.updatesEnabled());self.present.assert_called_once()
    def test_exception_restores_updates_without_hiding_the_original_error(self):
        with self.assertRaisesRegex(ValueError,'operation failed'):
            with self.gate.hold():raise ValueError('operation failed')
        self.assertTrue(self.widget.updatesEnabled());self.assertEqual(self.gate.depth,0)
        with self.gate.hold():pass
        self.assertEqual(self.present.call_count,2)
    def test_all_views_are_restored_before_any_view_is_presented(self):
        observations=[]
        def present():observations.append((self.widget.updatesEnabled(),self.other.updatesEnabled()))
        gate=feedback.DisplayGate(lambda:[(self.widget,present),(self.other,present)])
        with gate.hold():self.assertFalse(self.other.updatesEnabled())
        self.assertEqual(observations,[(True,True),(True,True)])
    def test_deleted_surface_is_skipped_during_restore(self):
        with self.gate.hold():
            self.widget.deleteLater();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        self.assertEqual(self.gate.depth,0);self.present.assert_not_called()
    def test_present_failure_does_not_leave_other_views_frozen(self):
        errors=[];gate=feedback.DisplayGate(lambda:[(self.widget,lambda:(_ for _ in ()).throw(RuntimeError('redraw failed'))),(self.other,self.present)],errors.append)
        with gate.hold():pass
        self.assertTrue(self.widget.updatesEnabled());self.assertTrue(self.other.updatesEnabled())
        self.present.assert_called_once();self.assertIn('redraw failed',gate.last_error);self.assertTrue(errors)
    def test_partial_provider_failure_unfreezes_previously_collected_views(self):
        def surfaces():
            yield self.widget,self.present
            raise RuntimeError('enumeration failed')
        gate=feedback.DisplayGate(surfaces)
        with self.assertRaisesRegex(RuntimeError,'enumeration failed'):
            with gate.hold():pass
        self.assertTrue(self.widget.updatesEnabled());self.assertEqual(gate.depth,0)
    def test_abandoned_gate_does_not_call_provider_or_presenter(self):
        provider=mock.Mock(return_value=[(self.widget,self.present)])
        gate=feedback.DisplayGate(provider);gate.abandon()
        with gate.hold():pass
        provider.assert_not_called();self.present.assert_not_called();self.assertTrue(self.widget.updatesEnabled())


if __name__=='__main__':unittest.main()
