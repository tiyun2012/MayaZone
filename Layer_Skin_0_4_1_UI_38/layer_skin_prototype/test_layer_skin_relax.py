"""Sparse one-ring relax invariants; no Maya runtime emulation."""
import copy
import math
import types
import unittest
import layer_skin_core as core
import layer_skin_relax as relax


def layer_state(rows,ids=None,coverage=None):
    ids=ids or [str(i) for i in range(len(rows[0]))]
    state=core.create(([1.]+[0.]*(len(ids)-1))*len(rows),len(rows),ids,'topology')
    state=core.edit(state,'add',dict(name='Relax'))
    identity=state['layers'][0]['id']
    samples={str(v):dict(weights=row,coverage=coverage[v] if coverage else 1.) for v,row in enumerate(rows)}
    state=core.edit(state,'assign',dict(layer=identity,joints=ids,generated=samples,scope=list(range(len(rows)))))
    return state,identity


def amounts(state,layer,v):
    row=next(row for row in state['layers'] if row['id']==layer)
    sample=row['samples'].get(str(v)) or row['generated'].get(str(v))
    return [value*sample['coverage'] for value in sample['weights']]


class RelaxTests(unittest.TestCase):
    def apply(self,state,layer,graph,scope=None,**kwargs):
        result,changed=relax.relax_samples(state,layer,graph,list(graph) if scope is None else scope,**kwargs)
        core.validate(result);return result,changed
    def test_selected_vertex_uses_fixed_outside_neighbors_across_iterations(self):
        state,layer=layer_state([[1.,0.],[0.,1.],[0.,1.]])
        graph={0:[1],1:[0,2],2:[1]};before=copy.deepcopy(state)
        result,changed=self.apply(state,layer,graph,[0],iterations=2,strength=.5)
        self.assertEqual(changed,[0]);self.assertEqual(amounts(result,layer,0),[.25,.75])
        self.assertEqual(amounts(result,layer,1),[0.,1.]);self.assertEqual(state,before)
    def test_jacobi_strength_settles_two_vertices_instead_of_swapping(self):
        state,layer=layer_state([[1.,0.],[0.,1.]])
        result,_=self.apply(state,layer,{0:[1],1:[0]},iterations=5,strength=.5)
        self.assertEqual(amounts(result,layer,0),[.5,.5]);self.assertEqual(amounts(result,layer,1),[.5,.5])
    def test_one_selected_joint_does_not_restrict_neighbor_influences(self):
        state,layer=layer_state([[1.,0.],[0.,1.]])
        result,_=self.apply(state,layer,{0:[1],1:[0]},[0],iterations=1,joints=['0'])
        self.assertEqual(amounts(result,layer,0),[.5,.5])
        other,_=self.apply(state,layer,{0:[1],1:[0]},[0],iterations=1,joints=['unbound-view-joint'])
        self.assertEqual(amounts(other,layer,0),[.5,.5])
    def test_two_selected_joints_keep_combined_weight_and_unselected_values(self):
        state,layer=layer_state([[.2,.3,.5],[.6,.1,.3]],['a','b','c'])
        result,_=self.apply(state,layer,{0:[1],1:[0]},[0],iterations=4,strength=.5,joints=['a','b'])
        values=amounts(result,layer,0)
        self.assertAlmostEqual(sum(values[:2]),.5);self.assertEqual(values[2],.5)
        self.assertGreater(values[0],.2);self.assertLess(values[1],.3)
    def test_three_selected_joints_only_transfer_the_existing_group_budget(self):
        state,layer=layer_state([[.1,.2,.3,.4],[.3,.1,.1,.5]],['a','b','c','d'])
        result,_=self.apply(state,layer,{0:[1],1:[0]},[0],iterations=1,strength=1.,joints=['a','b','c'])
        values=amounts(result,layer,0)
        for actual,expected in zip(values,[.36,.12,.12,.4]):self.assertAlmostEqual(actual,expected)
    def test_zero_subset_budget_does_not_import_group_weight(self):
        state,layer=layer_state([[0.,0.,1.],[.5,.5,0.]],['a','b','c'])
        result,changed=self.apply(state,layer,{0:[1],1:[0]},[0],joints=['a','b'])
        self.assertIs(result,state);self.assertEqual(changed,[])
    def test_max_new_limits_additions_without_pruning_existing_influences(self):
        state,layer=layer_state([[1.,0.,0.,0.],[0.,.2,.3,.5]])
        result,_=self.apply(state,layer,{0:[1],1:[0]},[0],iterations=1,max_new=1)
        values=amounts(result,layer,0)
        self.assertAlmostEqual(values[0],2/3);self.assertAlmostEqual(values[3],1/3);self.assertEqual(values[1:3],[0.,0.])
        state,layer=layer_state([[.3,.3,.4,0.],[0.,0.,0.,1.]])
        result,_=self.apply(state,layer,{0:[1],1:[0]},[0],iterations=1,max_new=1)
        self.assertTrue(all(value>0. for value in amounts(result,layer,0)))
    def test_max_new_applies_relative_to_start_for_the_entire_action(self):
        state,layer=layer_state([[1.,0.,0.,0.],[0.,.2,.3,.5],[0.,1.,0.,0.]])
        result,_=self.apply(state,layer,{0:[1],1:[0,2],2:[1]},iterations=10,max_new=1)
        for v in range(3):
            original=amounts(state,layer,v);values=amounts(result,layer,v)
            self.assertLessEqual(sum(a<=relax.EPS and b>relax.EPS for a,b in zip(original,values)),1)
            self.assertAlmostEqual(sum(values),1.)
    def test_limit_ties_use_identity_instead_of_influence_column(self):
        state,layer=layer_state([[1.,0.,0.],[0.,.5,.5]],['root','z','a'])
        result,_=self.apply(state,layer,{0:[1],1:[0]},[0],iterations=1,max_new=1)
        self.assertEqual(amounts(result,layer,0)[1],0.);self.assertGreater(amounts(result,layer,0)[2],0.)
    def test_partial_layer_coverage_is_smoothed_without_changing_masks_or_generated_rows(self):
        state,layer=layer_state([[1.,0.],[0.,1.]],coverage=[.2,.8])
        state=core.edit(state,'paint',dict(layer=layer,mode='mask',values={'0':.3}))
        result,_=self.apply(state,layer,{0:[1],1:[0]},[0],iterations=1)
        self.assertEqual(amounts(result,layer,0),[.1,.4])
        self.assertIs(result['layers'][0]['mask'],state['layers'][0]['mask'])
        self.assertIs(result['layers'][0]['generated'],state['layers'][0]['generated'])
        self.assertAlmostEqual(core.composite(result)[1],.12)
    def test_isolated_vertices_and_zero_strength_create_no_edit(self):
        state,layer=layer_state([[1.,0.],[0.,1.]])
        result,changed=self.apply(state,layer,{0:[],1:[]})
        self.assertIs(result,state);self.assertEqual(changed,[])
        result,_=self.apply(state,layer,{0:[1],1:[0]},strength=0.)
        self.assertIs(result,state)
    def test_constant_field_converges_without_running_all_requested_iterations(self):
        state,layer=layer_state([[.5,.5],[.5,.5]]);checks=[]
        result,changed=self.apply(state,layer,{0:[1],1:[0]},iterations=100,check=lambda:checks.append(1))
        self.assertIs(result,state);self.assertEqual(changed,[]);self.assertLess(len(checks),5)
    def test_invalid_options_and_graph_are_rejected(self):
        state,layer=layer_state([[1.,0.],[0.,1.]])
        for options in [dict(iterations=0),dict(iterations=True),dict(strength=math.nan),dict(max_new=-1),dict(max_new=1.5)]:
            with self.subTest(options=options),self.assertRaises(ValueError):self.apply(state,layer,{0:[1],1:[0]},**options)
        with self.assertRaises(ValueError):self.apply(state,layer,{0:[0],1:[0]})
    def test_cancel_keeps_input_unchanged(self):
        state,layer=layer_state([[1.,0.],[0.,1.]]);before=copy.deepcopy(state);calls=[]
        def cancel():
            calls.append(1)
            if len(calls)==2:raise RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError,'cancelled'):self.apply(state,layer,{0:[1],1:[0]},check=cancel)
        self.assertEqual(state,before)


class AdjacencyTests(unittest.TestCase):
    def setUp(self):
        self.reads=[];reads=self.reads
        class Iterator:
            def __init__(self,dag):pass
            def setIndex(self,v):self.v=v
            def getConnectedVertices(self):reads.append(self.v);return {0:[1],1:[0,2],2:[1]}[self.v]
        self.om=types.SimpleNamespace(MItMeshVertex=Iterator)
        self.ctx=dict(uuid='mesh-id',shape='mesh',dag='dag',topology='hash1',count=3)
    def test_lazy_cache_reuses_queried_vertices_and_invalidates_on_topology_change(self):
        cache=relax.AdjacencyCache()
        self.assertEqual(cache.get(self.ctx,[0],self.om),{0:(1,)})
        self.assertEqual(cache.get(self.ctx,[0,1],self.om),{0:(1,),1:(0,2)})
        self.assertEqual(self.reads,[0,1])
        self.ctx['topology']='hash2';cache.get(self.ctx,[0],self.om);self.assertEqual(self.reads,[0,1,0])
    def test_oversize_cache_is_not_retained(self):
        cache=relax.AdjacencyCache(max_bytes=1);cache.get(self.ctx,[0],self.om)
        self.assertEqual(cache.bytes,0);self.assertEqual(cache.entries,{})
    def test_growing_and_reusing_scopes_keep_exact_estimated_cost(self):
        cache=relax.AdjacencyCache()
        cache.get(self.ctx,[0],self.om);self.assertEqual(cache.bytes,140)
        cache.get(self.ctx,[0,1,1],self.om);self.assertEqual(cache.bytes,320)
        cache.get(self.ctx,[1],self.om);self.assertEqual(cache.bytes,320)
        cache.get(self.ctx,[2],self.om);self.assertEqual(cache.bytes,460)
        self.assertEqual(self.reads,[0,1,2])
    def test_cancellation_keeps_valid_neighbor_reads_without_suppressing_error(self):
        cache=relax.AdjacencyCache();cache.get(self.ctx,[0],self.om)
        def scope():
            yield 1
            raise RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError,'cancelled'):cache.get(self.ctx,scope(),self.om)
        self.assertEqual(cache.bytes,320)
        self.assertEqual(cache.get(self.ctx,[0,1],self.om),{0:(1,),1:(0,2)})
        self.assertEqual(self.reads,[0,1])
    def test_native_query_failure_keeps_previous_rows_and_allows_retry(self):
        cache=relax.AdjacencyCache();cache.get(self.ctx,[0],self.om)
        with self.assertRaises(KeyError):cache.get(self.ctx,[99],self.om)
        self.assertEqual(cache.bytes,140)
        self.assertEqual(cache.get(self.ctx,[0,1],self.om),{0:(1,),1:(0,2)})
        self.assertEqual(self.reads,[0,99,1])
    def test_cancel_callback_cannot_repopulate_explicitly_cleared_cache(self):
        cache=relax.AdjacencyCache();cache.get(self.ctx,[0],self.om)
        def cancel():
            cache.clear();raise RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError,'cancelled'):cache.get(self.ctx,[1],self.om,check=cancel)
        self.assertEqual(cache.bytes,0);self.assertEqual(cache.entries,{})
    def test_budget_and_lru_eviction_remain_bounded_across_meshes(self):
        cache=relax.AdjacencyCache(max_bytes=300,max_items=2)
        second=dict(self.ctx,uuid='second');third=dict(self.ctx,uuid='third')
        cache.get(self.ctx,[0],self.om);cache.get(second,[0],self.om)
        cache.get(self.ctx,[0],self.om);cache.get(third,[0],self.om)
        self.assertEqual(cache.bytes,280);self.assertEqual(len(cache.entries),2)
        before=len(self.reads);cache.get(self.ctx,[0],self.om)
        self.assertEqual(len(self.reads),before)
        cache.get(second,[0],self.om);self.assertEqual(len(self.reads),before+1)
        self.assertLessEqual(cache.bytes,300)
    def test_zero_item_budget_and_empty_requests_retain_no_cache(self):
        cache=relax.AdjacencyCache(max_items=0);cache.get(self.ctx,[0],self.om)
        self.assertEqual(cache.bytes,0);self.assertEqual(cache.entries,{})
        cache=relax.AdjacencyCache();self.assertEqual(cache.get(self.ctx,[],self.om),{})
        self.assertEqual(cache.entries,{})


class ScopeTests(unittest.TestCase):
    def scope(self,entries):
        shape=types.SimpleNamespace(hasFn=lambda kind:False)
        loaded=types.SimpleNamespace(node=lambda:shape)
        valid_path=types.SimpleNamespace(node=lambda:shape)
        foreign_node=types.SimpleNamespace(hasFn=lambda kind:False)
        foreign_path=types.SimpleNamespace(node=lambda:foreign_node)
        components=lambda values,kind=2:types.SimpleNamespace(isNull=lambda:False,hasFn=lambda candidate:candidate==kind,values=values)
        null=types.SimpleNamespace(isNull=lambda:True)
        choices={'vertices':(valid_path,components([0,2])),'foreign':(foreign_path,components([1])),
                 'edges':(valid_path,components([0],3)),'faces':(valid_path,components([0],4)),'object':(valid_path,null)}
        selection=types.SimpleNamespace(length=lambda:len(entries),getComponent=lambda i:choices[entries[i]])
        om=types.SimpleNamespace(MGlobal=types.SimpleNamespace(getActiveSelectionList=lambda:selection),
            MFn=types.SimpleNamespace(kTransform=1,kMeshVertComponent=2,kMeshEdgeComponent=3),
            MFnMesh=lambda path:types.SimpleNamespace(getEdgeVertices=lambda edge:(0,1)),
            MFnSingleIndexedComponent=lambda comp:types.SimpleNamespace(getElements=lambda:comp.values))
        return relax.selected_scope(dict(dag=loaded,count=3),om)
    def test_no_vertices_means_entire_mesh(self):
        self.assertEqual(self.scope([]),[0,1,2]);self.assertEqual(self.scope(['object']),[0,1,2])
    def test_selected_vertices_only(self):self.assertEqual(self.scope(['vertices','object']),[0,2])
    def test_edges_expand_to_endpoints_and_combine_with_vertex_selection(self):
        self.assertEqual(self.scope(['edges']),[0,1]);self.assertEqual(self.scope(['edges','vertices']),[0,1,2])
    def test_foreign_or_face_components_cannot_accidentally_relax_whole_mesh(self):
        for kind in ('foreign','faces'):
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.scope([kind])
