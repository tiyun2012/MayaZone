"""Real Qt cleanup controls and editor orchestration with a command adapter."""
import contextlib
import copy
import unittest
from unittest import mock
from test_layer_skin_ui import Adapter,ui

if ui is not None:
    QtCore=ui.QtCore;QtWidgets=ui.QtWidgets


@unittest.skipIf(ui is None,'PySide is required for cleanup UI checks')
class CleanupUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        self.api=Adapter();self.window=ui.LayerUI(self.api);self.window.target.setText('mesh')
        self.window.show();self.window.refresh();self.app.processEvents()
        self.helper=self.window.session.helper('layer_skin_cleanup');self.stack=contextlib.ExitStack()
        self.plan=dict(mesh='meshShape',nodes=[dict(node='savedLayerData',blocked=[])],skipped=[])
        self.inspect=self.stack.enter_context(mock.patch.object(self.helper,'inspect',side_effect=lambda api,target:copy.deepcopy(self.plan)))
        self.validate=self.stack.enter_context(mock.patch.object(self.helper,'validate',return_value=self.plan))
        self.remove=self.stack.enter_context(mock.patch.object(self.helper,'remove',side_effect=self.record_remove))
        self.before_remove=None
    def tearDown(self):
        if ui.shiboken.isValid(self.window):self.window.close()
        self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete);self.stack.close()
    def record_remove(self,api,plan):
        self.before_remove=api.snapshot();api.undo_stack.append(self.before_remove);api.redo_stack=[]
        api.attached=False;self.helper.clear_caches(api)
        return dict(removed=['savedLayerData'],mesh='meshShape')
    def test_cleanup_button_opens_a_readonly_scoped_inspection_without_scene_edit(self):
        before=self.api.snapshot();dialog=self.window.open_cleanup()
        self.assertTrue(dialog.isVisible());self.assertTrue(dialog.target.isReadOnly());self.assertTrue(dialog.details.isReadOnly())
        self.assertIn('savedLayerData',dialog.details.toPlainText());self.assertIn('this mesh only',dialog.details.toPlainText())
        self.assertTrue(dialog.remove_button.isEnabled());self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.undo_stack,[])
        self.assertIn('Cleanup…',[b.text() for b in self.window.findChildren(QtWidgets.QPushButton)])
        self.assertIs(self.window.open_cleanup(),dialog)
    def test_clear_caches_saves_pending_stroke_and_retains_painted_values_and_colors(self):
        self.window.choose_joint('|b');self.window.paint();self.window.session.before_stroke();self.window.session.set_value(1,0,.7)
        self.assertTrue(self.window.clear_cache());self.assertTrue(self.api.attached)
        sample=self.api.state['layers'][-1]['samples']['0']
        self.assertAlmostEqual(sample['weights'][1]*sample['coverage'],.7)
        self.assertEqual(len(self.api.undo_stack),1);self.assertTrue(self.window.session.viewing)
        self.assertTrue(self.api.weight_view.visible);self.assertFalse(self.window.session.active)
        self.assertTrue(any(e[0]=='clear_cache' for e in self.api.events));self.remove.assert_not_called()
    def test_remove_saves_pending_paint_then_keeps_native_skin_with_metadata_only_undo(self):
        self.window.choose_joint('|b');self.window.paint();self.window.session.before_stroke();self.window.session.set_value(1,1,.65)
        result=self.window.remove_saved_layers(self.plan)
        self.assertEqual(result['removed'],['savedLayerData']);self.assertFalse(self.api.attached)
        self.assertEqual(self.api.weights,self.before_remove[2]);self.assertAlmostEqual(self.api.weights[3],.65)
        self.assertEqual(self.window.rows,[]);self.assertEqual(self.window.state['base'],self.api.weights)
        self.assertFalse(self.window.session.viewing);self.assertIsNone(self.window.session.buffer)
        self.assertFalse(self.window._working);self.assertEqual(len(self.api.undo_stack),2)
        self.api.undo();self.window.refresh();self.assertTrue(self.api.attached);self.assertEqual(len(self.window.rows),3)
        self.api.redo();self.window.refresh();self.assertFalse(self.api.attached);self.assertEqual(self.window.rows,[])
    def test_remove_keeps_external_native_skin_edits_and_plus_starts_fresh_reference(self):
        self.api.weights=[.3,.7,.8,.2,.5,.5];weights=self.api.weights[:]
        self.window.remove_saved_layers(self.plan)
        self.assertEqual(self.api.weights,weights);self.assertEqual(self.window.state['base'],weights)
        self.assertTrue(self.window.run('add'));self.assertEqual(self.api.state['base'],weights)
        self.assertIsNone(self.api.state.get('reference'));self.assertEqual(len(self.api.state['layers']),1)
    def test_invalid_current_scope_is_rejected_before_stopping_or_committing_paint(self):
        self.window.choose_joint('|b');self.window.paint();self.window.session.before_stroke();self.window.session.set_value(1,0,.6)
        self.validate.side_effect=ValueError('Current mesh changed; refresh cleanup')
        with self.assertRaisesRegex(ValueError,'Current mesh changed'):self.window.remove_saved_layers(self.plan)
        self.assertTrue(self.window.session.active);self.assertEqual(self.api.calls,[]);self.remove.assert_not_called()
        self.validate.assert_called_with(self.api,self.plan,self.window.target.text())
    def test_rejected_pending_paint_aborts_cleanup_and_preserves_saved_data(self):
        self.window.choose_joint('|b');self.window.paint();self.window.session.before_stroke();self.window.session.set_value(1,0,.6)
        self.api.fail=True;self.assertIsNone(self.window.remove_saved_layers(self.plan));self.remove.assert_not_called()
        self.assertTrue(self.api.attached);self.assertFalse(self.window._working)
    def test_protected_nodes_disable_remove_but_keep_cache_cleanup_available(self):
        self.plan['nodes'][0]['blocked']=['Data node is referenced.'];dialog=self.window.open_cleanup()
        self.assertFalse(dialog.remove_button.isEnabled());self.assertTrue(dialog.cache_button.isEnabled())
        self.assertIn('referenced',dialog.details.toPlainText());dialog.cache_button.click();self.assertTrue(self.api.attached)
    def test_unreadable_editor_can_still_open_lightweight_cleanup(self):
        self.api.metadata=lambda ctx:(_ for _ in ()).throw(ValueError('Corrupt layer payload'))
        self.assertFalse(self.window.refresh());self.assertIsNone(self.window.state)
        dialog=self.window.open_cleanup();self.assertTrue(dialog.remove_button.isEnabled())
        self.assertIn('savedLayerData',dialog.details.toPlainText());self.assertEqual(self.api.calls,[])
    def test_remove_button_reports_success_and_after_delete_cache_warning(self):
        def remove(api,plan):
            result=self.record_remove(api,plan);self.plan['nodes']=[];result['cache_warning']='Memory cache warning';return result
        self.remove.side_effect=remove;dialog=self.window.open_cleanup();dialog.remove_button.click()
        self.assertIn('Removed 1',dialog.status.text());self.assertIn('Memory cache warning',dialog.status.text())
        self.assertFalse(dialog.remove_button.isEnabled());self.assertFalse(self.api.attached)
    def test_remove_failure_releases_working_guard_and_reports_the_error(self):
        self.remove.side_effect=RuntimeError('Native delete rejected');dialog=self.window.open_cleanup();dialog.remove_button.click()
        self.assertIn('Native delete rejected',dialog.status.text());self.assertTrue(self.api.attached);self.assertFalse(self.window._working)
    def test_scene_change_closes_the_stale_cleanup_scope_and_clears_caches(self):
        dialog=self.window.open_cleanup();self.window.scene_reset()
        self.assertFalse(dialog.isVisible());self.assertIsNone(self.window._cleanup_dialog)
        self.assertTrue(any(e[0]=='clear_cache' for e in self.api.events));self.assertTrue(self.api.attached)
    def test_closing_and_reopening_cleanup_makes_a_fresh_inspection(self):
        first=self.window.open_cleanup();first.close();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        self.plan['nodes']=[];second=self.window.open_cleanup()
        self.assertIsNot(first,second);self.assertFalse(second.remove_button.isEnabled());self.assertGreaterEqual(self.inspect.call_count,2)
