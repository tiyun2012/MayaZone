"""Real Qt module output list and attachment actions with command fixtures."""
import unittest
from pathlib import Path
import test_root_foot_ui as existing
from test_rig_module_outputs import load_api

QtWidgets=existing.QtWidgets


@unittest.skipIf(QtWidgets is None,'Qt unavailable')
class ModuleOutputUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):existing.RootFootUiTests.setUpClass.__func__(cls)
    def setUp(self):
        existing.RootFootUiTests.setUp(self);load_api(self.ns,self.tree)
    tearDown=existing.RootFootUiTests.tearDown
    manager=existing.RootFootUiTests.manager
    rig_row=existing.RootFootUiTests.rig_row

    def choose(self,p,rig):p.modules.setCurrentIndex(self.rig_row(p,rig['module']));self.app.processEvents()

    def test_all_registered_outputs_appear_with_joint_names_and_select_button(self):
        rig=self.fixture.foot();p=self.manager();self.choose(p,rig)
        self.assertEqual(p.outputs_table.rowCount(),2)
        for row in range(2):
            self.assertTrue(p.outputs_table.item(row,0).text().endswith('_OUTPUT'))
            self.assertEqual(p.outputs_table.item(row,1).text(),self.fixture.cmds.joints[row].rsplit('|',1)[-1])
            p.outputs_table.cellWidget(row,2).click();self.app.processEvents()
            self.assertEqual(self.fixture.cmds.selection[0].rsplit('|',1)[-1],p.outputs_table.item(row,0).text())

    def test_parent_output_stays_loaded_after_switching_to_child_and_attach_detach_work(self):
        parent=self.fixture.root();child=self.fixture.foot();p=self.manager();self.choose(p,parent)
        p.outputs_table.selectRow(0);p._use_output();identity=p.parent_output_uuid
        self.choose(p,child);self.assertEqual(p.parent_output_uuid,identity)
        p._attach_output();self.assertIn('attached to',p.attachment_status.text())
        state=self.ns['_rig_module_read'](child['module'])[1]
        self.assertEqual(state['attachment']['output'],identity)
        p._detach_output();self.assertIn('no output attachment',p.attachment_status.text())

    def test_get_selected_rejects_joint_then_accepts_marked_output(self):
        parent=self.fixture.root();p=self.manager()
        self.fixture.cmds.selection=[self.fixture.ankle];p._get_parent_output()
        self.assertIsNone(p.parent_output_uuid);self.assertIn('marked OUTPUT',p.status.text())
        self.fixture.cmds.selection=[parent['placement_output']];p._get_parent_output()
        self.assertEqual(p.parent_output_uuid,self.ns['_guide_ik_uuid'](parent['placement_output']))

    def test_self_attach_reports_error_without_invalid_parent_state(self):
        rig=self.fixture.root();p=self.manager();self.choose(p,rig)
        p.outputs_table.selectRow(0);p._use_output();p._attach_output()
        self.assertIn('own output',p.status.text())
        self.assertNotIn('attachment',self.ns['_rig_module_read'](rig['module'])[1])

    def test_repeated_publish_refresh_does_not_duplicate_rows(self):
        rig=self.fixture.foot();p=self.manager();self.choose(p,rig)
        for _ in range(3):p._publish_outputs()
        self.assertEqual(p.outputs_table.rowCount(),2)
        self.assertEqual(p.module_rows.rowCount(),1)

    def test_deleted_output_is_disabled_in_table(self):
        rig=self.fixture.root();self.fixture.cmds.delete(rig['placement_output']);p=self.manager()
        self.assertIn('missing',p.outputs_table.item(0,0).text())
        self.assertFalse(p.outputs_table.cellWidget(0,2).isEnabled())

    def test_output_group_is_collapsible_and_narrow_layout_has_no_horizontal_scroll(self):
        self.fixture.root();p=self.manager()
        self.assertTrue(p.output_group.body.isVisible())
        p.output_group.set_expanded(False);self.assertFalse(p.output_group.body.isVisible())
        p.output_group.set_expanded(True)
        scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(p);scroll.resize(700,900);scroll.show();self.app.processEvents()
        try:
            self.assertEqual(scroll.horizontalScrollBar().maximum(),0)
        finally:
            scroll.takeWidget();scroll.close();scroll.deleteLater()


if __name__=='__main__':unittest.main()
