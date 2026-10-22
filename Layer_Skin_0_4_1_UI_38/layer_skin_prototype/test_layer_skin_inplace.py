"""Observe native lifecycle calls directly, independently of Qt paint suppression.

These probes model an immediate native draw after each API mutation. They do
not claim to render Maya/VP2, but expose off/on resets that Qt-only checks miss.
"""
import unittest
from unittest import mock
from test_layer_skin_ui import Adapter
from test_layer_skin_session import FakePaintBuffer

try:
    from PySide6 import QtCore,QtWidgets
except ImportError:
    try:from PySide2 import QtCore,QtWidgets
    except ImportError:QtWidgets=None


@unittest.skipIf(QtWidgets is None,'PySide is required')
class NativeFeedbackTransitions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        import layer_skin_ui as ui
        self.api=Adapter();self.frames=[]
        self.window=ui.LayerUI(self.api);w=self.window;w.target.setText('mesh');w.show();w.refresh()
        w.run('paint',dict(mode='weights',joint='a',values={'0':.2,'1':.4,'2':.6}))
        w.run('paint',dict(mode='weights',joint='b',values={'0':.8,'1':.6,'2':.4}))
        w.choose_joint('|b');w.paint();self.app.processEvents()
        def instrument(owner,name):
            original=getattr(owner,name)
            def call(*args,**kwargs):
                if not kwargs.get('query') and not kwargs.get('exists'):self.frame()
                result=original(*args,**kwargs)
                if not kwargs.get('query') and not kwargs.get('exists'):self.frame()
                return result
            setattr(owner,name,call)
        for name in ('artUserPaintCtx','setToolTo','select','selectMode'):instrument(self.api.cmds,name)
        instrument(self.api.paint_buffer,'write');instrument(self.api.weight_view,'clear');instrument(self.api.weight_view,'show')
        self.frames=[];self.api.events=[]
    def tearDown(self):self.window.close();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
    def frame(self):
        if self.api.tool==self.api.paint_context and self.api.context_settings.get('colorfeedback'):
            self.frames.append(('native',tuple(self.api.paint_buffer.read())))
        elif self.api.weight_view.visible:self.frames.append(('held',tuple(self.api.weight_view.values)))
        else:self.frames.append(('material',()))
    def assert_no_reset(self):
        self.assertTrue(self.frames)
        self.assertNotIn('material',[kind for kind,values in self.frames])
        self.assertFalse(any(event[0] in ('tool','select_mode','mel') for event in self.api.events))
        self.assertFalse(any(event[0]=='paint_ctx' and event[2].get('colorfeedback') is False for event in self.api.events))
    def test_repeated_paint_never_exposes_a_default_frame_or_restarts_native_context(self):
        before=self.api.snapshot();buffer=self.window.session.buffer;history=list(self.api.undo_stack)
        for _ in range(5):self.window.paint();self.frame()
        self.assert_no_reset();self.assertTrue(all(values==(.8,.6,.4) for kind,values in self.frames))
        self.assertIs(self.window.session.buffer,buffer);self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.undo_stack,history)
    def test_joint_changes_publish_only_old_or_new_values_without_material_or_zero_frames(self):
        before=self.api.snapshot();self.assertTrue(self.window.choose_joint('|a'))
        self.assert_no_reset();self.assertEqual(self.window.session.values,[.2,.4,.6])
        for kind,values in self.frames:self.assertIn(values,((.8,.6,.4),(.2,.4,.6)))
        self.assertEqual(self.api.snapshot(),before)
    def test_repeated_paint_reuses_brush_buffer_previous_tool_and_does_not_rewrite_array(self):
        w=self.window;s=w.session;marker=mock.Mock(drawing=False);s.brush=marker
        old=(s.buffer,s.previous_tool,s.context_starts);self.api.paint_buffer.write=mock.Mock(wraps=self.api.paint_buffer.write)
        for _ in range(3):self.assertTrue(w.paint())
        self.assertEqual((s.buffer,s.previous_tool,s.context_starts),old);self.assertIs(s.brush,marker)
        self.api.paint_buffer.write.assert_not_called();marker.close.assert_not_called()
        self.assertEqual(s.paint_report()['native_view_updates']['last'],'already_current')
        self.assertEqual(s.context_reuses,3)
    def test_pending_stroke_saves_on_old_joint_once_before_retargeting(self):
        w=self.window;s=w.session;before=len(self.api.undo_stack);self.api.calls=[]
        s.before_stroke();self.api.paint_buffer.write([.9,.6,.4]);self.frames=[];self.api.events=[]
        self.assertTrue(w.choose_joint('|a'));self.assert_no_reset()
        self.assertEqual(len(self.api.calls),1);self.assertEqual(self.api.calls[0][1]['joint'],'b')
        self.assertEqual(s.last_stroke['joint'],'b');self.assertEqual(s.last_stroke['commit_reason'],'action_change')
        self.assertEqual(len(self.api.undo_stack),before+1);self.assertEqual(self.api._chunk_depth,0)
        self.assertAlmostEqual(s.values[0],.1)
    def test_rejected_pending_stroke_keeps_old_joint_array_and_view(self):
        w=self.window;s=w.session;before=self.api.snapshot();history=list(self.api.undo_stack)
        s.before_stroke();self.api.paint_buffer.write([.9,.6,.4]);self.api.fail=True;self.frames=[]
        self.assertFalse(w.choose_joint('|a'));self.assert_no_reset()
        self.assertEqual((w.active_joint(),s.joint),('b','b'));self.assertEqual(s.buffer.read(),[.8,.6,.4])
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.undo_stack,history)
        self.assertEqual(self.api._chunk_depth,0);self.assertIn('Stroke rejected',w.status.text())
    def test_joint_switch_after_native_write_failure_restores_old_scope_and_array(self):
        w=self.window;s=w.session;before=self.api.snapshot();original=self.api.paint_buffer.write;once=[True]
        def write(values):
            original(values)
            if values==[.2,.4,.6] and once[0]:once[0]=False;raise RuntimeError('Native array transfer failed')
        self.api.paint_buffer.write=write
        self.assertFalse(w.choose_joint('|a'));self.assert_no_reset()
        self.assertEqual((w.active_joint(),s.joint),('b','b'));self.assertEqual(s.values,[.8,.6,.4]);self.assertEqual(s.buffer.read(),s.values)
        self.assertFalse(s._configuring_view);self.assertTrue(s.active);self.assertEqual(self.api.snapshot(),before)
    def test_joint_switch_after_feedback_failure_restores_old_scope_and_array(self):
        w=self.window;s=w.session;before=self.api.snapshot();original=self.api.cmds.artUserPaintCtx;once=[True]
        def configure(name,**kwargs):
            result=original(name,**kwargs)
            if kwargs.get('edit') and kwargs.get('colorfeedback') is True and once[0]:
                once[0]=False;raise RuntimeError('Native feedback refresh failed')
            return result
        self.api.cmds.artUserPaintCtx=configure
        self.assertFalse(w.choose_joint('|a'));self.assert_no_reset()
        self.assertEqual((w.active_joint(),s.joint),('b','b'));self.assertEqual(s.buffer.read(),[.8,.6,.4])
        self.assertEqual(self.api.snapshot(),before);self.assertFalse(s._configuring_view)
    def test_invalid_joint_is_rejected_before_touching_active_feedback(self):
        w=self.window;s=w.session;before=self.api.snapshot();original=self.api.cmds.nodeType
        self.api.cmds.nodeType=lambda name:'transform' if name=='|bad' else original(name)
        self.assertFalse(w.choose_joint('|bad'));self.frame();self.assert_no_reset()
        self.assertEqual((w.active_joint(),s.joint),('b','b'));self.assertEqual(self.api.snapshot(),before)
    def test_repeated_paint_respects_external_skin_edit_guard_without_clearing_old_view(self):
        w=self.window;s=w.session;self.api.weights=[.5,.5]*3;before=self.api.snapshot()
        self.assertFalse(w.paint());self.frame();self.assert_no_reset()
        self.assertEqual(s.values,[.8,.6,.4]);self.assertEqual(self.api.snapshot(),before)
        self.assertIn('changed outside Layer Skin',w.status.text())
    def test_final_skin_joint_switch_keeps_readonly_native_context_and_zero_opacity(self):
        w=self.window;w.view_skin(True);self.frames=[];self.api.events=[];before=self.api.snapshot();s=w.session;buffer=s.buffer
        self.assertTrue(w.choose_joint('|a'));self.assert_no_reset()
        self.assertEqual((s.mode,s.readonly),('skin',True));self.assertEqual(self.api.context_settings['opacity'],0.)
        self.assertIs(s.buffer,buffer);self.assertTrue(w.show_skin.isChecked());self.assertEqual(self.api.snapshot(),before)
    def test_feedback_refresh_never_temporarily_disables_native_colors(self):
        s=self.window.session;before=self.api.snapshot()
        s.reload_feedback();s.refresh_view(force=True);s.set_display('grayscale');self.assert_no_reset()
        self.assertEqual(self.api.snapshot(),before)
    def test_changed_buffer_factory_rebuilds_only_transient_native_resources(self):
        w=self.window;s=w.session;buffer=FakePaintBuffer();before=self.api.snapshot();starts=s.context_starts
        self.api.make_paint_buffer=lambda mesh:buffer
        self.assertTrue(w.paint());self.assertIs(s.buffer,buffer);self.assertEqual(s.context_starts,starts+1)
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(buffer.read(),[.8,.6,.4])
    def test_explicit_paint_after_component_or_joint_selection_restores_paint_surface(self):
        w=self.window;s=w.session;before=self.api.snapshot()
        for selection,object_mode in [(['mesh.vtx[1]'],False),(['|a'],True)]:
            self.api.selected=list(selection);self.api.object_mode=object_mode;starts=s.context_starts
            self.assertTrue(w.paint())
            self.assertEqual(s.context_starts,starts+(1 if object_mode else 0))
            self.assertEqual(self.api.selected,['mesh'] if object_mode else selection+['mesh'])
            self.assertEqual(self.api.object_mode,object_mode)
        self.assertEqual(self.api.snapshot(),before)


if __name__=='__main__':unittest.main()
