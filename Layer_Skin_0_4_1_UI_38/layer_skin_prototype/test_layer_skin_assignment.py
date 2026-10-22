"""Reference assignments, saved paint separation and UUID remapping."""
import copy
import math
import unittest
from unittest import mock
import layer_skin_core as core
import layer_skin_assignment as geometry


def reference(points):
    frame=dict(position=[0,0,0],end=[2,0,0],ends=[[2,0,0]],x=[1,0,0],y=[0,1,0],z=[0,0,1])
    value=dict(points=points,joints={'a':frame},time=0);value['key']=geometry.digest(value);return value


class AssignmentTests(unittest.TestCase):
    def setUp(self):self.cache=geometry.AssignmentCache();self.ref=reference([[1,0,0],[1,.5,0],[-1,0,0],[4,0,0]])
    def generate(self,**settings):
        return self.cache.generate(self.ref,['a','b'],['a'],dict(method='axis',**settings))
    def test_one_selected_joint_covers_both_sides_and_far_vertices(self):
        samples,_=self.generate();self.assertEqual(set(samples),{'0','1','2','3'})
        self.assertTrue(all(row==dict(weights=[1.,0.],coverage=1.) for row in samples.values()))
        self.ref['points'][1]=[1,100000,0];samples,_=self.generate()
        self.assertEqual(samples['1']['coverage'],1.)
    def test_obsolete_settings_do_not_change_assignment_or_result_cache(self):
        for method in ('point','bone','axis'):
            first,_=self.cache.generate(self.ref,['a','b'],['a'],dict(method=method))
            tests=self.cache.vertex_tests
            second,info=self.cache.generate(self.ref,['a','b'],['a'],dict(method=method,radius=math.nan,length=-1,falloff='unused',axis_overlap='child_first'))
            self.assertIs(first,second);self.assertTrue(info['reused']);self.assertEqual(self.cache.vertex_tests,tests)
            for key in ('radius','length','falloff','axis_overlap'):self.assertNotIn(key,info['settings'])
    def test_chain_uses_bone_distance_axis_boundary_and_negative_fallback(self):
        ref=reference([[-1,0,0],[1,0,0],[3,0,0],[2,0,0]])
        ref['joints']['a']['parent']=None
        ref['joints']['b']=dict(ref['joints']['a'],position=[2,0,0],end=[4,0,0],ends=[[4,0,0]],parent='a')
        samples,_=self.cache.generate(ref,['a','b'],['b','a'],dict(method='axis'))
        self.assertEqual([samples[str(i)]['weights'] for i in range(4)],[[1.,0.],[1.,0.],[0.,1.],[1.,0.]])
    def test_coincident_joints_use_stable_uuid_instead_of_pick_order(self):
        ref=reference([[1,0,0]]*100)
        ref['joints'].update({joint:dict(ref['joints']['a']) for joint in ['b','c']})
        result,_=self.cache.generate(ref,['a','b','c'],['c','b','a'],dict(method='axis'))
        self.assertEqual(len(result),100)
        self.assertTrue(all(row['weights']==[1.,0.,0.] for row in result.values()))
    def test_reciprocal_axis_preference_matches_local_sign_with_shear(self):
        ref=reference([[.5,1,0],[.5,-1,0]])
        ref['joints']['a']['y']=[1,1,0]
        ref['joints']['b']=dict(ref['joints']['a'],x=[-1,0,0])
        result,_=self.cache.generate(ref,['a','b'],['a','b'],dict(method='axis'))
        self.assertEqual(result['0']['weights'],[0.,1.]);self.assertEqual(result['1']['weights'],[1.,0.])
    def test_rotated_translated_axis_resolves_overlapping_bones(self):
        ref=reference([[500,21,30],[10,19,30],[10,20,30]])
        ref['joints']['a'].update(position=[10,20,30],x=[0,2,0],y=[-3,0,0],z=[0,0,1])
        ref['joints']['b']=dict(ref['joints']['a'],x=[0,-2,0])
        result,_=self.cache.generate(ref,['a','b'],['a','b'],dict(method='axis'))
        self.assertEqual([result[str(i)]['weights'] for i in range(3)],[[1.,0.],[0.,1.],[1.,0.]])
    def test_mirrored_scaled_axis_preference_flips_without_losing_vertices(self):
        ref=reference([[-2,0,0],[2,0,0]])
        ref['joints']['a'].update(x=[-2,0,0],y=[0,3,0],z=[0,0,.5])
        ref['joints']['b']=dict(ref['joints']['a'],x=[2,0,0])
        result,_=self.cache.generate(ref,['a','b'],['a','b'],dict(method='axis'))
        self.assertEqual([result[str(i)]['weights'] for i in range(2)],[[1.,0.],[0.,1.]])
        result,_=self.cache.generate(ref,['a','b'],['a','b'],dict(method='axis',axis='-X'))
        self.assertEqual([result[str(i)]['weights'] for i in range(2)],[[0.,1.],[1.,0.]])
    def test_singular_axis_frame_rejects_before_any_result_is_cached(self):
        ref=reference([[1,0,0]]);ref['joints']['a']['y']=[1,0,0]
        with self.assertRaisesRegex(ValueError,'singular'):self.cache.generate(ref,['a'],['a'],dict(method='axis'))
        self.assertEqual(self.cache.builds,0);self.assertEqual(self.cache.entries,{})
    def test_axis_cancellation_does_not_cache_partial_samples_or_index(self):
        ref=reference([[1,0,0]]*3000);calls=[]
        def cancel():
            calls.append(1)
            if len(calls)==5:raise RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            self.cache.generate(ref,['a'],['a'],dict(method='axis'),check=cancel)
        self.assertEqual(self.cache.builds,0);self.assertEqual(self.cache.entries,{})
    def test_negative_x_still_covers_both_sides(self):
        samples,_=self.generate(axis='-X');self.assertEqual(set(samples),{'0','1','2','3'})
    def test_y_and_z_axes(self):
        for axis,point in [('+Y',[0,1,0]),('-Y',[0,-1,0]),('+Z',[0,0,1]),('-Z',[0,0,-1])]:
            ref=reference([point]);samples,_=self.cache.generate(ref,['a'],['a'],dict(method='axis',axis=axis))
            self.assertEqual(samples['0']['weights'],[1.])
    def test_bone_distance_uses_segment_not_only_pivot(self):
        ref=reference([[5.,0,0]])
        ref['joints']['a'].update(end=[100.,0,0],ends=[[100.,0,0]])
        ref['joints']['b']=dict(ref['joints']['a'],position=[6.,1,0],end=[6.,2,0],ends=[[6.,2,0]])
        point,_=self.cache.generate(ref,['a','b'],['a','b'],dict(method='point'))
        bone,_=self.cache.generate(ref,['a','b'],['a','b'],dict(method='bone'))
        self.assertEqual(point['0']['weights'],[0.,1.]);self.assertEqual(bone['0']['weights'],[1.,0.])
    def test_equal_distance_chooses_one_stable_joint_at_full_coverage(self):
        ref=reference([[1,.5,0]]);ref['joints']['b']=copy.deepcopy(ref['joints']['a'])
        samples,_=self.cache.generate(ref,['b','a'],['a','b'],dict(method='bone'))
        self.assertEqual(samples['0']['weights'],[0.,1.]);self.assertEqual(samples['0']['coverage'],1.)
    def test_same_input_reuses_result_without_vertex_queries(self):
        self.generate();count=self.cache.vertex_tests;builds=self.cache.builds
        _,info=self.generate();self.assertTrue(info['reused']);self.assertEqual(self.cache.vertex_tests,count);self.assertEqual(self.cache.builds,builds)
    def test_changed_parameters_and_reference_key_invalidate(self):
        self.generate();self.generate(axis='-X');self.assertEqual(self.cache.builds,2)
        self.ref['points'][0]=[1,.1,0];self.generate();self.assertEqual(self.cache.builds,3)
    def test_scope_is_included_in_cache_key(self):
        result,_=self.cache.generate(self.ref,['a','b'],['a'],dict(method='axis'),[1])
        self.assertEqual(set(result),{'1'});self.assertEqual(self.cache.vertex_tests,1)
    def test_stale_stored_reference_key_cannot_reuse_old_geometry(self):
        self.ref['joints']['b']=dict(self.ref['joints']['a'],position=[10,0,0],end=[12,0,0],ends=[[12,0,0]])
        first,_=self.cache.generate(self.ref,['a','b'],['a','b'],dict(method='point'))
        self.ref['points'][0]=[11,0,0]
        second,info=self.cache.generate(self.ref,['a','b'],['a','b'],dict(method='point'))
        self.assertFalse(info['reused']);self.assertEqual(first['0']['weights'],[1.,0.]);self.assertEqual(second['0']['weights'],[0.,1.])
    def test_missing_reference_for_new_joint_has_actionable_error(self):
        with self.assertRaisesRegex(ValueError,'Capture reference'):
            self.cache.generate(self.ref,['a','b'],['b'],dict(method='bone'))
    def test_oversize_entries_are_not_retained(self):
        cache=geometry.AssignmentCache(max_bytes=1)
        cache.generate(self.ref,['a'],['a'],dict(method='bone'));self.assertEqual(cache.bytes,0)
    def test_cache_limits_and_clear(self):
        cache=geometry.AssignmentCache(max_bytes=3000,max_items=2)
        for i in range(10):
            ref=dict(self.ref,time=i);cache.generate(ref,['a'],['a'],dict(method='point'))
        self.assertLessEqual(cache.bytes,3000);self.assertLessEqual(len(cache.entries),2)
        cache.clear();self.assertEqual(cache.bytes,0)
    def test_cancellation_and_timeout_do_not_store_incomplete_result(self):
        with self.assertRaisesRegex(RuntimeError,'cancel'):
            self.cache.generate(self.ref,['a'],['a'],dict(method='bone'),check=lambda:(_ for _ in ()).throw(RuntimeError('cancel')))
        self.assertEqual(self.cache.builds,0)
        with mock.patch.object(geometry.time,'monotonic',side_effect=[0,2]):
            with self.assertRaisesRegex(RuntimeError,'time limit'):self.cache.generate(self.ref,['a'],['a'],dict(method='bone',max_seconds=1))
    def test_invalid_settings_and_scope_are_rejected(self):
        for settings in [dict(max_seconds=-1),dict(max_seconds=math.nan),dict(axis='Q'),dict(method='other')]:
            with self.subTest(settings=settings),self.assertRaises(ValueError):
                self.cache.generate(self.ref,['a'],['a'],settings)
        with self.assertRaises(ValueError):self.cache.generate(self.ref,['a'],['a'],{},[99])


class JointWeightStatusTests(unittest.TestCase):
    def setUp(self):
        self.state=core.edit(core.create([1.,0.]*2,2,['a','b'],'topology'),'add',dict(name='Status'))
        self.layer=self.state['layers'][0]['id']
        self.state=core.edit(self.state,'membership',dict(layer=self.layer,joints=['a','b']))
    def test_membership_alone_has_no_weight(self):
        self.assertEqual(core.weighted_influences(self.state,self.layer),set())
    def test_base_status_comes_from_actual_captured_rows(self):
        self.assertEqual(core.weighted_influences(self.state,'__base__'),{'a'})
    def test_generated_and_manual_nonzero_contributions_are_detected(self):
        self.state=core.edit(self.state,'assign',dict(layer=self.layer,scope=[0],generated={'0':dict(weights=[0.,1.],coverage=.5)}))
        self.assertEqual(core.weighted_influences(self.state,self.layer),{'b'})
        self.state=core.edit(self.state,'paint',dict(layer=self.layer,mode='weights',joint='a',values={'1':.3}))
        self.assertEqual(core.weighted_influences(self.state,self.layer),{'a','b'})
    def test_zero_coverage_override_hides_the_generated_weight(self):
        self.state=core.edit(self.state,'assign',dict(layer=self.layer,scope=[0],generated={'0':dict(weights=[0.,1.],coverage=1.)}))
        self.state=core.edit(self.state,'paint',dict(layer=self.layer,mode='weights',joint='b',values={'0':0.}))
        self.assertEqual(core.weighted_influences(self.state,self.layer),set())
    def test_mask_alpha_and_enable_do_not_erase_authored_weight_status(self):
        self.state=core.edit(self.state,'paint',dict(layer=self.layer,mode='weights',joint='b',values={'0':1.}))
        self.state=core.edit(self.state,'paint',dict(layer=self.layer,mode='mask',values={'0':0.}))
        self.state=core.edit(self.state,'properties',dict(layer=self.layer,opacity=0.,enabled=False))
        self.assertEqual(core.weighted_influences(self.state,self.layer),{'b'})


class AuthoringTests(unittest.TestCase):
    def setUp(self):
        self.state=core.create([1,0]*3,3,['a','b'],'mesh')
        self.state=core.edit(self.state,'add',{'name':'Arm'});self.layer=self.state['layers'][0]['id']
        self.state=core.edit(self.state,'membership',{'layer':self.layer,'joints':['b']})
    def edit(self,action,**data):
        self.state=core.edit(self.state,action,dict(layer=self.layer,**data));return self.state
    def test_rebuilding_generated_weights_preserves_paint_and_mask(self):
        self.edit('assign',generated={'0':dict(weights=[0,1],coverage=.5)},scope=[0])
        self.edit('paint',mode='weights',joint='b',values={'0':.7})
        self.edit('paint',mode='mask',joint=None,values={'0':.4})
        original=copy.deepcopy(self.state['layers'][0]['samples'])
        self.edit('assign',generated={'0':dict(weights=[0,1],coverage=.2)},scope=[0])
        self.assertEqual(self.state['layers'][0]['samples'],original)
        self.assertEqual(self.state['layers'][0]['mask'],{'0':.4})
        self.assertAlmostEqual(core.composite(self.state)[1],.28)
    def test_clear_paint_reveals_generated_sample_and_preserves_mask(self):
        self.edit('assign',generated={'0':dict(weights=[0,1],coverage=.5)},scope=[0])
        self.edit('paint',mode='weights',joint='b',values={'0':.8})
        self.edit('clear',vertices=[0]);self.assertEqual(self.state['layers'][0]['samples'],{})
        self.assertAlmostEqual(core.composite(self.state)[1],.5)
    def test_partial_assignment_preserves_other_generated_vertices(self):
        self.edit('assign',generated={'0':dict(weights=[0,1],coverage=1)},scope=[0])
        self.edit('assign',generated={'1':dict(weights=[0,1],coverage=1)},scope=[1])
        self.assertEqual(set(self.state['layers'][0]['generated']),{'0','1'})
        self.edit('assign',generated={},scope=[1]);self.assertEqual(set(self.state['layers'][0]['generated']),{'0'})
    def test_single_joint_paint_preserves_lower_layer_distribution(self):
        self.edit('membership',joints=['a','b'])
        self.edit('paint',mode='weights',joint='a',values={'0':.25})
        self.assertEqual(self.state['layers'][0]['samples']['0']['weights'],[1.,0.])
        self.assertEqual(self.state['layers'][0]['samples']['0']['coverage'],.25)
        self.assertEqual(core.composite(self.state),[1,0]*3)
    def test_multi_joint_paint_keeps_selected_value_and_normalizes_overflow(self):
        self.edit('membership',joints=['a','b'])
        self.edit('paint',mode='weights',joint='a',values={'0':.8})
        self.edit('paint',mode='weights',joint='b',values={'0':.7})
        sample=self.state['layers'][0]['samples']['0']
        self.assertEqual(sample['coverage'],1.);self.assertAlmostEqual(sample['weights'][0],.3);self.assertAlmostEqual(sample['weights'][1],.7)
    def test_erasing_generated_joint_keeps_zero_override_until_clear(self):
        self.edit('assign',generated={'0':dict(weights=[0,1],coverage=.5)},scope=[0])
        self.edit('paint',mode='weights',joint='b',values={'0':0.})
        self.assertEqual(core.composite(self.state),self.state['base'])
        self.assertEqual(self.state['layers'][0]['samples']['0']['coverage'],0.)
    def test_invalid_paint_values_are_atomic_before_automatic_membership(self):
        before=copy.deepcopy(self.state)
        with self.assertRaises(ValueError):self.edit('paint',mode='weights',joint='missing',values={'0':1})
        with self.assertRaises(ValueError):self.edit('paint',mode='weights',joint='a',values={'0':1,'1':2})
        with self.assertRaises(ValueError):self.edit('paint',mode='mask',values={'0':.2,'1':2})
        self.assertEqual(self.state,before)
    def test_paint_automatically_adds_a_bound_joint_with_its_sample(self):
        before=copy.deepcopy(self.state)
        self.edit('paint',mode='weights',joint='a',values={'0':.6})
        self.assertEqual(self.state['layers'][0]['joints'],['b','a'])
        self.assertAlmostEqual(self.state['layers'][0]['samples']['0']['coverage'],.6)
        self.assertEqual(before['layers'][0]['joints'],['b'])
    def test_empty_paint_does_not_add_membership(self):
        before=copy.deepcopy(self.state);self.edit('paint',mode='weights',joint='a',values={})
        self.assertEqual(self.state,before)
    def test_assignment_registers_selected_joints_without_erasing_existing_members(self):
        self.edit('assign',joints=['a'],generated={'0':dict(weights=[1.,0.],coverage=.5)},scope=[0])
        self.assertEqual(self.state['layers'][0]['joints'],['b','a'])
    def test_sparse_composition_matches_full(self):
        self.edit('assign',generated={'0':dict(weights=[0,1],coverage=.5)},scope=[0])
        self.edit('paint',mode='mask',values={'0':.2});full=core.composite(self.state)
        self.assertEqual(core.composite_vertices(self.state,[2,0]),full[4:6]+full[:2])
    def test_uuid_remap_extends_base_generated_and_paint(self):
        self.edit('assign',generated={'0':dict(weights=[0,1],coverage=.5)},scope=[0])
        self.edit('paint',mode='weights',joint='b',values={'1':.8})
        mapped=core.remap(self.state,['b','new','a'])
        self.assertEqual(mapped['base'][:3],[0.,0.,1.])
        self.assertEqual(mapped['layers'][0]['generated']['0']['weights'],[1.,0.,0.])
        self.assertAlmostEqual(mapped['layers'][0]['samples']['1']['weights'][0],1.)
        self.assertAlmostEqual(mapped['layers'][0]['samples']['1']['coverage'],.8)
        self.assertEqual(self.state['influences'],['a','b'])
    def test_removing_weighted_influence_fails_closed(self):
        with self.assertRaisesRegex(ValueError,'saved weights'):core.remap(self.state,['b'])
    def test_legacy_state_upgrade_preserves_output(self):
        old=copy.deepcopy(self.state);old['schema']=1
        expected=core.composite(old);upgraded=core.decode(core.encode(old))
        self.assertEqual(upgraded['schema'],2);self.assertEqual(core.composite(upgraded),expected)
    def test_edit_shares_immutable_base_and_reference(self):
        self.state['reference']=reference([[0,0,0]]*3)
        self.edit('assign',generated={'0':dict(weights=[0,1],coverage=.5)},scope=[0])
        result=core.edit(self.state,'properties',{'layer':self.layer,'opacity':.5})
        self.assertIs(result['base'],self.state['base']);self.assertIs(result['reference'],self.state['reference'])
        self.assertIs(result['layers'][0]['generated'],self.state['layers'][0]['generated'])
        self.assertIs(result['layers'][0]['samples'],self.state['layers'][0]['samples'])
        self.assertEqual(self.state['layers'][0]['opacity'],1.)


if __name__=='__main__':unittest.main(verbosity=2)
