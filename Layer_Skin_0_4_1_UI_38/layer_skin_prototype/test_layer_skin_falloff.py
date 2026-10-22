"""Explicit Artisan falloff, stable native settings and absolute-value persistence.

The native-array tests supply Artisan's final values; they do not render or
simulate Maya brush stamps. Native brush falloff still needs a Maya check.
"""
import unittest
from unittest import mock
import layer_skin_core as core
import layer_skin_session as sessions
from test_layer_skin_session import FakeAPI

try:
    from PySide6 import QtCore,QtWidgets
except ImportError:
    try:from PySide2 import QtCore,QtWidgets
    except ImportError:QtWidgets=None


class FalloffSessionTests(unittest.TestCase):
    def setUp(self):self.api=FakeAPI();self.session=sessions.Session(self.api)
    def tearDown(self):self.session.close()
    def start(self):self.session.start('mesh',self.api.layer,joint='b',mode='weights')
    def test_default_replace_uses_solid_full_opacity_without_pressure_or_accumulation(self):
        self.start();flags=self.api.context_settings
        self.assertEqual((flags['stampProfile'],flags['selectedattroper'],flags['value'],flags['opacity']),('solid','absolute',1.,1.))
        self.assertIs(flags['usepressure'],False);self.assertIs(flags['accopacity'],False)
    def test_activation_preferences_cannot_silently_enable_soft_stamp_or_pressure(self):
        original=self.api.cmds.setToolTo
        def activate(name):
            original(name)
            self.api.context_settings.update(stampProfile='gaussian',usepressure=True,accopacity=True)
        self.api.cmds.setToolTo=activate;self.start()
        self.assertEqual(self.api.context_settings['stampProfile'],'solid')
        self.assertFalse(self.api.context_settings['usepressure']);self.assertFalse(self.api.context_settings['accopacity'])
    def test_all_supported_profiles_survive_reload_and_repeated_start_without_context_restart(self):
        self.start();buffer=self.session.buffer;starts=self.session.context_starts;before=self.api.snapshot();self.api.events=[]
        for profile in ('poly','gaussian','solid'):
            self.session.set_brush_profile(profile);self.session.reload_feedback();self.start()
            self.assertEqual(self.api.context_settings['stampProfile'],profile)
            self.assertEqual(self.session.brush_profile,profile);self.assertIs(self.session.buffer,buffer)
        self.assertEqual(self.session.context_starts,starts);self.assertEqual(self.api.snapshot(),before)
        self.assertFalse(any(e[0]=='paint_ctx' and e[2].get('colorfeedback') is False for e in self.api.events))
    def test_setting_profile_before_paint_does_not_create_scene_or_native_context_edits(self):
        before=self.api.snapshot();self.session.set_brush_profile('gaussian')
        self.assertEqual(self.api.snapshot(),before);self.assertFalse(self.api.context_exists)
        self.start();self.assertEqual(self.api.context_settings['stampProfile'],'gaussian')
    def test_invalid_profile_keeps_pending_stroke_and_current_native_settings_untouched(self):
        self.start();self.session.before_stroke();stroke=self.session.stroke;before=self.api.snapshot()
        with self.assertRaises(ValueError):self.session.set_brush_profile('unknown')
        self.assertIs(self.session.stroke,stroke);self.assertEqual(self.session.brush_profile,'solid')
        self.assertEqual(self.api.snapshot(),before)
    def test_profile_change_saves_outgoing_stroke_once_with_its_original_profile(self):
        self.start();self.session.before_stroke();self.api.paint_buffer.write([.35,.35,.35])
        self.session.set_brush_profile('gaussian')
        self.assertEqual(self.session.last_stroke['falloff'],'solid');self.assertEqual(self.session.last_stroke['commit_reason'],'falloff_change')
        self.assertEqual(len(self.api.undo_stack),1);self.assertEqual(self.api._chunk_depth,0)
        self.assertEqual(self.session.values,[.35]*3);self.assertEqual(self.api.context_settings['stampProfile'],'gaussian')
    def test_constant_native_replace_values_stay_constant_after_save_and_joint_roundtrip(self):
        self.api.state=core.edit(self.api.state,'paint',dict(layer=self.api.layer,mode='weights',joint='a',values={'0':.2,'1':.4,'2':.6}))
        self.api.state=core.edit(self.api.state,'paint',dict(layer=self.api.layer,mode='weights',joint='b',values={'0':.8,'1':.6,'2':.4}))
        self.api.weights=core.composite(self.api.state);self.start();before=self.api.snapshot()
        self.session.before_stroke();self.api.paint_buffer.write([.35]*3);self.session.after_stroke()
        self.assertEqual(self.session.values,[.35]*3);self.assertTrue(self.session.last_stroke['layer_values_verified'])
        self.session.start('mesh',self.api.layer,joint='a',mode='weights');self.start()
        self.assertEqual(self.session.values,[.35]*3);self.api.undo();self.assertEqual(self.api.snapshot(),before)
    def test_profile_edit_callbacks_cannot_accidentally_begin_or_modify_a_stroke(self):
        self.start();before=self.api.snapshot();original=self.api.cmds.artUserPaintCtx
        def configure(name,**kwargs):
            result=original(name,**kwargs)
            if kwargs.get('edit') and 'stampProfile' in kwargs:
                self.session.initialize('meshShape');self.session.before_stroke();self.session.set_value(1,0,.91);self.session.after_stroke()
            return result
        self.api.cmds.artUserPaintCtx=configure;self.session.set_brush_profile('poly')
        self.assertIsNone(self.session.stroke);self.assertEqual(self.api.snapshot(),before);self.assertFalse(self.session._configuring_view)


@unittest.skipIf(QtWidgets is None,'PySide is required')
class FalloffUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        import layer_skin_ui as ui
        from test_layer_skin_ui import Adapter
        self.api=Adapter();self.window=ui.LayerUI(self.api);self.window.target.setText('mesh');self.window.show();self.window.refresh();self.app.processEvents()
    def tearDown(self):self.window.close();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
    def choose(self,profile):self.window.brush_falloff.setCurrentIndex(self.window.brush_falloff.findData(profile))
    def test_ui_defaults_are_explicit_and_profile_control_fits_at_minimum_width(self):
        w=self.window;self.assertEqual(w.brush_falloff.currentData(),'solid');self.assertEqual(w.brush_opacity.value(),1.)
        w.resize(1040,940);self.app.processEvents()
        self.assertLess(w.brush_opacity.geometry().right(),w.brush_falloff.x())
        scroll=w.dock_layout.centralWidget();self.assertLessEqual(scroll.widget().width(),scroll.viewport().width())
        self.assertTrue(w.paint());self.assertEqual(self.api.context_settings['stampProfile'],'solid')
    def test_profile_change_and_joint_switch_retain_chosen_falloff_and_live_context(self):
        w=self.window;w.paint();starts=w.session.context_starts;self.choose('gaussian');self.api.events=[]
        w.choose_joint('|b');w.paint();w.session.refresh_view(force=True)
        self.assertEqual(self.api.context_settings['stampProfile'],'gaussian');self.assertEqual(w.session.context_starts,starts)
        self.assertFalse(any(e[0]=='paint_ctx' and e[2].get('colorfeedback') is False for e in self.api.events))
    def test_relax_disables_native_falloff_selector_and_retains_existing_smooth_solver(self):
        w=self.window;self.choose('gaussian');w.operation_radios['relax'].setChecked(True)
        self.assertFalse(w.brush_falloff.isEnabled());self.assertIn('own smooth curve',w.brush_falloff.toolTip())
        w.operation_radios['replace'].setChecked(True);self.assertTrue(w.brush_falloff.isEnabled());self.assertEqual(w.brush_falloff.currentData(),'gaussian')
    def test_rejected_pending_stroke_reverts_profile_choice_without_losing_layer_values(self):
        w=self.window;w.paint();s=w.session;s.before_stroke();self.api.paint_buffer.write([.35]*3)
        before=self.api.snapshot();self.api.fail=True;self.choose('gaussian')
        self.assertEqual(w.brush_falloff.currentData(),'solid');self.assertEqual(s.brush_profile,'solid')
        self.assertEqual(self.api.context_settings['stampProfile'],'solid');self.assertEqual(self.api.snapshot(),before)
    def test_native_tool_setting_profile_changes_sync_without_overwriting_other_fields(self):
        w=self.window;w.paint();self.api.context_settings['stampProfile']='poly';w.sync_brush_settings()
        self.assertEqual(w.brush_falloff.currentData(),'poly');self.assertEqual(w.session.brush_profile,'poly')
        self.assertEqual(w.value.value(),1.);w.session.reload_feedback();self.assertEqual(self.api.context_settings['stampProfile'],'poly')
    def test_warm_refresh_preserves_explicit_profile_and_all_operation_values(self):
        import layer_skin_ui_refresh as refresh
        w=self.window;w.value.setValue(.6);w.add_value.setValue(.2);w.scale_value.setValue(.8);self.choose('poly');w.paint()
        before=self.api.snapshot();history=list(self.api.undo_stack);self.window=refresh.refresh(w);w=self.window
        self.assertEqual(w.brush_falloff.currentData(),'poly');self.assertEqual(w.session.brush_profile,'poly')
        self.assertEqual((w.value.value(),w.add_value.value(),w.scale_value.value()),(.6,.2,.8))
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.undo_stack,history)
        w.paint();self.assertEqual(self.api.context_settings['stampProfile'],'poly')
    def test_upgrade_from_a_window_without_a_falloff_control_adopts_solid_once(self):
        import layer_skin_ui_refresh as refresh
        w=self.window;self.choose('gaussian');w.paint();before=self.api.snapshot()
        # Model the pre-UI15 public window contract while retaining real Qt
        # controls, Session and command/buffer adapters.
        del w.brush_falloff
        with mock.patch.object(w,'sync_brush_settings'):
            self.window=refresh.refresh(w)
        self.assertEqual(self.window.brush_falloff.currentData(),'solid');self.assertEqual(self.window.session.brush_profile,'solid')
        self.assertEqual(self.api.snapshot(),before);self.window.paint();self.assertEqual(self.api.context_settings['stampProfile'],'solid')


if __name__=='__main__':unittest.main()
