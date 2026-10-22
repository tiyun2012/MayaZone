"""Nearest joint/bone oracles, gap-free axis assignment and compact large rows."""
import copy
import math
import random
import unittest
from unittest import mock

import layer_skin_assignment as geometry
import layer_skin_assignment_scene as scene
import layer_skin_core as core


def frame(start,end=None,parent=None):
    return dict(position=list(start),end=list(start if end is None else end),
                ends=[] if end is None else [list(end)],parent=parent,
                x=[1.,0.,0.],y=[0.,1.,0.],z=[0.,0.,1.])


class NearestAssignmentTests(unittest.TestCase):
    def test_all_methods_match_brute_force_for_random_forks_and_zero_length_bones(self):
        rng=random.Random(27041);frames={}
        for i in range(65):
            start=[rng.uniform(-30.,30.) for _ in range(3)]
            end=[start[a]+rng.uniform(-8.,8.) for a in range(3)]
            record=frame(start,None if i%11==0 else end)
            if i%7==0:record['ends'].append([start[a]+rng.uniform(-10.,10.) for a in range(3)])
            angle=rng.uniform(-math.pi,math.pi)
            record.update(x=[math.cos(angle),math.sin(angle),0.],y=[-math.sin(angle),math.cos(angle),0.])
            frames['joint-'+str(i)]=record
        points=[[rng.uniform(-50.,50.) for _ in range(3)] for _ in range(300)]
        reference=dict(points=points,joints=frames);ids=list(frames)
        for method in ('point','bone','axis'):
            with self.subTest(method=method):
                result,info=geometry.AssignmentCache().generate(reference,ids,list(reversed(ids)),dict(method=method))
                self.assertEqual((info['assigned_vertices'],info['scope_vertices']),(300,300))
                for vertex,point in enumerate(points):
                    distances=[]
                    for identity,record in frames.items():
                        ends=[record['position']] if method=='point' else record['ends'] or [record['end']]
                        d=min(geometry.segment_distance(point,record['position'],end) for end in ends)
                        distances.append((d,identity))
                    expected=min(distances)[1]
                    self.assertEqual(ids[result[str(vertex)]['weights'].index(1.)],expected)
                    self.assertEqual(result[str(vertex)]['coverage'],1.)

    def test_axis_never_uses_a_remote_positive_bone_over_the_closest_negative_bone(self):
        frames={'near':frame([0,0,0],[4,0,0]),'remote':frame([-10,100,0],[-6,100,0])}
        reference=dict(points=[[-.1,.01,0],[-50.,1.,0],[0.,0.,0]],joints=frames)
        result,_=geometry.AssignmentCache().generate(reference,list(frames),list(frames),dict(method='axis'))
        self.assertEqual(set(result),{'0','1','2'})
        self.assertTrue(all(sample['weights']==[1.,0.] for sample in result.values()))

    def test_axis_resolves_equal_bones_before_depth_and_uuid_but_not_closer_bones(self):
        frames={'a':frame([0,0,0],[4,0,0]),'b':frame([0,0,0],[4,0,0],parent='a')}
        frames['b']['x']=[-1,0,0]
        reference=dict(points=[[2,1,0],[-2,1,0],[0,0,0]],joints=frames)
        ids=list(frames);cache=geometry.AssignmentCache()
        bone,_=cache.generate(reference,ids,ids,dict(method='bone'))
        axis,_=cache.generate(reference,ids,ids,dict(method='axis'))
        self.assertEqual(bone['0']['weights'],[0.,1.])
        self.assertEqual(axis['0']['weights'],[1.,0.]);self.assertEqual(axis['1']['weights'],[0.,1.])
        self.assertEqual(axis['2']['weights'],[0.,1.])

    def test_spatial_index_is_reused_across_vertex_scopes(self):
        reference=dict(points=[[.2,0,0],[3.,0,0]],joints={'a':frame([0,0,0]),'b':frame([4,0,0])})
        cache=geometry.AssignmentCache();ids=['a','b']
        first,_=cache.generate(reference,ids,ids,dict(method='point'),scope=[0])
        with mock.patch.object(geometry,'JointIndex',side_effect=AssertionError('Index rebuilt')):
            second,_=cache.generate(reference,ids,list(reversed(ids)),dict(method='point',axis='-Z'),scope=[1])
        self.assertEqual(first['0']['weights'],[1.,0.]);self.assertEqual(second['1']['weights'],[0.,1.])

    def test_parallel_branches_prune_joint_and_bone_candidate_tests(self):
        ids=['j'+str(i) for i in range(256)]
        frames={identity:frame([0.,i*20.,0.],[4.,i*20.,0.]) for i,identity in enumerate(ids)}
        reference=dict(points=[[2.,i*20.,0.] for i in range(256)],joints=frames)
        for method in ('point','bone','axis'):
            with self.subTest(method=method):
                cache=geometry.AssignmentCache();result,_=cache.generate(reference,ids,ids,dict(method=method))
                self.assertLess(cache.vertex_tests,256*256//8)
                for vertex,row in result.items():self.assertEqual(row['weights'].index(1.),int(vertex))

    def test_cancellation_during_generation_publishes_neither_index_nor_partial_rows(self):
        reference=dict(points=[[1.,0.,0.]]*3000,joints={'a':frame([0.,0.,0.],[2.,0.,0.])})
        for method in ('point','bone','axis'):
            cache=geometry.AssignmentCache();calls=[]
            def check():
                calls.append(1)
                if len(calls)==7:raise RuntimeError('cancel before writes')
            with self.subTest(method=method),self.assertRaisesRegex(RuntimeError,'cancel'):
                cache.generate(reference,['a'],['a'],dict(method=method),check=check)
            self.assertEqual(cache.entries,{});self.assertEqual(cache.builds,0)

    def test_large_assignments_keep_sparse_rows_through_edit_and_scene_roundtrip(self):
        store=geometry.storage();width=256;count=8000;ids=['j'+str(i) for i in range(width)]
        reference=dict(points=[[1.,0.,0.]]*count,joints={identity:frame([i*20.,0.,0.]) for i,identity in enumerate(ids)})
        generated,_=geometry.AssignmentCache().generate(reference,ids,[ids[-1]],dict(method='bone'))
        row=generated['0']['weights'];self.assertTrue(getattr(row,'_rtk_sparse_weights',False))
        self.assertEqual(row.entries,((width-1,1.),));self.assertIs(generated[str(count-1)]['weights'],row)
        weights=store.DenseWeights([1.]+[0.]*(width-1))*count
        state=core.edit(core.create(weights,count,ids,'topology'),'add',dict(name='Nearest'))
        layer=state['layers'][0]['id'];before=core.encode(state)
        state=core.edit(state,'assign',dict(layer=layer,joints=[ids[-1]],generated=generated,scope=list(range(count))))
        self.assertIs(state['layers'][0]['generated']['0']['weights'],row)
        result=core.decode(core.encode(state));saved=result['layers'][0]['generated']['0']['weights']
        self.assertTrue(getattr(saved,'_rtk_sparse_weights',False));self.assertEqual(saved.entries,row.entries)
        final=core.composite(result)
        for vertex in (0,count//2,count-1):self.assertEqual(list(final[vertex*width:(vertex+1)*width]),list(row))
        self.assertEqual(core.decode(before)['layers'][0]['generated'],{})

    def test_old_registered_planner_receives_no_obsolete_unit_settings_and_keeps_undo(self):
        from test_layer_skin_command import CommandTests
        case=CommandTests();case.setUp();layer=case.attach();source=case.ns['prepare_edit'];command_class=case.ns['LayerCommand']
        before=case.graph['raw'];weights=case.weights[:]
        def old_planner(ctx,meta,state,action,data):
            if action=='assign':
                float(data['settings'].get('radius',2.));float(data['settings'].get('length',5.))
            return source(ctx,meta,state,action,data)
        case.ns['prepare_edit']=old_planner;case.ns['_layer_skin_assignment_planner']=True
        case.ns.pop('_layer_skin_assignment_settings_cleaner',None)
        self.assertTrue(scene.install(case.ns));installed=case.ns['prepare_edit']
        self.assertTrue(scene.install(case.ns));self.assertIs(case.ns['prepare_edit'],installed)
        with case.assignment_environment():
            command=case.command('assign',layer=layer,joints=['b'],whole=True,
                                 settings=dict(method='bone',radius='obsolete',length=None,falloff='unused'))
        self.assertIs(case.ns['LayerCommand'],command_class);self.assertEqual(case.weights,[0.,1.]*3)
        stored=core.decode(case.graph['raw'])['layers'][0]['assignment']['settings']
        self.assertEqual(stored['rule'],'nearest_bone');self.assertNotIn('radius',stored)
        after=case.graph['raw'];command.undoIt();self.assertEqual(case.graph['raw'],before);self.assertEqual(case.weights,weights)
        command.redoIt();self.assertEqual(case.graph['raw'],after);self.assertEqual(case.weights,[0.,1.]*3)


if __name__=='__main__':unittest.main(verbosity=2)
