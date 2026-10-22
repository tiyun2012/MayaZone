import ast
import math
from pathlib import Path
import random
import shutil
import sys
import tempfile
import types
import unittest
import time
from contextlib import contextmanager
from unittest import mock
import copy_skinning_core as core
import copy_skinning_cache as caching
import skinning_tasks as tasks


class PluginLoaderTests(unittest.TestCase):
    """Execute the complete plug-in as Maya can: no __file__ in its namespace."""
    def setUp(self):
        self.path=Path(__file__).with_name('copy_skinning_plugin.py').resolve()
        self.source=self.path.read_text();self.registered=[]

    def execute(self,filename=None,file_global=None,load_path=None):
        maya=types.ModuleType('maya');maya.__path__=[]
        api=types.ModuleType('maya.api');api.__path__=[]
        cmds=types.ModuleType('maya.cmds');om=types.ModuleType('maya.api.OpenMaya');oma=types.ModuleType('maya.api.OpenMayaAnim')
        om.MPxCommand=object;registered=self.registered
        class Plugin:
            def __init__(self,*args):self.arguments=args
            def loadPath(self):return str(load_path or self_path)
            def registerCommand(self,*args):registered.append((self.arguments,args))
        self_path=self.path;om.MFnPlugin=Plugin
        maya.cmds=cmds;maya.api=api;api.OpenMaya=om;api.OpenMayaAnim=oma
        modules={'maya':maya,'maya.cmds':cmds,'maya.api':api,'maya.api.OpenMaya':om,'maya.api.OpenMayaAnim':oma}
        namespace={'__name__':'_maya_copy_loader_regression'}
        if file_global is not None:namespace['__file__']=str(file_global)
        with mock.patch.dict(sys.modules,modules):
            exec(compile(self.source,str(filename or self.path),'exec'),namespace)
        return namespace

    def test_complete_plugin_exec_without_file_uses_compiled_filename(self):
        namespace=self.execute()
        self.assertNotIn('__file__',namespace)
        self.assertEqual(namespace['core'].normalize([2,2]),[.5,.5])
        namespace['initializePlugin']('plugin-object')
        self.assertEqual(self.registered[0][0][2],'0.4.3')
        self.assertEqual(self.registered[0][1][0],'rtkCopySkin')

    def test_standard_module_import_with_file_still_works(self):
        namespace=self.execute(filename='<import wrapper>',file_global=self.path)
        self.assertIsNotNone(namespace['core'])

    def test_maya_load_path_fallback_when_no_usable_module_filename(self):
        namespace=self.execute(filename='<Maya loader>')
        self.assertIsNone(namespace['core'])
        namespace['initializePlugin']('plugin-object')
        self.assertIsNotNone(namespace['core']);self.assertEqual(len(self.registered),1)

    def test_directory_load_path_supported(self):
        namespace=self.execute(filename='<Maya loader>',load_path=self.path.parent)
        namespace['initializePlugin']('plugin-object')
        self.assertIsNotNone(namespace['core'])

    def test_spaces_and_unicode_in_plugin_folder(self):
        with tempfile.TemporaryDirectory(prefix='copy skin ') as temporary:
            folder=Path(temporary)/'Maya Zone_测试';folder.mkdir()
            path=folder/self.path.name;path.write_text(self.source)
            shutil.copyfile(self.path.with_name('copy_skinning_core.py'),folder/'copy_skinning_core.py')
            namespace=self.execute(filename=path,load_path=path)
            self.assertIsNotNone(namespace['core'])

    def test_missing_core_reports_actionable_error_before_registration(self):
        with tempfile.TemporaryDirectory() as temporary:
            namespace=self.execute(filename='<Maya loader>',load_path=temporary)
            with self.assertRaisesRegex(ImportError,'keep its Python files together'):
                namespace['initializePlugin']('plugin-object')
            self.assertEqual(self.registered,[])

    def test_core_loaded_once_for_repeated_initialization_lookup(self):
        namespace=self.execute();original=namespace['core']
        self.assertIs(namespace['_load_core']('/missing/path'),original)
    def test_mixed_package_versions_fail_before_registration(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'copy_skinning_plugin.py';path.write_text(self.source)
            path.with_name('copy_skinning_core.py').write_text("VERSION='0.1.1'\n")
            with self.assertRaisesRegex(ImportError,'different versions'):self.execute(filename=path,load_path=path)
            self.assertEqual(self.registered,[])


class SurfaceMathTests(unittest.TestCase):
    def assertRow(self,a,b):
        self.assertEqual(len(a),len(b))
        for x,y in zip(a,b):self.assertAlmostEqual(x,y,places=8)
    def surface(self,mask=None,threshold=.001):
        records,_=core.prepare_triangles([(0,0,0),(2,0,0),(0,2,0)],[(7,(0,1,2))],mask,threshold)
        return core.SurfaceIndex(records)
    def test_interior_interpolates_three_vertex_weights(self):
        hit=self.surface().nearest((.5,.5,3))
        self.assertRow(hit['bary'],(.5,.25,.25));self.assertRow(hit['point'],(.5,.5,0));self.assertAlmostEqual(hit['distance'],3)
        self.assertRow(core.interpolate([1,0,0,0,1,0,0,0,1],3,hit['ids'],hit['bary'],[2,0,1],4),(.25,.25,.5,0))
    def test_edge_projection(self):self.assertRow(self.surface().nearest((2,2,0))['point'],(1,1,0))
    def test_other_edge_projection(self):self.assertRow(self.surface().nearest((-1,.5,0))['point'],(0,.5,0))
    def test_vertex_region(self):self.assertRow(self.surface().nearest((-3,-1,0))['bary'],(1,0,0))
    def test_max_distance(self):self.assertIsNone(self.surface().nearest((.5,.5,2),1))
    def test_max_distance_boundary_accepted(self):self.assertIsNotNone(self.surface().nearest((.5,.5,2),2))
    def test_mask_clips_searchable_surface_not_only_hit_acceptance(self):
        hit=self.surface([1,0,0],.5).nearest((1.5,1.5,0))
        self.assertRow(hit['point'],(.5,.5,0));self.assertRow(hit['bary'],(.5,.25,.25));self.assertAlmostEqual(hit['source_alpha'],.5)
    def test_uniform_soft_source_mask_is_confidence(self):self.assertAlmostEqual(self.surface([.3,.3,.3]).nearest((.5,.5,0))['source_alpha'],.3)
    def test_empty_mask_rejected(self):
        with self.assertRaisesRegex(ValueError,'no usable triangles'):self.surface([0,0,0])
    def test_degenerate_triangles_skipped(self):
        records,skipped=core.prepare_triangles([(0,0,0),(0,0,0),(2,0,0),(0,2,0)],[(0,(0,1,2)),(1,(0,2,3))])
        self.assertEqual(skipped,1);self.assertEqual(len(records),1)
    def test_skinny_but_valid_triangle(self):
        self.assertTrue(core.triangle_valid(((0,0,0),(1,0,0),(0,.00001,0))))
    def test_face_restriction_uses_other_surface_if_nearest_face_excluded(self):
        points=[(0,0,0),(2,0,0),(0,2,0),(0,0,4),(2,0,4),(0,2,4)]
        records,_=core.prepare_triangles(points,[(9,(3,4,5))])
        hit=core.SurfaceIndex(records).nearest((.5,.5,.1));self.assertEqual(hit['face'],9);self.assertAlmostEqual(hit['distance'],3.9)
    def test_world_metric_with_stretched_triangle(self):
        records,_=core.prepare_triangles([(0,0,0),(20,0,0),(0,2,0)],[(0,(0,1,2))])
        hit=core.SurfaceIndex(records).nearest((10,2,0))
        # Projection onto x + 10*y = 20, independently calculated.
        self.assertRow(hit['point'],(10-10/101,2-100/101,0))
    def test_bvh_matches_exhaustive_triangle_queries(self):
        rng=random.Random(312);points=[];triangles=[]
        for i in range(60):
            x,y,z=(rng.uniform(-10,10) for _ in range(3));start=len(points)
            points.extend(((x,y,z),(x+1,y,z),(x,y+1,z)));triangles.append((i,(start,start+1,start+2)))
        records,_=core.prepare_triangles(points,triangles);index=core.SurfaceIndex(records)
        for _ in range(30):
            query=tuple(rng.uniform(-12,12) for _ in range(3));actual=index.nearest(query)
            expected=min(math.dist(query,core.closest_triangle(query,*r['points'])[0]) for r in records)
            self.assertAlmostEqual(actual['distance'],expected)
    def test_target_mask_blends_with_original_weights(self):self.assertRow(core.transfer_row([1,0],[0,1],.25),(.75,.25))
    def test_alpha_zero_keeps_raw_target_exactly(self):self.assertEqual(core.transfer_row([.2,.2],[0,1],0),[.2,.2])
    def test_interpolation_normalizes_each_source_sample(self):self.assertRow(core.interpolate([2,0,0,3,0,4],2,(0,1,2),(.5,.25,.25),[0,1],2),(.5,.5))
    def test_extra_target_influences_have_zero_sampled_weight(self):self.assertRow(core.interpolate([1,0,0,1,0,1],2,(0,1,2),(1,0,0),[2,0],4),(0,0,1,0))
    def test_invalid_weights_and_dimensions_rejected(self):
        for weights in ([0,0,0,0,0,0],[-1,2,0,1,0,1],[math.nan,0,0,1,0,1]):
            with self.assertRaises(ValueError):core.interpolate(weights,2,(0,1,2),(1,0,0),[0,1],2)
        with self.assertRaises(ValueError):core.transfer_row([1],[0,1],1)
    def test_uuid_mapping_before_names(self):
        self.assertEqual(core.influence_mapping([{'uuid':'x','path':'|old'}],[{'uuid':'x','path':'|renamed'}]),[0])
    def test_namespace_and_replace_mapping(self):
        source=[{'uuid':'a','path':'|old:arm_L'}];target=[{'uuid':'b','path':'|new:arm_R'}]
        self.assertEqual(core.influence_mapping(source,target,'_L','_R',True),[0])
    def test_ambiguous_mapping_rejected(self):
        source=[{'uuid':'a','path':'|old:arm'}];target=[{'uuid':'b','path':'|x:arm'},{'uuid':'c','path':'|y:arm'}]
        with self.assertRaisesRegex(ValueError,'ambiguous'):core.influence_mapping(source,target,ignore_namespace=True)
    def test_missing_mapping_rejected(self):
        with self.assertRaises(ValueError):core.influence_mapping([{'uuid':'x','path':'|a'}],[])
    def test_many_to_one_mapping_rejected(self):
        source=[{'uuid':'x','path':'|a'},{'uuid':'y','path':'|a'}];target=[{'uuid':'z','path':'|a'}]
        with self.assertRaisesRegex(ValueError,'same target'):core.influence_mapping(source,target)


class InfluenceResolverTests(unittest.TestCase):
    def record(self,identity,name,position=(0,0,0)):return {'uuid':identity,'path':'|'+name,'position':position}
    def resolve(self,source,target,**kw):return core.resolve_influences(source,target,**kw)
    def test_same_joint_set_maps_by_uuid_despite_reordered_columns(self):
        source=[self.record('a','A'),self.record('b','B')]
        report=self.resolve(source,list(reversed(source)),use_name=False,use_distance=False)
        self.assertEqual(report['mapping'],[1,0]);self.assertTrue(report['complete'])
    def test_name_only_exact_match_ignores_distance(self):
        report=self.resolve([self.record('a','old:arm_L')],[self.record('b','new:arm_L',(100,0,0))],use_distance=False)
        self.assertTrue(report['complete']);self.assertEqual(report['rows'][0]['method'],'Exact name')
    def test_distance_only_default_tolerance(self):
        report=self.resolve([self.record('a','source')],[self.record('b','target',(.009,0,0))],use_name=False)
        self.assertTrue(report['complete']);self.assertEqual(report['rows'][0]['method'],'Distance')
    def test_distance_outside_tolerance_stays_unmapped(self):
        self.assertFalse(self.resolve([self.record('a','source')],[self.record('b','target',(.011,0,0))],use_name=False)['complete'])
    def test_distance_boundary(self):
        self.assertTrue(self.resolve([self.record('a','source')],[self.record('b','target',(.01,0,0))],use_name=False)['complete'])
    def test_one_two_and_three_changed_characters(self):
        for prefix in ('X','XY','XYZ'):
            report=self.resolve([self.record('a','upper_arm_L')],[self.record('b',prefix+'upper_arm_L')],use_distance=False)
            self.assertTrue(report['complete']);self.assertEqual(report['rows'][0]['edits'],len(prefix))
    def test_edit_limit_is_adjustable(self):
        source=[self.record('a','upper_arm_L')];target=[self.record('b','XYZupper_arm_L')]
        self.assertFalse(self.resolve(source,target,max_edits=2,use_distance=False)['complete'])
        self.assertTrue(self.resolve(source,target,max_edits=3,use_distance=False)['complete'])
    def test_disabling_both_rules_keeps_only_identity_and_manual(self):
        self.assertFalse(self.resolve([self.record('a','arm_L')],[self.record('b','arm_L')],use_name=False,use_distance=False)['complete'])
    def test_nearby_similar_names_resolve_overlapping_joint_positions(self):
        source=[self.record('a','upper_arm_L'),self.record('b','lower_arm_L')]
        target=[self.record('y','Xlower_arm_L'),self.record('x','Xupper_arm_L')]
        report=self.resolve(source,target);self.assertTrue(report['complete']);self.assertEqual(report['mapping'],[1,0])
    def test_duplicate_names_are_resolved_by_positions(self):
        source=[self.record('a','arm_L',(0,0,0)),self.record('b','arm_L',(2,0,0))]
        target=[self.record('x','arm_L',(2,0,0)),self.record('y','arm_L',(0,0,0))]
        report=self.resolve(source,target);self.assertTrue(report['complete']);self.assertEqual(report['mapping'],[1,0])
    def test_equal_candidates_remain_ambiguous(self):
        report=self.resolve([self.record('a','arm_L')],[self.record('b','Xarm_L'),self.record('c','Yarm_L')])
        self.assertFalse(report['complete']);self.assertIn('Ambiguous',report['rows'][0]['method'])
    def test_distance_tie_does_not_use_array_order(self):
        source=[self.record('a','source')];targets=[self.record('b','first'),self.record('c','second')]
        for target in (targets,list(reversed(targets))):self.assertEqual(self.resolve(source,target,use_name=False)['mapping'],[None])
    def test_source_order_does_not_change_uuid_mapping(self):
        source=[self.record('a','one',(0,0,0)),self.record('b','two',(1,0,0))]
        target=[self.record('x','leftThing',(0,0,0)),self.record('y','rightThing',(1,0,0))]
        first=self.resolve(source,target,use_name=False);second=self.resolve(list(reversed(source)),list(reversed(target)),use_name=False)
        self.assertEqual({r['source_uuid']:r['target_uuid'] for r in first['rows']},{r['source_uuid']:r['target_uuid'] for r in second['rows']})
    def test_similar_left_right_names_do_not_auto_cross(self):
        self.assertFalse(self.resolve([self.record('a','arm_L')],[self.record('b','arm_R')])['complete'])
    def test_explicit_replace_can_cross_sides(self):
        self.assertTrue(self.resolve([self.record('a','arm_L')],[self.record('b','arm_R')],search='_L',replace='_R')['complete'])
    def test_manual_override_can_cross_sides(self):
        report=self.resolve([self.record('a','arm_L')],[self.record('b','arm_R')],manual={'a':'b'})
        self.assertTrue(report['complete']);self.assertEqual(report['rows'][0]['method'],'Manual')
    def test_manual_override_has_priority_over_uuid_identity(self):
        source=[self.record('a','A'),self.record('b','B')]
        report=self.resolve(source,source,manual={'a':'b','b':'a'})
        self.assertTrue(report['complete']);self.assertEqual(report['mapping'],[1,0])
    def test_single_manual_override_cannot_silently_redirect_reserved_identity(self):
        source=[self.record('a','A'),self.record('b','B')]
        report=self.resolve(source,source,manual={'a':'b'})
        self.assertFalse(report['complete']);self.assertEqual(report['mapping'],[1,None])
    def test_manual_duplicate_targets_block_copy(self):
        source=[self.record('a','A'),self.record('b','B')];target=[self.record('c','C')]
        report=self.resolve(source,target,manual={'a':'c','b':'c'})
        self.assertFalse(report['complete']);self.assertIn('Multiple manual',report['errors'][0])
    def test_explicit_unmapped_row_blocks_automatic_matching(self):
        record=self.record('a','A');report=self.resolve([record],[record],manual={'a':None})
        self.assertFalse(report['complete']);self.assertEqual(report['rows'][0]['method'],'Manually unmapped')
    def test_removed_manual_target_rejected(self):
        with self.assertRaisesRegex(ValueError,'stale'):self.resolve([self.record('a','A')],[],manual={'a':'removed'})
    def test_removed_manual_source_rejected(self):
        with self.assertRaisesRegex(ValueError,'stale'):self.resolve([self.record('a','A')],[],manual={'removed':None})
    def test_unrelated_short_names_not_fuzzy_matched(self):
        self.assertFalse(self.resolve([self.record('a','cat')],[self.record('b','dog')],use_distance=False)['complete'])
    def test_similarity_insert_delete_replace_counts(self):
        self.assertEqual(core.edit_distance('upperArm','XupperArm'),1)
        self.assertEqual(core.edit_distance('upperArm','upperAr'),1)
        self.assertEqual(core.edit_distance('upperArm','upperXrm'),1)
    def test_bounded_edit_distance_agrees_with_full_calculation(self):
        rng=random.Random(45)
        for _ in range(300):
            a=''.join(rng.choice('abcde') for _ in range(rng.randrange(1,15)))
            b=''.join(rng.choice('abcde') for _ in range(rng.randrange(1,15)))
            full=core.edit_distance(a,b);bounded=core.edit_distance(a,b,3)
            self.assertEqual(min(full,4),min(bounded,4))
    def test_invalid_tolerance_rejected(self):
        for value in (-1,math.nan,math.inf):
            with self.assertRaises(ValueError):self.resolve([],[],tolerance=value)
    def test_repeated_distance_conflict_is_not_greedily_assigned(self):
        source=[self.record('a','source1'),self.record('b','source2')];target=[self.record('x','target')]
        report=self.resolve(source,target,use_name=False);self.assertFalse(report['complete']);self.assertEqual(report['mapping'],[None,None])


class BackendMappingTests(unittest.TestCase):
    def setUp(self):
        tree=ast.parse(Path(__file__).with_name('copy_skinning_plugin.py').read_text())
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('mapping_report','validate_mapping_review','bind_target')]
        self.source={'influences':[{'uuid':'a','path':'|upper_arm','position':(0,0,0)}]}
        self.target={'influences':[{'uuid':'b','path':'|Xupper_arm','position':(.9,0,0)}],'skin':'existingSkin','weights':[.3,.7]}
        self.reads=[];self.positions=[]
        def context(name,read_weights=True,check=None):self.reads.append(read_weights);return self.source if name=='s' else self.target
        class Distance:
            def __init__(self,value,*_):self.value=value
            @staticmethod
            def uiUnit():return 'm'
            def asCentimeters(self):return self.value*100
        def positions(ctx,space):self.positions.append(space);return ctx['influences']
        cmds=types.SimpleNamespace(listHistory=lambda *_:['existingSkin'],ls=lambda *_,**kw:['existingSkin'])
        self.task_service=tasks.TaskService()
        self.ns={'task_service':lambda:self.task_service,'native_progress_info':lambda:None,'core':core,'math':math,'context':context,'influence_positions':positions,
                 'om':types.SimpleNamespace(MDistance=Distance),'cmds':cmds,
                 'mesh_path':lambda *_:types.SimpleNamespace(fullPathName=lambda:'targetMesh')}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<backend mapping>','exec'),self.ns)
    def test_point_zero_one_scene_unit_tolerance_converts_to_centimeters(self):
        result=self.ns['mapping_report']({'source':'s','target':'t','match_name':False,'joint_tolerance':.01})
        self.assertTrue(result['complete']);self.assertEqual(self.positions,['bind','bind']);self.assertEqual(self.reads,[False,False])
    def test_tighter_scene_unit_tolerance_stops_distance_match(self):
        report=self.ns['mapping_report']({'source':'s','target':'t','match_name':False,'joint_tolerance':.0001})
        self.assertFalse(report['complete'])
    def test_current_position_mode_routed_to_both_rigs(self):
        self.ns['mapping_report']({'source':'s','target':'t','joint_space':'current'})
        self.assertEqual(self.positions,['current','current'])
    def test_same_influence_ids_do_not_need_bind_matrix_queries(self):
        self.target['influences']=self.source['influences']
        self.assertTrue(self.ns['mapping_report']({'source':'s','target':'t'})['complete']);self.assertEqual(self.positions,[])
    def test_existing_skin_is_reused_without_rebinding_or_weight_writes(self):
        before=self.target['weights'][:]
        self.assertEqual(self.ns['bind_target']('s','t'),'existingSkin');self.assertEqual(self.target['weights'],before)
        self.assertEqual(self.reads,[False,False])
    def test_review_rejects_auto_pair_changes(self):
        report=self.ns['mapping_report']({'source':'s','target':'t'})
        review={'source_ids':['a'],'target_ids':['b'],'pairs':{'a':'different'}}
        with self.assertRaisesRegex(ValueError,'changed since review'):self.ns['validate_mapping_review'](report,review)
    def test_review_rejects_added_target_influence(self):
        report=self.ns['mapping_report']({'source':'s','target':'t'})
        review={'source_ids':['a'],'target_ids':['b','extra'],'pairs':{'a':'b'}}
        with self.assertRaises(ValueError):self.ns['validate_mapping_review'](report,review)
    def test_review_keeps_uuid_pairs_across_physical_order_changes(self):
        report={'source_ids':['b','a'],'target_ids':['y','x'],'rows':[{'source_uuid':'a','target_uuid':'x'},{'source_uuid':'b','target_uuid':'y'}]}
        self.ns['validate_mapping_review'](report,{'source_ids':['a','b'],'target_ids':['x','y'],'pairs':{'a':'x','b':'y'}})


class InfluencePositionTests(unittest.TestCase):
    def setUp(self):
        node=next(n for n in ast.parse(Path(__file__).with_name('copy_skinning_plugin.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='influence_positions')
        self.values=[1,0,0,0,0,1,0,0,0,0,1,0,-1,-2,-3,1];self.queries=[]
        class Matrix:
            def __init__(self,values):self.values=list(values)
            def isSingular(self):return not any(self.values)
            def inverse(self):
                result=self.values[:];result[12:15]=[-v for v in result[12:15]];return Matrix(result)
            def __iter__(self):return iter(self.values)
        self.Matrix=Matrix
        path=types.SimpleNamespace(inclusiveMatrix=lambda:Matrix([1,0,0,0,0,1,0,0,0,0,1,0,7,8,9,1]),node=lambda:'joint-object')
        self.paths=[path]
        self.fn=types.SimpleNamespace(influenceObjects=lambda:self.paths,indexForInfluenceObject=lambda path:7)
        self.ctx={'fn':self.fn,'skin':'skinA','influences':[{'uuid':'a','path':'|a'}]}
        def get(plug):self.queries.append(plug);return [tuple(self.values)]
        ns={'math':math,'om':types.SimpleNamespace(MMatrix=Matrix,MFnDependencyNode=lambda node:types.SimpleNamespace(uuid=lambda:types.SimpleNamespace(asString=lambda:'a'))),'cmds':types.SimpleNamespace(getAttr=get)}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<joint positions>','exec'),ns);self.sample=ns['influence_positions']
    def test_bind_positions_use_inverse_bind_matrix_logical_index(self):
        self.assertEqual(self.sample(self.ctx)[0]['position'],(1,2,3));self.assertEqual(self.queries,['skinA.bindPreMatrix[7]'])
    def test_current_position_reads_world_matrix(self):
        self.assertEqual(self.sample(self.ctx,'current')[0]['position'],(7,8,9));self.assertEqual(self.queries,[])
    def test_singular_bind_matrix_rejected(self):
        self.values=[0]*16
        with self.assertRaisesRegex(ValueError,'Singular bind'):self.sample(self.ctx)
    def test_changed_influence_count_rejected(self):
        self.paths=[]
        with self.assertRaisesRegex(ValueError,'Influence list changed'):self.sample(self.ctx)
    def test_index_lookup_accepts_object_fallback(self):
        def index(value):
            if value!='joint-object':raise TypeError('MObject required')
            return 12
        self.fn.indexForInfluenceObject=index
        self.sample(self.ctx);self.assertEqual(self.queries,['skinA.bindPreMatrix[12]'])
    def test_changed_influence_order_rejected(self):
        self.ctx['influences'][0]['uuid']='different'
        with self.assertRaisesRegex(ValueError,'Influence order changed'):self.sample(self.ctx)


class UIVersionTests(unittest.TestCase):
    def test_old_native_command_is_rejected_before_copy(self):
        tree=ast.parse(Path(__file__).with_name('copy_skinning_ui.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='backend')
        path=str(Path(__file__).with_name('copy_skinning_plugin.py').resolve())
        def plugin_info(*args,**kw):
            if kw.get('listPlugins'):return ['copy_skinning_plugin']
            if kw.get('path'):return path
            if kw.get('version'):return '0.1.1'
        import os
        ns={'os':os,'__file__':str(Path(__file__).with_name('copy_skinning_ui.py')),
            'cmds':types.SimpleNamespace(pluginInfo=plugin_info),'_backend':object()}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<UI version guard>','exec'),ns)
        with self.assertRaisesRegex(RuntimeError,'restart Maya'):ns['backend']()


class PlanTests(unittest.TestCase):
    assertRow=SurfaceMathTests.assertRow
    def setUp(self):
        tree=ast.parse(Path(__file__).with_name('copy_skinning_plugin.py').read_text())
        functions=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in ('PlanProgress','planning','plan','_plan','same','region','mapping_report','validate_mapping_review')]
        self.source={'weights':[1,0,0,1,0,1],'count':3,'width':2,'topology':'t','uuid':'s','dag':'s','mesh':types.SimpleNamespace(numPolygons=1)}
        self.target={'weights':[0,1,0,1,0,1],'count':3,'width':2,'topology':'t','uuid':'t','dag':'t','mesh':types.SimpleNamespace(numPolygons=1)}
        influences=[{'uuid':'a','path':'|a'},{'uuid':'b','path':'|b'}]
        self.source['influences']=influences;self.target['influences']=influences
        self.source['fn']=types.SimpleNamespace(getBlendWeights=lambda *_:[.2,.6,1])
        self.target['fn']=types.SimpleNamespace(getBlendWeights=lambda *_:[0,0,0])
        self.masks={'source':[1,1,1],'target':[1,1,1]};self.guard=[];self.samples=[]
        def sample(ctx,mode,override,check=None):
            self.samples.append((ctx['uuid'],mode,override))
            return ([(0,0,0),(2,0,0),(0,2,0)] if ctx is self.source else [(.5,.5,0),(0,0,1),(4,4,0)]),[(0,(0,1,2))]
        class Distance:
            def __init__(self,value,*_):self.value=value
            @staticmethod
            def uiUnit():return 'cm'
            def asCentimeters(self):return self.value
        self.cache=caching.CacheService()
        self.task_service=tasks.TaskService()
        self.ns={'task_service':lambda:self.task_service,'native_progress_info':lambda:None,'core':core,'math':math,'time':time,'contextmanager':contextmanager,'_active_plan':False,'cache_service':lambda:self.cache,
                 'make_interrupt_monitor':lambda:types.SimpleNamespace(beginComputation=lambda *a:None,isInterruptRequested=lambda:False,endComputation=lambda:None),
                 'context':lambda name,**kw:self.source if name=='s' else self.target,
                 'sample_geometry':sample,'mask_values':lambda ctx,role:self.masks[role],
                 'om':types.SimpleNamespace(MDistance=Distance),'components':lambda ids:list(ids),
                 'writable':lambda *args,**kw:self.guard.append(args)}
        exec(compile(ast.Module(body=functions,type_ignores=[]),'<transfer plan>','exec'),self.ns)
    def plan(self,**kw):return self.ns['plan'](dict(source='s',target='t',**kw))
    def regions(self):return {'source_region':{'uuid':'s','topology':'t','faces':[0]},'target_region':{'uuid':'t','topology':'t','vertices':[0]}}
    def test_surface_plan_interpolates_and_does_not_write(self):
        result=self.plan(method='surface',geometry='base');self.assertEqual(result['vertices'],[0,1]);self.assertRow(result['after'],[.5,.5,1,0]);self.assertEqual(self.target['weights'],[0,1,0,1,0,1]);self.assertEqual(len(self.guard),1)
    def test_current_and_base_options_routed_to_both_meshes(self):
        for mode in ('base','current'):
            self.samples=[];self.plan(method='surface',geometry=mode,source_base='baseS',target_base='baseT')
            self.assertEqual(self.samples,[('s',mode,'baseS'),('t',mode,'baseT')])
    def test_vertex_id_skips_geometry_queries(self):
        result=self.plan(method='id');self.assertEqual(self.samples,[]);self.assertEqual(result['vertices'],[0]);self.assertRow(result['after'],[1,0])
    def test_id_count_mismatch_rejected(self):
        self.target['count']=2
        with self.assertRaisesRegex(ValueError,'equal vertex'):self.plan(method='id')
    def test_id_topology_mismatch_rejected(self):
        self.target['topology']='other'
        with self.assertRaisesRegex(ValueError,'topology'):self.plan(method='id')
        self.plan(method='id',verify_topology=False)
    def test_source_and_target_soft_masks_multiply(self):
        self.masks={'source':[.5,.5,.5],'target':[.5,0,0]}
        result=self.plan(method='region',source_mask=True,target_mask=True)
        self.assertEqual(result['vertices'],[0]);self.assertRow(result['after'],[.125,.875])
    def test_face_and_vertex_regions_intersect_masks(self):
        result=self.plan(method='region',**self.regions());self.assertEqual(result['vertices'],[0]);self.assertRow(result['after'],[.5,.5])
    def test_regions_required_on_both_sides(self):
        with self.assertRaisesRegex(ValueError,'source'):self.plan(method='region')
        with self.assertRaisesRegex(ValueError,'target'):self.plan(method='region',source_mask=True)
    def test_stale_region_rejected(self):
        values=self.regions();values['source_region']['uuid']='other'
        with self.assertRaisesRegex(ValueError,'stale'):self.plan(method='region',**values)
    def test_max_distance_skips_without_overwriting(self):
        result=self.plan(method='surface',max_distance=.5);self.assertEqual(result['vertices'],[0]);self.assertEqual(result['summary']['distance_skips'],2)
    def test_dq_interpolated_with_same_barycentrics(self):
        result=self.plan(method='surface',copy_dq=True,max_distance=.5);self.assertRow(result['after_dq'],[.5]);self.assertRow(result['before_dq'],[0])
    def test_zero_opacity_does_not_change_weights(self):self.assertFalse(self.plan(method='surface',opacity=0)['vertices'])
    def test_different_joint_sets_transfer_to_name_mapped_physical_columns(self):
        self.target['influences']=[{'uuid':'targetB','path':'|b'},{'uuid':'targetA','path':'|a'}]
        result=self.plan(method='surface',match_distance=False)
        self.assertEqual(result['vertices'],[0,2]);self.assertRow(result['after'],[.5,.5,1,0])
        self.assertEqual(result['summary']['influence_mapping'],[('|a','|a'),('|b','|b')])
    def test_manual_mapping_controls_transferred_columns(self):
        result=self.plan(method='surface',manual_mapping={'a':'b','b':'a'})
        self.assertEqual(result['vertices'],[0,2]);self.assertRow(result['after'],[.5,.5,1,0])
    def test_unresolved_mapping_stops_before_geometry_and_preflight(self):
        self.target['influences']=[{'uuid':'x','path':'|x'},{'uuid':'y','path':'|y'}]
        with self.assertRaisesRegex(ValueError,'unresolved'):self.plan(method='surface',match_name=False,match_distance=False)
        self.assertEqual(self.guard,[]);self.assertEqual(self.samples,[])
    def test_reviewed_mapping_drift_stops_before_writes(self):
        review={'source_ids':['a','b'],'target_ids':['a','b'],'pairs':{'a':'b','b':'a'}}
        with self.assertRaisesRegex(ValueError,'changed since review'):self.plan(method='surface',reviewed_mapping=review)
        self.assertEqual(self.guard,[]);self.assertEqual(self.samples,[])


class ProgressTests(unittest.TestCase):
    setUp_plan=PlanTests.setUp
    def setUp(self):
        self.setUp_plan();self.events=[];self.open=False;self.cancel_at=None;self.can_open=True
        self.clock=0
        def now():self.clock+=.2;return self.clock
        def window(**kw):
            self.events.append(kw)
            if kw.get('endProgress'):self.open=False;return
            if kw.get('edit'):self.status=kw['status'];return
            if kw.get('query'):return self.cancel_at and self.status.startswith(self.cancel_at)
            self.open=self.can_open;self.status='Starting';return self.can_open
        self.ns.update(time=types.SimpleNamespace(monotonic=now),cmds=types.SimpleNamespace(progressWindow=window))
    def plan(self):return self.ns['plan']({'source':'s','target':'t','method':'surface'},progress=True)
    def assert_closed(self):
        self.assertFalse(self.open);self.assertFalse(self.ns['_active_plan'])
        self.assertEqual(sum(bool(e.get('endProgress')) for e in self.events),1)
    def test_success_covers_geometry_build_sampling_and_preflight(self):
        def guard(*args,**kw):
            self.assertTrue(self.open);self.assertTrue(self.status.startswith('Checking target'))
            kw['check']();self.guard.append(args)
        self.ns['writable']=guard
        self.plan();self.assert_closed()
        statuses=[e['status'] for e in self.events if e.get('edit')]
        for stage in ('Reading source','Reading target','Matching influences','Preparing source','Building source','Sampling target','Checking target','Preview calculation complete'):
            self.assertTrue(any(s.startswith(stage) for s in statuses),stage)
        self.assertEqual(self.target['weights'],[0,1,0,1,0,1])
    def test_cancel_each_phase_cleans_up_without_weight_writes(self):
        for stage in ('Reading source','Reading target','Matching influences','Evaluating source','Evaluating target','Preparing source','Building source','Reading DQ','Sampling target','Checking target'):
            with self.subTest(stage=stage):
                self.setUp();self.cancel_at=stage
                with self.assertRaisesRegex(RuntimeError,'cancelled before any weight writes'):self.plan()
                self.assert_closed();self.assertEqual(self.target['weights'],[0,1,0,1,0,1]);self.assertEqual(self.guard,[])
    def test_context_failure_also_closes_window(self):
        self.ns['context']=mock.Mock(side_effect=ValueError('scene read failed'))
        with self.assertRaisesRegex(ValueError,'scene read failed'):self.plan()
        self.assert_closed()
    def test_preflight_failure_closes_window(self):
        self.ns['writable']=mock.Mock(side_effect=ValueError('locked weights'))
        with self.assertRaisesRegex(ValueError,'locked weights'):self.plan()
        self.assert_closed()
    def test_keyboard_interrupt_releases_window(self):
        self.ns['sample_geometry']=mock.Mock(side_effect=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):self.plan()
        self.assert_closed()
    def test_existing_foreign_window_is_not_closed_or_edited(self):
        self.can_open=False
        with self.assertRaisesRegex(RuntimeError,'Maya could not create a progress window'):self.plan()
        self.assertEqual(len(self.events),1);self.assertFalse(self.ns['_active_plan']);self.assertEqual(self.samples,[])
    def test_reentrant_plan_does_not_close_outer_window(self):
        def sample(*args,**kwargs):
            with self.assertRaisesRegex(RuntimeError,'already calculating'):self.plan()
            self.assertTrue(self.open);raise ValueError('outer stopped')
        self.ns['sample_geometry']=sample
        with self.assertRaisesRegex(ValueError,'outer stopped'):self.plan()
        self.assert_closed()
    def test_cleanup_error_still_releases_operation_guard(self):
        original=self.ns['cmds'].progressWindow
        def window(**kw):
            result=original(**kw)
            if kw.get('endProgress'):raise RuntimeError('close failed')
            return result
        self.ns['cmds'].progressWindow=window
        with self.assertRaisesRegex(RuntimeError,'close failed'):self.plan()
        self.assertFalse(self.ns['_active_plan'])
    def test_progress_updates_are_throttled(self):
        self.ns['time']=types.SimpleNamespace(monotonic=lambda:1.)
        monitor=self.ns['PlanProgress'](True);monitor.start();monitor.stage('Building',40)
        for _ in range(1000):monitor.check()
        monitor.close()
        self.assertEqual(sum(bool(e.get('edit')) for e in self.events),1)


class CooperativeCancelTests(unittest.TestCase):
    def stop(self):raise RuntimeError('cancel requested')
    def test_triangle_preparation_is_cancellable(self):
        with self.assertRaisesRegex(RuntimeError,'cancel requested'):
            core.prepare_triangles([(0,0,0),(1,0,0),(0,1,0)],[(0,(0,1,2))],check=self.stop)
    def test_tree_build_is_cancellable(self):
        records,_=core.prepare_triangles([(0,0,0),(1,0,0),(0,1,0)],[(0,(0,1,2))])
        with self.assertRaisesRegex(RuntimeError,'cancel requested'):core.SurfaceIndex(records,check=self.stop)
    def test_single_nearest_query_is_cancellable(self):
        records,_=core.prepare_triangles([(0,0,0),(1,0,0),(0,1,0)],[(0,(0,1,2))])
        tree=core.SurfaceIndex(records);tree.check=self.stop
        with self.assertRaisesRegex(RuntimeError,'cancel requested'):tree.nearest((.2,.2,0))
    def test_influence_matching_is_cancellable(self):
        records=[{'uuid':'a','path':'|a'}]
        with self.assertRaisesRegex(RuntimeError,'cancel requested'):core.resolve_influences(records,records,check=self.stop)


class PreflightCancelTests(unittest.TestCase):
    def test_cancellation_is_checked_before_bulk_target_inspection(self):
        tree=ast.parse(Path(__file__).with_name('copy_skinning_plugin.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='writable')
        plug=types.SimpleNamespace(isLocked=False,isDestination=False)
        plug.elementByLogicalIndex=lambda *_:plug;plug.child=lambda *_:plug
        plug.getExistingArrayAttributeIndices=lambda:[0,1]
        ctx={'skin':'skin','shape':'mesh','influences':[],
             'fn':types.SimpleNamespace(findPlug=lambda *_:plug)}
        ns={'cmds':types.SimpleNamespace(referenceQuery=lambda *a,**kw:False,listConnections=lambda *a,**kw:[],getAttr=lambda *_:False),
            'om':types.SimpleNamespace(MFnDependencyNode=lambda *_:types.SimpleNamespace(isLocked=False)),'object_':lambda name:name}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<preflight cancellation>','exec'),ns)
        calls=[]
        def check():
            calls.append(1)
            if len(calls)==2:raise RuntimeError('cancel vertex inspection')
        with self.assertRaisesRegex(RuntimeError,'cancel vertex inspection'):ns['writable'](ctx,[0,1,2],[],check=check)
        self.assertEqual(len(calls),2)


class BusyActionTests(unittest.TestCase):
    def setUp(self):
        from functools import wraps
        tree=ast.parse(Path(__file__).with_name('copy_skinning_ui.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='busy_action')
        ns={'wraps':wraps,'shiboken':types.SimpleNamespace(isValid=lambda widget:True)}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<UI action guard>','exec'),ns)
        self.decorate=ns['busy_action'];self.widget=types.SimpleNamespace(_busy=False,enabled=True)
        self.widget.isEnabled=lambda:self.widget.enabled
        self.widget.setEnabled=lambda value:setattr(self.widget,'enabled',value)
    def test_reentrant_click_is_ignored_and_panel_restored(self):
        calls=[]
        @self.decorate
        def action(widget):
            calls.append(1);self.assertFalse(widget.enabled);action(widget)
        action(self.widget,False)
        self.assertEqual(calls,[1]);self.assertTrue(self.widget.enabled);self.assertFalse(self.widget._busy)
    def test_failure_restores_enabled_state(self):
        @self.decorate
        def action(widget):raise ValueError('failed')
        with self.assertRaises(ValueError):action(self.widget)
        self.assertTrue(self.widget.enabled);self.assertFalse(self.widget._busy)
    def test_previously_disabled_panel_stays_disabled(self):
        self.widget.enabled=False
        self.decorate(lambda widget:None)(self.widget)
        self.assertFalse(self.widget.enabled);self.assertFalse(self.widget._busy)


class GeometrySamplingTests(unittest.TestCase):
    """Unit-test mode/transform routing, not Maya's native mesh evaluation."""
    def setUp(self):
        class Point:
            def __init__(self,p):self.p=p
            def __mul__(self,m):return Point(tuple(self.p[i]*m[0][i]+m[1][i] for i in range(3)))
            def __iter__(self):return iter(self.p)
        class Mesh:
            def __init__(self,points,driven=False,sig='t'):self.points=points;self.driven=driven;self.sig=sig
            def getPoints(self,*_):return [Point(p) for p in self.points]
            def getTriangles(self):return [1],[0,1,2]
            def object(self):return self
            def hasFn(self,*_):return True
            def findPlug(self,*_):return types.SimpleNamespace(isDestination=self.driven)
        class Dag:
            def __init__(self,mesh,matrix):self.mesh=mesh;self.matrix=matrix
            def node(self):return self.mesh
            def inclusiveMatrix(self):
                class Matrix:
                    def __init__(matrix,pair):matrix.pair=pair
                    def __getitem__(matrix,i):return matrix.pair[i]
                    def __iter__(matrix):
                        scale,offset=matrix.pair
                        return iter([scale[0],0,0,0,0,scale[1],0,0,0,0,scale[2],0,*offset,1])
                return Matrix(self.matrix)
        self.Mesh=Mesh;self.Dag=Dag
        self.original=Mesh([(0,0,0),(1,0,0),(0,1,0)])
        current=Mesh([(0,0,2),(1,0,2),(0,1,2)])
        self.ctx={'mesh':current,'original':self.original,'dag':Dag(current,((2,3,4),(10,20,30))),'topology':'t',
                  'uuid':'mesh','skin_uuid':'skin','fn':object(),'input_index':0}
        self.override=Dag(Mesh([(1,0,0),(2,0,0),(1,1,0)]),((1,1,1),(-1,-2,-3)))
        node=next(n for n in ast.parse(Path(__file__).with_name('copy_skinning_plugin.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='sample_geometry')
        om=types.SimpleNamespace(MSpace=types.SimpleNamespace(kObject=0),MFn=types.SimpleNamespace(kDagNode=1),MFnMesh=lambda dag:dag.mesh,
            MFnDependencyNode=lambda node:types.SimpleNamespace(uuid=lambda:types.SimpleNamespace(asString=lambda:'override')))
        self.cache=caching.CacheService()
        self.ns={'om':om,'math':math,'signature':lambda mesh:mesh.sig,'mesh_path':lambda name:self.override,
            'cache_service':lambda:self.cache,'skin_input':lambda fn,index:(self.original,'skin.input[0].inputGeometry')}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<geometry modes>','exec'),self.ns)
    def test_current_points_use_world_transform_after_deformation(self):
        points,_=self.ns['sample_geometry'](self.ctx,'current');self.assertEqual(points[0],(10,20,38));self.assertEqual(points[1],(12,20,38))
    def test_base_uses_original_positions_and_visible_mesh_transform(self):
        points,_=self.ns['sample_geometry'](self.ctx,'base');self.assertEqual(points[0],(10,20,30));self.assertEqual(points[2],(10,23,30))
    def test_driven_pre_skin_input_is_sampled_automatically(self):
        self.original.driven=True
        points,_=self.ns['sample_geometry'](self.ctx,'base');self.assertEqual(points[0],(10,20,30))
    def test_explicit_base_uses_its_own_transform(self):
        self.original.driven=True
        points,_=self.ns['sample_geometry'](self.ctx,'base','explicit');self.assertEqual(points[0],(0,-2,-3))
    def test_override_topology_must_match(self):
        self.override.mesh.sig='other'
        with self.assertRaisesRegex(ValueError,'Base mesh must preserve'):self.ns['sample_geometry'](self.ctx,'base','explicit')


class UndoTests(unittest.TestCase):
    def setUp(self):
        tree=ast.parse(Path(__file__).with_name('copy_skinning_plugin.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='CopyCommand')
        ns={'om':types.SimpleNamespace(MPxCommand=object)};exec(compile(ast.Module(body=[node],type_ignores=[]),'<copy command>','exec'),ns)
        self.command=ns['CopyCommand']();self.log=[]
    def test_redo_and_undo_write_matching_snapshots(self):
        self.command.write=self.log.append;self.command.redoIt();self.command.undoIt();self.assertEqual(self.log,['after','before'])
    def test_failed_redo_restores_before(self):
        def write(key):
            self.log.append(key)
            if key=='after':raise RuntimeError('native setter failure')
        self.command.write=write
        with self.assertRaises(RuntimeError):self.command.redoIt()
        self.assertEqual(self.log,['after','before'])
    def test_failed_undo_restores_after(self):
        def write(key):
            self.log.append(key)
            if key=='before':raise RuntimeError('native setter failure')
        self.command.write=write
        with self.assertRaises(RuntimeError):self.command.undoIt()
        self.assertEqual(self.log,['before','after'])


if __name__=='__main__':unittest.main(verbosity=2)
