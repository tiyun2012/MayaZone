"""Lossless archives, validation, mapping and projection; no Maya runtime."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile
import layer_skin_core as core
import layer_skin_io as io


def snapshot():
    return dict(count=3,topology=io.topology(3,[3],[0,1,2]),
        influences=[dict(uuid='a',path='|old:jointA',position=[0.,0.,0.]),dict(uuid='b',path='|old:jointB',position=[1.,0.,0.])],
        weights=[1.,0.,0.,1.,1.,0.],points=[(0.,0.,0.),(1.,0.,0.),(0.,1.,0.)],triangles=[(0,1,2)],
        dq=[0.,.5,1.],skinning_method=2,geometry='base')


class FileTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/'测试 skin.rtkskin';self.data=snapshot()
    def rewrite(self,change):
        with zipfile.ZipFile(self.path) as z:parts={name:z.read(name) for name in z.namelist()}
        change(parts)
        with zipfile.ZipFile(self.path,'w') as z:
            for name,value in parts.items():z.writestr(name,value)
    def test_bit_exact_roundtrip_preserves_tiny_weights_geometry_and_dq(self):
        self.data['weights']=[1.-1e-15,1e-15,.123456789012345,.876543210987655,1.,0.]
        result=io.write(self.path,self.data);actual=io.read(self.path)
        for key in ('weights','points','triangles','dq','influences'):self.assertEqual(actual[key],self.data[key])
        self.assertEqual(result['nonzero'],5);self.assertEqual(actual['skinning_method'],2)
    def test_optional_geometry_and_dq_absent_still_allow_id_import(self):
        for key in ('points','triangles','dq'):self.data.pop(key)
        io.write(self.path,self.data);actual=io.read(self.path)
        self.assertNotIn('points',actual);self.assertIsNone(io.project(actual,actual)['dq'])
        with self.assertRaisesRegex(ValueError,'no saved surface'):io.project(actual,dict(count=1,points=[(0,0,0)]),'surface')
    def test_export_never_attaches_layer_payload_or_arbitrary_extra_data(self):
        self.data['layers']=[dict(secret='authoring')];self.data['reference']={'arbitrary':'data'}
        io.write(self.path,self.data);actual=io.read(self.path)
        self.assertNotIn('layers',actual);self.assertNotIn('reference',actual)
    def test_overwrite_is_explicit_and_cancelled_atomic_export_keeps_previous_file(self):
        self.path.write_bytes(b'previous backup')
        with self.assertRaises(FileExistsError):io.write(self.path,self.data)
        def cancel():
            if any(zipfile.is_zipfile(p) for p in Path(self.directory.name).glob('.rtkskin_*.tmp')):raise RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError,'cancelled'):io.write(self.path,self.data,overwrite=True,check=cancel)
        self.assertEqual(self.path.read_bytes(),b'previous backup');self.assertEqual(list(Path(self.directory.name).glob('*.tmp')),[])
    def test_validation_rejects_invalid_dimensions_normalization_and_nonfinite_values(self):
        cases=[dict(count=True),dict(count=0),dict(weights=[0.]*6),dict(weights=[float('nan')]*6),dict(weights=[-.1,1.1]*3),
            dict(dq=[0,2,0]),dict(topology='bad'),dict(skinning_method=True),dict(points=[(0,0,0)]),dict(triangles=[(0,1,10)])]
        for changes in cases:
            with self.subTest(changes=changes),self.assertRaises(ValueError):io.validate(dict(self.data,**changes))
        invalid=copy.deepcopy(self.data);invalid['influences'][1]['uuid']='a'
        with self.assertRaisesRegex(ValueError,'Duplicate'):io.validate(invalid)
    def test_checksum_mismatch_rejected(self):
        io.write(self.path,self.data)
        self.rewrite(lambda parts:parts.__setitem__('weights.bin',b'\x00'*len(parts['weights.bin'])))
        with self.assertRaisesRegex(ValueError,'checksum'):io.read(self.path)
    def test_truncated_array_rejected_before_array_allocation(self):
        io.write(self.path,self.data);self.rewrite(lambda p:p.__setitem__('columns.bin',p['columns.bin'][:-1]))
        with self.assertRaisesRegex(ValueError,'size mismatch'):io.read(self.path)
    def test_unknown_version_or_geometry_space_rejected(self):
        for key,value in [('version',2),('version',True),('point_space','world'),('linear_unit','meter')]:
            io.write(self.path,self.data,overwrite=True)
            def change(parts):
                meta=json.loads(parts['manifest.json']);meta[key]=value;parts['manifest.json']=json.dumps(meta).encode()
            self.rewrite(change)
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):io.read(self.path)
    def test_archive_members_are_not_extracted_and_unknown_members_rejected(self):
        io.write(self.path,self.data);self.rewrite(lambda p:p.__setitem__('../escape.py',b'not executed'))
        with self.assertRaisesRegex(ValueError,'Unexpected'):io.read(self.path)
        self.assertFalse((Path(self.directory.name).parent/'escape.py').exists())
    def test_archive_size_budget_is_checked_before_reading_payload(self):
        io.write(self.path,self.data)
        with mock.patch.object(io,'MAX_BYTES',10),self.assertRaisesRegex(ValueError,'size limit'):io.read(self.path)
    def test_duplicate_members_are_rejected(self):
        io.write(self.path,self.data)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(self.path,'a') as z:z.writestr('manifest.json',b'{}')
        with self.assertRaisesRegex(ValueError,'duplicate'):io.read(self.path)
    def test_read_and_write_checks_can_cancel_without_partial_destination(self):
        with self.assertRaisesRegex(RuntimeError,'stop'):
            io.write(self.path,self.data,check=lambda:(_ for _ in ()).throw(RuntimeError('stop')))
        self.assertFalse(self.path.exists())
        io.write(self.path,self.data)
        with self.assertRaisesRegex(RuntimeError,'stop'):
            io.read(self.path,check=lambda:(_ for _ in ()).throw(RuntimeError('stop')))


class TransferTests(unittest.TestCase):
    def setUp(self):self.data=snapshot()
    def test_id_checks_count_and_topology_instead_of_count_alone(self):
        self.assertEqual(io.project(self.data,self.data)['weights'],self.data['weights'])
        for target in (dict(count=2,topology=self.data['topology']),dict(count=3,topology='0'*64)):
            with self.assertRaisesRegex(ValueError,'Vertex ID'):io.project(self.data,target)
    def test_surface_interpolates_weights_and_dq_at_triangle_interior(self):
        result=io.project(self.data,dict(count=1,points=[(.25,.25,0.)]),'surface')
        self.assertEqual(result['weights'],[.75,.25]);self.assertAlmostEqual(result['dq'][0],.375)
        self.assertEqual(result['max_distance'],0.)
    def test_surface_supports_different_vertex_count_and_max_distance(self):
        target=dict(count=2,points=[(1,0,0),(0,1,.2)])
        result=io.project(self.data,target,'surface',.3)
        self.assertEqual(result['weights'],[0,1,1,0]);self.assertAlmostEqual(result['max_distance'],.2)
        with self.assertRaisesRegex(ValueError,'vertex 1'):io.project(self.data,target,'surface',.1)
    def test_sparse_unused_source_influence_does_not_require_joint_mapping(self):
        data=copy.deepcopy(self.data);data['influences'].append(dict(uuid='unused',path='|absent'))
        data['weights']=[v for i in range(3) for v in self.data['weights'][i*2:i*2+2]+[0.]]
        candidates=[dict(uuid='a2',path='|new:jointA',position=[0,0,0]),dict(uuid='b2',path='|new:jointB',position=[1,0,0])]
        report=io.map_joints(data,candidates);self.assertTrue(report['complete']);self.assertEqual(len(report['rows']),2)
    def test_name_namespace_search_replace_and_small_edit_mapping(self):
        candidates=[dict(uuid='a2',path='|new:jointAA',position=[0,0,0]),dict(uuid='b2',path='|new:jointBA',position=[1,0,0])]
        report=io.map_joints(self.data,candidates);self.assertTrue(report['complete'])
        self.assertTrue(all('distance' in r['method'] for r in report['rows']))
        candidates=[dict(uuid='a2',path='|new:ctrlA'),dict(uuid='b2',path='|new:ctrlB')]
        report=io.map_joints(self.data,candidates,dict(search='joint',replace='ctrl',distance=False,max_edits=0))
        self.assertTrue(report['complete'])
    def test_ambiguous_mapping_requires_manual_and_manual_conflicts_remain_blocked(self):
        candidates=[dict(uuid='a1',path='|x:jointA'),dict(uuid='a2',path='|y:jointA'),dict(uuid='b2',path='|new:jointB')]
        report=io.map_joints(self.data,candidates,dict(distance=False,max_edits=0));self.assertFalse(report['complete'])
        report=io.map_joints(self.data,candidates,manual={'a':'a2'});self.assertTrue(report['complete']);self.assertEqual(report['mapping'],[1,2])
        report=io.map_joints(self.data,candidates,manual={'a':'a2','b':'a2'});self.assertFalse(report['complete'])
    def test_import_creates_full_coverage_top_layer_without_mutating_previous_layers(self):
        state=core.create([1,0]*3,3,['a','b'],'topology');state=core.edit(state,'add',dict(name='Old'))
        layer=state['layers'][0]['id'];state=core.edit(state,'paint',dict(layer=layer,mode='mask',values={'0':0.}))
        before=copy.deepcopy(state);payload=dict(source_ids=['sourceB','sourceA'],mapping=['b','a'],weights=[1,0,.3,.7,0,1],name='File')
        result=io.import_state(core,state,dict(ids=['a','b'],count=3),payload)
        self.assertEqual(state,before);self.assertEqual(result['layers'][0],before['layers'][0]);self.assertEqual(result['base'],before['base'])
        self.assertEqual(core.composite(result),[0,1,.7,.3,1,0]);self.assertEqual(result['layers'][-1]['name'],'File')
    def test_import_mapping_handles_extra_target_influences_and_rejects_weighted_unmapped(self):
        state=core.create([1,0,0]*3,3,['a','b','extra'],'topology')
        payload=dict(source_ids=['sA','sB'],mapping=['a','b'],weights=self.data['weights'])
        result=io.import_state(core,state,dict(ids=['a','b','extra'],count=3),payload)
        self.assertEqual(core.composite(result),[1,0,0,0,1,0,1,0,0])
        for mapping in (['a',None],['a','a'],['a','removed']):
            with self.subTest(mapping=mapping),self.assertRaises(ValueError):io.import_state(core,state,dict(ids=['a','b','extra'],count=3),dict(payload,mapping=mapping))
    def test_cancelled_surface_planning_does_not_mutate_source_snapshot(self):
        before=copy.deepcopy(self.data)
        with self.assertRaisesRegex(RuntimeError,'stop'):io.project(self.data,dict(count=1,points=[(0,0,0)]),'surface',check=lambda:(_ for _ in ()).throw(RuntimeError('stop')))
        self.assertEqual(self.data,before)
