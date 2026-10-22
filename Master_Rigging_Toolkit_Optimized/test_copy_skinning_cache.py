"""Cache/invalidation regressions. Native Maya evaluation is covered by a separate smoke test."""
import ast
from contextlib import contextmanager
from pathlib import Path
import sys
import types
import unittest
from unittest import mock
import copy_skinning_cache as caching
import copy_skinning_core as core
import test_copy_skinning as regression


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.cache=caching.CacheService();self.points=[(0,0,0),(2,0,0),(0,2,0)];self.triangles=[(0,(0,1,2))]
    def surface(self,**kw):return self.cache.surface(core,self.points,self.triangles,kw.get('mask'),kw.get('threshold',.001))
    def test_identical_surface_reuses_index(self):
        a=self.surface();b=self.surface();self.assertIs(a[0],b[0]);self.assertTrue(b[-1]);self.assertEqual(self.cache.builds,1)
    def test_source_positions_invalidate_surface(self):
        a=self.surface();self.points[0]=(0,0,1);b=self.surface();self.assertIsNot(a[0],b[0]);self.assertEqual(self.cache.builds,2)
    def test_triangle_connectivity_and_face_restrictions_invalidate(self):
        a=self.surface();self.triangles=[(5,(0,2,1))];b=self.surface();self.assertIsNot(a[0],b[0])
    def test_source_mask_and_threshold_are_part_of_surface_key(self):
        a=self.surface(mask=[1,1,1]);b=self.surface(mask=[.5,.5,.5]);c=self.surface(mask=[1,1,1],threshold=.5)
        self.assertNotEqual(a[-2],b[-2]);self.assertNotEqual(a[-2],c[-2]);self.assertEqual(self.cache.builds,3)
    def test_cached_index_does_not_retain_old_progress_callback(self):
        callback=mock.Mock();result=self.cache.surface(core,self.points,self.triangles,None,.001,check=callback)
        self.assertIsNone(result[0].check);callback.assert_called()
    def test_lru_evicts_least_recent_by_size(self):
        cache=caching.CacheService(max_bytes=10);cache.put('a','a',4);cache.put('b','b',4);cache.get('a');cache.put('c','c',4)
        self.assertIsNone(cache.get('b'));self.assertEqual(cache.get('a'),'a');self.assertLessEqual(cache.bytes,10)
    def test_item_count_is_bounded(self):
        cache=caching.CacheService(max_items=2)
        for i in range(10):cache.put(i,i,1)
        self.assertEqual(len(cache.entries),2)
    def test_oversize_entries_are_not_retained(self):
        cache=caching.CacheService(max_bytes=10);self.assertFalse(cache.put('big',object(),11));self.assertEqual(cache.bytes,0)
    def test_replacing_entry_updates_budget(self):
        cache=caching.CacheService(max_bytes=10);cache.put('a',1,4);cache.put('a',2,7);self.assertEqual(cache.bytes,7);self.assertEqual(cache.get('a'),2)
    def test_clear_resets_payload_and_counters(self):
        self.surface();self.surface();self.cache.clear();self.assertEqual(self.cache.stats(),dict(items=0,estimated_bytes=0,hits=0,misses=0,surface_builds=0,nearest_queries=0,reused_queries=0))
    def test_correspondence_key_includes_source_target_scope_and_distance(self):
        keys=[self.cache.correspondence(*args)[0] for args in (('s','t',[0,1],0),('other','t',[0,1],0),('s','other',[0,1],0),('s','t',[1,2],0),('s','t',[0,1],1))]
        self.assertEqual(len(set(keys)),len(keys))
    def test_unqueried_and_confirmed_miss_remain_distinct(self):
        key,hits,_,cost=self.cache.correspondence('s','t',[0,1],0);self.assertIs(hits[0],False);hits[1]=None;self.cache.put(key,hits,cost)
        _,again,reused,_=self.cache.correspondence('s','t',[0,1],0);self.assertTrue(reused);self.assertIs(again[0],False);self.assertIsNone(again[1])
    def test_cache_validation_hashes_are_cancellable(self):
        def cancel():raise RuntimeError('cancel hashing')
        with self.assertRaisesRegex(RuntimeError,'cancel hashing'):caching.fingerprint(range(10000),'q',cancel)


class GeometryCacheTests(unittest.TestCase):
    def setUp(self):regression.GeometrySamplingTests.setUp(self)
    def sample(self,mode='base',override=''):return self.ns['sample_geometry'](self.ctx,mode,override)
    def test_unchanged_geometry_reuses_world_points_and_triangles(self):
        a=self.sample();b=self.sample();self.assertIs(a,b);self.assertEqual(self.cache.hits,1)
    def test_current_vertex_change_rebuilds_only_current_snapshot(self):
        base=self.sample();a=self.sample('current');self.ctx['mesh'].points[0]=(0,0,4)
        b=self.sample('current');self.assertIsNot(a,b);self.assertEqual(b[0][0],(10,20,46));self.assertIs(base,self.sample())
    def test_upstream_pre_skin_change_refreshes_base(self):
        a=self.sample();self.original.points[0]=(0,0,1);b=self.sample();self.assertIsNot(a,b);self.assertEqual(b[0][0],(10,20,34))
    def test_world_matrix_change_invalidates_world_positions(self):
        a=self.sample();self.ctx['dag'].matrix=((2,3,4),(11,20,30));b=self.sample();self.assertIsNot(a,b);self.assertEqual(b[0][0][0],11)
    def test_rebinding_same_mesh_uuid_invalidates_skin_identity(self):
        a=self.sample();self.ctx['skin_uuid']='replacement-skin';self.assertIsNot(a,self.sample())
    def test_topology_token_is_validated(self):
        a=self.sample('current');self.ctx['topology']='new';self.assertIsNot(a,self.sample('current'))
    def test_explicit_override_changes_are_detected(self):
        a=self.sample('base','mesh');self.override.mesh.points[0]=(2,0,0);b=self.sample('base','mesh');self.assertIsNot(a,b)
    def test_current_mode_ignores_override_fields(self):
        a=self.sample('current');b=self.sample('current','mesh');self.assertIs(a,b)
    def test_nonfinite_positions_are_rejected_before_cache(self):
        self.original.points[0]=(float('nan'),0,0)
        with self.assertRaisesRegex(ValueError,'Nonfinite'):self.sample()
        self.assertFalse(self.cache.entries)


class CorrespondenceTests(unittest.TestCase):
    def setUp(self):regression.PlanTests.setUp(self)
    def plan(self,**kw):return regression.PlanTests.plan(self,**kw)
    def regions(self):return regression.PlanTests.regions(self)
    def test_preview_then_copy_plan_reuses_nearest_queries(self):
        a=self.plan();queries=self.cache.queries;b=self.plan()
        self.assertEqual(a['after'],b['after']);self.assertEqual(self.cache.queries,queries);self.assertTrue(b['summary']['surface_cache_reused']);self.assertTrue(b['summary']['correspondence_cache_reused'])
    def test_painted_source_weights_are_read_fresh_with_cached_hits(self):
        self.plan();queries=self.cache.queries;self.source['weights']=[0,1]*3;b=self.plan()
        self.assertEqual(b['vertices'],[]);self.assertEqual(self.cache.queries,queries);self.assertGreater(self.cache.reused_queries,0)
    def test_target_weights_are_fresh_for_before_snapshot(self):
        self.plan();queries=self.cache.queries;self.target['weights']=[1,0]*3;b=self.plan()
        self.assertEqual(b['before'][:2],[1,0]);self.assertEqual(self.cache.queries,queries)
    def test_black_target_mask_does_not_cache_false_misses(self):
        self.masks['target']=[0,0,0];self.plan(method='region',source_mask=True,target_mask=True);self.assertEqual(self.cache.queries,0)
        self.masks['target']=[1,1,1];result=self.plan(method='region',source_mask=True,target_mask=True)
        self.assertEqual(result['vertices'],[0,1]);self.assertEqual(self.cache.queries,3)
    def test_zero_strength_does_not_poison_later_copy(self):
        self.plan(opacity=0);self.assertEqual(self.cache.queries,0);result=self.plan(opacity=1);self.assertEqual(result['vertices'],[0,1])
    def test_source_mask_change_rebuilds_surface_and_alpha(self):
        self.plan(method='region',source_mask=True,target_mask=True);self.masks['source']=[.5,.5,.5]
        result=self.plan(method='region',source_mask=True,target_mask=True)
        self.assertEqual(self.cache.builds,2);self.assertAlmostEqual(result['after'][0],.25)
    def test_max_distance_change_recomputes_misses(self):
        a=self.plan(max_distance=.5);b=self.plan(max_distance=0)
        self.assertEqual(a['summary']['distance_skips'],2);self.assertEqual(b['summary']['distance_skips'],0);self.assertEqual(self.cache.builds,1)
    def test_target_region_change_recomputes_component_mapping(self):
        values=self.regions();self.plan(method='region',**values);values['target_region']['vertices']=[1]
        result=self.plan(method='region',**values);self.assertEqual(result['vertices'],[1]);self.assertFalse(result['summary']['correspondence_cache_reused'])
    def test_manual_joint_mapping_change_uses_live_columns(self):
        self.plan();queries=self.cache.queries;result=self.plan(manual_mapping={'a':'b','b':'a'})
        self.assertEqual(result['vertices'],[0,2]);self.assertEqual(self.cache.queries,queries)
    def test_failed_preflight_does_not_store_new_correspondence(self):
        self.ns['writable']=mock.Mock(side_effect=ValueError('locked'))
        with self.assertRaises(ValueError):self.plan()
        self.assertFalse(any(key[0]=='hits' for key in self.cache.entries))


class InputGeometryTests(unittest.TestCase):
    def setUp(self):
        tree=ast.parse(Path(__file__).with_name('copy_skinning_plugin.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='skin_input')
        self.data=types.SimpleNamespace(isNull=lambda:False);self.seen=[]
        def child(name):return types.SimpleNamespace(attribute=lambda:name,asMObject=lambda:self.data,name=lambda:'skin.input[7].'+name)
        self.children=[child('groupId'),child('inputGeometry')]
        element=types.SimpleNamespace(numChildren=lambda:len(self.children),child=lambda i:self.children[i])
        def indexed(i):self.seen.append(i);return element
        self.fn=types.SimpleNamespace(findPlug=lambda name,networked:types.SimpleNamespace(elementByLogicalIndex=indexed))
        ns={'om':types.SimpleNamespace(MFnAttribute=lambda name:types.SimpleNamespace(name=name),MFnMesh=lambda data:('mesh-data',data))}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<skin input resolver>','exec'),ns);self.resolve=ns['skin_input']
    def test_resolves_evaluated_mesh_data_at_output_logical_index(self):
        mesh,name=self.resolve(self.fn,7);self.assertEqual(self.seen,[7]);self.assertIs(mesh[1],self.data);self.assertEqual(name,'skin.input[7].inputGeometry')
    def test_does_not_assume_input_geometry_is_first_child(self):
        self.assertEqual(self.resolve(self.fn,7)[0][0],'mesh-data')
    def test_missing_input_data_has_clear_error(self):
        self.data.isNull=lambda:True
        with self.assertRaisesRegex(ValueError,'no polygon mesh data'):self.resolve(self.fn,7)
    def test_missing_input_geometry_child_has_clear_error(self):
        self.children=self.children[:1]
        with self.assertRaisesRegex(ValueError,'Cannot resolve'):self.resolve(self.fn,7)


class SharedServiceTests(unittest.TestCase):
    def test_plugin_command_and_panel_helper_share_one_service(self):
        fixture=regression.PluginLoaderTests();fixture.setUp();name='_rtk_copy_skin_cache_043'
        with mock.patch.dict(sys.modules):
            sys.modules.pop(name,None);first=fixture.execute();second=fixture.execute()
            a=first['cache_service']();b=second['cache_service']();self.assertIs(a,b)
            a.put('probe','shared',1);self.assertEqual(b.get('probe'),'shared')
            first['clear_cache']();self.assertEqual(b.stats()['items'],0)


class LoadMeshTests(unittest.TestCase):
    def setUp(self):
        tree=ast.parse(Path(__file__).with_name('copy_skinning_plugin.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='load_mesh')
        self.cache=caching.CacheService();self.reads=[];self.samples=[];self.closed=False
        ctx={'shape':'|mesh|shape','uuid':'mesh','skin':'skin','count':3,'width':2,'input_plug':'skin.input[7].inputGeometry'}
        def context(name,read_weights=True,check=None):self.reads.append(read_weights);return ctx
        def sample(ctx,mode,override,check=None):self.samples.append((mode,override));return [(0,0,0),(1,0,0),(0,1,0)],[(0,(0,1,2))]
        @contextmanager
        def planning(progress,max_seconds=0,**kwargs):
            try:yield types.SimpleNamespace(stage=lambda *a:None,check=lambda:None)
            finally:self.closed=True
        ns={'mesh_path':lambda name:None,'mesh_input':lambda dag:types.SimpleNamespace(isDestination=True),'context':context,'sample_geometry':sample,'cache_service':lambda:self.cache,'cache_stats':self.cache.stats,'core':core,'planning':planning}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<load mesh cache warmup>','exec'),ns);self.load=ns['load_mesh']
    def test_source_load_warms_index_without_reading_weights(self):
        info=self.load('mesh',source=True);self.assertEqual(self.reads,[False]);self.assertEqual(self.cache.builds,1)
        self.assertEqual(info['input_geometry'],'skin.input[7].inputGeometry');self.assertTrue(self.closed)
    def test_target_load_does_not_build_unused_source_index(self):
        self.load('mesh');self.assertEqual(self.reads,[False]);self.assertEqual(self.cache.builds,0);self.assertEqual(len(self.samples),1)
    def test_id_mode_load_does_not_sample_geometry(self):
        self.load('mesh',source=True,method='id');self.assertEqual(self.samples,[]);self.assertEqual(self.cache.builds,0)
    def test_oversize_source_is_validated_without_warming_unretainable_index(self):
        self.cache.max_bytes=1;self.load('mesh',source=True);self.assertEqual(self.cache.builds,0);self.assertEqual(len(self.samples),1)


if __name__=='__main__':unittest.main(verbosity=2)
