"""Layer lock budgets, persistence, native transactions and real Qt padlocks."""
import copy
import json
import unittest
from unittest import mock
import layer_skin_core as core
import layer_skin_influence as rules
import layer_skin_relax as relax
import layer_skin_brush as brush
import layer_skin_session as sessions
from test_layer_skin_relax import layer_state,amounts
from test_layer_skin_session import FakeAPI

try:
    from PySide6 import QtCore,QtWidgets,QtTest
except ImportError:
    try:from PySide2 import QtCore,QtWidgets,QtTest
    except ImportError:QtWidgets=None


class InfluenceMathTests(unittest.TestCase):
    def state(self,rows=None,locks=('b',),coverage=None,method='proportional'):
        state,layer=layer_state(rows or [[.2,.3,.5]],['a','b','c'],coverage)
        return core.edit(state,'influence_settings',dict(layer=layer,influence_locks=list(locks),redistribution=method)),layer
    def paint(self,state,layer,joint,value):
        return core.edit(state,'paint',dict(layer=layer,mode='weights',joint=joint,values={'0':value}))
    def test_locked_contribution_caps_another_joint_and_prevents_negative_weights(self):
        state,layer=self.state();before=copy.deepcopy(state)
        result=self.paint(state,layer,'a',1.);self.assertEqual(state,before)
        for a,b in zip(amounts(result,layer,0),[.7,.3,0.]):self.assertAlmostEqual(a,b)
        core.validate(result)
    def test_partial_coverage_preserves_locked_displayed_contribution(self):
        state,layer=self.state(coverage=[.8]);result=self.paint(state,layer,'a',1.)
        self.assertAlmostEqual(amounts(result,layer,0)[1],.24)
        self.assertAlmostEqual(amounts(result,layer,0)[0],.76)
    def test_locked_target_and_all_locked_rows_are_unchanged(self):
        state,layer=self.state();self.assertIs(self.paint(state,layer,'b',1.),state)
        state=core.edit(state,'influence_settings',dict(layer=layer,influence_locks=['a','b','c']))
        result,changed=relax.relax_samples(state,layer,{0:[]},[0],iterations=20)
        self.assertIs(result,state);self.assertEqual(changed,[])
    def test_equal_and_proportional_share_only_other_unlocked_weighted_joints(self):
        for method,expected in [('proportional',[.4,.2,.4]),('equal',[.4,.3,.3])]:
            with self.subTest(method=method):
                state,layer=self.state([[.1,.3,.6]],locks=(),method=method)
                result=self.paint(state,layer,'a',.4)
                for a,b in zip(amounts(result,layer,0),expected):self.assertAlmostEqual(a,b)
        state,layer=layer_state([[.1,.3,.2,.4,0.]],['a','b','c','d','unused'])
        state=core.edit(state,'influence_settings',dict(layer=layer,influence_locks=['b'],redistribution='equal'))
        result=self.paint(state,layer,'a',.5)
        for a,b in zip(amounts(result,layer,0),[.5,.3,.1,.1,0.]):self.assertAlmostEqual(a,b)
    def test_reducing_a_weight_retains_existing_layer_transparency_behavior(self):
        state,layer=self.state();result=self.paint(state,layer,'a',.1)
        for a,b in zip(amounts(result,layer,0),[.1,.3,.5]):self.assertAlmostEqual(a,b)
        self.assertAlmostEqual(result['layers'][0]['samples']['0']['coverage'],.9)
    def test_settings_are_layer_local_metadata_and_do_not_change_skin_or_mask(self):
        state,layer=layer_state([[.2,.3,.5]],['a','b','c']);weights=core.composite(state)
        state=core.edit(state,'add',dict(name='Other'));other=state['layers'][-1]['id']
        result=core.edit(state,'influence_settings',dict(layer=layer,influence_locks=['b'],redistribution='equal'))
        self.assertEqual(core.composite(result),weights);self.assertNotIn('influence_locks',result['layers'][-1])
        self.assertNotEqual(layer,other);self.assertEqual(state['layers'][0]['mask'],result['layers'][0]['mask'])
    def test_settings_serialize_remap_and_retain_an_unbound_joint_lock(self):
        state,layer=self.state(locks=('b','unbound'))
        restored=core.decode(core.encode(state));self.assertEqual(restored,state)
        remapped=core.remap(restored,['c','b','a','unbound'])
        self.assertEqual(remapped['layers'][0]['influence_locks'],['b','unbound'])
        self.assertEqual(rules.columns(remapped,remapped['layers'][0]),{1,3})
        self.assertEqual(core.composite(state)[1],core.composite(remapped)[1])
    def test_bad_settings_reject_without_mutating_saved_state(self):
        state,layer=self.state();before=copy.deepcopy(state)
        for data in [dict(influence_locks='b'),dict(influence_locks=['b','b']),dict(influence_locks=[None]),dict(redistribution='random')]:
            with self.subTest(data=data),self.assertRaises(ValueError):core.edit(state,'influence_settings',dict(layer=layer,**data))
        self.assertEqual(state,before)
    def test_clear_and_assignment_keep_locked_manual_and_generated_contributions(self):
        state,layer=self.state();state=self.paint(state,layer,'a',.4)
        expected=amounts(state,layer,0)[1]
        cleared=core.edit(state,'clear',dict(layer=layer,vertices=[0]))
        self.assertAlmostEqual(amounts(cleared,layer,0)[1],expected)
        assigned=core.edit(state,'assign',dict(layer=layer,joints=['a'],scope=[0],replace_manual=True,
            generated={'0':dict(weights=[1.,0.,0.],coverage=1.)}))
        self.assertAlmostEqual(amounts(assigned,layer,0)[1],expected)
        self.assertAlmostEqual(amounts(assigned,layer,0)[0],1.-expected)
        core.validate(assigned)
    def test_zero_locked_contribution_does_not_receive_assignment_or_relax_weight(self):
        state,layer=self.state([[.5,0.,.5],[0.,1.,0.]])
        result,_=relax.relax_samples(state,layer,{0:[1],1:[0]},[0],iterations=20)
        self.assertEqual(amounts(result,layer,0)[1],0.)
        result=core.edit(state,'assign',dict(layer=layer,joints=['b'],scope=[0],generated={'0':dict(weights=[0.,1.,0.],coverage=1.)}))
        self.assertEqual(amounts(result,layer,0)[1],0.)
    def test_assignment_keeps_its_generated_ratios_with_scalar_equal_mode(self):
        state,layer=layer_state([[.1,.3,.2,.4]],['a','b','c','d'])
        state=core.edit(state,'influence_settings',dict(layer=layer,influence_locks=['b'],redistribution='equal'))
        result=core.edit(state,'assign',dict(layer=layer,joints=['a','c','d'],scope=[0],
            generated={'0':dict(weights=[.2,0.,.3,.5],coverage=1.)}))
        for a,b in zip(amounts(result,layer,0),[.14,.3,.21,.35]):self.assertAlmostEqual(a,b)
    def test_relax_preserves_locks_across_iterations_groups_and_new_influence_limits(self):
        state,layer=self.state([[.2,.3,.5],[.8,.1,.1]])
        for preserve in (False,True):
            for joints in ([],['a','b'],['a','b','c']):
                result,_=relax.relax_samples(state,layer,{0:[1],1:[0]},[0,1],iterations=30,max_new=1,joints=joints,preserve_coverage=preserve)
                for v in (0,1):
                    self.assertAlmostEqual(amounts(result,layer,v)[1],amounts(state,layer,v)[1])
                    self.assertLessEqual(sum(amounts(result,layer,v)),1.+1e-12)
                core.validate(result)
    def test_shift_staging_and_commit_keep_locks_and_outside_halo(self):
        state,layer=self.state([[.2,.3,.5],[.8,.1,.1]])
        stroke=brush.RelaxStroke(state,layer,'weights',dict(iterations=10),relax)
        for _ in range(4):stroke.stamp({0:1.},lambda v:[1-v])
        result,dirty,_=relax.prepare_stroke({},state,stroke.payload(),core)
        self.assertEqual(dirty,[0]);self.assertAlmostEqual(amounts(result,layer,0)[1],.3)
        self.assertEqual(amounts(result,layer,1),amounts(state,layer,1))
    def test_forged_relax_stroke_cannot_bypass_locks(self):
        state,layer=self.state();before=copy.deepcopy(state)
        with self.assertRaisesRegex(ValueError,'locked influence'):
            relax.prepare_stroke({},state,dict(layer=layer,mode='weights',samples={'0':dict(weights=[1.,0.,0.],coverage=1.)}),core)
        self.assertEqual(state,before)
    def test_masks_remain_independent_of_influence_locks(self):
        state,layer=self.state();result=core.edit(state,'paint',dict(layer=layer,mode='mask',values={'0':.25}))
        self.assertEqual(amounts(result,layer,0),amounts(state,layer,0));self.assertEqual(result['layers'][0]['mask'],{'0':.25})
    def test_random_weight_edits_keep_every_locked_contribution_and_valid_total(self):
        import random
        rng=random.Random(18)
        for _ in range(120):
            ids=['a','b','c','d','e'];weights=core.normalized([rng.random() for _ in ids])
            state,layer=layer_state([weights],ids,coverage=[rng.random()])
            locks=[joint for joint in ids if rng.random()<.5]
            state=core.edit(state,'influence_settings',dict(layer=layer,influence_locks=locks,redistribution=rng.choice(['equal','proportional'])))
            before=amounts(state,layer,0);result=self.paint(state,layer,rng.choice(ids),rng.random());after=amounts(result,layer,0)
            for j,identity in enumerate(ids):
                if identity in locks:self.assertAlmostEqual(after[j],before[j],places=12)
            self.assertTrue(all(value>=0. for value in after));self.assertLessEqual(sum(after),1.+1e-12);core.validate(result)


class InfluenceCommandTests(unittest.TestCase):
    def setUp(self):
        from test_layer_skin_command import CommandTests
        self.fixture=CommandTests();self.fixture.setUp();self.layer=self.fixture.attach()
    def test_toggle_is_metadata_only_and_native_command_undo_redo_restores_it(self):
        c=self.fixture;before=(dict(c.graph),list(c.weights));c.log=[]
        command=c.command('influence_settings',layer=self.layer,influence_locks=['b'],redistribution='equal')
        self.assertTrue(command.isUndoable());self.assertFalse(any(isinstance(row,tuple) and row[0]=='weights' for row in c.log))
        self.assertEqual(c.weights,before[1]);saved=dict(c.graph)
        command.undoIt();self.assertEqual(c.graph,before[0]);self.assertEqual(c.weights,before[1])
        command.redoIt();self.assertEqual(c.graph,saved);self.assertEqual(c.weights,before[1])
    def test_paint_command_respects_lock_budget_and_native_undo_restores_weights_and_metadata(self):
        c=self.fixture;c.command('paint',layer=self.layer,joint='b',mode='weights',values={'0':.4})
        c.command('influence_settings',layer=self.layer,influence_locks=['b']);before=(dict(c.graph),list(c.weights))
        command=c.command('paint',layer=self.layer,joint='a',mode='weights',values={'0':1.})
        self.assertAlmostEqual(c.weights[1],.4);self.assertAlmostEqual(c.weights[0],.6)
        saved=(dict(c.graph),list(c.weights));command.undoIt();self.assertEqual((c.graph,c.weights),before)
        command.redoIt();self.assertEqual((c.graph,c.weights),saved)
    def test_failed_metadata_save_does_not_leave_a_lock_or_native_weight_change(self):
        c=self.fixture;before=(dict(c.graph),list(c.weights));c.fail_data=True
        with self.assertRaisesRegex(RuntimeError,'metadata write failed'):
            c.command('influence_settings',layer=self.layer,influence_locks=['b'])
        self.assertEqual((c.graph,c.weights),before)
    def test_earlier_native_undo_objects_survive_refreshed_core(self):
        import importlib.util
        from pathlib import Path
        c=self.fixture;old=c.command('paint',layer=self.layer,joint='b',mode='weights',values={'0':.4})
        original=c.ns['LayerCommand'];spec=importlib.util.spec_from_file_location('_locks_core_check',Path(core.__file__))
        refreshed=importlib.util.module_from_spec(spec);spec.loader.exec_module(refreshed);c.ns['core']=refreshed
        new=c.command('influence_settings',layer=self.layer,influence_locks=['b'])
        saved=(dict(c.graph),list(c.weights));new.undoIt();old.undoIt();old.redoIt();new.redoIt()
        self.assertEqual((c.graph,c.weights),saved);self.assertIs(c.ns['LayerCommand'],original)


class InfluenceSessionTests(unittest.TestCase):
    def setUp(self):
        self.api=FakeAPI();state=self.api.state;layer=self.api.layer
        state=core.edit(state,'assign',dict(layer=layer,joints=['a','b'],scope=[0,1,2],generated={str(v):dict(weights=[.7,.3],coverage=1.) for v in range(3)}))
        self.api.state=core.edit(state,'influence_settings',dict(layer=layer,influence_locks=['b']))
        self.api.weights=core.composite(self.api.state);self.session=sessions.Session(self.api)
    def tearDown(self):self.session.close()
    def test_native_array_overshoot_is_capped_saved_and_undoable_without_verification_error(self):
        self.session.start('mesh',self.api.layer,joint='a',mode='weights');before=self.api.snapshot()
        self.session.before_stroke();self.api.paint_buffer.write([1.,.7,.7]);self.session.after_stroke()
        self.assertEqual(self.session.last_stroke['status'],'unchanged');self.assertEqual(self.api.snapshot(),before)
        self.session.before_stroke();self.api.paint_buffer.write([.2,.7,.7]);self.session.after_stroke()
        self.assertTrue(self.session.last_stroke['layer_values_verified']);self.assertAlmostEqual(self.session.values[0],.2)
        self.assertAlmostEqual(rules.amounts(rules.row(self.api.state['layers'][0],'0'),2)[1],.3)
        self.api.undo();self.assertEqual(self.api.snapshot(),before)
    def test_programmatic_painting_a_locked_joint_requires_readonly_view(self):
        with self.assertRaisesRegex(ValueError,'locked'):self.session.start('mesh',self.api.layer,joint='b',mode='weights')
        self.session.start('mesh',self.api.layer,joint='b',mode='weights',readonly=True)
        self.assertEqual(self.api.context_settings['opacity'],0.);self.session.set_value(1,0,1.)
        self.assertEqual(self.api.calls,[])
    def test_unbound_locked_joint_is_not_bound_by_execute_or_assignment(self):
        self.api.state=core.edit(self.api.state,'influence_settings',dict(layer=self.api.layer,influence_locks=['new']))
        before=self.api.snapshot()
        with self.assertRaisesRegex(ValueError,'locked'):
            self.session.edit_joints('mesh',self.api.layer,['|new'],'value_operation',dict(joint='new',mode='weights',operation='replace',amount=1.,whole=True))
        with self.assertRaisesRegex(ValueError,'locked'):
            self.session.edit_joints('mesh',self.api.layer,['|new'],'assign',dict(settings=dict(method='axis'),whole=True))
        self.assertEqual(self.api.snapshot(),before)


@unittest.skipIf(QtWidgets is None,'PySide is required')
class InfluenceUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def setUp(self):
        from test_layer_skin_ui import JointSceneAPI
        import layer_skin_ui as ui
        self.ui=ui;self.api=JointSceneAPI();self.window=ui.LayerUI(self.api)
        self.window.target.setText('mesh');self.window.show();self.window.refresh();self.app.processEvents()
    def tearDown(self):self.window.close();self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
    def row(self):return next(row for row in self.api.state['layers'] if row['id']==self.window.selected_id())
    def test_click_padlock_changes_only_layer_metadata_and_retains_vertex_and_joint_selection(self):
        browser=self.window.browser;path=self.api.joint_paths[1];identity=self.api.path_ids[path]
        self.api.selected=['mesh.vtx[0]'];self.window.choose_joint(self.api.joint_paths[0])
        weights=list(self.api.weights);selected=browser.joints();item=browser.items[path]
        rect=browser.lock_rect(item);self.assertGreater(rect.width(),0)
        QtTest.QTest.mouseClick(browser.widget.viewport(),QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,rect.center())
        self.assertEqual(self.row()['influence_locks'],[identity]);self.assertEqual(self.api.weights,weights)
        self.assertEqual(browser.joints(),selected);self.assertEqual(self.api.selected,['mesh.vtx[0]'])
        self.assertEqual(len(self.api.undo_stack),1);self.assertIn(identity,browser.locked)
        self.window.history(False);self.assertNotIn(identity,browser.locked)
        self.window.history(True);self.assertIn(identity,browser.locked)
    def test_locked_joint_view_is_readonly_and_switching_to_unlocked_joint_restores_paint(self):
        path=self.api.joint_paths[1];identity=self.api.path_ids[path]
        self.window.toggle_joint_lock(path,True);self.window.choose_joint(path);self.window.paint()
        self.assertTrue(self.window.session.readonly);self.assertEqual(self.api.context_settings['opacity'],0.)
        self.window.choose_joint(self.api.joint_paths[0])
        self.assertFalse(self.window.session.readonly);self.assertEqual(self.api.context_settings['opacity'],1.)
        self.assertIn(identity,self.row()['influence_locks'])
    def test_locking_current_joint_saves_pending_stroke_before_lock_and_unlock_resumes(self):
        path=self.api.joint_paths[1];self.window.choose_joint(path);self.window.paint()
        self.window.session.before_stroke();self.api.paint_buffer.write([.6,0.,0.])
        self.assertTrue(self.window.toggle_joint_lock(path,True));self.assertTrue(self.window.session.readonly)
        self.assertEqual([action for action,data in self.api.calls],['paint','influence_settings'])
        self.assertEqual(self.window.session.values,[.6,0.,0.]);self.assertTrue(self.window.toggle_joint_lock(path,False))
        self.assertFalse(self.window.session.readonly);self.assertEqual(self.window.session.values,[.6,0.,0.])
    def test_redistribution_setting_is_undoable_persistent_and_layer_local(self):
        before=list(self.api.weights);self.window.redistribution.setCurrentIndex(1)
        self.assertEqual(self.row()['redistribution'],'equal');self.assertEqual(self.api.weights,before)
        saved=core.decode(core.encode(self.api.state));self.assertEqual(saved,self.api.state)
        self.window.history(False);self.assertEqual(self.window.redistribution.currentData(),'proportional')
        self.window.history(True);self.assertEqual(self.window.redistribution.currentData(),'equal')
    def test_base_has_no_editable_locks_or_redistribution(self):
        self.window.layers.setCurrentItem(self.window.layers.topLevelItem(self.window.layers.topLevelItemCount()-1),1)
        self.assertFalse(self.window.redistribution.isEnabled());self.assertFalse(self.window.browser.editable)
        self.assertFalse(self.window.toggle_joint_lock(self.api.joint_paths[0],True));self.assertEqual(self.api.calls,[])
    def test_failed_lock_save_keeps_old_icon_state_and_existing_data(self):
        path=self.api.joint_paths[1];before=self.api.snapshot();self.api.fail=True
        self.assertFalse(self.window.toggle_joint_lock(path,True));self.assertEqual(self.api.snapshot(),before)
        self.assertNotIn(self.api.path_ids[path],self.window.browser.locked)
    def test_warm_refresh_retains_locks_distribution_and_undo(self):
        import layer_skin_ui_refresh as refresh
        path=self.api.joint_paths[1];self.window.toggle_joint_lock(path,True);self.window.redistribution.setCurrentIndex(1)
        before=self.api.snapshot();history=list(self.api.undo_stack)
        self.window=refresh.refresh(self.window);self.app.processEvents()
        self.assertEqual(self.api.snapshot(),before);self.assertEqual(self.api.undo_stack,history)
        self.assertIn(self.api.path_ids[path],self.window.browser.locked);self.assertEqual(self.window.redistribution.currentData(),'equal')
        self.window.history(False);self.assertEqual(self.window.redistribution.currentData(),'proportional')


if __name__=='__main__':unittest.main()
