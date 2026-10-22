"""Actual Qt layout and pickers with a recorded command backend."""
import ast
from pathlib import Path
import unittest
from unittest import mock
import test_root_foot_modules as cases
try:
    from PySide6 import QtCore,QtGui,QtWidgets
except ImportError:
    QtWidgets=None

@unittest.skipIf(QtWidgets is None,'Qt unavailable')
class RootFootUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())
    def setUp(self):
        # Backend AST fixture loads current functions; UI uses real Qt widgets.
        fixture=cases.RootFootTests();fixture.tree=self.tree;fixture.setUp();self.fixture=fixture;self.ns=fixture.ns
        self.ns.update(QtCore=QtCore,QtGui=QtGui,QtWidgets=QtWidgets)
        wanted={'_RootFootModulePanel','_RigControllerNames','_CollapsibleRigGroup','_RigModulesPanel','_IKModulePanel','_IKFKModulePanel','_IKLengthPanel'}
        defs=[n for n in self.tree.body if isinstance(n,ast.ClassDef) and n.name in wanted]
        exec(compile(ast.Module(body=defs,type_ignores=[]),'<Root Foot Qt>','exec'),self.ns)
        self.owner=QtWidgets.QWidget();self.owner.status=QtWidgets.QLabel();self.owner._error=mock.Mock();self.owner._refresh=mock.Mock()
        self.panels=[]
    def tearDown(self):
        for p in self.panels:p.close();p.deleteLater()
        self.owner.close();self.owner.deleteLater();self.app.processEvents()
    def panel(self,kind):
        p=self.ns['_RootFootModulePanel'](self.owner,kind);self.panels.append(p);p.show();self.app.processEvents();return p
    def test_root_fields_default_names_and_build_real_backend(self):
        p=self.panel('ROOT');self.assertEqual(set(p.fields),{'root_joint','placement'})
        self.assertEqual(p.names.fields['root'].placeholderText(),'Main_ctrl')
        self.assertEqual(p.names.fields['placement'].placeholderText(),'Root_ctrl')
        p.execute(True);self.owner._error.assert_not_called();self.owner._refresh.assert_called_once()
    def test_optional_root_joint_picker_validation_and_build(self):
        p=self.panel('ROOT');joint=self.fixture.ankle
        self.fixture.cmds.selection=[joint];p.pick('root_joint')
        self.assertEqual(p.fields['root_joint'].text(),joint)
        self.assertEqual(p.settings()['root_joint'],joint)
        p.execute(False);self.owner._error.assert_not_called()
        self.assertIn('1 root joint output',self.owner.status.text())
        p.execute(True);self.owner._error.assert_not_called()
        meta=self.owner._refresh.call_args[0][0]
        self.assertEqual(self.ns['_rig_module_read'](meta)[1]['root_joint'],self.ns['_guide_ik_uuid'](joint))

    def test_root_picker_rejects_transform_and_clear_disables_attachment(self):
        p=self.panel('ROOT');joint=self.fixture.ankle
        p.fields['root_joint'].setText(joint)
        self.fixture.cmds.selection=[self.fixture.guides['toe_tip']];p.pick('root_joint')
        self.owner._error.assert_called_once();self.assertEqual(p.fields['root_joint'].text(),joint)
        p.fields['root_joint'].clear()
        self.assertIsNone(p.settings()['root_joint'])

    def test_foot_fields_get_buttons_mode_switch_and_build(self):
        p=self.panel('FOOT');f=self.fixture
        self.assertEqual(set(p.fields),{'ankle','ball','toe_tip','left_pivot','right_pivot','heel_pivot','parent_control'})
        for key,node in dict(f.guides,ankle=f.ankle,ball=f.ball).items():
            f.cmds.selection=[node];p.pick(key);self.assertEqual(p.fields[key].text(),node)
        p.execute(False);self.owner._error.assert_not_called();self.assertIn('Ready',self.owner.status.text())
        p.mode.setCurrentText('FK');self.assertTrue(all(not row[0].isEnabled() for row in p.guide_rows))
        p.execute(True);self.owner._error.assert_not_called();self.owner._refresh.assert_called_once()
    def test_get_rejects_multiple_selection_and_keeps_field(self):
        p=self.panel('FOOT');p.fields['ankle'].setText('keep');self.fixture.cmds.selection=[self.fixture.ankle,self.fixture.ball]
        p.pick('ankle');self.assertEqual(p.fields['ankle'].text(),'keep');self.owner._error.assert_called_once()
    def manager(self):
        p=self.ns['_RigModulesPanel']();self.panels.append(p);p.show();self.app.processEvents();return p
    def rig_row(self,p,module):
        identity=self.ns['_guide_ik_uuid'](module)
        # The table and combo enumerate modules in the same stable order.
        return p.modules.findData(identity)
    def action(self,p,row,text):
        return next(b for b in p.module_rows.cellWidget(row,2).findChildren(QtWidgets.QPushButton) if b.text()==text)
    def test_each_module_row_has_own_actions_and_central_root_mirror_is_disabled(self):
        rig=self.ns['build_root_module']();p=self.manager();row=self.rig_row(p,rig['module'])
        self.assertFalse(self.action(p,row,'Constraints').isEnabled())
        self.assertFalse(self.action(p,row,'Mirror').isEnabled())
        self.assertTrue(self.action(p,row,'Delete Rig').isEnabled())
    def test_row_delete_targets_its_module_even_when_another_is_selected(self):
        a=self.ns['build_root_module'](name='RootA',controller_names={'root':'MainA','placement':'RootA'})
        b=self.ns['build_root_module'](name='RootB',controller_names={'root':'MainB','placement':'RootB'})
        p=self.manager();p.modules.setCurrentIndex(self.rig_row(p,b['module']))
        self.action(p,self.rig_row(p,a['module']),'Delete Rig').click()
        self.app.processEvents();self.app.processEvents()
        self.assertFalse(self.fixture.cmds.objExists(a['module']));self.assertTrue(self.fixture.cmds.objExists(b['module']))
        self.assertEqual(p.module_rows.rowCount(),1)
    def test_row_mirror_uses_its_uuid_and_shared_search_replace_fields(self):
        a=self.ns['build_root_module'](name='RootA',root_joint=self.fixture.ankle,controller_names={'root':'MainA','placement':'RootA'})
        b=self.ns['build_root_module'](name='RootB',controller_names={'root':'MainB','placement':'RootB'})
        called=mock.Mock(return_value={'module':b['module'],'joint_count':0});self.ns['mirror_rig_module']=called
        p=self.manager();p.modules.setCurrentIndex(self.rig_row(p,b['module']))
        p.mirror_search.setText('_left');p.mirror_replace.setText('_right')
        self.action(p,self.rig_row(p,a['module']),'Mirror').click();self.app.processEvents()
        called.assert_called_once_with(a['module'],'_left','_right')
    def test_row_constraint_action_runs_real_organize_backend(self):
        import test_regressions as legacy
        commands=legacy.ModularRigCommands();self.ns['cmds']=commands
        rig=self.ns['build_fk_module']([commands.joints[0]])
        p=self.manager();button=self.action(p,self.rig_row(p,rig['module']),'Constraints')
        self.assertTrue(button.isEnabled());button.click();self.app.processEvents()
        self.assertIn('Organized 2',p.status.text())

    def test_queued_row_action_is_ignored_if_window_is_deleted(self):
        rig=self.ns['build_root_module']();p=self.manager()
        self.action(p,self.rig_row(p,rig['module']),'Delete Rig').click()
        self.panels.remove(p);p.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        self.app.processEvents()
        self.assertTrue(self.fixture.cmds.objExists(rig['module']))
    def test_root_and_foot_are_collapsible_in_complete_manager(self):
        # Build the complete real panel. The existing length panel class is
        # defined separately and is not needed by its constructor here.
        p=self.ns['_RigModulesPanel']();self.panels.append(p);p.show();self.app.processEvents()
        self.assertIsInstance(p.root_panel,self.ns['_RootFootModulePanel']);self.assertIsInstance(p.foot_panel,self.ns['_RootFootModulePanel'])
        self.assertFalse(p.root_group.body.isVisible());self.assertFalse(p.foot_group.body.isVisible())
        self.assertIn('Foot',p.status.text())

if __name__=='__main__':unittest.main()
