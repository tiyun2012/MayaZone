"""Settings-only radius gestures must not read/rebuild high-resolution paint data."""
import contextlib
import sys
import unittest
from unittest import mock

from test_layer_skin_ui import Adapter, ui
from test_layer_skin_session import FakeAPI
import layer_skin_session as sessions

if ui is not None:
    QtCore,QtWidgets=ui.QtCore,ui.QtWidgets
    try:
        from PySide6 import QtTest
    except ImportError:
        from PySide2 import QtTest
    import layer_skin_brush_view as view_module


@contextlib.contextmanager
def no_mesh_work(session,api,allow_feedback=False):
    with contextlib.ExitStack() as guard:
        for owner,names in ((session,('prepare','snapshot','_write_buffer','_capture_array','reload_feedback')),
                            (api,('context','metadata')),(api.core,('encode','composite')),
                            (session.buffer or api.paint_buffer,('read','write'))):
            for name in names:
                if name=='reload_feedback' and allow_feedback:continue
                guard.enter_context(mock.patch.object(owner,name,side_effect=AssertionError('Unexpected mesh work: '+name)))
        yield


def native_settings_callbacks(session):
    """Sequences Artisan can emit while redrawing/releasing a settings edit."""
    assert session.initialize(session.target)=='-id 1'
    assert session.array_attribute(session.target)==session.buffer.attribute()
    session.before_stroke();session.set_value(1,0,.99);session.after_stroke();session.finalize(1)


@unittest.skipIf(ui is None,'PySide is required')
class BrushRadiusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.api=Adapter();self.viewport=QtWidgets.QWidget();self.viewport.resize(200,100);self.viewport.show()
        self.api.make_brush_controller=lambda session:view_module.BrushController(session,
            lambda s,w:self.viewport if w is self.viewport else None)
        self.window=ui.LayerUI(self.api);self.window.target.setText('mesh');self.window.show();self.window.refresh()
        self.window.paint();self.app.processEvents();self.session=self.window.session;self.brush=self.session.brush

    def tearDown(self):
        if ui.shiboken.isValid(self.window):self.window.close()
        self.viewport.close();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete);self.app.processEvents()

    def b_press(self):QtTest.QTest.keyPress(self.viewport,QtCore.Qt.Key_B)
    def b_release(self):QtTest.QTest.keyRelease(self.viewport,QtCore.Qt.Key_B)
    def mouse_press(self):QtTest.QTest.mousePress(self.viewport,QtCore.Qt.LeftButton,pos=QtCore.QPoint(50,50))
    def mouse_release(self):QtTest.QTest.mouseRelease(self.viewport,QtCore.Qt.LeftButton,pos=QtCore.QPoint(50,50))

    def test_radius_field_only_edits_radius_despite_reentrant_native_callbacks(self):
        original=self.api.cmds.artUserPaintCtx;edits=[];values=self.session.values;buffer_values=self.session.buffer.values
        before=self.api.snapshot();preview=self.session.preview.updates
        def edit(name,**kw):
            result=original(name,**kw)
            if kw.get('edit'):
                edits.append(kw);native_settings_callbacks(self.session)
            return result
        with mock.patch.object(self.api.cmds,'artUserPaintCtx',side_effect=edit),no_mesh_work(self.session,self.api):
            for i in range(50):
                self.window.brush_radius.setValue(2.+i*.1);self.window.brush_radius.editingFinished.emit()
            self.app.processEvents()
        self.assertEqual(len(edits),50);self.assertTrue(all(set(data)=={'edit','radius'} for data in edits))
        self.assertIs(self.session.values,values);self.assertIs(self.session.buffer.values,buffer_values)
        self.assertEqual(self.session.preview.updates,preview);self.assertEqual(self.api.snapshot(),before)
        self.assertEqual(self.api.calls,[]);self.assertIsNone(self.session.stroke);self.assertEqual(self.api._chunk_depth,0)
        self.assertFalse(self.session.adjusting_brush)

    def test_unchanged_radius_does_not_edit_context_or_schedule_work(self):
        original=self.api.cmds.artUserPaintCtx
        with mock.patch.object(self.api.cmds,'artUserPaintCtx',wraps=original) as command,no_mesh_work(self.session,self.api):
            self.window.brush_radius.editingFinished.emit()
        self.assertFalse(any(call.kwargs.get('edit') for call in command.call_args_list))
        self.assertFalse(self.session.adjusting_brush);self.assertFalse(self.brush._sync_queued)

    def test_b_drag_skips_all_mesh_work_and_keeps_guard_through_key_first_release(self):
        before=self.api.snapshot();values=self.session.values;sync=mock.Mock(wraps=self.session.on_brush_settings)
        self.session.on_brush_settings=sync
        with no_mesh_work(self.session,self.api):
            self.b_press();self.mouse_press()
            for i in range(100):
                self.api.context_settings['radius']=2.+i*.01
                QtTest.QTest.mouseMove(self.viewport,QtCore.QPoint(50+i%20,50))
                native_settings_callbacks(self.session)
            self.b_release();native_settings_callbacks(self.session);self.app.processEvents()
            self.assertTrue(self.session.adjusting_brush)  # Mouse is still down.
            self.mouse_release();native_settings_callbacks(self.session)
            self.assertTrue(self.session.adjusting_brush);self.app.processEvents()
        self.assertFalse(self.session.adjusting_brush);self.assertTrue(sync.called)
        self.assertEqual(self.window.brush_radius.value(),2.99);self.assertIs(self.session.values,values)
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.calls,[])
        self.assertEqual(self.api._chunk_depth,0);self.assertIsNone(self.session.stroke)

    def test_mouse_first_release_keeps_guard_until_b_is_up_and_next_paint_commits(self):
        self.b_press();self.mouse_press();self.mouse_release();self.app.processEvents()
        self.assertTrue(self.session.adjusting_brush)
        with no_mesh_work(self.session,self.api):
            native_settings_callbacks(self.session);self.b_release();native_settings_callbacks(self.session);self.app.processEvents()
        self.assertFalse(self.session.adjusting_brush)
        self.session.before_stroke();self.api.paint_buffer.write([.7,0.,0.]);self.session.after_stroke()
        self.assertEqual(self.session.values,[.7,0.,0.]);self.assertEqual(len(self.api.undo_stack),1)
        self.assertEqual(self.session.last_stroke['status'],'saved')

    def test_entering_radius_change_saves_one_pending_real_stroke_before_skipping_callbacks(self):
        self.session.before_stroke();self.api.paint_buffer.write([.65,0.,0.])
        self.b_press();self.assertEqual(len(self.api.calls),1);self.assertIsNone(self.session.stroke)
        with no_mesh_work(self.session,self.api):
            self.mouse_press();native_settings_callbacks(self.session);self.mouse_release()
            self.app.processEvents()  # A queued completed-stroke refresh waits.
            self.b_release();native_settings_callbacks(self.session)
        self.app.processEvents()
        self.assertEqual(self.session.values,[.65,0.,0.]);self.assertEqual(len(self.api.undo_stack),1)
        self.assertEqual(self.session.last_stroke['commit_reason'],'radius_change')
        self.assertEqual(self.api._chunk_depth,0)

    def test_readonly_radius_callbacks_do_not_reupload_the_full_array(self):
        self.window.show_skin.setChecked(True);self.app.processEvents();self.session=self.window.session;self.brush=self.session.brush
        self.assertTrue(self.session.readonly)
        with no_mesh_work(self.session,self.api):
            self.b_press();self.mouse_press();native_settings_callbacks(self.session)
            self.b_release();self.mouse_release();native_settings_callbacks(self.session);self.app.processEvents()
        self.assertEqual(self.api.calls,[])

    def test_deferred_callbacks_after_field_edit_and_next_press_are_safe(self):
        self.session.update_brush_settings(radius=4.)
        with no_mesh_work(self.session,self.api):
            native_settings_callbacks(self.session)
        self.assertTrue(self.session.adjusting_brush)
        self.mouse_press();self.assertFalse(self.session.adjusting_brush)
        self.session.before_stroke();self.api.paint_buffer.write([.4,0.,0.]);self.mouse_release();self.session.after_stroke()
        self.assertEqual(self.session.values,[.4,0.,0.]);self.assertEqual(len(self.api.calls),1)

    def test_failed_radius_edit_releases_guards_and_does_not_change_weights(self):
        before=self.api.snapshot();original=self.api.cmds.artUserPaintCtx
        def fail(name,**kw):
            if kw.get('edit') and 'radius' in kw:
                native_settings_callbacks(self.session);raise RuntimeError('native radius failure')
            return original(name,**kw)
        with mock.patch.object(self.api.cmds,'artUserPaintCtx',side_effect=fail),no_mesh_work(self.session,self.api):
            with self.assertRaisesRegex(RuntimeError,'radius failure'):self.session.update_brush_settings(radius=4.)
            self.app.processEvents()
        self.assertFalse(self.session.adjusting_brush);self.assertFalse(self.session._configuring_view)
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.calls,[])

    def test_b_outside_viewport_does_not_suppress_layer_painting(self):
        QtTest.QTest.keyPress(self.window.brush_radius,QtCore.Qt.Key_B)
        QtTest.QTest.keyRelease(self.window.brush_radius,QtCore.Qt.Key_B)
        self.assertFalse(self.session.adjusting_brush);self.assertFalse(self.brush.b_down)

    def test_warm_helper_loading_ignores_the_previous_radius_controller(self):
        old=mock.Mock();old.attach.side_effect=AssertionError('Old controller was reused')
        with mock.patch.dict(sys.modules,{'_rtk_layer_skin_authoring_20_layer_skin_brush_view':old}):
            module=self.session.helper('layer_skin_brush_view')
        self.assertIsNot(module,old);self.assertTrue(hasattr(module.BrushController,'settings_changed'))

    def test_radius_change_finishes_pending_custom_relax_once(self):
        # Reuse the established viewport fixture with actual Relax computation.
        self.window.close();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        from test_layer_skin_brush_view import BrushViewTests
        case=BrushViewTests();case.app=self.app;case.setUp()
        try:
            case.press();case.key(QtCore.Qt.Key_B)
            self.assertEqual(len(case.api.calls),1)
            with no_mesh_work(case.session,case.api):native_settings_callbacks(case.session)
            case.key(QtCore.Qt.Key_B,QtCore.QEvent.KeyRelease);case.release(False);self.app.processEvents()
            self.assertFalse(case.session.adjusting_brush);self.assertEqual(len(case.api.calls),1)
            self.assertEqual(case.session.last_stroke['commit_reason'],'radius_change')
        finally:case.tearDown()


if __name__=='__main__':unittest.main(verbosity=2)
