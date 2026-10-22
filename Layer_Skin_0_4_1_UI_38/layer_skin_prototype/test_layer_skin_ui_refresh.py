"""Open/refresh entry-point guards and discovery of real Qt editors."""
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock
import layer_skin_launch as launch
import layer_skin_ui_refresh as refresh_ui
import test_layer_skin_launch as launch_tests
from test_layer_skin_ui import Adapter, JointSceneAPI, ui


class RefreshEntryTests(unittest.TestCase):
    def test_explicit_window_skips_discovery_and_launch(self):
        window=object()
        with mock.patch.object(refresh_ui,'current_window') as discover, mock.patch.object(refresh_ui,'_open_current_folder') as open_ui:
            self.assertIs(refresh_ui._refresh_window(window),window)
        discover.assert_not_called();open_ui.assert_not_called()

    def test_existing_window_is_reused_without_launch(self):
        window=object()
        with mock.patch.object(refresh_ui,'current_window',return_value=window), mock.patch.object(refresh_ui,'_open_current_folder') as open_ui:
            self.assertIs(refresh_ui._refresh_window(),window)
        open_ui.assert_not_called()

    def test_absent_window_launches_once_then_finds_the_editor(self):
        window=object()
        with mock.patch.object(refresh_ui,'current_window',side_effect=[None,window]) as discover, mock.patch.object(refresh_ui,'_open_current_folder') as open_ui:
            self.assertIs(refresh_ui._refresh_window(),window)
        open_ui.assert_called_once_with();self.assertEqual(discover.call_count,2)

    def test_ambiguous_editors_do_not_trigger_another_launch(self):
        with mock.patch.object(refresh_ui,'current_window',side_effect=RuntimeError('More than one Layer Skin window')), mock.patch.object(refresh_ui,'_open_current_folder') as open_ui:
            with self.assertRaisesRegex(RuntimeError,'More than one'):refresh_ui._refresh_window()
        open_ui.assert_not_called()

    def test_launch_failure_is_reported_without_retry_or_fallback_unload(self):
        with mock.patch.object(refresh_ui,'current_window',return_value=None), mock.patch.object(refresh_ui,'_open_current_folder',side_effect=RuntimeError('registered version mismatch')) as open_ui:
            with self.assertRaisesRegex(RuntimeError,'registered version mismatch'):refresh_ui._refresh_window()
        open_ui.assert_called_once_with()

    def test_missing_editor_after_launch_reports_the_actual_failure(self):
        with mock.patch.object(refresh_ui,'current_window',return_value=None), mock.patch.object(refresh_ui,'_open_current_folder') as open_ui:
            with self.assertRaisesRegex(RuntimeError,'launched but no live editor'):refresh_ui._refresh_window()
        open_ui.assert_called_once_with()

    def test_source_folder_works_without_a_file_global(self):
        expected=Path(refresh_ui.refresh.__code__.co_filename).resolve().parent
        with mock.patch.object(refresh_ui,'__file__',None):self.assertEqual(Path(refresh_ui._source_folder()),expected)

    def test_missing_sibling_launcher_reports_incomplete_package(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(refresh_ui,'_source_folder',return_value=folder):
            with self.assertRaisesRegex(RuntimeError,'Missing layer_skin_launch.py'):refresh_ui._open_current_folder()

    def test_launch_uses_the_exact_sibling_instead_of_an_imported_other_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'layer_skin_launch.py').write_text('def open_ui(folder=None):\n    return folder\n')
            wrong=types.SimpleNamespace(open_ui=mock.Mock(side_effect=AssertionError('wrong launcher used')))
            with mock.patch.object(refresh_ui,'_source_folder',return_value=folder), mock.patch.dict(sys.modules,{'layer_skin_launch':wrong}):
                self.assertEqual(refresh_ui._open_current_folder(),folder)
            wrong.open_ui.assert_not_called()

    def maya(self,cmds):
        maya=types.ModuleType('maya');maya.cmds=cmds
        return mock.patch.dict(sys.modules,{'maya':maya,'maya.cmds':cmds})

    def test_auto_open_reuses_matching_registered_command_without_reloading(self):
        cmds=launch_tests.MayaCommands();path=Path(refresh_ui._source_folder())/'layer_skin_test.py'
        cmds.plugins['renamedPlugin']=dict(command=['rtkLayerSkin'],path=str(path),version=launch.disk_version(path))
        with self.maya(cmds):self.assertEqual(refresh_ui._open_current_folder(),'window')
        self.assertEqual(cmds.loads,[]);self.assertEqual(cmds.ui_calls,[dict(action='ui')])

    def test_auto_open_still_rejects_a_different_version_or_folder(self):
        path=Path(refresh_ui._source_folder())/'layer_skin_test.py'
        for version,registered_path in (('0.4.0',str(path)),('0.4.1',str(path.parent/'different'/'layer_skin_test.py'))):
            with self.subTest(version=version,path=registered_path):
                cmds=launch_tests.MayaCommands();cmds.plugins['registeredOwner']=dict(command=['rtkLayerSkin'],path=registered_path,version=version)
                with self.maya(cmds), self.assertRaisesRegex(RuntimeError,'do not match'):refresh_ui._open_current_folder()
                self.assertEqual(cmds.loads,[]);self.assertEqual(cmds.ui_calls,[])

    def test_auto_open_fresh_loads_the_exact_package_plugin(self):
        cmds=launch_tests.MayaCommands();path=Path(refresh_ui._source_folder())/'layer_skin_test.py'
        with self.maya(cmds):self.assertEqual(refresh_ui._open_current_folder(),'window')
        self.assertEqual(cmds.loads,[str(path)]);self.assertEqual(cmds.ui_calls,[dict(action='ui')])


@unittest.skipIf(ui is None,'PySide is required')
class RefreshDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=ui.QtWidgets.QApplication.instance() or ui.QtWidgets.QApplication([])
    def setUp(self):
        self.api=Adapter();self.api.WINDOW='rtkLayerSkinPrototypeWindow';self.windows=[]
    def tearDown(self):
        for window in self.windows:
            if ui.shiboken.isValid(window):window.close()
        self.app.sendPostedEvents(None,ui.QtCore.QEvent.DeferredDelete);self.app.processEvents()
    def editor(self,parent=None):
        window=ui.LayerUI(self.api,parent);self.windows.append(window)
        window.target.setText('mesh');window.show();window.refresh();self.app.processEvents()
        return window

    def test_no_editor_returns_none_instead_of_the_old_error(self):
        self.assertIsNone(refresh_ui.current_window())

    def test_hidden_editor_is_found_and_refreshed_without_a_duplicate_launch(self):
        window=self.editor();window.choose_joint('|b');window.value.setValue(.4);window.hide()
        before=self.api.snapshot();target=window.target.text();self.assertIs(refresh_ui.current_window(),window)
        with mock.patch.object(refresh_ui,'_open_current_folder') as open_ui:
            replacement=refresh_ui.refresh();self.windows.append(replacement)
        open_ui.assert_not_called();self.app.processEvents()
        self.assertTrue(window._closed);self.assertTrue(replacement.isVisible())
        self.assertEqual(replacement.target.text(),target);self.assertEqual(replacement.active_joint(),'b')
        self.assertEqual(replacement.value.value(),.4);self.assertEqual(self.api.snapshot(),before)
        self.assertIn('UI 38',replacement.windowTitle())

    def test_refresh_preserves_joint_search_and_current_target(self):
        self.api=JointSceneAPI();self.api.WINDOW='rtkLayerSkinPrototypeWindow'
        window=self.editor();window.choose_joint(self.api.joint_paths[-1])
        window.browser.search.setText('joint3');before=self.api.snapshot()
        replacement=refresh_ui.refresh(window);self.windows.append(replacement);self.app.processEvents()
        self.assertEqual(replacement.browser.search.text(),'joint3')
        self.assertEqual(replacement.active_joint(),self.api.ids[-1])
        self.assertEqual(replacement.browser.joints(),[self.api.joint_paths[-1]])
        self.assertIn('1 of 3 joints match',replacement.browser.search_status.text())
        self.assertEqual(self.api.snapshot(),before)

    def test_embedded_editor_is_found_outside_top_level_widgets(self):
        parent=ui.QtWidgets.QWidget();self.windows.append(parent);parent.show()
        window=self.editor(parent);window.setWindowFlags(ui.QtCore.Qt.Widget);window.show();self.app.processEvents()
        self.assertNotIn(window,self.app.topLevelWidgets())
        self.assertIs(refresh_ui.current_window(),window)

    def test_embedded_refresh_keeps_widget_flags_and_parent_layout(self):
        parent=ui.QtWidgets.QWidget();self.windows.append(parent)
        layout=ui.QtWidgets.QVBoxLayout(parent);parent.show()
        window=self.editor(parent);window.setWindowFlags(ui.QtCore.Qt.Widget);layout.addWidget(window)
        window.show();self.app.processEvents()
        replacement=refresh_ui.refresh();self.windows.append(replacement);self.app.processEvents()
        self.assertFalse(replacement.isWindow());self.assertIs(replacement.parentWidget(),parent)
        self.assertEqual(layout.indexOf(window),-1);self.assertGreaterEqual(layout.indexOf(replacement),0)
        self.assertTrue(replacement.isVisible());self.assertTrue(window._closed)

    def test_closed_or_deleted_editor_is_not_reused(self):
        window=self.editor();window.close();self.assertIsNone(refresh_ui.current_window())
        window.deleteLater();self.app.sendPostedEvents(None,ui.QtCore.QEvent.DeferredDelete)
        self.assertFalse(ui.shiboken.isValid(window));self.assertIsNone(refresh_ui.current_window())

    def test_duplicate_editors_raise_a_specific_error_without_closing_them(self):
        first=self.editor();second=self.editor()
        with self.assertRaisesRegex(RuntimeError,'More than one Layer Skin window'):refresh_ui.current_window()
        self.assertFalse(first._closed);self.assertFalse(second._closed)

    def test_unrelated_widget_with_the_same_name_is_ignored(self):
        unrelated=ui.QtWidgets.QWidget();self.windows.append(unrelated)
        unrelated.setObjectName('rtkLayerSkinPrototypeWindow');unrelated.show()
        self.assertIsNone(refresh_ui.current_window())

    def test_refresh_can_start_with_no_editor_and_finish_with_one_current_ui(self):
        before=self.api.snapshot()
        with mock.patch.object(refresh_ui,'_open_current_folder',side_effect=self.editor) as open_ui:
            replacement=refresh_ui.refresh();self.windows.append(replacement)
        open_ui.assert_called_once_with();self.assertIs(refresh_ui.current_window(),replacement)
        self.assertIn('UI 38',replacement.windowTitle());self.assertEqual(self.api.snapshot(),before)


if __name__=='__main__':unittest.main(verbosity=2)
