"""Weight-editor math and orchestration tests; Maya/Qt internals are not emulated."""
import ast
from contextlib import contextmanager,nullcontext
import importlib.util
import json
import math
from pathlib import Path
import random
import sys
import types
import unittest
from unittest import mock
import skinning_core as core
import copy_skinning_core as transfer


class MathTests(unittest.TestCase):
    def assertRow(self,a,b):
        self.assertEqual(len(a),len(b))
        for x,y in zip(a,b):self.assertAlmostEqual(x,y,places=10)
    def test_set_single_preserves_other_ratios(self):self.assertRow(core.set_total([.2,.3,.5],[0],.4),[.4,.225,.375])
    def test_nudge_is_additive(self):self.assertRow(core.set_total([.2,.3,.5],[0],.1,relative=True),[.3,.2625,.4375])
    def test_multiple_selected_form_combined_total(self):self.assertRow(core.set_total([.1,.2,.7],[0,1],.6),[.2,.4,.4])
    def test_unweighted_selected_influence_receives_weight(self):self.assertRow(core.set_total([0,.3,.7],[0],.2),[.2,.24,.56])
    def test_zero_other_weights_distribute_equally(self):self.assertRow(core.set_total([1,0,0],[0],.4),[.4,.3,.3])
    def test_held_weights_remain_exact(self):self.assertRow(core.set_total([.2,.3,.5],[0],.4,locked=[1]),[.4,.3,.3])
    def test_selected_held_weight_counts_in_total(self):self.assertRow(core.set_total([.2,.3,.5],[0,1],.6,locked=[0]),[.2,.4,.4])
    def test_clamp_to_available_unlocked_budget(self):self.assertRow(core.set_total([.2,.3,.5],[0],1,locked=[1]),[.7,.3,0])
    def test_nudge_clamps_at_zero(self):self.assertRow(core.set_total([.2,.3,.5],[0],-4,relative=True),[0,.375,.625])
    def test_all_selected_held_is_explicit_error(self):
        with self.assertRaisesRegex(ValueError,'held'):core.set_total([.2,.8],[0],.4,locked=[0])
    def test_empty_selected_is_error(self):
        with self.assertRaisesRegex(ValueError,'Select'):core.set_total([.2,.8],[],.4)
    def test_all_columns_selected_cannot_drop_weight(self):
        with self.assertRaisesRegex(ValueError,'remaining weight'):core.set_total([.2,.8],[0,1],.5)
    def test_average_really_divides_by_vertex_count(self):self.assertRow(core.average([[1,0],[0,1],[0,1]]),[1/3,2/3])
    def test_average_empty_rejected(self):
        with self.assertRaises(ValueError):core.average([])
    def test_streamed_average_can_be_cancelled(self):
        def cancel():raise RuntimeError('cancelled average')
        with self.assertRaisesRegex(RuntimeError,'cancelled average'):core.average(([.25,.75] for _ in range(1000)),check=cancel)
    def test_bad_rows_rejected(self):
        for row in ([],[0,0],[.2,.2],[-.1,1.1],[float('nan'),0],[float('inf'),0]):
            with self.subTest(row=row),self.assertRaises(ValueError):core.row_values(row)
    def test_invalid_indices_and_values_rejected(self):
        for selected,value in (([-1],.2),([2],.2),([True],.2),([0],float('nan')),([0],1.2)):
            with self.subTest(selected=selected,value=value),self.assertRaises(ValueError):core.set_total([.2,.8],selected,value)
    def test_paste_fits_around_held_weights(self):self.assertRow(core.fit_locked([.2,.3,.5],[.8,.1,.1],[1]),[.7*8/9,.3,.7/9])
    def test_paste_with_no_unlocked_mass_is_error(self):
        with self.assertRaisesRegex(ValueError,'no unlocked weight'):core.fit_locked([.2,.8],[0,1],[1])
    def test_all_held_paste_is_noop(self):self.assertRow(core.fit_locked([.2,.8],[1,0],[0,1]),[.2,.8])
    def test_prune_and_renormalize(self):self.assertRow(core.prune([.001,.499,.5],.01),[0,.499/.999,.5/.999])
    def test_prune_preserves_tiny_held_weight(self):self.assertRow(core.prune([.001,.499,.5],.01,[0]),[.001,.499,.5])
    def test_prune_all_candidates_keeps_greatest(self):self.assertRow(core.prune([.2,.3,.5],1),[0,0,1])
    def test_random_set_and_nudge_preserve_locks_and_unit_sums(self):
        rng=random.Random(913)
        for _ in range(500):
            row=[rng.random() for _ in range(7)];row=[x/sum(row) for x in row]
            selected=[0,1];locked=[2,4]
            for relative in (False,True):
                result=core.set_total(row,selected,rng.random(),locked,relative)
                self.assertAlmostEqual(sum(result),1);self.assertTrue(all(0<=v<=1 for v in result))
                self.assertEqual([result[i] for i in locked],[row[i] for i in locked])
    def test_mirror_tokens_are_reciprocal_and_center_stays(self):
        records=[{'path':'|rig|arm_L'},{'path':'|rig|root'},{'path':'|rig|arm_R'}]
        self.assertEqual(core.mirror_mapping(records),[2,1,0])
    def test_mirror_custom_tokens(self):self.assertEqual(core.mirror_mapping([{'path':'left_hand'},{'path':'right_hand'}],'left_','right_'),[1,0])
    def test_untagged_duplicate_center_names_keep_identity(self):self.assertEqual(core.mirror_mapping([{'path':'|a|center'},{'path':'|b|center'}]),[0,1])
    def test_mirror_missing_partner_rejected(self):
        with self.assertRaisesRegex(ValueError,'Missing'):core.mirror_mapping([{'path':'arm_L'}])
    def test_mirror_ambiguous_partner_rejected(self):
        with self.assertRaisesRegex(ValueError,'ambiguous'):core.mirror_mapping([{'path':'a|arm_L'},{'path':'a|arm_R'},{'path':'b|arm_R'}])


def load_backend():
    maya=types.ModuleType('maya');maya.__path__=[];cmds=types.ModuleType('maya.cmds')
    api=types.ModuleType('maya.api');api.__path__=[];om=types.ModuleType('maya.api.OpenMaya')
    modules={'maya':maya,'maya.cmds':cmds,'maya.api':api,'maya.api.OpenMaya':om}
    with mock.patch.dict(sys.modules,modules):
        spec=importlib.util.spec_from_file_location('_skin_backend_tests',Path(__file__).with_name('skinning_backend.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.backend=load_backend();self.stages=[];self.checks=0;self.preflight=[];self.vertices=[0,1]
        self.ctx={'shape':'|mesh|shape','skin':'skin','uuid':'mesh-id','topology':'topo','count':3,'width':3,
                  'influences':[{'uuid':str(i),'path':'|joint'+str(i)} for i in range(3)],'weights':[.2,.3,.5,.1,.3,.6,.4,.2,.4]}
        self.backend.selected_vertices=lambda *a,**k:list(self.vertices);self.backend.held_indices=lambda ctx:{1}
        self.backend.adjacency=lambda *args:{0:[1,2],1:[0,2]}
        @contextmanager
        def planning(progress,**kwargs):
            class Monitor:
                value=0
                def stage(monitor,name,value):self.stages.append(name)
                def check(monitor):self.checks+=1
            self.stages.append('OPEN')
            try:yield Monitor()
            finally:self.stages.append('CLOSE')
        self.api=types.SimpleNamespace(context=lambda *a,**kw:self.ctx,planning=planning,core=transfer,
            same=lambda a,b,tol:len(a)==len(b) and all(abs(x-y)<=tol for x,y in zip(a,b)),
            writable=lambda *a,**kw:self.preflight.append(a))
    def plan(self,action='set',**kw):return self.backend.plan(self.api,dict(mesh='mesh',action=action,influences=['0'],value=.4,**kw))
    def test_set_plan_reads_only_and_snapshots_all_columns(self):
        result=self.plan();self.assertEqual(result['vertices'],[0,1]);self.assertEqual(result['before'],[.2,.3,.5,.1,.3,.6])
        self.assertEqual(self.ctx['weights'],[.2,.3,.5,.1,.3,.6,.4,.2,.4]);self.assertEqual(result['after'][1::3],[.3,.3])
        self.assertFalse(result['copy_dq']);self.assertEqual(len(self.preflight),1);self.assertEqual(self.stages[-1],'CLOSE')
    def test_nudge_only_changes_selected_vertex_scope(self):
        self.vertices=[1];result=self.plan('nudge');self.assertEqual(result['vertices'],[1]);self.assertAlmostEqual(result['after'][0],.5)
    def test_zero_strength_has_no_changed_snapshots(self):self.assertEqual(self.plan(strength=0)['vertices'],[])
    def test_half_strength_blends_rows(self):
        result=self.plan(strength=.5);self.assertAlmostEqual(result['after'][0],.3)
    def test_paste_maps_uuid_columns_not_source_order(self):
        clip={'influences':[{'uuid':'2','path':'|joint2','weight':.75},{'uuid':'0','path':'|joint0','weight':.25}]}
        result=self.plan('paste',clipboard=clip);self.assertAlmostEqual(result['after'][0],.175);self.assertAlmostEqual(result['after'][2],.525)
    def test_empty_clipboard_fails_cleanly(self):
        with self.assertRaisesRegex(ValueError,'Copy vertex'):self.plan('paste',clipboard=None)
        self.assertEqual(self.stages[-1],'CLOSE');self.assertFalse(self.preflight)
    def test_clipboard_missing_joint_is_not_silently_dropped(self):
        clip={'influences':[{'uuid':'missing','path':'|no_joint','weight':1}]}
        with self.assertRaisesRegex(ValueError,'Clipboard influences'):self.plan('paste',clipboard=clip)
    def test_boundary_average_uses_outside_selection_only(self):
        result=self.plan('average');self.assertAlmostEqual(result['after'][0],.35);self.assertAlmostEqual(result['after'][2],.35)
    def test_boundary_without_neighbors_is_clear_error(self):
        self.backend.adjacency=lambda *args:{0:[1],1:[0]}
        with self.assertRaisesRegex(ValueError,'no outside'):self.plan('average')
    def test_smooth_samples_snapshot_not_preceding_edited_rows(self):
        result=self.plan('smooth')
        self.assertAlmostEqual(result['after'][0],.7*.25/(.25+.5))
        self.assertAlmostEqual(result['after'][3],.7*.3/(.3+.45))
    def test_prune_retains_held_column(self):
        result=self.plan('prune',threshold=.4);self.assertEqual(result['after'][0],0);self.assertEqual(result['after'][1],.3)
    def test_mesh_uuid_and_topology_are_validated(self):
        for kw in ({'mesh_uuid':'other'},{'topology':'old'}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):self.plan(**kw)
        self.assertFalse(self.preflight)
    def test_removed_and_duplicate_influence_ids_rejected(self):
        for ids in (['gone'],['0','0']):
            with self.subTest(ids=ids),self.assertRaises(ValueError):self.backend.plan(self.api,{'mesh':'mesh','action':'set','influences':ids})
    def test_preflight_error_releases_operation_and_keeps_weights(self):
        original=self.ctx['weights'][:];self.api.writable=mock.Mock(side_effect=ValueError('driven weights'))
        with self.assertRaisesRegex(ValueError,'driven weights'):self.plan()
        self.assertEqual(self.ctx['weights'],original);self.assertEqual(self.stages[-1],'CLOSE')
    def test_cancel_inside_edit_loop_closes_operation(self):
        self.backend.core.set_total=mock.Mock(side_effect=RuntimeError('cancelled'))
        with self.assertRaisesRegex(RuntimeError,'cancelled'):self.plan()
        self.assertEqual(self.stages[-1],'CLOSE');self.assertFalse(self.preflight)
    def test_mirror_reflects_position_and_swaps_influence_columns(self):
        self.ctx['influences']=[{'uuid':'0','path':'|arm_L'},{'uuid':'1','path':'|center'},{'uuid':'2','path':'|arm_R'}]
        self.ctx['weights']=[.8,0,.2,.8,0,.2,.8,0,.2];self.backend.held_indices=lambda ctx:set();self.vertices=[0]
        self.api.sample_geometry=lambda *a,**kw:([(-1,.25,0),(1,0,0),(1,1,0)],[(0,(0,1,2))])
        result=self.plan('mirror',geometry='current');self.assertAlmostEqual(result['after'][0],.2);self.assertAlmostEqual(result['after'][2],.8)
        self.assertEqual(result['vertices'],[0]);self.assertEqual(self.ctx['weights'],[.8,0,.2]*3)
    def test_mirror_leaves_source_side_and_center_untouched(self):
        self.ctx['influences']=[{'uuid':'0','path':'|arm_L'},{'uuid':'1','path':'|center'},{'uuid':'2','path':'|arm_R'}]
        self.api.sample_geometry=lambda *a,**kw:([(1,0,0),(0,1,0),(2,0,0)],[(0,(0,1,2))])
        result=self.plan('mirror');self.assertFalse(result['vertices'])
    def test_inspection_reports_true_average_and_hold_state(self):
        result=self.backend.inspect(self.api,'mesh',weighted_only=False)
        self.assertEqual(result['vertex_count'],2)
        self.assertAlmostEqual(result['rows'][0]['weight'],.15)
        self.assertTrue(result['rows'][1]['held']);self.assertFalse(result['rows'][0]['held'])
        self.assertEqual(self.stages[-1],'CLOSE')
    def test_clipboard_captures_average_without_editing_weights(self):
        before=self.ctx['weights'][:];result=self.backend.clipboard(self.api,'mesh')
        self.assertEqual(result['vertex_count'],2);self.assertAlmostEqual(result['influences'][0]['weight'],.15)
        self.assertEqual(self.ctx['weights'],before);self.assertEqual(self.stages[-1],'CLOSE')


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.backend=load_backend();self.items=[];self.node=object()
        class Node:
            def __init__(node,identity):node.identity=identity
            def hasFn(node,kind):return False
            def __eq__(node,other):return isinstance(other,Node) and node.identity==other.identity
        class Path:
            def __init__(path,identity):path.identity=identity
            def node(path):return Node(path.identity)
        class Component:
            def __init__(component,kind=None,ids=(),complete=False):component.kind=kind;component.ids=list(ids);component.isComplete=complete
            def isNull(component):return component.kind is None
            def hasFn(component,kind):return component.kind==kind
            def getElements(component):return component.ids
            def getCompleteData(component):return 5
        class Selection:
            def length(selection):return len(self.items)
            def getComponent(selection,i):return self.items[i]
        self.Path=Path;self.Component=Component
        self.backend.om=types.SimpleNamespace(MGlobal=types.SimpleNamespace(getActiveSelectionList=Selection),
            MFn=types.SimpleNamespace(kTransform='transform',kMeshVertComponent='vertex',kMeshEdgeComponent='edge',kMeshPolygonComponent='face'),MFnSingleIndexedComponent=lambda c:c)
        self.ctx={'count':5,'dag':Path('mesh')};self.api=object()
    def resolve(self,whole=False):return self.backend.selected_vertices(self.api,self.ctx,whole)
    def test_vertex_ids_are_deduplicated_and_sorted(self):
        self.items=[(self.Path('mesh'),self.Component('vertex',[3,1])),(self.Path('mesh'),self.Component('vertex',[3,4]))]
        self.assertEqual(self.resolve(),[1,3,4])
    def test_complete_component_and_mesh_selection_cover_all_vertices(self):
        for component in (self.Component('vertex',complete=True),self.Component()):
            self.items=[(self.Path('mesh'),component)];self.assertEqual(self.resolve(),list(range(5)))
    def test_no_selection_does_not_implicitly_edit_whole_mesh(self):
        with self.assertRaisesRegex(ValueError,'Select vertices'):self.resolve()
        self.assertEqual(self.resolve(True),list(range(5)))
    def test_foreign_component_selection_is_rejected(self):
        self.items=[(self.Path('other'),self.Component('vertex',[1]))]
        with self.assertRaisesRegex(ValueError,'loaded mesh only'):self.resolve()
    def test_stale_ids_rejected(self):
        self.items=[(self.Path('mesh'),self.Component('vertex',[7]))]
        with self.assertRaisesRegex(ValueError,'stale'):self.resolve()
    def test_edge_and_face_scopes_use_api_component_iterators(self):
        class Iterator:
            def __init__(iterator,path,component):iterator.values=component.ids;iterator.i=0
            def isDone(iterator):return iterator.i>=len(iterator.values)
            def next(iterator):iterator.i+=1
            def vertexId(iterator,index):return iterator.values[iterator.i][index]
            def getVertices(iterator):return iterator.values[iterator.i]
        self.backend.om.MItMeshEdge=Iterator;self.backend.om.MItMeshPolygon=Iterator
        for kind,values,expected in (('edge',[(0,1),(1,3)],[0,1,3]),('face',[(0,2,3),(1,2,4)],list(range(5)))):
            self.items=[(self.Path('mesh'),self.Component(kind,values))]
            with self.subTest(kind=kind):self.assertEqual(self.resolve(),expected)


class HoldTests(unittest.TestCase):
    def setUp(self):
        self.backend=load_backend();self.states={'|a.lockInfluenceWeights':False,'|b.lockInfluenceWeights':True};self.events=[];self.referenced=False;self.fail=False
        self.ctx={'influences':[{'uuid':'a','path':'|a'},{'uuid':'b','path':'|b'}]};self.api=types.SimpleNamespace(context=lambda *a,**kw:self.ctx)
        def undo(**kw):
            if kw.get('query'):return True
            self.events.append(kw)
        def set_attr(plug,value):
            if self.fail and plug=='|b.lockInfluenceWeights' and value is False:raise RuntimeError('attribute write failed')
            self.states[plug]=value
        self.backend.cmds=types.SimpleNamespace(objExists=lambda plug:plug in self.states,referenceQuery=lambda *a,**kw:self.referenced,
            getAttr=lambda plug,**kw:False if kw.get('lock') else self.states[plug],listConnections=lambda *a,**kw:[],undoInfo=undo,setAttr=set_attr)
    def test_explicit_toggle_uses_one_native_undo_chunk(self):
        self.backend.set_hold(self.api,'mesh',['a','b'],'toggle')
        self.assertEqual(self.states,{'|a.lockInfluenceWeights':True,'|b.lockInfluenceWeights':False})
        self.assertEqual(len(self.events),2);self.assertTrue(self.events[0]['openChunk']);self.assertTrue(self.events[1]['closeChunk'])
    def test_reference_preflight_stops_before_changes(self):
        self.referenced=True
        with self.assertRaisesRegex(ValueError,'referenced'):self.backend.set_hold(self.api,'mesh',['a'],'hold')
        self.assertFalse(self.states['|a.lockInfluenceWeights']);self.assertEqual(self.events,[])
    def test_write_failure_rolls_back_earlier_hold_changes(self):
        self.fail=True
        with self.assertRaisesRegex(RuntimeError,'attribute write failed'):self.backend.set_hold(self.api,'mesh',['a','b'],'toggle')
        self.assertEqual(self.states,{'|a.lockInfluenceWeights':False,'|b.lockInfluenceWeights':True});self.assertTrue(self.events[-1]['closeChunk'])
    def test_stale_or_empty_influence_selection_is_rejected(self):
        for ids in ([],['missing']):
            with self.subTest(ids=ids),self.assertRaisesRegex(ValueError,'valid influences'):self.backend.set_hold(self.api,'mesh',ids,'hold')
        self.assertEqual(self.events,[])


class IntegrationTests(unittest.TestCase):
    def test_command_dispatches_edits_to_snapshot_undo_command(self):
        tree=ast.parse(Path(__file__).with_name('copy_skinning_plugin.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='CopyCommand')
        cls=ast.ClassDef(name=cls.name,bases=[ast.Name(id='object',ctx=ast.Load())],keywords=[],body=cls.body,decorator_list=[])
        ast.fix_missing_locations(cls);calls=[]
        class Args:
            def flagArgumentString(self,*_):return json.dumps({'operation':'edit','action':'nudge'})
        om=types.SimpleNamespace(MArgDatabase=lambda *a:Args(),MIntArray=list)
        ns={'om':om,'cmds':types.SimpleNamespace(undoInfo=lambda **kw:True),'json':json,'components':list,
            'planning':lambda *a,**kw:nullcontext(types.SimpleNamespace(stage=lambda *a:None,begin_write=lambda:None)),
            'edit_plan':lambda data,progress,**kwargs:calls.append((data,progress)) or {'vertices':[0],'ctx':{'width':2,'original':'evaluated mesh data','weights':[1,0]},'summary':{'ok':True}},
            'plan':mock.Mock(side_effect=AssertionError('copy plan must not run'))}
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'<shared command dispatch>','exec'),ns)
        command=ns['CopyCommand']();command.syntax=lambda:None;command.redoIt=lambda:calls.append('redo');command.setResult=lambda text:calls.append(json.loads(text))
        command.doIt([]);self.assertEqual(calls[0][0]['action'],'nudge');self.assertEqual(calls[1:],[ 'redo',{'ok':True}]);self.assertTrue(command.isUndoable())
        self.assertEqual(command.result['ctx'],{'width':2})
    def test_master_navigation_embeds_the_merged_skinning_page(self):
        tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MasterRiggingUI')
        assignment=next(n for n in cls.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='WORKFLOWS' for t in n.targets))
        workflows=ast.literal_eval(assignment.value)
        self.assertEqual(next(r[1] for r in workflows if r[0]=='copy_skinning'),'Skinning Tools')
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TabCopySkinning')
        self.assertIn('SkinningToolsPanel',ast.unparse(cls));self.assertIn('skinning_ui.py',ast.unparse(cls))


class UIActionTests(unittest.TestCase):
    def setUp(self):
        from functools import wraps
        tree=ast.parse(Path(__file__).with_name('skinning_ui.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='action')
        ns={'wraps':wraps,'shiboken':types.SimpleNamespace(isValid=lambda widget:True)}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<editor UI action>','exec'),ns)
        self.decorate=ns['action'];self.messages=[]
        self.widget=types.SimpleNamespace(_busy=False,enabled=True,say=lambda *a:self.messages.append(a))
        self.widget.isEnabled=lambda:self.widget.enabled;self.widget.setEnabled=lambda value:setattr(self.widget,'enabled',value)
    def test_error_restores_panel_and_reports(self):
        @self.decorate
        def edit(widget):raise ValueError('invalid selection')
        edit(self.widget)
        self.assertFalse(self.widget._busy);self.assertTrue(self.widget.enabled)
        self.assertEqual(str(self.messages[0][0]),'invalid selection');self.assertTrue(self.messages[0][1])
    def test_reentry_is_ignored_and_action_arguments_survive(self):
        values=[]
        @self.decorate
        def edit(widget,kind,value=0):
            values.append((kind,value));self.assertFalse(widget.enabled);edit(widget,'nested')
        edit(self.widget,'nudge',value=-.05)
        self.assertEqual(values,[('nudge',-.05)]);self.assertTrue(self.widget.enabled);self.assertFalse(self.widget._busy)


if __name__=='__main__':unittest.main(verbosity=2)
