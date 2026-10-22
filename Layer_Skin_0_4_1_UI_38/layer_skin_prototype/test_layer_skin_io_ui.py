"""Real Qt Utilities workflow with file IO and a recording scene/backend adapter."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import layer_skin_core as core
import layer_skin_io as io
import test_layer_skin_io as file_fixtures
from test_layer_skin_ui import Adapter,ui

if ui is not None:QtCore=ui.QtCore;QtWidgets=ui.QtWidgets


class RecordingBackend:
    def __init__(self,api):self.api=api;self.calls=[];self.fail=None;self.current_joint='|c'
    def selected_mesh(self):return 'meshShape'
    def selected_joint(self):return self.current_joint
    def export(self,target,path,geometry,include_geometry,overwrite):
        self.calls.append(('export',target,path,geometry,include_geometry,overwrite))
        if self.fail:raise RuntimeError(self.fail)
        value=file_fixtures.snapshot();value['weights']=self.api.weights[:]
        if not include_geometry:value.pop('points');value.pop('triangles')
        return io.write(path,value,overwrite)
    def preview(self,snapshot,target,**settings):
        self.calls.append(('preview',target,copy.deepcopy(settings)))
        if self.fail:raise RuntimeError(self.fail)
        candidates=[dict(uuid=name,path='|'+name,position=[i,0,0]) for i,name in enumerate(('a','b','c'))]
        report=io.map_joints(snapshot,candidates,settings['options'],settings['manual'])
        converted=io.project(snapshot,dict(count=3,topology=snapshot['topology'],points=[(0,0,0),(1,0,0),(0,1,0)]),settings['method'],settings['max_distance'])
        mapping={r['source_uuid']:r['target_uuid'] for r in report['rows']}
        payload=dict(count=3,name=settings['name'],source_ids=[r['uuid'] for r in snapshot['influences']],mapping=[mapping[r['uuid']] for r in snapshot['influences']],weights=converted['weights'])
        return dict(target=target,payload=payload,report=report,skin='skin',missing=[])
    def commit(self,plan,create_skin,add_influences):
        self.calls.append(('commit',create_skin,add_influences))
        if self.fail:raise RuntimeError(self.fail)
        before=self.api.snapshot();self.api.state=io.import_state(core,self.api.state,self.api.context('mesh'),plan['payload'])
        self.api.weights=core.composite(self.api.state);self.api.attached=True;self.api.undo_stack.append(before)
        return 'Skin imported as a new layer.'


@unittest.skipIf(ui is None,'PySide is required')
class UtilitiesUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'skin.rtkskin';io.write(self.path,file_fixtures.snapshot())
        self.api=Adapter();self.backend=RecordingBackend(self.api);self.api.make_skin_io_backend=lambda session:self.backend
        self.window=ui.LayerUI(self.api);self.window.target.setText('mesh');self.window.show();self.window.refresh();self.app.processEvents()
        self.page=self.window.utilities
    def tearDown(self):
        if ui.shiboken.isValid(self.window):self.window.close()
        self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
    def load(self):
        self.window.tabs.setCurrentIndex(1);self.page.import_path.setText(str(self.path));self.page.target.setText('meshShape');self.page.load_file()
    def test_utilities_is_a_real_second_tab_and_does_not_read_skin_until_requested(self):
        self.assertEqual([self.window.tabs.tabText(i) for i in range(self.window.tabs.count())],['Layers','Utilities'])
        self.assertIs(self.window.tabs.widget(1),self.page);self.assertIsNone(self.page._backend);self.assertEqual(self.backend.calls,[])
        self.assertTrue(all(not b.autoDefault() for b in self.window.findChildren(QtWidgets.QPushButton)))
    def test_primary_preview_import_actions_stay_visible_while_scrolling_options(self):
        self.window.tabs.setCurrentIndex(1);self.app.processEvents()
        before=self.page.preview_button.mapTo(self.window,self.page.preview_button.rect().center())
        self.assertTrue(self.window.rect().contains(before));self.page.verticalScrollBar().setValue(self.page.verticalScrollBar().maximum());self.app.processEvents()
        after=self.page.preview_button.mapTo(self.window,self.page.preview_button.rect().center())
        self.assertEqual(before,after);self.assertTrue(self.window.rect().contains(self.page.import_button.mapTo(self.window,self.page.import_button.rect().center())))
    def test_switching_to_utilities_saves_pending_stroke_and_stops_native_paint(self):
        self.window.choose_joint('|b');self.window.paint();self.window.session.before_stroke();self.window.session.set_value(1,0,.7)
        self.window.tabs.setCurrentIndex(1)
        self.assertEqual(len(self.api.calls),1);self.assertFalse(self.window.session.active);self.assertEqual(self.window.tabs.currentIndex(),1)
        self.assertAlmostEqual(self.api.weights[1],.7)
    def test_rejected_pending_paint_keeps_layers_page_active(self):
        self.window.choose_joint('|b');self.window.paint();self.window.session.before_stroke();self.window.session.set_value(1,0,.7);self.api.fail=True
        self.window.tabs.setCurrentIndex(1);self.assertEqual(self.window.tabs.currentIndex(),0);self.assertEqual(self.backend.calls,[])
    def test_load_and_preview_are_readonly_and_mapping_is_visible(self):
        before=self.api.snapshot();self.load();self.page.preview_import()
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.page.table.rowCount(),2)
        self.assertTrue(self.page.import_button.isEnabled());self.assertEqual(self.page.table.item(0,1).text(),'|a')
        self.assertIsNone(QtWidgets.QApplication.overrideCursor());self.assertFalse(self.window._working)
    def test_import_creates_top_layer_and_undo_returns_previous_stack(self):
        self.load();self.page.preview_import();before=self.api.snapshot();self.page.import_file()
        self.assertEqual(len(self.window.rows),4);self.assertEqual(self.api.weights,[1,0,0,1,1,0])
        self.assertEqual(self.window.layer()['name'],'skin_import');self.assertFalse(self.page.import_button.isEnabled())
        self.window.history(False);self.assertEqual(self.api.snapshot(),before)
    def test_changing_options_invalidates_preview_and_unmatched_mapping_blocks_import(self):
        self.load();self.page.preview_import();self.page.search.setText('joint');self.assertIsNone(self.page.plan)
        self.assertFalse(self.page.import_button.isEnabled());self.page.preview_import()
        self.assertTrue(self.page.import_button.isEnabled());self.page.manual={'a':None};self.page.preview_import()
        self.assertFalse(self.page.import_button.isEnabled());self.assertIn('Resolve',self.page.note.text())
    def test_manual_mapping_uses_selected_row_and_selected_joint_then_preview(self):
        self.load();self.page.preview_import();self.page.table.setCurrentCell(0,0);self.page.map_selected()
        self.assertEqual(self.page.manual,{'a':'c'});self.assertEqual(self.page.table.item(0,1).text(),'|c')
        self.assertEqual(self.backend.calls[-1][2]['manual_paths'],{'c':'|c'})
        self.page.table.setCurrentCell(0,0);self.page.clear_manual();self.assertEqual(self.page.manual,{})
        self.assertEqual(self.backend.calls[-1][2]['manual_paths'],{})
    def test_surface_settings_and_dq_flags_are_forwarded(self):
        self.load();self.page.method.setCurrentIndex(1);self.page.target_geometry.setCurrentIndex(1)
        self.page.max_distance.setValue(.25);self.page.copy_dq.setChecked(False);self.page.copy_method.setChecked(False);self.page.preview_import()
        settings=self.backend.calls[-1][2]
        self.assertEqual(settings['method'],'surface');self.assertEqual(settings['geometry'],'current');self.assertEqual(settings['max_distance'],.25)
        self.assertFalse(settings['copy_dq']);self.assertFalse(settings['copy_method'])
    def test_corrupt_file_failure_restores_cursor_and_releases_working_guard(self):
        self.page.import_path.setText(str(self.path));self.path.write_bytes(b'not a skin archive');self.page.load_file()
        self.assertIsNone(self.page.snapshot);self.assertIsNone(QtWidgets.QApplication.overrideCursor());self.assertFalse(self.window._working)
        self.assertTrue(self.page.isEnabled());self.assertFalse(self.page._busy)
    def test_preview_or_import_failure_restores_cursor_and_scene(self):
        self.load();before=self.api.snapshot();self.backend.fail='Preview rejected';self.page.preview_import()
        self.assertIsNone(self.page.plan);self.assertIn('Preview rejected',self.page.note.text())
        self.backend.fail=None;self.page.preview_import();self.backend.fail='Import rejected';self.page.import_file()
        self.assertEqual(self.api.snapshot(),before);self.assertIn('Import rejected',self.page.note.text())
        self.assertIsNone(QtWidgets.QApplication.overrideCursor());self.assertFalse(self.window._working)
    def test_changed_file_requires_reload_and_does_not_use_stale_snapshot(self):
        self.load();self.page.preview_import();calls=len(self.backend.calls)
        self.path.write_bytes(self.path.read_bytes()+b'changed');self.page.import_file()
        self.assertEqual(len(self.backend.calls),calls);self.assertIn('changed on disk',self.page.note.text())
    def test_export_saves_pending_paint_and_writes_final_skin_file(self):
        self.window.choose_joint('|b');self.window.paint();self.window.session.before_stroke();self.window.session.set_value(1,0,.7)
        path=Path(self.folder.name)/'export';self.page.export_mesh.setText('meshShape');self.page.export_path.setText(str(path));self.page.export_file()
        actual=io.read(str(path)+'.rtkskin');self.assertAlmostEqual(actual['weights'][1],.7)
        self.assertEqual(len(self.api.undo_stack),1);self.assertIsNone(QtWidgets.QApplication.overrideCursor())
    def test_overwrite_cancel_keeps_existing_file_and_does_not_start_export(self):
        self.page.export_path.setText(str(self.path));before=self.path.read_bytes()
        with mock.patch.object(QtWidgets.QMessageBox,'question',return_value=QtWidgets.QMessageBox.Cancel):self.page.export_file()
        self.assertEqual(self.path.read_bytes(),before);self.assertEqual(self.backend.calls,[])
    def test_scene_change_clears_targets_and_preview_but_keeps_loaded_external_file(self):
        self.load();self.page.preview_import();loaded=self.page.snapshot;self.window.scene_reset()
        self.assertIs(self.page.snapshot,loaded);self.assertEqual(self.page.target.text(),'');self.assertIsNone(self.page.plan)
        self.assertEqual(self.page.table.rowCount(),0);self.assertFalse(self.page.import_button.isEnabled())
    def test_unload_releases_cached_file_without_scene_edits(self):
        self.load();before=self.api.snapshot();self.page.unload_file()
        self.assertIsNone(self.page.snapshot);self.assertIsNone(self.page.plan);self.assertEqual(self.api.snapshot(),before)
    def test_live_refresh_preserves_utilities_controls_and_cached_file_but_requires_new_preview(self):
        import layer_skin_ui_refresh
        self.load();self.page.tolerance.setValue(.02);self.page.search.setText('joint');self.page.preview_import();loaded=self.page.snapshot
        self.window=layer_skin_ui_refresh.refresh(self.window);self.app.processEvents();self.page=self.window.utilities
        self.assertEqual(self.window.tabs.currentIndex(),1);self.assertEqual(self.page.tolerance.value(),.02);self.assertEqual(self.page.search.text(),'joint')
        self.assertIs(self.page.snapshot,loaded);self.assertIsNone(self.page.plan);self.assertFalse(self.page.import_button.isEnabled())
