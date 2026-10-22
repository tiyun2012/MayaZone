"""Real Qt controls with a recorded Maya command backend (no Maya solver)."""
import ast
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    try:
        from PySide2 import QtCore, QtGui, QtWidgets
    except ImportError:
        QtWidgets = None

from test_joint_cleanup import CleanupCommands


@unittest.skipIf(QtWidgets is None, "Maya PySide2 or PySide6 is required for UI checks")
class JointCleanupUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.source = Path(__file__).with_name("master_rigging_toolkit.py")
        cls.tree = ast.parse(cls.source.read_text(encoding="utf-8"))
        wanted = {"TabJointCleanup", "_set_button_role", "_polish_native_panel"}
        cls.definitions = [node for node in cls.tree.body
                           if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in wanted]

    def setUp(self):
        self.cmds = CleanupCommands()
        maya = types.ModuleType("maya")
        maya.cmds = self.cmds
        self.modules = mock.patch.dict(sys.modules, {"maya": maya, "maya.cmds": self.cmds})
        self.modules.start()
        self.ns = {"QtWidgets": QtWidgets, "QtCore": QtCore, "QtGui": QtGui,
                   "cmds": self.cmds, "__file__": str(self.source)}
        exec(compile(ast.Module(body=self.definitions, type_ignores=[]), str(self.source), "exec"), self.ns)
        self.panel = self.ns["TabJointCleanup"]()
        self.ns["_polish_native_panel"](self.panel)

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()
        self.modules.stop()

    def button(self, text):
        return next(button for button in self.panel.findChildren(QtWidgets.QPushButton) if button.text() == text)

    def load(self):
        self.cmds.selection = ["|body"]
        self.button("Get selected meshes").click()
        self.cmds.selection = [self.cmds.root]
        self.button("Get selected").click()
        self.panel.scan_button.click()

    def find_item(self, path):
        for i in range(self.panel.table.topLevelItemCount()):
            item = self.panel.table.topLevelItem(i)
            if item.toolTip(0) == path:
                return item
        raise AssertionError("No row for " + path)

    def test_workflow_is_searchable_and_has_its_own_lazy_panel(self):
        master = next(n for n in self.tree.body if isinstance(n, ast.ClassDef) and n.name == "MasterRiggingUI")
        workflows = ast.literal_eval(next(n.value for n in master.body if isinstance(n, ast.Assign)
                                         and any(isinstance(t, ast.Name) and t.id == "WORKFLOWS" for t in n.targets)))
        entry = next(row for row in workflows if row[0] == "cleanup")
        self.assertEqual(entry[1], "Cleanup")
        self.assertIn("joint", entry[3])
        route = ast.get_source_segment(self.source.read_text(), next(n for n in master.body
                                      if isinstance(n, ast.FunctionDef) and n.name == "_navigation_changed"))
        self.assertIn('key == "cleanup"', route)
        self.assertIn("TabJointCleanup()", route)

    def test_selection_load_scan_and_right_column_delete_buttons(self):
        self.assertFalse(self.panel.delete_all.isEnabled())
        self.load()
        self.assertEqual(self.panel.mesh_list.count(), 1)
        self.assertEqual(self.panel.root.text(), self.cmds.root)
        self.assertEqual(self.panel.table.topLevelItemCount(), 3)
        tip = self.find_item(self.cmds.tip)
        branch = self.find_item(self.cmds.branch)
        self.assertTrue(self.panel.table.itemWidget(tip, 3).isEnabled())
        self.assertFalse(self.panel.table.itemWidget(branch, 3).isEnabled())
        for i in range(self.panel.table.topLevelItemCount()):
            item = self.panel.table.topLevelItem(i)
            select = self.panel.table.itemWidget(item, 2)
            self.assertEqual(select.text(), "Select")
            self.assertTrue(select.isEnabled())
            select.click()
            self.assertEqual(self.cmds.selection, [item.toolTip(0)])
        self.assertTrue(self.panel.delete_all.isEnabled())

    def test_row_delete_refreshes_parent_button_and_undo_is_one_action(self):
        self.load()
        self.panel.table.itemWidget(self.find_item(self.cmds.tip), 3).click()
        self.assertNotIn(self.cmds.tip, self.cmds.nodes)
        self.assertTrue(self.panel.table.itemWidget(self.find_item(self.cmds.branch), 3).isEnabled())
        self.assertEqual(self.cmds.chunks, ["open", "close"])

    def test_delete_all_keeps_protected_rows(self):
        self.load()
        self.panel.delete_all.click()
        self.assertEqual(self.panel.table.topLevelItemCount(), 1)
        self.assertIn("Deleted 2", self.panel.summary.text())
        self.assertFalse(self.panel.delete_all.isEnabled())
        self.assertIn(self.cmds.bound, self.cmds.nodes)

    def test_editing_root_invalidates_delete_buttons(self):
        self.load()
        self.panel.root.setText("differentRoot")
        self.assertEqual(self.panel.table.topLevelItemCount(), 0)
        self.assertFalse(self.panel.delete_all.isEnabled())
        self.assertIsNone(self.panel._report)

    def test_multiple_mesh_loads_add_and_deduplicate(self):
        self.load()
        self.cmds.selection = [self.cmds.mesh]
        self.button("Get selected meshes").click()
        self.assertEqual(self.panel.mesh_list.count(), 1)
        self.assertFalse(self.panel.delete_all.isEnabled())
        mesh = self.cmds.add("|otherShape", "mesh")
        self.cmds.selection = [mesh]
        self.button("Get selected meshes").click()
        self.assertEqual(self.panel.mesh_list.count(), 2)
        self.panel.mesh_list.item(0).setSelected(True)
        self.button("Remove selected").click()
        self.assertEqual(self.panel.mesh_list.count(), 1)
        self.button("Clear").click()
        self.assertEqual(self.panel.mesh_list.count(), 0)

    def test_unskinned_scan_has_no_stale_deletes(self):
        self.load()
        self.cmds.history[self.cmds.mesh] = []
        self.panel.scan_button.click()
        self.assertIn("No skinClusters", self.panel.summary.text())
        self.assertEqual(self.panel.table.topLevelItemCount(), 0)
        self.assertFalse(self.panel.delete_all.isEnabled())

    def test_double_click_selects_by_identity_after_rename(self):
        self.load()
        item = self.find_item(self.cmds.tip)
        self.cmds.rename(self.cmds.tip, "|renamedTip")
        self.panel.table.itemWidget(item, 2).click()
        self.assertEqual(self.cmds.selection, ["|renamedTip"])
        self.cmds.selection = []
        self.panel.table.itemDoubleClicked.emit(item, 0)
        self.assertEqual(self.cmds.selection, ["|renamedTip"])

    def test_delete_error_invalidates_destructive_controls(self):
        self.load()
        self.cmds.fail_delete.add(self.cmds.branch)
        self.panel.delete_all.click()
        self.assertIsNone(self.panel._report)
        self.assertFalse(self.panel.delete_all.isEnabled())
        self.assertIn("rolled back", self.panel.summary.text())
        self.assertIn(self.cmds.tip, self.cmds.nodes)

    def test_unused_root_removed_clears_root_and_table(self):
        unused = self.cmds.add("|unusedRoot", "joint")
        self.load()
        self.panel.root.setText(unused)
        self.panel.scan_button.click()
        self.panel.delete_all.click()
        self.assertEqual(self.panel.root.text(), "")
        self.assertIsNone(self.panel._report)
        self.assertEqual(self.panel.table.topLevelItemCount(), 0)
        self.assertIn("unused root was removed", self.panel.summary.text())

    def test_renamed_mesh_and_root_refresh_the_display(self):
        self.load()
        self.cmds.rename("|body", "|bodyNew")
        self.cmds.rename(self.cmds.root, "|rootNew")
        self.panel.scan_button.click()
        self.assertEqual(self.panel.root.text(), "|rootNew")
        self.assertEqual(self.panel.mesh_list.item(0).toolTip(), "|bodyNew|bodyShape")

    def test_protected_other_skin_is_visible_with_disabled_delete(self):
        mesh = self.cmds.add("|otherShape", "mesh")
        self.cmds.skin("otherSkin", [self.cmds.tip], [mesh])
        self.load()
        item = self.find_item(self.cmds.tip)
        self.assertIn("otherSkin", item.text(1))
        self.assertFalse(self.panel.table.itemWidget(item, 3).isEnabled())
        self.panel.table.itemWidget(item, 2).click()
        self.assertEqual(self.cmds.selection, [self.cmds.tip])
        self.assertFalse(self.panel.delete_all.isEnabled())


if __name__ == "__main__":
    unittest.main(verbosity=2)
