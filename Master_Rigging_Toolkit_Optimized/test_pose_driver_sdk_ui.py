"""Actual Qt SDK table and authoring interactions; native curve adapter recorded."""
import ast
from pathlib import Path
import types
import unittest
import test_pose_driver_sdk as cases
try:
    from PySide6 import QtCore,QtWidgets
except ImportError:
    QtWidgets=None

@unittest.skipIf(QtWidgets is None,'Qt unavailable')
class SDKUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())
    def setUp(self):
        self.cmds=cases.SDKCommands();self.left=self.cmds.add('face_L');self.right=self.cmds.add('face_R')
        self.a=self.cmds.weight('cone_L');self.b=self.cmds.weight('cone_R');self.backend=cases.load_backend(self.cmds)
        self.cmds.setAttr(self.left+'.translateX',5);self.cmds.setAttr(self.right+'.translateX',20)
        self.owner=QtWidgets.QWidget();self.errors=[];self.owner._error=lambda exc:self.errors.append(str(exc));self.owner._group=lambda:'setup_L'
        self.states={side:{'joint':'joint_'+side,'cone':'cone_'+side,'poses':[dict(id='pose_'+side,name='pose_'+side,attribute='Weight')]} for side in 'LR'}
        self.api={'_pd_read':lambda group:(group,self.states[group[-1]]),'_pd_node':lambda v:v,
                  '_pd_mirror_tokens':lambda a,b:(a,b),'_pd_mirror_name':lambda value,a,b:value.replace(a,b),
                  '_pd_mirror_object':lambda value,a,b,**kw:value.replace(a,b),'find_pose_drivers':lambda j:['setup_'+j[-1]]}
        nodes=[n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name in ('_pd_sdk_output','_pd_sdk_mirror_output')]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<SDK bridge>','exec'),self.api)
        import pose_driver_sdk_ui as ui
        self.ui=ui;self.panel=ui.SDKPanel(self.owner,self.api,self.backend);self.panel.show();self.app.processEvents()
    def tearDown(self):
        self.panel.close();self.panel.deleteLater();self.owner.close();self.owner.deleteLater();self.app.processEvents()
    def load(self):
        self.panel.refresh_poses();self.panel.use_output();self.cmds.selection=[self.left];self.panel.get_driven();return self.panel
    def authored(self):
        p=self.load();p.cells['translateX']['value'].setValue(10);p.choose_changed();p.set_key();return p
    def test_raw_and_normalize_blend_choose_existing_public_outputs(self):
        p=self.load();before=self.cmds.snap();self.assertEqual(p.weight.text(),'cone_L.WeightRaw')
        p.mode.setCurrentIndex(1);p.use_output();self.assertEqual(p.weight.text(),'cone_L.Weight');self.assertEqual(self.cmds.snap(),before)
    def test_get_samples_neutral_but_read_values_preserves_it(self):
        p=self.load();self.assertEqual(p.cells['translateX']['neutral'].value(),5)
        self.cmds.setAttr(self.left+'.translateX',9);p.read_values()
        self.assertEqual(p.cells['translateX']['value'].value(),9);self.assertEqual(p.cells['translateX']['neutral'].value(),5)
    def test_table_numeric_key_authoring_retains_desired_values_when_live_weight_is_zero(self):
        p=self.authored();self.assertEqual(p.cells['translateX']['value'].value(),10)
        self.assertEqual(self.cmds.getAttr(self.left+'.translateX'),5)
        p.key_value.setValue(.5);p.cells['translateX']['value'].setValue(7);p.set_key()
        curve=self.backend.direct_curve(self.left+'.translateX');self.assertEqual(self.cmds.nodes[curve]['keys'],[(0.,5.),(.5,7.),(1.,10.)])
    def test_find_preview_flip_and_mirror_with_separate_neutral(self):
        p=self.authored();p.find_mirror();self.assertEqual(p.mirror_weight.text(),'cone_R.WeightRaw');self.assertEqual(p.mirror_driven.text(),self.right)
        before=self.cmds.snap();p.guard(p.preview_mirror);self.assertIn('Read mirror neutral',self.errors[-1]);self.assertEqual(self.cmds.snap(),before)
        p.read_mirror_neutral();cell=p.cells['translateX'];cell['rule'].setCurrentIndex(cell['rule'].findData('flip_delta'))
        p.preview_mirror();self.assertIn('Mirror ready',p.status.text());p.mirror()
        curve=self.backend.direct_curve(self.right+'.translateX');self.assertEqual(self.cmds.nodes[curve]['keys'],[(0.,20.),(1.,15.)])
    def test_axis_mapping_invalidates_old_neutral_until_explicit_read(self):
        p=self.authored();p.find_mirror();p.read_mirror_neutral();p.cells['translateX']['mirror_channel'].setCurrentText('translateZ')
        self.assertIsNone(p.mirror_neutral_ref)
        with self.assertRaisesRegex(ValueError,'Read mirror neutral'):p.mirror_args()
        self.cmds.setAttr(self.right+'.translateZ',12);p.read_mirror_neutral();self.assertEqual(p.cells['translateX']['target_neutral'].value(),12)
    def test_saved_map_survives_new_panel_with_object_renames(self):
        p=self.authored();p.find_mirror();p.read_mirror_neutral();p.cells['translateX']['rule'].setCurrentIndex(1);p.save_map()
        self.cmds.rename(self.left,'new_L');p.refresh_saved();p.load_saved();self.assertEqual(p.driven.text(),'new_L')
        self.assertEqual(p.cells['translateX']['rule'].currentData(),'flip_delta');self.assertEqual(p.cells['translateX']['target_neutral'].value(),20)
    def test_remove_uses_selected_saved_binding_and_keeps_driven_pose(self):
        p=self.authored();self.cmds.setAttr('cone_L.WeightRaw',.4);p.remove_sdk()
        self.assertEqual(self.cmds.getAttr(self.left+'.translateX'),7);self.assertFalse(self.backend.bindings())
    def test_loading_new_driver_or_transform_clears_stale_channel_rows(self):
        p=self.load();self.assertTrue(p.cells);p.invalidate_source();self.assertFalse(p.cells);self.assertIsNone(p.meta)
    def test_bridge_matches_opposite_pose_by_setup_joint_instead_of_random_cone_name(self):
        output=self.api['_pd_sdk_mirror_output']('setup_L','pose_L','raw','_L','_R');self.assertEqual(output,'cone_R.WeightRaw')
        self.states['R']['poses'].append(dict(id='duplicate',name='pose_R',attribute='Weight'))
        with self.assertRaisesRegex(ValueError,'uniquely'):self.api['_pd_sdk_mirror_output']('setup_L','pose_L','raw','_L','_R')
    def test_full_pose_driver_has_collapsible_sdk_group(self):
        ns=dict(self.api,QtCore=QtCore,QtWidgets=QtWidgets,cmds=self.cmds,
                _polish_native_panel=lambda w:None,list_pose_drivers=lambda:[],_pd_sdk_widget=lambda owner:self.ui.SDKPanel(owner,self.api,self.backend))
        names={'_CollapsibleRigGroup','PoseDriverPoseRow','TabPoseDriver'}
        definitions=[n for n in self.tree.body if isinstance(n,ast.ClassDef) and n.name in names]
        exec(compile(ast.Module(body=definitions,type_ignores=[]),'<PoseDriver Qt>','exec'),ns)
        tab=ns['TabPoseDriver']();tab.show();self.app.processEvents()
        self.assertFalse(tab.sdk_group.body.isVisible());tab.sdk_group.set_expanded(True);self.app.processEvents()
        self.assertTrue(tab.sdk_panel.isVisible());tab.close();tab.deleteLater()

if __name__=='__main__':unittest.main()
