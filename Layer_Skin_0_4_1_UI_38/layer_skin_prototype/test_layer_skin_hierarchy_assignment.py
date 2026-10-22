"""Branch arbitration, frozen hierarchy upgrades, and buffered bone references."""
import copy
import math
import random
import types
import unittest

import layer_skin_assignment as geometry
import layer_skin_assignment_scene as scene
import layer_skin_core as core


def frame(position,parent=None,end=None):
    return dict(position=list(position),end=list(end or position),ends=[list(end)] if end else [],
                x=[1.,0.,0.],y=[0.,1.,0.],z=[0.,0.,1.],parent=parent)


def branched_reference():
    paths={'|rig|root':'root','|rig|root|L_buffer|joint':'left',
           '|rig|root|L_buffer|joint|offset|tip':'left_tip',
           '|rig|root|R_buffer|extra|extra2|joint':'right',
           '|rig|root|R_buffer|extra|extra2|joint|tip':'right_tip'}
    frames={'root':frame([-5,0,0]),'left':frame([0,10,0]),'left_tip':frame([2,10,0]),
            'right':frame([0,-10,0]),'right_tip':frame([2,-10,0])}
    reference=dict(points=[[3,10,0],[3,-10,0],[1,10,0],[1,-10,0],[-2,0,0],[-8,0,0]],joints=frames,time=1.)
    return scene.with_hierarchy(reference,paths,geometry),paths


class BranchAssignmentTests(unittest.TestCase):
    def setUp(self):self.cache=geometry.AssignmentCache();self.ref,self.paths=branched_reference();self.ids=list(self.ref['joints'])
    def assign(self,**settings):return self.cache.generate(self.ref,self.ids,list(reversed(self.ids)),dict(method='axis',**settings))
    def owners(self,samples):
        return {vertex:self.ids[row['weights'].index(1.)] for vertex,row in samples.items()}

    def test_overlapping_branches_do_not_steal_vertices_based_on_dag_depth_or_names(self):
        result,info=self.assign()
        self.assertEqual(self.owners(result),{'0':'left_tip','1':'right_tip','2':'left','3':'right','4':'root','5':'root'})
        self.assertEqual(info['settings']['rule'],'nearest_bone_axis_ties')
        self.assertEqual((info['assigned_vertices'],info['scope_vertices']),(6,6))
        self.assertTrue(all(row['coverage']==1. for row in result.values()))

    def test_selected_order_is_canonical_and_reuses_cached_branch_assignment(self):
        first,_=self.assign();count=self.cache.vertex_tests
        second,info=self.cache.generate(self.ref,self.ids,self.ids,dict(method='axis'))
        self.assertIs(first,second);self.assertTrue(info['reused']);self.assertEqual(self.cache.vertex_tests,count)

    def test_single_chain_uses_nearest_bone_instead_of_unbounded_claiming(self):
        result,info=self.cache.generate(self.ref,self.ids,['root','left','left_tip'],dict(method='axis'))
        self.assertEqual(info['settings']['rule'],'nearest_bone_axis_ties')
        self.assertEqual(self.owners(result)['1'],'root')  # Root has a bone into the closer branch.

    def test_sparse_selection_detects_branches_through_unselected_ancestors(self):
        result,info=self.cache.generate(self.ref,self.ids,['root','left_tip','right_tip'],dict(method='axis'))
        self.assertEqual(info['settings']['rule'],'nearest_bone_axis_ties')
        self.assertEqual(self.owners(result)['0'],'left_tip');self.assertEqual(self.owners(result)['1'],'right_tip')

    def test_distance_to_bone_includes_every_child_through_transform_buffers(self):
        root=self.ref['joints']['root']
        self.assertEqual({tuple(end) for end in root['ends']},{(0,10,0),(0,-10,0)})
        self.ref['points']=[[-2.5,5.,0.],[-2.5,-5.,0.]]
        result,_=self.cache.generate(self.ref,self.ids,['root'],dict(method='bone',radius=.1))
        self.assertEqual(set(result),{'0','1'})
        self.assertTrue(all(row['coverage']==1. for row in result.values()))

    def test_scope_is_preserved_and_negative_side_receives_nearest_fallback(self):
        result,info=self.cache.generate(self.ref,self.ids,self.ids,dict(method='axis'),scope=[1,5])
        self.assertEqual(self.owners(result),{'1':'right_tip','5':'root'})
        self.assertEqual((info['assigned_vertices'],info['scope_vertices']),(2,2))
        result,_=self.assign(axis='-X');self.assertEqual(set(result),{str(i) for i in range(6)})

    def test_legacy_overlap_setting_cannot_restore_holes_or_change_cache_key(self):
        auto,info=self.assign();old,legacy=self.assign(axis_overlap='child_first')
        self.assertIs(auto,old);self.assertEqual(info['key'],legacy['key'])
        self.assertEqual(legacy['settings']['rule'],'nearest_bone_axis_ties')

    def test_cycles_are_rejected_before_samples_are_cached(self):
        self.ref['joints']['root']['parent']='left_tip'
        with self.assertRaisesRegex(ValueError,'cyclic'):self.assign()
        self.assertFalse(self.cache.entries)

    def test_branch_cancel_keeps_partial_results_out_of_cache(self):
        self.ref['points']=[[3,10,0]]*4000;calls=[]
        def check():
            calls.append(1)
            if len(calls)==3:raise RuntimeError('cancel')
        with self.assertRaisesRegex(RuntimeError,'cancel'):
            self.cache.generate(self.ref,self.ids,self.ids,dict(method='axis'),check=check)
        self.assertEqual(self.cache.builds,0);self.assertFalse(self.cache.entries)

    def test_spatial_index_prunes_parallel_branches(self):
        frames={str(i):frame([0.,i*20.,0.],end=[4.,i*20.,0.]) for i in range(96)}
        reference=dict(points=[[2.,i*20.,0.] for i in range(96)],joints=frames,time=0.,hierarchy_version=1)
        ids=list(frames);result,_=self.cache.generate(reference,ids,ids,dict(method='axis'))
        self.assertEqual(len(result),96)
        self.assertLess(self.cache.vertex_tests,96*96//4)
        for vertex,row in result.items():self.assertEqual(row['weights'].index(1.),int(vertex))

    def test_bvh_matches_brute_force_nearest_bone_before_axis_preference(self):
        rng=random.Random(2481);frames={}
        for i in range(40):
            start=[rng.uniform(-20.,20.) for _ in range(3)]
            end=[start[a]+rng.uniform(-5.,5.) for a in range(3)]
            record=frame(start,end=end);angle=rng.uniform(-math.pi,math.pi)
            record.update(x=[math.cos(angle),math.sin(angle),0.],y=[-math.sin(angle),math.cos(angle),0.])
            frames[str(i)]=record
        points=[[rng.uniform(-30.,30.) for _ in range(3)] for _ in range(120)]
        ids=list(frames);reference=dict(points=points,joints=frames,time=0.,hierarchy_version=1)
        result,_=self.cache.generate(reference,ids,ids,dict(method='axis'))
        for vertex,point in enumerate(points):
            candidates=[]
            for identity,record in frames.items():
                distance=min(geometry.segment_distance(point,record['position'],end) for end in record['ends'])
                candidates.append((distance,identity))
            self.assertEqual(ids[result[str(vertex)]['weights'].index(1.)],min(candidates)[1])


class FrozenHierarchyTests(unittest.TestCase):
    def test_upgrade_keeps_frozen_geometry_axes_time_and_original_reference_immutable(self):
        reference,paths=branched_reference();legacy=copy.deepcopy(reference);legacy.pop('hierarchy_version')
        for record in legacy['joints'].values():record.pop('parent');record.update(ends=[],end=list(record['position']))
        before=copy.deepcopy(legacy)
        owner={'reference_joint_paths':lambda ctx:[types.SimpleNamespace(fullPathName=lambda path=path:path) for path in paths],
               'joint_id':lambda path:paths[path],'sibling':lambda name:geometry}
        state=dict(reference=legacy,layers=[]);upgraded=scene.ensure_reference(owner,{},state)['reference']
        self.assertEqual(legacy,before);self.assertIs(upgraded['points'],legacy['points'])
        self.assertEqual(upgraded['time'],legacy['time']);self.assertEqual(upgraded['hierarchy_version'],1)
        self.assertEqual(upgraded['joints']['left']['parent'],'root')
        self.assertEqual(upgraded['joints']['left']['ends'],[[2,10,0]])
        for identity,record in upgraded['joints'].items():
            for key in ('position','x','y','z'):self.assertEqual(record[key],legacy['joints'][identity][key])

    def test_roots_walk_through_buffers_and_do_not_confuse_duplicate_short_names(self):
        reference,paths=branched_reference();queries=[]
        def node_type(path):queries.append(path);return 'joint' if path in paths else 'transform'
        owner={'cmds':types.SimpleNamespace(nodeType=node_type)}
        influences=[types.SimpleNamespace(fullPathName=lambda path=path:path) for path in paths if path.endswith('|tip')]
        self.assertEqual(scene.joint_roots(owner,dict(influences=influences)),['|rig|root'])
        self.assertEqual(len(queries),len(set(queries)))

    def test_current_hierarchy_reference_never_queries_the_live_scene_again(self):
        reference,_=branched_reference();state=dict(reference=reference)
        self.assertIs(scene.ensure_reference({},None,state),state)

    def test_capture_rejects_a_visible_mesh_without_a_skin_input_context(self):
        with self.assertRaisesRegex(ValueError,'skin input'):
            scene.capture_reference({},dict(mesh=object()))

    def test_warm_install_keeps_command_class_and_upgrades_legacy_assignment_in_one_undo(self):
        from test_layer_skin_command import CommandTests
        case=CommandTests();case.setUp();layer=case.attach();original_class=case.ns['LayerCommand']
        reference=dict(points=[[3.,10.,0.],[3.,-10.,0.],[-1.,0.,0.]],time=1.,
                       joints={'a':frame([0,10,0],end=[2,10,0]),'b':frame([0,-10,0],end=[2,-10,0])})
        for record in reference['joints'].values():record.pop('parent')
        state=core.edit(core.decode(case.graph['raw']),'reference',dict(reference=reference))
        case.graph['raw']=core.encode(state);before=case.graph['raw'];before_weights=case.weights[:]
        paths={'|rig|left|joint':'a','|rig|right|joint':'b'}
        case.ns['reference_joint_paths']=lambda ctx:[types.SimpleNamespace(fullPathName=lambda path=path:path) for path in paths]
        case.ns['joint_id']=lambda path:paths[path]
        # A legacy planner has no hierarchy-upgrade step of its own.
        def legacy(ctx,meta,state,action,data):
            samples,info=geometry.CACHE.generate(state['reference'],case.ids,data['joints'],data['settings'])
            data.update(generated=samples,assignment=info,scope=[0,1,2])
            return core.edit(state,'assign',data),[0,1,2],info['reused']
        case.ns['prepare_edit']=legacy
        self.assertTrue(scene.install(case.ns));planner=case.ns['prepare_edit']
        self.assertTrue(scene.install(case.ns));self.assertIs(case.ns['prepare_edit'],planner)
        self.assertIs(case.ns['LayerCommand'],original_class)
        command=case.command('assign',layer=layer,joints=['b','a'],settings=dict(method='axis'),whole=True)
        self.assertEqual(case.weights,[1.,0.,0.,1.,1.,0.])
        self.assertEqual(core.decode(case.graph['raw'])['reference']['hierarchy_version'],1)
        command.undoIt();self.assertEqual(case.graph['raw'],before);self.assertEqual(case.weights,before_weights)
        command.redoIt();self.assertEqual(case.weights,[1.,0.,0.,1.,1.,0.])


try:
    from test_layer_skin_ui import ui,JointSceneAPI
except ImportError:
    ui=None


@unittest.skipIf(ui is None,'PySide is required')
class BranchAssignmentUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=ui.QtWidgets.QApplication.instance() or ui.QtWidgets.QApplication([])
    def test_buffered_duplicate_names_assign_and_report_scope_without_changing_selection(self):
        api=JointSceneAPI();paths=['|rig|root','|rig|root|leftBuffer|joint','|rig|root|rightBuffer|more|joint']
        ids=['root','left','right'];api.joint_paths=paths;api.path_ids=dict(zip(paths,ids));api.ids=ids;api.weights=[1.,0.,0.]*3
        api.state=core.edit(core.create(api.weights,3,ids,'topology'),'add',dict(name='Branches'))
        ref=dict(points=[[3.,10.,0.],[3.,-10.,0.],[-8.,0.,0.]],time=1.,joints={
            'root':frame([-5,0,0]),'left':frame([0,10,0]),'right':frame([0,-10,0])})
        api.state=core.edit(api.state,'reference',dict(reference=scene.with_hierarchy(ref,api.path_ids,geometry)))
        window=ui.LayerUI(api)
        try:
            window.target.setText('mesh');window.show();window.refresh();self.app.processEvents()
            window.method.setCurrentIndex(2);window.browser.widget.clearSelection()
            for path in paths[1:]:window.browser.items[path].setSelected(True)
            selected=api.selected[:]
            self.assertTrue(window.assign());self.assertFalse(api.warnings)
            self.assertEqual(api.weights,[0.,1.,0.,0.,0.,1.,0.,1.,0.])
            self.assertIn('3 of 3 scoped vertices assigned',window.status.text())
            self.assertEqual(api.selected,selected)
            self.assertEqual(set(window.browser.joints()),set(paths[1:]))
        finally:
            window.close();self.app.sendPostedEvents(None,ui.QtCore.QEvent.DeferredDelete)


if __name__=='__main__':unittest.main(verbosity=2)
