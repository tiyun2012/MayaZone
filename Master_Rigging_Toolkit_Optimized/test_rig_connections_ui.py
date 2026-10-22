"""Nested modular-rig tabs and reviewed hierarchy plans with real Qt widgets."""
import ast
from pathlib import Path
import unittest
import test_root_foot_ui as existing
import test_rig_connections as cases

QtWidgets=existing.QtWidgets


@unittest.skipIf(QtWidgets is None,'Qt unavailable')
class RigConnectionUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):existing.RootFootUiTests.setUpClass.__func__(cls)
    def setUp(self):
        existing.RootFootUiTests.setUp(self)
        fixture=cases.RigConnectionTests();fixture.tree=self.tree;fixture.setUp()
        self.fixture=fixture;self.ns.update(fixture.ns)
        cases.load_connections(self.ns,self.tree)
        wanted={'_RigConnectionsPanel','TabModularRig'}
        nodes=[n for n in self.tree.body if isinstance(n,ast.ClassDef) and n.name in wanted]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<Connections Qt>','exec'),self.ns)
    tearDown=existing.RootFootUiTests.tearDown

    def panel(self):
        panel=self.ns['_RigConnectionsPanel']();self.panels.append(panel);panel.show();self.app.processEvents();return panel
    def choose_root(self,p,root):
        p.roots.setCurrentIndex(p.roots.findData(self.fixture.state(root)['meta']));self.app.processEvents()
    def choose_child(self,p,child):
        identity=self.fixture.state(child)['meta']
        for i in range(p.tree.topLevelItemCount()):
            item=p.tree.topLevelItem(i)
            if item.data(0,existing.QtCore.Qt.UserRole)==identity:p.tree.setCurrentItem(item);self.app.processEvents();return item
        raise AssertionError('Child module not listed')

    def test_modules_and_connections_are_nested_tabs_with_lazy_connections(self):
        self.fixture.scene();p=self.ns['TabModularRig']();self.panels.append(p);p.show();self.app.processEvents()
        self.assertEqual([p.tabs.tabText(i) for i in range(p.tabs.count())],['Modules','Connections'])
        self.assertIsInstance(p.modules_panel,self.ns['_RigModulesPanel']);self.assertIsNone(p.connections_panel)
        p.tabs.setCurrentIndex(1);self.app.processEvents()
        self.assertIsInstance(p.connections_panel,self.ns['_RigConnectionsPanel'])
        self.assertTrue(p.connections_panel.report)

    def test_scan_auto_populates_missing_modules_and_right_side_suggestion(self):
        root,foot,leaf=self.fixture.scene();p=self.panel();self.choose_root(p,root)
        self.assertEqual(p.tree.topLevelItemCount(),2)
        self.choose_child(p,leaf)
        self.assertEqual(p.parents.currentData(),self.fixture.state(foot)['meta'])
        self.assertEqual(p.outputs.currentData(),self.fixture.state(foot)['outputs'][-1]['node'])
        self.assertEqual(p.method.currentData(),'parent_constraint')
        self.assertTrue(p.connect_button.isEnabled())

    def test_scan_and_tab_switch_do_not_mutate_scene_or_create_undo_steps(self):
        self.fixture.scene();before=self.fixture.snapshot();chunks=self.fixture.cmds.chunks[:]
        p=self.ns['TabModularRig']();self.panels.append(p);p.tabs.setCurrentIndex(1);self.app.processEvents()
        p.tabs.setCurrentIndex(0);p.tabs.setCurrentIndex(1);self.app.processEvents()
        self.assertEqual(self.fixture.snapshot(),before);self.assertEqual(self.fixture.cmds.chunks,chunks)

    def test_place_only_root_can_get_and_message_link_scan_start(self):
        root=self.fixture.root();p=self.panel();self.choose_root(p,root)
        self.fixture.cmds.selection=[self.fixture.fixture.ankle];p._get_start()
        self.assertFalse(self.fixture.state(root)['start_joint'])
        p._set_start();self.assertEqual(p.report['root_start'],self.fixture.ns['_guide_ik_uuid'](self.fixture.fixture.ankle))
        self.assertFalse(self.fixture.state(root)['joints'])

    def test_planned_space_switch_is_visibly_disabled(self):
        self.fixture.scene();p=self.panel();index=p.method.findData('space_switch')
        self.assertGreaterEqual(index,0);self.assertFalse(p.method.model().item(index).isEnabled())

    def test_selected_native_connection_disappears_from_attention_list_then_detaches(self):
        root,foot,_leaf=self.fixture.scene();p=self.panel();self.choose_root(p,root);self.choose_child(p,foot)
        p._connect_selected();self.app.processEvents()
        self.assertEqual(self.fixture.state(foot)['attachment']['method'],'parent_constraint')
        self.assertEqual(p.tree.topLevelItemCount(),1)
        p.missing_only.setChecked(False);self.choose_child(p,foot)
        self.assertFalse(p.connect_button.isEnabled());self.assertTrue(p.detach_button.isEnabled())
        p._detach();self.assertNotIn('attachment',self.fixture.state(foot))

    def test_parent_method_edits_are_retained_when_switching_child_rows(self):
        root,foot,leaf=self.fixture.scene();p=self.panel();self.choose_root(p,root);self.choose_child(p,leaf)
        p.parents.setCurrentIndex(p.parents.findData(self.fixture.state(root)['meta']))
        p.method.setCurrentIndex(p.method.findData('matrix_parent'))
        output=p.outputs.currentData()
        self.choose_child(p,foot);self.choose_child(p,leaf)
        self.assertEqual(p.parents.currentData(),self.fixture.state(root)['meta'])
        self.assertEqual(p.outputs.currentData(),output);self.assertEqual(p.method.currentData(),'matrix_parent')

    def test_connect_checked_applies_whole_plan_with_one_undo(self):
        root,foot,leaf=self.fixture.scene();p=self.panel();self.choose_root(p,root)
        before=self.fixture.snapshot();chunks=len(self.fixture.cmds.chunks)
        p._connect_checked();self.app.processEvents()
        self.assertEqual(self.fixture.cmds.chunks[chunks:],['open','close'])
        self.assertTrue(self.fixture.state(foot).get('attachment'));self.assertTrue(self.fixture.state(leaf).get('attachment'))
        self.fixture.cmds.undo();self.assertEqual(self.fixture.snapshot(),before)

    def test_rename_after_scan_and_before_connect_uses_cached_identities(self):
        root,foot,leaf=self.fixture.scene();p=self.panel();self.choose_root(p,root);self.choose_child(p,leaf)
        output=p.outputs.currentData();self.fixture.cmds.rename(self.fixture.node(output),'ChangedSocketName')
        self.fixture.cmds.rename(self.fixture.fixture.ball,'ChangedJointName')
        p._connect_selected();self.assertEqual(self.fixture.state(leaf)['attachment']['output'],output)

    def test_connected_matrix_method_is_shown_correctly_without_being_replaced(self):
        root,foot,_leaf=self.fixture.scene();self.ns['attach_rig_module'](foot['module'],root['placement_output'])
        p=self.panel();self.choose_root(p,root);p.missing_only.setChecked(False);self.choose_child(p,foot)
        self.assertEqual(p.method.currentData(),'matrix_parent');self.assertFalse(p.method.isEnabled())

    def test_nested_page_fits_700_pixel_window_without_horizontal_scroll(self):
        self.fixture.scene();p=self.ns['TabModularRig']();self.panels.append(p)
        scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(p);scroll.resize(700,900);scroll.show()
        p.tabs.setCurrentIndex(1);self.app.processEvents()
        try:
            self.assertEqual(scroll.horizontalScrollBar().maximum(),0)
            self.assertEqual(p.connection_scroll.horizontalScrollBar().maximum(),0)
        finally:scroll.takeWidget();scroll.close();scroll.deleteLater()


if __name__=='__main__':unittest.main()
